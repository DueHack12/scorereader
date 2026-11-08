from scoreboards import icast as ic


def make():
    return ic.PROTOCOLS["ICast_Basketball"]()


GAME = b"12:34;25;130;2;3;4;5;16;1;24;0;0;Q;Game Time"
HALF = b"09.5;7;99;1;0;1;12;3;2;8.7;1;0:45;Q;Intermission Half"


def test_game_time_packet():
    p = make()
    assert p.feed(GAME) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", " ")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "2", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "3", "0")
    assert (c["Period"], c["HomeTimeouts"], c["GuestTimeouts"]) == ("2", "3", "4")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "5", "1", "6")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("2", "4", " ")
    assert "TimeoutClockSecondOnes" not in c or c["TimeoutClockSecondOnes"] == " "
    assert p.contract_name == "Basketball"


def test_intermission_half_packet_with_timeout_clock():
    p = make()
    assert p.feed(HALF) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", " ", "0", "9", "5")
    assert (c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("7", "9", "9")
    assert c["GuestPossession"] == ">" and c["HomePossession"] == " "
    assert (c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("8", "7")
    assert (c["TimeoutClockMinutesOnes"], c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("0", "4", "5")
    p.feed(b"09.5;7;99;1;0;1;12;3;2;8.7;0;0:45;Q;Game Time")  # timeout flag 0 clears the timeout clock
    assert p.snapshot()["TimeoutClockSecondTens"] == " "


def test_nul_bytes_split_and_garbage():
    p = make()
    stream = b"\x00\x00" + GAME.replace(b";", b";\x00", 2)
    assert p.feed(stream[:15]) == 0
    assert p.feed(stream[15:]) == 1
    assert p.snapshot()["HomeScoreOnes"] == "5"
    # a malformed first packet (wrong field count) is rejected, the next one decodes
    assert p.feed(b"junk;Game Time" + GAME.replace(b"25", b"31", 1)) == 1 and p.bad == 1
    assert p.snapshot()["HomeScoreOnes"] == "1"


def test_two_packets_in_one_feed_and_short_fields_ignored():
    p = make()
    assert p.feed(GAME + HALF) == 2
    before = p.snapshot()
    p.feed(b"1:;;;;;;;;;;;;Game Time")  # bad clock/blank fields: skipped without raising
    assert p.snapshot()["HomeScoreOnes"] == before["HomeScoreOnes"]
