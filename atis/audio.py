"""Record the raw stream and split it into complete ATIS loops."""

import subprocess
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
FRAME_SEC = 0.05


class CaptureError(RuntimeError):
    pass


def _ffmpeg_cmd(url: str, seconds: int, out_path: Path) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5",
        "-rw_timeout", "15000000",
        "-i", url,
        "-t", str(seconds), "-ac", "1", "-ar", str(SAMPLE_RATE), str(out_path),
    ]


def start_recording(url: str, seconds: int, out_path: Path) -> subprocess.Popen:
    """Start recording in the background, so the previous sample can be processed meanwhile."""
    return subprocess.Popen(_ffmpeg_cmd(url, seconds, out_path),
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def finish_recording(proc: subprocess.Popen, seconds: int, out_path: Path) -> Path:
    try:
        _, err = proc.communicate(timeout=seconds + 60)
    except subprocess.TimeoutExpired:
        proc.kill()
        err = "ffmpeg timed out"
    if out_path.exists() and duration(out_path) >= seconds * 0.8:
        return out_path
    raise CaptureError(f"recording failed: {(err or '').strip() or 'recording too short'}")


def record(url: str, seconds: int, out_path: Path, retries: int = 3) -> Path:
    """Record `seconds` of the stream to a 16 kHz mono WAV using ffmpeg."""
    for attempt in range(retries):
        try:
            return finish_recording(start_recording(url, seconds, out_path), seconds, out_path)
        except CaptureError:
            if attempt == retries - 1:
                raise
    raise AssertionError("unreachable")


def load(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1:
            raise ValueError("expected 16 kHz mono WAV")
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def save(samples: np.ndarray, path: Path) -> Path:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return path


def frame_levels_db(samples: np.ndarray) -> np.ndarray:
    n = int(SAMPLE_RATE * FRAME_SEC)
    usable = len(samples) // n * n
    frames = samples[:usable].reshape(-1, n)
    rms = np.sqrt(np.mean(frames ** 2, axis=1)) + 1e-9
    return 20 * np.log10(rms)


def split_loops(
    samples: np.ndarray,
    min_gap_sec: float = 2.5,
    min_loop_sec: float = 15.0,
    max_loop_sec: float = 120.0,
) -> list[tuple[float, float]]:
    """Return (start, end) seconds of every loop bounded by silence on both sides.

    The ATIS recording repeats with a pause of several seconds between plays;
    the pause is much longer than any gap between words.
    """
    levels = frame_levels_db(samples)
    if len(levels) == 0:
        return []
    # Threshold relative to the loud part of the signal so it copes with gain changes.
    loud = np.percentile(levels, 90)
    silent = levels < max(loud - 25, -50)

    gaps: list[tuple[int, int]] = []
    start = None
    for i, s in enumerate(silent):
        if s and start is None:
            start = i
        elif not s and start is not None:
            gaps.append((start, i))
            start = None
    if start is not None:
        gaps.append((start, len(silent)))
    min_gap = int(min_gap_sec / FRAME_SEC)
    gaps = [g for g in gaps if g[1] - g[0] >= min_gap]

    loops = []
    for (_, a), (b, _) in zip(gaps, gaps[1:]):
        length = (b - a) * FRAME_SEC
        if min_loop_sec <= length <= max_loop_sec:
            # Keep a little padding so the first word isn't clipped.
            loops.append((max(a * FRAME_SEC - 0.3, 0), b * FRAME_SEC + 0.3))
    return loops
