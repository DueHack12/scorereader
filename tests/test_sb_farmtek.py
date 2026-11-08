from __future__ import annotations

from scoreboards import farmtek


def mk():
    return farmtek.PROTOCOLS["Farmtek_Timing"]()


def test_timer():
    p = mk()
    assert p.feed(b"012.345\r") == 1
    c = p.snapshot()
    assert (c["ClockSecondHundreds"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockMode"],
            c["ClockTenthsSecond"], c["ClockHundredths"], c["ClockMilliseconds"]) == ("0", "1", "2", ".", "3", "4", "5")
    assert c["EventId"] == "Timer" and p.contract_name == "Timer"
    assert p.decoder.parse_type == "OnlySecondsClock"


def test_split_and_length_rejection():
    p = mk()
    assert p.feed(b"99") == 0
    assert p.feed(b"9.123\r") == 1
    assert p.feed(b"12.34\r") == 0 and p.bad == 1
    assert p.feed(b"001.2345\r") == 0 and p.bad == 2
    assert p.snapshot()["ClockSecondHundreds"] == "9"


def test_garbage_before_frame_is_part_of_it():
    p = mk()
    assert p.feed(b"x012.345\r") == 0  # 8 bytes: rejected, resync on the next frame
    assert p.feed(b"012.345\r") == 1
