from __future__ import annotations

from scoreboards import ultrascore


def frame(typ: int, total: int, fields: dict | None = None) -> bytes:
    b = bytearray(total)
    b[0], b[1], b[2], b[4] = 0xFE, 0xFF, typ, total - 6
    for k, v in (fields or {}).items():
        b[k] = v
    return bytes(b)


def mk():
    return ultrascore.PROTOCOLS["UltraScore"]()


GEN = {6: 0x03, 7: 17, 8: 12, 9: 34, 10: 5, 11: 24, 12: 7, 13: 255, 16: 65, 17: 58, 18: 7, 19: 12, 20: 2, 21: 3,
       22: 1, 23: 0}


def test_general():
    p = mk()
    assert p.feed(frame(1, 24, GEN)) == 1
    c = p.snapshot()
    assert c["Period"] == "3" and c["InternalClockStatus"] == "R"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == ("1", "2", "3", "4", "5")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("2", "4", "7")
    assert c["TimeoutClockSecondTens"] == " "
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("6", "5", "5", "8")
    assert (c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == ("7", "1", "2")
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "3"
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "


def test_clock_blank_and_stopped():
    p = mk()
    f = dict(GEN)
    f.update({8: 255, 11: 255, 7: 18})
    p.feed(frame(1, 24, f))
    c = p.snapshot()
    assert c["InternalClockStatus"] == "S" and c["ClockMinutesTens"] == " " and c["ShotClockSecondOnes"] == " "


def test_players():
    p = mk()
    f = {7: 23, 8: 14, 9: 2, 10: 11, 11: 4, 12: 1, 19: 44, 20: 9, 21: 3, 16: 99, 22: 55, 23: 20, 24: 5}
    p.feed(frame(2, 25, f))
    p.feed(frame(3, 25, {7: 10, 8: 2, 9: 1}))
    c = p.snapshot()
    assert (c["HomePlayer1"], c["HomePlayer1Points"], c["HomePlayer1FoulNumber"]) == ("23", "14", "2")
    assert (c["HomePlayer2"], c["HomePlayer2Points"]) == ("11", "04")
    assert c["HomePlayer4"] == "44" and c["HomePlayer4Points"] == "09"  # second triple wins
    assert c["HomePlayer5"] == "55" and c["HomePlayer5FoulNumber"] == "5"
    assert c["GuestPlayer1"] == "10"


def test_garbage_split_and_wait():
    p = mk()
    d = frame(1, 24, GEN)
    assert p.feed(b"\x00\xfe\x01" + d[:10]) == 0
    assert p.feed(d[10:]) == 1
    assert p.feed(d + d[:5]) == 1
    assert p.feed(d[5:]) == 1
    assert p.bad == 0
