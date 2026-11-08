from scoreboards import tissot


def rec(rid, *vals):
    return ("\x014|6|%d|0|" % rid + "|".join(vals) + "\x04").encode()


def test_full_stream():
    p = tissot.PROTOCOLS["Tissot_Basketball"]()
    stream = b"\xfe\x10" + rec(1, "7", "112") + rec(2, "3", "10", "1", "2") + rec(4, "0", "2")
    stream += rec(5, "2") + rec(17, "Lions", "Tigers") + rec(32, "0", "0", "0", "2", "3")
    stream += rec(30, " 8:05", "0", "0:30", "0", "0", "0") + rec(31, "  14")
    assert p.feed(stream[:10]) == 0
    assert p.feed(stream[10:]) == 8
    c = p.snapshot()
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", " ", "7")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "1", "2")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "3", "1", "0")
    assert c["HomeBonus"] == "B" and c["HomeDoubleBonus"] == " "
    assert c["GuestBonus"] == " " and c["GuestDoubleBonus"] == "B"
    assert c["Period"] == "2" and c["HomePossession"] == " " and c["GuestPossession"] == ">"
    assert c["HomeTeamName"] == "Lions" and c["GuestTeamName"] == "Tigers"
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "3"
    assert c["ClockMode"] == ":" and (c["ClockMinutesTens"], c["ClockMinutesOnes"]) == ("0", "8")
    assert (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("0", "5")
    assert c["InternalClockStatus"] == "R"
    assert (c["TimeoutClockMinutesOnes"], c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("0", "3", "0")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("1", "4", " ")
    assert p.contract_name == "Basketball" and c["EventId"] == "Basketball"


def test_sub_minute_clock_and_stopped_flag():
    p = tissot.PROTOCOLS["Tissot_Basketball"]()
    p.feed(rec(30, "      9.5", "0", "", "0", "0", "1"))
    c = p.snapshot()
    assert c["ClockMode"] == "." and (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("0", "9")
    assert c["ClockTenthsSecond"] == "5" and c["InternalClockStatus"] == "S"
    assert c["TimeoutClockSecondTens"] == "0"
    p.feed(rec(31, "7.3"))
    c = p.snapshot()
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == (" ", "7", "3")


def test_clock_keeps_last_two_digits():
    p = tissot.PROTOCOLS["Tissot_Basketball"]()
    p.feed(rec(30, "123:45", "0", "", "0", "0", "0"))
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("2", "3", "4", "5")


def test_rejects_wrong_header_and_missing_soh():
    p = tissot.PROTOCOLS["Tissot_Basketball"]()
    assert p.feed(b"\x015|6|1|0|1|2\x04") == 0 and p.bad == 1
    assert p.feed(b"no soh here\x04") == 0 and p.bad == 2
    assert p.feed(rec(1, "1", "2")) == 1
    assert p.snapshot()["HomeScoreOnes"] == "1"


def test_short_records_do_not_raise():
    p = tissot.PROTOCOLS["Tissot_Basketball"]()
    assert p.feed(rec(30) + rec(2, "1") + rec(32, "1") + b"\x014|6\x04") >= 0
    assert p.bad == 0
