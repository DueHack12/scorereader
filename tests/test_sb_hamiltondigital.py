from __future__ import annotations

from scoreboards import hamiltondigital


def ascii_pkt(sep: bytes = b":") -> bytes:
    b = bytearray(b" " * 30)
    b[0] = ord("T")
    b[1:3] = b"12"
    b[3:4] = sep
    b[4:6] = b"34"
    b[7:9], b[10:12] = b"02", b"15"
    b[13:15], b[16:18] = b"01", b"59"
    b[19:21], b[22:24] = b"00", b"30"
    b[25:27], b[28:30] = b"11", b"45"
    return bytes(b) + b"\n"


def mk():
    return hamiltondigital.PROTOCOLS["HamiltonDigital_Hockey"]()


def test_ascii_minutes():
    p = mk()
    assert p.feed(ascii_pkt()) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", "0")
    assert (c["HomePenaltyPlayer1ClockMinutesTens"], c["HomePenaltyPlayer1ClockMinutesOnes"],
            c["HomePenaltyPlayer1ClockSecondTens"], c["HomePenaltyPlayer1ClockSecondOnes"]) == ("0", "2", "1", "5")
    assert c["GuestPenaltyPlayer1ClockSecondTens"] == "5" and c["HomePenaltyPlayer2ClockSecondTens"] == "3"
    assert c["GuestPenaltyPlayer2ClockMinutesOnes"] == "1" and c["GuestPenaltyPlayer2ClockSecondOnes"] == "5"
    assert c["EventId"] == "Hockey" and p.contract_name == "HockeyLacrosse"


def test_tenths_mode():
    p = mk()
    p.feed(ascii_pkt(b"."))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "1", "2", "3")


def test_bcd_variant():
    p = mk()
    b = bytearray(b"\x0f" * 30)
    b[0] = 0xD4
    b[1:3] = bytes([0x01, 0x02])
    b[3] = ord(":")
    b[4:6] = bytes([0x03, 0xA4])
    p.feed(bytes(b) + b"\n")
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "2", "3", "4")
    assert c["HomePenaltyPlayer1ClockMinutesTens"] == " "


def test_garbage_split_bad_code_short():
    p = mk()
    d = ascii_pkt()
    assert p.feed(d[:10]) == 0
    assert p.feed(d[10:]) == 1
    assert p.feed(b"X" + b"1" * 29 + b"\n") == 0 and p.bad == 1
    assert p.feed(b"\n") == 0 and p.bad == 2
    p.feed(b"Tshort\n")
    assert p.snapshot()["ClockMinutesOnes"] == "2"
