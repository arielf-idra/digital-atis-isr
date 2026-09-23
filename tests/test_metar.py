import json
from datetime import datetime, timezone
from pathlib import Path

from atis.consensus import vote
from atis.metar import verify
from atis.parse import parse

FIX = Path(__file__).parent / "fixtures"
METARS = json.loads((FIX / "metar_llha.json").read_text())
RUNWAYS = ("15", "33")
NOW = datetime(2026, 9, 23, 7, 5, tzinfo=timezone.utc)


def fields_from(name):
    texts = json.loads((FIX / name).read_text(encoding="utf-8-sig"))
    texts = texts if isinstance(texts, list) else [texts]
    return vote([parse(t, RUNWAYS) for t in texts])


def test_echo_matches_its_0550_metar():
    r = verify(fields_from("llha_echo.json"), METARS, NOW)
    assert r["matched"] and r["time"] == "2026-09-23T05:50Z"
    assert r["differs"] == []
    assert {k for k, c in r["checks"].items() if c["agree"]} == {
        "qnh", "temperature", "dewpoint", "wind", "clouds", "visibility"}


def test_golf_matches_its_0650_metar():
    r = verify(fields_from("llha_golf.json"), METARS, NOW)
    assert r["matched"] and r["time"] == "2026-09-23T06:50Z"
    assert r["differs"] == []


def test_misheard_qnh_is_flagged():
    fields = fields_from("llha_echo.json")
    fields["qnh"]["value"] = 1013
    r = verify(fields, METARS, NOW)
    assert r["differs"] == ["qnh"]
    assert r["checks"]["qnh"]["metar"] == 1015


def test_falls_back_to_latest_metar_with_looser_tolerance():
    fields = fields_from("llha_echo.json")
    fields["time"]["value"] = "0450"          # no METAR at that time
    fields["temperature"]["value"] = 29       # latest METAR says 30
    r = verify(fields, METARS, NOW)
    assert not r["matched"] and r["time"] == "2026-09-23T07:50Z"
    assert r["checks"]["temperature"]["agree"] is True


def test_no_recent_metar():
    later = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    fields = fields_from("llha_echo.json")
    fields["time"]["value"] = "1150"
    assert verify(fields, METARS, later) is None


def test_missing_atis_field_shows_metar_without_verdict():
    fields = fields_from("llha_echo.json")
    del fields["dewpoint"]
    r = verify(fields, METARS, NOW)
    assert r["checks"]["dewpoint"] == {"metar": 19, "agree": None}
