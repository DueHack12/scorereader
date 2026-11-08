from scoreboards import spectrum as sp


def body(n, fill):
    """n bytes of ASCII blanks with fill = {index: char-or-int}; byte 0 is the start byte 0x02."""
    p = bytearray(b" " * n)
    p[0] = 2
    for k, v in fill.items():
        p[k] = ord(v) if isinstance(v, str) else v
    return p


def v2w(n, fill):
    return bytes(body(n, fill)) + b"\n"


def v2e(n, fill):  # n counts the LF, like ScoreConnect's length check
    return bytes(body(n - 1, fill)) + b"\n\x00"


def put(s, start):
    return {start + i: ch for i, ch in enumerate(s)}


def run(pid, data):
    pr = sp.PROTOCOLS[pid]()
    pr.feed(data)
    return pr, pr.snapshot()


def test_all_ids_registered():
    assert set(sp.PROTOCOLS) == {
        "SpectrumMS250_Baseball", "SpectrumMSX_Hockey", "SpectrumV2E_Baseball", "SpectrumV2E_Basketball", "SpectrumV2E_Football",
        "SpectrumV2E_Soccer", "SpectrumV2W_Baseball", "SpectrumV2W_Basketball", "SpectrumV2W_Football",
        "SpectrumV2W_Soccer", "SpectrumV2W_Volleyball", "SpectrumV2_Basketball"}


# ---------------------------------------------------------------- V2W
FOOTBALL = {**put("1234", 1), **put("2114", 5), **put("0710", 9), **put("35", 15), 21: "3", 22: "2", 23: "4",
            24: "1", **put("25", 25), 12: 3}


def test_v2w_football():
    pr, c = run("SpectrumV2W_Football", v2w(35, FOOTBALL))
    assert pr.packets == 1 and pr.contract_name == "Football"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "1", "1", "4")
    assert (c["ToGoTens"], c["ToGoOnes"], c["BallOnTens"], c["BallOnOnes"], c["Down"]) == ("0", "7", "3", "5", "3")
    assert (c["HomeTimeouts"], c["Quarter"], c["GuestTimeouts"], c["PlayClockTens"], c["PlayClockOnes"]) == ("2", "4", "1", "2", "5")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", ">")


def test_v2w_football_clock_ignores_bit3_and_hi_bit_masked():
    fr = v2w(35, {**FOOTBALL, 12: 8, 1: ord("1") | 0x80, 3: ":"})
    _, c = run("SpectrumV2W_Football", fr)
    assert c["ClockMode"] == ":" and c["ClockMinutesTens"] == "1" and c["ClockSecondTens"] == " "
    assert (c["HomePossession"], c["GuestPossession"]) == (" ", " ")


def test_v2w_lengths_garbage_split_and_reject():
    pr = sp.PROTOCOLS["SpectrumV2W_Football"]()
    fr = v2w(41, FOOTBALL)
    pr.feed(fr[:20])
    assert pr.packets == 0
    pr.feed(fr[20:])
    assert pr.packets == 1
    pr.feed(v2w(44, FOOTBALL))
    assert pr.packets == 2
    pr.feed(v2w(30, FOOTBALL))  # wrong length
    assert pr.packets == 2 and pr.bad == 1
    pr.feed(b"\n")  # empty line
    assert pr.bad == 2
    pr.feed(b"junk" + v2w(35, FOOTBALL))  # garbage glued to a frame changes the length -> rejected
    assert pr.bad == 3
    pr.feed(v2w(35, FOOTBALL))
    assert pr.packets == 3


def test_v2w_soccer():
    fr = v2w(35, {**put("4530", 1), **put("23", 5), **put("14", 7), **put("07", 9), **put("11", 15), 12: "2",
                  21: "5", 22: "1", 23: "3", 24: "0"})
    pr, c = run("SpectrumV2W_Soccer", fr)
    assert pr.contract_name == "Soccer"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreOnes"], c["HomeShotOnes"], c["GuestShotTens"]) == ("2", "3", "4", "7", "1")
    assert (c["Period"], c["HomePenalties"], c["GuestPenalties"]) == ("2", "15", "03")
    assert (c["ClockMinutesTens"], c["ClockSecondOnes"]) == ("4", "0")


def test_v2w_volleyball():
    fr = v2w(35, {**put("1525", 5), 22: "2", 23: "3", 24: "1"})
    pr, c = run("SpectrumV2W_Volleyball", fr)
    assert pr.contract_name == "Volleyball"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "5", "2", "5")
    assert (c["HomeGamesWon"], c["GuestGamesWon"], c["Set"]) == ("2", "1", "3")


def test_v2w_basketball_clock_modes_and_flags():
    common = {**put("0830", 1), **put("42", 5), **put("37", 7), **put("2", 25), 26: "4", **put("05", 21),
              16: "0", 24: "3", 23: "2", 30: "3", 31: "2"}
    fr = v2w(35, {**common, 12: 8 | 1, 14: 1 | 4 | 8, 11: 8})
    pr, c = run("SpectrumV2W_Basketball", fr)
    assert pr.contract_name == "Basketball"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == (":", "0", "8", "3", "0")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "4", "2")
    assert (c["GuestScoreHundreds"], c["GuestScoreOnes"]) == (" ", "7")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert (c["HomeBonus"], c["GuestBonus"], c["HomeDoubleBonus"], c["GuestDoubleBonus"]) == ("B", "B", "B", " ")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["HomeFoulOnes"], c["GuestFoulOnes"]) == ("2", "4", "5", "3")
    assert (c["Period"], c["HomeTimeouts"], c["GuestTimeouts"], c["HomeFullTimeouts"]) == ("2", "3", "2", " ")
    fr = v2w(35, {**common, 12: 2, 14: 2})
    _, c = run("SpectrumV2W_Basketball", fr)
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "0", "0", "8", "3")
    assert (c["GuestPossession"], c["GuestScoreHundreds"], c["HomeScoreHundreds"]) == (">", "1", " ")


def baseball_fill(extra):
    return {**put("123", 1), **put("0507", 5), **put("12", 9), **put("0407", 15), 19: "1", 20: "2", **extra}


def test_v2w_baseball_top_and_bottom():
    # guest 1,0,2 / home 0,1 -> bottom of the 2nd inning
    inn = {21: "1", 22: "0", 23: "0", 24: "1", 25: "2"}
    pr, c = run("SpectrumV2W_Baseball", v2w(44, baseball_fill(inn)))
    assert pr.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert (c["Balls"], c["Strikes"], c["Outs"]) == ("1", "2", "3")
    assert (c["HomeRunTens"], c["HomeRunOnes"], c["GuestRunTens"], c["GuestRunOnes"]) == ("0", "5", "0", "7")
    assert (c["AtBatTens"], c["AtBatOnes"], c["HomeHitsOnes"], c["GuestHitsOnes"], c["HomeErrors"], c["GuestErrors"]) == ("1", "2", "4", "7", "1", "2")
    assert (c["GuestInning1"], c["HomeInning1"], c["GuestInning2"], c["HomeInning2"], c["GuestInning3"]) == ("1", "0", "0", "1", "2")
    assert (c["InningTens"], c["InningOnes"], c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"]) == ("0", "3", "T", ".", " ")
    inn = {21: "1", 22: "0", 23: "0", 24: "1"}
    _, c = run("SpectrumV2W_Baseball", v2w(44, baseball_fill(inn)))
    assert (c["InningOnes"], c["TopBottomInning"], c["BottomOfInning"]) == ("2", "B", ".")


def test_v2w_baseball_short_packet_does_not_raise():
    pr, c = run("SpectrumV2W_Baseball", v2w(35, baseball_fill({21: "1"})))
    assert pr.packets == 1 and c["GuestInning1"] == "1" and "GuestInning10" not in c


# ---------------------------------------------------------------- V2E
def test_v2e_football():
    pr, c = run("SpectrumV2E_Football", v2e(36, {**FOOTBALL, 12: 53, 4: "F"}))
    assert pr.packets == 1 and pr.contract_name == "Football"
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert c["ClockSecondOnes"] == " "  # "F" reads as blank on V2E
    assert (c["HomeScoreOnes"], c["Quarter"], c["Down"]) == ("1", "4", "3")
    _, c = run("SpectrumV2E_Football", v2e(44, {**FOOTBALL, 12: 65}))
    assert (c["HomePossession"], c["GuestPossession"]) == (" ", ">")


def test_v2e_framing():
    pr = sp.PROTOCOLS["SpectrumV2E_Football"]()
    fr = v2e(36, FOOTBALL)
    pr.feed(fr[:10])
    assert pr.packets == 0
    pr.feed(fr[10:])
    assert pr.packets == 1
    pr.feed(v2e(35, FOOTBALL))  # wrong length
    assert pr.packets == 1 and pr.bad == 1
    pr.feed(b"\x01\x02\n\x00")  # garbage ending in the terminator
    assert pr.bad == 2
    pr.feed(fr)
    assert pr.packets == 2


def test_v2e_soccer():
    fr = v2e(36, {**put("4530", 1), **put("23", 5), **put("14", 7), **put("07", 9), **put("11", 15), 12: "2",
                  21: "5", 22: "1", 23: "3", 24: "0"})
    pr, c = run("SpectrumV2E_Soccer", fr)
    assert pr.contract_name == "Soccer"
    assert (c["HomeScoreOnes"], c["GuestScoreOnes"], c["Period"], c["HomePenalties"], c["GuestPenalties"]) == ("3", "4", "2", "15", "03")


def test_v2e_basketball_status_bytes_offset_by_seven():
    # status bytes >= 64 lose 7 before the flag bits are read
    common = {**put("1000", 1), **put("42", 5), **put("37", 7), **put("2", 25), 26: "4", **put("05", 21),
              16: "0", 24: "3", 23: "2", 30: "3", 31: "2"}
    fr = v2e(36, {**common, 12: 0x40 + 9, 14: 0x30 | 1 | 4, 11: 0x30 | 4})
    pr, c = run("SpectrumV2E_Basketball", fr)
    assert pr.contract_name == "Basketball"
    # 0x49 - 7 = 0x42: bit 8 clear -> seconds mode, bit 1 clear, bit 2 set
    assert c["ClockMode"] == "." and c["ClockSecondTens"] == "1"
    assert (c["HomePossession"], c["GuestPossession"]) == (" ", ">")
    assert (c["HomeScoreHundreds"], c["HomeBonus"], c["GuestBonus"]) == ("1", "B", " ")
    assert (c["HomeDoubleBonus"], c["GuestDoubleBonus"]) == (" ", "B")
    # plain (<64) status bytes work as on V2W
    fr = v2e(36, {**common, 12: 8 | 2, 14: 2 | 8, 11: 8})
    _, c = run("SpectrumV2E_Basketball", fr)
    assert c["ClockMode"] == ":" and c["ClockMinutesTens"] == "1" and c["GuestPossession"] == ">"
    assert (c["GuestScoreHundreds"], c["GuestBonus"], c["HomeDoubleBonus"], c["Period"]) == ("1", "B", "B", "2")


def test_v2e_baseball():
    inn = {21: "1", 22: "0", 23: "0"}
    pr, c = run("SpectrumV2E_Baseball", v2e(44, baseball_fill(inn)))
    assert pr.contract_name == "BaseballSoftball"
    assert (c["Balls"], c["InningOnes"], c["TopBottomInning"], c["GuestRunOnes"]) == ("1", "2", "T", "7")
    pr, c = run("SpectrumV2E_Baseball", v2e(36, baseball_fill(inn)))  # short frame: only innings 1-7 reached
    assert pr.packets == 1 and "HomeInning10" not in c


# ---------------------------------------------------------------- V2 basketball (text)
def test_v2_basketball_text():
    pr, c = run("SpectrumV2_Basketball", b">12:34.5,45,7,3<\n")
    assert pr.packets == 1 and pr.contract_name == "Basketball"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", "0")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "4", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"], c["Period"]) == (" ", " ", "7", "3")
    _, c = run("SpectrumV2_Basketball", b">00:09.8,102,99,4\r\n")
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "0", "9", "8")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "2")


def test_v2_basketball_framing():
    pr = sp.PROTOCOLS["SpectrumV2_Basketball"]()
    pr.feed(b">12:34.5,45,7")
    assert pr.packets == 0
    pr.feed(b",3<\n")
    assert pr.packets == 1
    pr.feed(b"garbage\n")  # no ">"
    pr.feed(b"\n")
    assert pr.bad == 2
    pr.feed(b">1,2\n")  # too few fields: decoded as nothing, no exception
    assert pr.snapshot()["HomeScoreOnes"] == "5"


# ---------------------------------------------------------------- MS250
def ms250(fill):
    p = bytearray(13)
    p[1] = 0x0F
    for k, v in fill.items():
        p[k] = v
    return bytes(p)


def test_ms250_baseball():
    fr = ms250({2: 0x07, 3: 0x01, 4: 0x02, 5: 0x00, 6: 0x09, 10: 0x03, 11: 0x05, 12: 0x01})
    pr, c = run("SpectrumMS250_Baseball", fr)
    assert pr.packets == 1 and pr.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert (c["InningOnes"], c["HomeRunTens"], c["HomeRunOnes"], c["GuestRunTens"], c["GuestRunOnes"]) == ("7", "1", "2", "0", "9")
    assert (c["Balls"], c["Strikes"], c["Outs"], c["TopBottomInning"]) == ("2", "1", "1", "B")
    c = run("SpectrumMS250_Baseball", ms250({10: 7, 11: 3, 12: 3}))[1]
    assert (c["Balls"], c["Strikes"], c["Outs"], c["TopBottomInning"]) == ("3", "2", "2", "T")


def test_ms250_unknown_lamp_pattern_keeps_value_and_framing():
    pr = sp.PROTOCOLS["SpectrumMS250_Baseball"]()
    fr = ms250({10: 1})
    pr.feed(b"\x55\x66" + fr[:6])
    assert pr.packets == 0
    pr.feed(fr[6:])
    assert pr.packets == 1 and pr.snapshot()["Balls"] == "1"
    pr.feed(ms250({10: 2}))  # 2 is not a lamp pattern
    assert pr.packets == 2 and pr.snapshot()["Balls"] == "1"
    pr.feed(fr[:12])  # incomplete frame waits
    assert pr.packets == 2


# ---------------------------------------------------------------- MSX hockey (V2E framing)
HOCKEY = {**put("1530", 1), **put("0312", 5), 23: "2", 12: 8}


def test_msx_hockey_without_penalties():
    pr, c = run("SpectrumMSX_Hockey", v2e(36, HOCKEY))
    assert pr.packets == 1 and pr.contract_name == "HockeyLacrosse" and c["EventId"] == "Hockey"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondOnes"]) == (":", "1", "0")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"], c["Period"]) == ("0", "3", "1", "2", "2")
    assert "HomePenaltyPlayer1Tens" not in c


def test_msx_hockey_penalties_possession_and_subminute():
    pen = {**put("12", 20), 22: "2", **put("30", 24), **put("34", 26), 28: "1", **put("45", 29),
           **put("07", 31), 33: "1", **put("15", 34), **put("99", 36), 38: "2", **put("00", 39)}
    # byte 12 = 65 ("A") is guest possession; 65 - 7 = 58 has bit 3 set so the clock is mm:ss
    _, c = run("SpectrumMSX_Hockey", v2e(44, {**HOCKEY, **pen, 12: 65}))
    assert (c["GuestPossession"], c["HomePossession"], c["ClockMode"]) == (">", " ", ":")
    assert (c["HomePenaltyPlayer1Tens"], c["HomePenaltyPlayer1Ones"], c["HomePenaltyPlayer1ClockMinutesTens"],
            c["HomePenaltyPlayer1ClockMinutesOnes"]) == ("1", "2", " ", "2")
    assert (c["HomePenaltyPlayer1ClockSecondTens"], c["HomePenaltyPlayer1ClockSecondOnes"]) == ("3", "0")
    assert (c["GuestPenaltyPlayer1Tens"], c["GuestPenaltyPlayer1Ones"], c["GuestPenaltyPlayer1ClockMinutesOnes"]) == ("3", "4", "1")
    assert (c["GuestPenaltyPlayer1ClockSecondTens"], c["GuestPenaltyPlayer1ClockSecondOnes"]) == ("4", "5")
    assert (c["HomePenaltyPlayer2Tens"], c["HomePenaltyPlayer2Ones"], c["HomePenaltyPlayer2ClockMinutesOnes"]) == ("0", "7", "1")
    assert (c["HomePenaltyPlayer2ClockSecondTens"], c["HomePenaltyPlayer2ClockSecondOnes"]) == ("1", "5")
    assert (c["GuestPenaltyPlayer2Tens"], c["GuestPenaltyPlayer2ClockSecondOnes"]) == ("9", "0")
    # byte 12 = "5" is home possession; 53 has bit 3 clear -> seconds/tenths clock
    _, c = run("SpectrumMSX_Hockey", v2e(36, {**HOCKEY, 12: 53}))
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "0", "1", "5", "3")


def test_msx_hockey_framing():
    pr = sp.PROTOCOLS["SpectrumMSX_Hockey"]()
    fr = v2e(44, HOCKEY)
    pr.feed(fr[:30])
    pr.feed(fr[30:])
    assert pr.packets == 1
    pr.feed(v2e(40, HOCKEY))
    assert pr.bad == 1
