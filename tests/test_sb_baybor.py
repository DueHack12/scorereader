from __future__ import annotations

from scoreboards import baybor


def pk(first: int, body: str, size: int = 12) -> bytes:
    return bytes([first]) + body.encode().ljust(size - 1, b" ")


def mk():
    return baybor.PROTOCOLS["Baybor_Basketball"]()


def test_clock_possession_timeouts():
    p = mk()
    d = bytearray(pk(0x80, "\x00" * 1 + "12:34 p@ @"))
    d[1] = 0x20
    d[2:7] = b"12:34"
    d[7], d[8], d[9], d[10] = 112, ord("B"), 32, 64
    assert p.feed(bytes(d)) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondOnes"]) == (":", "1", "4")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == " "


def test_tenths_clock():
    p = mk()
    d = bytearray(b" " * 12)
    d[0] = 0x80
    d[2:4] = b"09"
    d[4] = 32
    d[5] = ord("7")
    d[9] = 112
    d[8] = ord("C")
    p.feed(bytes(d))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockTenthsSecond"]) == (".", "0", "7")
    assert c["GuestPossession"] == ">" and c["HomeTimeouts"] == "3"


def test_shot_score_foul_horn_names():
    p = mk()
    p.feed(pk(0x81, "124"))
    p.feed(bytes([0x82]) + b"105" + b"098" + b"B" + b"4" + b"B" + b"  ")
    p.feed(bytes([0x83]) + b"  " + b"  " + b"  " + b"07" + b"11" + b" ")
    c = p.snapshot()
    assert c["ShotClockSecondTens"] == "2" and c["ShotClockSecondOnes"] == "4"
    assert (c["HomeScoreHundreds"], c["HomeScoreOnes"], c["GuestScoreTens"]) == ("1", "5", "9")
    assert c["HomeBonus"] == "B" and c["GuestBonus"] == "B" and c["Period"] == "4"
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == ("0", "7", "1", "1")
    p.feed(bytes([146]) + b"EAGLES" + b" " * 7)
    p.feed(bytes([147]) + b"LIONS" + b" " * 8)
    p.feed(bytes([148]) + b"1" + b" " * 10)
    c = p.snapshot()
    assert c["HomeTeamName"].strip() == "EAGLES" and c["GuestTeamName"].strip() == "LIONS" and c["Horn"] == "H"


def test_play_clock_status_and_shot_tenths():
    p = mk()
    d = bytearray(b" " * 12)
    d[0], d[1], d[2], d[3], d[9] = 0x81, ord("2"), ord("8"), ord("5"), ord("1")
    p.feed(bytes(d))
    c = p.snapshot()
    assert c["ShotClockSecondTens"] == " " and c["ShotClockTenthsSecond"] == "5" and c["PlayClockStatusInternal"] == "R"


def test_garbage_split_and_partial():
    p = mk()
    d = pk(0x82, "000000 4 ")
    assert p.feed(b"abc\x01" + d[:5]) == 0
    assert p.feed(d[5:]) == 1
    assert p.feed(b"no start byte here") == 0
    assert p.snapshot()["Period"] == "4"
