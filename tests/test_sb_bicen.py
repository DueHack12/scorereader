from __future__ import annotations

from scoreboards import bicen


def frame(**f) -> bytes:
    b = bytearray(160)
    b[0], b[1] = 0xFA, 0x44
    for k, v in f.items():
        b[int(k[1:])] = v
    s = sum(b[:158]) & 0xFFFF
    b[158], b[159] = s >> 8, s & 0xFF
    return bytes(b)


def mk():
    return bicen.PROTOCOLS["Bicen_Basketball"]()


BASE = dict(i52=0x10, i53=0x50, i54=0x98, i55=0x24, i56=0x01, i57=0x20, i58=0x34, i61=0x03, i60=0xFF, i62=0x0F,
            i63=0x02)


def test_minutes_mode():
    p = mk()
    assert p.feed(frame(**BASE)) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "9", "8")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4") and c["Period"] == "3"


def test_tenths_and_shot_tenths():
    p = mk()
    p.feed(frame(**{**BASE, "i58": 0x5F, "i63": 0x00, "i57": 0x70}))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "1", "7", "5")
    assert c["ShotClockSecondTens"] == " " and c["ShotClockSecondOnes"] == "2" and c["ShotClockTenthsSecond"] == "4"


def test_timeouts_and_fouls():
    p = mk()
    p.feed(frame(**{**BASE, "i60": 0x30, "i62": 0x0F}))
    c = p.snapshot()
    assert c["TimeoutClockSecondTens"] == "3" and c["TimeoutClockSecondOnes"] == "0"
    p.feed(frame(**{**BASE, "i60": 0xF7, "i62": 0x0F, "i63": 0x52}))
    c = p.snapshot()
    assert c["HomeFoulOnes"] == "7" and c["GuestFoulOnes"] == "5"
    assert c["TimeoutClockSecondTens"] == " "


def test_garbage_split_checksum():
    p = mk()
    d = frame(**BASE)
    assert p.feed(b"\xfa\x00junk" + d[:100]) == 0
    assert p.feed(d[100:]) == 1
    bad = bytearray(d)
    bad[159] ^= 1
    assert p.feed(bytes(bad)) == 0 and p.bad == 1
    assert p.feed(d + d[:50]) == 1
