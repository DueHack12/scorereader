from __future__ import annotations

from scoreboards import esk


def pkt(typ: str, fields: dict, size: int = 60) -> bytes:
    b = bytearray(b" " * size)
    b[0], b[1], b[size - 1] = 0xF8, ord(typ), 0x0D
    for k, v in fields.items():
        b[k] = v if isinstance(v, int) else ord(v)
    return bytes(b)


def put(s: str, at: int) -> dict:
    return {at + i: ch for i, ch in enumerate(s)}


MAIN = {**put("12", 4), **put("34", 6), 3: "1", **put("105", 8), **put("098", 11), 14: "3", 15: "4", 16: "5",
        17: "2", 18: "1", 19: "1", 21: "1", **put("30", 46), **put("24", 48), 52: "1"}


def mk():
    return esk.PROTOCOLS["ESK_Basketball"]()


def test_main_packet():
    p = mk()
    assert p.feed(pkt("3", MAIN)) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert (c["HomeScoreHundreds"], c["HomeScoreOnes"], c["GuestScoreTens"]) == ("1", "5", "9")
    assert c["Period"] == "3" and c["HomeFoulOnes"] == "4" and c["GuestFoulOnes"] == "5"
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "1" and c["Horn"] == "H"
    assert c["TimeoutClockMinutesOnes"] == "1" and c["TimeoutClockSecondTens"] == "3"
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("2", "4", " ")


def test_seconds_mode_and_short_minutes():
    p = mk()
    f = {**MAIN, **put("59", 4), **put("7 ", 6), 52: "."}
    p.feed(pkt("7", f))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "5", "9", "7")
    assert c["ShotClockSecondTens"] == " " and c["ShotClockSecondOnes"] == "2" and c["ShotClockTenthsSecond"] == "4"
    assert "HomeScoreOnes" not in c  # types 7/8 only carry clocks
    p.feed(pkt("8", {**MAIN, **put(" 5", 4), **put("07", 6)}))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"]) == (":", "0", "5", "0")


def test_blank_clock_left_alone_and_short_ignored():
    p = mk()
    p.feed(pkt("3", MAIN))
    p.feed(pkt("3", {**MAIN, **put("  ", 4), **put("  ", 6)}))
    assert p.snapshot()["ClockMinutesOnes"] == "2"
    p.feed(b"\xf8" + b"3" * 10 + b"\x0d")
    assert p.snapshot()["Period"] == "3"


def test_garbage_split_and_unframed():
    p = mk()
    d = pkt("3", MAIN)
    assert p.feed(b"xx\x0d" + d[:20]) == 0 and p.bad == 1
    assert p.feed(d[20:]) == 1
