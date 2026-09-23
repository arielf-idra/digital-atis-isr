"""Combine several independent transcriptions of the same ATIS loop.

The recording repeats every ~40 s, so we hear the same message several times.
Each field is accepted only when the readings agree; disagreements are reported
instead of guessed.
"""

import math
from collections import Counter

FIELDS = ("letter", "time", "runway", "circuit", "wind", "visibility", "clouds",
          "temperature", "dewpoint", "qnh")


def vote(parsed: list[dict]) -> dict:
    """Return {field: {"value", "votes", "of", "status"}} for every field seen."""
    n = len(parsed)
    result = {}
    for name in FIELDS:
        readings = []
        for p in parsed:
            readings.append(p.get(name))
            # The letter is spoken twice per loop; both count.
            if name == "letter" and p.get("letter_end"):
                readings.append(p["letter_end"])
        counts = Counter(r for r in readings if r is not None)
        if not counts:
            continue
        ranked = counts.most_common()
        value, votes = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else 0
        if votes >= 2 and votes > runner_up:
            status = "confirmed" if runner_up == 0 else "majority"
        elif len(ranked) == 1:
            status = "single"  # heard clearly only once; shown but marked unconfirmed
        else:
            status = "conflict"
        result[name] = {
            "value": value if status != "conflict" else None,
            "votes": votes,
            "of": len(readings),
            "status": status,
            "readings": [r for r, _ in ranked],
        }
    return result


def letter_from_scores(span_scores: list[dict], text_field: dict | None) -> dict | None:
    """Decide the ATIS letter from acoustic scores of every "information <letter>" mention.

    Each loop says the letter twice, so with 3 loops there are ~6 independent
    mentions. Their log-probabilities are added up; the letter is confirmed only
    when every mention prefers it and it clearly beats the runner-up.
    """
    if not span_scores:
        return None
    letters = span_scores[0].keys()
    total = {l: sum(s[l] for s in span_scores) for l in letters}
    ranked = sorted(total, key=total.get, reverse=True)
    best = ranked[0]
    # Probability of the best letter against all others, from the summed evidence.
    top = total[best]
    confidence = 1.0 / sum(math.exp(total[l] - top) for l in letters)
    per_span = [max(s, key=s.get) for s in span_scores]
    votes = per_span.count(best)
    text_letter = (text_field or {}).get("value")

    if votes == len(per_span) and confidence >= 0.95:
        status = "confirmed" if len(per_span) >= 2 else "single"
    elif votes > len(per_span) / 2 and confidence >= 0.9:
        status = "majority"
    else:
        status = "conflict"
    if text_letter and text_letter != best and (text_field or {}).get("status") == "confirmed":
        status = "conflict"  # the written transcript clearly says something else

    return {
        "value": best if status != "conflict" else None,
        "votes": votes,
        "of": len(per_span),
        "status": status,
        "readings": sorted(set(per_span) | ({text_letter} if text_letter else set())),
        "method": "acoustic",
        "confidence": round(confidence, 3),
    }


def best_transcript(transcripts: list[tuple[str, float]], parsed: list[dict], fields: dict) -> int:
    """Index of the transcript that agrees most with the consensus."""
    def score(i: int) -> tuple[int, float]:
        agree = sum(1 for k, v in fields.items() if v["value"] is not None and parsed[i].get(k) == v["value"])
        return agree, transcripts[i][1]
    return max(range(len(transcripts)), key=score)
