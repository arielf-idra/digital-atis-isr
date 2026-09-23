import json
from pathlib import Path

from atis.consensus import vote
from atis.parse import normalize, parse

RUNWAYS = ("15", "33")
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "llha_echo.json").read_text())


def test_normalize_spoken_numbers():
    assert normalize("Runway one five, QNH one zero one five") == "runway 15 qnh 1015"
    assert normalize("Runway in use 1-5") == "runway in use 15"
    assert normalize("Clouds few 3,400 feet") == "clouds few 3400 feet"


def test_clean_transcript():
    p = parse(FIXTURE[1], RUNWAYS)
    assert p == {
        "letter": "E", "letter_end": "E", "time": "0550", "runway": "15",
        "circuit": "left", "wind": "VRB/2kt", "visibility": "10 km+",
        "clouds": "FEW 3400ft", "temperature": 28, "dewpoint": 19, "qnh": 1015,
    }


def test_garbled_fields_are_dropped_not_guessed():
    p = parse(FIXTURE[0], RUNWAYS)
    assert "dewpoint" not in p
    assert "clouds" not in p
    assert p["qnh"] == 1015


def test_unknown_runway_rejected():
    assert "runway" not in parse("Runway in use 27", RUNWAYS)


def test_implausible_values_rejected():
    p = parse("QNH 1915. Temperature 12, dew point 19. Valid from 2875 UTC", RUNWAYS)
    assert "qnh" not in p and "dewpoint" not in p and "time" not in p


def test_wind_forms():
    assert parse("wind 250 degrees 8 knots gusting 18")["wind"] == "250/8kt G18kt"
    assert parse("touchdown zone wind calm")["wind"] == "CALM"


def test_vote_over_real_loops():
    fields = vote([parse(t, RUNWAYS) for t in FIXTURE])
    assert fields["letter"]["value"] == "E" and fields["letter"]["status"] == "confirmed"
    assert fields["temperature"]["value"] == 28
    assert fields["dewpoint"]["value"] == 19
    assert fields["qnh"]["value"] == 1015


def test_vote_reports_conflict():
    fields = vote([{"qnh": 1015}, {"qnh": 1013}])
    assert fields["qnh"]["status"] == "conflict" and fields["qnh"]["value"] is None


def test_vote_foxtrot_all_fields_confirmed():
    texts = json.loads((Path(__file__).parent / "fixtures" / "llha_foxtrot.json").read_text())
    fields = vote([parse(t, RUNWAYS) for t in texts])
    assert {k: v["value"] for k, v in fields.items()} == {
        "letter": "F", "time": "0550", "runway": "33", "circuit": "right",
        "wind": "VRB/3kt", "visibility": "10 km+", "clouds": "FEW 3400ft",
        "temperature": 28, "dewpoint": 19, "qnh": 1015,
    }
    assert all(v["status"] == "confirmed" for v in fields.values())
