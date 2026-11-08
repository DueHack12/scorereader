"""Skorled basketball: STX b1 LEN b3 b4 TYPE ... XOR (LEN + 4 bytes)."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def pkt(kind, fields, size=40):
    b = bytearray(b" " * size)
    b[0], b[2], b[5] = 2, size - 4, ord(kind)
    for i, s in fields.items():
        b[i : i + len(s)] = s.encode()
    x = 0
    for v in b[:-1]:
        x ^= v
    b[-1] = x
    return bytes(b)


GAME = {10: "12", 12: ":", 13: "34", 15: "24", 17: " ", 18: "T", 24: "2", 8: "8", 25: "087", 28: "05", 30: "9",
        31: "3", 32: "065", 35: " 4", 37: "2", 38: "1"}


def test_game_packet():
    p = create("Skorled_Basketball")
    p.feed(pkt("B", GAME))
    check(p.snapshot(), ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
          ClockSecondOnes="4", ClockTenthsSecond="0", ShotClockSecondTens="2", ShotClockSecondOnes="4",
          ShotClockTenthsSecond=" ", Period="2", Horn="H", HomeScoreHundreds="0", HomeScoreTens="8",
          HomeScoreOnes="7", HomeFoulTens="0", HomeFoulOnes="5", HomePossession="<", HomeBonus="B",
          HomeDoubleBonus=" ", HomeTimeouts="3", GuestScoreHundreds="0", GuestScoreTens="6", GuestScoreOnes="5",
          GuestFoulTens=" ", GuestFoulOnes="4", GuestPossession=" ", GuestBonus=" ", GuestDoubleBonus="B",
          GuestTimeouts="1", InternalClockStatus="R", EventId="Basketball")


def test_seconds_clock_tenths_shot_and_stop():
    p = create("Skorled_Basketball")
    p.feed(pkt("B", {10: "09", 12: ".", 13: "5", 15: "7", 16: "3", 17: ".", 18: "t", 8: "0"}))
    check(p.snapshot(), ClockMode=".", ClockMinutesTens="0", ClockSecondTens="0", ClockSecondOnes="9",
          ClockTenthsSecond="5", ShotClockSecondTens=" ", ShotClockSecondOnes="7", ShotClockTenthsSecond="3",
          InternalClockStatus="S", Horn=" ")
    p.feed(pkt("B", {10: "09", 12: ".", 13: "5", 18: "g", 22: "45"}))
    check(p.snapshot(), TimeoutClockSecondTens="4", TimeoutClockSecondOnes="5")


def test_player_packets():
    p = create("Skorled_Basketball")
    p.feed(pkt("C", {18: "1" "10" "2" "12" "3" "14" "4" "16" "5" "18"}, 34))
    p.feed(pkt("D", {14: "0102030405"}, 30))
    p.feed(pkt("E", {18: "5" "20" "4" "22" "3" "24" "2" "26" "1" "28"}, 34))
    p.feed(pkt("F", {14: "2122232425"}, 30))
    check(p.snapshot(), HomePlayer1FoulNumber="1", HomePlayer1Points="10", HomePlayer5FoulNumber="5",
          HomePlayer5Points="18", HomePlayer1="01", HomePlayer5="05", GuestPlayer1FoulNumber="5",
          GuestPlayer1Points="20", GuestPlayer5Points="28", GuestPlayer1="21", GuestPlayer5="25")


def test_garbage_split_and_checksum_reject():
    data = b"\x00junk" + pkt("B", GAME)
    p = create("Skorled_Basketball")
    p.feed(data[:3])
    p.feed(data[3:20])
    p.feed(data[20:])
    assert p.packets == 1
    bad = bytearray(pkt("B", {24: "9"}))
    bad[-1] ^= 0xFF
    p.feed(bytes(bad))
    assert p.bad >= 1 and p.snapshot()["Period"] == "2"
    p.feed(pkt("B", {24: "4"}))
    assert p.snapshot()["Period"] == "4"
