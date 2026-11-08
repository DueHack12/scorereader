"""OES scoreboards: synthetic packets in the real STX..checksum CR wire format."""
import pytest

from scoreboards import create, oes
from scoreboards.oes import AUTODETECT, make_packet, oes_checksum

TXT = {"t": 116, "s": 115}


def pkt(length, kind="t", fields=None):
    """Packet of total ``length`` (STX..CR). ``fields`` maps index -> str / int / bytes."""
    body = bytearray(b" " * (length - 2))
    body[0] = 2
    body[1] = TXT[kind]
    for idx, v in (fields or {}).items():
        if isinstance(v, str):
            for k, ch in enumerate(v):
                body[idx + k] = ord(ch)
        elif isinstance(v, int):
            body[idx] = v
        else:
            body[idx : idx + len(v)] = v
    return make_packet(bytes(body))


def run(pid, data):
    p = create(pid)
    p.feed(data)
    return p


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


# ------------------------------------------------------------------ framing
def test_checksum_rules():
    body = b"\x02t" + b"A" * 6
    assert oes_checksum(body) == sum(body) % 128
    assert oes_checksum(b"\x02") == 34  # below 0x20 -> +32
    assert make_packet(body)[-2:] == bytes([oes_checksum(body), 13])


def test_garbage_before_frame_and_split_feed():
    p = create("OES_Football")
    data = pkt(25, "t", {6: "2", 7: "21", 9: "14"})
    p.feed(b"\x99\x01garbage\r\x55" + data[:10])
    assert p.packets == 0
    p.feed(data[10:])
    assert p.packets == 1
    check(p.snapshot(), Quarter="2", HomeScoreTens="2", HomeScoreOnes="1", GuestScoreTens="1", GuestScoreOnes="4")
    # two frames in one feed
    p.feed(data + data)
    assert p.packets == 3


def test_bad_checksum_rejected_then_recovers():
    p = create("OES_Football")
    good = pkt(25, "t", {7: "07"})
    bad = bytearray(good)
    bad[-2] ^= 0x01
    p.feed(bytes(bad) + good)
    assert p.packets == 1
    assert p.bad == 1
    check(p.snapshot(), HomeScoreTens="0", HomeScoreOnes="7")


def test_cr_without_stx_is_dropped_silently():
    p = create("OES_Football")
    p.feed(b"abc\r" + pkt(25, "t", {8: "5"}))
    assert p.packets == 1 and p.bad == 0


# ------------------------------------------------------------------ football
def test_football():
    d = pkt(25, "t", {2: "12", 4: "34", 6: "3", 7: "07", 9: "21", 11: "2", 12: "1", 13: 184, 14: 0x20,
                      15: "2", 16: " 8", 18: "35", 20: "25"})
    c = run("OES_Football", d).snapshot()
    check(c, ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3", ClockSecondOnes="4",
          ClockMode=":", ClockTenthsSecond="0", Quarter="3", HomeScoreTens="0", HomeScoreOnes="7",
          GuestScoreTens="2", GuestScoreOnes="1", HomeTimeouts="2", GuestTimeouts="1", HomePossession="<",
          GuestPossession=" ", Down="2", ToGoTens=" ", ToGoOnes="8", BallOnTens="3", BallOnOnes="5",
          PlayClockTens="2", PlayClockOnes="5", EventId="Football")
    assert create("OES_Football").contract_name == "Football"


def test_clock_under_a_minute_and_colon_blank():
    # byte 5 blank: SS.t in bytes 2-4; bit 7 on a byte is ignored
    d = pkt(25, "t", {2: "4", 3: "5", 4: bytes([ord("7") | 0x80])})
    c = run("OES_Football", d).snapshot()
    check(c, ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens="4", ClockSecondOnes="5",
          ClockTenthsSecond="7", ClockMode=".")


def test_football_wireless():
    d = pkt(21, "t", {2: "0900", 7: "14", 11: "07", 15: "4", 17: "10"})
    c = run("OES_FootballWireless", d).snapshot()
    check(c, ClockMinutesTens="0", ClockMinutesOnes="9", ClockSecondTens="0", ClockSecondOnes="0",
          HomeScoreTens="1", HomeScoreOnes="4", GuestScoreTens="0", GuestScoreOnes="7", Quarter="4",
          ToGoTens="1", ToGoOnes="0")


# ------------------------------------------------------------------ basketball
def basketball_game(**over):
    f = {2: "0512", 6: "2", 7: "21", 9: "18", 11: "3", 12: "2", 13: "4", 14: "2", 16: 0x80 | 1 | 2 | 8,
         17: 0x80 | 4, 18: "24"}
    f.update(over)
    return pkt(23, "t", f)


def test_basketball():
    c = run("OES_Basketball", basketball_game()).snapshot()
    check(c, ClockMinutesTens="0", ClockMinutesOnes="5", ClockSecondTens="1", ClockSecondOnes="2",
          InternalClockStatus="R", Period="2", HomeScoreHundreds=" ", HomeScoreTens="2", HomeScoreOnes="1",
          GuestScoreTens="1", GuestScoreOnes="8", HomeTimeouts="3", GuestTimeouts="2", HomeFullTimeouts="3",
          HomeFoulOnes="4", GuestFoulOnes="2", HomeFoulTens=" ", HomePossession="<", GuestPossession=" ",
          HomeBonus="B", HomeDoubleBonus=" ", GuestBonus=" ", GuestDoubleBonus="B", HomePartialTimeouts="2",
          GuestPartialTimeouts="1", ShotClockSecondTens="2", ShotClockSecondOnes="4")


def test_basketball_high_bits_and_clock_stopped():
    f = {2: bytes([ord("0") | 0x80]), 7: bytes([ord("0") | 0x80]), 9: bytes([ord("5") | 0x80]),
         13: bytes([ord("1") | 0x80]), 18: bytes([ord("9") | 0x80]), 19: "x"}
    d = pkt(23, "t", {**f, 3: "0", 4: "30", 5: "0", 8: "5", 10: "0"})
    c = run("OES_Basketball", d).snapshot()
    check(c, InternalClockStatus="S", HomeScoreHundreds="1", HomeScoreTens="0", HomeScoreOnes="5",
          GuestScoreHundreds="1", HomeFoulTens="1", HomeFoulOnes="1", ShotClockSecondTens=" ",
          ShotClockSecondOnes="9")


def test_basketball_shot_clock_unused_keeps_previous():
    p = create("OES_Basketball")
    p.feed(basketball_game())
    p.feed(pkt(23, "t", {18: bytes([0xB0, 0xB0])}))
    check(p.snapshot(), ShotClockSecondTens="2", ShotClockSecondOnes="4")


def test_basketball_tissot_has_no_clock_status():
    c = run("OES_Basketball_Tissot_Adapter", basketball_game()).snapshot()
    assert "InternalClockStatus" not in c
    check(c, HomeScoreTens="2", Period="2")


def test_basketball_player_packets():
    p = create("OES_Basketball")
    p.feed(pkt(23, "s", {2: "H", 3: "2", 4: "23", 6: "3", 7: "14"}))
    p.feed(pkt(23, "s", {2: "G", 3: "5", 4: "07", 6: "1", 7: " 9"}))
    p.feed(pkt(23, "s", {2: "X", 3: "5", 4: "99"}))
    check(p.snapshot(), HomePlayer2="23", HomePlayer2FoulNumber="3", HomePlayer2Points="14",
          GuestPlayer5="07", GuestPlayer5FoulNumber="1", GuestPlayer5Points=" 9")
    assert "HomePlayer5" not in p.snapshot()


# ------------------------------------------------------------------ hockey / lacrosse
def hockey_common(shots):
    return {2: "1500", 6: "2", 7: "03", 9: "02", shots: "0710"}


def test_hockey_standard():
    f = hockey_common(11)
    f.update({19: "12", 21: "1", 22: "45", 24: "07", 26: "2", 27: "30", 29: "88", 31: "0", 32: "59", 34: "17",
              36: "1", 37: "02"})
    c = run("OES_HockeyStandard", pkt(44, "t", f)).snapshot()
    check(c, ClockMinutesTens="1", ClockMinutesOnes="5", Period="2", HomeScoreOnes="3", GuestScoreOnes="2",
          HomeShotOnGoalTens="0", HomeShotOnGoalOnes="7", GuestShotOnGoalTens="1", GuestShotOnGoalOnes="0",
          HomePenaltyPlayer1Tens="1", HomePenaltyPlayer1Ones="2", HomePenaltyPlayer1ClockMinutesTens=" ",
          HomePenaltyPlayer1ClockMinutesOnes="1", HomePenaltyPlayer1ClockSecondTens="4",
          HomePenaltyPlayer1ClockSecondOnes="5", HomePenaltyPlayer2Tens="0", HomePenaltyPlayer2Ones="7",
          HomePenaltyPlayer2ClockMinutesOnes="2", HomePenaltyPlayer2ClockSecondTens="3",
          GuestPenaltyPlayer1Tens="8", GuestPenaltyPlayer1ClockSecondOnes="9",
          GuestPenaltyPlayer2Ones="7", GuestPenaltyPlayer2ClockMinutesOnes="1",
          GuestPenaltyPlayer2ClockSecondOnes="2", HomePenaltyPlayer3Tens=" ", HomeGoal=" ", Horn=" ")
    assert c["EventId"] == "Hockey"


def test_hockey_requires_t_packet():
    c = run("OES_HockeyStandard", pkt(44, "s", hockey_common(11))).snapshot()
    assert "HomeScoreOnes" not in c


def test_hockey_pro_offsets():
    f = hockey_common(18)
    f.update({22: "11", 24: "2", 25: "00", 32: "22", 34: "1", 35: "59", 37: "33", 39: "4", 40: "01"})
    c = run("OES_HockeyPro", pkt(45, "t", f)).snapshot()
    check(c, HomeShotOnGoalOnes="7", GuestShotOnGoalTens="1", HomePenaltyPlayer1Ones="1",
          HomePenaltyPlayer1ClockMinutesOnes="2", GuestPenaltyPlayer1Tens="2", GuestPenaltyPlayer1ClockSecondTens="5",
          GuestPenaltyPlayer2Tens="3", GuestPenaltyPlayer2ClockMinutesOnes="4", GuestPenaltyPlayer2ClockSecondOnes="1")


def test_hockey_isc85x_offsets():
    f = hockey_common(11)
    f.update({17: "77", 19: "2", 20: "15", 27: "88", 29: "1", 30: "30", 32: "99", 34: "0", 35: "45"})
    c = run("OES_Hockey_ISC85X", pkt(39, "t", f)).snapshot()
    check(c, HomePenaltyPlayer1Tens="7", HomePenaltyPlayer1ClockMinutesOnes="2", HomePenaltyPlayer1ClockSecondOnes="5",
          GuestPenaltyPlayer1Tens="8", GuestPenaltyPlayer1ClockSecondTens="3", GuestPenaltyPlayer2Tens="9",
          GuestPenaltyPlayer2ClockSecondTens="4", GuestPenaltyPlayer2ClockSecondOnes="5")


def test_short_hockey():
    f = hockey_common(11)
    f.update({19: "215", 22: "030", 25: "145", 28: "000"})
    # no byte-1 check on the short layout
    c = run("OES_ShortHockeyStandard", pkt(36, "s", f)).snapshot()
    check(c, HomeScoreOnes="3", HomePenaltyPlayer1Tens=" ", HomePenaltyPlayer1ClockMinutesOnes="2",
          HomePenaltyPlayer1ClockSecondTens="1", HomePenaltyPlayer1ClockSecondOnes="5",
          HomePenaltyPlayer2ClockMinutesOnes="0", HomePenaltyPlayer2ClockSecondTens="3",
          GuestPenaltyPlayer1ClockMinutesOnes="1", GuestPenaltyPlayer1ClockSecondOnes="5",
          GuestPenaltyPlayer2ClockSecondOnes="0")


def test_lacrosse():
    f = hockey_common(18)
    f.update({22: "12", 24: "1", 25: "30", 27: "13", 29: "0", 30: "45", 32: "21", 34: "2", 35: "00",
              37: "22", 39: "1", 40: "15", 42: "30"})
    c = run("OES_Lacrosse", pkt(47, "t", f)).snapshot()
    check(c, EventId="Lacrosse", ShotClockTens="3", ShotClockOnes="0", HomeScoreOnes="3", Period="2",
          HomePenaltyPlayer1Tens="1", HomePenaltyPlayer1ClockMinutesOnes="1", HomePenaltyPlayer2Ones="3",
          GuestPenaltyPlayer1Tens="2", GuestPenaltyPlayer2ClockSecondTens="1", GuestPenaltyPlayer2ClockSecondOnes="5")
    assert "HomeGoal" not in c and "HomePenaltyPlayer3Tens" not in c


# ------------------------------------------------------------------ soccer / volleyball / wrestling
def test_soccer_pro():
    f = {2: "4512", 6: "1", 7: "02", 9: "01", 11: "08", 13: "03", 15: "05", 17: "01", 19: "11", 21: "04",
         23: "02", 25: "00"}
    c = run("OES_SoccerPro", pkt(32, "s", f)).snapshot()
    check(c, ClockMinutesTens="4", ClockMinutesOnes="5", ClockSecondTens="1", ClockSecondOnes="2", Period="1",
          HomeScoreOnes="2", GuestScoreOnes="1", HomeShotTens="0", HomeShotOnes="8", HomeSaves="03",
          HomeCornerKicks="05", HomePenalties="01", GuestShotTens="1", GuestShotOnes="1", GuestSaves="04",
          GuestCornerKicks="02", GuestPenalties="00", HomePossession=" ")


def test_soccer_ignores_t_packets():
    c = run("OES_SoccerPro", pkt(32, "t", {7: "09"})).snapshot()
    assert "HomeScoreOnes" not in c


def test_volleyball():
    f = {2: "0000", 6: "3", 7: "24", 9: "22", 11: "1", 12: "2", 17: "1", 18: "0", 20: "2", 22: "1"}
    c = run("OES_Volleyball", pkt(31, "t", f)).snapshot()
    check(c, Set="3", IsSet3="1", HomeScoreTens="2", HomeScoreOnes="4", GuestScoreOnes="2", HomeTimeout="1",
          GuestTimeout="2", HomeServe="*", GuestServe=" ", HomeGamesWon="2", GuestGamesWon="1",
          InternalClockStatus="R")
    c = run("OES_Volleyball", pkt(31, "t", {2: bytes([0xB0]), 6: "1"})).snapshot()
    check(c, IsSet3="0", InternalClockStatus="S")


def test_wrestling():
    f = {2: "0130", 6: "2", 7: "05", 9: "03", 19: "12", 21: "09", 25: "07"}
    c = run("OES_Wrestling", pkt(29, "t", f)).snapshot()
    check(c, Period="2", HomeScoreOnes="5", GuestScoreOnes="3", HomeMatchScoreTens="1", HomeMatchScoreOnes="2",
          GuestMatchScoreTens="0", GuestMatchScoreOnes="9", HomeMatchTens="0", HomeMatchOnes="7")


# ------------------------------------------------------------------ baseball
def put_innings(f, home, guest, home_vals, guest_vals):
    for i, v in zip(home, home_vals):
        f[i] = v
    for i, v in zip(guest, guest_vals):
        f[i] = v


def test_baseball_standard():
    f = {2: "2", 3: " 5", 5: "07", 12: "88", 22: "097", 25: "2", 26: "1", 27: "2", 28: bytes([73]), 30: "05",
         32: "08", 34: "1", 35: "03", 37: "06", 39: "0"}
    put_innings(f, range(50, 60), range(40, 50), "0102030000", "0000100200")
    c = run("OES_BaseballStandard", pkt(75, "t", f)).snapshot()
    check(c, Balls="2", Strikes="1", Outs="2", ErrorFlag="H", GuestRunTens="0", GuestRunOnes="5",
          GuestHitsTens="0", GuestHitsOnes="8", GuestErrors="1", HomeRunOnes="3", HomeHitsOnes="6",
          GuestInning1="0", GuestInning5="1", HomeInning1="0", HomeInning2="1", HomeInning3="0", HomeInning4="2",
          TopBottomInning="B", TopOfInning=" ", BottomOfInning=".", InningTens=" ", InningOnes="5",
          AtBatTens="0", AtBatOnes="7", PitchSpeed="097", PitchCount=" 88", ClockMode=":", EventId="Baseball")
    assert create("OES_BaseballStandard").contract_name == "BaseballSoftball"


def test_baseball_standard_top_and_unknown_half():
    c = run("OES_BaseballStandard", pkt(75, "t", {2: "1"})).snapshot()
    check(c, TopBottomInning="T", TopOfInning=".", BottomOfInning=" ")
    c = run("OES_BaseballStandard", pkt(75, "t", {2: "0"})).snapshot()
    check(c, TopBottomInning=" ", TopOfInning=" ", BottomOfInning=" ")


def test_baseball_error_flag_is_sticky():
    p = create("OES_BaseballStandard")
    p.feed(pkt(75, "t", {28: bytes([71])}))
    check(p.snapshot(), ErrorFlag="E")
    p.feed(pkt(75, "t", {28: bytes([60])}))  # unlisted byte: unchanged
    check(p.snapshot(), ErrorFlag="E")
    p.feed(pkt(75, "t", {28: bytes([58])}))
    check(p.snapshot(), ErrorFlag=" ")


def test_baseball_code50():
    f = {2: "09", 4: "3", 17: "2", 18: "1", 33: "04", 35: "02", 37: "07", 39: "05", 41: "1", 42: "2", 49: "2"}
    put_innings(f, [6, 7, 8, 9, 10, 21, 22, 23, 24, 25], [11, 12, 13, 14, 15, 26, 27, 28, 29, 30],
                "1000200000", "0120000000")
    f.update({36: "x"})
    c = run("OES_Baseball_Code50", pkt(52, "t", f)).snapshot()
    check(c, Balls="3", Strikes="2", Outs="1", HomeRunTens="0", HomeRunOnes="4", HomeHitsTens="0",
          HomeHitsOnes="7", HomeErrors="1", GuestHitsTens="0", GuestHitsOnes="5", GuestErrors="2",
          AtBatTens="0", AtBatOnes="9", TopBottomInning="B", BottomOfInning=".",
          GuestInning1="0", GuestInning2="1", GuestInning3="2", HomeInning1="1", HomeInning2="0",
          HomeInning3="0", HomeInning4="0", HomeInning5="2")
    # Guests marked in innings 1-3 (blank after), home 1-5 marked: derived inning is read from the line score
    assert c["InningTens"] + c["InningOnes"] != "  "


def test_baseball_code50_top():
    c = run("OES_Baseball_Code50", pkt(52, "t", {49: "1"})).snapshot()
    check(c, TopBottomInning="T", TopOfInning=".")


def test_baseball_code53():
    f = {2: "1", 3: " 7", 5: " 4", 10: "1", 11: "2", 12: "0", 13: "9", 17: "03", 19: "05", 21: "1",
         22: "02", 24: "04", 26: "0", 47: "091", 50: " 55"}
    put_innings(f, range(37, 47), range(27, 37), "0010000000", "0100000000")
    c = run("OES_Baseball_Code53", pkt(55, "t", f)).snapshot()
    check(c, TopBottomInning="T", TopOfInning=".", InningTens=" ", InningOnes="7", AtBatTens=" ", AtBatOnes="4",
          Balls="1", Strikes="2", Outs="0", ErrorFlag="E", GuestRunOnes="3", GuestHitsOnes="5", GuestErrors="1",
          HomeRunOnes="2", HomeHitsOnes="4", HomeErrors="0", GuestInning2="1", HomeInning3="1",
          PitchSpeed="091", PitchCount=" 55")
    c = run("OES_Baseball_Code53", pkt(55, "t", {2: "2", 13: "6"})).snapshot()
    check(c, ErrorFlag="H", TopBottomInning="B", BottomOfInning=".")


def test_baseball_code85_derives_inning_from_linescore():
    f = {10: " 3", 12: "1", 13: "6", 29: "2", 30: "1", 33: "04", 35: "08", 37: "1", 38: "03", 40: "06", 42: "0"}
    # guest innings 1-4 in bytes 2-5, 5-10 in 17-22; home 1-4 in 6-9, 5-10 in 23-28
    put_innings(f, [6, 7, 8, 9, 23, 24, 25, 26, 27, 28], [2, 3, 4, 5, 17, 18, 19, 20, 21, 22],
                "0001      ", "00010     ")
    c = run("OES_Baseball_Code85", pkt(48, "t", f)).snapshot()
    # guests have 5 innings posted, home 4: bottom of the 5th
    check(c, InningTens="0", InningOnes="5", TopBottomInning="B", Balls="1", Strikes="2", Outs="1",
          ErrorFlag="H", GuestRunOnes="4", GuestHitsOnes="8", GuestErrors="1", HomeRunOnes="3",
          HomeHitsOnes="6", HomeErrors="0", AtBatTens=" ", AtBatOnes="3", GuestInning4="1", GuestInning5="0")


def test_baseball_code85_complete_inning_advances():
    f = {}
    put_innings(f, [6, 7, 8, 9, 23, 24, 25, 26, 27, 28], [2, 3, 4, 5, 17, 18, 19, 20, 21, 22],
                "000       ", "000       ")
    c = run("OES_Baseball_Code85", pkt(48, "t", f)).snapshot()
    check(c, InningTens="0", InningOnes="4", TopBottomInning="T")
    c = run("OES_Baseball_Code85", pkt(48, "t", {})).snapshot()
    check(c, InningTens="0", InningOnes="1", TopBottomInning="T")


def test_baseball_isc85x():
    f = {2: " 6", 4: "2", 5: "1", 6: "0", 36: "01", 39: "5", 40: "2", 44: "03", 47: "7", 48: "1"}
    put_innings(f, [17, 18, 19, 20, 21, 22, 23, 33, 34, 35], [25, 26, 27, 28, 29, 30, 31, 41, 42, 43],
                "0000010001", "1000000200")
    c = run("OES_BaseballISC85X", pkt(52, "t", f)).snapshot()
    check(c, Balls="2", Strikes="1", Outs="0", HomeRunTens="0", HomeRunOnes="1", HomeHitsOnes="5",
          HomeErrors="2", GuestRunOnes="3", GuestHitsOnes="7", GuestErrors="1", AtBatOnes="6",
          HomeInning6="1", HomeInning10="1", GuestInning1="1", GuestInning8="2")
    assert "InningOnes" not in c and "GuestHitsTens" not in c


def test_baseball_pro_short_and_long():
    c = run("OES_BaseballPro", pkt(72, "t", {2: "G", 3: " 4", 6: "H", 25: "2", 26: "1", 27: "0", 30: "07",
                                             35: "03"})).snapshot()
    check(c, TopBottomInning="T", InningTens=" ", InningOnes="4", ErrorFlag="H", Balls="2", Strikes="1",
          Outs="0", GuestRunOnes="7", HomeRunOnes="3")
    assert "PitchSpeed" not in c
    f = {2: "H", 3: "10", 7: " 9", 14: "104", 27: "095", 30: "3", 31: "2", 32: "1", 33: "E", 35: "11", 37: "12",
         39: "3", 40: "09", 42: "10", 44: "1", 66: "1", 68: "0", 104: "X", 86: "2"}
    c = run("OES_BaseballPro", pkt(117, "t", f)).snapshot()
    check(c, TopBottomInning="B", BottomOfInning=".", InningTens="1", InningOnes="0", AtBatOnes="9",
          PitchSpeed="095", PitchCount="104", Balls="3", Strikes="2", Outs="1", ErrorFlag="E",
          GuestRunTens="1", GuestRunOnes="1", GuestHitsTens="1", GuestHitsOnes="2", GuestErrors="3",
          HomeRunOnes="9", HomeHitsTens="1", HomeErrors="1", GuestInning1="1", GuestInning2="0",
          HomeInning1="2", HomeInning10="X")


def test_baseball_pro_other_lengths_ignored():
    c = run("OES_BaseballPro", pkt(80, "t", {30: "3"})).snapshot()
    assert "Balls" not in c


# ------------------------------------------------------------------ short packets never raise
@pytest.mark.parametrize("pid", sorted(oes.PROTOCOLS))
def test_short_packet_is_harmless(pid):
    p = create(pid)
    p.feed(make_packet(b"\x02t12"))
    p.feed(make_packet(b"\x02s"))
    assert p.bad == 0
    assert p.packets == 2


# ------------------------------------------------------------------ autodetect
def test_registry_has_all_ids():
    expected = {"OES_AutoDetect", "OES_BaseballISC85X", "OES_BaseballPro", "OES_BaseballStandard",
                "OES_Baseball_Code50", "OES_Baseball_Code53", "OES_Baseball_Code85", "OES_Basketball",
                "OES_Basketball_Tissot_Adapter", "OES_Football", "OES_FootballWireless", "OES_HockeyPro",
                "OES_HockeyStandard", "OES_Hockey_ISC85X", "OES_Lacrosse", "OES_ShortHockeyStandard",
                "OES_SoccerPro", "OES_Volleyball", "OES_Wrestling"}
    assert set(oes.PROTOCOLS) == expected


def test_autodetect_switches_sport_by_packet_length():
    p = create("OES_AutoDetect")
    assert p.contract_name == "Generic"
    p.feed(pkt(26 - 1, "t", {7: "11"}))  # length 25 -> football
    assert p.decoder.detected == "OES_Football"
    assert p.contract_name == "Football"
    check(p.snapshot(), HomeScoreTens="1", HomeScoreOnes="1", EventId="Football")
    p.feed(pkt(32, "s", {7: "02", 9: "01"}))
    assert p.decoder.detected == "OES_SoccerPro"
    assert p.contract_name == "Soccer"
    c = p.snapshot()
    check(c, HomeScoreOnes="2", EventId="Soccer")
    assert "Down" not in c  # fresh contract for the new sport
    p.feed(pkt(47, "t", {42: "15"}))
    assert p.decoder.event == "Lacrosse"
    check(p.snapshot(), ShotClockTens="1", ShotClockOnes="5")


def test_autodetect_ignores_unknown_length_until_selected():
    p = create("OES_AutoDetect")
    p.feed(pkt(40, "t", {7: "11"}))
    assert p.packets == 1 and "HomeScoreTens" not in p.snapshot()
    p.feed(pkt(23, "t", {7: "21"}))
    assert p.decoder.detected == "OES_Basketball"
    # unknown length now goes to the selected decoder
    p.feed(pkt(40, "t", {7: "31"}))
    check(p.snapshot(), HomeScoreTens="3")


@pytest.mark.parametrize("length", sorted(AUTODETECT))
def test_autodetect_every_length(length):
    p = create("OES_AutoDetect")
    kind = "s" if length == 32 else "t"
    seen = []
    p.decoder.on_detect = seen.append
    p.feed(pkt(length, kind))
    assert p.decoder.detected == AUTODETECT[length][1]
    assert seen == [AUTODETECT[length][1]]
    assert p.decoder.contract == AUTODETECT[length][0]().contract
    assert p.bad == 0
