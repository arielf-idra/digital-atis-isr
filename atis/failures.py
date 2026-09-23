"""Keep and report broadcasts that could not be fully decoded.

Every ATIS must give runway, wind, temperature and QNH. When one of them is
missing, the recording and transcripts are kept under data/<ICAO>/failed/ and
a GitHub issue is opened (once per broadcast) so a person can review it and
the decoder can be improved.
"""

import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path

REQUIRED = ("runway", "wind", "temperature", "qnh")
KEEP = 100
LABEL = "decode-failure"


def missing_required(fields: dict) -> list[str]:
    return [k for k in REQUIRED if (fields.get(k) or {}).get("value") is None]


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def record(out: Path, record: dict, missing: list[str]) -> str | None:
    """Store a failed broadcast once. Returns its name, or None if already stored."""
    t = record["timing"]
    letter = record.get("letter")
    issue_time = (record["fields"].get("time") or {}).get("value")
    # Same broadcast = same letter and issue time. Without either, group by hour so
    # an unreadable stretch doesn't produce a report every few minutes.
    key = f"{letter or '?'}-{issue_time or t['heard_at'][:13]}"

    folder = out / "failed"
    folder.mkdir(exist_ok=True)
    index = _read(folder / "index.json", [])
    if any(e["key"] == key for e in index):
        return None

    name = t["heard_at"].replace("-", "").replace(":", "")[:13] + "Z-" + (letter or "unknown")
    if record.get("transcripts") and (out / "latest.mp3").exists() and record.get("source") != "text":
        shutil.copy2(out / "latest.mp3", folder / f"{name}.mp3")
    _write(folder / f"{name}.json", record)
    index.insert(0, {"key": key, "name": name, "heard_at": t["heard_at"], "letter": letter,
                     "time": issue_time, "missing": missing, "issue": None})
    for old in index[KEEP:]:
        for ext in ("mp3", "json"):
            (folder / f"{old['name']}.{ext}").unlink(missing_ok=True)
    _write(folder / "index.json", index[:KEEP])
    return name


def _issue_body(repo: str, icao: str, rec: dict, entry: dict) -> str:
    base = f"https://raw.githubusercontent.com/{repo}/gh-pages/data/{icao}/failed/{entry['name']}"
    rows = "\n".join(
        f"| {k} | {v.get('value') if v.get('value') is not None else '**—**'} | {v['status']} | "
        f"{' / '.join(map(str, v.get('readings', [])))} |"
        for k, v in rec["fields"].items()
    )
    loops = "\n\n".join(f"**Repetition {i + 1}** ({round(t['confidence'] * 100)}%):\n> {t['text']}"
                        for i, t in enumerate(rec.get("transcripts", [])))
    metar = (rec.get("metar") or {}).get("raw") or "not available"
    source = (f"Text D-ATIS from {rec.get('source_url')} · [full data]({base}.json)"
              if rec.get("source") == "text"
              else f"Recording: [{entry['name']}.mp3]({base}.mp3) · [full data]({base}.json)")
    return f"""Could not read: **{', '.join(entry['missing'])}**

- Station: {icao}, information **{entry['letter'] or '?'}**, valid from {entry['time'] or '?'}Z
- Heard at: {entry['heard_at']}
- {source}
- METAR: `{metar}`

| Field | Value | Status | Readings |
|---|---|---|---|
{rows}

{loops}
"""


def _post(url: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "digital-atis",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def report(data_dir: Path, icao: str) -> int:
    """Open a GitHub issue for each stored failure not yet reported. Returns how many."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    folder = data_dir / icao / "failed"
    index = _read(folder / "index.json", [])
    if not token or not repo or not index:
        return 0
    opened = 0
    for entry in index:
        if entry.get("issue"):
            continue
        rec = _read(folder / f"{entry['name']}.json", {"fields": {}})
        payload = {
            "title": f"{icao} information {entry['letter'] or '?'} "
                     f"({entry['time'] or entry['heard_at'][11:16].replace(':', '')}Z): "
                     f"could not read {', '.join(entry['missing'])}",
            "body": _issue_body(repo, icao, rec, entry),
            "labels": [LABEL],
        }
        url = f"https://api.github.com/repos/{repo}/issues"
        try:
            try:
                issue = _post(url, token, payload)
            except urllib.error.HTTPError as exc:
                if exc.code != 422:
                    raise
                del payload["labels"]  # label couldn't be applied; the issue matters more
                issue = _post(url, token, payload)
        except urllib.error.HTTPError as exc:
            print(f"could not open issue for {entry['name']}: {exc}", flush=True)
            continue
        entry["issue"] = issue.get("html_url")
        opened += 1
    _write(folder / "index.json", index)
    return opened
