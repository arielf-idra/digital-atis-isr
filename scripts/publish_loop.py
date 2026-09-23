"""Capture ATIS repeatedly and publish to the gh-pages worktree.

Runs inside one GitHub Actions job for ~50 minutes. The gh-pages branch is kept
as a single amended commit so audio files don't accumulate in git history.
Pushes happen when the ATIS content changes, or as a heartbeat so the site can
show the data is fresh; this keeps GitHub Pages builds well under its hourly limit.
"""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atis.__main__ import main as capture  # noqa: E402

VOLATILE = {"checked_at", "transcripts", "text"}


def signature(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return json.dumps({k: v for k, v in data.items() if k not in VOLATILE}, sort_keys=True)


def git(pages: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(pages), *args], check=True)


def publish(pages: Path) -> None:
    git(pages, "add", "-A")
    git(pages, "commit", "--amend", "--quiet", "-m", "Latest ATIS")
    git(pages, "push", "--force", "--quiet", "origin", "HEAD:gh-pages")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=Path, required=True)
    ap.add_argument("--stations", nargs="+", default=["LLHA"])
    ap.add_argument("--minutes", type=float, default=50)
    ap.add_argument("--interval", type=int, default=240, help="seconds between capture starts")
    ap.add_argument("--heartbeat", type=int, default=600, help="max seconds between pushes")
    args = ap.parse_args()

    site = Path(__file__).resolve().parent.parent / "site"
    for f in site.iterdir():
        if f.is_file():
            shutil.copy2(f, args.pages / f.name)
    (args.pages / ".nojekyll").touch()

    deadline = time.monotonic() + args.minutes * 60
    last_push = 0.0
    failures = 0
    while time.monotonic() < deadline:
        started = time.monotonic()
        before = {s: signature(args.pages / "data" / s / "latest.json") for s in args.stations}
        for s in args.stations:
            try:
                rc = capture([s, "--out", str(args.pages / "data")])
            except Exception as exc:  # never let one bad cycle kill the job
                print(f"{s}: unexpected error {exc!r}", flush=True)
                rc = 1
            failures = failures + 1 if rc else 0
        changed = any(signature(args.pages / "data" / s / "latest.json") != before[s] for s in args.stations)
        if changed or time.monotonic() - last_push >= args.heartbeat:
            try:
                publish(args.pages)
                last_push = time.monotonic()
                print("published" + (" (changed)" if changed else " (heartbeat)"), flush=True)
            except subprocess.CalledProcessError as exc:
                print(f"push failed: {exc}", flush=True)
        time.sleep(max(0, args.interval - (time.monotonic() - started)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
