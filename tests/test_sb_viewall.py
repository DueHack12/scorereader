"""View All basketball: STX f0;f1;...;f12 ETX with twelve semicolons."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def frame(text: str) -> bytes:
    return b"\x02" + text.encode() + b"\x03"


FULL = "A;B;C;HOME;GUEST;12;34;2;R;05:30;24;3;14"


def test_full_packet():
    p = create("ViewAll_Basketball")
    p.feed(frame(FULL))
    check(p.snapshot(), HomeTeamName="HOME", GuestTeamName="GUEST", HomeScoreHundreds="0", HomeScoreTens="1",
          HomeScoreOnes="2", GuestScoreHundreds="0", GuestScoreTens="3", GuestScoreOnes="4", Period="2",
          InternalClockStatus="R", ClockMode=":", ClockMinutesTens="0", ClockMinutesOnes="5",
          ClockSecondTens="3", ClockSecondOnes="0", ClockTenthsSecond="0", ShotClockSecondTens="2",
          ShotClockSecondOnes="4", HomeFoulTens=" ", HomeFoulOnes="3", GuestFoulTens="1", GuestFoulOnes="4",
          EventId="Basketball")


def test_variants():
    p = create("ViewAll_Basketball")
    p.feed(frame("A;B;C;LONGTEAMNAME;;105;7;1Q2;S;09.5;;;"))
    check(p.snapshot(), HomeTeamName="LONGTEAM", HomeScoreHundreds="1", HomeScoreTens="0", HomeScoreOnes="5",
          GuestScoreHundreds="0", GuestScoreOnes="7", Period="Q", ClockMode=".", ClockMinutesTens="0",
          ClockSecondTens="0", ClockSecondOnes="9", ClockTenthsSecond="5", ShotClockSecondTens=" ",
          ShotClockSecondOnes="0")
    assert "GuestTeamName" not in p.snapshot()  # empty name field is ignored
    p.feed(frame("A;B;C;H;G;1;2;3;R;01:02;7;;"))
    check(p.snapshot(), ShotClockSecondTens=" ", ShotClockSecondOnes="7")


def test_garbage_split_and_semicolon_reject():
    data = b"xx" + frame(FULL)
    p = create("ViewAll_Basketball")
    p.feed(data[:10])
    p.feed(data[10:30])
    p.feed(data[30:])
    assert p.packets == 1 and p.bad == 0
    p.feed(frame("A;B;C;D"))
    assert p.bad == 1 and p.packets == 1
