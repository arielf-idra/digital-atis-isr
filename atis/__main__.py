"""Capture one ATIS broadcast and write it as JSON.

    python -m atis LLHA --out data
"""

import argparse
import json
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import audio, consensus, metar, parse, transcribe
from .stations import STATIONS

HISTORY_LIMIT = 96
MAX_LETTER_SPANS = 4          # start + end mention of two loops is plenty and keeps a cycle short
CHECK_INTERVAL_MIN = 3
STALE_AFTER_MIN = 15
DISCLAIMER = (
    "UNOFFICIAL - NOT FOR OPERATIONAL USE. Automatic speech-to-text transcription of the "
    "broadcast ATIS. It may be wrong, incomplete, late or unavailable. It is not approved by, "
    "or affiliated with, any air navigation service provider or airport. Always obtain the "
    "official ATIS on frequency before flight. Use entirely at your own risk."
)


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def to_mp3(wav: Path, mp3: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav),
         "-ac", "1", "-ar", "16000", "-b:a", "32k", str(mp3)],
        check=True, timeout=60,
    )


def issued_at(hhmm: str | None, heard: datetime) -> datetime | None:
    """The ATIS "valid from HHMM" as a full UTC time (the most recent one not after it was heard)."""
    if not hhmm:
        return None
    t = heard.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:]), second=0)
    return t - timedelta(days=1) if t > heard + timedelta(minutes=5) else t


def capture(station, wav: Path, workdir: Path) -> dict:
    samples = audio.load(wav)
    loops = audio.split_loops(samples)
    complete = bool(loops)
    if not loops:
        # No clean loop boundaries (e.g. the recording changed format); use it all.
        loops = [(0.0, len(samples) / audio.SAMPLE_RATE)]

    transcripts, parsed, clips, letter_scores = [], [], [], []
    for start, end in loops:
        clip = samples[int(start * audio.SAMPLE_RATE):int(end * audio.SAMPLE_RATE)]
        text, prob, words = transcribe.transcribe(clip, station)
        transcripts.append((text, prob))
        parsed.append(parse.parse(text, station.runways))
        clips.append(clip)
        if len(letter_scores) < MAX_LETTER_SPANS:
            try:
                spans = transcribe.letter_spans(words, len(clip) / audio.SAMPLE_RATE)
                letter_scores += transcribe.score_letters(clip, spans[:MAX_LETTER_SPANS - len(letter_scores)])
            except Exception as exc:  # fall back to the letter as written in the transcript
                print(f"letter scoring skipped: {exc!r}")

    fields = consensus.vote(parsed)
    acoustic = consensus.letter_from_scores(letter_scores, fields.get("letter"))
    if acoustic:
        fields["letter"] = acoustic
    best = consensus.best_transcript(transcripts, parsed, fields)
    audio.save(clips[best], workdir / "best.wav")

    letter = fields.get("letter", {})
    confirmed = sum(1 for v in fields.values() if v["status"] in ("confirmed", "majority"))
    conflicts = [k for k, v in fields.items() if v["status"] == "conflict"]
    try:
        metar_check = metar.verify(fields, metar.fetch(station.icao))
    except Exception as exc:  # METAR is a cross-check only; never block the ATIS on it
        print(f"METAR check skipped: {exc!r}")
        metar_check = None
    # A disagreement with the very METAR the ATIS quotes points at a transcription error.
    metar_differs = bool(metar_check and metar_check["matched"] and metar_check["differs"])

    if (letter.get("status") in ("confirmed", "majority") and len(loops) >= 2
            and not conflicts and not metar_differs):
        quality = "good"
    elif letter.get("value"):
        quality = "partial"
    else:
        quality = "poor"

    return {
        "letter": letter.get("value"),
        "fields": fields,
        "text": transcripts[best][0],
        "loops": len(loops),
        "complete_loops": complete,
        "quality": quality,
        "confirmed_fields": confirmed,
        "conflicts": conflicts,
        "metar": metar_check,
        "transcripts": [{"text": t, "confidence": round(p, 3)} for t, p in transcripts],
        "model": transcribe.DEFAULT_MODEL,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("station", choices=sorted(STATIONS))
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--seconds", type=int, default=180,
                    help="recording length; must hold 2+ complete loops of the longest ATIS")
    ap.add_argument("--wav", type=Path, help="use this recording instead of recording now")
    ap.add_argument("--heard-at", help="UTC time the --wav recording ended (ISO 8601)")
    ap.add_argument("--error", help="recording failed with this error; publish as offline")
    args = ap.parse_args(argv)

    station = STATIONS[args.station]
    out = args.out / station.icao
    out.mkdir(parents=True, exist_ok=True)
    latest_path, history_path = out / "latest.json", out / "history.json"
    previous = read_json(latest_path, {})

    record = {
        "disclaimer": DISCLAIMER,
        "station": {"icao": station.icao, "name": station.name,
                    "frequency": station.frequency, "source": station.stream_url},
        "checked_at": iso(utcnow()),
    }
    try:
        if args.error:
            raise audio.CaptureError(args.error)
        with tempfile.TemporaryDirectory() as tmp:
            if args.wav:
                wav = args.wav
                heard = datetime.fromisoformat(args.heard_at.replace("Z", "+00:00")) if args.heard_at else utcnow()
            else:
                wav = audio.record(station.stream_url, args.seconds, Path(tmp) / "raw.wav")
                heard = utcnow()
            result = capture(station, wav, Path(tmp))
            to_mp3(Path(tmp) / "best.wav", out / "latest.mp3")
    except Exception as exc:  # keep publishing the last good ATIS, flagged as offline
        traceback.print_exc()
        record.update({k: v for k, v in previous.items() if k not in record})
        record["status"] = "offline"
        record["error"] = f"{type(exc).__name__}: {exc}"
        write_json(latest_path, record)
        return 1

    # A new broadcast is one with a different letter or a different issue time.
    key = (result["letter"], result["fields"].get("time", {}).get("value"))
    prev_key = (previous.get("letter"), previous.get("fields", {}).get("time", {}).get("value"))
    same = key == prev_key and previous.get("status") != "offline"
    first_heard = previous.get("first_seen") if same and previous.get("first_seen") else iso(heard)
    issued = issued_at(key[1], heard)

    record.update(result)
    record["status"] = "ok" if result["quality"] != "poor" else "unreadable"
    record["first_seen"] = first_heard
    record["timing"] = {
        # The data file is static: compare these with your own clock to get the current age.
        "heard_at": iso(heard),                    # end of the recording this is based on
        "first_heard_at": first_heard,             # when this letter/issue was first heard
        "atis_issued_at": iso(issued) if issued else None,   # the ATIS "valid from" time
        "atis_age_min_when_heard": round((heard - issued).total_seconds() / 60) if issued else None,
        "published_at": iso(utcnow()),
        "check_interval_min": CHECK_INTERVAL_MIN,
        "stale_after": iso(heard + timedelta(minutes=STALE_AFTER_MIN)),
    }
    write_json(latest_path, record)

    history = read_json(history_path, [])
    if result["letter"] and (not history or (history[0]["letter"], history[0].get("time")) != key):
        history.insert(0, {
            "letter": result["letter"],
            "time": key[1],
            "first_seen": first_heard,
            "text": result["text"],
            "quality": result["quality"],
        })
        write_json(history_path, history[:HISTORY_LIMIT])

    summary = {k: v["value"] for k, v in result["fields"].items()}
    print(f"{station.icao} {result['quality']} loops={result['loops']} {summary}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
