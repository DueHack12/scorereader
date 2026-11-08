from __future__ import annotations

from scoreboards import prospecta


def frame(typ: int, data: bytes) -> bytes:
    body = bytes([0xD1, len(data) + 2, typ]) + data  # total = LEN + 2 (incl. checksum)
    return body + bytes([sum(body) & 0xFF])


def mk():
    return prospecta.PROTOCOLS["Prospecta_Basketball"]()


def main22(mins=12, secs=34, flags=0b10110110, shot=24) -> bytes:
    # p[3] mins, p[4] secs, p[5] tenths nibbles, p[6] shot, p[7] timeout, p[8..9] scores, p[10] period, p[11] flags
    return frame(22, bytes([mins, secs, 0x50, shot, 0x15, 105, 98, 3, flags, 7, 21]))


def test_main_packet():
    p = mk()
    assert p.feed(main22()) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", "0")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    assert (c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("2", "1")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "9", "8")
    assert c["Period"] == "3"
    # flags 1011 0110: home poss 1, home bonus 0, home TO 3, guest poss 0, guest bonus 1, guest TO 2
    assert (c["HomePossession"], c["GuestPossession"], c["HomeBonus"], c["GuestBonus"]) == ("<", " ", " ", "B")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("3", "2")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "7", "2", "1")


def test_last_minute_and_shot_off():
    p = mk()
    p.feed(main22(mins=0, secs=45, shot=170))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "4", "5", "5")
    assert c["ShotClockSecondTens"] == " " and c["ShotClockSecondOnes"] == " "


def test_type4_fouls_and_names():
    p = mk()
    p.feed(frame(4, bytes([5, 9, 0, 30, 0x42])))
    c = p.snapshot()
    assert c["ClockMinutesTens"] == " " and c["ClockMinutesOnes"] == "5" and c["TimeoutClockSecondOnes"] == "6"
    p.feed(frame(13, bytes([7, 12, 23, 3])))
    c = p.snapshot()
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "7", "1", "2")
    assert (c["FoulPlayerTens"], c["FoulPlayerOnes"], c["FoulPlayerNumberOfFouls"]) == ("2", "3", "3")
    p.feed(frame(10, b"EAGLES  " + b"\x00\x00\x00\x00" + b"LIONS   "))
    c = p.snapshot()
    assert c["HomeTeamName"] == "EAGLES  " and c["GuestTeamName"] == "LIONS   "


def test_garbage_split_doubled_start_and_checksum():
    p = mk()
    d = main22()
    assert p.feed(b"\x01\x02" + d[:6]) == 0
    assert p.feed(d[6:]) == 1
    assert p.feed(b"\xd1" + d) == 1  # doubled start byte
    bad = bytearray(d)
    bad[-1] ^= 1
    assert p.feed(bytes(bad)) == 0 and p.bad == 1
    assert p.feed(d) == 1
