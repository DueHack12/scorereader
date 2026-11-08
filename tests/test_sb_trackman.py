from __future__ import annotations

from scoreboards import trackman

MSG = b'{"Time":"2024-05-01T12:00:00Z","Pitch":{"TrackStartTime":"2024-05-01T12:00:00Z","Speed":"87.34"}}'


def mk():
    return trackman.PROTOCOLS["Trackman_BaseballPitchSpeed"]()


def test_speed_truncated():
    p = mk()
    assert p.feed(MSG) == 1
    c = p.snapshot()
    assert c["PitchSpeed"] == "87" and c["EventId"] == "Baseball" and p.contract_name == "BaseballSoftball"


def test_numeric_and_missing():
    p = mk()
    p.feed(b'{"Pitch":{"Speed":91.2}}')
    assert p.snapshot()["PitchSpeed"] == "91"
    p.feed(b'{"Time":"x"}')
    assert p.snapshot()["PitchSpeed"] == ""


def test_split_datagram_accumulates():
    p = mk()
    assert p.feed(MSG[:30]) == 1
    p.feed(MSG[30:])
    assert p.snapshot().get("PitchSpeed") == "87"


def test_garbage_ignored_then_recovers():
    p = mk()
    p.feed(b"\x00\xffnot json")
    assert "PitchSpeed" not in p.snapshot()
    p.feed(MSG)
    assert p.snapshot()["PitchSpeed"] == "87"
    p.feed(b"")
    p.feed(b"[1,2]")
    assert p.snapshot()["PitchSpeed"] == "87"
