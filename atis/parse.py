"""Turn a free-text ATIS transcript into structured fields.

Every extractor is deliberately strict: a field is either matched with a
plausible value or left as None. A missing field is better than a wrong one.
"""

import difflib
import re

PHONETIC = {
    "alpha": "A", "alfa": "A", "bravo": "B", "charlie": "C", "delta": "D",
    "echo": "E", "foxtrot": "F", "golf": "G", "gulf": "G", "hotel": "H", "india": "I",
    "juliet": "J", "juliett": "J", "kilo": "K", "lima": "L", "mike": "M",
    "november": "N", "oscar": "O", "papa": "P", "quebec": "Q", "romeo": "R",
    "sierra": "S", "tango": "T", "uniform": "U", "victor": "V", "whiskey": "W",
    "whisky": "W", "x-ray": "X", "xray": "X", "yankee": "Y", "zulu": "Z",
}
LETTER_WORD = {v: k for k, v in PHONETIC.items() if k not in ("alfa", "juliett", "whisky", "xray")}

DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "tree": "3", "four": "4",
    "fower": "4", "five": "5", "fife": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "niner": "9",
}

CLOUD_COVER = {
    "few": "FEW", "scattered": "SCT", "broken": "BKN", "overcast": "OVC",
}


def normalize(text: str) -> str:
    t = text.lower()
    t = t.replace("x-ray", "xray")
    t = re.sub(r"(\d)er\b", r"\1", t)                    # "29er" (two niner) -> "29"
    # Spoken digits -> numerals, then join runs of single digits ("one five" -> "15").
    t = re.sub(r"\b(" + "|".join(DIGITS) + r")\b", lambda m: DIGITS[m.group(1)], t)
    t = re.sub(r"(?<=\d)[-\s](?=\d\b)", "", t)          # "1-5" / "1 5" -> "15"
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)            # "3,400" -> "3400"
    t = re.sub(r"(?<=\d) decimal (?=\d)", ".", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)            # periods only survive inside numbers
    t = re.sub(r"[^\w\s.\-/]", " ", t)                   # drop punctuation except . - /
    t = re.sub(r"\bclouds? view\b", "cloud few", t)      # consistent speech-model mishearing
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _letter(words: tuple[str, ...]) -> str | None:
    """Phonetic word(s) after "information" -> letter.

    The speech model sometimes splits or bends a code word ("dual yet" for
    Juliet), so after an exact lookup we accept the closest code word by
    spelling. A wrong guess is caught because the letter is said at the start
    and end of every loop and all readings must agree.
    """
    words = tuple(w for w in words if w)
    if not words:
        return None
    if words[0] in PHONETIC:
        return PHONETIC[words[0]]
    candidates = [words[0]] + (["".join(words[:2])] if len(words) > 1 else [])
    best, best_score = None, 0.0
    for c in candidates:
        for word, letter in PHONETIC.items():
            # Spelling alone confuses "joel" with "hotel"; consonants carry the sound.
            score = (_similar(c, word) + _similar(_consonants(c), _consonants(word))) / 2
            if score > best_score:
                best, best_score = letter, score
    return best if best_score >= 0.6 else None


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _consonants(word: str) -> str:
    return re.sub(r"[aeiouy]", "", word)


def parse(text: str, runways: tuple[str, ...] = ()) -> dict:
    t = normalize(text)
    f: dict = {}

    mentions = re.findall(r"information (\w+)(?: (\w+))?", t)
    if mentions:
        f["letter"] = _letter(mentions[0])
    if len(mentions) > 1:
        f["letter_end"] = _letter(mentions[-1])

    m = re.search(r"\b(\d{4})\s*(?:utc|zulu|z)\b", t)
    if m and int(m.group(1)[:2]) < 24 and int(m.group(1)[2:]) < 60:
        f["time"] = m.group(1)

    m = re.search(r"runways? (?:in use )?(\d{2})\b", t)
    if m and (not runways or m.group(1) in runways):
        f["runway"] = m.group(1)

    m = re.search(r"\b(left|right)[\s-]?hand circuit", t)
    if m:
        f["circuit"] = m.group(1)

    m = re.search(r"wind\b(?: touchdown zone)?\s+(variable|calm|\d{3})(?: degrees)?\s*(?:(\d{1,2}) knots?)?", t)
    if m:
        direction, speed = m.group(1), m.group(2)
        if direction == "calm":
            f["wind"] = "CALM"
        elif speed and (direction == "variable" or int(direction) <= 360):
            f["wind"] = ("VRB" if direction == "variable" else direction) + f"/{int(speed)}kt"
        rest = t[m.start():m.start() + 120]
        g = re.search(r"gust(?:s|ing)? (?:up to )?(\d{1,2})", rest)
        if g and "wind" in f and f["wind"] != "CALM":
            f["wind"] += f" G{int(g.group(1))}kt"
        v = re.search(r"var(?:ying|iable) between (\d{3})(?: degrees)? and (\d{3})", rest)
        if v and "wind" in f and f["wind"] != "CALM":
            f["wind"] += f" V{v.group(1)}-{v.group(2)}"

    if re.search(r"\bcav ?ok\b", t):
        f["visibility"] = "CAVOK"
    else:
        m = re.search(r"visibility (\d{1,2}) ?(?:kilometers?|km)( or more)?", t)
        if m:
            f["visibility"] = f"{int(m.group(1))} km" + ("+" if m.group(2) else "")
        else:
            m = re.search(r"visibility (\d{3,4}) ?(?:meters?|m)\b", t)
            if m:
                f["visibility"] = f"{int(m.group(1))} m"

    clouds = [
        f"{CLOUD_COVER[c]} {int(h)}ft"
        for c, h in re.findall(r"\b(few|scattered|broken|overcast) (\d{3,5}) (?:feet|ft)", t)
    ]
    if clouds:
        f["clouds"] = ", ".join(clouds)
    elif re.search(r"no significant cloud|\bnsc\b|sky clear", t):
        f["clouds"] = "NSC"

    m = re.search(r"temperature (minus )?(\d{1,2})\b", t)
    if m:
        f["temperature"] = -int(m.group(2)) if m.group(1) else int(m.group(2))
    m = re.search(r"dew ?point (minus )?(\d{1,2})\b", t)
    if m:
        f["dewpoint"] = -int(m.group(2)) if m.group(1) else int(m.group(2))
    if "temperature" in f and "dewpoint" in f and f["dewpoint"] > f["temperature"]:
        del f["dewpoint"]

    m = re.search(r"qnh (\d{3,4})\b", t)
    if m and 940 <= int(m.group(1)) <= 1060:
        f["qnh"] = int(m.group(1))

    return {k: v for k, v in f.items() if v is not None}
