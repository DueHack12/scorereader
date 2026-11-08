"""Nevco (PIC 55 AA, code 0xB7) decoders. Packet index n = payload byte n-2 (index 0/1 are frame bytes 6/7)."""
from __future__ import annotations

import pytest

from scoreboards import nevco
from scoreboards.pic55aa import CODE_NEVCO, make_frame

L = 33  # payload length used by the tests: the decoder sees L + 3 = 36 bytes


def frame(fields: dict, length: int = L) -> bytes:
    payload = bytearray(length)
    for idx, val in fields.items():
        payload[idx - 2] = val
    return make_frame(CODE_NEVCO, bytes(payload))


def decode(pid: str, fields: dict) -> dict:
    p = nevco.PROTOCOLS[pid]()
    assert p.feed(frame(fields)) == 1
    return p.snapshot()


def clk(c):
    return c["ClockMinutesTens"] + c["ClockMinutesOnes"] + c["ClockMode"] + c["ClockSecondTens"] + c["ClockSecondOnes"]


# pid -> (packet bytes, expected contract fields)
CASES = {
    "Football": ({17: 0x01, 19: 0x02, 21: 0x03, 23: 0x04, 15: 0x01, 13: 0x07, 33: 0x32, 31: 0x41, 29: 0x01,
                  5: 0x03, 3: 0x05, 4: 0x08, 6: 0x09, 7: 0x02, 11: 0x01, 9: 0x00, 27: 0x03},
                 dict(ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
                      ClockSecondOnes="4", ClockTenthsSecond="0", HomeScoreTens="1", HomeScoreOnes="7",
                      GuestScoreTens="2", GuestScoreOnes="1", HomeTimeouts="4", GuestTimeouts="3",
                      HomePossession="<", GuestPossession=" ", BallOnTens="3", BallOnOnes="5",
                      PlayClockTens=" ", PlayClockOnes="9", Down="2", ToGoTens="1", ToGoOnes="0", Quarter="3")),
    "Football_Code827": ({17: 0x31, 19: 0x42, 21: 0x53, 23: 0x04, 15: 0x20, 13: 0x30, 33: 0x25, 31: 0x16, 11: 0x04,
                          4: 0x0C, 6: 0x05, 27: 0x30, 7: 0x02, 25: 0x40, 32: 0x07},
                         dict(ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
                              ClockSecondOnes="4", HomeScoreTens="2", HomeScoreOnes="3", GuestScoreTens="5",
                              GuestScoreOnes="6", HomePossession=" ", GuestPossession=">", BallOnTens="4",
                              BallOnOnes="3", PlayClockTens="4", PlayClockOnes="5", Down="3", ToGoTens="2",
                              ToGoOnes="1", Quarter="2", HomeTimeouts="4", GuestTimeouts="5")),
    "FootballMPC7": ({24: 0x23, 26: 0x14, 8: 0x21, 6: 0x07, 14: 0x14, 16: 0x45, 29: 0x38, 4: 0x03, 31: 0x10,
                      33: 0x02, 11: 0x23},
                     dict(ClockMode=":", ClockMinutesTens="4", ClockMinutesOnes="1", ClockSecondTens="3",
                          ClockSecondOnes="2", HomeScoreTens="1", HomeScoreOnes="2", GuestScoreTens="7",
                          GuestScoreOnes="0", HomePossession="<", GuestPossession=" ", Flag="F",
                          PlayClockTens="5", PlayClockOnes="4", BallOnTens="8", BallOnOnes="3", Down="0",
                          ToGoTens="0", ToGoOnes="1", Quarter="0", HomeTimeouts="3", GuestTimeouts="2")),
    "FootballMPC7_Code1": ({24: 0xF5, 26: 0x42, 4: 0x38, 31: 0x20, 29: 0x07, 14: 0x08},
                           dict(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens="2",
                                ClockSecondOnes="4", ClockTenthsSecond="5", BallOnTens="8", BallOnOnes="3",
                                Down="0", ToGoTens="7", ToGoOnes="0", GuestPossession=">", HomePossession=" ",
                                Flag=" ")),
    "Basketball": ({19: 0x05, 17: 0x04, 21: 0x03, 23: 0x04, 15: 0x01, 13: 0x07, 33: 0x02, 31: 0x03, 25: 0x08,
                    27: 0x08, 29: 0x05, 11: 0x09, 9: 0x08, 26: 0x02, 28: 0x03, 4: 0x05, 6: 0x07, 5: 0x01, 7: 0x02,
                    3: 0x03},
                   dict(ClockMode=":", ClockMinutesTens="0", ClockMinutesOnes="5", ClockSecondTens="3",
                        ClockSecondOnes="4", HomeScoreHundreds="1", HomeScoreTens="1", HomeScoreOnes="7",
                        GuestScoreHundreds=" ", GuestScoreTens="2", GuestScoreOnes="3", HomePossession=" ",
                        GuestPossession=">", HomeBonus="B", GuestBonus=" ", Period="4", HomeFoulTens="1",
                        HomeFoulOnes="9", GuestFoulTens=" ", GuestFoulOnes="8", HomeTimeouts="3",
                        GuestTimeouts="2", ShotClockSecondTens="5", ShotClockSecondOnes="7",
                        FoulPlayerTens="1", FoulPlayerOnes="2", FoulPlayerNumberOfFouls="3")),
    "Basketball_2745": ({19: 0x00, 17: 0x00, 21: 0x02, 23: 0x09, 32: 0x03, 11: 0x50, 31: 0x60, 29: 0x70, 23 + 0: 0x09},
                        dict(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens="2",
                             ClockSecondOnes="9", ClockTenthsSecond="3", HomeFoulOnes="5", GuestFoulOnes="6",
                             HomeTimeouts="7", GuestTimeouts="0", ShotClockSecondTens="0", ShotClockSecondOnes="0")),
    "BasketballMPC7": ({34: 244, 19: 0x02, 17: 0x00, 21: 0x41, 23: 0x05, 30: 0x08, 15: 0x01, 13: 0x0B, 33: 0x00,
                        31: 0x04, 20: 0x0C, 29: 0x03, 11: 0x06, 7: 0x04, 9: 0x08, 28: 0x03, 26: 0x01, 27: 0x0E,
                        4: 0x02, 6: 0x09},
                       dict(ClockMode=":", ClockMinutesTens="8", ClockMinutesOnes="2", ClockSecondTens="1",
                            ClockSecondOnes="5", HomeScoreTens="1", HomeScoreOnes="0", GuestScoreTens="0",
                            GuestScoreOnes="4", HomeDoubleBonus="B", GuestDoubleBonus="B", HomeFoulTens="1",
                            GuestFoulTens="1", HomeFoulOnes="6", GuestFoulOnes="8", HomeTimeouts="3",
                            GuestTimeouts="1", Period="9", ShotClockSecondTens="2", ShotClockSecondOnes="9",
                            FoulPlayerNumberOfFouls="1")),
    "BasketballMPC7_Code1": ({34: 244, 19: 0x03, 17: 0x01, 21: 0x20, 23: 0x08, 13: 0x05, 31: 0x06, 22: 0x02,
                              9: 0x07, 4: 0x03, 6: 0x0F, 27: 0x01},
                             dict(ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="3", ClockSecondTens="0",
                                  ClockSecondOnes="8", HomeScoreOnes="5", GuestScoreOnes="6", GuestFoulTens="2",
                                  GuestFoulOnes="7", ShotClockSecondTens="3", ShotClockSecondOnes=" ", Period="1")),
    "Hockey": ({17: 0x04, 19: 0x03, 21: 0x05, 23: 0x06, 32: 0x07, 4: 0x01, 6: 0x02, 15: 0x01, 13: 0x02, 33: 0x03,
                31: 0x04, 16: 0x50, 14: 0x60, 12: 0x70, 10: 0x80, 27: 0x02, 21 + 0: 0x0D, 9: 0x45, 7: 0x31,
                11: 0x1F, 3: 0x20, 5: 0x30},
               dict(ClockMode=":", ClockMinutesTens="0", ClockMinutesOnes="3", ClockSecondTens="5",
                    ClockSecondOnes="6", ClockTenthsSecond="7", ShotClockTens="1", ShotClockOnes="2",
                    HomeScoreTens="1", HomeScoreOnes="2", HomeGoal="*", GuestScoreTens="3", GuestScoreOnes="4",
                    GuestGoal=" ", HomeShotOnGoalTens="5", HomeShotOnGoalOnes="6", GuestShotOnGoalTens="7",
                    GuestShotOnGoalOnes="8", Period="2", Horn="H", HomePenaltyPlayer1Tens="5",
                    HomePenaltyPlayer1Ones="1", HomePenaltyPlayer1ClockMinutesTens="1",
                    HomePenaltyPlayer1ClockMinutesOnes="2", HomePenaltyPlayer1ClockSecondTens="3",
                    HomePenaltyPlayer1ClockSecondOnes="3", HomePenaltyPlayer2ClockMinutesTens="1",
                    GuestPenaltyPlayer1ClockMinutesTens="1", HomePlayerPopUp="  ", GuestPlayerPopUp="  ")),
    "LacrosseMPC7": ({34: 112, 24: 0x45, 26: 0x12, 7: 0x23, 15: 0x34, 27: 0x56, 8: 0x07, 6: 0x10, 10: 0x03,
                      16: 0x21},
                     dict(ClockMode=":", ClockMinutesTens="2", ClockMinutesOnes="1", ClockSecondTens="5",
                          ClockSecondOnes="4", HomePenaltyPlayer1Tens="3", HomePenaltyPlayer1Ones="2",
                          HomePenaltyPlayer1ClockMinutesOnes="4", HomePenaltyPlayer1ClockSecondTens="6",
                          HomePenaltyPlayer1ClockSecondOnes="5", HomePenaltyPlayer2ClockMinutesOnes="3",
                          HomePenaltyPlayer3Tens=" ", HomeScoreTens="7", HomeScoreOnes="0", GuestScoreTens="0",
                          GuestScoreOnes="1", Period="0", ShotClockTens="1", ShotClockOnes="2")),
    "Soccer": ({17: 0x04, 19: 0x05, 21: 0x03, 23: 0x02, 15: 0x01, 13: 0x02, 33: 0x03, 31: 0x04, 5: 0x05, 3: 0x06,
                11: 0x07, 9: 0x08, 27: 0x02},
               dict(ClockMode=":", ClockMinutesTens="4", ClockMinutesOnes="5", ClockSecondTens="3",
                    ClockSecondOnes="2", ClockTenthsSecond="0", HomeScoreTens="1", HomeScoreOnes="2",
                    GuestScoreTens="3", GuestScoreOnes="4", HomeShotTens="5", HomeShotOnes="6",
                    GuestShotTens="7", GuestShotOnes="8", Period="2")),
    "Soccer_Code761": ({17: 0x14, 19: 0x25, 21: 0x03, 23: 0x02, 15: 0x10, 13: 0x20, 33: 0x43, 31: 0x54, 7: 0x01},
                       dict(ClockMinutesTens="4", ClockMinutesOnes="5", HomeScoreTens="1", HomeScoreOnes="2",
                            GuestScoreTens="3", GuestScoreOnes="4", HomeShotTens="4", HomeShotOnes="5",
                            GuestShotTens="2", GuestShotOnes="1", Period="1")),
    "SoccerMPCX": ({24: 0x34, 26: 0x12, 8: 0x56, 6: 0x78, 4: 0x91, 33: 0x23, 10: 0x02},
                   dict(ClockMinutesTens="2", ClockMinutesOnes="1", ClockSecondTens="4", ClockSecondOnes="3",
                        HomeScoreTens="6", HomeScoreOnes="5", GuestScoreTens="8", GuestScoreOnes="7",
                        HomeShotTens="1", HomeShotOnes="9", GuestShotTens="3", GuestShotOnes="2", Period="0")),
    "Volleyball": ({5: 0x03, 11: 0x01, 9: 0x02, 15: 0x01, 13: 0x05, 17: 0x03, 19: 0x04, 21: 0x05, 23: 0x06,
                    25: 0x08, 33: 0x02, 31: 0x03},
                   dict(ClockMode=":", Game="3", HomeGamesWon="1", GuestGamesWon="2", HomeScoreTens="1",
                        HomeScoreOnes="5", ClockMinutesTens="3", ClockMinutesOnes="4", ClockSecondTens="5",
                        ClockSecondOnes="6", HomeServe=" ", GuestServe="*", GuestScoreTens="2", GuestScoreOnes="3")),
    "VolleyballMPC7": ({34: 4, 19: 0x00, 17: 0x00, 21: 0x02, 23: 0x03, 32: 0x09, 5: 0x02, 15: 0x01, 13: 0x02,
                        11: 0x01, 33: 0x02, 31: 0x01, 9: 0x00, 28: 0x01, 26: 0x02, 25: 0x04},
                       dict(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens="2",
                            ClockSecondOnes="3", ClockTenthsSecond="9", Set="2", Game="2", HomeScoreTens="1",
                            HomeScoreOnes="2", HomeGamesWon="1", GuestScoreTens="2", GuestScoreOnes="1",
                            GuestGamesWon="0", HomeTimeout="1", GuestTimeout="2", HomeServe="*", GuestServe=" ")),
    "Wrestling": ({17: 0x01, 19: 0x02, 21: 0x03, 23: 0x04, 15: 0x01, 13: 0x02, 33: 0x03, 31: 0x04, 29: 0x01,
                   11: 0x05, 9: 0x06, 25: 0x0C, 3: 0x01, 5: 0x02, 7: 0x03, 27: 0x02},
                  dict(ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
                       ClockSecondOnes="4", ClockTenthsSecond=" ", HomeScoreTens="1", HomeScoreOnes="2",
                       GuestScoreTens="3", GuestScoreOnes="4", HomeMatchScoreTens="1", HomeMatchScoreOnes="5",
                       GuestMatchScoreTens="0", GuestMatchScoreOnes="6", WeightClass="123", Period="2")),
    "Baseball": ({28: 0x02, 26: 0x01, 24: 0x01, 18: 0x00, 16: 0x03, 13: 0x01, 11: 0x25, 33: 0x10, 31: 0x20,
                  29: 0x30, 9: 0x12, 7: 0x34, 5: 0x56, 32: 0x01, 30: 0x07, 22: 12},
                 dict(Balls="2", Strikes="1", Outs="1", InningTens="0", InningOnes="3", GuestRunTens=" ",
                      GuestRunOnes="2", HomeRunTens="1", HomeRunOnes="5", GuestInning1="1", HomeInning1="0",
                      GuestInning2="2", HomeInning2="0", GuestInning3="3", HomeInning3="0", GuestHitsTens="1",
                      HomeHitsTens="2", GuestHitsOnes="3", HomeHitsOnes="4", GuestErrors="6", HomeErrors="5",
                      AtBatTens="1", AtBatOnes="7", ErrorFlag="E", TopBottomInning="B", TopOfInning=" ",
                      BottomOfInning=".", GuestErrorNumber=" ")),
    "Baseball_MPCX_Code706": ({4: 247, 7: 0x02, 9: 0x01, 27: 0x00, 19: 0x05, 33: 0x01, 31: 0x04, 15: 0x00,
                               13: 0x07, 5: 0x01, 3: 0x02, 29: 243},
                              dict(Balls="2", Strikes="1", Outs="0", InningTens=" ", InningOnes="5",
                                   GuestRunTens="1", GuestRunOnes="4", HomeRunTens="0", HomeRunOnes="7",
                                   AtBatTens="1", AtBatOnes="2", ErrorFlag="H", TopBottomInning=" ")),
    "Baseball_MPCX_code_252": ({27: 0x03, 29: 0x0C, 25: 0x01, 19: 0x04, 33: 0x01, 31: 0x02, 23: 0x00, 21: 0x09},
                               dict(Balls="2", Strikes="2", Outs="1", InningTens=" ", InningOnes="4",
                                    GuestRunTens="1", GuestRunOnes="2", HomeRunTens="0", HomeRunOnes="9")),
    "SimpleBaseball_Code925": ({25: 0x03, 23: 0x02, 21: 0x01, 19: 0x01, 17: 0x02, 33: 0x01, 31: 0x05, 15: 0x00,
                                13: 0x0F, 29: 0x00, 27: 0x09},
                               dict(Balls="3", Strikes="2", Outs="1", InningTens="1", InningOnes="2",
                                    GuestRunTens="1", GuestRunOnes="5", HomeRunTens="0", HomeRunOnes="0",
                                    AtBatTens="0", AtBatOnes="9")),
    "SimpleBaseball_Code673": ({27: 0x07, 29: 0x04, 25: 0x00, 11: 0x01, 33: 0x01, 31: 0x02, 15: 0x00, 13: 0x03},
                               dict(Balls="3", Strikes="1", Outs="0", InningTens=" ", InningOnes="1",
                                    GuestRunTens="1", GuestRunOnes="2", HomeRunTens="0", HomeRunOnes="3",
                                    TopBottomInning="T", TopOfInning=".", BottomOfInning=" ")),
    "HandheldBaseball_Code673": ({27: 0x06, 33: 0x01, 31: 0x02, 15: 0x03, 13: 0x04},
                                 dict(Balls=" ", Strikes=" ", Outs=" ", InningTens=" ", InningOnes="6",
                                      GuestRunTens="1", GuestRunOnes="2", HomeRunTens="3", HomeRunOnes="4",
                                      TopBottomInning=" ")),
    "SimpleBaseballMPC7": ({34: 112, 31: 0x30, 29: 0x20, 33: 0x10, 14: 0x80, 10: 0x20, 6: 0x12, 8: 0x34,
                            21: 0x56, 23: 0x78, 18: 241, 4: 0x09, 17: 0x71, 19: 0x82},
                           dict(Balls="3", Strikes="2", Outs="1", InningTens="1", InningOnes="2",
                                GuestRunTens="2", GuestRunOnes="1", HomeRunTens="4", HomeRunOnes="3",
                                GuestHitsTens="6", GuestHitsOnes="5", HomeHitsTens="8", HomeHitsOnes="7",
                                TopBottomInning="B", TopOfInning=" ", BottomOfInning=".", AtBatTens="9",
                                AtBatOnes="0", GuestInning1="1", GuestErrors="7", HomeInning1="2",
                                HomeErrors="8")),
}

ALL_IDS = sorted(nevco.PROTOCOLS)


def test_every_id_has_a_case():
    covered = {f"PIC55AA_Nevco_{k}" for k in CASES} | {"PIC55AA_Nevco_Basketball_2745", "PIC55AA_Nevco_HockeyMPC7",
                                                       "PIC55AA_Nevco_Baseball_MPCX_Code706"}
    assert len(ALL_IDS) == 24
    assert set(ALL_IDS) <= covered


@pytest.mark.parametrize("name", sorted(CASES))
def test_decode(name):
    fields, expected = CASES[name]
    c = decode(f"PIC55AA_Nevco_{name}", fields)
    for key, want in expected.items():
        assert c.get(key) == want, key


def test_basketball_2745_fouls_and_timeouts():
    # 2745 reads the high nibbles of bytes 11, 31, 29, 23; bytes 31 and 29 also feed other fields
    c = decode("PIC55AA_Nevco_Basketball_2745", CASES["Basketball_2745"][0])
    assert (c["HomeFoulOnes"], c["GuestFoulOnes"], c["HomeTimeouts"], c["GuestTimeouts"]) == ("5", "6", "7", "0")


def test_hockey_mpc7_is_plain_hockey():
    c = decode("PIC55AA_Nevco_HockeyMPC7", CASES["Hockey"][0])
    assert c["EventId"] == "Hockey" and c["HomeScoreOnes"] == "2" and c["Period"] == "2"


def test_event_and_contract_names():
    expect = {"Lacrosse": "LacrosseMPC7", "Hockey": "Hockey", "Wrestling": "Wrestling", "Volleyball": "Volleyball",
              "Soccer": "Soccer", "Football": "Football", "Basketball": "Basketball", "Baseball": "Baseball"}
    for event, name in expect.items():
        d = nevco.PROTOCOLS[f"PIC55AA_Nevco_{name}"]().decoder
        assert d.event == event and d.c["EventId"] == event
    assert nevco.PROTOCOLS["PIC55AA_Nevco_LacrosseMPC7"]().decoder.contract == "HockeyLacrosse"
    assert nevco.PROTOCOLS["PIC55AA_Nevco_Baseball"]().decoder.contract == "BaseballSoftball"


# ---- details worth pinning
def test_football_play_clock_tens_blanks_7_and_up():
    for tens, want in ((0x06, "6"), (0x07, " "), (0x09, " ")):
        assert decode("PIC55AA_Nevco_Football", {4: tens})["PlayClockTens"] == want
    # code 827 masks bit 3 first: 0x0F -> 0x07 -> blank, 0x08 -> 0x00 -> "0"
    assert decode("PIC55AA_Nevco_Football_Code827", {4: 0x08})["PlayClockTens"] == "0"
    assert decode("PIC55AA_Nevco_Football_Code827", {4: 0x0F})["PlayClockTens"] == " "


def test_football_827_all_lamps_lit_hides_guest_possession():
    assert decode("PIC55AA_Nevco_Football_Code827", {11: 0x0F})["GuestPossession"] == " "
    assert decode("PIC55AA_Nevco_Football_Code827", {11: 0x04})["GuestPossession"] == ">"


def test_football_clock_switches_to_seconds_and_tenths():
    c = decode("PIC55AA_Nevco_Football", {21: 0x05, 23: 0x06, 32: 0x07})
    assert c["ClockMode"] == "." and c["ClockSecondTens"] == "5" and c["ClockTenthsSecond"] == "7"
    assert c["ClockMinutesTens"] == "0" and c["ClockMinutesOnes"] == "0"


def test_mpc7_basketball_guest_fouls_use_byte_9():
    c = decode("PIC55AA_Nevco_BasketballMPC7", {34: 244, 9: 0x05, 7: 0x03})
    assert c["GuestFoulOnes"] == "5"


def test_basketball_minutes_tens_split_across_bytes():
    # bits 2-3 of byte 30 and bits 0-1 of byte 17 build the minutes tens digit (here 0b1011 = 11 -> blank)
    c = decode("PIC55AA_Nevco_Basketball", {30: 0x08, 17: 0x03, 19: 0x01})
    assert c["ClockMode"] == ":" and c["ClockMinutesTens"] == " "
    c = decode("PIC55AA_Nevco_Basketball", {30: 0x04, 17: 0x01, 19: 0x01})
    assert c["ClockMinutesTens"] == "5"


def test_nevco_digit_table():
    assert [nevco._nevco_digit(b, 0) for b in (0, 1, 2, 4, 8, 9, 0xA, 0xC, 0xD, 0xE)] == list("0123456789")
    assert nevco._nevco_digit(0x30, 0) == "0" and nevco._nevco_digit(0x30, 1) == " "
    assert nevco._nevco_digit(0xF0, 1) == " "


def test_mpc_variants_ignore_other_packet_types():
    for name, marker in (("BasketballMPC7", 244), ("VolleyballMPC7", 4), ("LacrosseMPC7", 112),
                         ("Baseball_MPCX_Code706", None)):
        p = nevco.PROTOCOLS[f"PIC55AA_Nevco_{name}"]()
        before = p.snapshot()
        p.feed(frame({34: 99, 4: 99}))
        assert p.snapshot() == before, name


def test_simple_baseball_mpc7_late_innings_packet():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_SimpleBaseballMPC7"]()
    p.feed(frame(CASES["SimpleBaseballMPC7"][0]))
    p.feed(frame({34: 120, 17: 0x12, 19: 0x34, 21: 0x56, 23: 0x78}))
    c = p.snapshot()
    assert (c["GuestInning9"], c["GuestInning10"], c["HomeInning9"], c["HomeInning10"]) == ("2", "1", "4", "3")
    assert (c["GuestInning7"], c["GuestInning8"], c["HomeInning7"], c["HomeInning8"]) == ("6", "5", "8", "7")
    assert c["HomeRunOnes"] == "3"  # main-packet data is kept


def test_baseball_bottom_of_inning_when_home_line_filled():
    c = decode("PIC55AA_Nevco_Baseball", {16: 0x01, 33: 0x25})
    assert c["TopBottomInning"] == "B" and c["BottomOfInning"] == "." and c["TopOfInning"] == " "


def test_baseball_673_infers_half_inning():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_SimpleBaseball_Code673"]()
    p.feed(frame({11: 0x01, 25: 0x03}))
    assert p.snapshot()["TopBottomInning"] == "T" and p.snapshot()["Outs"] == "2"
    p.feed(frame({11: 0x01, 25: 0x00}))  # outs fell back to 0 in the top: bottom of the inning
    assert p.snapshot()["TopBottomInning"] == "B"
    p.feed(frame({11: 0x02, 25: 0x00}))  # new inning number: top
    assert p.snapshot()["TopBottomInning"] == "T"


# ---- framing
@pytest.mark.parametrize("pid", ALL_IDS)
def test_short_packets_never_raise(pid):
    d = nevco.PROTOCOLS[pid]().decoder
    assert d.need <= 35
    before = dict(d.c)
    d.decode(bytes(d.need - 1))
    assert d.c == before
    d.decode(b"")
    d.decode(bytes(d.need))  # exactly the minimum length decodes without error
    for n in range(0, 40):
        d.decode(bytes([244]) * n)


def test_garbage_before_frame():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_Soccer"]()
    f = frame(CASES["Soccer"][0])
    assert p.feed(b"\x00\x13\x55\x01junk" + f) == 1
    assert p.snapshot()["HomeScoreOnes"] == "2"


def test_frame_split_across_feeds():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_Soccer"]()
    f = frame(CASES["Soccer"][0])
    assert p.feed(f[:10]) == 0 and p.feed(f[10:30]) == 0
    assert p.feed(f[30:]) == 1
    assert p.snapshot()["GuestShotTens"] == "7"


def test_two_frames_in_one_feed():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_Soccer"]()
    f = frame(CASES["Soccer"][0])
    assert p.feed(f + f) == 2


def test_bad_checksum_rejected():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_Soccer"]()
    f = bytearray(frame(CASES["Soccer"][0]))
    f[-1] ^= 0x5A
    assert p.feed(bytes(f)) == 0 and p.bad == 1
    assert p.feed(frame(CASES["Soccer"][0])) == 1  # stream recovers


def test_wrong_code_ignored():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_Soccer"]()
    assert p.feed(make_frame(0xBD, bytes(L))) == 0
    assert p.snapshot() == {"EventId": "Soccer"}


def test_short_payload_frame_is_valid_but_ignored_by_decoder():
    p = nevco.PROTOCOLS["PIC55AA_Nevco_Soccer"]()
    assert p.feed(frame({}, length=10)) == 1  # framing OK, decoder needs 34 bytes and skips it
    assert p.snapshot() == {"EventId": "Soccer"}
