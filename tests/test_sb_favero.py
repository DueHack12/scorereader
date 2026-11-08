"""Favero basketball: command byte >= 0x80 followed by 11 (or 13) ASCII bytes."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def pkt(cmd, text, size=12):
    return bytes([cmd]) + text.encode().ljust(size - 1, b" ")


def test_clock_possession_timeouts():
    p = create("Favero_Basketball")
    p.feed(pkt(0x80, " 12:34pA @"))
    check(p.snapshot(), ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
          ClockSecondOnes="4", ClockTenthsSecond="0", HomePossession="<", GuestPossession=" ",
          HomeTimeouts="1", GuestTimeouts=" ", EventId="Basketball")
    p.feed(pkt(0x80, " 09.5  BpC"))
    check(p.snapshot(), ClockMode=".", ClockMinutesTens="0", ClockSecondTens="0", ClockSecondOnes="9",
          ClockTenthsSecond="5", GuestPossession=">", HomePossession=" ", HomeTimeouts="2", GuestTimeouts="3")


def test_shot_clock_score_fouls_horn():
    p = create("Favero_Basketball")
    p.feed(pkt(0x81, "124" + "     1"))
    check(p.snapshot(), ShotClockSecondTens="2", ShotClockSecondOnes="4", ShotClockTenthsSecond=" ",
          PlayClockStatusInternal="R")
    p.feed(pkt(0x81, "293" + "     0"))
    check(p.snapshot(), ShotClockSecondTens=" ", ShotClockSecondOnes="9", ShotClockTenthsSecond="3",
          PlayClockStatusInternal="S")
    p.feed(pkt(0x82, "102 98B2 "))
    check(p.snapshot(), HomeScoreHundreds="1", HomeScoreTens="0", HomeScoreOnes="2", GuestScoreHundreds=" ",
          GuestScoreTens="9", GuestScoreOnes="8", HomeBonus="B", GuestBonus=" ", Period="2")
    p.feed(pkt(0x83, " 23  60405"))
    check(p.snapshot(), FoulPlayerTens="2", FoulPlayerOnes="3", FoulPlayerNumberOfFouls="6", HomeFoulTens="0",
          HomeFoulOnes="4", GuestFoulTens="0", GuestFoulOnes="5")
    p.feed(pkt(0x94, "1"))
    check(p.snapshot(), Horn="H")
    p.feed(pkt(0x94, "0"))
    check(p.snapshot(), Horn=" ")


def test_team_names_are_14_bytes():
    p = create("Favero_Basketball")
    p.feed(pkt(0x92, "HAWKS", 14) + pkt(0x93, "LIONS", 14) + pkt(0x82, "001 02 ", 12))
    check(p.snapshot(), HomeTeamName="HAWKS        ", GuestTeamName="LIONS        ", HomeScoreOnes="1")
    assert p.packets == 3


def test_garbage_and_split():
    data = b"junk\x00" + pkt(0x82, "102 98B2 ")
    p = create("Favero_Basketball")
    p.feed(data[:3])
    p.feed(data[3:9])
    assert p.packets == 0
    p.feed(data[9:])
    assert p.packets == 1 and p.snapshot()["HomeScoreOnes"] == "2"
    p.feed(b"no command byte here")  # nothing >= 0x80: discarded
    assert p.packets == 1 and not p.buf
