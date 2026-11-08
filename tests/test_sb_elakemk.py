from __future__ import annotations

from scoreboards import elakemk


def pkt(typ: str, rest: bytes) -> bytes:
    return b"\xd3" + b"41" + typ.encode() + rest + b"\x0d"


def mk():
    return elakemk.PROTOCOLS["ElakEmk_Basketball"]()


def test_clock_minutes_and_seconds():
    p = mk()
    # packet[4]='P', [5] ' ', [6..7] minutes, [8] ':', [9..10] seconds, [11] ' ', [12] tenths
    assert p.feed(pkt("T", b"P 12:34 0")) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    p.feed(pkt("T", b"P    07 5"))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "0", "7", "5")


def test_timeouts_and_timeout_clock():
    p = mk()
    p.feed(pkt("T", b"O:" + b" 2" + b"  1" + b" "))
    c = p.snapshot()
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "1"
    p.feed(pkt("T", b"OT" + b" 45" + b" "))
    c = p.snapshot()
    assert c["TimeoutClockSecondTens"] == "4" and c["TimeoutClockSecondOnes"] == "5"


def test_scores_and_shot_clock():
    p = mk()
    p.feed(pkt("R", b"  105  098 "))
    c = p.snapshot()
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "9", "8")
    p.feed(pkt("A", b"T 24 "))
    c = p.snapshot()
    assert c["ShotClockSecondTens"] == "2" and c["ShotClockSecondOnes"] == "4"


def test_garbage_split_nul_and_header_check():
    p = mk()
    d = pkt("R", b"  105  098 ")
    assert p.feed(b"\x00\x00ab" + d[:6]) == 0
    assert p.feed(d[6:] + b"\x00") == 1
    assert p.feed(b"\xd3" + b"99Rxxxxxxxxxxxxxxx\x0d") == 0 and p.bad == 1
    assert p.feed(b"zz\x0d") == 0
