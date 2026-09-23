"""Capture ATIS continuously and publish to the gh-pages worktree.

Runs inside one GitHub Actions job for ~50 minutes. While one recording is
being transcribed the next one is already being recorded, so a fresh check is
published about every `--seconds` (3 minutes by default).

The gh-pages branch is kept as a single amended commit so audio files don't
accumulate in git history. The web page is served from main, so pushes here
don't trigger GitHub Pages builds.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atis import audio, failures  # noqa: E402
from atis.__main__ import main as capture  # noqa: E402
from atis.stations import STATIONS  # noqa: E402

RETRY_PAUSE_SEC = 30


def git(pages: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(pages), *args], check=True)


def publish(pages: Path) -> None:
    git(pages, "add", "-A")
    git(pages, "commit", "--amend", "--quiet", "-m", "Latest ATIS")
    git(pages, "push", "--force", "--quiet", "origin", "HEAD:gh-pages")


def utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=Path, required=True)
    ap.add_argument("--stations", nargs="+", default=["LLHA"])
    ap.add_argument("--minutes", type=float, default=50)
    ap.add_argument("--seconds", type=int, default=180, help="length of each recording")
    args = ap.parse_args()

    shutil.copy2(Path(__file__).resolve().parent.parent / "index.html", args.pages / "index.html")
    (args.pages / ".nojekyll").touch()

    tmp = Path(tempfile.mkdtemp())
    deadline = time.monotonic() + args.minutes * 60
    counter = 0

    def start_all() -> dict:
        nonlocal counter
        counter += 1
        pending = {}
        for s in args.stations:
            path = tmp / f"{s}-{counter}.wav"
            pending[s] = (audio.start_recording(STATIONS[s].stream_url, args.seconds, path), path)
        return pending

    pending = start_all()
    while pending:
        ready = {}
        for s, (proc, path) in pending.items():
            try:
                ready[s] = (audio.finish_recording(proc, args.seconds, path), utc_iso(), None)
            except audio.CaptureError as exc:
                ready[s] = (None, utc_iso(), str(exc))

        all_failed = all(err for _, _, err in ready.values())
        if all_failed:
            time.sleep(RETRY_PAUSE_SEC)  # stream down: retry calmly instead of spinning
        # Start the next recordings before processing, so listening never pauses.
        more = time.monotonic() + args.seconds < deadline
        pending = start_all() if more else {}

        for s, (wav, heard_at, err) in ready.items():
            argv = [s, "--out", str(args.pages / "data")]
            argv += ["--error", err] if err else ["--wav", str(wav), "--heard-at", heard_at]
            try:
                capture(argv)
            except Exception as exc:  # never let one bad cycle kill the job
                print(f"{s}: unexpected error {exc!r}", flush=True)
            if wav:
                wav.unlink(missing_ok=True)
        try:
            publish(args.pages)
            print(f"published {utc_iso()}", flush=True)
        except subprocess.CalledProcessError as exc:
            print(f"push failed: {exc}", flush=True)
        # After the push, so the recording linked from the issue already exists.
        for s in args.stations:
            try:
                if n := failures.report(args.pages / "data", s):
                    print(f"{s}: opened {n} decode-failure issue(s)", flush=True)
            except Exception as exc:
                print(f"{s}: failure report skipped: {exc!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
