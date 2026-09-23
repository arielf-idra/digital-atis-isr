"""Combine several independent transcriptions of the same ATIS loop.

The recording repeats every ~40 s, so we hear the same message several times.
Each field is accepted only when the readings agree; disagreements are reported
instead of guessed.
"""

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


def best_transcript(transcripts: list[tuple[str, float]], parsed: list[dict], fields: dict) -> int:
    """Index of the transcript that agrees most with the consensus."""
    def score(i: int) -> tuple[int, float]:
        agree = sum(1 for k, v in fields.items() if v["value"] is not None and parsed[i].get(k) == v["value"])
        return agree, transcripts[i][1]
    return max(range(len(transcripts)), key=score)
