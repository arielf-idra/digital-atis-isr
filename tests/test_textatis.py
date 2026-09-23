from datetime import datetime, timezone
from pathlib import Path

from atis import textatis
from atis.stations import STATIONS

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 9, 23, 17, 23, tzinfo=timezone.utc)


def load(icao):
    return textatis.cards((FIX / f"atisguru_{icao.lower()}.html").read_text(encoding="utf-8"))


def values(fields):
    return {k: v["value"] for k, v in fields.items()}


def test_llbg_cards():
    arr, dep = load("LLBG")
    assert arr["type"] == "ARR" and arr["requested_by"] == "LY356 (4X-EHH)"
    assert dep["type"] == "DEP" and dep["requested_by"] == "9HBBH"
    assert values(textatis.parse(arr["text"], "ARR", STATIONS["LLBG"].runways)) == {
        "letter": "I", "time": "2320", "runway": "ARR 21 · DEP 26", "wind": "160/4kt",
        "visibility": "10 km+", "clouds": "FEW 3000ft", "temperature": 25, "dewpoint": 20, "qnh": 1012,
    }


def test_ller_cavok_and_tdz_wind():
    arr, _ = load("LLER")
    assert values(textatis.parse(arr["text"], "ARR", STATIONS["LLER"].runways)) == {
        "letter": "U", "time": "1550", "runway": "01", "wind": "020/15kt",
        "visibility": "CAVOK", "clouds": "CAVOK", "temperature": 35, "dewpoint": 13, "qnh": 1009,
    }


def test_age_comes_from_the_atis_time_not_the_received_time():
    # Listed as received 17:06 today, but the text says TIME 2320: that is yesterday's ATIS.
    arr, _ = load("LLBG")
    received = textatis.parse_received(arr["received"])
    assert received == datetime(2026, 9, 23, 17, 6, tzinfo=timezone.utc)
    issued = textatis.issued_at("2320", received, NOW)
    assert issued == datetime(2026, 9, 22, 23, 20, tzinfo=timezone.utc)
    assert (NOW - issued).total_seconds() / 60 > textatis.OLD_AFTER_MIN


def test_unknown_runway_rejected():
    f = textatis.parse("LLBG ARR INFO A. TIME 1000. EXP ILS APCH ARR RWY 27.", "ARR", STATIONS["LLBG"].runways)
    assert "runway" not in f
