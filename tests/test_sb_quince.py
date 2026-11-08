"""Quince basketball: 01 00 LEN <data> CR with BCD fields."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def frame(*body):
    """body = bytes starting at p[1]; LEN is added."""
    p = bytes([len(body) + 1]) + bytes(body)
    return b"\x01\x00" + p + b"\x0d"


def run(data):
    p = create("Quince_Basketball")
    p.feed(data)
    return p


def test_scores_fouls_timeouts():
    p = run(frame(0, 0, 0x36, 0x01, 0x23, 0, 0))
    p.feed(frame(0, 0, 0x46, 0x00, 0x87, 0, 0))
    p.feed(frame(0, 0, 0x38, 0x12, 0, 0, 0))
    p.feed(frame(0, 0, 0x48, 0x0F, 0, 0, 0))
    p.feed(frame(0, 0, 0x33, 0x03, 0, 0, 0))
    p.feed(frame(0, 0, 0x43, 0x02, 0, 0, 0))
    check(p.snapshot(), HomeScoreHundreds="1", HomeScoreTens="2", HomeScoreOnes="3", GuestScoreHundreds="0",
          GuestScoreTens="8", GuestScoreOnes="7", HomeFoulTens="1", HomeFoulOnes="2", GuestFoulTens="0",
          GuestFoulOnes=" ", HomeTimeouts="3", GuestTimeouts="2", EventId="Basketball")


def test_clock_modes():
    p = run(frame(0, 0, 0x02, 0, 0, 0x12, 0x34, 0x50))
    check(p.snapshot(), ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
          ClockSecondOnes="4", ClockTenthsSecond="0")
    p.feed(frame(0, 0, 0x02, 0, 0, 0x00, 0x05, 0x70))
    check(p.snapshot(), ClockMode=".", ClockSecondTens="0", ClockSecondOnes="5", ClockTenthsSecond="7")


def test_clock_status_and_shot_clock():
    p = run(frame(0xC5, 0, 1, 0, 0, 0))
    check(p.snapshot(), InternalClockStatus="R")
    p.feed(frame(0xC5, 0, 0, 0, 0, 0))
    check(p.snapshot(), InternalClockStatus="S")
    p.feed(frame(0, 0x45, 1, 0, 0x24, 0x50))  # p[3]==1: digits at 5, 6
    check(p.snapshot(), ShotClockSecondTens="2", ShotClockSecondOnes="4", ShotClockTenthsSecond="5")
    p.feed(frame(0, 0x45, 0, 0, 0, 0x13, 0x20))  # otherwise at 6, 7
    check(p.snapshot(), ShotClockSecondTens="1", ShotClockSecondOnes="3", ShotClockTenthsSecond="2")
    before = dict(p.snapshot())
    p.feed(bytes([1, 0]) + bytes([7, 0, 0x45, 0, 0, 0, 0x91]) + b"\x0d")  # length 7 ending 0x91: ignored
    assert p.snapshot() == before


def test_players_and_names():
    p = run(frame(0, 0, 0x53, 0x07, 0x12, 0x23, 0x34, 0x45))
    p.feed(frame(0, 0, 0x63, 0x08, 0x13, 0x24, 0x35, 0x46))
    p.feed(frame(0, 0, 0x51, 0x10, 0x11, 0x12, 0x13, 0x14))
    p.feed(frame(0, 0, 0x61, 0x20, 0x21, 0x22, 0x23, 0x24))
    p.feed(frame(0, 0, 0x54, 0x12, 0x34, 0x50, 0))
    p.feed(frame(0, 0, 0x64, 0x54, 0x32, 0x10, 0))
    p.feed(frame(0, 0, 0x31, 0, *b"HAWKS", 0, 0))
    p.feed(frame(0, 0, 0x41, 0, *b"LIONS", 0, 0))
    check(p.snapshot(), HomePlayer1="07", HomePlayer5="45", GuestPlayer1="08", GuestPlayer5="46",
          HomePlayer1Points="10", HomePlayer5Points="14", GuestPlayer3Points="22", HomePlayer1FoulNumber="1",
          HomePlayer4FoulNumber="4", HomePlayer5FoulNumber="5", GuestPlayer1FoulNumber="5",
          GuestPlayer5FoulNumber="1", HomeTeamName="HAWKS", GuestTeamName="LIONS")


def test_garbage_split_and_bad_length():
    data = b"\xff\x55" + frame(0, 0, 0x36, 0x01, 0x23, 0, 0)
    p = create("Quince_Basketball")
    p.feed(data[:4])
    p.feed(data[4:8])
    assert p.packets == 0
    p.feed(data[8:])
    assert p.packets == 1 and p.snapshot()["HomeScoreOnes"] == "3"
    p.feed(b"\x01\x00\x05abcdef\x0d")  # CR not where LEN says
    assert p.bad == 1
    p.feed(frame(0, 0, 0x36, 0x00, 0x45, 0, 0))
    assert p.packets == 2 and p.snapshot()["HomeScoreOnes"] == "5"
