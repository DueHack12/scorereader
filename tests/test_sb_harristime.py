from scoreboards import harristime as ht


def enc(ch, k=0):
    """Harris digit with flag offset k (0 = plain ASCII)."""
    return ord(ch) if k == 0 else ord(ch) + 12 + 11 * (k - 1)


def main_frame(**over):
    p = bytearray(b"0" * 74)
    p[0] = 0x3A
    p[1:5] = b"4321"
    p[73] = 0x0A
    for i, v in over.items():
        p[int(i[1:])] = v
    return bytes(p)


def test_encoding_table():
    h = ht._harris_ascii
    assert h(ord("5")) == "5" and h(65) == "5" and h(106) == "2" and h(126 + 3) == "3" and h(59) == " "
    assert h(200) == " " and h(70) == " "


def basketball_frame():
    return main_frame(p9=ord("2"), p10=enc("5", 1), p11=ord("1"), p12=enc("2", 5), p13=ord("3"), p14=ord("4"),
                      p15=enc("3", 2), p16=ord("0"), p17=ord("2"), p18=ord("1"), p19=ord("4"), p20=ord("2"),
                      p21=ord("3"), p22=ord("7"), p23=ord("1"), p24=ord("2"), p25=ord("2"), p26=ord("4"),
                      p58=ord("1"))


def test_basketball():
    p = ht.PROTOCOLS["HarrisTime_Basketball"]()
    assert p.feed(basketball_frame()) == 1
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "5", "3", "0")
    assert c["HomeBonus"] == "B" and c["HomeDoubleBonus"] == " " and c["GuestBonus"] == " "
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert (c["Period"], c["HomeFoulOnes"], c["GuestFoulOnes"], c["HomeTimeouts"], c["GuestTimeouts"]) == tuple("21423")
    assert (c["FoulPlayerOnes"], c["FoulPlayerTens"], c["FoulPlayerNumberOfFouls"]) == ("7", "1", "2")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["Horn"]) == ("2", "4", "H")
    assert c["GuestScoreHundreds"] == "1" and c["HomeScoreHundreds"] == " "  # offset-coded digit = 100s
    assert p.contract_name == "Basketball"


def test_basketball_seconds_mode_and_guest_possession():
    p = ht.PROTOCOLS["HarrisTime_Basketball"]()
    p.feed(main_frame(p11=ord("5"), p12=enc("9", 1), p13=ord("7"), p14=ord(" "), p58=ord("0")))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "5", "9", "7")
    assert c["GuestPossession"] == ">" and c["HomePossession"] == " " and c["Horn"] == " "


def test_main_garbage_split_and_length_reject():
    p = ht.PROTOCOLS["HarrisTime_Basketball"]()
    f = basketball_frame()
    p.feed(b"\r\n\x00junk\n")  # LF with no ':' before it is dropped
    assert p.feed(b"zz" + f[:40]) == 0
    assert p.feed(f[40:]) == 1
    assert p.feed(b":4321short\n") == 0 and p.bad == 1
    assert p.packets == 1


def test_main_wrong_header_is_ignored():
    p = ht.PROTOCOLS["HarrisTime_Hockey"]()
    p.feed(main_frame() .replace(b"4321", b"1111", 1))
    assert "HomeScoreOnes" not in p.snapshot()


def test_hockey_main():
    p = ht.PROTOCOLS["HarrisTime_Hockey"]()
    vals = {"p9": "0", "p10": "3", "p11": "1", "p12": "5", "p13": "4", "p14": "2", "p15": "0", "p16": "1",
            "p17": "2", "p18": "1", "p19": "2", "p20": "0", "p21": "9", "p22": "1", "p23": "7", "p24": "2",
            "p25": "3", "p26": "0", "p27": "4", "p28": "4", "p29": "1", "p30": "5", "p31": "9", "p32": "2",
            "p33": "2", "p34": "1", "p35": "0", "p36": "8", "p37": "3", "p38": "3", "p39": "2", "p40": "4",
            "p41": "5"}
    assert p.feed(main_frame(**{k: ord(v) for k, v in vals.items()})) == 1
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("1542")
    assert (c["HomeScoreOnes"], c["GuestScoreOnes"], c["Period"]) == ("3", "1", "2")
    assert (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"], c["GuestShotOnGoalTens"],
            c["GuestShotOnGoalOnes"]) == ("1", "2", "0", "9")
    assert (c["HomePenaltyPlayer1Tens"], c["HomePenaltyPlayer1Ones"], c["HomePenaltyPlayer1ClockMinutesOnes"],
            c["HomePenaltyPlayer1ClockSecondTens"], c["HomePenaltyPlayer1ClockSecondOnes"]) == tuple("17230")
    assert (c["HomePenaltyPlayer2Tens"], c["HomePenaltyPlayer2Ones"]) == ("4", "4")
    assert (c["GuestPenaltyPlayer1Tens"], c["GuestPenaltyPlayer1ClockSecondOnes"]) == ("2", "8")
    assert (c["GuestPenaltyPlayer2Tens"], c["GuestPenaltyPlayer2ClockSecondOnes"]) == ("3", "5")
    assert p.contract_name == "HockeyLacrosse" and p.decoder.event == "Hockey"


def v2_frame(**over):
    p = bytearray(b"0" * 62)
    p[0:2] = b"@@"
    p[60:62] = b"##"
    for i, v in over.items():
        p[int(i[1:])] = ord(v)
    return bytes(p)


def test_v2_hockey():
    p = ht.PROTOCOLS["HarrisTimeV2_Hockey"]()
    f = v2_frame(p15="7", p16="3", p17="5", p18="1", p20="4", p21="1", p23="2", p24="0", p26="3", p28="6",
                 p29="1", p31="8", p32="0", p34="9", p35="5", p36="1", p37="3", p38="2", p52="4", p53="3",
                 p54="2", p55="6", p56="1")
    assert p.feed(f) == 1
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("1537")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == tuple("1402")
    assert c["Period"] == "3" and (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"]) == ("1", "6")
    assert (c["GuestShotOnGoalTens"], c["GuestShotOnGoalOnes"]) == ("0", "8")
    assert (c["HomePenaltyPlayer1ClockSecondOnes"], c["HomePenaltyPlayer1ClockSecondTens"],
            c["HomePenaltyPlayer1ClockMinutesOnes"], c["HomePenaltyPlayer1Ones"],
            c["HomePenaltyPlayer1Tens"]) == tuple("95132")
    assert (c["GuestPenaltyPlayer2ClockSecondOnes"], c["GuestPenaltyPlayer2Tens"]) == ("4", "1")
    assert (c["GuestPenaltyPlayer2Ones"], c["GuestPenaltyPlayer2ClockMinutesOnes"]) == ("6", "2")


def test_v2_garbage_split_and_length_reject():
    p = ht.PROTOCOLS["HarrisTimeV2_Hockey"]()
    f = v2_frame(p15="1")
    p.feed(b"##")  # "##" with no "@@" before it
    assert p.feed(b"xx" + f[:25]) == 0
    assert p.feed(f[25:]) == 1
    assert p.feed(b"@@" + b"0" * 10 + b"##") == 0 and p.bad == 1
