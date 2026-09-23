"""Published D-ATIS text (for airports without a public audio stream).

atis.guru republishes the data-link ATIS that aircraft request over ACARS.
A new text only appears when some aircraft requests it, so the text can be
hours or days old. Its "received" time is not reliable either (an ATIS for
2320Z has been seen listed as received 17:06), so the age is always taken from
the time written inside the ATIS itself.
"""

import html
import re
import urllib.request
from datetime import datetime, timedelta, timezone

OLD_AFTER_MIN = 90  # an ATIS older than this is certainly not the current one

_CARD = re.compile(
    r'<h5 class="card-title"[^>]*>\s*(Arrival|Departure) ATIS\s*</h5>\s*'
    r'<h6([^>]*)>([^<]*)</h6>\s*'
    r'<div class="atis">(.*?)</div>',
    re.S,
)


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "digital-atis (+https://github.com/arielf-idra/digital-atis-isr)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def cards(page: str) -> list[dict]:
    """Arrival/departure ATIS texts on an atis.guru page."""
    out = []
    for kind, attrs, received, body in _CARD.findall(page):
        text = html.unescape(body).replace("\r", "")
        text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
        title = re.search(r'title="([^"]*)"', attrs)
        out.append({
            "type": "ARR" if kind == "Arrival" else "DEP",
            "received": received.strip(),
            "requested_by": html.unescape(title.group(1)).removeprefix("Requested by ").strip() if title else None,
            "text": text,
        })
    return out


def _field(value, status="confirmed"):
    return {"value": value, "status": status, "votes": 1, "of": 1, "readings": [value]}


def parse(text: str, kind: str, runways: tuple[str, ...] = ()) -> dict:
    """Fields of a D-ATIS text, in the same shape as the audio decoder's vote output."""
    t = " ".join(text.upper().split())
    f: dict = {}

    m = re.search(r"\bINFO(?:RMATION)? ([A-Z])\b", t) or re.search(r"\bATIS ([A-Z])\b", t)
    if m:
        f["letter"] = m.group(1)
    m = re.search(r"\bTIME (\d{4})\b", t) or re.search(r"\b(\d{4})Z\b", t)
    if m and int(m.group(1)[:2]) < 24 and int(m.group(1)[2:]) < 60:
        f["time"] = m.group(1)

    def rwy(pattern):
        m = re.search(pattern, t)
        return m.group(1) if m and (not runways or m.group(1)[:2] in runways) else None

    arr = rwy(r"(?:ARR|APCH|APPROACH|ACTIVE|LDG|LANDING)[A-Z ,]*?(?:RWY|RUNWAY)S? (\d{2}[LRC]?)\b")
    dep = rwy(r"\bDEP[A-Z ,]*?(?:RWY|RUNWAY)S? (\d{2}[LRC]?)\b")
    if arr and dep and arr != dep:
        f["runway"] = f"ARR {arr} · DEP {dep}"
    elif arr or dep:
        f["runway"] = arr or dep

    m = re.search(r"\bWIND (?:TDZ )?(CALM|VRB|\d{3})(?: DEG)?,? ?(?:(\d{1,2}) ?KT)?", t)
    if m:
        if m.group(1) == "CALM":
            f["wind"] = "CALM"
        elif m.group(2):
            f["wind"] = f"{m.group(1)}/{int(m.group(2))}kt"
            rest = t[m.end():m.end() + 60]
            g = re.search(r"(?:MAX|GUSTS?(?: TO)?) (\d{1,2}) ?KT", rest)
            if g:
                f["wind"] += f" G{int(g.group(1))}kt"
            v = re.search(r"VR?B? ?(?:BTN|BETWEEN) (\d{3})(?: DEG)?(?: AND |/)(\d{3})", rest)
            if v:
                f["wind"] += f" V{v.group(1)}-{v.group(2)}"

    if re.search(r"\bCAVOK\b", t):
        f["visibility"] = "CAVOK"
        f["clouds"] = "CAVOK"
    else:
        m = re.search(r"\bVIS (\d{1,2}) ?KM( OR MORE)?", t)
        if m:
            f["visibility"] = f"{int(m.group(1))} km" + ("+" if m.group(2) else "")
        else:
            m = re.search(r"\bVIS (\d{3,4}) ?M\b", t)
            if m:
                f["visibility"] = f"{int(m.group(1))} m"
        clouds = [f"{c} {int(h)}ft" for c, h in re.findall(r"\b(FEW|SCT|BKN|OVC) (\d{3,5}) ?FT", t)]
        if clouds:
            f["clouds"] = ", ".join(clouds)
        elif re.search(r"\b(NSC|SKC|NCD)\b", t):
            f["clouds"] = "NSC"

    m = re.search(r"\bT(?:EMP)? (M|MS|MINUS )?(\d{1,2})\b", t)
    if m:
        f["temperature"] = -int(m.group(2)) if m.group(1) else int(m.group(2))
    m = re.search(r"\bDP (M|MS|MINUS )?(\d{1,2})\b", t)
    if m:
        f["dewpoint"] = -int(m.group(2)) if m.group(1) else int(m.group(2))
    m = re.search(r"\bQNH (\d{3,4})\b", t)
    if m and 940 <= int(m.group(1)) <= 1060:
        f["qnh"] = int(m.group(1))

    return {k: _field(v) for k, v in f.items()}


def issued_at(hhmm: str | None, received: datetime | None, now: datetime) -> datetime | None:
    """Full UTC time of the ATIS: the latest HHMM that is not after it was received (or now)."""
    if not hhmm:
        return None
    ref = min(received, now) if received else now
    t = ref.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:]), second=0, microsecond=0)
    return t - timedelta(days=1) if t > ref + timedelta(minutes=5) else t


def parse_received(s: str) -> datetime | None:
    m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC", s)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) if m else None
