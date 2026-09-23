"""Cross-check transcribed ATIS values against the official METAR.

The METAR comes from NOAA's Aviation Weather Center (aviationweather.gov),
a free public API. The ATIS "valid from HHMM" time is normally the time of the
METAR it was built from, so when that report is found the values should match
almost exactly. Otherwise the latest METAR is used with looser tolerances.

A difference is only ever reported as a warning: the METAR never replaces what
was heard on the ATIS.
"""

import json
import re
import urllib.request
from datetime import datetime, timezone

API = "https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours=3"
MAX_AGE_MIN = 90

# (tolerance against the METAR the ATIS was built from, against the latest METAR)
TOLERANCE = {
    "qnh": (0, 1),
    "temperature": (0, 2),
    "dewpoint": (0, 2),
    "wind_speed": (5, 8),     # ATIS gives touchdown-zone wind, METAR a 10-min mean
    "wind_dir": (40, 60),
    "cloud_base": (300, 1000),
}


def fetch(icao: str, timeout: int = 15) -> list[dict]:
    req = urllib.request.Request(API.format(icao=icao), headers={"User-Agent": "digital-atis"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _obs_time(m: dict) -> datetime:
    return datetime.fromtimestamp(m["obsTime"], tz=timezone.utc)


def _pick(metars: list[dict], atis_time: str | None, now: datetime) -> tuple[dict | None, bool]:
    """Return (metar, matched) where matched means it is the report the ATIS quotes."""
    metars = sorted(metars, key=lambda m: m["obsTime"], reverse=True)
    if atis_time:
        for m in metars:
            if _obs_time(m).strftime("%H%M") == atis_time:
                return m, True
    if metars and (now - _obs_time(metars[0])).total_seconds() / 60 <= MAX_AGE_MIN:
        return metars[0], False
    return None, False


def _vis_m(raw: str) -> int | None:
    if "CAVOK" in raw:
        return 10000
    m = re.search(r"\s(\d{4})\s", raw)
    return int(m.group(1)) if m else None


def _atis_vis_m(v: str) -> int | None:
    if v == "CAVOK":
        return 10000
    m = re.match(r"(\d+) (km|m)", v)
    if not m:
        return None
    return int(m.group(1)) * (1000 if m.group(2) == "km" else 1)


def _angle(a: int, b: int) -> int:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _metar_wind(m: dict) -> str:
    if m.get("wspd") == 0:
        return "CALM"
    d = "VRB" if m.get("wdir") == "VRB" else f"{int(m['wdir']):03d}"
    s = f"{d}/{m['wspd']}kt"
    if m.get("wgst"):
        s += f" G{m['wgst']}kt"
    return s


def _check_wind(atis: str, m: dict, tol: int) -> bool:
    if atis == "CALM":
        return (m.get("wspd") or 0) <= 3
    w = re.match(r"(VRB|\d{3})/(\d+)kt", atis)
    if not w:
        return False
    speed = int(w.group(2))
    if m.get("wspd") == 0:
        return speed <= 3
    if abs(speed - m["wspd"]) > TOLERANCE["wind_speed"][tol]:
        return False
    # Direction is meaningless in light or variable wind.
    if w.group(1) == "VRB" or m.get("wdir") == "VRB" or speed < 5 or m["wspd"] < 5:
        return True
    return _angle(int(w.group(1)), int(m["wdir"])) <= TOLERANCE["wind_dir"][tol]


def _check_clouds(atis: str, m: dict, tol: int) -> bool:
    layers = m.get("clouds") or []
    if atis == "NSC":
        return not any(l.get("base") for l in layers)
    first = re.match(r"\w+ (\d+)ft", atis)
    bases = [l["base"] for l in layers if l.get("base")]
    if not first or not bases:
        return False
    return abs(int(first.group(1)) - min(bases)) <= TOLERANCE["cloud_base"][tol]


def verify(fields: dict, metars: list[dict], now: datetime | None = None) -> dict | None:
    """Compare voted ATIS fields with the matching METAR.

    Returns None when no usable METAR exists. Otherwise:
    {"raw", "time", "matched", "checks": {field: {"metar", "agree"}}, "differs": [...]}.
    """
    now = now or datetime.now(timezone.utc)
    atis_time = (fields.get("time") or {}).get("value")
    m, matched = _pick(metars, atis_time, now)
    if not m:
        return None
    tol = 0 if matched else 1

    def value(name):
        f = fields.get(name) or {}
        return f.get("value")

    checks: dict[str, dict] = {}

    def add(name, metar_value, agree):
        checks[name] = {"metar": metar_value, "agree": agree}

    if m.get("altim") is not None:
        q = int(round(m["altim"]))
        add("qnh", q, None if value("qnh") is None else abs(value("qnh") - q) <= TOLERANCE["qnh"][tol])
    for name, key in (("temperature", "temp"), ("dewpoint", "dewp")):
        if m.get(key) is not None:
            t = int(round(m[key]))
            add(name, t, None if value(name) is None else abs(value(name) - t) <= TOLERANCE[name][tol])
    if m.get("wspd") is not None:
        add("wind", _metar_wind(m), None if value("wind") is None else _check_wind(value("wind"), m, tol))
    if m.get("clouds") is not None:
        layers = [f"{l['cover']} {l['base']}ft" for l in m["clouds"] if l.get("base")]
        add("clouds", ", ".join(layers) or "NSC",
            None if value("clouds") is None else _check_clouds(value("clouds"), m, tol))
    vis = _vis_m(m.get("rawOb", ""))
    if vis is not None:
        atis_vis = _atis_vis_m(value("visibility")) if value("visibility") else None
        agree = None if atis_vis is None else (
            (vis >= 9999 and atis_vis >= 10000) or abs(vis - atis_vis) <= 0.2 * max(vis, atis_vis))
        add("visibility", "10 km+" if vis >= 9999 else f"{vis} m", agree)

    return {
        "raw": m.get("rawOb"),
        "time": _obs_time(m).strftime("%Y-%m-%dT%H:%MZ"),
        "matched": matched,
        "checks": checks,
        "differs": [k for k, c in checks.items() if c["agree"] is False],
    }
