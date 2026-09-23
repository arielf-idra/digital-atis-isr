"""Speech-to-text with faster-whisper, primed with ATIS phraseology."""

import os
from functools import lru_cache

import numpy as np

from .parse import LETTER_WORD
from .stations import Station

DEFAULT_MODEL = os.environ.get("ATIS_WHISPER_MODEL", "small.en")
SAMPLE_RATE = 16000


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


def transcribe(samples: np.ndarray, station: Station, model: str = DEFAULT_MODEL):
    """Return (text, mean word probability, [(word, start_sec, end_sec), ...])."""
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
    texts, probs, words = [], [], []
    for seg in segments:
        texts.append(seg.text.strip())
        for w in seg.words or []:
            probs.append(w.probability)
            words.append((w.word.strip(), w.start, w.end))
    return " ".join(texts).strip(), float(np.mean(probs)) if probs else 0.0, words


def letter_spans(words: list[tuple[str, float, float]], clip_len: float) -> list[tuple[float, float]]:
    """Audio windows covering "information <letter>" (said at the start and end of each loop)."""
    return [
        (max(start - 0.1, 0.0), min(end + 1.2, clip_len))
        for word, start, end in words
        if "information" in word.lower()
    ]


def score_letters(samples: np.ndarray, spans: list[tuple[float, float]], model: str = DEFAULT_MODEL) -> list[dict]:
    """For each span, the log-probability of hearing "information <code word>" for all 26 letters.

    Instead of trusting what the model chose to write ("dual yet"), this asks
    how well each valid code word explains the audio, so the answer is always
    a real letter and comes with a margin over the alternatives.
    """
    import ctranslate2
    from faster_whisper.tokenizer import Tokenizer

    m = _model(model)
    tok = Tokenizer(m.hf_tokenizer, multilingual=m.model.is_multilingual, task="transcribe", language="en")
    letters = list(LETTER_WORD)
    names = ["X-ray" if LETTER_WORD[l] == "xray" else LETTER_WORD[l].capitalize() for l in letters]
    candidates = [tok.encode(f" information {n}") for n in names]

    results = []
    for start, end in spans:
        clip = samples[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
        if len(clip) < SAMPLE_RATE // 2:
            continue
        padded = np.pad(clip, (0, max(0, 30 * SAMPLE_RATE - len(clip))))
        features = m.feature_extractor(padded)[:, :3000]
        encoded = m.model.encode(ctranslate2.StorageView.from_array(
            np.ascontiguousarray(features[None].astype(np.float32))))
        frames = len(clip) // 160
        scores = {}
        # One call per candidate: batching align() overflows the stack on Windows.
        for letter, ids in zip(letters, candidates):
            r = m.model.align(encoded, list(tok.sot_sequence), [ids], [frames])[0]
            # Skip the first token (" information"), which is the same for every candidate.
            scores[letter] = float(np.sum(np.log(np.asarray(r.text_token_probs[1:]) + 1e-12)))
        results.append(scores)
    return results
