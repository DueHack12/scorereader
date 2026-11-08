from __future__ import annotations

from scoreboards import uno


def pkt(**f):
    b = bytearray(b" " * 26)
    b[0], b[25] = 0xF8, 0x0D
    for k, v in f.items():
        b[int(k[1:])] = v if isinstance(v, int) else ord(v)
    return bytes(b)


def build(idx: dict) -> bytes:
    return pkt(**{f"i{k}": v for k, v in idx.items()})


BASE = {4: "1", 5: "2", 6: "3", 7: "4", 8: "1", 9: "0", 10: "5", 11: "0", 12: "9", 13: "8", 14: "2", 15: "3",
        16: "4", 17: "2", 18: "1", 19: "0", 20: "1", 21: "0", 22: "0", 23: "2", 24: "4"}


def test_basketball_minutes_and_scores():
    p = uno.PROTOCOLS["Uno_Basketball"]()
    assert p.feed(build(BASE)) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondOnes"]) == (":", "1", "2", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert c["GuestScoreOnes"] == "8" and c["Period"] == "2" and c["HomeTimeouts"] == "2"
    assert c["HomeFoulOnes"] == "3" and c["GuestFoulTens"] == "4"  # ScoreConnect puts guest fouls in the tens slot
    assert c["ShotClockSecondTens"] == "0" and c["EventId"] == "Basketball"


def test_basketball_tenths_and_shot_clock():
    p = uno.PROTOCOLS["Uno_Basketball"]()
    p.feed(build({**BASE, 19: "1", 22: "1"}))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "1", "2", "3")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")


def test_generic():
    p = uno.PROTOCOLS["Uno_Generic"]()
    p.feed(build({**BASE, 19: "1", 20: "1", 21: "1", 22: "1"}))
    c = p.snapshot()
    assert c["ClockDigit1"] == "1" and c["HomeOnes"] == "5" and c["GuestFouls"] == "4"
    assert (c["ClockMode"], c["InternalClockStatus"], c["PlayClockStatusInternal"], c["PlayClockDisplay"]) == (".", "R", "R", "1")
    assert c["PlayClock"] == "24" and c["EventId"] == "Generic" and p.contract_name == "Generic"


def test_garbage_split_and_unframed():
    p = uno.PROTOCOLS["Uno_Basketball"]()
    d = build(BASE)
    assert p.feed(b"\x01\x02\x0d\x05" + d[:10]) == 0
    assert p.feed(d[10:]) == 1
    assert p.snapshot()["Period"] == "2"
    assert p.feed(b"abc\x0d") == 0  # CR with no F8 before it is dropped
    assert p.feed(d + d) == 2


def test_short_packet_ignored():
    p = uno.PROTOCOLS["Uno_Basketball"]()
    p.feed(b"\xf8abc\x0d")
    assert "HomeScoreOnes" not in p.snapshot()
