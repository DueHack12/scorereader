from __future__ import annotations

from scoreboards import lgr


def pkt(body: bytes) -> bytes:
    return b"\x02" + body + b"\x03"


def mk():
    return lgr.PROTOCOLS["LGR_Basketball"]()


def test_clock_minutes_and_shot():
    p = mk()
    assert p.feed(pkt(b"i" + b"0542" + b"1" + b"24" + b" " + b"R")) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == (":", "5", "4", "2")
    assert c["ShotClockSecondTens"] == "2" and c["InternalClockStatus"] == "R"


def test_clock_tenths_and_timeout_clock():
    p = mk()
    p.feed(pkt(b"i" + b"0007" + b"3" + b"45" + b" " + b"T"))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "0", "7", "3")
    assert c["TimeoutClockSecondTens"] == "4" and c["TimeoutClockSecondOnes"] == "5"
    assert "ShotClockSecondTens" not in c


def test_scores_fouls_possession():
    p = mk()
    p.feed(pkt(b"2" + b"105" + b"098"))
    p.feed(pkt(b"3" + b"07" + b"3" + b"2" + b"7" + b"11"))
    p.feed(pkt(b"*" + b"01"))
    c = p.snapshot()
    assert (c["HomeScoreHundreds"], c["HomeScoreOnes"], c["GuestScoreTens"]) == ("1", "5", "9")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulOnes"]) == ("0", "7", "1")
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "3" and c["Period"] == "2"
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "


def test_guest_possession_quirk():
    p = mk()
    p.feed(pkt(b"*" + b"2" + b"2"))
    assert p.snapshot()["GuestPossession"] == ">"


def test_garbage_split_and_short():
    p = mk()
    d = pkt(b"2" + b"105" + b"098")
    assert p.feed(b"\x7f\x03xx" + d[:3]) == 0
    assert p.feed(d[3:]) == 1
    assert p.feed(b"\x02\x03") == 0 and p.bad == 1  # too short
    assert p.feed(b"abc\x03") == 0  # ETX with no STX before it
