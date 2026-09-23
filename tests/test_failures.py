import json

from atis import failures


def make_record(letter="N", time="1050", heard="2026-09-23T10:05:19Z", wind=None):
    return {
        "letter": letter,
        "timing": {"heard_at": heard},
        "fields": {
            "letter": {"value": letter, "status": "confirmed", "readings": [letter]},
            "time": {"value": time, "status": "confirmed", "readings": [time]},
            "runway": {"value": "33", "status": "confirmed", "readings": ["33"]},
            "wind": {"value": wind, "status": "conflict" if wind is None else "confirmed", "readings": []},
            "temperature": {"value": 30, "status": "confirmed", "readings": [30]},
            "qnh": {"value": 1015, "status": "single", "readings": [1015]},
        },
        "transcripts": [{"text": "Haifa airport information November. Tree 20 degrees.", "confidence": 0.7}],
        "metar": {"raw": "METAR LLHA 231050Z AUTO 31010KT 9999 FEW040 30/18 Q1015"},
    }


def test_missing_required():
    assert failures.missing_required(make_record()["fields"]) == ["wind"]
    assert failures.missing_required(make_record(wind="320/11kt")["fields"]) == []
    assert failures.missing_required({}) == ["runway", "wind", "temperature", "qnh"]


def test_record_once_per_broadcast(tmp_path):
    (tmp_path / "latest.mp3").write_bytes(b"mp3")
    assert failures.record(tmp_path, make_record(), ["wind"]) == "20260923T1005Z-N"
    # Same letter and issue time three minutes later: not stored again.
    assert failures.record(tmp_path, make_record(heard="2026-09-23T10:08:00Z"), ["wind"]) is None
    # A new broadcast is.
    assert failures.record(tmp_path, make_record(letter="O", time="1150", heard="2026-09-23T11:52:00Z"), ["wind"])
    index = json.loads((tmp_path / "failed" / "index.json").read_text())
    assert [e["key"] for e in index] == ["O-1150", "N-1050"]
    assert (tmp_path / "failed" / "20260923T1005Z-N.mp3").read_bytes() == b"mp3"


def test_old_failures_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(failures, "KEEP", 2)
    (tmp_path / "latest.mp3").write_bytes(b"mp3")
    for i, letter in enumerate("ABC"):
        failures.record(tmp_path, make_record(letter=letter, heard=f"2026-09-23T1{i}:00:00Z"), ["wind"])
    names = sorted(p.name for p in (tmp_path / "failed").glob("*.mp3"))
    assert names == ["20260923T1100Z-B.mp3", "20260923T1200Z-C.mp3"]


def test_report_opens_one_issue_per_failure(tmp_path, monkeypatch):
    out = tmp_path / "LLHA"
    out.mkdir()
    (out / "latest.mp3").write_bytes(b"mp3")
    failures.record(out, make_record(), ["wind"])
    posted = []
    monkeypatch.setattr(failures, "_post", lambda url, token, payload: posted.append(payload) or {"html_url": "https://x/1"})
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "arielf-idra/digital-atis-isr")

    assert failures.report(tmp_path, "LLHA") == 1
    assert failures.report(tmp_path, "LLHA") == 0          # already reported
    assert posted[0]["title"] == "LLHA information N (1050Z): could not read wind"
    assert "gh-pages/data/LLHA/failed/20260923T1005Z-N.mp3" in posted[0]["body"]
    assert "Tree 20 degrees" in posted[0]["body"]


def test_report_without_token_does_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert failures.report(tmp_path, "LLHA") == 0
