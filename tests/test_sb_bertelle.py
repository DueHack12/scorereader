from __future__ import annotations

from scoreboards import bertelle
from scoreboards.common import xor8


def pk(body: bytes) -> bytes:
    b = b":" + body
    return b + bytes([xor8(b)])


def mk():
    return bertelle.PROTOCOLS["Bertelle_Basketball"]()


def main(p5: int = 4, p8: int = ord("4")) -> bytes:
    b = bytearray(20)
    b[0:4] = bytes([ord(":"), ord("P"), ord("W"), 16])
    b[5] = p5
    b[6], b[7] = ord("2"), ord("3")  # guest hundreds, home hundreds
    b[8], b[9], b[10], b[11] = p8, ord("3"), ord("2"), ord("1")  # seconds ones .. minutes tens
    b[12], b[13], b[14], b[15] = ord("9"), ord("8"), ord("5"), ord("6")  # guest tens/ones, home tens/ones
    b[16], b[17], b[18], b[19] = ord("7"), ord("0"), ord("2"), ord("1")  # home fouls 07, guest fouls 12
    return bytes(b) + bytes([xor8(b)])


def test_main_minutes():
    p = mk()
    assert p.feed(main() + b":") == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("3", "5", "6")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "9", "8")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == ("0", "7", "1", "2")
    assert c["Period"] == "2"  # packet[5] = 4 -> (4 & 15) / 2


def test_tenths_and_odd_period_kept():
    p = mk()
    p.feed(main(p5=4) + b":")
    p.feed(main(p5=5, p8=15) + b":")
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", " ", "1", "2", "3")
    assert c["Period"] == "2"


def test_shot_clock():
    p = mk()
    p.feed(pk(bytes([ord("T"), ord("W"), 4]) + b"24") + b":")
    c = p.snapshot()
    assert c["ShotClockSecondTens"] == "2" and c["ShotClockSecondOnes"] == "4"


def test_checksum_garbage_split():
    p = mk()
    d = main()
    assert p.feed(b"\x01\x02" + d[:7]) == 0
    assert p.feed(d[7:] + b":") == 1
    bad = bytearray(d)
    bad[-1] ^= 0x10
    assert p.feed(bytes(bad) + b":") == 0 and p.bad >= 1
