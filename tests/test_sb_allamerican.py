from scoreboards import allamerican as aa
from scoreboards.common import crc16_ccitt


def f8000(page, fill, **at):
    """Model 8000 frame: byte 9 = page type, at = {index: value}."""
    p = bytearray(32)
    p[0] = 0xFC
    p[9] = page
    for k, v in fill.items():
        p[int(k)] = v
    total = sum(p[3:30])
    lo, hi = total & 0xFF, total >> 8
    p[30] = 0x69 if lo == 0xFC else lo
    p[31] = 0x69 if hi == 0xFC else hi
    return bytes(p)


def f3000(vals):
    p = bytearray(20)
    p[0] = 0xFC
    for k, v in vals.items():
        p[k] = v
    return bytes(p)


def f9000(vals):
    p = bytearray(34)
    p[0] = 0xFC
    for k, v in vals.items():
        p[k] = v
    crc = crc16_ccitt(p, 0, 32)
    p[32], p[33] = crc >> 8, crc & 0xFF
    return bytes(p)


def run(pid, data):
    pr = aa.PROTOCOLS[pid]()
    pr.feed(data)
    return pr, pr.snapshot()


def test_all_ids_registered():
    assert set(aa.PROTOCOLS) == {
        "AllAmerican3000_Football", "AllAmerican9000_Baskteball", "AllAmerican9000_Football",
        "AllAmerican9000_Hockey", "AllAmerican_Baseball", "AllAmerican_Basketeball", "AllAmerican_Football",
        "AllAmerican_Hockey", "AllAmerican_Soccer", "AllAmerican_Volleyball"}


def test_main_football():
    fr = f8000(0x11, {4: 0x12, 5: 0x34, 7: 0x25, 10: 0x21, 11: 1, 12: 0x14, 14: 3, 17: 0x10, 18: 2,
                      19: 0x32, 20: 0x35, 3: 0x80})
    pr, c = run("AllAmerican_Football", fr)
    assert pr.packets == 1 and pr.contract_name == "Football" and c["EventId"] == "Football"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondOnes"]) == (":", "1", "4")
    assert (c["PlayClockTens"], c["PlayClockOnes"]) == ("2", "5")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "1", "1", "4")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert (c["Quarter"], c["Down"], c["ToGoTens"], c["ToGoOnes"]) == ("3", "2", "1", "0")
    assert (c["HomeTimeouts"], c["GuestTimeouts"], c["BallOnTens"], c["BallOnOnes"]) == ("3", "2", "3", "5")
    assert c["Horn"] == "H"


def test_main_sub_minute_clock_and_guest_possession():
    fr = f8000(0x11, {4: 0x00, 5: 0x45, 6: 0x07, 13: 1})
    _, c = run("AllAmerican_Football", fr)
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockTenthsSecond"]) == (".", "0", "4", "7")
    assert (c["HomePossession"], c["GuestPossession"]) == (" ", ">")


def test_main_other_page_does_not_touch_scores():
    pr = aa.PROTOCOLS["AllAmerican_Football"]()
    pr.feed(f8000(0x11, {10: 0x21}))
    pr.feed(f8000(0x22, {4: 0x05}))
    assert pr.snapshot()["HomeScoreOnes"] == "1"


def test_main_basketball():
    fr = f8000(0x11, {4: 0x07, 5: 0x30, 7: 0x24, 10: 0x05, 11: 0x0F, 12: 0x99, 13: 0x10, 14: 0x02, 15: 0x12,
                      16: 0x08, 17: 0x23, 18: 5, 19: 0x21})
    _, c = run("AllAmerican_Basketeball", fr)
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"]) == ("7", "3")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "9", "9")
    assert c["HomeBonus"] == "B" and c["GuestBonus"] == " "
    assert c["HomeDoubleBonus"] == "B"  # byte 13 bit 4 (ScoreConnect quirk)
    assert "GuestDoubleBonus" not in c
    assert (c["Period"], c["HomeFoulTens"], c["GuestFoulOnes"]) == ("2", "1", "8")
    assert (c["FoulPlayerTens"], c["FoulPlayerOnes"], c["FoulPlayerNumberOfFouls"]) == ("2", "3", "5")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("2", "1")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")


def test_main_hockey_both_pages():
    pr = aa.PROTOCOLS["AllAmerican_Hockey"]()
    pr.feed(f8000(0x11, {4: 0x15, 5: 0x00, 7: 0x30, 10: 0x03, 12: 0x01, 14: 2, 15: 0x12, 16: 0x07, 19: 0x21,
                         20: 0x15, 21: 0x09}))
    pr.feed(f8000(0x22, {7: 0x30, 10: 0x02, 11: 0x00, 12: 0x17, 13: 0x01, 14: 0x30, 15: 0x22, 16: 0x00, 17: 0x45,
                         18: 0x09, 19: 0x05, 20: 0x00, 21: 0x11}))
    c = pr.snapshot()
    assert pr.packets == 2 and pr.contract_name == "HockeyLacrosse"
    assert (c["Period"], c["HomeScoreOnes"], c["GuestScoreOnes"], c["HomeSaves"], c["GuestSaves"]) == ("2", "3", "1", "15", "09")
    assert (c["ShotClockTens"], c["HomeTimeOut"], c["GuestTimeOut"]) == ("3", "2", "1")
    assert (c["HomeShotOnGoalTens"], c["GuestShotOnGoalOnes"]) == ("1", "7")
    assert (c["HomePenaltyPlayer1Tens"], c["HomePenaltyPlayer1Ones"], c["HomePenaltyPlayer1ClockMinutesOnes"]) == ("1", "7", "2")
    assert (c["HomePenaltyPlayer2ClockSecondTens"], c["GuestPenaltyPlayer1ClockSecondTens"]) == ("3", "4")
    assert (c["GuestPenaltyPlayer2Tens"], c["GuestPenaltyPlayer2Ones"]) == ("1", "1")
    assert c["HomePenaltyPlayer3Tens"] == " " and c["GuestPenaltyPlayer3ClockSecondOnes"] == " "
    assert c["EventId"] == "Hockey"


def test_main_soccer():
    fr = f8000(0x11, {4: 0x40, 5: 0x05, 10: 0x02, 12: 0x01, 14: 2, 15: 0x08, 16: 0x11, 19: 0x10, 20: 0x04,
                      21: 0x12, 3: 0x80})
    pr, c = run("AllAmerican_Soccer", fr)
    assert pr.contract_name == "Soccer"
    assert (c["Period"], c["HomeScoreOnes"], c["GuestScoreOnes"], c["HomeCornerKicks"], c["GuestCornerKicks"]) == ("2", "2", "1", "04", "12")
    assert (c["HomeShotOnes"], c["GuestShotTens"], c["HomeTimeouts"], c["Horn"]) == ("8", "1", "1", "H")
    assert (c["ClockMinutesTens"], c["ClockSecondOnes"]) == ("4", "5")


def test_main_volleyball():
    fr = f8000(0x11, {4: 0x00, 5: 0x00, 10: 0x15, 11: 1, 12: 0x12, 14: 3, 15: 1, 16: 2, 19: 0x21, 20: 0x25,
                      21: 0x23, 22: 0x19, 23: 0x25, 24: 0x08, 25: 0x03})
    pr, c = run("AllAmerican_Volleyball", fr)
    assert pr.contract_name == "Volleyball"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreOnes"]) == ("1", "5", "2")
    assert (c["HomeServe"], c["GuestServe"], c["Game"], c["Set"]) == ("*", " ", "3", " ")
    assert (c["HomeGamesWon"], c["GuestGamesWon"], c["HomeTimeout"], c["GuestTimeout"]) == ("1", "2", "2", "1")
    assert (c["HomeScoreSet1"], c["GuestScoreSet1"], c["HomeScoreSet2"], c["GuestScoreSet2"]) == ("25", "23", "19", "25")
    assert (c["HomeScoreSet3"], c["GuestScoreSet3"]) == ("08", "03")


def test_main_baseball_both_pages():
    pr = aa.PROTOCOLS["AllAmerican_Baseball"]()
    pr.feed(f8000(0x11, {10: 0x03, 12: 0x05, 13: 1, 14: 0x07, 16: 0x21, 17: 0x12, 18: 0x03, 20: 0x09,
                         21: 0x14, 22: 0x20, 27: 4}))
    pr.feed(f8000(0x22, {10: 0, 11: 1, 12: 2, 19: 3, 20: 0, 21: 4, 29: 5}))
    c = pr.snapshot()
    assert pr.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert (c["HomeRunOnes"], c["GuestRunOnes"], c["InningTens"], c["InningOnes"]) == ("3", "5", "0", "7")
    assert (c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"]) == ("T", ".", " ")
    assert (c["Balls"], c["Strikes"], c["Outs"], c["AtBatOnes"], c["GuestErrorNumber"]) == ("3", "1", "2", "9", "4")
    assert (c["HomeErrors"], c["GuestErrors"], c["HomeHitsTens"], c["HomeHitsOnes"], c["GuestHitsTens"]) == ("2", "1", "1", "4", "2")
    assert (c["GuestInning2"], c["GuestInning3"], c["GuestInning10"], c["HomeInning2"], c["HomeInning10"]) == ("1", "2", "3", "4", "5")
    pr.feed(f8000(0x11, {13: 0}))
    assert pr.snapshot()["TopBottomInning"] == "B"


def test_main_checksum_0xfc_substitution():
    # Find a payload whose sum low byte is 0xFC so the sender writes 0x69 instead
    fr = bytearray(f8000(0x11, {10: 0x12}))
    fr[20] = (0xFC - sum(fr[3:30]) + fr[20]) & 0xFF
    assert sum(fr[3:30]) & 0xFF == 0xFC and fr[20] != 0xFC
    fr[30] = 0x69
    fr[31] = 0x69 if (sum(fr[3:30]) >> 8) == 0xFC else sum(fr[3:30]) >> 8
    pr, c = run("AllAmerican_Football", bytes(fr))
    assert pr.packets == 1 and c["HomeScoreOnes"] == "2"


def test_main_garbage_split_and_bad_checksum():
    fr = f8000(0x11, {10: 0x42})
    pr = aa.PROTOCOLS["AllAmerican_Football"]()
    pr.feed(b"\x01\x02\x03" + fr[:10])
    assert pr.packets == 0
    pr.feed(fr[10:])
    assert pr.packets == 1 and pr.snapshot()["HomeScoreTens"] == "4"
    bad = bytearray(fr)
    bad[31] ^= 1
    pr.feed(bytes(bad))
    assert pr.packets == 1 and pr.bad == 1
    pr.feed(f8000(0x11, {10: 0x57}))
    assert pr.packets == 2 and pr.snapshot()["HomeScoreTens"] == "5"


def test_3000_football():
    fr = f3000({1: 1, 2: 4, 3: 2, 5: 7, 6: 1, 8: 0, 9: 1, 10: 5, 11: 3, 12: 2, 13: 4, 15: 9, 16: 5, 17: 3, 18: 1})
    pr, c = run("AllAmerican3000_Football", fr)
    assert pr.packets == 1 and c["EventId"] == "Football"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "4", "1", "7")
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "3", "5", "9")
    assert (c["Quarter"], c["Down"], c["ToGoTens"], c["ToGoOnes"], c["BallOnTens"], c["BallOnOnes"]) == ("4", "2", "1", "0", "3", "5")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    pr.feed(f3000({1: 2}))
    assert (pr.snapshot()["HomePossession"], pr.snapshot()["GuestPossession"]) == (" ", ">")


def test_3000_garbage_split():
    fr = f3000({2: 7})
    pr = aa.PROTOCOLS["AllAmerican3000_Football"]()
    pr.feed(b"\x00\x11" + fr[:7])
    assert pr.packets == 0
    pr.feed(fr[7:] + fr[:5])
    assert pr.packets == 1 and pr.snapshot()["HomeScoreOnes"] == "7"
    pr.feed(fr[5:])
    assert pr.packets == 2


def test_9000_football():
    fr = f9000({4: 12, 5: 34, 12: 25, 14: 0x10, 15: 7, 16: 21, 17: 3, 18: 2, 19: 35, 20: 8, 21: 2, 22: 1})
    pr, c = run("AllAmerican9000_Football", fr)
    assert pr.packets == 1 and pr.contract_name == "Football"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "2", "3", "4")
    assert (c["PlayClockTens"], c["PlayClockOnes"], c["Quarter"], c["Down"]) == ("2", "5", "3", "2")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "7", "2", "1")
    assert (c["BallOnTens"], c["BallOnOnes"], c["ToGoTens"], c["ToGoOnes"]) == ("3", "5", " ", "8")
    assert (c["HomeTimeouts"], c["GuestTimeouts"], c["HomePossession"], c["GuestPossession"]) == ("2", "1", "<", " ")
    pr.feed(f9000({14: 0x20}))
    assert (pr.snapshot()["HomePossession"], pr.snapshot()["GuestPossession"]) == (" ", ">")


def test_9000_basketball():
    fr = f9000({4: 0, 5: 45, 6: 7, 9: 24, 14: 0x11, 15: 105, 16: 8, 17: 2, 18: 3, 19: 12, 20: 0x23, 21: 4,
                22: 5, 23: 2, 24: 1})
    pr, c = run("AllAmerican9000_Baskteball", fr)
    assert pr.contract_name == "Basketball"
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "4", "5", "7")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", " ", "8")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "3", "1", "2")
    assert (c["HomeBonus"], c["GuestBonus"], c["HomeDoubleBonus"], c["GuestDoubleBonus"]) == ("B", " ", "B", " ")
    assert (c["Period"], c["FoulPlayerTens"], c["FoulPlayerOnes"], c["FoulPlayerNumberOfFouls"]) == ("2", "2", "3", "4")
    assert (c["HomeTimeouts"], c["GuestTimeouts"], c["Horn"], c["HomePossession"]) == ("2", "1", "H", "<")


def test_9000_hockey_quirk():
    fr = f9000({4: 9, 5: 59, 15: 3, 16: 12, 17: 1, 18: 25, 19: 9, 20: 2, 21: 1, 22: 17, 23: 33})
    pr, c = run("AllAmerican9000_Hockey", fr)
    assert pr.contract_name == "HockeyLacrosse" and c["EventId"] == "Hockey"
    assert (c["Period"], c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", " ", "3", "1", "2")
    assert (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"], c["GuestShotOnGoalTens"], c["GuestShotOnGoalOnes"]) == ("2", "5", " ", "9")
    assert (c["HomeTimeOut"], c["GuestTimeOut"]) == ("2", "1")
    assert c["HomeSaves"] == "33" and "GuestSaves" not in c


def test_9000_framing():
    fr = f9000({15: 11})
    pr = aa.PROTOCOLS["AllAmerican9000_Football"]()
    pr.feed(b"\x10\x20" + fr[:20])
    assert pr.packets == 0
    pr.feed(fr[20:])
    assert pr.packets == 1
    bad = bytearray(fr)
    bad[33] ^= 0xFF
    pr.feed(bytes(bad))
    assert pr.packets == 1 and pr.bad == 1
    pr.feed(f9000({15: 22}))
    assert pr.packets == 2 and pr.snapshot()["HomeScoreTens"] == "2"
