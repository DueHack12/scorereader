"""Tests for scoreboards.contracts: sbdata positions, JSON fields, flat() aliases, emulator, swap and the
comparison with the hand-written sportzcast_mqtt.build_payloads()."""
from __future__ import annotations

import json

import pytest

import sportzcast_mqtt
from scoreboards import contracts as K

NOW = 1700000000.25
META = {"bot_number": 5, "home_team_name": "HOME", "guest_team_name": "GUEST", "now": NOW, "publish_rate": 10.0}


def sb(contract, c, **meta):
    return K.sbdata(contract, c, dict(META, **meta))


def js(contract, c, **meta):
    return K.sportzcast_json(contract, c, dict(META, **meta))


# --------------------------------------------------------------------------- basics
def test_contract_list_and_event_codes():
    for name in ("Football", "Soccer", "Basketball", "BaseballSoftball", "HockeyLacrosse", "Volleyball", "Wrestling",
                 "WaterPolo", "Tennis", "TableTennisBadminton", "FutsalHandball", "DragRacing", "Rodeo", "Timer",
                 "Generic", "SwimmingDetail", "SwimmingEvent", "SwimmingRows", "SwimmingMixed"):
        assert name in K.CONTRACTS
    assert K.event_code("Baseball") == "01"
    assert K.event_code("Softball") == "04"
    assert K.event_code("Badminton") == "32"
    assert K.event_code("Nope") == "  "


@pytest.mark.parametrize("name", K.CONTRACTS)
def test_every_contract_runs_on_empty_dict(name):
    j = js(name, {})
    assert j["BotNumberHex"] == "000005" and j["OriginType"] == "Local" and j["InboundChannelNumber"] == "1"
    assert "ClockStatus" in j and "InternalClockStatus" not in j and "EmulatedClockStatus" not in j
    json.dumps(j)
    K.flat(name, {})
    assert K.swap_teams(name, {}) == {}
    if name != "SwimmingMixed":
        s = sb(name, {})
        assert len(s) == 150 and s[131] == "1" and s[132:138] == "000005"
        assert s[138:150] == "8DBE55EE90A2"


def test_timestamp_forms():
    j = js("Football", {})
    assert j["TimeStamp"] == "8DBE55EE90A2"
    assert j["TimeStampFull"] == "2023-11-14T22:13:20.2500000Z"
    assert j["TimeStampEpoch"] == "1700000000250"


def test_origin_and_channel_meta():
    j = js("Football", {}, origin=5, channel="3", venue_name="Rafferty", venue_id=7)
    assert j["OriginTypeId"] == 5 and j["OriginType"] == "Local emulated"
    assert j["InboundChannelNumber"] == "3" and j["VenueName"] == "Rafferty" and j["VenueId"] == 7


def test_team_name_meta_overrides_contract():
    c = {"HomeTeamName": "Old", "GuestTeamName": "Older"}
    assert js("Football", c)["HomeTeamName"] == "HOME"
    assert K.sportzcast_json("Football", c, {"now": NOW})["HomeTeamName"] == "Old"
    s = K.sbdata("Football", c, {"now": NOW})
    assert s[26:34] == "Old     "


# --------------------------------------------------------------------------- Football
FOOTBALL = {"EventId": "Football", "ClockMode": ":", "ClockMinutesOnes": "4", "ClockSecondTens": "3",
            "ClockSecondOnes": "2", "InternalClockStatus": "R", "PlayClockTens": "2", "PlayClockOnes": "5",
            "HomeScoreTens": "1", "HomeScoreOnes": "4", "GuestScoreTens": " ", "GuestScoreOnes": "7",
            "Quarter": "2", "HomePossession": "<", "HomeTimeouts": "3", "GuestTimeouts": "2", "BallOnTens": "3",
            "BallOnOnes": "5", "Down": "3", "ToGoTens": " ", "ToGoOnes": "7", "HomeYardsRushing": "123"}


def test_football_sbdata_positions():
    s = sb("Football", FOOTBALL)
    assert s[0:2] == "02"
    assert s[2:6] == " 432"
    assert s[8:10] == "25"
    assert s[11:13] == "14" and s[14:16] == " 7"
    assert s[16] == "<" and s[17] == " "
    assert s[18:20] == "32" and s[20] == "3"
    assert s[21:23] == " 7" and s[23:25] == "35" and s[25] == "2"
    assert s[26:34] == "HOME    " and s[34:42] == "GUEST   "
    assert s[42:46] == " 123"
    assert (s[116], s[117], s[118]) == ("R", ":", " ")


def test_football_json_fields():
    j = js("Football", FOOTBALL)
    assert j["EventId"] == 2 and j["Clock"] == "4:32" and j["FullClock"] == "4:32.0"
    assert j["HomeScore"] == "14" and j["GuestScore"] == "7"  # BuildScore drops leading blanks and zeros
    assert j["PlayClock"] == "25" and j["ToGo"] == " 7" and j["BallOn"] == "35"
    assert j["QuarterOrdinal"] == "2nd" and j["ClockStatus"] == "R"
    assert j["HomeYardsRushing"] == "123" and j["HomeTotalYards"] == ""
    assert j["WeightedCoverage"] == pytest.approx(0.95)
    assert isinstance(j["PublishRate"], float)


def test_build_score_edge_cases():
    assert js("Football", {})["HomeScore"] == "0"
    assert js("Football", {"HomeScoreTens": "0", "HomeScoreOnes": "0"})["HomeScore"] == "0"
    assert js("Football", {"HomeScoreTens": "0", "HomeScoreOnes": "7"})["HomeScore"] == "7"
    assert js("Football", {"HomeScoreTens": "1", "HomeScoreOnes": "0"})["HomeScore"] == "10"


def test_football_flat():
    f = K.flat("Football", FOOTBALL)
    assert f["sport"] == "football" and f["clock"] == "4:32" and f["clock_running"] is True
    assert f["home_score"] == "14" and f["guest_score"] == "7" and f["period"] == "2"
    assert f["period_ordinal"] == "2nd" and f["play_clock"] == "25"
    assert f["home_poss"] is True and f["guest_poss"] is False and f["possession"] == "H"
    assert f["down"] == "3rd" and f["to_go"] == "7" and f["ball_on"] == "35" and f["down_distance"] == "3rd & 7"
    assert f["home_timeouts"] == "3" and f["guest_timeouts"] == "2"
    assert f["home_score_tens"] == "1" and f["clock_minutes_tens"] == ""


def test_tenths_clock():
    c = {"ClockMode": ".", "ClockSecondTens": "5", "ClockSecondOnes": "9", "ClockTenthsSecond": "8"}
    assert js("Football", c)["Clock"] == "59.8"
    s = sb("Football", c)
    assert s[2:6] == "598 " and s[117] == "."
    c2 = {"ClockMode": ".", "ClockSecondTens": "0", "ClockSecondOnes": "5", "ClockTenthsSecond": "3"}
    assert js("Football", c2)["Clock"] == "5.3"


def test_swap_football():
    c = dict(FOOTBALL, GuestTeamName="B", HomeTeamName="A")
    w = K.swap_teams("Football", c)
    assert w is not c and c["HomeScoreOnes"] == "4"
    assert w["HomeScoreOnes"] == "7" and w["GuestScoreOnes"] == "4" and w["GuestScoreTens"] == "1"
    assert w["GuestPossession"] == ">" and w["HomePossession"] == " "
    assert w["HomeTimeouts"] == "2" and w["GuestTimeouts"] == "3"
    assert w["HomeTeamName"] == "B" and w["GuestTeamName"] == "A"
    assert "HomeYardsRushing" not in w  # swapped from the (absent) visitor value
    w2 = K.swap_teams("Football", w)
    assert w2["HomePossession"] == "<" and w2["GuestPossession"] == " "


# --------------------------------------------------------------------------- Soccer
SOCCER = {"EventId": "Soccer", "ClockMode": ":", "ClockMinutesTens": "4", "ClockMinutesOnes": "5",
          "ClockSecondTens": "0", "ClockSecondOnes": "9", "HomeScoreOnes": "2", "GuestScoreOnes": "1",
          "HomeShotTens": "1", "HomeShotOnes": "2", "GuestShotOnes": "5", "HomeCornerKicks": "11",
          "GuestCornerKicks": "3", "Period": "1", "Horn": "H"}


def test_soccer_sbdata_positions():
    s = sb("Soccer", SOCCER)
    assert s[0:2] == "08" and s[2:6] == "4509"
    assert s[11:13] == " 2" and s[14:16] == " 1"
    assert s[17:19] == "12" and s[19] == "1" and s[20:22] == " 5" and s[22] == "3"
    assert s[29] == "1" and s[30] == "H"
    assert s[31:39] == "HOME    " and s[39:47] == "GUEST   "
    assert s[47] == "1" and s[48] == " "  # tens digit of a two-digit corner count


def test_soccer_flat():
    f = K.flat("Soccer", SOCCER)
    assert f["sport"] == "soccer" and f["clock"] == "45:09" and f["period"] == "1"
    assert f["home_shots"] == "12" and f["guest_shots"] == "5" and f["home_corners"] == "11"
    assert f["home_score"] == "2" and f["horn"] is True


def test_soccer_swap():
    w = K.swap_teams("Soccer", SOCCER)
    assert "HomeShotTens" not in w  # swapped from the absent GuestShotTens
    assert w["HomeShotOnes"] == "5" and w["GuestShotOnes"] == "2" and w["HomeCornerKicks"] == "3"


# --------------------------------------------------------------------------- Basketball
def test_basketball():
    c = {"EventId": "Basketball", "ClockMode": ":", "ClockMinutesTens": "0", "ClockMinutesOnes": "7",
         "ClockSecondTens": "4", "ClockSecondOnes": "1", "ShotClockSecondTens": "1", "ShotClockSecondOnes": "4",
         "HomeScoreHundreds": "1", "HomeScoreTens": "0", "HomeScoreOnes": "5", "GuestScoreTens": "9",
         "GuestScoreOnes": "9", "HomeFoulOnes": "4", "GuestFoulTens": "1", "GuestFoulOnes": "0",
         "HomeBonus": "B", "HomeDoubleBonus": "D", "GuestPossession": ">", "Period": "7", "HomePlayer1": "23",
         "HomePlayer1Points": "12", "TimeoutClockMinutesOnes": "1", "TimeoutClockSecondTens": "0",
         "TimeoutClockSecondOnes": "5"}
    s = sb("Basketball", c)
    assert s[0:2] == "03" and s[2:6] == "0741"
    assert s[6] == "D" and s[7] == " "  # GuestDoubleBonus unset
    assert s[8:10] == "14" and s[10:13] == "105" and s[13:16] == " 99"
    assert s[17] == ">" and s[20] == "B" and s[22:24] == " 4" and s[24:26] == "10"
    assert s[29] == "E"  # periods above 4 collapse to overtime
    assert s[47:49] == "23" and s[50:52] == "12" and s[112:116] == "1:05"
    j = js("Basketball", c)
    assert j["HomeScore"] == "105" and j["GuestScore"] == "99" and j["ShotClock"] == "14"
    assert j["Period"] == "E" and j["PeriodOrdinal"] == "" and j["TimeoutClock"] == "1:05"
    assert j["WeightedCoverage"] == pytest.approx(1.0)
    f = K.flat("Basketball", c)
    assert f["shot_clock"] == "14" and f["home_fouls"] == "4" and f["guest_fouls"] == "10"
    assert f["home_bonus"] is True and f["guest_bonus"] is False and f["period"] == "E"
    assert f["guest_poss"] is True and f["possession"] == "V" and f["home_score"] == "105"
    # home hundreds digit is not swapped by ScoreConnect
    assert K.swap_teams("Basketball", c)["HomeScoreHundreds"] == "1"


def test_basketball_double_bonus_position():
    s = sb("Basketball", {"HomeDoubleBonus": "D", "GuestDoubleBonus": "E"})
    assert s[6] == "D" and s[7] == "E"
    assert js("Basketball", {"ShotClockSecondTens": "0", "ShotClockSecondOnes": "7",
                             "ShotClockTenthsSecond": "3"})["ShotClock"] == "7.3"


# --------------------------------------------------------------------------- Baseball / Softball
BASEBALL = {"EventId": "Softball", "Balls": "2", "Strikes": "1", "Outs": "2", "InningOnes": "3",
            "GuestRunOnes": "4", "HomeRunTens": "1", "HomeRunOnes": "2", "TopBottomInning": "B",
            "GuestHitsOnes": "6", "HomeHitsTens": "1", "HomeHitsOnes": "0", "GuestErrors": "1",
            "HomeErrors": "0", "AtBatTens": "1", "AtBatOnes": "4", "GuestInning1": "0", "HomeInning1": "2",
            "OnFirst": "1", "OnThird": "1", "PitchSpeed": "72", "PitchCount": "45", "PitchClockSecondTens": "1",
            "PitchClockSecondOnes": "5"}


def test_baseball_sbdata():
    s = sb("BaseballSoftball", BASEBALL)
    assert s[0:2] == "04"
    assert s[6:9] == "212" and s[9:11] == " 3" and s[11:13] == " 4" and s[13:15] == "12" and s[15] == "B"
    assert s[16:18] == " 6" and s[18:20] == "10" and s[20] == "1" and s[21] == "0" and s[22:24] == "14"
    assert s[30] == "0" and s[31] == "2"
    assert s[50:58] == "GUEST   " and s[58:66] == "HOME    "
    assert s[66] == "1" and s[67] == " " and s[68] == "1" and s[69:72] == " 72" and s[72:75] == " 45"
    assert s[75:79] == "  15"


def test_baseball_json_and_flat():
    j = js("BaseballSoftball", BASEBALL)
    assert j["EventId"] == 4 and j["Inning"] == " 3" and j["InningOrdinal"] == "3rd"
    assert j["HomeRuns"] == "12" and j["GuestRuns"] == "4" and j["PitchClock"] == "0:15"
    assert js("BaseballSoftball", {"InningTens": "1", "InningOnes": "2"})["InningOrdinal"] == "12th"
    f = K.flat("BaseballSoftball", BASEBALL)
    assert f["sport"] == "softball" and f["balls"] == "2" and f["strikes"] == "1" and f["outs"] == "2"
    assert f["inning"] == "3" and f["inning_ordinal"] == "3rd" and f["inning_half"] == "bottom"
    assert f["home_hits"] == "10" and f["guest_hits"] == "6" and f["home_errors"] == "0"
    assert f["home_score"] == "12" and f["guest_score"] == "4" and f["on_first"] is True and f["on_second"] is False
    w = K.swap_teams("BaseballSoftball", BASEBALL)
    assert w["HomeRunOnes"] == "4" and w["GuestRunTens"] == "1" and w["GuestInning1"] == "2"


# --------------------------------------------------------------------------- Hockey / Lacrosse
def test_hockey():
    c = {"EventId": "Hockey", "ClockMode": ":", "ClockMinutesTens": "1", "ClockMinutesOnes": "2",
         "ClockSecondTens": "0", "ClockSecondOnes": "5", "HomeScoreOnes": "3", "GuestScoreOnes": "2",
         "HomeGoal": "*", "HomeShotOnGoalTens": "1", "HomeShotOnGoalOnes": "8", "Period": "3",
         "HomePenaltyPlayer1Tens": "1", "HomePenaltyPlayer1Ones": "7", "HomePenaltyPlayer1ClockMinutesOnes": "1",
         "HomePenaltyPlayer1ClockSecondTens": "4", "HomePenaltyPlayer1ClockSecondOnes": "0",
         "HomePlayer1PenaltyType1": "T", "HomeSaves": "21", "GuestPossession": ">",
         "ShotClockTens": "2", "ShotClockOnes": "8"}
    s = sb("HockeyLacrosse", c)
    assert s[0:2] == "05" and s[2:6] == "1205" and s[8:10] == "28"
    assert s[11:13] == " 3" and s[13] == "*" and s[14:16] == " 2"
    assert s[24:26] == "18" and s[29] == "3"
    assert s[47:49] == "17"
    assert s[49] == " " and s[50] == "1" and s[51] == "4" and s[52] == "0"
    assert s[87:89] == "21" and s[92] == ">" and s[119] == "T"
    j = js("HockeyLacrosse", c)
    assert j["HomePenaltyPlayer1"] == "17" and j["HomePenaltyPlayer1Clock"] == "1:40"
    assert j["PeriodOrdinal"] == "3rd" and j["HomeShotsOnGoal"] == "18" and j["ShotClock"] == "28.0"
    f = K.flat("HockeyLacrosse", c)
    assert f["home_shots"] == "18" and f["home_penalties"] == 1 and f["guest_penalties"] == 0
    assert f["home_saves"] == "21" and f["guest_poss"] is True
    assert K.flat("HockeyLacrosse", dict(c, EventId="Lacrosse"))["sport"] == "lacrosse"
    assert sb("HockeyLacrosse", dict(c, EventId="Lacrosse"))[0:2] == "07"


# --------------------------------------------------------------------------- Volleyball
def test_volleyball():
    c = {"EventId": "Volleyball", "HomeGamesWon": "1", "GuestGamesWon": "2", "HomeScoreTens": "2",
         "HomeScoreOnes": "1", "GuestScoreTens": "1", "GuestScoreOnes": "9", "HomeServe": "*",
         "HomeTimeout": "1", "HomeScoreSet1": "25", "GuestScoreSet1": "20", "HomeScoreSet5": "15",
         "HomePlayer1": "7", "HomePlayer1Kills": "4", "HomePlayer1Digs": "11", "Set": "4", "Game": "1",
         "GuestPlayer6Digs": "9", "TimeoutClockMinutesOnes": "0", "TimeoutClockSecondTens": "3",
         "TimeoutClockSecondOnes": "0"}
    s = sb("Volleyball", c)
    assert s[0:2] == "06" and s[6] == "1" and s[7:9] == "21" and s[9] == "2" and s[10:12] == "19"
    assert s[12] == "*" and s[14] == "1" and s[16:20] == "2520" and s[102:104] == "15"
    assert s[48:50] == " 7" and s[50] == "4" and s[51:53] == "11" and s[119] == "4" and s[120] == "1"
    assert s[129:131] == " 9" and s[107:110] == "030"
    j = js("Volleyball", c)
    assert j["SetOrdinal"] == "4th" and j["TimeoutClock"] == "0:30" and j["HomeScore"] == "21"
    f = K.flat("Volleyball", c)
    assert f["home_sets"] == "1" and f["guest_sets"] == "2" and f["set"] == "4" and f["home_serve"] is True
    assert f["home_score"] == "21" and f["home_score_set1"] == "25" and f["possession"] == "H"


# --------------------------------------------------------------------------- Wrestling / WaterPolo / Futsal
def test_wrestling():
    c = {"EventId": "Wrestling", "ClockMinutesTens": " ", "ClockMinutesOnes": "1", "ClockSecondTens": "4",
         "ClockSecondOnes": "5", "ClockTenthsSecond": "2", "HomeMatchHundreds": " ", "HomeMatchTens": "1",
         "HomeMatchOnes": "2", "HomeScoreOnes": "3", "HomeMatchScoreTens": "1", "HomeMatchScoreOnes": "5",
         "GuestScoreOnes": "2", "WeightClass": "126", "AdvantageTimeMinutesOnes": "1",
         "AdvantageTimeSecondTens": "2", "AdvantageTimeSecondOnes": "5", "AdvantageHome": "*", "Period": "2",
         "InternalClockStatus": "R", "ClockMode": ":"}
    s = sb("Wrestling", c)
    assert s[0:2] == "12" and s[2:7] == " 1452" and s[8:11] == " 12" and s[11:13] == " 3"
    assert s[13:15] == "15" and s[15:17] == " 2" and s[19:22] == "126" and s[22:25] == "125"
    assert s[25] == "*" and s[26] == " " and s[29] == "2" and s[116] == "R" and s[117] == ":"
    j = js("Wrestling", c)
    assert j["AdvantageTime"] == "1:25" and j["HomeMatch"] == "12" and j["HomeMatchScore"] == "15"
    f = K.flat("Wrestling", c)
    assert f["weight_class"] == "126" and f["advantage_home"] is True and f["home_match_score"] == "15"


def test_waterpolo():
    c = {"EventId": "WaterPolo", "ClockMode": ":", "ClockMinutesTens": "0", "ClockMinutesOnes": "6",
         "ClockSecondTens": "1", "ClockSecondOnes": "2", "ClockTenthsSecond": "3", "ClockHundreths": "4",
         "ShotClockTens": "2", "ShotClockOnes": "5", "Period": "2", "GuestScoreOnes": "4",
         "HomeScoreTens": "1", "HomeScoreOnes": "0", "HomeTimeouts": "2", "GuestTimeouts": "1",
         "TimeoutMinutesOnes": "1", "TimeoutSecondsTens": "0", "TimeoutSecondsOnes": "0",
         "HomePenaltyPlayer1Tens": "0", "HomePenaltyPlayer1Ones": "9", "InternalClockStatus": "S"}
    j = js("WaterPolo", c)
    assert j["FullClock"] == "06:12.34" and j["Timeout"] == "1:00" and j["ShotClock"] == "25"
    s = sb("WaterPolo", c)
    assert s[0:2] == "24" and s[2:10] == "06:12.34" and s[10:12] == "25" and s[12] == "2"
    assert s[13:17] == "1:00" and s[17:19] == " 4" and s[19] == "1" and s[20:22] == "10" and s[22] == "2"
    assert s[23:31] == "HOME    " and s[31:39] == "GUEST   " and s[39:41] == "09" and s[116] == "S"
    f = K.flat("WaterPolo", c)
    assert f["shot_clock"] == "25" and f["home_penalties"] == 1 and f["home_timeouts"] == "2"


def test_futsal_handball():
    c = {"EventId": "Handball", "ClockMode": ":", "ClockMinutesTens": "2", "ClockMinutesOnes": "9",
         "ClockSecondTens": "5", "ClockSecondOnes": "9", "HomeScoreTens": "1", "HomeScoreOnes": "2",
         "GuestScoreOnes": "9", "HomeTimeOut": "1", "HomeFouls": "3", "Period": "2",
         "GuestPenaltyPlayer3Tens": "1", "GuestPenaltyPlayer3Ones": "1", "GuestPenaltyPlayer3ClockMinutesOnes": "2"}
    s = sb("FutsalHandball", c)
    assert s[0:2] == "30" and s[2:6] == "2959" and s[11:13] == "12" and s[13:15] == " 9"
    assert s[15] == "1" and s[17] == "3" and s[19] == "2" and s[21:29] == "HOME    "
    assert s[77:79] == "11" and s[80] == "2"
    f = K.flat("FutsalHandball", c)
    assert f["sport"] == "handball" and f["home_fouls"] == "3" and f["guest_penalties"] == 1


# --------------------------------------------------------------------------- Tennis / table tennis
def test_tennis():
    c = {"EventId": "Tennis", "ClockHourTens": "1", "ClockHourOnes": "4", "ClockMinutesTens": "0",
         "ClockMinutesOnes": "5", "Set": "2", "TopPoints": "40", "BottomPoints": "15", "TopSet1Ones": "6",
         "BottomSet1Ones": "4", "TopServe": "*", "Court": "1", "GameNumberOnes": "3",
         "TopPlayerName": "Federer", "BottomPlayerName": "Nadal", "Advantage": "T", "Set1TopTieBreak": "7",
         "TopSet2Tens": "1"}
    s = sb("Tennis", c)
    assert s[0:2] == "16" and s[2:6] == "1405" and s[6] == "2" and s[7:9] == "40" and s[9:11] == "15"
    assert s[11] == "6" and s[16] == "*" and s[18] == "4" and s[23] == "1" and s[24] == "3"
    assert s[30] == "T" and s[31:39] == "Federer " and s[39:47] == "Nadal   " and s[64:66] == " 7"
    assert s[87] == "1"
    j = js("Tennis", c)
    assert j["SetOrdinal"] == "2nd" and j["Clock"] == "41:05"  # hour digits are reversed in ScoreConnect's Clock
    f = K.flat("Tennis", c)
    assert f["home_score"] == "40" and f["home_name"] == "Federer" and f["home_serve"] is True
    # the original only flips Advantage on the source object, so the copy keeps it
    assert K.swap_teams("Tennis", c)["Advantage"] == "T"


def test_table_tennis():
    c = {"EventId": "TableTennis", "Set": "3", "HomePoints": "11", "GuestPoints": " 9", "HomeSetsWon": "2",
         "GuestSetsWon": "1", "HomeServe": "*", "HomePointsSet1": "11", "GuestPointsSet1": "7"}
    s = sb("TableTennisBadminton", c)
    assert s[0:2] == "31" and s[6] == "3" and s[7:9] == "11" and s[9:11] == " 9" and s[11] == "2"
    assert s[12] == "1" and s[13] == "*" and s[15:19] == "11 7"
    f = K.flat("TableTennisBadminton", c)
    assert f["home_sets"] == "2" and f["home_score"] == "11" and f["sport"] == "tabletennis"


# --------------------------------------------------------------------------- Drag racing / rodeo / timer / generic
def test_dragracing_both_layouts():
    c = {"EventId": "DragRacing", "ChannelNumber": "2", "CategoryName": "Pro Stock", "Round": "3",
         "LeftCarNumber": "42", "LeftDriver": "A. Driver", "RightDriver": "B. Racer", "LeftDialIn": "9.50",
         "LeftReactionTime": "0.012", "Win": "L", "Mov": "0.011", "IsDetailed": False}
    s = sb("DragRacing", c)
    assert s[0:2] == "20" and s[2] == "2" and s[3:11] == "Pro Stoc" and s[28:30] == "3 "
    assert s[30:34] == "42  " and s[38:47] == "A. Driver" and s[75:83] == "B. Racer"
    d = sb("DragRacing", dict(c, IsDetailed=True))
    assert d[3:8] == "9.50 " and d[8:14] == "0.012 " and d[115] == "L" and d[116:122] == "0.011 "
    assert js("DragRacing", c)["IsDetailed"] is False
    assert K.flat("DragRacing", c)["left_driver"] == "A. Driver"
    assert K.swap_teams("DragRacing", c)["RightDialIn"] == "9.50"


def test_rodeo():
    c = {"EventId": "Rodeo", "ClockMode": ".", "ClockMinutesTens": "0", "ClockMinutesOnes": "1",
         "ClockSecondTens": "2", "ClockSecondOnes": "3", "ClockTenthsSecond": "4", "ClockHundreths": "5",
         "ClockMilliSeconds": "6", "RiderNumber": "17", "RiderScore": "85.5", "Penalty": "P",
         "LeaderNumber": "9", "InternalClockStatus": "R"}
    s = sb("Rodeo", c)
    assert s[0:2] == "21" and s[2:9] == "0123456" and s[10:14] == "  17" and s[14:21] == "   85.5"
    assert s[22] == "P" and s[25:29] == "   9" and s[116] == "R" and s[117] == "."
    assert js("Rodeo", c)["Clock"] == "01:21.456"  # ScoreConnect repeats the minutes-ones digit for seconds ones


def test_timer_variants():
    c = {"EventId": "SingleTimer", "ClockMode": ":", "ClockMinutesTens": "1", "ClockMinutesOnes": "2",
         "ClockSecondTens": "3", "ClockSecondOnes": "4", "ClockTenthsSecond": "5", "ClockHundredths": "6",
         "InternalClockStatus": "R"}
    assert sb("Timer", c)[2:10] == "12:34.56" and js("Timer", c)["Clock"] == "12:34.56"
    assert sb("Timer", c)[116] == "R"
    c2 = {"ParseType": "OnlySecondsClock", "ClockSecondHundreds": "1", "ClockSecondTens": "2",
          "ClockSecondOnes": "3", "ClockTenthsSecond": "4", "ClockHundredths": "5", "ClockMilliseconds": "6"}
    assert js("Timer", c2)["Clock"] == "123.456" and sb("Timer", c2)[2:9] == "123.456"
    assert js("Timer", c2)["ParseType"] == 2
    lanes = {"ParseType": "Lanes", "Lane1ClockStatus": "R", "Lane1Id": "1", "Lane1Clock": "12.34",
             "Lane8ClockStatus": "S", "Lane8Id": "8", "Lane8Clock": "0.00"}
    s = sb("Timer", lanes)
    assert s[2] == "R" and s[3:6] == "  1" and s[6:15] == "    12.34" and s[93] == "S" and s[94:97] == "  8"
    assert s[97:106] == "     0.00"


def test_generic():
    c = {"EventId": "Generic", "TOTimerMinutesOnes": "1", "TOTimerSecondsTens": "2", "TOTimerSecondsOnes": "3",
         "ClockDigit1": "1", "ClockDigit2": "2", "ClockDigit3": "3", "ClockDigit4": "4", "HomeHundreds": "1",
         "HomeTens": "2", "HomeOnes": "3", "GuestOnes": "7", "Period": "2", "HomeFouls": "4",
         "HomeNumberOfTO": "2", "ClockMode": ":", "ClockRun": "R", "PlayClock": "24"}
    s = sb("Generic", c)
    assert s[0:2] == "28" and s[2:5] == "123" and s[5:9] == "1234" and s[9:12] == "123" and s[12:15] == "  7"
    assert s[15] == "2" and s[16] == "4" and s[18] == "2" and s[20] == ":" and s[21] == "R" and s[24:26] == "24"
    f = K.flat("Generic", c)
    assert f["clock"] == "12:34" and f["clock_running"] is True and f["home_score"] == "123"


# --------------------------------------------------------------------------- Swimming
def test_swimming_contracts():
    c = {"EventId": "Swimming", "ClockMode": ".", "ClockMinutesTens": "0", "ClockMinutesOnes": "1",
         "ClockSecondTens": "2", "ClockSecondOnes": "3", "ClockTenthsSecond": "4", "FinishFlag1": ".",
         "Split1": "2", "Place1": "1", "Clock1": "1:23.45"}
    s = sb("SwimmingDetail", c)
    assert s[0:2] == "13" and s[2:7] == "01234" and s[7] == "." and s[8:10] == " 2" and s[10] == "1"
    assert s[11:18] == "1:23.45" and s[117] == "."
    ev = {"EventId": "Swimming", "ClockMinutesOnes": "1", "ClockSecondTens": "2", "ClockSecondOnes": "3",
          "ClockTenthsSecond": "4", "ClockHundreths": "5", "EventName": "100 Free", "EventRecord": "49.99"}
    s = sb("SwimmingEvent", ev)
    assert s[2:10] == " 1:23.45" and s[10:46].strip() == "100 Free" and s[46:82].strip() == "49.99"
    assert s[10:46] == "100 Free".rjust(36)
    rows = {"EventId": "Swimming", "RowType": "Row4To6", "RowALane": "4", "RowASwimmerName": "J. Smith",
            "RowAClock": "23.45", "RowAPlace": "1"}
    j = js("SwimmingRows", rows)
    assert (j["RowANumber"], j["RowBNumber"], j["RowCNumber"], j["RowType"]) == (4, 5, 6, 1)
    s = sb("SwimmingRows", rows)
    assert s[10:12] == " 4" and s[12:28] == "        J. Smith" and s[32:40] == "   23.45" and s[40:42] == " 1"
    mixed = {"EventId": "Swimming", "PacketType": "Event", "SwimmingEvent": ev, "SwimmingRows": rows}
    assert sb("SwimmingMixed", mixed) == sb("SwimmingEvent", ev)
    assert sb("SwimmingMixed", dict(mixed, PacketType="Rows")) == sb("SwimmingRows", rows)
    mj = js("SwimmingMixed", mixed)
    assert mj["PacketType"] == 1 and mj["SwimmingEvent"]["EventName"] == "100 Free"
    assert K.flat("SwimmingMixed", mixed)["event_name"] == "100 Free"
    with pytest.raises(ValueError):
        sb("SwimmingMixed", {})


# --------------------------------------------------------------------------- clock status emulator
def test_emulator_main_clock():
    em = K.ClockStatusEmulator()
    c = {"ClockMode": ":", "ClockMinutesTens": "1", "ClockMinutesOnes": "0", "ClockSecondTens": "0",
         "ClockSecondOnes": "0"}
    em.apply(c, now=100.0)
    assert c["EmulatedClockStatus"] == "S"
    c["ClockSecondOnes"] = "9"
    c["ClockSecondTens"] = "5"
    c["ClockMinutesOnes"] = "9"
    em.apply(c, now=101.0)
    assert c["EmulatedClockStatus"] == "R" and K.flat("Football", c)["clock_running"] is True
    em.apply(c, now=102.0)  # unchanged for 1.0 s: still running
    assert c["EmulatedClockStatus"] == "R"
    em.apply(c, now=102.6)  # 1.6 s without change
    assert c["EmulatedClockStatus"] == "S"
    c["ClockSecondOnes"] = "8"
    em.apply(c, now=103.0)
    assert c["EmulatedClockStatus"] == "R"
    c["ClockMinutesTens"] = c["ClockMinutesOnes"] = c["ClockSecondTens"] = c["ClockSecondOnes"] = "0"
    em.apply(c, now=103.5)
    assert c["EmulatedClockStatus"] == "S"  # zero always stops


def test_emulator_tenths_mode_stops_after_150ms():
    em = K.ClockStatusEmulator()
    c = {"ClockMode": ".", "ClockSecondTens": "5", "ClockSecondOnes": "9", "ClockTenthsSecond": "8"}
    em.apply(c, now=1.0)
    c["ClockTenthsSecond"] = "7"
    em.apply(c, now=1.1)
    assert c["EmulatedClockStatus"] == "R"
    em.apply(c, now=1.2)
    assert c["EmulatedClockStatus"] == "R"
    em.apply(c, now=1.3)
    assert c["EmulatedClockStatus"] == "S"


def test_emulator_respects_internal_status_and_play_clock():
    em = K.ClockStatusEmulator("Football")
    c = {"InternalClockStatus": "S", "ClockMode": ":", "PlayClockTens": "2", "PlayClockOnes": "5"}
    em.apply(c, now=1.0)
    assert c["EmulatedClockStatus"] == "S" and c["EmulatedPlayClockStatus"] == "S"
    c["PlayClockOnes"] = "4"
    em.apply(c, now=2.0)
    assert c["EmulatedPlayClockStatus"] == "R"
    em.apply(c, now=3.0)
    assert c["EmulatedPlayClockStatus"] == "R"
    em.apply(c, now=3.6)
    assert c["EmulatedPlayClockStatus"] == "S"
    # the internal flag wins in the output
    assert js("Football", dict(c, InternalClockStatus="R", EmulatedClockStatus="S"))["ClockStatus"] == "R"
    assert js("Football", {"EmulatedClockStatus": "R"})["ClockStatus"] == "R"


# --------------------------------------------------------------------------- comparison with build_payloads
def _fb_game():
    d = dict(sport="football", clock="4:32", clock_running=True, play_clock="25", home_score="14",
             guest_score="7", period="2", period_ordinal="2nd", home_poss=True, guest_poss=False,
             home_timeouts="3", guest_timeouts="2", ball_on="35", down="3rd", to_go="7", possession="H",
             home_name="HOME", guest_name="GUEST")
    c = {"EventId": "Football", "ClockMode": ":", "ClockMinutesOnes": "4", "ClockSecondTens": "3",
         "ClockSecondOnes": "2", "InternalClockStatus": "R", "PlayClockTens": "2", "PlayClockOnes": "5",
         "HomeScoreTens": "1", "HomeScoreOnes": "4", "GuestScoreTens": " ", "GuestScoreOnes": "7", "Quarter": "2",
         "HomePossession": "<", "HomeTimeouts": "3", "GuestTimeouts": "2", "BallOnTens": "3", "BallOnOnes": "5",
         "Down": "3", "ToGoTens": " ", "ToGoOnes": "7"}
    return d, c


def _soccer_game():
    d = dict(sport="soccer", clock="45:09", clock_running=False, home_score="2", guest_score="1", period="1",
             period_ordinal="1st", home_shots="12", guest_shots="5", home_corners="4", guest_corners="3",
             horn=True, home_name="HOME", guest_name="GUEST")
    c = {"EventId": "Soccer", "ClockMode": ":", "ClockMinutesTens": "4", "ClockMinutesOnes": "5",
         "ClockSecondTens": "0", "ClockSecondOnes": "9", "InternalClockStatus": "S", "HomeScoreTens": " ",
         "HomeScoreOnes": "2", "GuestScoreTens": " ", "GuestScoreOnes": "1", "HomeShotTens": "1",
         "HomeShotOnes": "2", "GuestShotTens": " ", "GuestShotOnes": "5", "HomeCornerKicks": "4",
         "GuestCornerKicks": "3", "Period": "1", "Horn": "H"}
    return d, c


# differences that are expected and documented in docs/vendors/contracts.md
FOOTBALL_DIFFS = {"ClockTenthsSecond", "FullClock", "TimeStampFull", "TimeStampEpoch", "WeightedCoverage"}
SOCCER_DIFFS = {"ClockTenthsSecond", "TimeStampFull", "TimeStampEpoch", "WeightedCoverage"}


def _compare(contract, d, c):
    cfg = {"mqtt": {"bot_number": 5, "publish_rate": 10}}
    old_json, old_sb = sportzcast_mqtt.build_payloads(d, cfg, NOW)
    old = json.loads(old_json)
    new = js(contract, c)
    only_old = set(old) - set(new)
    only_new = set(new) - set(old)
    differ = {k for k in set(old) & set(new) if old[k] != new[k]}
    return old, new, only_old, only_new, differ, old_sb, sb(contract, c)


def test_football_matches_build_payloads():
    d, c = _fb_game()
    old, new, only_old, only_new, differ, old_sb, new_sb = _compare("Football", d, c)
    assert new_sb == old_sb
    assert only_new == set()
    assert only_old == {"Possession"}
    assert differ == FOOTBALL_DIFFS
    assert old["ClockTenthsSecond"] == "0" and new["ClockTenthsSecond"] == " "
    assert old["FullClock"] == " 4:32.0" and new["FullClock"] == "4:32.0"
    assert old["TimeStampEpoch"] == "1700000000" and new["TimeStampEpoch"] == "1700000000250"
    assert old["TimeStampFull"].endswith(".250Z") and new["TimeStampFull"].endswith(".2500000Z")
    assert old["WeightedCoverage"] == 1.0 and new["WeightedCoverage"] == pytest.approx(0.95)
    for k in ("HomeScore", "GuestScore", "ToGo", "BallOn", "PlayClock", "Clock", "QuarterOrdinal", "Down",
              "HomePossession", "ClockStatus", "EventId", "TimeStamp", "BotNumberHex", "HomeTeamName"):
        assert old[k] == new[k], k


def test_soccer_matches_build_payloads():
    d, c = _soccer_game()
    old, new, only_old, only_new, differ, old_sb, new_sb = _compare("Soccer", d, c)
    assert only_new == set() and only_old == set()
    # build_payloads leaves the corner string right-aligned in sbdata[19] and [47] the same way
    assert new_sb == old_sb
    assert differ == SOCCER_DIFFS
    for k in ("HomeScore", "GuestScore", "HomeShots", "GuestShots", "HomeCornerKicks", "GuestCornerKicks",
              "Period", "PeriodOrdinal", "Horn", "Clock", "ClockStatus", "EventId", "HomeTeamName"):
        assert old[k] == new[k], k
    assert new["WeightedCoverage"] == pytest.approx(0.82)
    assert old["WeightedCoverage"] == 1.0


def test_build_payloads_key_order_differs_only_in_clockmode_position():
    d, c = _fb_game()
    old, new, *_ = _compare("Football", d, c)
    order_old = [k for k in old if k in new]
    order_new = [k for k in new if k in old]
    assert sorted(order_old) == sorted(order_new)
    assert order_old.index("ClockMode") < order_old.index("VendorSportId")
    assert order_new.index("VendorSportId") < order_new.index("ClockMode")
