"""Capture one ATIS broadcast and write it as JSON.

    python -m atis LLHA --out data
"""

import argparse
import json
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import audio, consensus, parse, transcribe
from .stations import STATIONS

HISTORY_LIMIT = 96


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def capture(station, seconds: int, workdir: Path) -> dict:
    wav = audio.record(station.stream_url, seconds, workdir / "raw.wav")
    samples = audio.load(wav)
    loops = audio.split_loops(samples)
    complete = bool(loops)
    if not loops:
        # No clean loop boundaries (e.g. the recording changed format); use it all.
        loops = [(0.0, len(samples) / audio.SAMPLE_RATE)]

    transcripts, parsed, clips = [], [], []
    for start, end in loops:
        clip = samples[int(start * audio.SAMPLE_RATE):int(end * audio.SAMPLE_RATE)]
        text, prob = transcribe.transcribe(clip, station)
        transcripts.append((text, prob))
        parsed.append(parse.parse(text, station.runways))
        clips.append(clip)

    fields = consensus.vote(parsed)
    best = consensus.best_transcript(transcripts, parsed, fields)
    audio.save(clips[best], workdir / "best.wav")

    letter = fields.get("letter", {})
    confirmed = sum(1 for v in fields.values() if v["status"] in ("confirmed", "majority"))
    conflicts = [k for k, v in fields.items() if v["status"] == "conflict"]
    if letter.get("status") in ("confirmed", "majority") and len(loops) >= 2 and not conflicts:
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
        "transcripts": [{"text": t, "confidence": round(p, 3)} for t, p in transcripts],
        "model": transcribe.DEFAULT_MODEL,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("station", choices=sorted(STATIONS))
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--seconds", type=int, default=210,
                    help="recording length; must hold 2+ complete loops of the longest ATIS")
    args = ap.parse_args(argv)

    station = STATIONS[args.station]
    out = args.out / station.icao
    out.mkdir(parents=True, exist_ok=True)
    latest_path, history_path = out / "latest.json", out / "history.json"
    previous = read_json(latest_path, {})

    record = {
        "station": {"icao": station.icao, "name": station.name,
                    "frequency": station.frequency, "source": station.stream_url},
        "checked_at": now(),
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = capture(station, args.seconds, Path(tmp))
            to_mp3(Path(tmp) / "best.wav", out / "latest.mp3")
    except Exception as exc:  # keep publishing the last good ATIS, flagged as stale
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
    record.update(result)
    record["status"] = "ok" if result["quality"] != "poor" else "unreadable"
    record["first_seen"] = previous.get("first_seen", record["checked_at"]) if same else record["checked_at"]
    write_json(latest_path, record)

    history = read_json(history_path, [])
    if result["letter"] and (not history or (history[0]["letter"], history[0].get("time")) != key):
        history.insert(0, {
            "letter": result["letter"],
            "time": key[1],
            "first_seen": record["first_seen"],
            "text": result["text"],
            "quality": result["quality"],
        })
        write_json(history_path, history[:HISTORY_LIMIT])

    summary = {k: v["value"] for k, v in result["fields"].items()}
    print(f"{station.icao} {result['quality']} loops={result['loops']} {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
