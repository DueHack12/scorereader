from scoreboards import stramatel

P = stramatel.PROTOCOLS


def frame(sport, fields=None, n=54, ch=0xF8):
    """Standard frame: channel byte, sport character, blanks, CR. fields: index -> str or int."""
    b = bytearray(b" " * n)
    b[0] = ch
    b[1] = sport if isinstance(sport, int) else ord(sport)
    b[n - 1] = 13
    for i, v in (fields or {}).items():
        if isinstance(v, int):
            b[i] = v
        else:
            b[i : i + len(v)] = v.encode("latin-1")
    return bytes(b)


def be_wire(sport, fields=None):
    p = bytearray(frame(sport, fields, n=55))
    p[53] = 13  # frames end CR CR
    return b"\xf8" + bytes(p)


def decode(pid, wire):
    p = P[pid]()
    p.feed(wire)
    assert p.packets == 1 and p.bad == 0
    return p.decoder.c


def clock(c):
    return "".join(c[k] for k in ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes"))


BASKET = {3: "1", 4: "12", 6: "34", 8: "021", 11: "105", 14: "2", 15: "3", 16: "4", 17: "2", 18: "1", 19: "1", 20: "0",
          21: "1", 22: "12345", 34: "67890", 46: "30", 48: "24", 51: "0"}


# ----------------------------------------------------------------------------- basketball
def test_basketball():
    p = P["Stramatel_Basketball"]()
    p.feed(frame("3", BASKET))
    c = p.decoder.c
    assert p.decoder.contract == "Basketball" and c["EventId"] == "Basketball"
    assert clock(c) == "1234"
    assert c["ClockMode"] == ":" and c["ClockTenthsSecond"] == "0" and c["InternalClockStatus"] == "R"
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "2", "1")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "0", "5")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert (c["Period"], c["HomeFoulOnes"], c["GuestFoulOnes"], c["HomeTimeouts"], c["GuestTimeouts"]) == tuple("23421")
    assert c["Horn"] == "H" and c["PlayClockStatusInternal"] == "R"
    assert (c["TimeoutClockMinutesOnes"], c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("1", "3", "0")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("2", "4", " ")
    assert c["HomePlayer1FoulNumber"] == "1" and c["HomePlayer5FoulNumber"] == "5" and c["GuestPlayer5FoulNumber"] == "0"


def test_basketball_tenths_modes():
    f = dict(BASKET)
    f.update({4: "7", 5: "3", 6: " ", 7: " ", 48: "7", 49: 0x45})
    c = decode("Stramatel_Basketball", frame("4", f))
    assert c["ClockMode"] == "." and c["ClockMinutesOnes"] == "0"
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == ("7", "3", " ")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("0", "7", "5")


def test_basketball_player_points_and_names():
    p = P["Stramatel_Basketball"]()
    p.feed(frame("8", {22: "0512345678"}) + frame("7", {22: "9988776655"}))
    c = p.decoder.c
    assert c["HomePlayer1Points"] == " 5" and c["HomePlayer2Points"] == "12" and c["HomePlayer5Points"] == "78"
    assert c["GuestPlayer1Points"] == "99" and c["GuestPlayer5Points"] == "55"
    name = "TIGR".encode("utf-16-le")
    p.feed(frame("w") [:6] + name + frame("w")[14:])
    assert p.decoder.c["HomeTeamName"] == "TIGR"
    p.feed(frame("b")[:6] + "LION".encode("utf-16-le") + frame("b")[14:])
    assert p.decoder.c["GuestTeamName"] == "LION"
    p.feed(frame("w")[:6] + "XXXX".encode("utf-16-le") + frame("w")[14:])
    assert p.decoder.c["HomeTeamName"] == "TIGR"  # the first non-blank name sticks


def test_basketball_be04030():
    c = decode("Stramatel_BasketballBE04030", be_wire("3", BASKET))
    assert c["HomeScoreOnes"] == "1" and c["Period"] == "2" and c["InternalClockStatus"] == "R"


# ----------------------------------------------------------------------------- hockey family
HOCKEY = {4: "09", 6: "45", 9: "12", 12: "03", 14: "2", 17: "1", 18: "2", 19: "1", 20: "0",
          22: "123", 25: "456", 28: "789", 35: "111", 38: "222", 41: "333"}


def test_hockey_and_rink_hockey():
    for pid in ("Stramatel_Hockey", "Stramatel_RinkHockey"):
        c = decode(pid, frame("5", HOCKEY))
        assert clock(c) == " 945"  # a leading zero in the minutes tens is blanked and c["ClockMode"] == ":" and c["InternalClockStatus"] == "R"
        assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == tuple("1203")
        assert c["Period"] == "2" and c["HomeTimeOut"] == "1" and c["GuestTimeOut"] == "2" and c["Horn"] == "H"
        assert c["HomePenaltyPlayer1ClockMinutesTens"] == " "
        assert (c["HomePenaltyPlayer1ClockMinutesOnes"], c["HomePenaltyPlayer1ClockSecondTens"],
                c["HomePenaltyPlayer1ClockSecondOnes"]) == tuple("123")
        assert c["HomePenaltyPlayer3ClockSecondOnes"] == "9" and c["GuestPenaltyPlayer1ClockMinutesOnes"] == "1"
        assert c["GuestPenaltyPlayer3ClockSecondOnes"] == "3"
        assert P[pid]().decoder.contract == "HockeyLacrosse" and c["EventId"] == "Hockey"


def test_hockey_shot_clocks():
    p = P["Stramatel_Hockey"]()
    p.feed(frame("7", {48: "24"}))
    assert (p.decoder.c["ShotClockTens"], p.decoder.c["ShotClockOnes"]) == ("2", "4")
    p.feed(frame("8", {48: "7", 49: 0x45}))
    c = p.decoder.c
    assert (c["ShotClockTens"], c["ShotClockOnes"], c["ShotClockTenthsSecond"]) == ("0", "7", "5")


def test_hockey_452_penalty_layout():
    f = dict(HOCKEY)
    f.update({24: "123", 29: "456", 34: "789", 39: "321", 44: "654", 49: "987"})
    c = decode("Stramatel_Hockey452", frame("5", f))
    assert (c["HomePenaltyPlayer1ClockMinutesOnes"], c["HomePenaltyPlayer1ClockSecondOnes"]) == ("1", "3")
    assert c["HomePenaltyPlayer3ClockSecondOnes"] == "9" and c["GuestPenaltyPlayer1ClockMinutesOnes"] == "3"
    assert c["GuestPenaltyPlayer3ClockMinutesOnes"] == "9" and c["GuestPenaltyPlayer3ClockSecondOnes"] == "7"
    assert c["HomeScoreOnes"] == "2"


ICE = {4: "12", 6: "00", 8: "0705", 12: "3", 19: "1", 20: "0", 16: "259"}


def test_ice_hockey():
    c = decode("Stramatel_IceHockey", frame(0x93, ICE))
    assert clock(c) == "1200" and c["InternalClockStatus"] == "R"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == tuple("0705")
    assert c["Period"] == "3" and c["Horn"] == "H"
    assert (c["HomePenaltyPlayer1ClockMinutesOnes"], c["HomePenaltyPlayer1ClockSecondTens"],
            c["HomePenaltyPlayer1ClockSecondOnes"]) == tuple("259")
    assert "HomeTimeOut" not in c
    p = P["Stramatel_IceHockey"]()
    p.feed(frame("8", {48: "30"}))
    assert p.decoder.c["ShotClockTens"] == "3"


def test_ice_hockey_be04030():
    f = {4: "08", 6: "30", 9: "12", 12: "03", 14: "1", 17: "2", 18: "1", 20: "1", 22: "123", 26: "456",
         29: "1", 30: "2", 36: "789", 40: "321", 43: "4", 44: "5"}
    c = decode("Stramatel_IceHockeyBE04030", be_wire(0x93, f))
    assert c["InternalClockStatus"] == "R"  # running code is "1" on this board
    assert c["HomePenaltyPlayer1ClockMinutesTens"] == "1" and c["HomePenaltyPlayer1ClockSecondOnes"] == "3"
    assert c["HomePenaltyPlayer2ClockMinutesTens"] == "2" and c["HomePenaltyPlayer2ClockMinutesOnes"] == "4"
    assert c["GuestPenaltyPlayer1ClockMinutesTens"] == "4" and c["GuestPenaltyPlayer1ClockSecondOnes"] == "9"
    assert c["GuestPenaltyPlayer2ClockMinutesTens"] == "5" and c["GuestPenaltyPlayer2ClockSecondOnes"] == "1"
    assert (c["HomeScoreTens"], c["GuestScoreOnes"], c["Period"], c["HomeTimeOut"]) == ("1", "3", "1", "2")
    p = P["Stramatel_IceHockeyBE04030"]()
    p.feed(be_wire("w", {}).replace(b"w", b"w", 1)[:8] + "ABCD".encode("utf-16-le") + be_wire("w")[16:])
    assert p.decoder.c["HomeTeamName"] == "ABCD"


# ----------------------------------------------------------------------------- futsal / handball
FUT = {4: "20", 6: "00", 8: "3", 9: "07", 11: "2", 12: "11", 14: "2", 17: "1", 18: "0", 19: "1", 20: "0",
       22: "123", 25: "456", 31: "12", 33: "34", 35: "789", 38: "987", 46: "56", 48: "78"}


def test_futsal_and_handball():
    for pid, sport, ev in (("Stramatel_Futsal", "5", "Futsal"), ("Stramatel_HandBall", "<", "Handball")):
        c = decode(pid, frame(sport, FUT))
        assert c["EventId"] == ev
        assert (c["HomeFouls"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("3", " ", "7")
        assert (c["GuestFouls"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "1", "1")
        assert (c["HomePenaltyPlayer1Tens"], c["HomePenaltyPlayer1Ones"]) == ("1", "2")
        assert c["HomePenaltyPlayer1ClockSecondOnes"] == "3" and c["GuestPenaltyPlayer1ClockMinutesOnes"] == "4"
        assert c["HomePenaltyPlayer2ClockMinutesOnes"] == "7" and c["GuestPenaltyPlayer2ClockSecondOnes"] == "7"
        assert (c["HomePenaltyPlayer2Tens"], c["GuestPenaltyPlayer2Ones"]) == ("5", "8")
        assert c["HomeTimeOut"] == "1" and c["InternalClockStatus"] == "R" and c["Horn"] == "H"
    assert P["Stramatel_Futsal"]().decoder.contract == "FutsalHandball"


def test_futsal_accepts_either_id_and_clock_only_packets():
    c = decode("Stramatel_Futsal", frame(60, FUT))  # the Futsal board also accepts the handball sport id
    assert c["HomeScoreOnes"] == "7"
    c = decode("Stramatel_HandBall", frame("%", {4: "05", 6: "30"}))
    assert clock(c) == " 530"


# ----------------------------------------------------------------------------- racket sports
TT = {4: "01", 6: "23", 9: "11", 12: "09", 14: "3", 15: "1", 16: "2", 24: "1121", 28: "0910", 32: "1112", 36: "0000",
      50: "3"}


def test_table_tennis_and_badminton():
    for pid, sport, ev in (("Stramatel_TableTennis", ":", "TableTennis"), ("Stramatel_Badminton", "l", "Badminton")):
        c = decode(pid, frame(sport, TT))
        assert c["EventId"] == ev
        assert (c["ClockHourTens"], c["ClockHourOnes"], c["ClockMinutesTens"], c["ClockMinutesOnes"]) == tuple("0123")
        assert c["HomePoints"] == "11" and c["GuestPoints"] == "09" and c["Set"] == "3"
        assert (c["HomeSetsWon"], c["GuestSetsWon"]) == ("1", "2")
        assert c["HomeServe"] == " " and c["GuestServe"] == "S"
        assert (c["HomePointsSet1"], c["GuestPointsSet1"]) == ("11", "21")
        assert (c["HomePointsSet2"], c["GuestPointsSet2"]) == ("09", "10")
        assert (c["HomePointsSet3"], c["GuestPointsSet3"]) == ("11", "12")
    c = decode("Stramatel_Badminton", frame("l", {50: "1"}))
    assert c["HomeServe"] == "S" and c["GuestServe"] == " "


TEN = {4: "00", 6: "45", 9: "40", 12: "15", 14: "2", 20: "0", 24: "06", 26: "04", 28: "03", 30: "06", 37: "07",
       39: "05", 41: "00", 43: "00", 50: "0", 52: "1"}


def test_tennis():
    c = decode("Stramatel_Tennis", frame("9", TEN))
    assert c["TopPoints"] == "40"
    assert c["BottomPoints"] == "15" and c["Set"] == "2"
    assert (c["TopSet1Tens"], c["TopSet1Ones"], c["BottomSet1Tens"], c["BottomSet1Ones"]) == (" ", "6", " ", "4")
    assert (c["TopSet3Tens"], c["TopSet3Ones"], c["BottomSet3Tens"], c["BottomSet3Ones"]) == ("0", "7", "0", "5")
    assert (c["TopSet4Tens"], c["BottomSet4Ones"]) == ("0", "0")
    assert c["TopServe"] == "S" and c["BottomServe"] == " " and c["IsTieBreak"] == "1"
    assert c["InternalClockStatus"] == "R"
    assert (c["ClockHourTens"], c["ClockMinutesOnes"]) == ("0", "5")
    c = decode("Stramatel_Tennis", frame("9", {50: "2"}))
    assert "TopServe" not in c  # ScoreConnect never reports a bottom-player serve


def test_volleyball():
    f = {4: "10", 6: "30", 9: "05", 12: "21", 14: "2", 15: "1", 16: "0", 17: "1", 18: "2", 20: "1",
         22: "2518", 26: "2523", 30: "0710"}
    c = decode("Stramatel_Volleyball", frame("6", f))
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "5", "2", "1")
    assert c["Set"] == "2" and (c["HomeGamesWon"], c["GuestGamesWon"]) == ("1", "0")
    assert (c["HomeTimeout"], c["GuestTimeout"]) == ("1", "2") and c["InternalClockStatus"] == "S"
    assert (c["HomeScoreSet1"], c["GuestScoreSet1"]) == ("25", "18")
    assert (c["HomeScoreSet2"], c["GuestScoreSet2"]) == ("25", "23")
    assert (c["HomeScoreSet3"], c["GuestScoreSet3"]) == (" 7", "10")
    assert P["Stramatel_Volleyball"]().decoder.contract == "Volleyball"


# ----------------------------------------------------------------------------- clock modes
def test_clock_seconds_mode():
    c = decode("Stramatel_Basketball", frame("3", {4: "0", 5: "7", 6: "3", 7: " "}))
    assert c["ClockMode"] == "." and c["ClockMinutesTens"] == c["ClockMinutesOnes"] == "0"
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (" ", "7", "3")


# ----------------------------------------------------------------------------- framing
def test_standard_garbage_split_and_wrong_length():
    good = frame("3", BASKET)
    p = P["Stramatel_Basketball"]()
    p.feed(b"\x01\x02" + good[:20])
    assert p.packets == 0
    p.feed(good[20:] + b"\x07")
    assert p.packets == 1 and p.bad == 0 and p.decoder.c["Period"] == "2"
    p.feed(frame("3", BASKET, n=53))
    assert p.packets == 1 and p.bad == 1
    p.feed(good)
    assert p.packets == 2


def test_standard_all_channels():
    for ch in range(0xF8, 0xFE):
        assert decode("Stramatel_Basketball", frame("3", BASKET, ch=ch))["Period"] == "2"
    p = P["Stramatel_Basketball"]()
    p.feed(frame("3", BASKET, ch=0xF7))  # not a channel byte
    assert p.packets == 0 and p.bad == 1


def test_be04030_garbage_split_and_wrong_length():
    good = be_wire("3", BASKET)
    p = P["Stramatel_BasketballBE04030"]()
    p.feed(b"\x01\x02\r" + good[:30])  # a stray lone CR before the frame is dropped
    assert p.packets == 0
    p.feed(good[30:])
    assert p.packets == 1 and p.decoder.c["Period"] == "2"
    bad = good[:-3] + b"\r\r"  # 2 bytes short
    before = p.bad
    p.feed(bad)
    assert p.packets == 1 and p.bad == before + 1
    p.feed(frame("3", BASKET) + b"\r")  # a standard-length frame on a BE04030 port is rejected too
    assert p.packets == 1


def test_short_packet_does_not_raise():
    d = stramatel.Basketball()
    d.decode(b"\xf8\x33" + b" " * 10)
    assert d.c == {"EventId": "Basketball"}
