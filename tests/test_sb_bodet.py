"""Bodet basketball and volleyball: SOH <addr> STX <message> ETX frames."""
from scoreboards import bodet, create


def frame(msg: bytes) -> bytes:
    return bytes([1, 0x30, 2]) + msg + b"\x03"


def run(pid, data):
    p = create(pid)
    p.feed(data)
    return p


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


CLOCK = b"018" + bytes([0x34]) + b"x1234" + b"23" + b"xx" + b"2"


def test_basketball_clock():
    c = run("Bodet_Basketball", frame(CLOCK)).snapshot()
    check(c, ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3", ClockSecondOnes="4",
          ClockTenthsSecond="0", InternalClockStatus="R", Horn="H", HomeTimeouts="2", GuestTimeouts="3",
          HomeFullTimeouts="2", GuestFullTimeouts="3", Period="2", EventId="Basketball")


def test_basketball_stopped_and_d_keeps_clock():
    p = run("Bodet_Basketball", frame(CLOCK))
    p.feed(frame(b"018" + bytes([0x32]) + b"x12D4" + b"23" + b"xx" + b"2"))
    check(p.snapshot(), InternalClockStatus="S", Horn=" ", ClockSecondTens="3")


def test_basketball_shot_clock():
    c = run("Bodet_Basketball", frame(b"050" + bytes([0x30]) + b"24")).snapshot()
    check(c, ShotClockSecondTens="2", ShotClockSecondOnes="4", ShotClockTenthsSecond=" ", PlayClockStatusInternal="R")
    c = run("Bodet_Basketball", frame(b"050" + bytes([0x92]) + b"95")).snapshot()
    check(c, ShotClockSecondTens="0", ShotClockSecondOnes="9", ShotClockTenthsSecond="5", PlayClockStatusInternal="S")


def test_basketball_scores_zero_blank():
    c = run("Bodet_Basketball", frame(b"030" + b"0" + b"105" + b"  7")).snapshot()
    check(c, HomeScoreHundreds="1", HomeScoreTens="0", HomeScoreOnes="5", GuestScoreHundreds=" ",
          GuestScoreTens=" ", GuestScoreOnes="7")
    c = run("Bodet_Basketball", frame(b"030" + b"0" + b"  0" + b" 12")).snapshot()
    check(c, HomeScoreHundreds=" ", HomeScoreTens=" ", HomeScoreOnes=" ", GuestScoreTens="1", GuestScoreOnes="2")


def test_basketball_fouls_final_minute_names_and_default():
    p = run("Bodet_Basketball", frame(b"031" + b"0" + b"x4x" + b"6" + b"12" + b"3"))
    check(p.snapshot(), HomeFoulOnes="4", GuestFoulOnes="6", FoulPlayerTens="1", FoulPlayerOnes="2",
          FoulPlayerNumberOfFouls="3")
    p.feed(frame(b"036" + b"05" + b"9" + b"7"))  # p3='0' p4='5'? see layout: p[3],p[4],p[5]
    check(p.snapshot(), ClockMode=".", ClockMinutesTens="0", ClockSecondTens="0", ClockSecondOnes="5", ClockTenthsSecond="9")
    p.feed(frame(b"098" + b"HAWKS   "))
    p.feed(frame(b"099" + b"EAGLES  "))
    check(p.snapshot(), HomeTeamName="HAWKS   ", GuestTeamName="EAGLES  ")
    p.feed(frame(b"077" + b"xxxx"))  # unknown message clears possession
    check(p.snapshot(), HomePossession=" ", GuestPossession=" ")


def test_volleyball():
    flags = bytes([0x34])
    c = run("Bodet_Volleyball", frame(b"006" + flags + b"x" + b"2" + b"1" + b"0" + b"2119" + b"10" + b"30")).snapshot()
    check(c, Set="2", HomeGamesWon="0", HomeScoreTens="2", HomeScoreOnes="1", GuestScoreTens="1",
          GuestScoreOnes="9", HomeTimeout="1", GuestTimeout="0", TimeoutClockSecondTens="3",
          TimeoutClockSecondOnes="0", HomeServe="*", GuestServe=" ", InternalClockStatus="R", EventId="Volleyball")
    c = run("Bodet_Volleyball", frame(b"007" + bytes([0x32]) + b"x" + b"0512")).snapshot()
    check(c, ClockMinutesTens="0", ClockMinutesOnes="5", ClockSecondTens="1", ClockSecondOnes="2",
          GuestServe="*", HomeServe=" ", InternalClockStatus="S")
    c = run("Bodet_Volleyball", frame(b"008" + flags + b"x" + b"25" + b"21" + b"18" + b"25" + b"07" + b"05")).snapshot()
    check(c, HomeScoreSet1="25", GuestScoreSet1="21", HomeScoreSet2="18", GuestScoreSet2="25",
          HomeScoreSet3="07", GuestScoreSet3="05")


def test_garbage_and_split():
    data = b"\xff\x10junk" + frame(CLOCK)
    p = create("Bodet_Basketball")
    p.feed(data[:7])
    p.feed(data[7:12])
    p.feed(data[12:])
    assert p.packets == 1
    assert p.snapshot()["ClockMinutesTens"] == "1"
    assert bodet.PROTOCOLS


def test_rejects_frame_without_stx():
    p = run("Bodet_Basketball", b"\x01\x30\x05abc\x03")
    assert p.bad == 1 and p.packets == 0
    p.feed(frame(CLOCK))
    assert p.packets == 1
