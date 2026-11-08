from __future__ import annotations

from scoreboards import mondo


def pkt(*parts: bytes, typ: int = 1) -> bytes:
    return b"\x02" + bytes([typ]) + b"".join(parts) + b"\x03"


FULL = pkt(b"\x11" + b"12:34", b"\x15" + b"3", b"\x17" + b"105" + b"\x1f" + b"98" + b"\x0e" + b"07" + b"\x0f" + b"12")
IDS = ["Mondo_Basketball", "Cuma_Basketball"]


def test_both_ids_decode():
    for pid in IDS:
        p = mondo.PROTOCOLS[pid]()
        assert p.feed(FULL) == 1
        c = p.snapshot()
        assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
                c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
        assert c["Period"] == "3"
        assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
        assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "9", "8")
        assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "7", "1", "2")


def test_last_minute_shot_and_short_score():
    p = mondo.PROTOCOLS["Mondo_Basketball"]()
    p.feed(pkt(b"\x12" + b"00:" + b"07" + b".5", b"\x13" + b"14", b"\x17" + b"7" + b"\x1f" + b"3" + b"\x0e"))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "0", "7", "5")
    assert c["ShotClockSecondTens"] == "1" and c["ShotClockSecondOnes"] == "4"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreOnes"]) == (" ", "7", "3")


def test_garbage_split_and_bad_type():
    p = mondo.PROTOCOLS["Mondo_Basketball"]()
    assert p.feed(b"zz\x03\x01" + FULL[:7]) == 0
    assert p.feed(FULL[7:]) == 1
    assert p.feed(b"\x02\x09abc\x03") == 0 and p.bad == 1  # type byte above 6
    assert p.feed(b"\x02\x01\x11" + b"1") == 0  # incomplete
    p.feed(b"\x03")  # truncated clock field is ignored, never raises
    assert p.snapshot()["ClockMinutesTens"] == "1" and p.bad == 1
