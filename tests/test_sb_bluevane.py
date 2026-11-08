"""Blue Vane basketball (normal and swapped teams): STX <16 bytes> ETX."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def frame(flags=0x22, clock=b"1234", **over):
    b = bytearray(clock + b"34" + b"4538" + b"24" + b"21" + b"3" + bytes([flags]))
    for k, v in over.items():
        b[int(k[1:])] = v
    return b"\x02" + bytes(b) + b"\x03"


def test_normal_layout():
    p = create("BlueVane_Basketball")
    p.feed(frame())
    check(p.snapshot(), ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
          ClockSecondOnes="4", ClockTenthsSecond="0", HomeFoulOnes="3", GuestFoulOnes="4", HomeScoreTens="4",
          HomeScoreOnes="5", HomeScoreHundreds="1", GuestScoreTens="3", GuestScoreOnes="8",
          GuestScoreHundreds=" ", ShotClockSecondTens="2", ShotClockSecondOnes="4", ShotClockTenthsSecond=" ",
          HomeTimeouts="2", GuestTimeouts="1", Period="3", Horn="H", EventId="Basketball")


def test_swapped_layout_is_already_swapped():
    p = create("BlueVane_Basketball_SwappedTeamsInfo")
    p.feed(frame())
    check(p.snapshot(), GuestFoulOnes="3", HomeFoulOnes="4", GuestScoreTens="4", GuestScoreOnes="5",
          GuestScoreHundreds="1", HomeScoreTens="3", HomeScoreOnes="8", HomeScoreHundreds=" ",
          GuestTimeouts="2", HomeTimeouts="1", ShotClockTenthsSecond="0", Period="3", Horn="H")


def test_hundreds_rule_and_flags():
    p = create("BlueVane_Basketball")
    p.feed(frame(flags=0x30, i6=ord("9"), i7=ord("5")))  # both hundreds flags; home 95 has a nine -> no hundreds
    check(p.snapshot(), HomeScoreHundreds=" ", GuestScoreHundreds="1", Horn=" ")


def test_under_a_minute_and_tenths_shot_clock():
    p = create("BlueVane_Basketball")
    p.feed(frame(flags=0x44, clock=b"09 5"))
    check(p.snapshot(), ClockMode=".", ClockMinutesTens="0", ClockSecondTens="0", ClockSecondOnes="9",
          ClockTenthsSecond="5", ShotClockSecondTens=" ", ShotClockSecondOnes="2", ShotClockTenthsSecond="4")
    p.feed(frame(clock=b"0  0"))
    check(p.snapshot(), ClockMode=":", ClockSecondTens="0")  # blank digits read as zero


def test_garbage_split_and_short_reject():
    data = b"\x05\x03junk" + frame()
    p = create("BlueVane_Basketball")
    p.feed(data[:5])
    p.feed(data[5:15])
    p.feed(data[15:])
    assert p.packets == 1 and p.bad == 0
    p.feed(b"\x02short\x03")
    assert p.bad == 1 and p.packets == 1
