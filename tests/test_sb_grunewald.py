from __future__ import annotations

from scoreboards import grunewald


def pkt(body: bytes) -> bytes:
    b = b"#" + body.ljust(23, b" ")[:23] + b"\r"
    assert len(b) == 25
    return b


def mk():
    return grunewald.PROTOCOLS["Grunewald_basketball"]()


def body(**kw) -> bytes:
    """Index k here is packet[k + 1]."""
    b = bytearray(b" " * 23)
    b[0] = ord("2")          # period
    b[1] = ord("C")          # running
    b[2:6] = b"1234"         # clock
    b[7:10] = b"245"         # shot clock
    b[10:13] = b"105"        # home
    b[13:16] = b"098"        # guest
    b[16] = ord("A")         # shot clock shown
    b[18], b[19] = ord("2"), ord("3")
    b[20] = ord("<")
    b[21], b[22] = ord("4"), ord("5")
    return bytes(b)


def test_minutes():
    p = mk()
    assert p.feed(pkt(body())) == 1
    c = p.snapshot()
    assert c["Period"] == "2" and c["InternalClockStatus"] == "R"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", " ")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("2", "4", "5")
    assert (c["HomeScoreHundreds"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "5", "9", "8")
    assert (c["HomeTimeouts"], c["GuestTimeouts"], c["HomeFoulOnes"], c["GuestFoulOnes"]) == ("2", "3", "4", "5")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "


def test_tenths_stopped_shot_off_guest_arrow():
    p = mk()
    b = bytearray(body())
    b[1] = ord("c")
    b[2:7] = b"00785"
    b[16] = ord("N")
    b[20] = ord(">")
    p.feed(pkt(bytes(b)))
    c = p.snapshot()
    assert c["InternalClockStatus"] == "S"
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "7", "8", "5")
    assert c["ShotClockSecondTens"] == " " and c["GuestPossession"] == ">" and c["HomePossession"] == " "


def test_garbage_split_and_length():
    p = mk()
    d = pkt(body())
    assert p.feed(b"xx\r" + d[:10]) == 0
    assert p.feed(d[10:]) == 1
    assert p.feed(b"#12345\r") == 0 and p.bad == 1
    assert p.feed(b"abc\r") == 0 and p.bad == 1
