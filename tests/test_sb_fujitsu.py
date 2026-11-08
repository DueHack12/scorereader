"""Fujitsu basketball: 100-byte STX ... CR packets."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def pkt(kind, fields):
    b = bytearray(b" " * 100)
    b[0], b[1], b[99] = 2, ord(kind), 13
    for i, s in fields.items():
        b[i : i + len(s)] = s.encode()
    return bytes(b)


GAME = {2: "12:34", 8: "5", 9: ".", 10: "3", 13: "HOMGST", 19: "2", 20: "2", 21: "102", 24: " 98", 27: "4", 28: "5",
        29: "3", 30: "2"}


def test_game_packet():
    p = create("Fujitsu_Basketball")
    p.feed(pkt("1", GAME))
    check(p.snapshot(), ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
          ClockSecondOnes="4", ClockTenthsSecond=" ", ShotClockSecondTens=" ", ShotClockSecondOnes="5",
          ShotClockTenthsSecond="3", HomeTeamName="HOM", GuestTeamName="GST", Period="2", GuestPossession=">",
          HomePossession=" ", HomeScoreHundreds="1", HomeScoreTens="0", HomeScoreOnes="2",
          GuestScoreHundreds=" ", GuestScoreTens="9", GuestScoreOnes="8", HomeFoulOnes="4", GuestFoulOnes="5",
          HomeTimeouts="3", GuestTimeouts="2", EventId="Basketball")


def test_seconds_clock_and_home_possession():
    p = create("Fujitsu_Basketball")
    p.feed(pkt("1", {2: "45", 4: ".", 5: "7", 9: "2", 10: "4"}))
    check(p.snapshot(), ClockMode=".", ClockSecondTens="4", ClockSecondOnes="5", ClockTenthsSecond="7",
          ShotClockSecondTens="2", ShotClockSecondOnes="4", HomePossession="<", GuestPossession=" ")


def test_player_packets():
    p = create("Fujitsu_Basketball")
    p.feed(pkt("2", {13: "0102030405", 45: "10121416" "18", 77: "12345"}))
    p.feed(pkt("3", {13: "2122232425", 45: "20222426" "28", 77: "54321"}))
    check(p.snapshot(), HomePlayer1="01", HomePlayer5="05", HomePlayer1Points="10", HomePlayer5Points="18",
          HomePlayer1FoulNumber="1", HomePlayer5FoulNumber="5", GuestPlayer1="21", GuestPlayer4Points="26",
          GuestPlayer2FoulNumber="4")


def test_garbage_split_and_length_reject():
    data = b"\r\x00junk" + pkt("1", GAME)
    p = create("Fujitsu_Basketball")
    for i in range(0, len(data), 37):
        p.feed(data[i : i + 37])
    assert p.packets == 1
    p.feed(b"\x02" + b"x" * 20 + b"\r")  # wrong length
    assert p.bad == 1
    p.feed(pkt("1", {19: "3"}))
    assert p.packets == 2 and p.snapshot()["Period"] == "3"
