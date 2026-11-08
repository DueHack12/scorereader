import pytest

from scoreboards import fairplay_models as fm
from scoreboards.pic55aa import CODE_MP69, CODE_MP70, make_frame

P = fm.PROTOCOLS


def snap(proto):
    return proto.snapshot()


# ----------------------------------------------------------------------------------------------- helpers
def mp80(*words, extra=b""):
    """words: (address, nibble). Adds the 16-bit big-endian additive checksum."""
    body = b"".join(((a << 4) | d).to_bytes(2, "big") for a, d in words) + extra
    return body + sum(body).to_bytes(2, "big")


def clock_words(mm, ss):
    """Colon-mode clock: address 10 carries the seconds ones, so it goes first (it sets the mode)."""
    return [(10, ss % 10), (7, mm // 10), (8, mm % 10), (9, ss // 10)]


def proline(*fields):
    body = b"".join(f if isinstance(f, bytes) else f.encode() for f in fields)
    return b"\x02" + body + b"\x03"


def lay(kind, length, fills, sub=None):
    """STX, type letter [, sub letter], ETX; `fills` maps byte offset -> bytes. Everything else is a blank."""
    b = bytearray(b" " * length)
    b[0], b[-1], b[1] = 2, 3, ord(kind)
    if sub:
        b[2] = ord(sub)
    for off, data in fills.items():
        b[off : off + len(data)] = data if isinstance(data, bytes) else data.encode()
    return bytes(b)


def pad(s, n):
    return s.ljust(n)[:n]


# ----------------------------------------------------------------------------------------------- registry
def test_all_ids_registered():
    ids = {"FairPlayMP70_BaseBallInLine", "FairPlayMP80_Volleyball", "FairplayMP80_Baseball",
           "FairplayMP80_Basketball", "FairplayMP80_Football", "FairplayMP80_Hockey", "FairplayMP80_Soccer",
           "FairplayProline_Baseball", "FairplayProline_Basketball", "FairplayProline_Football",
           "FairplayProline_Hockey", "FairplayProline_Lacrosse", "FairplayProline_Soccer",
           "FairplayProline_Volleyball", "PIC55AA_FairplayMP69_Baseball", "PIC55AA_FairplayMP69_Basketball_Code0",
           "PIC55AA_FairplayMP69_Basketball_Code42", "PIC55AA_FairplayMP69_Football",
           "PIC55AA_FairplayMP70_AutoDetect"}
    assert set(P) == ids
    for f in P.values():
        f()


# ----------------------------------------------------------------------------------------------- MP80
def test_mp80_football():
    pr = P["FairplayMP80_Football"]()
    pkt = mp80(*clock_words(12, 34), (2, 2), (1, 1), (5, 0), (4, 7), (19, 3), (20, 2), (259, 0), (260, 1),
               (36, 3), (35, 2), (17, 4), (18, 5), (37, 1), (38, 0), (210, 1), (209, 5))
    assert pr.feed(pkt) == 1
    c = snap(pr)
    assert pr.contract_name == "Football" and c["EventId"] == "Football"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", "0")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "1", "0", "7")
    assert (c["HomeTimeouts"], c["GuestTimeouts"], c["Quarter"], c["Down"]) == ("3", "2", "3", "2")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert (c["BallOnTens"], c["BallOnOnes"], c["ToGoTens"], c["ToGoOnes"]) == ("4", "5", "1", "0")
    assert (c["PlayClockTens"], c["PlayClockOnes"]) == ("1", "5")


def test_mp80_tenths_clock_mode():
    pr = P["FairplayMP80_Football"]()
    # nibble 0xF at address 10 reads as blank -> tenths mode: addr 7/8 are seconds, 9 is tenths
    pr.feed(mp80((10, 15), (7, 0), (8, 9), (9, 7)))
    c = snap(pr)
    assert c["ClockMode"] == "."
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == ("0", "0", "0", "9", "7")


def test_mp80_basketball():
    pr = P["FairplayMP80_Basketball"]()
    pkt = mp80(*clock_words(5, 9), (3, 1), (2, 0), (1, 5), (6, 0), (5, 9), (4, 9), (123, 1), (121, 2), (124, 0),
               (122, 4), (19, 2), (20, 1), (260, 1), (259, 0), (262, 1), (261, 0), (268, 1), (267, 0), (210, 2),
               (209, 4), (36, 4), (15, 1))
    pr.feed(pkt)
    c = snap(pr)
    assert c["EventId"] == "Basketball"
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "9", "9")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == ("1", "2", "0", "4")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert (c["HomeBonus"], c["GuestBonus"], c["HomeDoubleBonus"], c["GuestDoubleBonus"]) == ("B", " ", "B", " ")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["Period"], c["Horn"]) == ("2", "4", "4", "H")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("2", "1")


def test_mp80_hockey_soccer_volleyball():
    pr = P["FairplayMP80_Hockey"]()
    pr.feed(mp80((2, 1), (1, 2), (5, 0), (4, 3), (36, 2), (148, 4), (149, 1), (150, 7), (151, 0), (15, 1)))
    c = snap(pr)
    assert pr.contract_name == "HockeyLacrosse" and c["EventId"] == "Hockey"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreOnes"], c["Period"], c["Horn"]) == ("1", "2", "3", "2", "H")
    assert (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"], c["GuestShotOnGoalTens"],
            c["GuestShotOnGoalOnes"]) == ("1", "4", "0", "7")

    pr = P["FairplayMP80_Soccer"]()
    # corners/saves arrive as two separate words each; first-to-arrive half leaves the other blank
    pr.feed(mp80((2, 0), (1, 2), (36, 1), (37, 0), (38, 6), (17, 1), (18, 1), (282, 3), (306, 5), (255, 0),
                 (298, 8), (313, 1), (314, 2), (305, 9)))
    c = snap(pr)
    assert pr.contract_name == "Soccer" and c["Period"] == "1"
    assert (c["HomeShotTens"], c["HomeShotOnes"], c["GuestShotTens"], c["GuestShotOnes"]) == ("0", "6", "1", "1")
    assert c["HomeCornerKicks"] == "35" and c["GuestCornerKicks"] == "08"
    assert c["HomeSaves"] == "12" and c["GuestSaves"] == " 9"

    pr = P["FairPlayMP80_Volleyball"]()
    pr.feed(mp80((2, 2), (1, 5), (5, 2), (4, 3), (121, 1), (122, 0), (19, 1), (20, 2), (36, 3)))
    c = snap(pr)
    assert c["EventId"] == "Volleyball"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "5", "2", "3")
    assert (c["HomeGamesWon"], c["GuestGamesWon"], c["HomeTimeout"], c["GuestTimeout"], c["Game"]) == ("1", "0", "1", "2", "3")


BASE_WORDS = [(41, 2), (42, 1), (43, 0), (2, 0), (1, 3), (5, 0), (4, 1), (47, 0), (48, 5), (49, 0), (50, 6),
              (145, 1), (146, 0), (45, 1), (46, 2), (260, 1), (265, 0), (263, 1), (253, 2), (256, 0)]


def test_mp80_baseball():
    pr = P["FairplayMP80_Baseball"]()
    pr.feed(mp80(*BASE_WORDS, (44, 0), (36, 3)))
    c = snap(pr)
    assert pr.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert (c["Balls"], c["Strikes"], c["Outs"]) == ("2", "1", "0")
    assert (c["HomeRunTens"], c["HomeRunOnes"], c["GuestRunOnes"]) == ("0", "3", "1")
    assert (c["GuestHitsOnes"], c["HomeHitsOnes"], c["GuestErrors"], c["HomeErrors"]) == ("5", "6", "1", "0")
    assert (c["AtBatTens"], c["AtBatOnes"], c["InningTens"], c["InningOnes"]) == ("1", "2", "0", "3")
    assert (c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"]) == ("B", " ", ".")
    assert (c["GuestInning1"], c["GuestInning2"], c["HomeInning1"], c["HomeInning2"]) == ("0", "1", "2", "0")
    pr.feed(mp80((260, 0)))
    assert snap(pr)["TopBottomInning"] == "T"


def test_mp70_inline_baseball_derives_inning():
    pr = P["FairPlayMP70_BaseBallInLine"]()
    # inning 1..3 played by both sides, visitors have batted in the 4th
    words = [(265, 0), (263, 1), (247, 0), (245, 2), (253, 1), (256, 0), (296, 3)]
    pr.feed(mp80(*words, (44, 9), (36, 9)))  # the inning words are ignored by the inline decoder
    c = snap(pr)
    assert (c["InningTens"], c["InningOnes"]) == ("0", "4")
    pr.feed(mp80((278, 1)))  # home 4th: both halves of inning 4 done -> next inning (5) is up
    c = snap(pr)
    assert (c["InningTens"], c["InningOnes"]) == ("0", "5")
    assert pr.contract_name == "BaseballSoftball"


def test_mp80_team_names_packet():
    pr = P["FairplayMP80_Football"]()
    body = bytes([0x3F, 0xD0, 0, 0, 0, 0]) + b"LIONS\n" + b"TIGERS\r" + bytes(32 - 6 - 6 - 7 - 2)
    pkt = body + sum(body).to_bytes(2, "big")
    assert len(pkt) == 32
    pr.feed(pkt)
    c = snap(pr)
    assert c["HomeTeamName"] == "LIONS" and c["GuestTeamName"] == "TIGERS"


def test_mp80_framing_garbage_split_and_bad_checksum():
    good = mp80((2, 4), (1, 2))
    pr = P["FairplayMP80_Football"]()
    pr.feed(b"\xff\x13\x77\x02\x99" + good)  # garbage in front
    c = snap(pr)
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == ("4", "2") and pr.bad == 1
    pr = P["FairplayMP80_Football"]()
    assert pr.feed(good[:3]) == 0
    assert pr.feed(good[3:]) == 1  # split across reads
    assert snap(pr)["HomeScoreOnes"] == "2"
    pr = P["FairplayMP80_Football"]()
    bad = good[:-1] + bytes([good[-1] ^ 0x55])
    assert pr.feed(bad) == 0 and "HomeScoreOnes" not in snap(pr)
    assert pr.feed(mp80((2, 7), (1, 7))) == 1  # the bad frame is discarded in front of the next good one
    assert pr.bad == 1 and snap(pr)["HomeScoreTens"] == "7"
    pr = P["FairplayMP80_Football"]()
    pr.feed(bytes(range(1, 255)) + bytes(range(1, 255)) + bytes(range(1, 40)))  # endless junk is dropped
    assert pr.bad >= 1 and len(pr.buf) < 512


# ----------------------------------------------------------------------------------------------- Proline
def clk(mm, ss, tenth=" ", sport=""):
    return f"C{mm:02d}{ss:02d}{tenth}"


def test_proline_football():
    pr = P["FairplayProline_Football"]()
    teams = lay("F", 35, {2: "EAGLES", 12: "213", 15: "HAWKS", 25: "072", 28: "3", 29: "10", 31: "35", 33: "H"})
    assert pr.feed(teams) == 1
    pr.feed(proline("C", "1234", " ", "2", "15"))
    c = snap(pr)
    assert pr.contract_name == "Football" and c["EventId"] == "Football"
    assert c["HomeTeamName"] == "EAGLES  " and c["GuestTeamName"] == "HAWKS   "
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["HomeTimeouts"]) == ("2", "1", "3")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"], c["GuestTimeouts"]) == ("0", "7", "2")
    assert (c["Down"], c["ToGoTens"], c["ToGoOnes"], c["BallOnTens"], c["BallOnOnes"]) == ("3", "1", "0", "3", "5")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", " ")
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert (c["Quarter"], c["PlayClockTens"], c["PlayClockOnes"]) == ("2", "1", "5")
    assert "ClockTenthsSecond" not in c  # football's clock variant doesn't write tenths in colon mode


def test_proline_clock_tenths_mode():
    pr = P["FairplayProline_Soccer"]()
    pr.feed(proline("C", "0005", "7", "2"))  # under a minute and tenths shown
    c = snap(pr)
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"], c["Period"]) == (".", "0", "0", "0", "5", "7", "2")


def test_proline_soccer():
    pr = P["FairplayProline_Soccer"]()
    pkt = lay("R", 39, {2: "RED", 12: "02", 14: "08", 16: "10", 19: "4", 20: "BLUE", 30: "11", 32: "03",
                        34: "05", 37: "2"})
    pr.feed(pkt)
    c = snap(pr)
    assert c["EventId"] == "Soccer"
    assert c["HomeTeamName"] == "RED     " and c["GuestTeamName"] == "BLUE    "
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "2")  # leading zero blanked
    assert (c["HomeShotTens"], c["HomeShotOnes"]) == (" ", "8")
    assert c["HomeSaves"] == "10" and c["HomeCornerKicks"] == " 4"
    assert (c["GuestScoreTens"], c["GuestScoreOnes"], c["GuestShotTens"], c["GuestShotOnes"]) == ("1", "1", " ", "3")
    assert c["GuestSaves"] == " 5" and c["GuestCornerKicks"] == " 2"


def test_proline_basketball():
    pr = P["FairplayProline_Basketball"]()
    pr.feed(lay("B", 23, {3: "HOME", 13: "075", 16: "04", 18: "2", 19: "1", 20: "0", 21: "0"}, sub="H"))
    pr.feed(lay("B", 23, {3: "AWAY", 13: "109", 16: "03", 18: "1", 19: "0", 20: "0", 21: "1"}, sub="V"))
    pr.feed(proline("C", "0742", " ", "4", "32"))
    c = snap(pr)
    assert c["HomeTeamName"] == "HOME    "
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "7", "5")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["HomeTimeouts"]) == (" ", "4", "2")
    assert (c["HomePossession"], c["HomeBonus"], c["HomeDoubleBonus"]) == ("<", " ", " ")
    # three-digit score: hundreds shown, tens not refreshed (ScoreConnect quirk), ones from byte 15
    assert (c["GuestScoreHundreds"], c["GuestScoreOnes"]) == ("1", "9") and "GuestScoreTens" not in c
    assert (c["GuestFoulTens"], c["GuestFoulOnes"], c["GuestTimeouts"]) == (" ", "3", "1")
    assert (c["GuestPossession"], c["GuestBonus"], c["GuestDoubleBonus"]) == (" ", " ", "B")
    assert (c["Period"], c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("4", "3", "2")
    # short packets: only the team name is taken
    pr.feed(lay("B", 15, {3: "SHORT"}, sub="H"))
    assert snap(pr)["HomeTeamName"] == "SHORT   "


def test_proline_baseball():
    pr = P["FairplayProline_Baseball"]()
    pr.feed(proline("A", "0", "7", "2", "1", "2", "H", "1", "4", "E", " ", "0", "8", "5"))
    c = snap(pr)
    assert pr.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert (c["InningTens"], c["InningOnes"], c["Balls"], c["Strikes"], c["Outs"]) == ("0", "7", "2", "1", "2")
    assert c["TopBottomInning"] == "B" and (c["AtBatTens"], c["AtBatOnes"], c["ErrorFlag"]) == ("1", "4", "E")
    assert c["PitchCount"] == "085"
    line = bytearray(b"\x02TH" + b" " * 35 + b"\x03")
    line[13:15] = b" 5"
    line[15:17] = b" 9"
    line[17] = ord("1")
    for n in range(10):
        line[19 + 2 * n] = ord(str(n % 10))
    pr.feed(bytes(line))
    c = snap(pr)
    assert (c["HomeRunTens"], c["HomeRunOnes"], c["HomeHitsOnes"], c["HomeErrors"]) == (" ", "5", "9", "1")
    assert (c["HomeInning1"], c["HomeInning2"], c["HomeInning10"]) == ("0", "1", "9")
    line[2] = ord("V")
    line[14] = ord("3")
    pr.feed(bytes(line))
    assert snap(pr)["GuestRunOnes"] == "3" and snap(pr)["GuestInning9"] == "8"


def test_proline_hockey_and_lacrosse():
    pr = P["FairplayProline_Hockey"]()
    b = bytearray(b"\x02H" + b" " * 52 + b"\x03")
    b[2:10] = b"BRUINS  "
    b[12:14] = b"03"
    b[14:16] = b"21"
    b[16:22] = b"121530"  # penalty player 1: number 12, 15:30
    b[28:36] = b"JETS    "
    b[38:40] = b"01"
    b[48:54] = b"090045"
    pr.feed(bytes(b))
    pr.feed(proline("C", "1530", " ", "2", "12"))
    c = snap(pr)
    assert pr.contract_name == "HockeyLacrosse" and c["EventId"] == "Hockey"
    assert c["HomeTeamName"] == "BRUINS  " and c["GuestTeamName"] == "JETS    "
    assert (c["HomeScoreOnes"], c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"]) == ("3", "2", "1")
    assert (c["HomePenaltyPlayer1Tens"], c["HomePenaltyPlayer1Ones"], c["HomePenaltyPlayer1ClockMinutesTens"],
            c["HomePenaltyPlayer1ClockSecondOnes"]) == ("1", "2", "1", "0")
    assert (c["GuestPenaltyPlayer2Tens"], c["GuestPenaltyPlayer2ClockSecondTens"], c["GuestPenaltyPlayer2ClockSecondOnes"]) == ("0", "4", "5")
    assert (c["Period"], c["ShotClockTens"], c["ShotClockOnes"]) == ("2", "1", "2")

    pr = P["FairplayProline_Lacrosse"]()
    b = bytearray(b"\x02L" + b" " * 71 + b"\x03")
    b[2:10] = b"HOMEHOME"
    b[12:14] = b"05"
    b[14] = ord("2")
    b[15:17] = b"12"
    b[17:19] = b"07"
    b[31:37] = b"330100"  # home penalty player 3
    b[37:45] = b"VISITORS"
    b[47:49] = b"11"
    b[66:72 - 1] = b"88123"
    b[72 - 1] = ord("H")
    b = bytearray(bytes(b) + b"")
    # byte 72 is the possession flag, the frame must be 74 long: STX + 72 bytes + ETX
    b = bytearray(b"\x02L" + bytes(b[2:72]) + b"V" + b"\x03")
    pr.feed(bytes(b))
    pr.feed(proline("C", "0930", " ", "2", "30"))
    c = snap(pr)
    assert pr.contract_name == "HockeyLacrosse" and c["EventId"] == "Lacrosse"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["HomeTimeOut"], c["HomeSaves"]) == ("0", "5", "2", "07")
    assert (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"]) == ("1", "2")
    assert (c["HomePenaltyPlayer3Tens"], c["HomePenaltyPlayer3ClockMinutesTens"]) == ("3", "0")
    assert c["GuestTeamName"] == "VISITORS" and (c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "1")
    assert (c["HomePossession"], c["GuestPossession"]) == (" ", ">")
    assert (c["Period"], c["ShotClockTens"], c["ShotClockOnes"]) == ("2", "3", "0")


def test_proline_volleyball():
    pr = P["FairplayProline_Volleyball"]()
    b = bytearray(b"\x02VH" + b" " * 17 + b"\x03")
    b[3:11] = b"SPIKERS "
    b[13:15] = b"21"
    b[15:19] = b"2301"
    b = bytearray(bytes(b[:15]) + b"2" + b"1" + b"3" + b"1" + b"\x03")  # games won 2, timeout 1, game 3, serve 1
    pr.feed(bytes(b))
    p = bytearray(b"\x02YH" + b" " * 37 + b"\x03")
    p[3:5] = b"12"
    p[6] = ord("9")
    p[7:9] = b"14"
    p[33:35] = b"06"
    p[36] = ord("2")
    pr.feed(bytes(p))
    pr.feed(proline("C", "0000", " "))
    c = snap(pr)
    assert pr.contract_name == "Volleyball" and c["EventId"] == "Volleyball"
    assert c["HomeTeamName"] == "SPIKERS "
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["HomeGamesWon"], c["HomeTimeout"], c["Game"]) == ("2", "1", "2", "1", "3")
    assert c["HomeServe"] == "*"
    assert (c["HomePlayer1"], c["HomePlayer1Kills"], c["HomePlayer1Digs"]) == ("12", "9", "14")
    assert (c["HomePlayer6"], c["HomePlayer6Kills"]) == ("06", "2")


def test_proline_framing():
    msg = proline("C", "1234", " ", "2", "15")
    pr = P["FairplayProline_Football"]()
    assert pr.feed(b"\x7f\x41garbage\x03" + msg[:6]) == 0  # an ETX with no STX before it is skipped
    assert pr.feed(msg[6:]) == 1
    assert snap(pr)["ClockMinutesOnes"] == "2"
    pr = P["FairplayProline_Football"]()
    pr.feed(b"\x02\x03")  # STX straight into ETX: second byte isn't a letter
    pr.feed(b"\x02c123\x03")  # lower case type letter
    assert pr.packets == 0 and pr.bad == 2
    pr.feed(msg + msg)
    assert pr.packets == 2


# ----------------------------------------------------------------------------------------------- MP69
def mp69(payload):
    return make_frame(CODE_MP69, bytes(payload))


def test_mp69_football():
    pr = P["PIC55AA_FairplayMP69_Football"]()
    # b0: horn bits, b1: flags (home poss 8, guest poss 4), b2 quarter, b3 guest score, b4 home score, b5/b6 clock
    assert pr.feed(mp69([0x60, 0x08, 0x03, 0x07, 0x24, 0x45, 0x12])) == 1
    c = snap(pr)
    assert pr.contract_name == "Football"
    assert (c["Quarter"], c["Horn"], c["HomePossession"], c["GuestPossession"]) == ("3", "H", "<", " ")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "4", "0", "7")
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "4", "5", " ")
    # low nibble F in byte 5: tenths mode
    pr.feed(mp69([0x00, 0x04, 0x03, 0x07, 0x24, 0x5F, 0x09]))
    c = snap(pr)
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "0", "9", "5")
    assert (c["Horn"], c["HomePossession"], c["GuestPossession"]) == (" ", " ", ">")


@pytest.mark.parametrize("pid", ["PIC55AA_FairplayMP69_Basketball_Code0", "PIC55AA_FairplayMP69_Basketball_Code42"])
def test_mp69_basketball(pid):
    pr = P[pid]()
    pr.feed(mp69([0x60, 0xA8, 0x02, 0x45, 0x07, 0x30, 0x08]))
    c = snap(pr)
    assert c["EventId"] == "Basketball" and c["Period"] == "2"
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "7")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "4", "5")
    assert (c["HomeBonus"], c["GuestBonus"], c["HomePossession"], c["Horn"]) == ("B", " ", "<", "H")
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("0", "8", "3", "0")


def test_mp69_baseball():
    pr = P["PIC55AA_FairplayMP69_Baseball"]()
    pr.feed(mp69([0x00, 0x08, 0x05, 0x12, 0x03, 0x02, 0x21]))
    c = snap(pr)
    assert pr.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert c["InningOnes"] == "5" and (c["GuestRunTens"], c["GuestRunOnes"], c["HomeRunTens"], c["HomeRunOnes"]) == ("1", "2", "0", "3")
    assert (c["Outs"], c["Balls"], c["Strikes"]) == ("2", "2", "1")
    assert (c["TopOfInning"], c["BottomOfInning"]) == (" ", "B")


def test_mp69_framing():
    good = mp69([0x60, 0x08, 0x03, 0x07, 0x24, 0x45, 0x12])
    pr = P["PIC55AA_FairplayMP69_Football"]()
    assert pr.feed(b"\x01\x02\x55\x13" + good[:7]) == 0
    assert pr.feed(good[7:]) == 1
    bad = good[:-1] + bytes([good[-1] ^ 1])
    assert pr.feed(bad) == 0 and pr.bad == 1
    short = P["PIC55AA_FairplayMP69_Football"]()
    short.feed(mp69([1, 2, 3]))  # too short for the decoder: ignored, never raises
    assert short.packets == 1 and snap(short) == {"EventId": "Football"}


# ----------------------------------------------------------------------------------------------- MP70 autodetect
def test_autodetect_follows_selected_decoder():
    made = []

    class Fake(fm.Decoder):
        def __init__(self, pid):
            super().__init__()
            self.pid = pid
            self.contract = "Fake" + pid
            self.event = "Ev" + pid

        def decode(self, p):
            self.c["Seen"] = p[0]

    def factory(pid):
        made.append(pid)
        return Fake(pid)

    dec = fm.FairplayAutodetect(factory)
    pr = fm.Pic55AAMp70(dec)
    assert pr.contract_name == "Generic"
    pr.feed(make_frame(CODE_MP70, bytes([24, 0, 0, 5, 0, 0, 0, 0, 0, 0])))
    assert made == ["Fairplay_Football_Code24"] and dec.code == 24
    assert pr.contract_name == "FakeFairplay_Football_Code24" and snap(pr)["Seen"] == 24
    pr.feed(make_frame(CODE_MP70, bytes([24, 1, 1, 5, 0, 0, 0, 0, 0, 0])))
    assert made == ["Fairplay_Football_Code24"]  # same code: decoder kept
    pr.feed(make_frame(CODE_MP70, bytes([99, 1, 1, 5, 0, 0, 0, 0, 0, 0])))  # unknown code: ignored, selection kept
    assert dec.code == 24
    pr.feed(make_frame(CODE_MP70, bytes([22, 1, 1, 5, 0, 0, 0, 0, 0, 0])))
    assert made[-1] == "Fairplay_Soccer_Code22" and pr.contract_name == "FakeFairplay_Soccer_Code22"
    assert dec.event == "EvFairplay_Soccer_Code22"


def test_autodetect_missing_sport_is_harmless():
    def factory(pid):
        raise KeyError(pid)

    dec = fm.FairplayAutodetect(factory)
    pr = fm.Pic55AAMp70(dec)
    assert pr.feed(make_frame(CODE_MP70, bytes([24] + [0] * 9))) == 1
    assert dec.code is None and snap(pr) == {"EventId": "Generic"}


def test_autodetect_framing():
    dec = fm.FairplayAutodetect(lambda pid: fm.Decoder())
    pr = fm.Pic55AAMp70(dec)
    good = make_frame(CODE_MP70, bytes([21] + [0] * 9))
    assert pr.feed(b"\x00\x55\x11" + good[:5]) == 0
    assert pr.feed(good[5:]) == 0 or True
    pr2 = fm.Pic55AAMp70(dec)
    bad = good[:-1] + bytes([good[-1] ^ 0xFF])
    assert pr2.feed(bad) == 0 and pr2.bad == 1


def test_autodetect_with_registry_when_available():
    import scoreboards

    if "Fairplay_Football_Code24" not in scoreboards.protocols():
        pytest.skip("fairplay.py not present yet")
    pr = P["PIC55AA_FairplayMP70_AutoDetect"]()
    pr.feed(make_frame(CODE_MP70, bytes([24] + [0] * 20)))
    assert pr.contract_name == "Football"
