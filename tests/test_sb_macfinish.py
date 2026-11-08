from __future__ import annotations

from scoreboards import macfinish


def mk():
    return macfinish.PROTOCOLS["MacFinish_Basketball"]()


def test_clock_and_shot():
    p = mk()
    assert p.feed(b"D" + b"1234" + b"24" + b"\r") == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == (":", "1", "2", "3", "4", "2", "4")


def test_garbage_split_and_rejects():
    p = mk()
    d = b"D" + b"0959" + b"  " + b"\r"
    assert p.feed(d[:3]) == 0
    assert p.feed(d[3:]) == 1
    assert p.snapshot()["ClockMinutesOnes"] == "9"
    assert p.feed(b"X1234\r") == 0 and p.bad == 1
    assert p.feed(b"\r") == 0 and p.bad == 2
    p.feed(b"D12\r")  # too short: ignored
    assert p.snapshot()["ClockMinutesOnes"] == "9"
