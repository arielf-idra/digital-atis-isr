"""Speech-to-text with faster-whisper, primed with ATIS phraseology."""

import os
from functools import lru_cache

import numpy as np

from .stations import Station

DEFAULT_MODEL = os.environ.get("ATIS_WHISPER_MODEL", "small.en")


def prompt_for(station: Station) -> str:
    # Whisper uses the prompt as "previous text", so a realistic example ATIS
    # steers spelling and number formatting far better than a word list.
    return (
        f"{station.spoken_name} airport information Alpha. Recorded at 0520 UTC. "
        f"Runway in use {station.runways[0]}. Left hand circuit. "
        "Touchdown zone wind 250 degrees 8 knots. Visibility 10 kilometers or more. "
        "Few 3000 feet. Temperature 28, dew point 19. QNH 1015 hectopascals. "
        f"{', '.join(station.vocabulary)}. "
        "Advise on initial contact you have information Alpha."
    )


@lru_cache(maxsize=2)
def _model(name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type="int8")


def transcribe(samples: np.ndarray, station: Station, model: str = DEFAULT_MODEL) -> tuple[str, float]:
    """Return (text, mean word probability)."""
    segments, _ = _model(model).transcribe(
        samples,
        language="en",
        beam_size=5,
        temperature=0,
        initial_prompt=prompt_for(station),
        condition_on_previous_text=False,
        word_timestamps=True,
        vad_filter=False,
    )
    words, probs = [], []
    for seg in segments:
        words.append(seg.text.strip())
        probs.extend(w.probability for w in (seg.words or []))
    return " ".join(words).strip(), float(np.mean(probs)) if probs else 0.0
