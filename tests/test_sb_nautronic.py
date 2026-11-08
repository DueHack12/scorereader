from scoreboards import nautronic

P = nautronic.PROTOCOLS


def sub(hi_lo, *data):
    body = bytes([hi_lo >> 8, hi_lo & 0xFF]) + bytes(data)
    return bytes([len(body)]) + body


def main_frame(*subs):
    body = b"".join(subs)
    pkt = bytes([0xFF, 0x71, 0, 0x00, 0x80, 0x00]) + body
    return pkt[:2] + bytes([len(pkt) - 4]) + pkt[3:]


def run(pid, *subs):
    p = P[pid]()
    p.feed(main_frame(*subs))
    p.feed(main_frame())  # the next frame header is what ends the previous frame
    return p


def ng(pid, *packets):
    p = P[pid]()
    for pk in packets:
        p.feed(bytes(pk))
    return p.decoder.c


# ----------------------------------------------------------------------------- Nautronic_Basketball
def test_basketball_clock_minutes_and_status():
    p = run("Nautronic_Basketball", sub(0x400C, 0x01, 0x02, 0x63, 0x04))
    c = p.decoder.c
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("1234")
    assert c["ClockMode"] == ":" and c["ClockTenthsSecond"] == "0" and c["InternalClockStatus"] == "R"
    assert p.decoder.contract == "Basketball" and c["EventId"] == "Basketball"


def test_basketball_clock_tenths_mode_and_stopped():
    c = run("Nautronic_Basketball", sub(0x400C, 0x05, 0x07, 0x29, 0x0F)).decoder.c
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == ("5", "7", "9")
    assert c["ClockMinutesTens"] == c["ClockMinutesOnes"] == "0" and c["ClockMode"] == "."
    assert c["InternalClockStatus"] == "S"


def test_basketball_scores_period_possession():
    c = run("Nautronic_Basketball",
            sub(0x4000, 0x07, 0x13), sub(0x407C, 0x00, 0x00, 0x00, 0x00, 0x04, 0x05, 0x00, 0x00),
            sub(0x4006, 0x00, 0x02), sub(0x8005, 0x10)).decoder.c
    assert c["HomeScoreHundreds"] == "1" and c["HomeScoreTens"] == "7" and c["HomeScoreOnes"] == "3"
    assert c["GuestScoreHundreds"] == " " and c["GuestScoreTens"] == "4" and c["GuestScoreOnes"] == "5"
    assert c["Period"] == "2"
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "


def test_basketball_hundreds_quirk_and_guest_possession():
    c = run("Nautronic_Basketball", sub(0x4000, 0x00, 0xF3), sub(0x8005, 0x00)).decoder.c
    assert c["HomeScoreHundreds"] == "1"  # a blank nibble is not "0", so ScoreConnect shows a 1
    assert c["GuestPossession"] == ">" and c["HomePossession"] == " "


def test_basketball_timeouts_fouls():
    c = run("Nautronic_Basketball", sub(0x8000, 0x05, 0, 0), sub(0x8080, 0x15, 0, 0),
            sub(0x8007, 0x07), sub(0x8087, 0x1F)).decoder.c
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "3"
    assert c["HomeFoulOnes"] == "3" and c["GuestFoulOnes"] == "5"


def test_basketball_players_and_points():
    digits = bytes(range(0x00, 0x0A))
    c = run("Nautronic_Basketball", sub(0x4020, *digits, 0, 0, 0), sub(0x40A0, *digits[::-1], 0, 0, 0),
            sub(0x4050, *digits, 0, 0, 0), sub(0x40D0, *digits[::-1], 0, 0, 0)).decoder.c
    assert [c[f"HomePlayer{i}"] for i in range(1, 6)] == ["01", "23", "45", "67", "89"]
    assert c["GuestPlayer1"] == "98" and c["GuestPlayer5"] == "10"
    assert c["HomePlayer3Points"] == "45" and c["GuestPlayer2Points"] == "76"


def test_basketball_shot_clock_needs_exactly_five_bytes():
    c = run("Nautronic_Basketball", sub(0x40CA, 0x24, 0x00)).decoder.c
    assert "ShotClockSecondTens" not in c


def test_basketball_shot_clock_forms():
    c = run("Nautronic_Basketball", sub(0x40CA, 0x01, 0x02, 0x01)).decoder.c
    assert c["ShotClockSecondTens"] == " " and c["ShotClockSecondOnes"] == "1" and c["ShotClockTenthsSecond"] == "2"
    c = run("Nautronic_Basketball", sub(0x40CA, 0x01, 0x02, 0x00)).decoder.c
    assert c["ShotClockTenthsSecond"] == " " and c["ShotClockSecondTens"] == "1" and c["ShotClockSecondOnes"] == "2"


def test_basketball_timeout_clock_and_delayed_blanking():
    for ident in (0x4013, 0x4093):
        pr = P["Nautronic_Basketball"]()
        pr.feed(main_frame(sub(ident, 0x01, 0x23, 0x04, 0x00)))
        pr.feed(main_frame())
        c = pr.decoder.c
        assert (c["TimeoutClockMinutesOnes"], c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("1", "3", "4")
        empty = main_frame(sub(ident, 0x00, 0x0F, 0x00, 0x00))
        for _ in range(11):  # needs more than 10 consecutive empty updates
            pr.feed(empty)
        assert pr.decoder.c["TimeoutClockMinutesOnes"] == "1"
        pr.feed(empty)
        pr.feed(empty)
        assert pr.decoder.c["TimeoutClockMinutesOnes"] == " "


def test_basketball_names():
    name = b"  TIGERS  "
    c = run("Nautronic_Basketball", sub(0xC0D3, 0x00, 0, 0, 0, 0, 0, *name)).decoder.c
    assert c["HomeTeamName"] == "TIGERS  "
    c = run("Nautronic_Basketball", sub(0xC0D3, 0x80, 0, 0, 0, 0, 0, *b"  LIONS" + b" " * 14)).decoder.c
    assert c["GuestTeamName"].startswith("LIONS")


# ----------------------------------------------------------------------------- Nautronic_Basketball framing
def test_main_garbage_split_and_reject():
    frame = main_frame(sub(0x4006, 0x00, 0x04))
    p = P["Nautronic_Basketball"]()
    p.feed(b"\x01\x02\x03" + frame[:7])
    assert p.packets == 0
    p.feed(frame[7:] + main_frame())
    assert p.packets == 1 and p.decoder.c["Period"] == "4"
    assert p.bad == 0


def test_main_rejects_bad_marker_and_length():
    p = P["Nautronic_Hockey"]()
    bad = bytearray(main_frame(sub(0x4000, 0x01, 0x02)))
    bad[4] = 0x81  # marker must be 0x80
    p.feed(bytes(bad) + main_frame())
    assert p.bad == 1  # the trailing empty frame is still waiting for its end
    assert "HomeScoreTens" not in p.decoder.c
    q = P["Nautronic_Hockey"]()
    short = bytearray(main_frame(sub(0x4000, 0x01, 0x02)))
    short[2] = 0  # declared length far too small: len - (L + 4) >= 3
    q.feed(bytes(short) + main_frame())
    assert q.bad == 1 and "HomeScoreTens" not in q.decoder.c


# ----------------------------------------------------------------------------- Nautronic_Hockey
def test_hockey_scores_sog_period_clock():
    p = run("Nautronic_Hockey",
            sub(0x4000, 0x02, 0x03, 0, 0, 0x01, 0x05, 0, 0x03), sub(0x407C, 0, 0, 0, 0, 0x04, 0x05, 0, 0, 0x02, 0x08),
            sub(0x400C, 0x01, 0x05, 0x63, 0x09))
    c = p.decoder.c
    assert p.decoder.contract == "HockeyLacrosse" and c["EventId"] == "Hockey"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"], c["Period"]) \
        == ("2", "3", "1", "5", "3")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"], c["GuestShotOnGoalTens"], c["GuestShotOnGoalOnes"]) \
        == ("4", "5", "2", "8")
    assert "".join(c[k] for k in ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")) == "1539"
    assert c["ClockMode"] == ":" and c["InternalClockStatus"] == "R"


def test_hockey_penalties():
    data = bytes([0x01, 0x07, 0x02, 0x03, 0x04, 0x02, 0x08, 0x01, 0x00, 0x00, 0x03, 0x09, 0x00, 0x05, 0x06])
    c = run("Nautronic_Hockey", sub(0x4011, *data), sub(0x4091, *data[::-1])).decoder.c
    assert c["HomePenaltyPlayer1Tens"] == "1" and c["HomePenaltyPlayer1Ones"] == "7"
    assert c["HomePenaltyPlayer1ClockMinutesTens"] == " " and c["HomePenaltyPlayer1ClockMinutesOnes"] == "2"
    assert c["HomePenaltyPlayer1ClockSecondTens"] == "3" and c["HomePenaltyPlayer1ClockSecondOnes"] == "4"
    assert c["HomePenaltyPlayer3ClockSecondOnes"] == "6" and c["HomePenaltyPlayer2Tens"] == "2"
    assert c["GuestPenaltyPlayer1ClockSecondOnes"] == "3" and c["GuestPenaltyPlayer3Ones"] == "3"


def test_hockey_timeouts_and_penalty_types_are_crossed():
    c = run("Nautronic_Hockey",
            sub(0x8000, 0x05, 0x00, 0x01, 0x00, 0x03, 0x00, 0x05), sub(0x8080, 0x15, 0x00, 0x04, 0x00, 0x03)).decoder.c
    assert c["GuestFullTimeoutsRemaining"] == "2" and c["GuestPartialTimeoutsRemaining"] == " "
    assert (c["HomePlayer1PenaltyType1"], c["HomePlayer1PenaltyType2"]) == ("2", " ")
    assert (c["HomePlayer2PenaltyType1"], c["HomePlayer2PenaltyType2"]) == ("2", "2")
    assert (c["HomePlayer3PenaltyType1"], c["HomePlayer3PenaltyType2"]) == ("2", "5")
    assert c["HomeFullTimeoutsRemaining"] == "3"
    assert (c["GuestPlayer1PenaltyType1"], c["GuestPlayer1PenaltyType2"]) == ("5", " ")
    assert (c["GuestPlayer2PenaltyType1"], c["GuestPlayer2PenaltyType2"]) == ("2", "2")


def test_hockey_names():
    c = run("Nautronic_Hockey", sub(0xC0D3, 0x00, 0, 0, 0, 0, 0, *b"  BEARS ")).decoder.c
    assert c["HomeTeamName"] == "BEARS "
    c = run("Nautronic_Hockey", sub(0xC0D3, 0x80, 0, 0, 0, 0, 0, *b"WOLVES" + b" " * 16)).decoder.c
    assert c["GuestTeamName"].startswith("WOLVES")


def test_hockey_short_subpacket_is_ignored_not_raised():
    p = run("Nautronic_Hockey", sub(0x4000, 0x01), sub(0x4006, 0))
    assert p.bad == 0 and p.decoder.c["HomeScoreTens"] == "1"


# ----------------------------------------------------------------------------- NautronicNg08_Basketball
def test_ng08_clock_forms():
    c = ng("NautronicNg08_Basketball", [10, 12, 1, 2, 3, 4, 0x80])
    assert "".join(c[k] for k in ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")) == "1234"
    assert c["ClockMode"] == ":" and c["InternalClockStatus"] == "R" and c["ClockTenthsSecond"] == "0"
    c = ng("NautronicNg08_Basketball", [40, 12, 5, 7, 0x09, 0x0F, 0x80])
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"], c["ClockMode"]) == ("5", "7", "9", ".")
    c = ng("NautronicNg08_Basketball", [10, 12, 1, 2, 0x23, 4, 0x80])
    assert c["InternalClockStatus"] == "S"


def test_ng08_clock_suppressed_while_flag_set():
    c = ng("NautronicNg08_Basketball", [10, 12, 0x21, 2, 3, 4, 0x80])
    assert "ClockMode" not in c and c["InternalClockStatus"] == "R"


def test_ng08_alt_clock_13():
    c = ng("NautronicNg08_Basketball", [10, 13, 2, 3, 4, 0x80])
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockMode"]) == ("2", "3", "4", ":")
    assert "ClockMinutesTens" not in c
    c = ng("NautronicNg08_Basketball", [10, 13, 7, 8, 0x0F, 0x80])
    assert (c["ClockSecondOnes"], c["ClockTenthsSecond"], c["ClockMode"]) == ("7", "8", ".")


def test_ng08_scores_period():
    c = ng("NautronicNg08_Basketball", [10, 0, 0x23, 0x04, 0x02, 0x07, 0x05, 0x80])
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "3", "4")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "7", "5")
    assert c["Period"] == "2"


def test_ng08_decimal_score_and_fouls():
    home = [3, 5, 10, 5, 0, 0, 0, 0, 0, 0, 0, 123, 7, 0x80]
    guest = [3, 5, 10, 5, 1, 0, 0, 0, 0, 0, 0, 45, 12, 0x80]
    c = ng("NautronicNg08_Basketball", home, guest)
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "2", "3")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"]) == (" ", "7")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "4", "5")
    assert (c["GuestFoulTens"], c["GuestFoulOnes"]) == ("1", "2")


def test_ng08_shot_clock_variants():
    c = ng("NautronicNg08_Basketball", [10, 17, 1, 4, 5, 0x80])
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("0", "4", "5")
    c = ng("NautronicNg08_Basketball", [10, 17, 1, 4, 5, 0x80], [10, 18, 3, 7, 0x80])  # partial update, under 5 s
    assert (c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("3", "7")
    c = ng("NautronicNg08_Basketball", [10, 17, 0, 2, 1, 0x80], [10, 18, 1, 9, 0x80])
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("1", "9")
    c = ng("NautronicNg08_Basketball", [40, 0, 2, 1, 0, 0x80])
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "1")
    c = ng("NautronicNg08_Basketball", [40, 0, 4, 5, 1, 0x80])
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("0", "4", "5")


def test_ng08_framing_garbage_split_reject():
    pkt = bytes([10, 12, 1, 2, 3, 4, 0x80])
    p = P["NautronicNg08_Basketball"]()
    p.feed(b"\x90")  # terminator with no start byte: rejected
    assert p.bad == 1 and p.packets == 0
    p.feed(b"\x05\x06" + pkt[:3])
    assert p.packets == 0
    p.feed(pkt[3:])
    assert p.packets == 1 and p.decoder.c["ClockSecondOnes"] == "4"


def test_ng08_short_packet_does_not_raise():
    p = P["NautronicNg08_Basketball"]()
    p.feed(bytes([10, 12, 1, 0x80]))
    assert p.bad == 0


# ----------------------------------------------------------------------------- NautronicNTPult_Basketball
def test_ntpult_clock_and_status():
    c = ng("NautronicNTPult_Basketball", [10, 12, 1, 2, 3, 4, 0x80])
    assert (c["ClockMinutesTens"], c["ClockSecondOnes"], c["ClockMode"], c["InternalClockStatus"]) == ("1", "4", ":", "R")
    c = ng("NautronicNTPult_Basketball", [40, 12, 5, 7, 0x29, 0x0F, 0x80])
    assert (c["ClockSecondTens"], c["ClockTenthsSecond"], c["ClockMode"], c["InternalClockStatus"]) == ("5", "9", ".", "S")
    c = ng("NautronicNTPult_Basketball", [10, 13, 2, 3, 4, 0x80])
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("2", "3", "4")


def test_ntpult_scores():
    c = ng("NautronicNTPult_Basketball", [10, 0, 0x23, 0x04, 0x80], [10, 3, 0x07, 0x05, 0x80])
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "3", "4")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "7", "5")
    c = ng("NautronicNTPult_Basketball", [10, 0, 0x0A, 0x05, 0x80])
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == ("0", "5")  # blank tens digit with no hundreds reads as 0


def test_ntpult_shot_clock():
    assert ng("NautronicNTPult_Basketball", [40, 0, 2, 1, 0x80])["ShotClockSecondOnes"] == "1"
    c = ng("NautronicNTPult_Basketball", [10, 18, 1, 4, 0x80])
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("1", "4")
    c = ng("NautronicNTPult_Basketball", [10, 17, 0, 3, 5, 0x80])
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("3", "5")


def test_ntpult_possession_and_timeout_clock():
    pr = P["NautronicNTPult_Basketball"]()
    pr.feed(bytes([10, 5, 0x02, 0x03, 0x24, 0x80]))
    c = pr.decoder.c
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert (c["TimeoutClockMinutesOnes"], c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("2", "3", "4")
    pr.feed(bytes([10, 8, 0x00, 0x00, 0x24, 0x80]))
    assert pr.decoder.c["GuestPossession"] == ">" and pr.decoder.c["HomePossession"] == " "
    pr.feed(bytes([10, 12, 1, 2, 3, 4, 0x80]))  # clock running -> timeout clock hidden on the next update
    pr.feed(bytes([10, 5, 0x02, 0x03, 0x24, 0x80]))
    assert pr.decoder.c["TimeoutClockSecondOnes"] == " " and pr.decoder.c["HomePossession"] == "<"
    assert pr.decoder.contract == "Basketball"
