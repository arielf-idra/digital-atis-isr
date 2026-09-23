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


def test_golf_phrasing():
    texts = json.loads((Path(__file__).parent / "fixtures" / "llha_golf.json").read_text(encoding="utf-8-sig"))
    p = parse(texts[0] if isinstance(texts, list) else texts, RUNWAYS)
    assert p["letter"] == "G" and p["letter_end"] == "G"
    assert p["wind"] == "290/6kt V270-320"
    assert p["temperature"] == 29 and p["dewpoint"] == 18
    assert p["clouds"] == "FEW 3700ft" and p["qnh"] == 1015


def test_letter_from_scores_combines_start_and_end_mentions():
    from atis.consensus import letter_from_scores
    # Real scores from the Juliet broadcast (start and end of one loop), top candidates only.
    base = {l: -15.0 for l in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    start = {**base, "J": -9.07, "M": -10.76, "D": -11.03}
    end = {**base, "J": -8.75, "H": -11.42, "D": -11.49}
    text = {"value": None, "status": "conflict"}   # transcript said "dual yet" / "Joel yet"
    f = letter_from_scores([start, end], text)
    assert f["value"] == "J" and f["status"] == "confirmed" and f["votes"] == 2


def test_letter_from_scores_disagreeing_mentions_is_conflict():
    from atis.consensus import letter_from_scores
    base = {l: -15.0 for l in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
    f = letter_from_scores([{**base, "J": -9.0, "D": -9.2}, {**base, "D": -9.0, "J": -9.3}], None)
    assert f["status"] == "conflict" and f["value"] is None


def test_november_tree_is_three_in_headings():
    texts = json.loads((Path(__file__).parent / "fixtures" / "llha_november.json").read_text(encoding="utf-8"))
    assert normalize("Wind touchdown zone. Tree 20 degrees. 11 knots.") == "wind touchdown zone 320 degrees 11 knots"
    winds = [parse(t, RUNWAYS).get("wind") for t in texts]
    # The third loop wrote "3300 degrees" for three three zero; it is read as 330 too.
    assert winds == ["320/11kt V260-330"] * 3
    fields = vote([parse(t, RUNWAYS) for t in texts])
    assert fields["wind"]["value"] == "320/11kt V260-330" and fields["wind"]["status"] == "confirmed"
    assert fields["letter"]["value"] == "N" and fields["time"]["value"] == "1050"
    assert fields["temperature"]["value"] == 30 and fields["dewpoint"]["value"] == 18


def test_tree_as_three_elsewhere():
    assert parse("temperature tree zero dew point one eight")["temperature"] == 30
    assert parse("wind 250 degrees tree knots")["wind"] == "250/3kt"
    assert parse("QNH one zero one tree")["qnh"] == 1013


def test_issue_1_niner_heard_as_nine_or():
    # github.com/arielf-idra/digital-atis-isr/issues/1
    t = ("Haifa airport, information Romeo. Valid from 1450 UTC. Runway in use 33. Right hand circuit. "
         "Wind touchdown zone. Tree 20 degrees. 9 or knots. Varying between 280 and 340 degrees. "
         "Visibility 10 kilometers or more. Clouds view 3,000 feet, temperature 28, dew point 20, QNH 1014 millibars")
    p = parse(t, RUNWAYS)
    assert p["wind"] == "320/9kt V280-340" and p["visibility"] == "10 km+"
    assert parse("Valid from 09 or 50 UTC.")["time"] == "0950"


def test_issue_2_heading_written_with_extra_zero():
    # github.com/arielf-idra/digital-atis-isr/issues/2
    t = ("Wind touchdown zone 3300 degrees. 5 knots. Varying between 270 and 350 degrees. "
         "Clouds scattered 3300 feet.")
    p = parse(t, RUNWAYS)
    assert p["wind"] == "330/5kt V270-350"
    assert p["clouds"] == "SCT 3300ft"              # only headings are shortened
    assert "wind" not in parse("Wind 3700 degrees 5 knots")   # not a valid heading either way
