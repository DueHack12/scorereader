from __future__ import annotations

from scoreboards import colosseo
from scoreboards.common import xor8


def frame(typ: int, data: bytes) -> bytes:
    body = bytes([1, len(data), typ]) + data
    return body + bytes([(xor8(body) | 0x80)]) + b"\x03"


def mk():
    return colosseo.PROTOCOLS["Colosseo_basketball"]()


def test_clock_minutes():
    p = mk()
    assert p.feed(frame(1, b"R3P12:34")) == 1  # data from byte 3
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", " ")
    assert c["Period"] == "3"


def test_clock_tenths():
    p = mk()
    p.feed(frame(1, b"S2P07.4"[:0] + b"S" + b"1" + b"P" + b"07" + b"." + b"4"))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "0", "7", "4")
    assert c["ClockMinutesTens"] == " " and c["Period"] == "1"


def test_scores_possession():
    p = mk()
    p.feed(frame(2, b"105" + b"098" + b"\x20" * 6 + b"21" + b"34" + b"1"))
    c = p.snapshot()
    assert (c["HomeScoreHundreds"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "5", "9", "8")
    assert (c["HomeTimeouts"], c["GuestTimeouts"], c["HomeFoulOnes"], c["GuestFoulOnes"]) == ("2", "1", "3", "4")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    p.feed(frame(2, b"000" + b"000" + b"\x20" * 6 + b"00" + b"00" + b"2"))
    assert p.snapshot()["GuestPossession"] == ">"


def test_shot_and_timeout_clock():
    p = mk()
    p.feed(frame(17, b" 24"[:0] + b" " + b"24"))
    c = p.snapshot()
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("2", "4", " ")
    p.feed(frame(17, b"9" + b"." + b"3"))
    c = p.snapshot()
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == (" ", "9", "3")
    p.feed(frame(7, b" 45"))
    c = p.snapshot()
    assert (c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("4", "5")


def test_back_to_back_garbage_split_and_checksum():
    p = mk()
    a = frame(7, b" 12")
    b = frame(7, b" 34")
    assert p.feed(b"junk\x03" + a[:3]) == 0
    assert p.feed(a[3:] + b[:4]) == 1
    assert p.feed(b[4:]) == 1
    assert p.snapshot()["TimeoutClockSecondOnes"] == "4"
    bad = bytearray(a)
    bad[-2] ^= 0x01
    assert p.feed(bytes(bad)) == 0 and p.bad >= 1
    assert p.feed(a) == 1
    short = bytearray(a)
    short[1] = 9  # wrong length
    assert p.feed(bytes(short)) == 0
