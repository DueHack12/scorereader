"""Fair-Play (Fairplay.Main) protocol + decoders, using synthetic packets in the real wire format."""
import pytest

from scoreboards import create, fairplay


def pkt(code, ptype, data, length=None, third=0):
    """code type third L data[L] sum_lo sum_hi. `data` maps packet offset (>= 4) -> byte."""
    n = length if length is not None else max(max(data, default=4) - 3, 8)
    body = bytearray(n + 4)
    body[0], body[1], body[2], body[3] = code, ptype, third, n
    for k, v in data.items():
        body[k] = v
    s = sum(body)
    return bytes(body) + bytes([s & 0xFF, s >> 8])


def run(pid, *packets):
    proto = create(pid)
    for p in packets:
        proto.feed(p)
    return proto, proto.snapshot()


def clock_bytes(m, s):
    return {4: m, 5: s}


ALL_IDS = [
    "Fairplay_BaseballSoftball_Code34", "Fairplay_BaseballSoftball_Code35", "Fairplay_Baseball_Code30",
    "Fairplay_Baseball_Code31", "Fairplay_Baseball_Code32", "Fairplay_Baseball_Code33", "Fairplay_Basketball_Code0",
    "Fairplay_Basketball_Code1", "Fairplay_Basketball_Code10", "Fairplay_Basketball_Code11",
    "Fairplay_Basketball_Code12", "Fairplay_Basketball_Code2", "Fairplay_Basketball_Code4",
    "Fairplay_Basketball_Code5", "Fairplay_Basketball_Code6", "Fairplay_Basketball_Code9",
    "Fairplay_Football_Code23", "Fairplay_Football_Code24", "Fairplay_Football_Code25", "Fairplay_Football_Code26",
    "Fairplay_Football_Code27", "Fairplay_Hockey_Code14", "Fairplay_Hockey_code13", "Fairplay_Lacrosse",
    "Fairplay_Soccer_Code22", "Fairplay_Soccer_Code36", "Fairplay_Softball_Code31", "Fairplay_Volleyball_Code0",
    "Fairplay_Volleyball_Code4",
]


def code_of(pid):
    return fairplay._TABLE[pid][1]


# ----------------------------------------------------------------------------- registration / every id
@pytest.mark.parametrize("pid", ALL_IDS)
def test_every_id_registered_and_decodes_clock(pid):
    if "aseball" in pid or "Softball" in pid:
        proto, c = run(pid, pkt(code_of(pid), 0x81, {}, length=40))
        assert proto.packets == 1 and c["ClockMode"] == ":" and c["EventId"] == "Baseball"
        return
    code = code_of(pid)
    proto, c = run(pid, pkt(code, 0x81, {**clock_bytes(0x12, 0x34), 6: 0x21, 7: 0x03}, length=40))
    assert proto.packets == 1 and proto.bad == 0
    assert c["ClockMode"] == ":"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("1234")
    assert c["ClockTenthsSecond"] == "0"


@pytest.mark.parametrize("pid", ALL_IDS)
def test_every_id_survives_short_and_odd_packets(pid):
    code = code_of(pid)
    proto = create(pid)
    proto.feed(pkt(code, 0x81, {}, length=1))
    proto.feed(pkt(code, 0x55, {}, length=3))
    proto.feed(pkt(code, 0x81, {4: 0xFF, 5: 0xFF}, length=2))
    assert proto.bad == 0


def test_clock_tenths_mode():
    _, c = run("Fairplay_Football_Code23", pkt(23, 0x81, {4: 0x45, 5: 0x7F}))
    assert c["ClockMode"] == "." and c["ClockMinutesTens"] == "0" and c["ClockMinutesOnes"] == "0"
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == ("4", "5", "7")


# ----------------------------------------------------------------------------- football
@pytest.mark.parametrize("code", [23, 24, 25, 26, 27])
def test_football(code):
    pid = f"Fairplay_Football_Code{code}"
    main = pkt(code, 0x81, {**clock_bytes(0x08, 0x15), 6: 0x14, 7: 0x07, 8: 0x32, 9: 0x10, 10: 0x08, 11: 0x10,
                           12: 0x35, 13: 0x23})
    play = pkt(code, 0xC1, {7: 0x25})
    _, c = run(pid, main, play)
    assert c["EventId"] == "Football"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == tuple("1407")
    assert (c["Down"], c["Quarter"], c["ToGoTens"], c["ToGoOnes"]) == ("3", "2", "1", "0")
    assert (c["BallOnTens"], c["BallOnOnes"]) == ("3", "5")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("2", "3")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " " and c["Horn"] == "H"
    assert (c["PlayClockTens"], c["PlayClockOnes"]) == ("2", "5")
    assert fairplay.FairplayFootball.contract == "Football"


# ----------------------------------------------------------------------------- basketball
def bb_main(code):
    return pkt(code, 0x81, {**clock_bytes(0x07, 0x30), 6: 0x45, 7: 0x38, 8: 0x02, 10: 0x30 | 0x02 | 0x04 | 0x01, 11: 0x30 | 0x01,
                           12: 0x07, 13: 0x11, 14: 0x23, 15: 0x04, 16: 0x32}, length=24)


@pytest.mark.parametrize("code", [1, 2, 9, 10, 11, 12])
def test_basketball_generic(code):
    _, c = run(f"Fairplay_Basketball_Code{code}", bb_main(code), pkt(code, 0xC1, {7: 0x24}))
    assert c["EventId"] == "Basketball"
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "4", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "3", "8")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("3", "2")
    assert c["Horn"] == "H" and c["HomePossession"] == "<" and c["GuestPossession"] == ">"
    assert c["GuestBonus"] == "B" and c["HomeBonus"] == " "
    assert c["GuestDoubleBonus"] == "B" and c["HomeDoubleBonus"] == " "
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == ("0", "7", "1", "1")
    assert (c["FoulPlayerTens"], c["FoulPlayerOnes"], c["FoulPlayerNumberOfFouls"], c["Period"]) == ("2", "3", "4", "2")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")


def test_basketball_player_pages():
    code = 1
    home = pkt(code, 0xB1, {4: 0x10, 5: 0x23, 6: 0x34, 7: 0x45, 8: 0x56, 12: 0x02, 13: 0x04, 14: 0x06, 15: 0x08, 16: 0x10,
                          20: 0x01, 21: 0x02, 22: 0x03, 23: 0x04, 24: 0x05}, length=24)
    guest = pkt(code, 0xB4, {4: 0x11, 12: 0x22, 20: 0x03}, length=24)
    _, c = run("Fairplay_Basketball_Code1", home, guest)
    assert c["HomePlayer1"] == "10" and c["HomePlayer5"] == "56"
    assert c["HomePlayer3Points"] == "06" and c["HomePlayer5Points"] == "10"
    assert c["HomePlayer2FoulNumber"] == "2" and c["HomePlayer5FoulNumber"] == "5"
    assert c["GuestPlayer1"] == "11" and c["GuestPlayer1Points"] == "22" and c["GuestPlayer1FoulNumber"] == "3"


def test_basketball_code5_6_has_no_double_bonus():
    for code in (5, 6):
        _, c = run(f"Fairplay_Basketball_Code{code}", bb_main(code))
        assert "HomeDoubleBonus" not in c and "GuestDoubleBonus" not in c
        assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("3", "2")
        assert c["GuestBonus"] == "B" and c["Period"] == "2"


def test_basketball_code0():
    _, c = run("Fairplay_Basketball_Code0", bb_main(0))
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "4", "5")
    assert c["GuestDoubleBonus"] == "B" and c["Horn"] == "H" and c["Period"] == "2"
    assert "HomeTimeouts" not in c and "HomeFoulTens" not in c
    # horn: any horn bit is enough on code 0 but both are needed on the other layouts
    one = pkt(0, 0x81, {4: 0x10, 5: 0x00, 11: 0x10}, length=24)
    assert run("Fairplay_Basketball_Code0", one)[1]["Horn"] == "H"
    assert run("Fairplay_Basketball_Code1", pkt(1, 0x81, {4: 0x10, 5: 0x00, 11: 0x10}, length=24))[1]["Horn"] == " "


def test_basketball_code4():
    data = {**clock_bytes(0x10, 0x00), 6: 0x12, 7: 0x34, 8: 0x35, 10: 0x01, 11: 0x30, 12: 0x01, 13: 0x02, 14: 0x03,
            15: 0x40 | 0x05}
    _, c = run("Fairplay_Basketball_Code4", pkt(4, 0x81, data, length=24), pkt(4, 0xC1, {7: 0x14}))
    assert c["HomeTimeouts"] == "3" and c["GuestTimeouts"] == "4"
    assert c["GuestPossession"] == ">" and c["Horn"] == "H" and c["Period"] == "5"
    assert (c["GuestFoulTens"], c["GuestFoulOnes"], c["FoulPlayerNumberOfFouls"]) == ("0", "2", "5")
    assert c["ShotClockSecondTens"] == "1"


# ----------------------------------------------------------------------------- volleyball
def test_volleyball_code0():
    _, c = run("Fairplay_Volleyball_Code0", pkt(0, 0x81, {6: 0x21, 7: 0x19, 8: 0x03}))
    assert c["EventId"] == "Volleyball"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == tuple("2119")
    assert c["Game"] == "3"


def test_volleyball_code4():
    data = {6: 0x10, 7: 0x12, 8: 0x23, 10: 0x02, 12: 0x01, 13: 0x02, 15: 0x30, 16: 0x30, 20: 0x25, 21: 0x20, 22: 0x25,
            23: 0x23, 28: 0x11, 29: 0x12, 30: 0x15, 31: 0x13}
    _, c = run("Fairplay_Volleyball_Code4", pkt(4, 0x81, data, length=32))
    assert c["Game"] == "3" and c["Set"] == "3" and c["HomeTimeout"] == "2" and c["GuestTimeout"] == "3"
    assert (c["HomeGamesWon"], c["GuestGamesWon"]) == ("1", "2")
    assert (c["HomeScoreSet1"], c["GuestScoreSet1"], c["HomeScoreSet2"], c["GuestScoreSet2"]) == ("25", "20", "25", "23")
    assert (c["HomeScoreSet3"], c["GuestScoreSet3"]) == ("15", "13")  # bytes 30/31 overwrite 28/29
    assert c["HomeServe"] == "*" and c["GuestServe"] == " "


# ----------------------------------------------------------------------------- hockey / lacrosse / soccer
def test_hockey13():
    data = {**clock_bytes(0x12, 0x00), 6: 0x03, 7: 0x02, 8: 0x02, 12: 0x21, 13: 0x45, 14: 0x30, 15: 0x07, 16: 0x12,
            20: 0x10, 21: 0x59, 22: 0x00, 23: 0x08, 24: 0x09}
    _, c = run("Fairplay_Hockey_code13", pkt(13, 0x81, data, length=28), pkt(13, 0xC1, {7: 0x30}))
    assert c["EventId"] == "Hockey" and fairplay.FairplayHockey13.contract == "HockeyLacrosse"
    assert c["Period"] == "2" and c["HomeScoreOnes"] == "3" and c["GuestScoreOnes"] == "2"
    assert c["HomePenaltyPlayer1Ones"] == "7" and c["HomePenaltyPlayer1ClockMinutesTens"] == " "
    assert c["HomePenaltyPlayer1ClockMinutesOnes"] == "2"
    assert (c["HomePenaltyPlayer1ClockSecondTens"], c["HomePenaltyPlayer1ClockSecondOnes"]) == ("4", "5")
    assert c["HomePenaltyPlayer2ClockMinutesOnes"] == "1" and c["HomePenaltyPlayer2Tens"] == "1"
    assert c["HomePenaltyPlayer2ClockSecondTens"] == "3"
    assert c["GuestPenaltyPlayer1ClockMinutesOnes"] == "1" and c["GuestPenaltyPlayer1ClockSecondTens"] == "5"
    assert c["GuestPenaltyPlayer2Ones"] == "9" and c["GuestPenaltyPlayer2ClockMinutesOnes"] == "0"
    assert (c["ShotClockTens"], c["ShotClockOnes"]) == ("3", "0")


def test_hockey14():
    data = {**clock_bytes(0x05, 0x00), 6: 0x01, 7: 0x00, 8: 0x03, 12: 0x14, 13: 0x09, 20: 0x20, 21: 0x30, 22: 0x15,
            23: 0x11, 24: 0x22, 28: 0x10, 29: 0x45, 30: 0x00, 31: 0x33, 32: 0x44}
    _, c = run("Fairplay_Hockey_Code14", pkt(14, 0x81, data, length=36))
    assert c["Period"] == "3" and (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"]) == ("1", "4")
    assert c["GuestShotOnGoalOnes"] == "9"
    assert c["HomePenaltyPlayer1Tens"] == "1" and c["HomePenaltyPlayer1ClockMinutesOnes"] == "2"
    assert c["HomePenaltyPlayer1ClockSecondTens"] == "3" and c["HomePenaltyPlayer2ClockSecondOnes"] == "5"
    assert c["GuestPenaltyPlayer1Tens"] == "3" and c["GuestPenaltyPlayer1ClockMinutesOnes"] == "1"
    assert c["GuestPenaltyPlayer1ClockSecondOnes"] == "5" and c["GuestPenaltyPlayer2Ones"] == "4"


def test_lacrosse():
    _, c = run("Fairplay_Lacrosse", pkt(21, 0x81, {**clock_bytes(0x10, 0x00), 6: 0x05, 7: 0x04, 8: 0x03}),
               pkt(21, 0xC1, {7: 0x45}))
    assert c["EventId"] == "Lacrosse" and c["Period"] == "3" and c["HomeScoreOnes"] == "5"
    assert (c["ShotClockTens"], c["ShotClockOnes"]) == ("4", "5")


def test_soccer22():
    data = {**clock_bytes(0x33, 0x20), 6: 0x02, 7: 0x01, 8: 0x02, 11: 0x01, 12: 0x07, 13: 0x03, 14: 0x04, 15: 0x09,
            16: 0x12, 17: 0x05}
    _, c = run("Fairplay_Soccer_Code22", pkt(22, 0x81, data, length=20))
    assert c["EventId"] == "Soccer" and c["Period"] == "2"
    assert (c["HomeShotTens"], c["HomeShotOnes"], c["GuestShotOnes"]) == ("0", "7", "9")
    assert c["HomeSaves"] == "03" and c["GuestSaves"] == "12"
    assert c["HomeCornerKicks"] == "4" and c["GuestCornerKicks"] == "5"
    assert c["GuestPossession"] == ">" and c["HomePossession"] == " "


def test_soccer36_period_is_seven_segment():
    _, c = run("Fairplay_Soccer_Code36", pkt(36, 0x81, {6: 0x01, 7: 0x00, 8: 0x05, 9: 0x12, 10: 0x5B}))
    assert c["Period"] == "2" and c["HomeShotOnes"] == "5" and (c["GuestShotTens"], c["GuestShotOnes"]) == ("1", "2")


# ----------------------------------------------------------------------------- baseball / softball
def test_baseball30():
    # balls/strikes/outs are hex letters: A=1 B=2 C=3
    data = {6: 0x03, 7: 0x01, 8: 0x7B, 9: 0xAC, 10: 0x64, 12: 0x15, 13: 0x42}
    _, c = run("Fairplay_Baseball_Code30", pkt(30, 0x81, data, length=16))
    assert c["EventId"] == "Baseball" and c["ClockMode"] == ":" and c["InternalClockStatus"] == " "
    assert c["Balls"] == " " and c["Strikes"] == "3" and c["Outs"] == "1"
    assert (c["InningTens"], c["InningOnes"]) == ("7", " ")
    assert c["TopBottomInning"] == "T" and c["TopOfInning"] == "." and c["PitchCount"] == "042"
    assert c["ErrorFlag"] == "H"
    bottom = {**data, 10: 0x58, 9: 0xBA}
    _, c = run("Fairplay_Baseball_Code30", pkt(30, 0x81, bottom, length=16))
    assert c["TopBottomInning"] == "B" and c["BottomOfInning"] == "." and c["PitchCount"] == "015"
    assert c["ErrorFlag"] == "E" and c["Strikes"] == "1" and c["Outs"] == "2"
    assert c["Balls"] == " "


@pytest.mark.parametrize("pid", ["Fairplay_Baseball_Code31", "Fairplay_Softball_Code31"])
def test_baseball31_and_softball31(pid):
    data = {5: 0x07, 6: 0x02, 7: 0x11, 8: 0x25, 9: 0x12, 10: 0x08 | 0x10}
    _, c = run(pid, pkt(31, 0x81, data, length=16))
    assert c["EventId"] == "Baseball"  # ScoreConnect labels the softball id with the same decoder
    assert (c["Balls"], c["InningOnes"], c["Strikes"], c["Outs"]) == ("2", "5", "2", "1")
    assert (c["HomeRunTens"], c["HomeRunOnes"], c["GuestRunTens"], c["GuestRunOnes"]) == tuple("0211")
    assert c["TopBottomInning"] == "B" and c["BottomOfInning"] == "." and c["TopOfInning"] == " "
    assert c["ErrorFlag"] == "E" and (c["AtBatTens"], c["AtBatOnes"]) == ("0", "7")
    _, c = run(pid, pkt(31, 0x81, {**data, 10: 0x04 | 0x20}, length=16))
    assert c["TopBottomInning"] == "T" and c["TopOfInning"] == "." and c["ErrorFlag"] == "H"


def test_baseball32():
    data = {6: 0x04, 7: 0x05, 8: 0xB3, 9: 0xCA, 10: 0x08}
    _, c = run("Fairplay_Baseball_Code32", pkt(32, 0x81, data, length=16))
    assert c["Balls"] == "2" and c["Strikes"] == "1" and c["Outs"] == "3" and c["InningOnes"] == "3"
    assert c["HomeRunOnes"] == "4" and c["GuestRunOnes"] == "5" and c["TopBottomInning"] == "B"


def test_baseball33():
    data = {4: 0x12, 5: 0x35, 6: 0x21, 7: 0x03, 8: 0x24, 9: 0x71, 10: 0x10 | 0x04 | 0x01 | 0x80, 12: 0x09}
    _, c = run("Fairplay_Baseball_Code33", pkt(33, 0x81, data, length=16))
    assert (c["Balls"], c["Strikes"], c["Outs"]) == ("2", "1", "1")
    assert (c["GuestErrors"], c["HomeErrors"]) == ("3", "2")
    assert (c["InningTens"], c["InningOnes"]) == ("1", "7")
    assert (c["GuestRunTens"], c["GuestRunOnes"], c["HomeRunTens"], c["HomeRunOnes"]) == tuple("1203")
    assert (c["GuestHitsTens"], c["GuestHitsOnes"], c["HomeHitsTens"], c["HomeHitsOnes"]) == ("1", "5", "1", "4")
    assert c["AtBatOnes"] == "9" and c["TopBottomInning"] == "B"
    _, c = run("Fairplay_Baseball_Code33", pkt(33, 0x81, {10: 0x40}, length=16))
    assert c["TopBottomInning"] == "T" and c["InningTens"] == " "


def linescore34(guest, home):
    d = {}
    for n, v in enumerate(guest):
        d[12 + n // 2] = d.get(12 + n // 2, 0) | (v << (4 * (n % 2)))
    for n, v in enumerate(home):
        d[20 + n // 2] = d.get(20 + n // 2, 0) | (v << (4 * (n % 2)))
    return d


def test_baseball34_inning_from_linescore():
    blank = 0xF
    guest = [1, 0, 2, 0, 3, blank, blank, blank, blank, blank]
    home = [0, 0, 1, 2, blank, blank, blank, blank, blank, blank]
    data = {**linescore34(guest, home), 4: 0x09, 5: 0x08, 6: 0x21, 7: 0x05, 8: 0x21, 9: 0x30, 17: 0x06, 25: 0x03}
    _, c = run("Fairplay_BaseballSoftball_Code34", pkt(34, 0x81, data, length=24))
    assert (c["GuestInning1"], c["GuestInning5"], c["GuestInning6"]) == ("1", "3", " ")
    assert (c["HomeInning3"], c["HomeInning4"], c["HomeInning5"]) == ("1", "2", " ")
    assert (c["Outs"], c["Strikes"], c["Balls"]) == ("2", "1", "3")
    assert c["GuestRunOnes"] == "6" and c["HomeRunOnes"] == "3"
    assert (c["GuestHitsTens"], c["GuestHitsOnes"], c["HomeHitsOnes"]) == ("0", "8", "5")
    assert (c["HomeErrors"], c["GuestErrors"]) == ("2", "1")
    # guest has batted in innings 1-5, home in 1-4: inning 5, top
    assert (c["InningTens"], c["InningOnes"]) == ("0", "5")
    assert c["TopBottomInning"] == "T" and c["TopOfInning"] == "." and c["BottomOfInning"] == " "
    # home inning 5 filled -> bottom of 5
    home[4] = 0
    data = {**linescore34(guest, home), 4: 0x09}
    _, c = run("Fairplay_BaseballSoftball_Code34", pkt(34, 0x81, data, length=24))
    assert (c["InningTens"], c["InningOnes"]) == ("0", "5") and c["TopBottomInning"] == "B"


def test_baseball35():
    d = {4: 0x21, 5: 0x03, 6: 0xFF, 7: 0xFF, 8: 0x32, 9: 0x05, 12: 0x10, 13: 0x20, 14: 0xFF, 15: 0xFF, 16: 0x2F,
         17: 0x04, 18: 0x86, 20: 0x11}
    _, c = run("Fairplay_BaseballSoftball_Code35", pkt(35, 0x81, d, length=24))
    assert (c["GuestInning1"], c["GuestInning2"], c["GuestInning3"], c["GuestInning4"]) == ("1", "2", "3", "0")
    assert c["GuestInning5"] == " " and c["GuestInning9"] == "2"  # byte 8 low nibble
    assert c["Balls"] == "3" and c["Strikes"] == "2" and c["Outs"] == "1"
    assert c["HomeInning1"] == "0" and c["HomeInning2"] == "1" and c["HomeInning9"] == " "
    assert (c["GuestRunTens"], c["GuestRunOnes"], c["HomeRunOnes"], c["AtBatOnes"]) == ("0", "5", "4", "1")
    assert fairplay._fairplay_outs(0xBF) == "0" and fairplay._fairplay_outs(0xDB) == "2"
    assert fairplay._fairplay_outs(0x00) == " "


# ----------------------------------------------------------------------------- framing
def test_garbage_before_frame():
    proto = create("Fairplay_Football_Code24")
    frame = pkt(24, 0x81, {**clock_bytes(0x10, 0x00), 6: 0x07})
    proto.feed(b"\x99\x98\x97\x01\x02" + frame)
    assert proto.packets == 1 and proto.snapshot()["HomeScoreOnes"] == "7"


def test_garbage_containing_the_code_byte():
    proto = create("Fairplay_Football_Code24")
    frame = pkt(24, 0x81, {**clock_bytes(0x10, 0x00), 6: 0x07})
    proto.feed(bytes([24, 0x81, 0, 2, 1, 2, 3]) + frame)  # a false start with a bad sum
    assert proto.packets == 1 and proto.bad >= 1 and proto.snapshot()["HomeScoreOnes"] == "7"


def test_frame_split_across_feeds():
    proto = create("Fairplay_Soccer_Code22")
    frame = pkt(22, 0x81, {**clock_bytes(0x10, 0x00), 6: 0x03}, length=20)
    for i in range(0, len(frame), 5):
        proto.feed(frame[i : i + 5])
    assert proto.packets == 1 and proto.bad == 0 and proto.snapshot()["HomeScoreOnes"] == "3"
    proto.feed(frame[:2])
    proto.feed(frame[2:3])
    assert proto.packets == 1


def test_checksum_rejected_then_recovers():
    proto = create("Fairplay_Hockey_Code14")
    good = pkt(14, 0x81, {6: 0x05}, length=36)
    bad = bytearray(good)
    bad[6] ^= 0x01
    proto.feed(bytes(bad))
    assert proto.packets == 0 and proto.bad >= 1
    proto.feed(good)
    assert proto.packets == 1 and proto.snapshot()["HomeScoreOnes"] == "5"


def test_sum_is_16_bit_not_truncated():
    # a large L whose byte sum exceeds 255 must still verify through the high byte of the trailer
    proto = create("Fairplay_Basketball_Code1")
    frame = pkt(1, 0x81, {k: 0xEE for k in range(9, 30)}, length=40)
    assert frame[-1] != 0
    proto.feed(frame)
    assert proto.packets == 1
    broken = bytearray(frame)
    broken[-1] ^= 1
    p2 = create("Fairplay_Basketball_Code1")
    p2.feed(bytes(broken))
    assert p2.packets == 0 and p2.bad >= 1


def test_two_frames_back_to_back_and_wrong_code_ignored():
    proto = create("Fairplay_Football_Code23")
    a = pkt(23, 0x81, {6: 0x01})
    b = pkt(23, 0x81, {6: 0x02})
    proto.feed(a + b)
    assert proto.packets == 2 and proto.snapshot()["HomeScoreOnes"] == "2"
    p2 = create("Fairplay_Football_Code24")
    p2.feed(pkt(23, 0x81, {6: 0x01}))
    assert p2.packets == 0
