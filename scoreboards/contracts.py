"""Sportzcast contract layer: turns a decoder's contract dict into every output ScoreConnect III produces.

A *contract* is a plain dict keyed by the exact Sportzcast property names (``HomeScoreTens``,
``ClockMode``, ``InternalClockStatus`` ...). Single-character properties are one-character strings; a missing
key means ``" "`` for characters and ``""`` for strings. Decoders set ``EventId`` to the EventType *name*
("Football", "Softball" ...). Only the properties a board actually provides need to be present.

Public API::

    CONTRACTS                          contract class names
    ClockStatusEmulator().apply(c)     start/stop emulation for boards that send no run flag (stateful)
    sportzcast_json(contract, c, meta) the MQTT ``bot/<n>/json`` payload as a dict
    sbdata(contract, c, meta)          the 150-character ``bot/<n>/sbdata`` string
    flat(contract, c)                  snake_case fields plus friendly aliases for data.json / vMix / text files
    swap_teams(contract, c)            ScoreConnect's SwapTeamInformation, on a copy
    event_code(event_name)             sbdata characters 0-1

``meta`` keys: ``bot_number``, ``home_team_name``, ``guest_team_name``, ``publish_rate``, ``now`` (epoch
seconds), ``channel``, ``origin`` and optionally ``venue_name``, ``venue_id``, ``venue_genius_id``.

The tables below were written from the field lists and sbdata positions of the Windows ScoreConnect III
contracts (facts only); see docs/vendors/contracts.md for behaviours worth knowing.
"""
from __future__ import annotations

import datetime as _dt
import re
import time

__all__ = ["CONTRACTS", "ClockStatusEmulator", "sportzcast_json", "sbdata", "flat", "swap_teams", "event_code"]

# --------------------------------------------------------------------------- enums
EVENT_CODES = {
    "Baseball": 1, "Football": 2, "Basketball": 3, "Softball": 4, "Hockey": 5, "Volleyball": 6, "Lacrosse": 7,
    "Soccer": 8, "Wrestling": 12, "Swimming": 13, "Tennis": 16, "AutoDetect": 19, "DragRacing": 20, "Rodeo": 21,
    "Timing": 22, "WaterPolo": 24, "Timer": 25, "SingleTimer": 26, "SwissTiming": 27, "Generic": 28, "Futsal": 29,
    "Handball": 30, "TableTennis": 31, "Badminton": 32,
}
ORIGIN_NAMES = {0: "Unknown", 1: "Local", 2: "Cloud", 3: "Replay", 4: "Ingress", 5: "Local emulated"}
_ENUMS = {
    "ParseType": {"Lanes": 0, "FullClock": 1, "OnlySecondsClock": 2},
    "PacketType": {"Event": 1, "Rows": 2},
    "RowType": {"Row1To3": 0, "Row4To6": 1, "Row7To9": 2},
}
_DEFAULT_EVENT = {
    "Football": "Football", "Soccer": "Soccer", "Basketball": "Basketball", "BaseballSoftball": "Baseball",
    "HockeyLacrosse": "Hockey", "Volleyball": "Volleyball", "Wrestling": "Wrestling", "WaterPolo": "WaterPolo",
    "Tennis": "Tennis", "TableTennisBadminton": "TableTennis", "FutsalHandball": "Futsal",
    "DragRacing": "DragRacing", "Rodeo": "Rodeo", "Timer": "SingleTimer", "Generic": "Generic",
    "SwimmingDetail": "Swimming", "SwimmingEvent": "Swimming", "SwimmingRows": "Swimming",
    "SwimmingMixed": "Swimming",
}
_NET_EPOCH_TICKS = 621355968000000000

# --------------------------------------------------------------------------- per-contract tables
# props : declaration order. "Name" = char, "Name:s" string, ":i" int, ":b" bool, ":e" enum,
#         "Name=cat:A,B,'x" concatenation (a leading ' marks a literal, _ is a space), "=score:", "=nclock:",
#         "=ord:" (ToOrdinal of a char) or "=custom" (hand written below).
# sb    : sbdata operations in order. c:Name@i one char, e:Name@a-b right aligned, s:Name@a-b left aligned,
#         p:Name@i second-to-last character of a string (only if it has two), A+B joins values, K = the common clock block (digits, status at 116, mode 117, play clock 118).
# swap  : "A=B" means A takes B's value; swap_poss moves the '<' / '>' possession marker.
_SPECS = {
    "Football": dict(
        props=(
            "PlayClockTens PlayClockOnes HomeScoreTens HomeScoreOnes GuestScoreTens GuestScoreOnes ToGoTens "
            "ToGoOnes BallOnTens BallOnOnes PlayClock=cat:PlayClockTens,PlayClockOnes "
            "HomeScore=score:HomeScoreTens,HomeScoreOnes GuestScore=score:GuestScoreTens,GuestScoreOnes "
            "ToGo=cat:ToGoTens,ToGoOnes BallOn=cat:BallOnTens,BallOnOnes Flag Horn HomePossession "
            "GuestPossession HomeTimeouts GuestTimeouts Down Quarter QuarterOrdinal=ord:Quarter "
            "HomeYardsRushing:s HomeYardsPassing:s HomeTotalYards:s VisitorYardsRushing:s "
            "VisitorYardsPassing:s VisitorTotalYards:s HomeTotalFirstDowns:s VisitorTotalFirstDowns:s "
            "HomeScoreQuarter1:s HomeScoreQuarter2:s HomeScoreQuarter3:s HomeScoreQuarter4:s "
            "VisitorScoreQuarter1:s VisitorScoreQuarter2:s VisitorScoreQuarter3:s VisitorScoreQuarter4:s"
        ),
        sb=(
            "K e:PlayClock@8-9 c:Flag@10 e:HomeScoreTens+HomeScoreOnes@11-12 c:Horn@13 "
            "e:GuestScoreTens+GuestScoreOnes@14-15 c:HomePossession@16 c:GuestPossession@17 c:HomeTimeouts@18 "
            "c:GuestTimeouts@19 c:Down@20 e:ToGo@21-22 e:BallOn@23-24 c:Quarter@25 s:HomeTeamName@26-33 "
            "s:GuestTeamName@34-41 e:HomeYardsRushing@42-45 e:HomeYardsPassing@46-49 e:HomeTotalYards@50-53 "
            "e:VisitorYardsRushing@54-57 e:VisitorYardsPassing@58-61 e:VisitorTotalYards@62-65 "
            "e:HomeTotalFirstDowns@66-67 e:VisitorTotalFirstDowns@68-69 e:HomeScoreQuarter1@70-71 "
            "e:HomeScoreQuarter2@72-73 e:HomeScoreQuarter3@74-75 e:HomeScoreQuarter4@76-77 "
            "e:VisitorScoreQuarter1@78-79 e:VisitorScoreQuarter2@80-81 e:VisitorScoreQuarter3@82-83 "
            "e:VisitorScoreQuarter4@84-85"
        ),
        swap=(
            "HomeScoreTens=GuestScoreTens GuestScoreTens=HomeScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes GuestTimeouts=HomeTimeouts HomeTimeouts=GuestTimeouts "
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName VisitorYardsPassing=HomeYardsPassing "
            "HomeYardsPassing=VisitorYardsPassing VisitorYardsRushing=HomeYardsRushing "
            "HomeYardsRushing=VisitorYardsRushing VisitorTotalYards=HomeTotalYards "
            "HomeTotalYards=VisitorTotalYards VisitorTotalFirstDowns=HomeTotalFirstDowns "
            "HomeTotalFirstDowns=VisitorTotalFirstDowns VisitorScoreQuarter1=HomeScoreQuarter1 "
            "HomeScoreQuarter1=VisitorScoreQuarter1 VisitorScoreQuarter2=HomeScoreQuarter2 "
            "HomeScoreQuarter2=VisitorScoreQuarter2 VisitorScoreQuarter3=HomeScoreQuarter3 "
            "HomeScoreQuarter3=VisitorScoreQuarter3 VisitorScoreQuarter4=HomeScoreQuarter4 "
            "HomeScoreQuarter4=VisitorScoreQuarter4"
        ),
        swap_poss=True,
    ),
    "Soccer": dict(
        props=(
            "HomeScoreTens HomeScoreOnes GuestScoreTens GuestScoreOnes HomeShotTens HomeShotOnes "
            "GuestShotTens GuestShotOnes HomeScore=score:HomeScoreTens,HomeScoreOnes HomePossession "
            "GuestScore=score:GuestScoreTens,GuestScoreOnes GuestPossession "
            "HomeShots=cat:HomeShotTens,HomeShotOnes HomeCornerKicks:s "
            "GuestShots=cat:GuestShotTens,GuestShotOnes GuestCornerKicks:s HomeSaves:s GuestSaves:s "
            "HomeTimeouts GuestTimeouts Period PeriodOrdinal=ord:Period HomePenalties:s GuestPenalties:s Horn"
        ),
        sb=(
            "K e:HomeScoreTens+HomeScoreOnes@11-12 c:HomePossession@13 e:GuestScoreTens+GuestScoreOnes@14-15 "
            "c:GuestPossession@16 e:HomeShots@17-18 e:HomeCornerKicks@19-19 e:GuestShots@20-21 "
            "e:GuestCornerKicks@22-22 e:HomeSaves@23-24 e:GuestSaves@25-26 c:HomeTimeouts@27 "
            "c:GuestTimeouts@28 c:Period@29 c:Horn@30 s:HomeTeamName@31-38 s:GuestTeamName@39-46 "
            "e:HomePenalties@49-50 e:GuestPenalties@51-52 p:HomeCornerKicks@47 p:GuestCornerKicks@48"
        ),
        swap=(
            "GuestScoreTens=HomeScoreTens HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes GuestTimeouts=HomeTimeouts HomeTimeouts=GuestTimeouts "
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName GuestShotTens=HomeShotTens "
            "HomeShotTens=GuestShotTens GuestShotOnes=HomeShotOnes HomeShotOnes=GuestShotOnes "
            "GuestCornerKicks=HomeCornerKicks HomeCornerKicks=GuestCornerKicks GuestSaves=HomeSaves "
            "HomeSaves=GuestSaves GuestPenalties=HomePenalties HomePenalties=GuestPenalties"
        ),
        swap_poss=True,
    ),
    "Basketball": dict(
        props=(
            "ShotClockSecondTens ShotClockSecondOnes ShotClockTenthsSecond HomeScoreHundreds HomeScoreTens "
            "HomeScoreOnes GuestScoreHundreds GuestScoreTens GuestScoreOnes HomeFoulTens HomeFoulOnes "
            "GuestFoulTens GuestFoulOnes FoulPlayerTens FoulPlayerOnes TimeoutClockMinutesOnes "
            "TimeoutClockSecondTens TimeoutClockSecondOnes TimeoutClock=custom ShotClock=custom "
            "HomeScore=score:HomeScoreHundreds,HomeScoreTens,HomeScoreOnes "
            "GuestScore=score:GuestScoreHundreds,GuestScoreTens,GuestScoreOnes "
            "HomeFouls=cat:HomeFoulTens,HomeFoulOnes GuestFouls=cat:GuestFoulTens,GuestFoulOnes "
            "FoulPlayer=cat:FoulPlayerTens,FoulPlayerOnes HomeDoubleBonus GuestDoubleBonus HomePossession "
            "GuestPossession HomeTimeouts GuestTimeouts HomeBonus GuestBonus FoulPlayerNumberOfFouls "
            "Period=custom PeriodOrdinal=ord:Period Horn HomePlayer1:s HomePlayer1FoulNumber "
            "HomePlayer1Points:s HomePlayer2:s HomePlayer2FoulNumber HomePlayer2Points:s HomeFullTimeouts "
            "HomePartialTimeouts GuestFullTimeouts GuestPartialTimeouts HomePlayer3:s HomePlayer3FoulNumber "
            "HomePlayer3Points:s HomePlayer4:s HomePlayer4FoulNumber HomePlayer4Points:s HomePlayer5:s "
            "HomePlayer5FoulNumber HomePlayer5Points:s HomeBottomCenter GuestPlayer1:s GuestPlayer1FoulNumber "
            "GuestPlayer1Points:s GuestPlayer2:s GuestPlayer2FoulNumber GuestPlayer2Points:s GuestPlayer3:s "
            "GuestPlayer3FoulNumber GuestPlayer3Points:s GuestPlayer4:s GuestPlayer4FoulNumber "
            "GuestPlayer4Points:s GuestPlayer5:s GuestPlayer5FoulNumber GuestPlayer5Points:s"
        ),
        sb=(
            "K c:HomeDoubleBonus@6 c:GuestDoubleBonus@7 c:ShotClockSecondTens@8 c:ShotClockSecondOnes@9 "
            "e:HomeScoreHundreds+HomeScoreTens+HomeScoreOnes@10-12 "
            "e:GuestScoreHundreds+GuestScoreTens+GuestScoreOnes@13-15 c:HomePossession@16 "
            "c:GuestPossession@17 c:HomeTimeouts@18 c:GuestTimeouts@19 c:HomeBonus@20 c:GuestBonus@21 "
            "e:HomeFouls@22-23 e:GuestFouls@24-25 e:FoulPlayer@26-27 c:FoulPlayerNumberOfFouls@28 c:Period@29 "
            "c:Horn@30 s:HomeTeamName@31-38 s:GuestTeamName@39-46 e:HomePlayer1@47-48 "
            "c:HomePlayer1FoulNumber@49 e:HomePlayer1Points@50-51 e:HomePlayer2@52-53 "
            "c:HomePlayer2FoulNumber@54 e:HomePlayer2Points@55-56 c:HomeFullTimeouts@60 "
            "c:HomePartialTimeouts@62 c:GuestFullTimeouts@64 c:GuestPartialTimeouts@66 e:HomePlayer3@67-68 "
            "c:HomePlayer3FoulNumber@69 e:HomePlayer3Points@70-71 e:HomePlayer4@72-73 "
            "c:HomePlayer4FoulNumber@74 e:HomePlayer4Points@75-76 e:HomePlayer5@77-78 "
            "c:HomePlayer5FoulNumber@79 e:HomePlayer5Points@80-81 c:HomeBottomCenter@82 e:GuestPlayer1@83-84 "
            "c:GuestPlayer1FoulNumber@85 e:GuestPlayer1Points@86-87 e:GuestPlayer2@88-89 "
            "c:GuestPlayer2FoulNumber@90 e:GuestPlayer2Points@91-92 e:GuestPlayer3@93-94 "
            "c:GuestPlayer3FoulNumber@95 e:GuestPlayer3Points@96-97 s:TimeoutClock@112-115 "
            "e:GuestPlayer4@121-122 c:GuestPlayer4FoulNumber@123 e:GuestPlayer4Points@124-125 "
            "e:GuestPlayer5@126-127 c:GuestPlayer5FoulNumber@128 e:GuestPlayer5Points@129-130"
        ),
        swap=(
            "GuestDoubleBonus=HomeDoubleBonus HomeDoubleBonus=GuestDoubleBonus GuestScoreTens=HomeScoreTens "
            "HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes HomeScoreOnes=GuestScoreOnes "
            "GuestTimeouts=HomeTimeouts HomeTimeouts=GuestTimeouts GuestBonus=HomeBonus HomeBonus=GuestBonus "
            "GuestFoulTens=HomeFoulTens HomeFoulTens=GuestFoulTens GuestFoulOnes=HomeFoulOnes "
            "HomeFoulOnes=GuestFoulOnes GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName "
            "GuestPlayer1=HomePlayer1 HomePlayer1=GuestPlayer1 GuestPlayer1FoulNumber=HomePlayer1FoulNumber "
            "HomePlayer1FoulNumber=GuestPlayer1FoulNumber GuestPlayer1Points=HomePlayer1Points "
            "HomePlayer1Points=GuestPlayer1Points GuestPlayer2=HomePlayer2 HomePlayer2=GuestPlayer2 "
            "GuestPlayer2FoulNumber=HomePlayer2FoulNumber HomePlayer2FoulNumber=GuestPlayer2FoulNumber "
            "GuestPlayer2Points=HomePlayer2Points HomePlayer2Points=GuestPlayer2Points "
            "GuestPlayer3=HomePlayer3 HomePlayer3=GuestPlayer3 GuestPlayer3FoulNumber=HomePlayer3FoulNumber "
            "HomePlayer3FoulNumber=GuestPlayer3FoulNumber GuestPlayer3Points=HomePlayer3Points "
            "HomePlayer3Points=GuestPlayer3Points GuestPlayer4=HomePlayer4 HomePlayer4=GuestPlayer4 "
            "GuestPlayer4FoulNumber=HomePlayer4FoulNumber HomePlayer4FoulNumber=GuestPlayer4FoulNumber "
            "GuestPlayer4Points=HomePlayer4Points HomePlayer4Points=GuestPlayer4Points "
            "GuestPlayer5=HomePlayer5 HomePlayer5=GuestPlayer5 GuestPlayer5FoulNumber=HomePlayer5FoulNumber "
            "HomePlayer5FoulNumber=GuestPlayer5FoulNumber GuestPlayer5Points=HomePlayer5Points "
            "HomePlayer5Points=GuestPlayer5Points GuestFullTimeouts=HomeFullTimeouts "
            "HomeFullTimeouts=GuestFullTimeouts GuestPartialTimeouts=HomePartialTimeouts "
            "HomePartialTimeouts=GuestPartialTimeouts"
        ),
        swap_poss=True,
    ),
    "BaseballSoftball": dict(
        props=(
            "GuestRunTens GuestRunOnes GuestHitsTens GuestHitsOnes HomeRunTens HomeRunOnes HomeHitsTens "
            "HomeHitsOnes AtBatTens AtBatOnes InningTens InningOnes PitchClockMinutesTens "
            "PitchClockMinutesOnes PitchClockSecondTens PitchClockSecondOnes Balls Strikes Outs "
            "Inning=cat:InningTens,InningOnes InningOrdinal=custom GuestRuns=score:GuestRunTens,GuestRunOnes "
            "HomeRuns=score:HomeRunTens,HomeRunOnes TopBottomInning GuestHits=cat:GuestHitsTens,GuestHitsOnes "
            "HomeHits=cat:HomeHitsTens,HomeHitsOnes GuestErrors HomeErrors AtBat=cat:AtBatTens,AtBatOnes "
            "ErrorFlag GuestErrorNumber TopOfInning BottomOfInning GuestInning1 HomeInning1 GuestInning2 "
            "HomeInning2 GuestInning3 HomeInning3 GuestInning4 HomeInning4 GuestInning5 HomeInning5 "
            "GuestInning6 HomeInning6 GuestInning7 HomeInning7 GuestInning8 HomeInning8 GuestInning9 "
            "HomeInning9 GuestInning10 HomeInning10 OnFirst OnSecond OnThird PitchSpeed:s PitchCount:s "
            "PitchClock=nclock:PitchClockMinutesTens,PitchClockMinutesOnes,PitchClockSecondTens,PitchClockSecondOnes"
        ),
        sb=(
            "K c:Balls@6 c:Strikes@7 c:Outs@8 e:Inning@9-10 e:GuestRunTens+GuestRunOnes@11-12 "
            "e:HomeRunTens+HomeRunOnes@13-14 c:TopBottomInning@15 e:GuestHits@16-17 e:HomeHits@18-19 "
            "c:GuestErrors@20 c:HomeErrors@21 e:AtBat@22-23 c:ErrorFlag@24 c:GuestErrorNumber@25 "
            "c:TopOfInning@26 c:BottomOfInning@27 c:GuestInning1@30 c:HomeInning1@31 c:GuestInning2@32 "
            "c:HomeInning2@33 c:GuestInning3@34 c:HomeInning3@35 c:GuestInning4@36 c:HomeInning4@37 "
            "c:GuestInning5@38 c:HomeInning5@39 c:GuestInning6@40 c:HomeInning6@41 c:GuestInning7@42 "
            "c:HomeInning7@43 c:GuestInning8@44 c:HomeInning8@45 c:GuestInning9@46 c:HomeInning9@47 "
            "c:GuestInning10@48 c:HomeInning10@49 s:GuestTeamName@50-57 s:HomeTeamName@58-65 c:OnFirst@66 "
            "c:OnSecond@67 c:OnThird@68 e:PitchSpeed@69-71 e:PitchCount@72-74 c:PitchClockMinutesTens@75 "
            "c:PitchClockMinutesOnes@76 c:PitchClockSecondTens@77 c:PitchClockSecondOnes@78"
        ),
        swap=(
            "GuestRunTens=HomeRunTens HomeRunTens=GuestRunTens GuestRunOnes=HomeRunOnes "
            "HomeRunOnes=GuestRunOnes GuestHitsTens=HomeHitsTens HomeHitsTens=GuestHitsTens "
            "GuestHitsOnes=HomeHitsOnes HomeHitsOnes=GuestHitsOnes GuestErrors=HomeErrors "
            "HomeErrors=GuestErrors GuestInning1=HomeInning1 HomeInning1=GuestInning1 "
            "GuestInning2=HomeInning2 HomeInning2=GuestInning2 GuestInning3=HomeInning3 "
            "HomeInning3=GuestInning3 GuestInning4=HomeInning4 HomeInning4=GuestInning4 "
            "GuestInning5=HomeInning5 HomeInning5=GuestInning5 GuestInning6=HomeInning6 "
            "HomeInning6=GuestInning6 GuestInning7=HomeInning7 HomeInning7=GuestInning7 "
            "GuestInning8=HomeInning8 HomeInning8=GuestInning8 GuestInning9=HomeInning9 "
            "HomeInning9=GuestInning9 GuestInning10=HomeInning10 HomeInning10=GuestInning10 "
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName"
        ),
    ),
    "HockeyLacrosse": dict(
        props=(
            "HomeScoreTens HomeScoreOnes GuestScoreTens GuestScoreOnes HomePenaltyPlayer1Tens "
            "HomePenaltyPlayer1Ones HomePenaltyPlayer1ClockMinutesTens HomePenaltyPlayer1ClockMinutesOnes "
            "HomePenaltyPlayer1ClockSecondTens HomePenaltyPlayer1ClockSecondOnes HomePenaltyPlayer2Tens "
            "HomePenaltyPlayer2Ones HomePenaltyPlayer2ClockMinutesTens HomePenaltyPlayer2ClockMinutesOnes "
            "HomePenaltyPlayer2ClockSecondTens HomePenaltyPlayer2ClockSecondOnes HomePenaltyPlayer3Tens "
            "HomePenaltyPlayer3Ones HomePenaltyPlayer3ClockMinutesTens HomePenaltyPlayer3ClockMinutesOnes "
            "HomePenaltyPlayer3ClockSecondTens HomePenaltyPlayer3ClockSecondOnes GuestPenaltyPlayer1Tens "
            "GuestPenaltyPlayer1Ones GuestPenaltyPlayer1ClockMinutesTens GuestPenaltyPlayer1ClockMinutesOnes "
            "GuestPenaltyPlayer1ClockSecondTens GuestPenaltyPlayer1ClockSecondOnes GuestPenaltyPlayer2Tens "
            "GuestPenaltyPlayer2Ones GuestPenaltyPlayer2ClockMinutesTens GuestPenaltyPlayer2ClockMinutesOnes "
            "GuestPenaltyPlayer2ClockSecondTens GuestPenaltyPlayer2ClockSecondOnes GuestPenaltyPlayer3Tens "
            "GuestPenaltyPlayer3Ones GuestPenaltyPlayer3ClockMinutesTens GuestPenaltyPlayer3ClockMinutesOnes "
            "GuestPenaltyPlayer3ClockSecondTens GuestPenaltyPlayer3ClockSecondOnes HomeShotOnGoalTens "
            "HomeShotOnGoalOnes GuestShotOnGoalTens GuestShotOnGoalOnes ShotClockTens ShotClockOnes "
            "ShotClockTenthsSecond ShotClock=custom HomeScore=score:HomeScoreTens,HomeScoreOnes HomeGoal "
            "GuestScore=score:GuestScoreTens,GuestScoreOnes GuestGoal HomeTimeOut GuestTimeOut "
            "HomePlayerPopUp:s GuestPlayerPopUp:s HomeShotsOnGoal=cat:HomeShotOnGoalTens,HomeShotOnGoalOnes "
            "GuestShotsOnGoal=cat:GuestShotOnGoalTens,GuestShotOnGoalOnes Period PeriodOrdinal=ord:Period "
            "Horn HomePenaltyPlayer1=cat:HomePenaltyPlayer1Tens,HomePenaltyPlayer1Ones "
            "HomePenaltyPlayer1Clock=nclock:HomePenaltyPlayer1ClockMinutesTens,HomePenaltyPlayer1ClockMinutesOnes,HomePenaltyPlayer1ClockSecondTens,HomePenaltyPlayer1ClockSecondOnes "
            "HomePenaltyPlayer2=cat:HomePenaltyPlayer2Tens,HomePenaltyPlayer2Ones "
            "HomePenaltyPlayer2Clock=nclock:HomePenaltyPlayer2ClockMinutesTens,HomePenaltyPlayer2ClockMinutesOnes,HomePenaltyPlayer2ClockSecondTens,HomePenaltyPlayer2ClockSecondOnes "
            "HomePenaltyPlayer3=cat:HomePenaltyPlayer3Tens,HomePenaltyPlayer3Ones "
            "HomePenaltyPlayer3Clock=nclock:HomePenaltyPlayer3ClockMinutesTens,HomePenaltyPlayer3ClockMinutesOnes,HomePenaltyPlayer3ClockSecondTens,HomePenaltyPlayer3ClockSecondOnes "
            "GuestPenaltyPlayer1=cat:GuestPenaltyPlayer1Tens,GuestPenaltyPlayer1Ones "
            "GuestPenaltyPlayer1Clock=nclock:GuestPenaltyPlayer1ClockMinutesTens,GuestPenaltyPlayer1ClockMinutesOnes,GuestPenaltyPlayer1ClockSecondTens,GuestPenaltyPlayer1ClockSecondOnes "
            "GuestPenaltyPlayer2=cat:GuestPenaltyPlayer2Tens,GuestPenaltyPlayer2Ones "
            "GuestPenaltyPlayer2Clock=nclock:GuestPenaltyPlayer2ClockMinutesTens,GuestPenaltyPlayer2ClockMinutesOnes,GuestPenaltyPlayer2ClockSecondTens,GuestPenaltyPlayer2ClockSecondOnes "
            "GuestPenaltyPlayer3=cat:GuestPenaltyPlayer3Tens,GuestPenaltyPlayer3Ones "
            "GuestPenaltyPlayer3Clock=nclock:GuestPenaltyPlayer3ClockMinutesTens,GuestPenaltyPlayer3ClockMinutesOnes,GuestPenaltyPlayer3ClockSecondTens,GuestPenaltyPlayer3ClockSecondOnes "
            "HomeFullTimeoutsRemaining GuestFullTimeoutsRemaining HomePartialTimeoutsRemaining "
            "GuestPartialTimeoutsRemaining HomeSaves:s GuestSaves:s HomePossession GuestPossession "
            "HomePlayer1PenaltyType1 HomePlayer1PenaltyType2 HomePlayer2PenaltyType1 HomePlayer2PenaltyType2 "
            "HomePlayer3PenaltyType1 HomePlayer3PenaltyType2 GuestPlayer1PenaltyType1 "
            "GuestPlayer1PenaltyType2 GuestPlayer2PenaltyType1 GuestPlayer2PenaltyType2 "
            "GuestPlayer3PenaltyType1 GuestPlayer3PenaltyType2"
        ),
        sb=(
            "K c:ShotClockTens@8 c:ShotClockOnes@9 e:HomeScoreTens+HomeScoreOnes@11-12 c:HomeGoal@13 "
            "e:GuestScoreTens+GuestScoreOnes@14-15 c:GuestGoal@16 c:HomeTimeOut@18 c:GuestTimeOut@19 "
            "e:HomePlayerPopUp@20-21 e:GuestPlayerPopUp@22-23 e:HomeShotsOnGoal@24-25 "
            "e:GuestShotsOnGoal@26-27 c:Period@29 c:Horn@30 s:HomeTeamName@31-38 s:GuestTeamName@39-46 "
            "e:HomePenaltyPlayer1@47-48 c:HomePenaltyPlayer1ClockMinutesTens@49 "
            "c:HomePenaltyPlayer1ClockMinutesOnes@50 c:HomePenaltyPlayer1ClockSecondTens@51 "
            "c:HomePenaltyPlayer1ClockSecondOnes@52 e:HomePenaltyPlayer2@53-54 "
            "c:HomePenaltyPlayer2ClockMinutesTens@55 c:HomePenaltyPlayer2ClockMinutesOnes@56 "
            "c:HomePenaltyPlayer2ClockSecondTens@57 c:HomePenaltyPlayer2ClockSecondOnes@58 "
            "e:HomePenaltyPlayer3@59-60 c:HomePenaltyPlayer3ClockMinutesTens@61 "
            "c:HomePenaltyPlayer3ClockMinutesOnes@62 c:HomePenaltyPlayer3ClockSecondTens@63 "
            "c:HomePenaltyPlayer3ClockSecondOnes@64 e:GuestPenaltyPlayer1@65-66 "
            "c:GuestPenaltyPlayer1ClockMinutesTens@67 c:GuestPenaltyPlayer1ClockMinutesOnes@68 "
            "c:GuestPenaltyPlayer1ClockSecondTens@69 c:GuestPenaltyPlayer1ClockSecondOnes@70 "
            "e:GuestPenaltyPlayer2@71-72 c:GuestPenaltyPlayer2ClockMinutesTens@73 "
            "c:GuestPenaltyPlayer2ClockMinutesOnes@74 c:GuestPenaltyPlayer2ClockSecondTens@75 "
            "c:GuestPenaltyPlayer2ClockSecondOnes@76 e:GuestPenaltyPlayer3@77-78 "
            "c:GuestPenaltyPlayer3ClockMinutesTens@79 c:GuestPenaltyPlayer3ClockMinutesOnes@80 "
            "c:GuestPenaltyPlayer3ClockSecondTens@81 c:GuestPenaltyPlayer3ClockSecondOnes@82 "
            "c:HomeFullTimeoutsRemaining@83 c:GuestFullTimeoutsRemaining@84 c:HomePartialTimeoutsRemaining@85 "
            "c:GuestPartialTimeoutsRemaining@86 e:HomeSaves@87-88 e:GuestSaves@89-90 c:HomePossession@91 "
            "c:GuestPossession@92 c:HomePlayer1PenaltyType1@119 c:HomePlayer1PenaltyType2@120 "
            "c:HomePlayer2PenaltyType1@121 c:HomePlayer2PenaltyType2@122 c:HomePlayer3PenaltyType1@123 "
            "c:HomePlayer3PenaltyType2@124 c:GuestPlayer1PenaltyType1@125 c:GuestPlayer1PenaltyType2@126 "
            "c:GuestPlayer2PenaltyType1@127 c:GuestPlayer2PenaltyType2@128 c:GuestPlayer3PenaltyType1@129 "
            "c:GuestPlayer3PenaltyType2@130"
        ),
        swap=(
            "GuestScoreTens=HomeScoreTens HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes GuestGoal=HomeGoal HomeGoal=GuestGoal GuestTimeOut=HomeTimeOut "
            "HomeTimeOut=GuestTimeOut GuestPlayerPopUp=HomePlayerPopUp HomePlayerPopUp=GuestPlayerPopUp "
            "GuestShotOnGoalTens=HomeShotOnGoalTens HomeShotOnGoalTens=GuestShotOnGoalTens "
            "GuestShotOnGoalOnes=HomeShotOnGoalOnes HomeShotOnGoalOnes=GuestShotOnGoalOnes "
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName "
            "GuestPenaltyPlayer1Tens=HomePenaltyPlayer1Tens HomePenaltyPlayer1Tens=GuestPenaltyPlayer1Tens "
            "GuestPenaltyPlayer1Ones=HomePenaltyPlayer1Ones HomePenaltyPlayer1Ones=GuestPenaltyPlayer1Ones "
            "GuestPenaltyPlayer1ClockMinutesTens=HomePenaltyPlayer1ClockMinutesTens "
            "HomePenaltyPlayer1ClockMinutesTens=GuestPenaltyPlayer1ClockMinutesTens "
            "GuestPenaltyPlayer1ClockMinutesOnes=HomePenaltyPlayer1ClockMinutesOnes "
            "HomePenaltyPlayer1ClockMinutesOnes=GuestPenaltyPlayer1ClockMinutesOnes "
            "GuestPenaltyPlayer1ClockSecondTens=HomePenaltyPlayer1ClockSecondTens "
            "HomePenaltyPlayer1ClockSecondTens=GuestPenaltyPlayer1ClockSecondTens "
            "GuestPenaltyPlayer1ClockSecondOnes=HomePenaltyPlayer1ClockSecondOnes "
            "HomePenaltyPlayer1ClockSecondOnes=GuestPenaltyPlayer1ClockSecondOnes "
            "GuestPenaltyPlayer2Tens=HomePenaltyPlayer2Tens HomePenaltyPlayer2Tens=GuestPenaltyPlayer2Tens "
            "GuestPenaltyPlayer2Ones=HomePenaltyPlayer2Ones HomePenaltyPlayer2Ones=GuestPenaltyPlayer2Ones "
            "GuestPenaltyPlayer2ClockMinutesTens=HomePenaltyPlayer2ClockMinutesTens "
            "HomePenaltyPlayer2ClockMinutesTens=GuestPenaltyPlayer2ClockMinutesTens "
            "GuestPenaltyPlayer2ClockMinutesOnes=HomePenaltyPlayer2ClockMinutesOnes "
            "HomePenaltyPlayer2ClockMinutesOnes=GuestPenaltyPlayer2ClockMinutesOnes "
            "GuestPenaltyPlayer2ClockSecondTens=HomePenaltyPlayer2ClockSecondTens "
            "HomePenaltyPlayer2ClockSecondTens=GuestPenaltyPlayer2ClockSecondTens "
            "GuestPenaltyPlayer2ClockSecondOnes=HomePenaltyPlayer2ClockSecondOnes "
            "HomePenaltyPlayer2ClockSecondOnes=GuestPenaltyPlayer2ClockSecondOnes "
            "GuestPenaltyPlayer3Tens=HomePenaltyPlayer3Tens HomePenaltyPlayer3Tens=GuestPenaltyPlayer3Tens "
            "GuestPenaltyPlayer3Ones=HomePenaltyPlayer3Ones HomePenaltyPlayer3Ones=GuestPenaltyPlayer3Ones "
            "GuestPenaltyPlayer3ClockMinutesTens=HomePenaltyPlayer3ClockMinutesTens "
            "HomePenaltyPlayer3ClockMinutesTens=GuestPenaltyPlayer3ClockMinutesTens "
            "GuestPenaltyPlayer3ClockMinutesOnes=HomePenaltyPlayer3ClockMinutesOnes "
            "HomePenaltyPlayer3ClockMinutesOnes=GuestPenaltyPlayer3ClockMinutesOnes "
            "GuestPenaltyPlayer3ClockSecondTens=HomePenaltyPlayer3ClockSecondTens "
            "HomePenaltyPlayer3ClockSecondTens=GuestPenaltyPlayer3ClockSecondTens "
            "GuestPenaltyPlayer3ClockSecondOnes=HomePenaltyPlayer3ClockSecondOnes "
            "HomePenaltyPlayer3ClockSecondOnes=GuestPenaltyPlayer3ClockSecondOnes "
            "GuestFullTimeoutsRemaining=HomeFullTimeoutsRemaining "
            "HomeFullTimeoutsRemaining=GuestFullTimeoutsRemaining "
            "GuestPartialTimeoutsRemaining=HomePartialTimeoutsRemaining "
            "HomePartialTimeoutsRemaining=GuestPartialTimeoutsRemaining GuestSaves=HomeSaves "
            "HomeSaves=GuestSaves GuestPlayer1PenaltyType1=HomePlayer1PenaltyType1 "
            "HomePlayer1PenaltyType1=GuestPlayer1PenaltyType1 "
            "GuestPlayer1PenaltyType2=HomePlayer1PenaltyType2 "
            "HomePlayer1PenaltyType2=GuestPlayer1PenaltyType2 "
            "GuestPlayer2PenaltyType1=HomePlayer2PenaltyType1 "
            "HomePlayer2PenaltyType1=GuestPlayer2PenaltyType1 "
            "GuestPlayer2PenaltyType2=HomePlayer2PenaltyType2 "
            "HomePlayer2PenaltyType2=GuestPlayer2PenaltyType2 "
            "GuestPlayer3PenaltyType1=HomePlayer3PenaltyType1 "
            "HomePlayer3PenaltyType1=GuestPlayer3PenaltyType1 "
            "GuestPlayer3PenaltyType2=HomePlayer3PenaltyType2 "
            "HomePlayer3PenaltyType2=GuestPlayer3PenaltyType2"
        ),
        swap_poss=True,
    ),
    "Volleyball": dict(
        props=(
            "HomeScoreTens HomeScoreOnes GuestScoreTens GuestScoreOnes HomeGamesWon "
            "HomeScore=score:HomeScoreTens,HomeScoreOnes GuestGamesWon "
            "GuestScore=score:GuestScoreTens,GuestScoreOnes HomeServe GuestServe HomeTimeout GuestTimeout "
            "HomeScoreSet1:s GuestScoreSet1:s HomeScoreSet2:s GuestScoreSet2:s HomeScoreSet3:s "
            "GuestScoreSet3:s HomeScoreSet4:s GuestScoreSet4:s HomePlayer1:s HomePlayer1Kills "
            "HomePlayer1Digs:s HomePlayer2:s HomePlayer2Kills HomePlayer2Digs:s HomePlayer3:s "
            "HomePlayer3Kills HomePlayer3Digs:s HomePlayer4:s HomePlayer4Kills HomePlayer4Digs:s "
            "HomePlayer5:s HomePlayer5Kills HomePlayer5Digs:s HomePlayer6:s HomePlayer6Kills "
            "HomePlayer6Digs:s GuestPlayer1:s GuestPlayer1Kills GuestPlayer1Digs:s GuestPlayer2:s "
            "GuestPlayer2Kills GuestPlayer2Digs:s GuestPlayer3:s GuestPlayer3Kills GuestPlayer3Digs:s "
            "GuestPlayer4:s GuestPlayer4Kills GuestPlayer4Digs:s HomeScoreSet5:s GuestScoreSet5:s IsSet3 Set "
            "SetOrdinal=ord:Set Game GuestPlayer5:s GuestPlayer5Kills GuestPlayer5Digs:s GuestPlayer6:s "
            "GuestPlayer6Kills GuestPlayer6Digs:s TimeoutClockMinutesOnes TimeoutClockSecondTens "
            "TimeoutClockSecondOnes TimeoutClock=custom"
        ),
        sb=(
            "K c:HomeGamesWon@6 e:HomeScoreTens+HomeScoreOnes@7-8 c:GuestGamesWon@9 "
            "e:GuestScoreTens+GuestScoreOnes@10-11 c:HomeServe@12 c:GuestServe@13 c:HomeTimeout@14 "
            "c:GuestTimeout@15 e:HomeScoreSet1@16-17 e:GuestScoreSet1@18-19 e:HomeScoreSet2@20-21 "
            "e:GuestScoreSet2@22-23 e:HomeScoreSet3@24-25 e:GuestScoreSet3@26-27 e:HomeScoreSet4@28-29 "
            "e:GuestScoreSet4@30-31 s:HomeTeamName@32-39 s:GuestTeamName@40-47 e:HomePlayer1@48-49 "
            "c:HomePlayer1Kills@50 e:HomePlayer1Digs@51-52 e:HomePlayer2@53-54 c:HomePlayer2Kills@55 "
            "e:HomePlayer2Digs@56-57 e:HomePlayer3@58-59 c:HomePlayer3Kills@60 e:HomePlayer3Digs@61-62 "
            "e:HomePlayer4@63-64 c:HomePlayer4Kills@65 e:HomePlayer4Digs@66-67 e:HomePlayer5@68-69 "
            "c:HomePlayer5Kills@70 e:HomePlayer5Digs@71-72 e:HomePlayer6@73-74 c:HomePlayer6Kills@75 "
            "e:HomePlayer6Digs@76-77 e:GuestPlayer1@78-79 c:GuestPlayer1Kills@80 e:GuestPlayer1Digs@81-82 "
            "e:GuestPlayer2@83-84 c:GuestPlayer2Kills@85 e:GuestPlayer2Digs@86-87 e:GuestPlayer3@88-89 "
            "c:GuestPlayer3Kills@90 e:GuestPlayer3Digs@91-92 e:GuestPlayer4@93-94 c:GuestPlayer4Kills@95 "
            "e:GuestPlayer4Digs@96-97 e:HomeScoreSet5@102-103 e:GuestScoreSet5@104-105 c:IsSet3@106 "
            "c:TimeoutClockMinutesOnes@107 c:TimeoutClockSecondTens@108 c:TimeoutClockSecondOnes@109 "
            "c:Set@119 c:Game@120 e:GuestPlayer5@121-122 c:GuestPlayer5Kills@123 e:GuestPlayer5Digs@124-125 "
            "e:GuestPlayer6@126-127 c:GuestPlayer6Kills@128 e:GuestPlayer6Digs@129-130"
        ),
        swap=(
            "GuestScoreTens=HomeScoreTens HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes GuestGamesWon=HomeGamesWon HomeGamesWon=GuestGamesWon "
            "GuestServe=HomeServe HomeServe=GuestServe GuestTimeout=HomeTimeout HomeTimeout=GuestTimeout "
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName GuestScoreSet1=HomeScoreSet1 "
            "HomeScoreSet1=GuestScoreSet1 GuestScoreSet2=HomeScoreSet2 HomeScoreSet2=GuestScoreSet2 "
            "GuestScoreSet3=HomeScoreSet3 HomeScoreSet3=GuestScoreSet3 GuestScoreSet4=HomeScoreSet4 "
            "HomeScoreSet4=GuestScoreSet4 GuestScoreSet5=HomeScoreSet5 HomeScoreSet5=GuestScoreSet5 "
            "GuestPlayer1=HomePlayer1 HomePlayer1=GuestPlayer1 GuestPlayer1Digs=HomePlayer1Digs "
            "HomePlayer1Digs=GuestPlayer1Digs GuestPlayer1Kills=HomePlayer1Kills "
            "HomePlayer1Kills=GuestPlayer1Kills GuestPlayer2=HomePlayer2 HomePlayer2=GuestPlayer2 "
            "GuestPlayer2Digs=HomePlayer2Digs HomePlayer2Digs=GuestPlayer2Digs "
            "GuestPlayer2Kills=HomePlayer2Kills HomePlayer2Kills=GuestPlayer2Kills GuestPlayer3=HomePlayer3 "
            "HomePlayer3=GuestPlayer3 GuestPlayer3Digs=HomePlayer3Digs HomePlayer3Digs=GuestPlayer3Digs "
            "GuestPlayer3Kills=HomePlayer3Kills HomePlayer3Kills=GuestPlayer3Kills GuestPlayer4=HomePlayer4 "
            "HomePlayer4=GuestPlayer4 GuestPlayer4Digs=HomePlayer4Digs HomePlayer4Digs=GuestPlayer4Digs "
            "GuestPlayer4Kills=HomePlayer4Kills HomePlayer4Kills=GuestPlayer4Kills GuestPlayer5=HomePlayer5 "
            "HomePlayer5=GuestPlayer5 GuestPlayer5Digs=HomePlayer5Digs HomePlayer5Digs=GuestPlayer5Digs "
            "GuestPlayer5Kills=HomePlayer5Kills HomePlayer5Kills=GuestPlayer5Kills GuestPlayer6=HomePlayer6 "
            "HomePlayer6=GuestPlayer6 GuestPlayer6Digs=HomePlayer6Digs HomePlayer6Digs=GuestPlayer6Digs "
            "GuestPlayer6Kills=HomePlayer6Kills HomePlayer6Kills=GuestPlayer6Kills"
        ),
    ),
    "Wrestling": dict(
        props=(
            "AdvantageTimeMinutesOnes AdvantageTimeSecondTens AdvantageTimeSecondOnes HomeMatchHundreds "
            "HomeMatchTens HomeMatchOnes HomeMatchScoreTens HomeMatchScoreOnes GuestMatchScoreTens "
            "GuestMatchScoreOnes HomeScoreTens HomeScoreOnes GuestScoreTens GuestScoreOnes "
            "HomeMatch=score:HomeMatchHundreds,HomeMatchTens,HomeMatchOnes "
            "HomeScore=score:HomeScoreTens,HomeScoreOnes "
            "HomeMatchScore=score:HomeMatchScoreTens,HomeMatchScoreOnes "
            "GuestScore=score:GuestScoreTens,GuestScoreOnes "
            "GuestMatchScore=score:GuestMatchScoreTens,GuestMatchScoreOnes WeightClass:s "
            "AdvantageTime=cat:AdvantageTimeMinutesOnes,':,AdvantageTimeSecondTens,AdvantageTimeSecondOnes "
            "AdvantageHome AdvantageGuest Period PeriodOrdinal=ord:Period Horn"
        ),
        sb=(
            "c:ClockMinutesTens@2 c:ClockMinutesOnes@3 c:ClockSecondTens@4 c:ClockSecondOnes@5 "
            "c:ClockTenthsSecond@6 e:HomeMatchHundreds+HomeMatchTens+HomeMatchOnes@8-10 "
            "e:HomeScoreTens+HomeScoreOnes@11-12 e:HomeMatchScoreTens+HomeMatchScoreOnes@13-14 "
            "e:GuestScoreTens+GuestScoreOnes@15-16 e:GuestMatchScoreTens+GuestMatchScoreOnes@17-18 "
            "e:WeightClass@19-21 c:AdvantageTimeMinutesOnes@22 c:AdvantageTimeSecondTens@23 "
            "c:AdvantageTimeSecondOnes@24 c:AdvantageHome@25 c:AdvantageGuest@26 c:Period@29 c:Horn@30 "
            "s:HomeTeamName@31-38 s:GuestTeamName@39-46 c:ClockStatus@116 c:ClockMode@117 "
            "c:PlayClockStatusInternal@118"
        ),
        swap=(
            "GuestScoreTens=HomeScoreTens HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName "
            "GuestMatchScoreTens=HomeMatchScoreTens HomeMatchScoreTens=GuestMatchScoreTens "
            "GuestMatchScoreOnes=HomeMatchScoreOnes HomeMatchScoreOnes=GuestMatchScoreOnes "
            "GuestScoreTens=HomeScoreTens HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes AdvantageGuest=AdvantageHome AdvantageHome=AdvantageGuest"
        ),
    ),
    "WaterPolo": dict(
        props=(
            "ClockHundreths ShotClockTens ShotClockOnes TimeoutMinutesOnes TimeoutSecondsTens "
            "TimeoutSecondsOnes GuestScoreTens GuestScoreOnes HomeScoreTens HomeScoreOnes "
            "HomePenaltyPlayer1Tens HomePenaltyPlayer1Ones HomePenaltyPlayer1ClockMinutesTens "
            "HomePenaltyPlayer1ClockMinutesOnes HomePenaltyPlayer1ClockSecondTens "
            "HomePenaltyPlayer1ClockSecondOnes "
            "HomePenaltyPlayer1=cat:HomePenaltyPlayer1Tens,HomePenaltyPlayer1Ones "
            "HomePenaltyPlayer1Clock=nclock:HomePenaltyPlayer1ClockMinutesTens,HomePenaltyPlayer1ClockMinutesOnes,HomePenaltyPlayer1ClockSecondTens,HomePenaltyPlayer1ClockSecondOnes "
            "HomePenaltyPlayer2Tens HomePenaltyPlayer2Ones HomePenaltyPlayer2ClockMinutesTens "
            "HomePenaltyPlayer2ClockMinutesOnes HomePenaltyPlayer2ClockSecondTens "
            "HomePenaltyPlayer2ClockSecondOnes "
            "HomePenaltyPlayer2=cat:HomePenaltyPlayer2Tens,HomePenaltyPlayer2Ones "
            "HomePenaltyPlayer2Clock=nclock:HomePenaltyPlayer2ClockMinutesTens,HomePenaltyPlayer2ClockMinutesOnes,HomePenaltyPlayer2ClockSecondTens,HomePenaltyPlayer2ClockSecondOnes "
            "GuestPenaltyPlayer1Tens GuestPenaltyPlayer1Ones GuestPenaltyPlayer1ClockMinutesTens "
            "GuestPenaltyPlayer1ClockMinutesOnes GuestPenaltyPlayer1ClockSecondTens "
            "GuestPenaltyPlayer1ClockSecondOnes "
            "GuestPenaltyPlayer1=cat:GuestPenaltyPlayer1Tens,GuestPenaltyPlayer1Ones "
            "GuestPenaltyPlayer1Clock=nclock:GuestPenaltyPlayer1ClockMinutesTens,GuestPenaltyPlayer1ClockMinutesOnes,GuestPenaltyPlayer1ClockSecondTens,GuestPenaltyPlayer1ClockSecondOnes "
            "GuestPenaltyPlayer2Tens GuestPenaltyPlayer2Ones GuestPenaltyPlayer2ClockMinutesTens "
            "GuestPenaltyPlayer2ClockMinutesOnes GuestPenaltyPlayer2ClockSecondTens "
            "GuestPenaltyPlayer2ClockSecondOnes "
            "GuestPenaltyPlayer2=cat:GuestPenaltyPlayer2Tens,GuestPenaltyPlayer2Ones "
            "GuestPenaltyPlayer2Clock=nclock:GuestPenaltyPlayer2ClockMinutesTens,GuestPenaltyPlayer2ClockMinutesOnes,GuestPenaltyPlayer2ClockSecondTens,GuestPenaltyPlayer2ClockSecondOnes "
            "ShotClock=cat:ShotClockTens,ShotClockOnes Period PeriodOrdinal=ord:Period "
            "Timeout=nclock:'_,TimeoutMinutesOnes,TimeoutSecondsTens,TimeoutSecondsOnes "
            "GuestScore=score:GuestScoreTens,GuestScoreOnes GuestTimeouts "
            "HomeScore=score:HomeScoreTens,HomeScoreOnes HomeTimeouts"
        ),
        fullclock="custom",
        sb=(
            "e:FullClock@2-9 e:ShotClock@10-11 c:Period@12 e:Timeout@13-16 "
            "e:GuestScoreTens+GuestScoreOnes@17-18 c:GuestTimeouts@19 e:HomeScoreTens+HomeScoreOnes@20-21 "
            "c:HomeTimeouts@22 s:HomeTeamName@23-30 s:GuestTeamName@31-38 e:HomePenaltyPlayer1@39-40 "
            "c:HomePenaltyPlayer1ClockMinutesTens@41 c:HomePenaltyPlayer1ClockMinutesOnes@42 "
            "c:HomePenaltyPlayer1ClockSecondTens@43 c:HomePenaltyPlayer1ClockSecondOnes@44 "
            "e:HomePenaltyPlayer2@45-46 c:HomePenaltyPlayer2ClockMinutesTens@47 "
            "c:HomePenaltyPlayer2ClockMinutesOnes@48 c:HomePenaltyPlayer2ClockSecondTens@49 "
            "c:HomePenaltyPlayer2ClockSecondOnes@50 e:GuestPenaltyPlayer1@51-52 "
            "c:GuestPenaltyPlayer1ClockMinutesTens@53 c:GuestPenaltyPlayer1ClockMinutesOnes@54 "
            "c:GuestPenaltyPlayer1ClockSecondTens@55 c:GuestPenaltyPlayer1ClockSecondOnes@56 "
            "e:GuestPenaltyPlayer2@57-58 c:GuestPenaltyPlayer2ClockMinutesTens@59 "
            "c:GuestPenaltyPlayer2ClockMinutesOnes@60 c:GuestPenaltyPlayer2ClockSecondTens@61 "
            "c:GuestPenaltyPlayer2ClockSecondOnes@62 c:ClockStatus@116 c:ClockMode@117"
        ),
        swap=(
            "GuestScoreTens=HomeScoreTens HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes GuestTimeouts=HomeTimeouts HomeTimeouts=GuestTimeouts "
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName "
            "GuestPenaltyPlayer1Tens=HomePenaltyPlayer1Tens HomePenaltyPlayer1Tens=GuestPenaltyPlayer1Tens "
            "GuestPenaltyPlayer1Ones=HomePenaltyPlayer1Ones HomePenaltyPlayer1Ones=GuestPenaltyPlayer1Ones "
            "GuestPenaltyPlayer1ClockMinutesTens=HomePenaltyPlayer1ClockMinutesTens "
            "HomePenaltyPlayer1ClockMinutesTens=GuestPenaltyPlayer1ClockMinutesTens "
            "GuestPenaltyPlayer1ClockMinutesOnes=HomePenaltyPlayer1ClockMinutesOnes "
            "HomePenaltyPlayer1ClockMinutesOnes=GuestPenaltyPlayer1ClockMinutesOnes "
            "GuestPenaltyPlayer1ClockSecondTens=HomePenaltyPlayer1ClockSecondTens "
            "HomePenaltyPlayer1ClockSecondTens=GuestPenaltyPlayer1ClockSecondTens "
            "GuestPenaltyPlayer1ClockSecondOnes=HomePenaltyPlayer1ClockSecondOnes "
            "HomePenaltyPlayer1ClockSecondOnes=GuestPenaltyPlayer1ClockSecondOnes "
            "GuestPenaltyPlayer2Tens=HomePenaltyPlayer2Tens HomePenaltyPlayer2Tens=GuestPenaltyPlayer2Tens "
            "GuestPenaltyPlayer2Ones=HomePenaltyPlayer2Ones HomePenaltyPlayer2Ones=GuestPenaltyPlayer2Ones "
            "GuestPenaltyPlayer2ClockMinutesTens=HomePenaltyPlayer2ClockMinutesTens "
            "HomePenaltyPlayer2ClockMinutesTens=GuestPenaltyPlayer2ClockMinutesTens "
            "GuestPenaltyPlayer2ClockMinutesOnes=HomePenaltyPlayer2ClockMinutesOnes "
            "HomePenaltyPlayer2ClockMinutesOnes=GuestPenaltyPlayer2ClockMinutesOnes "
            "GuestPenaltyPlayer2ClockSecondTens=HomePenaltyPlayer2ClockSecondTens "
            "HomePenaltyPlayer2ClockSecondTens=GuestPenaltyPlayer2ClockSecondTens "
            "GuestPenaltyPlayer2ClockSecondOnes=HomePenaltyPlayer2ClockSecondOnes "
            "HomePenaltyPlayer2ClockSecondOnes=GuestPenaltyPlayer2ClockSecondOnes"
        ),
    ),
    "Tennis": dict(
        props=(
            "ClockHourTens ClockHourOnes Set SetOrdinal=ord:Set TopPoints:s BottomPoints:s TopSet1Ones "
            "TopSet2Ones TopSet3Ones TopSet4Ones TopSet5Ones TopServe BottomServe BottomSet1Ones "
            "BottomSet2Ones BottomSet3Ones BottomSet4Ones BottomSet5Ones Court GameNumberOnes TopTeamScore:s "
            "BottomTeamScore:s IsDeuce Advantage TopPlayerName:s BottomPlayerName:s TopTeamName:s "
            "BottomTeamName:s IsTieBreak Set1TopTieBreak:s Set1BottomTieBreak:s Set2TopTieBreak:s "
            "Set2BottomTieBreak:s Set3TopTieBreak:s Set3BottomTieBreak:s Set4TopTieBreak:s "
            "Set4BottomTieBreak:s Set5TopTieBreak:s Set5BottomTieBreak:s IsSet3 GameNumberTens TopSet1Tens "
            "TopSet2Tens TopSet3Tens TopSet4Tens TopSet5Tens BottomSet1Tens BottomSet2Tens BottomSet3Tens "
            "BottomSet4Tens BottomSet5Tens PacketTwittle"
        ),
        clock="cat:ClockHourOnes,ClockHourTens,':,ClockMinutesTens,ClockMinutesOnes",
        sb=(
            "c:ClockHourTens@2 c:ClockHourOnes@3 c:ClockMinutesTens@4 c:ClockMinutesOnes@5 c:Set@6 "
            "e:TopPoints@7-8 e:BottomPoints@9-10 c:TopSet1Ones@11 c:TopSet2Ones@12 c:TopSet3Ones@13 "
            "c:TopSet4Ones@14 c:TopSet5Ones@15 c:TopServe@16 c:BottomServe@17 c:BottomSet1Ones@18 "
            "c:BottomSet2Ones@19 c:BottomSet3Ones@20 c:BottomSet4Ones@21 c:BottomSet5Ones@22 c:Court@23 "
            "c:GameNumberOnes@24 e:TopTeamScore@25-26 e:BottomTeamScore@27-28 c:IsDeuce@29 c:Advantage@30 "
            "s:TopPlayerName@31-38 s:BottomPlayerName@39-46 s:TopTeamName@47-54 s:BottomTeamName@55-62 "
            "c:IsTieBreak@63 e:Set1TopTieBreak@64-65 e:Set1BottomTieBreak@66-67 e:Set2TopTieBreak@68-69 "
            "e:Set2BottomTieBreak@70-71 e:Set3TopTieBreak@72-73 e:Set3BottomTieBreak@74-75 "
            "e:Set4TopTieBreak@76-77 e:Set4BottomTieBreak@78-79 e:Set5TopTieBreak@80-81 "
            "e:Set5BottomTieBreak@82-83 c:IsSet3@84 c:GameNumberTens@85 c:TopSet1Tens@86 c:TopSet2Tens@87 "
            "c:TopSet3Tens@88 c:TopSet4Tens@89 c:TopSet5Tens@90 c:BottomSet1Tens@91 c:BottomSet2Tens@92 "
            "c:BottomSet3Tens@93 c:BottomSet4Tens@94 c:BottomSet5Tens@95 c:PacketTwittle@97"
        ),
        swap=(
            "BottomPoints=TopPoints TopPoints=BottomPoints BottomSet1Ones=TopSet1Ones "
            "TopSet1Ones=BottomSet1Ones BottomSet2Ones=TopSet2Ones TopSet2Ones=BottomSet2Ones "
            "BottomSet3Ones=TopSet3Ones TopSet3Ones=BottomSet3Ones BottomSet4Ones=TopSet4Ones "
            "TopSet4Ones=BottomSet4Ones BottomSet5Ones=TopSet5Ones TopSet5Ones=BottomSet5Ones "
            "TopServe=BottomServe BottomServe=TopServe BottomTeamScore=TopTeamScore "
            "TopTeamScore=BottomTeamScore BottomPlayerName=TopPlayerName TopPlayerName=BottomPlayerName "
            "BottomTeamName=TopTeamName TopTeamName=BottomTeamName Set1BottomTieBreak=Set1TopTieBreak "
            "Set1TopTieBreak=Set1BottomTieBreak Set2BottomTieBreak=Set2TopTieBreak "
            "Set2TopTieBreak=Set2BottomTieBreak Set3BottomTieBreak=Set3TopTieBreak "
            "Set3TopTieBreak=Set3BottomTieBreak Set4BottomTieBreak=Set4TopTieBreak "
            "Set4TopTieBreak=Set4BottomTieBreak Set5BottomTieBreak=Set5TopTieBreak "
            "Set5TopTieBreak=Set5BottomTieBreak BottomSet1Tens=TopSet1Tens TopSet1Tens=BottomSet1Tens "
            "BottomSet2Tens=TopSet2Tens TopSet2Tens=BottomSet2Tens BottomSet3Tens=TopSet3Tens "
            "TopSet3Tens=BottomSet3Tens BottomSet4Tens=TopSet4Tens TopSet4Tens=BottomSet4Tens "
            "BottomSet5Tens=TopSet5Tens TopSet5Tens=BottomSet5Tens"
        ),
    ),
    "TableTennisBadminton": dict(
        props=(
            "ClockHourTens ClockHourOnes Set SetOrdinal=ord:Set HomePoints:s GuestPoints:s HomeSetsWon "
            "GuestSetsWon HomePointsSet1:s HomePointsSet2:s HomePointsSet3:s HomePointsSet4:s "
            "GuestPointsSet1:s GuestPointsSet2:s GuestPointsSet3:s GuestPointsSet4:s HomeServe GuestServe"
        ),
        clock="cat:ClockHourOnes,ClockHourTens,':,ClockMinutesTens,ClockMinutesOnes",
        sb=(
            "c:ClockHourTens@2 c:ClockHourOnes@3 c:ClockMinutesTens@4 c:ClockMinutesOnes@5 c:Set@6 "
            "e:HomePoints@7-8 e:GuestPoints@9-10 c:HomeSetsWon@11 c:GuestSetsWon@12 c:HomeServe@13 "
            "c:GuestServe@14 e:HomePointsSet1@15-16 e:GuestPointsSet1@17-18 e:HomePointsSet2@19-20 "
            "e:GuestPointsSet2@21-22 e:HomePointsSet3@23-24 e:GuestPointsSet3@25-26 e:HomePointsSet4@27-28 "
            "e:GuestPointsSet4@29-30 s:HomeTeamName@31-38 s:GuestTeamName@39-46"
        ),
        swap=(
            "HomePoints=GuestPoints GuestPoints=HomePoints GuestSetsWon=HomeSetsWon HomeSetsWon=GuestSetsWon "
            "HomeServe=GuestServe GuestServe=HomeServe HomePointsSet1=GuestPointsSet1 "
            "GuestPointsSet1=HomePointsSet1 HomePointsSet2=GuestPointsSet2 GuestPointsSet2=HomePointsSet2 "
            "HomePointsSet3=GuestPointsSet3 GuestPointsSet3=HomePointsSet3 HomePointsSet4=GuestPointsSet4 "
            "GuestPointsSet4=HomePointsSet4"
        ),
    ),
    "FutsalHandball": dict(
        props=(
            "HomeScoreTens HomeScoreOnes GuestScoreTens GuestScoreOnes HomePenaltyPlayer1Tens "
            "HomePenaltyPlayer1Ones HomePenaltyPlayer1ClockMinutesTens HomePenaltyPlayer1ClockMinutesOnes "
            "HomePenaltyPlayer1ClockSecondTens HomePenaltyPlayer1ClockSecondOnes HomePenaltyPlayer2Tens "
            "HomePenaltyPlayer2Ones HomePenaltyPlayer2ClockMinutesTens HomePenaltyPlayer2ClockMinutesOnes "
            "HomePenaltyPlayer2ClockSecondTens HomePenaltyPlayer2ClockSecondOnes HomePenaltyPlayer3Tens "
            "HomePenaltyPlayer3Ones HomePenaltyPlayer3ClockMinutesTens HomePenaltyPlayer3ClockMinutesOnes "
            "HomePenaltyPlayer3ClockSecondTens HomePenaltyPlayer3ClockSecondOnes GuestPenaltyPlayer1Tens "
            "GuestPenaltyPlayer1Ones GuestPenaltyPlayer1ClockMinutesTens GuestPenaltyPlayer1ClockMinutesOnes "
            "GuestPenaltyPlayer1ClockSecondTens GuestPenaltyPlayer1ClockSecondOnes GuestPenaltyPlayer2Tens "
            "GuestPenaltyPlayer2Ones GuestPenaltyPlayer2ClockMinutesTens GuestPenaltyPlayer2ClockMinutesOnes "
            "GuestPenaltyPlayer2ClockSecondTens GuestPenaltyPlayer2ClockSecondOnes GuestPenaltyPlayer3Tens "
            "GuestPenaltyPlayer3Ones GuestPenaltyPlayer3ClockMinutesTens GuestPenaltyPlayer3ClockMinutesOnes "
            "GuestPenaltyPlayer3ClockSecondTens GuestPenaltyPlayer3ClockSecondOnes Period "
            "PeriodOrdinal=ord:Period HomeFouls GuestFouls HomeTimeOut GuestTimeOut Horn "
            "HomeScore=score:HomeScoreTens,HomeScoreOnes GuestScore=score:GuestScoreTens,GuestScoreOnes "
            "HomePenaltyPlayer1=cat:HomePenaltyPlayer1Tens,HomePenaltyPlayer1Ones "
            "HomePenaltyPlayer1Clock=nclock:HomePenaltyPlayer1ClockMinutesTens,HomePenaltyPlayer1ClockMinutesOnes,HomePenaltyPlayer1ClockSecondTens,HomePenaltyPlayer1ClockSecondOnes "
            "HomePenaltyPlayer2=cat:HomePenaltyPlayer2Tens,HomePenaltyPlayer2Ones "
            "HomePenaltyPlayer2Clock=nclock:HomePenaltyPlayer2ClockMinutesTens,HomePenaltyPlayer2ClockMinutesOnes,HomePenaltyPlayer2ClockSecondTens,HomePenaltyPlayer2ClockSecondOnes "
            "HomePenaltyPlayer3=cat:HomePenaltyPlayer3Tens,HomePenaltyPlayer3Ones "
            "HomePenaltyPlayer3Clock=nclock:HomePenaltyPlayer3ClockMinutesTens,HomePenaltyPlayer3ClockMinutesOnes,HomePenaltyPlayer3ClockSecondTens,HomePenaltyPlayer3ClockSecondOnes "
            "GuestPenaltyPlayer1=cat:GuestPenaltyPlayer1Tens,GuestPenaltyPlayer1Ones "
            "GuestPenaltyPlayer1Clock=nclock:GuestPenaltyPlayer1ClockMinutesTens,GuestPenaltyPlayer1ClockMinutesOnes,GuestPenaltyPlayer1ClockSecondTens,GuestPenaltyPlayer1ClockSecondOnes "
            "GuestPenaltyPlayer2=cat:GuestPenaltyPlayer2Tens,GuestPenaltyPlayer2Ones "
            "GuestPenaltyPlayer2Clock=nclock:GuestPenaltyPlayer2ClockMinutesTens,GuestPenaltyPlayer2ClockMinutesOnes,GuestPenaltyPlayer2ClockSecondTens,GuestPenaltyPlayer2ClockSecondOnes "
            "GuestPenaltyPlayer3=cat:GuestPenaltyPlayer3Tens,GuestPenaltyPlayer3Ones "
            "GuestPenaltyPlayer3Clock=nclock:GuestPenaltyPlayer3ClockMinutesTens,GuestPenaltyPlayer3ClockMinutesOnes,GuestPenaltyPlayer3ClockSecondTens,GuestPenaltyPlayer3ClockSecondOnes"
        ),
        sb=(
            "K e:HomeScoreTens+HomeScoreOnes@11-12 e:GuestScoreTens+GuestScoreOnes@13-14 c:HomeTimeOut@15 "
            "c:GuestTimeOut@16 c:HomeFouls@17 c:GuestFouls@18 c:Period@19 c:Horn@20 s:HomeTeamName@21-28 "
            "s:GuestTeamName@29-36 e:HomePenaltyPlayer1@47-48 c:HomePenaltyPlayer1ClockMinutesTens@49 "
            "c:HomePenaltyPlayer1ClockMinutesOnes@50 c:HomePenaltyPlayer1ClockSecondTens@51 "
            "c:HomePenaltyPlayer1ClockSecondOnes@52 e:HomePenaltyPlayer2@53-54 "
            "c:HomePenaltyPlayer2ClockMinutesTens@55 c:HomePenaltyPlayer2ClockMinutesOnes@56 "
            "c:HomePenaltyPlayer2ClockSecondTens@57 c:HomePenaltyPlayer2ClockSecondOnes@58 "
            "e:HomePenaltyPlayer3@59-60 c:HomePenaltyPlayer3ClockMinutesTens@61 "
            "c:HomePenaltyPlayer3ClockMinutesOnes@62 c:HomePenaltyPlayer3ClockSecondTens@63 "
            "c:HomePenaltyPlayer3ClockSecondOnes@64 e:GuestPenaltyPlayer1@65-66 "
            "c:GuestPenaltyPlayer1ClockMinutesTens@67 c:GuestPenaltyPlayer1ClockMinutesOnes@68 "
            "c:GuestPenaltyPlayer1ClockSecondTens@69 c:GuestPenaltyPlayer1ClockSecondOnes@70 "
            "e:GuestPenaltyPlayer2@71-72 c:GuestPenaltyPlayer2ClockMinutesTens@73 "
            "c:GuestPenaltyPlayer2ClockMinutesOnes@74 c:GuestPenaltyPlayer2ClockSecondTens@75 "
            "c:GuestPenaltyPlayer2ClockSecondOnes@76 e:GuestPenaltyPlayer3@77-78 "
            "c:GuestPenaltyPlayer3ClockMinutesTens@79 c:GuestPenaltyPlayer3ClockMinutesOnes@80 "
            "c:GuestPenaltyPlayer3ClockSecondTens@81 c:GuestPenaltyPlayer3ClockSecondOnes@82"
        ),
        swap=(
            "GuestScoreTens=HomeScoreTens HomeScoreTens=GuestScoreTens GuestScoreOnes=HomeScoreOnes "
            "HomeScoreOnes=GuestScoreOnes GuestFouls=HomeFouls HomeFouls=GuestFouls GuestTimeOut=HomeTimeOut "
            "HomeTimeOut=GuestTimeOut GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName "
            "GuestPenaltyPlayer1Tens=HomePenaltyPlayer1Tens HomePenaltyPlayer1Tens=GuestPenaltyPlayer1Tens "
            "GuestPenaltyPlayer1Ones=HomePenaltyPlayer1Ones HomePenaltyPlayer1Ones=GuestPenaltyPlayer1Ones "
            "GuestPenaltyPlayer1ClockMinutesTens=HomePenaltyPlayer1ClockMinutesTens "
            "HomePenaltyPlayer1ClockMinutesTens=GuestPenaltyPlayer1ClockMinutesTens "
            "GuestPenaltyPlayer1ClockMinutesOnes=HomePenaltyPlayer1ClockMinutesOnes "
            "HomePenaltyPlayer1ClockMinutesOnes=GuestPenaltyPlayer1ClockMinutesOnes "
            "GuestPenaltyPlayer1ClockSecondTens=HomePenaltyPlayer1ClockSecondTens "
            "HomePenaltyPlayer1ClockSecondTens=GuestPenaltyPlayer1ClockSecondTens "
            "GuestPenaltyPlayer1ClockSecondOnes=HomePenaltyPlayer1ClockSecondOnes "
            "HomePenaltyPlayer1ClockSecondOnes=GuestPenaltyPlayer1ClockSecondOnes "
            "GuestPenaltyPlayer2Tens=HomePenaltyPlayer2Tens HomePenaltyPlayer2Tens=GuestPenaltyPlayer2Tens "
            "GuestPenaltyPlayer2Ones=HomePenaltyPlayer2Ones HomePenaltyPlayer2Ones=GuestPenaltyPlayer2Ones "
            "GuestPenaltyPlayer2ClockMinutesTens=HomePenaltyPlayer2ClockMinutesTens "
            "HomePenaltyPlayer2ClockMinutesTens=GuestPenaltyPlayer2ClockMinutesTens "
            "GuestPenaltyPlayer2ClockMinutesOnes=HomePenaltyPlayer2ClockMinutesOnes "
            "HomePenaltyPlayer2ClockMinutesOnes=GuestPenaltyPlayer2ClockMinutesOnes "
            "GuestPenaltyPlayer2ClockSecondTens=HomePenaltyPlayer2ClockSecondTens "
            "HomePenaltyPlayer2ClockSecondTens=GuestPenaltyPlayer2ClockSecondTens "
            "GuestPenaltyPlayer2ClockSecondOnes=HomePenaltyPlayer2ClockSecondOnes "
            "HomePenaltyPlayer2ClockSecondOnes=GuestPenaltyPlayer2ClockSecondOnes "
            "GuestPenaltyPlayer3Tens=HomePenaltyPlayer3Tens HomePenaltyPlayer3Tens=GuestPenaltyPlayer3Tens "
            "GuestPenaltyPlayer3Ones=HomePenaltyPlayer3Ones HomePenaltyPlayer3Ones=GuestPenaltyPlayer3Ones "
            "GuestPenaltyPlayer3ClockMinutesTens=HomePenaltyPlayer3ClockMinutesTens "
            "HomePenaltyPlayer3ClockMinutesTens=GuestPenaltyPlayer3ClockMinutesTens "
            "GuestPenaltyPlayer3ClockMinutesOnes=HomePenaltyPlayer3ClockMinutesOnes "
            "HomePenaltyPlayer3ClockMinutesOnes=GuestPenaltyPlayer3ClockMinutesOnes "
            "GuestPenaltyPlayer3ClockSecondTens=HomePenaltyPlayer3ClockSecondTens "
            "HomePenaltyPlayer3ClockSecondTens=GuestPenaltyPlayer3ClockSecondTens "
            "GuestPenaltyPlayer3ClockSecondOnes=HomePenaltyPlayer3ClockSecondOnes "
            "HomePenaltyPlayer3ClockSecondOnes=GuestPenaltyPlayer3ClockSecondOnes"
        ),
    ),
    "DragRacing": dict(
        props=(
            "ChannelNumber CategoryName:s Round:s LeftCarNumber:s LeftDriver:s LeftMember:s LeftQualPos:s "
            "RightCarNumber:s RightDriver:s RightMember:s RightQualPos:s LeftClass:s RightClass:s "
            "LeftDialIn:s LeftReactionTime:s Left60Feet:s Left330Feet:s Left660Feet:s Left660FeetMPH:s "
            "Left1000Feet:s LeftQuarterMile:s LeftQuarterMileMPH:s RightDialIn:s RightReactionTime:s "
            "Right60Feet:s Right330Feet:s Right660Feet:s Right660FeetMPH:s Right1000Feet:s RightQuarterMile:s "
            "RightQuarterMileMPH:s LeftFirst:s RightFirst:s Win Mov:s IsDetailed:b"
        ),
        sb_variants=dict(
            detailed=(
                "c:ChannelNumber@2 s:LeftDialIn@3-7 s:LeftReactionTime@8-13 s:Left60Feet@14-19 "
                "s:Left330Feet@20-25 s:Left660Feet@26-31 s:Left660FeetMPH@32-37 s:Left1000Feet@38-43 "
                "s:LeftQuarterMile@44-49 s:LeftQuarterMileMPH@50-55 s:RightDialIn@56-60 s:RightReactionTime@61-66 "
                "s:Right60Feet@67-72 s:Right330Feet@73-78 s:Right660Feet@79-84 s:Right660FeetMPH@85-90 "
                "s:Right1000Feet@91-96 s:RightQuarterMile@97-102 s:RightQuarterMileMPH@103-108 "
                "s:LeftFirst@109-114 c:Win@115 s:Mov@116-121 s:RightFirst@122-127"
            ),
            summary=(
                "c:ChannelNumber@2 s:CategoryName@3-27 s:Round@28-29 s:LeftCarNumber@30-33 s:LeftDriver@38-57 "
                "s:LeftMember@58-63 s:LeftQualPos@64-65 s:RightCarNumber@67-70 s:RightDriver@75-94 "
                "s:RightMember@95-100 s:RightQualPos@101-102 s:LeftClass@103-108 s:RightClass@109-114"
            ),
        ),
        swap=(
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName RightDialIn=LeftDialIn "
            "LeftDialIn=RightDialIn RightReactionTime=LeftReactionTime LeftReactionTime=RightReactionTime "
            "Right60Feet=Left60Feet Left60Feet=Right60Feet Right330Feet=Left330Feet Left330Feet=Right330Feet "
            "Right660Feet=Left660Feet Left660Feet=Right660Feet Right660FeetMPH=Left660FeetMPH "
            "Left660FeetMPH=Right660FeetMPH Right1000Feet=Left1000Feet Left1000Feet=Right1000Feet "
            "RightQuarterMile=LeftQuarterMile LeftQuarterMile=RightQuarterMile "
            "RightQuarterMileMPH=LeftQuarterMileMPH LeftQuarterMileMPH=RightQuarterMileMPH "
            "RightFirst=LeftFirst LeftFirst=RightFirst RightCarNumber=LeftCarNumber "
            "LeftCarNumber=RightCarNumber RightDriver=LeftDriver LeftDriver=RightDriver "
            "RightMember=LeftMember LeftMember=RightMember RightQualPos=LeftQualPos LeftQualPos=RightQualPos "
            "RightClass=LeftClass LeftClass=RightClass"
        ),
    ),
    "Rodeo": dict(
        props=(
            "ClockHundreths ClockMilliSeconds RiderNumber:s RiderScore:s Penalty ReRide LeaderNumber:s "
            "LeaderScore:s PrevRiderNumber:s PrevRiderScore:s"
        ),
        clock="cat:ClockMinutesTens,ClockMinutesOnes,':,ClockSecondTens,ClockMinutesOnes,'.,ClockTenthsSecond,ClockHundreths,ClockMilliSeconds",
        sb=(
            "c:ClockMinutesTens@2 c:ClockMinutesOnes@3 c:ClockSecondTens@4 c:ClockSecondOnes@5 "
            "c:ClockTenthsSecond@6 c:ClockHundreths@7 c:ClockMilliSeconds@8 e:RiderNumber@10-13 "
            "e:RiderScore@14-20 c:Penalty@22 c:ReRide@23 e:LeaderNumber@25-28 e:LeaderScore@29-35 "
            "e:PrevRiderNumber@37-40 e:PrevRiderScore@41-47 c:ClockStatus@116 c:ClockMode@117"
        ),
        swap=(
            ""
        ),
    ),
    "Timer": dict(
        props=(
            "ParseType:e ClockSecondHundreds ClockMilliseconds ClockHundredths Lane1ClockStatus Lane1Id:s "
            "Lane1Clock:s Lane2ClockStatus Lane2Id:s Lane2Clock:s Lane3ClockStatus Lane3Id:s Lane3Clock:s "
            "Lane4ClockStatus Lane4Id:s Lane4Clock:s Lane5ClockStatus Lane5Id:s Lane5Clock:s Lane6ClockStatus "
            "Lane6Id:s Lane6Clock:s Lane7ClockStatus Lane7Id:s Lane7Clock:s Lane8ClockStatus Lane8Id:s "
            "Lane8Clock:s"
        ),
        clock="custom",
        sb_variants=dict(
            OnlySecondsClock=(
                "e:Clock@2-8 c:ClockStatus@116"
            ),
            FullClock=(
                "e:Clock@2-9 c:ClockStatus@116"
            ),
            Lanes=(
                "c:Lane1ClockStatus@2 e:Lane1Id@3-5 e:Lane1Clock@6-14 c:Lane2ClockStatus@15 e:Lane2Id@16-18 "
                "e:Lane2Clock@19-27 c:Lane3ClockStatus@28 e:Lane3Id@29-31 e:Lane3Clock@32-40 "
                "c:Lane4ClockStatus@41 e:Lane4Id@42-44 e:Lane4Clock@45-53 c:Lane5ClockStatus@54 e:Lane5Id@55-57 "
                "e:Lane5Clock@58-66 c:Lane6ClockStatus@67 e:Lane6Id@68-70 e:Lane6Clock@71-79 "
                "c:Lane7ClockStatus@80 e:Lane7Id@81-83 e:Lane7Clock@84-92 c:Lane8ClockStatus@93 e:Lane8Id@94-96 "
                "e:Lane8Clock@97-105"
            ),
        ),
        swap=(
            ""
        ),
    ),
    "Generic": dict(
        props=(
            "TOTimerMinutesOnes TOTimerSecondsTens TOTimerSecondsOnes HomeHundreds HomeTens HomeOnes "
            "GuestHundreds GuestTens GuestOnes "
            "TOTimer=cat:TOTimerMinutesOnes,TOTimerSecondsTens,TOTimerSecondsOnes ClockDigit1 ClockDigit2 "
            "ClockDigit3 ClockDigit4 Home=cat:HomeHundreds,HomeTens,HomeOnes "
            "Guest=cat:GuestHundreds,GuestTens,GuestOnes Period PeriodOrdinal=ord:Period HomeFouls GuestFouls "
            "HomeNumberOfTO GuestNumberOfTO ClockRun PlayClockRun PlayClockDisplay PlayClock:s"
        ),
        sb=(
            "e:TOTimer@2-4 c:ClockDigit1@5 c:ClockDigit2@6 c:ClockDigit3@7 c:ClockDigit4@8 e:Home@9-11 "
            "e:Guest@12-14 c:Period@15 c:HomeFouls@16 c:GuestFouls@17 c:HomeNumberOfTO@18 "
            "c:GuestNumberOfTO@19 c:ClockMode@20 c:ClockRun@21 c:PlayClockRun@22 c:PlayClockDisplay@23 "
            "e:PlayClock@24-25"
        ),
        swap=(
            "GuestTeamName=HomeTeamName HomeTeamName=GuestTeamName GuestHundreds=HomeHundreds "
            "HomeHundreds=GuestHundreds GuestTens=HomeTens HomeTens=GuestTens GuestOnes=HomeOnes "
            "HomeOnes=GuestOnes GuestFouls=HomeFouls HomeFouls=GuestFouls GuestNumberOfTO=HomeNumberOfTO "
            "HomeNumberOfTO=GuestNumberOfTO"
        ),
    ),
    "SwimmingDetail": dict(
        props=(
            "FinishFlag1 Split1:s Place1 Clock1:s FinishFlag2 Split2:s Place2 Clock2:s FinishFlag3 Split3:s "
            "Place3 Clock3:s FinishFlag4 Split4:s Place4 Clock4:s FinishFlag5 Split5:s Place5 Clock5:s "
            "FinishFlag6 Split6:s Place6 Clock6:s FinishFlag7 Split7:s Place7 Clock7:s FinishFlag8 Split8:s "
            "Place8 Clock8:s"
        ),
        clock="cat:ClockMinutesTens,ClockMinutesOnes,':,ClockSecondTens,ClockSecondOnes,'.,ClockTenthsSecond",
        sb=(
            "c:ClockMinutesTens@2 c:ClockMinutesOnes@3 c:ClockSecondTens@4 c:ClockSecondOnes@5 "
            "c:ClockTenthsSecond@6 c:FinishFlag1@7 e:Split1@8-9 c:Place1@10 e:Clock1@11-17 c:FinishFlag2@18 "
            "e:Split2@19-20 c:Place2@21 e:Clock2@22-28 c:FinishFlag3@29 e:Split3@30-31 c:Place3@32 "
            "e:Clock3@33-39 c:FinishFlag4@40 e:Split4@41-42 c:Place4@43 e:Clock4@44-50 c:FinishFlag5@51 "
            "e:Split5@52-53 c:Place5@54 e:Clock5@55-61 c:FinishFlag6@62 e:Split6@63-64 c:Place6@65 "
            "e:Clock6@66-72 c:FinishFlag7@73 e:Split7@74-75 c:Place7@76 e:Clock7@77-83 c:FinishFlag8@84 "
            "e:Split8@85-86 c:Place8@87 e:Clock8@88-94 c:ClockMode@117"
        ),
        swap=(
            ""
        ),
    ),
    "SwimmingEvent": dict(
        props=(
            "EventName:s EventRecord:s ClockHundreths"
        ),
        clock="custom",
        sb=(
            "e:Clock@2-9 e:EventName@10-45 e:EventRecord@46-81"
        ),
        swap=(
            ""
        ),
    ),
    "SwimmingRows": dict(
        props=(
            "RowType=custom RowANumber:i RowBNumber:i RowCNumber:i ClockHundreths RowALane:s "
            "RowASwimmerName:s RowATeamName:s RowAClock:s RowAPlace:s RowBLane:s RowBSwimmerName:s "
            "RowBTeamName:s RowBClock:s RowBPlace:s RowCLane:s RowCSwimmerName:s RowCTeamName:s RowCClock:s "
            "RowCPlace:s"
        ),
        clock="custom",
        sb=(
            "e:Clock@2-9 e:RowALane@10-11 e:RowASwimmerName@12-27 e:RowATeamName@28-31 e:RowAClock@32-39 "
            "e:RowAPlace@40-41 e:RowBLane@42-43 e:RowBSwimmerName@44-59 e:RowBTeamName@60-63 "
            "e:RowBClock@64-71 e:RowBPlace@72-73 e:RowCLane@74-75 e:RowCSwimmerName@76-91 "
            "e:RowCTeamName@92-95 e:RowCClock@96-103 e:RowCPlace@104-105"
        ),
        swap=(
            ""
        ),
    ),
    "SwimmingMixed": dict(
        props=(
            "PacketType:e SwimmingRows:e SwimmingEvent:e"
        ),
        sb=(
            ""
        ),
        swap=(
            ""
        ),
    ),
}

CONTRACTS = tuple(_SPECS)

# --------------------------------------------------------------------------- compile tables
_BASE_CHARS = ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes", "ClockTenthsSecond",
               "ClockMode", "InboundChannelNumber", "InternalClockStatus", "EmulatedClockStatus",
               "PlayClockStatusInternal", "EmulatedPlayClockStatus")


class _Spec:
    def __init__(self, name, raw):
        self.name = name
        self.props = []  # (name, kind, expr)
        for tok in raw["props"].split():
            if "=" in tok:
                n, e = tok.split("=", 1)
                self.props.append((n, "x", e))
            elif ":" in tok:
                n, k = tok.split(":", 1)
                self.props.append((n, k, None))
            else:
                self.props.append((tok, "c", None))
        self.kinds = {n: k for n, k, _ in self.props}
        self.exprs = {n: e for n, k, e in self.props if k == "x"}
        self.clock = raw.get("clock")
        self.fullclock = raw.get("fullclock")
        self.sb = raw["sb"].split() if "sb" in raw else None
        self.variants = {k: v.split() for k, v in raw.get("sb_variants", {}).items()}
        self.swap = [t.split("=") for t in raw["swap"].split()]
        self.swap_poss = bool(raw.get("swap_poss"))


_COMPILED = {n: _Spec(n, r) for n, r in _SPECS.items()}


def _spec(contract):
    try:
        return _COMPILED[contract]
    except KeyError:
        raise ValueError(f"unknown contract {contract!r}") from None


# --------------------------------------------------------------------------- string helpers (Sport base class)
def _ch(v):
    if v is None:
        return " "
    s = str(v)
    return s[0] if s else " "


def _ws(ch):
    return ch.isspace()


def _ordinal(ch):
    if not ch.isdigit() or not ch.isascii():
        return ""
    n = int(ch)
    if n <= 0:
        return ""
    return f"{n}{({1: 'st', 2: 'nd', 3: 'rd'}).get(n, 'th')}"


def _ordinal_int(n):
    if n <= 0:
        return ""
    if 11 <= n <= 13:
        return f"{n}th"
    return f"{n}{({1: 'st', 2: 'nd', 3: 'rd'}).get(n % 10, 'th')}"


def _normal_clock(mt, mo, st, so):
    mt = " " if mt in (" ", "0") else mt
    mo = "0" if mo == " " else mo
    st = "0" if st == " " else st
    so = "0" if so == " " else so
    return f"{mt}{mo}:{st}{so}".strip()


def _tenth_clock(st, so, t):
    st = " " if st in (" ", "0") else st
    so = "0" if so == " " else so
    t = "0" if t == " " else t
    return f"{st}{so}.{t}".strip()


def _full_clock(mt, mo, st, so, t):
    mt = "" if _ws(mt) else mt
    mo = "0" if _ws(mo) else mo
    st = "0" if _ws(st) else st
    so = "0" if _ws(so) else so
    t = "0" if _ws(t) else t
    return f"{mt}{mo}:{st}{so}.{t}"


def _score(*digits):
    if not digits:
        return "0"
    s = "".join(" " if (ord(d) < 32 or 127 <= ord(d) < 160) else d for d in digits).lstrip(" 0")
    return s or "0"


def _try_int(s):
    s = s.strip()
    return int(s) if re.fullmatch(r"[+-]?[0-9]+", s) else 0


# --------------------------------------------------------------------------- view of one contract
class _View:
    """Property access with ScoreConnect's defaults and computed properties."""

    def __init__(self, contract, c, meta):
        self.sp = _spec(contract)
        self.c = c
        self.meta = meta or {}
        self.memo = {}

    def get(self, name):
        if name in self.memo:
            return self.memo[name]
        v = self._get(name)
        self.memo[name] = v
        return v

    __getitem__ = get

    def _get(self, name):
        sp, c = self.sp, self.c
        if name in _BASE_CHARS:
            if name == "InboundChannelNumber":
                m = self.meta.get("channel")
                return _ch(m if m not in (None, "") else (c.get(name) if _ch(c.get(name)) != " " else "1"))
            return _ch(c.get(name))
        if name == "Clock":
            return self._clock()
        if name == "FullClock":
            return self._fullclock()
        if name == "ClockStatus":
            i = _ch(c.get("InternalClockStatus"))
            return i if i != " " else _ch(c.get("EmulatedClockStatus"))
        if name == "PlayClockStatus":
            i = _ch(c.get("PlayClockStatusInternal"))
            return i if i != " " else _ch(c.get("EmulatedPlayClockStatus"))
        if name in ("HomeTeamName", "GuestTeamName"):
            m = self.meta.get("home_team_name" if name[0] == "H" else "guest_team_name")
            return str(m) if m else str(c.get(name) or "")
        if name == "WeightedCoverage":
            return _coverage(self)
        if name == "Period" and sp.name == "Basketball":
            p = _ch(c.get("Period"))
            return "E" if p > "4" else p
        if sp.name == "SwimmingRows" and name in ("RowType", "RowANumber", "RowBNumber", "RowCNumber"):
            rt = _enum("RowType", c.get("RowType"))
            if name == "RowType":
                return rt
            if c.get(name) is not None:
                return int(c[name])
            return rt * 3 + "ABC".index(name[3]) + 1
        k = sp.kinds.get(name)
        if k == "x":
            return self._expr(name, sp.exprs[name])
        if k == "s":
            v = c.get(name)
            return "" if v is None else str(v)
        if k == "i":
            try:
                return int(c.get(name) or 0)
            except (TypeError, ValueError):
                return 0
        if k == "b":
            return bool(c.get(name))
        if k == "e":
            return _enum(name, c.get(name))
        return _ch(c.get(name))

    def text(self, name):
        v = self.get(name)
        return v if isinstance(v, str) else str(v)

    def _clock(self):
        sp = self.sp
        if sp.clock == "custom":
            return _CUSTOM_CLOCK[sp.name](self)
        if sp.clock:
            return self._expr("Clock", sp.clock)
        g = self.get
        if g("ClockMode") in (":", " "):
            return _normal_clock(g("ClockMinutesTens"), g("ClockMinutesOnes"), g("ClockSecondTens"), g("ClockSecondOnes"))
        return _tenth_clock(g("ClockSecondTens"), g("ClockSecondOnes"), g("ClockTenthsSecond"))

    def _fullclock(self):
        g = self.get
        base = _full_clock(g("ClockMinutesTens"), g("ClockMinutesOnes"), g("ClockSecondTens"), g("ClockSecondOnes"),
                           g("ClockTenthsSecond"))
        if self.sp.fullclock:  # WaterPolo: hundredths appended
            h = g("ClockHundreths")
            return base + ("0" if _ws(h) else h)
        return base

    def _expr(self, name, expr):
        kind, _, arg = expr.partition(":")
        if kind == "custom":
            return _CUSTOM[(self.sp.name, name)](self)
        parts = arg.split(",")
        if kind == "cat":
            return "".join((" " if p == "'_" else p[1:]) if p.startswith("'") else self.text(p) for p in parts)
        if kind == "score":
            return _score(*[self.get(p) for p in parts])
        if kind == "ord":
            return _ordinal(self.get(parts[0]))
        if kind == "nclock":
            a = [" " if p == "'_" else self.get(p) for p in parts]
            return _normal_clock(*a)
        raise ValueError(expr)


def _enum(name, v):
    if v is None or v == "":
        return 0 if name != "ParseType" else 1
    if isinstance(v, str) and not v.lstrip("-").isdigit():
        return _ENUMS[name].get(v, 0)
    return int(v)


# --------------------------------------------------------------------------- hand-written computed properties
def _shot_clock_basketball(v):
    tenths = v["ShotClockTenthsSecond"] != " "
    t, o = v["ShotClockSecondTens"], v["ShotClockSecondOnes"]
    lead = o if t in (" ", "0") else t + o
    return f"{lead}.{v['ShotClockTenthsSecond']}" if tenths else lead


def _timeout_clock(v):
    mo = v["TimeoutClockMinutesOnes"]
    return f"{mo}{':' if mo != ' ' else ' '}{v['TimeoutClockSecondTens']}{v['TimeoutClockSecondOnes']}"


def _shot_clock_hockey(v):
    t = v["ShotClockTenthsSecond"]
    return f"{v['ShotClockTens']}{v['ShotClockOnes']}.{t if t != ' ' else '0'}"


def _inning_ordinal(v):
    t, o = v["InningTens"], v["InningOnes"]
    if t in (" ", "0"):
        return _ordinal(o)
    n = _try_int(t + o)
    return _ordinal_int(n) if n > 0 else ""


_CUSTOM = {
    ("Basketball", "ShotClock"): _shot_clock_basketball,
    ("Basketball", "TimeoutClock"): _timeout_clock,
    ("Volleyball", "TimeoutClock"): _timeout_clock,
    ("HockeyLacrosse", "ShotClock"): _shot_clock_hockey,
    ("BaseballSoftball", "InningOrdinal"): _inning_ordinal,
}


def _timer_clock(v):
    mode = _enum("ParseType", v.c.get("ParseType"))
    g = v.get
    if mode == 1:
        return f"{g('ClockMinutesTens')}{g('ClockMinutesOnes')}:{g('ClockSecondTens')}{g('ClockSecondOnes')}." \
               f"{g('ClockTenthsSecond')}{g('ClockHundredths')}"
    if mode == 2:
        return f"{g('ClockSecondHundreds')}{g('ClockSecondTens')}{g('ClockSecondOnes')}.{g('ClockTenthsSecond')}" \
               f"{g('ClockHundredths')}{g('ClockMilliseconds')}"
    return ""


def _swim_clock(v):
    g = v.get
    return f"{g('ClockMinutesTens')}{g('ClockMinutesOnes')}{':' if g('ClockMinutesOnes') != ' ' else ' '}" \
           f"{g('ClockSecondTens')}{g('ClockSecondOnes')}.{g('ClockTenthsSecond')}{g('ClockHundreths')}"


_CUSTOM_CLOCK = {"Timer": _timer_clock, "SwimmingEvent": _swim_clock, "SwimmingRows": _swim_clock}


def _coverage(v):
    n = v.sp.name
    g = v.get
    if n not in ("Football", "Soccer", "Basketball"):
        return 0.0
    pts = 0
    named = lambda x: 1 if g(x) else 0  # noqa: E731
    if n == "Football":
        pts = 20 + 20 + 20  # clock, scores: the strings are never empty
        pts += 5 if (g("HomePossession") != " " or g("GuestPossession") != " ") else 0
        pts += 5 if g("Down") != " " else 0
        pts += 5 + 5  # ToGo and BallOn are two-character strings, so never empty
        pts += 5 if g("Flag") != " " else 0
        pts += 5 if g("Quarter") != " " else 0
        pts += 5 * named("HomeTeamName") + 5 * named("GuestTeamName")
    elif n == "Soccer":
        pts = 25 + 20 + 20
        pts += 10 if g("HomeTimeouts") != " " else 0
        pts += 10 if g("GuestTimeouts") != " " else 0
        pts += 7 if g("Period") != " " else 0
        pts += 5 * named("HomeTeamName") + 5 * named("GuestTeamName")
    else:
        pts = 30 + 20 + 20
        pts += 10 if (g("HomePossession") != " " or g("GuestPossession") != " ") else 0
        pts += 8 if g("Period") != " " else 0
        pts += 6 * named("HomeTeamName") + 6 * named("GuestTeamName")
    return pts / 100.0


# --------------------------------------------------------------------------- timestamps
def _timestamps(now):
    us = int(now * 1_000_000)
    ticks = us * 10 + _NET_EPOCH_TICKS
    sec, frac = divmod(us, 1_000_000)
    dt = _dt.datetime.fromtimestamp(sec, _dt.timezone.utc)
    full = dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{frac * 10:07d}Z"
    return format(ticks, "X")[:12], full, str(us // 1000)


def event_code(event_name):
    """sbdata characters 0-1 for an EventType name (two spaces if unknown)."""
    n = EVENT_CODES.get(event_name)
    return f"{n:02d}" if n is not None else "  "


def _event_name(contract, c):
    e = c.get("EventId")
    if isinstance(e, int):
        for k, n in EVENT_CODES.items():
            if n == e:
                return k
    return str(e) if e else _DEFAULT_EVENT[contract]


# --------------------------------------------------------------------------- JSON
def _nested(contract, c, key):
    sub = dict(c.get(key) or {})
    sub.setdefault("EventId", c.get("EventId"))
    return sub


def sportzcast_json(contract, c, meta=None):
    """The properties ScoreConnect serialises (``[JsonIgnore]`` ones left out), in declaration order."""
    meta = meta or {}
    v = _View(contract, c, meta)
    now = meta.get("now")
    now = time.time() if now is None else now
    ts, ts_full, ts_epoch = _timestamps(now)
    bot = int(meta.get("bot_number", 0) or 0)
    origin = int(meta.get("origin", 1))
    g = v.get
    out = {
        "OriginTypeId": origin, "OriginType": ORIGIN_NAMES.get(origin, "Unknown"),
        "ClockMinutesTens": g("ClockMinutesTens"), "ClockMinutesOnes": g("ClockMinutesOnes"),
        "ClockSecondTens": g("ClockSecondTens"), "ClockSecondOnes": g("ClockSecondOnes"),
        "ClockTenthsSecond": g("ClockTenthsSecond"),
        "VendorSportId": int(c.get("VendorSportId") or 0), "ClockMode": g("ClockMode"),
        "Clock": g("Clock"), "FullClock": g("FullClock"),
        "EventId": EVENT_CODES.get(_event_name(contract, c), 0), "InboundChannelNumber": g("InboundChannelNumber"),
        "ClockStatus": g("ClockStatus"), "PlayClockStatus": g("PlayClockStatus"),
        "BotNumberHex": f"{bot:06X}", "BotNumber": bot,
        "TimeStamp": ts, "TimeStampFull": ts_full, "TimeStampEpoch": ts_epoch,
        "GuestTeamName": g("GuestTeamName"), "HomeTeamName": g("HomeTeamName"),
        "WeightedCoverage": float(g("WeightedCoverage")), "PublishRate": float(meta.get("publish_rate", 10.0)),
        "VenueName": str(meta.get("venue_name") or ""), "VenueId": int(meta.get("venue_id") or 0),
        "VenueGeniusId": int(meta.get("venue_genius_id") or 0),
    }
    if contract == "SwimmingMixed":
        out["PacketType"] = _enum("PacketType", c.get("PacketType"))
        out["SwimmingRows"] = sportzcast_json("SwimmingRows", _nested(contract, c, "SwimmingRows"), meta)
        out["SwimmingEvent"] = sportzcast_json("SwimmingEvent", _nested(contract, c, "SwimmingEvent"), meta)
        return out
    for name, _k, _e in v.sp.props:
        out[name] = g(name)
    return out


# --------------------------------------------------------------------------- sbdata
def _put(sb, text, a, b, right):
    width = b - a + 1
    text = text or ""
    if right:
        text = text[-width:].rjust(width)
    else:
        text = text[:width].ljust(width)
    sb[a:b + 1] = list(text)


def sbdata(contract, c, meta=None):
    """The 150-character ParseToSbData string."""
    meta = meta or {}
    if contract == "SwimmingMixed":
        pt = _enum("PacketType", c.get("PacketType"))
        if pt == 1:
            return sbdata("SwimmingEvent", _nested(contract, c, "SwimmingEvent"), meta)
        if pt == 2:
            return sbdata("SwimmingRows", _nested(contract, c, "SwimmingRows"), meta)
        raise ValueError("SwimmingMixed needs PacketType Event or Rows")
    v = _View(contract, c, meta)
    sp = v.sp
    now = meta.get("now")
    ts = _timestamps(time.time() if now is None else now)[0]
    bot = int(meta.get("bot_number", 0) or 0)
    sb = [" "] * 150
    _put(sb, event_code(_event_name(contract, c)), 0, 1, False)
    sb[131] = v["InboundChannelNumber"]
    _put(sb, f"{bot:06X}", 132, 137, False)
    _put(sb, ts, 138, 149, False)
    if sp.variants:
        if contract == "Timer":
            key = {0: "Lanes", 1: "FullClock", 2: "OnlySecondsClock"}[_enum("ParseType", c.get("ParseType"))]
        else:
            key = "detailed" if c.get("IsDetailed") else "summary"
        ops = sp.variants[key]
    else:
        ops = sp.sb
    for op in ops:
        if op == "K":
            if v["ClockMode"] in (":", " "):
                digits = [v["ClockMinutesTens"], v["ClockMinutesOnes"], v["ClockSecondTens"], v["ClockSecondOnes"]]
            else:
                digits = [v["ClockSecondTens"], v["ClockSecondOnes"], v["ClockTenthsSecond"], " "]
            sb[2:6] = [_clean(d) for d in digits]
            sb[116], sb[117], sb[118] = (_clean(v["ClockStatus"]), _clean(v["ClockMode"]), _clean(v["PlayClockStatus"]))
            continue
        kind, rest = op.split(":", 1)
        src, _, pos = rest.partition("@")
        if kind == "c":
            sb[int(pos)] = _clean(_ch(v.get(src)))
            continue
        if kind == "p":  # second-to-last character, only when the string has at least two
            t = v.text(src)
            if len(t) >= 2:
                sb[int(pos)] = _clean(t[-2])
            continue
        a, _, b = pos.partition("-")
        text = "".join(v.text(p) for p in src.split("+"))
        _put(sb, text, int(a), int(b), kind == "e")
    return "".join(sb)


def _clean(ch):
    return " " if (ord(ch) < 32 or 127 <= ord(ch) < 160) else ch


# --------------------------------------------------------------------------- team swap
def swap_teams(contract, c):
    """SwapTeamInformation on a copy. (Tennis and DragRacing: the original only changes the source object,
    so the returned copy is unchanged; reproduced here, input untouched.)"""
    if contract == "SwimmingMixed":
        return dict(c)
    sp = _spec(contract)
    new = dict(c)
    for a, b in sp.swap:
        if b in c:
            new[a] = c[b]
        else:
            new.pop(a, None)
    if sp.swap_poss:
        if _ch(c.get("HomePossession")) == "<":
            new["GuestPossession"], new["HomePossession"] = ">", " "
        elif _ch(c.get("GuestPossession")) == ">":
            new["GuestPossession"], new["HomePossession"] = " ", "<"
    return new


# --------------------------------------------------------------------------- clock status emulator
class ClockStatusEmulator:
    """Infers 'R'/'S' for boards without a run flag from whether the clock digits keep changing.

    Call :meth:`apply` after each decode. It reads ``InternalClockStatus`` / ``PlayClockStatusInternal`` and the
    previous ``EmulatedClockStatus`` / ``EmulatedPlayClockStatus`` from the contract and writes the new
    emulated values back. ``contract`` (optional) picks the play-clock source; otherwise it is guessed from the keys.
    """

    def __init__(self, contract=None):
        self.contract = contract
        self._main = -1
        self._play = -1
        self._main_sw = None
        self._play_sw = None

    @staticmethod
    def _elapsed_ms(sw, t):
        return 0.0 if sw is None else (t - sw) * 1000.0

    @staticmethod
    def _main_value(c):
        mode = _ch(c.get("ClockMode"))
        if mode == ":":
            return (_try_int(_ch(c.get("ClockMinutesTens")) + _ch(c.get("ClockMinutesOnes"))) * 600
                    + _try_int(_ch(c.get("ClockSecondTens")) + _ch(c.get("ClockSecondOnes"))) * 10)
        if mode == ".":
            return (_try_int(_ch(c.get("ClockSecondTens")) + _ch(c.get("ClockSecondOnes"))) * 10
                    + _try_int(_ch(c.get("ClockTenthsSecond"))))
        return -1

    def _play_value(self, c):
        k = self.contract
        if k is None:
            k = ("Football" if "PlayClockTens" in c else "Basketball" if "ShotClockSecondTens" in c
                 else "HockeyLacrosse" if "ShotClockTens" in c else "")
        g = lambda n: _ch(c.get(n))  # noqa: E731
        if k == "Football":
            s = g("PlayClockTens") + g("PlayClockOnes")
        elif k == "Basketball":
            s = g("ShotClockSecondTens") + g("ShotClockSecondOnes")
        elif k == "HockeyLacrosse":
            s = g("ShotClockTens") + g("ShotClockOnes")
        else:
            return 0
        s = s.strip()
        return _try_int(s) * 10 if re.fullmatch(r"[+-]?[0-9]+", s) else 0

    def apply(self, c, now=None):
        t = time.monotonic() if now is None else now
        emu = _ch(c.get("EmulatedClockStatus"))
        if _ch(c.get("InternalClockStatus")) == " ":
            if self._main == -1:
                self._main = self._main_value(c)
                self._main_sw = t
            r = self._main_value(c)
            mode = _ch(c.get("ClockMode"))
            el = self._elapsed_ms(self._main_sw, t)
            if r != self._main and r != 0:
                emu, self._main_sw = "R", t
            elif r == 0 or (mode == ":" and r == self._main and el >= 1500) \
                    or (mode == "." and r == self._main and el >= 150):
                emu, self._main_sw = "S", None
            self._main = r
        c["EmulatedClockStatus"] = "S" if emu == " " else emu
        pemu = _ch(c.get("EmulatedPlayClockStatus"))
        if _ch(c.get("PlayClockStatusInternal")) == " ":
            pc = self._play_value(c)
            if self._play == -1:
                self._play = pc
                self._play_sw = t
            if pc != self._play:
                pemu, self._play_sw = "R", t
            elif self._elapsed_ms(self._play_sw, t) >= 1500:
                pemu, self._play_sw = "S", None
            self._play = pc
        c["EmulatedPlayClockStatus"] = "S" if pemu == " " else pemu


# --------------------------------------------------------------------------- flat() for data.json / vMix / text files
_SNAKE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_FLAT_BASE = ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes", "ClockTenthsSecond",
              "ClockMode", "Clock", "FullClock", "ClockStatus", "PlayClockStatus", "GuestTeamName", "HomeTeamName",
              "WeightedCoverage")


def _snake(name):
    return _SNAKE.sub("_", name).lower()


def _n(s, blank=""):
    """Trimmed number text: '07' -> '7', '' -> blank."""
    s = str(s).strip()
    if not s:
        return blank
    return str(int(s)) if s.isdigit() else s


def _flag(ch):
    return str(ch).strip() != ""


class _Recorder(dict):
    """dict that remembers which keys were written (to tell friendly aliases from raw contract fields)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.written = set()

    def __setitem__(self, k, v):
        self.written.add(k)
        super().__setitem__(k, v)

    def setdefault(self, k, v=None):
        if k not in self:
            self.written.add(k)
        return super().setdefault(k, v)

    def update(self, *a, **k):
        for key, val in dict(*a, **k).items():
            self[key] = val


def raw_keys(contract, c):
    """The keys of flat(contract, c) that are plain contract fields rather than ScoreReader's friendly fields
    (clock, home_score, period, shot_clock, …)."""
    return flat(contract, c, _split=True)[1]


def flat(contract, c, _split=False):
    """snake_case version of every serialised property (blank characters become ""), plus friendly aliases."""
    v = _View(contract, c, None)
    sp = v.sp
    out = {}

    def put(name, val):
        out[_snake(name)] = val.strip() if isinstance(val, str) else val

    if contract == "SwimmingMixed":
        pt = _enum("PacketType", c.get("PacketType"))
        sub = "SwimmingEvent" if pt == 1 else "SwimmingRows"
        out, raw = flat(sub, _nested(contract, c, sub), _split=True)
        out["packet_type"] = pt
        return (out, raw) if _split else out
    for n in _FLAT_BASE:
        put(n, v[n])
    for n, _k, _e in sp.props:
        put(n, v[n])
    raw = set(out)
    out = _Recorder(out)
    ev = _event_name(contract, c)
    out["sport"] = ev.lower()
    out["clock"] = v["Clock"].strip()
    out["clock_running"] = v["ClockStatus"] == "R"
    if v["HomeTeamName"]:
        out["home_name"] = v["HomeTeamName"].strip()
    if v["GuestTeamName"]:
        out["guest_name"] = v["GuestTeamName"].strip()
    _ALIASES.get(contract, lambda v, o: None)(v, out)
    for k in ("home_poss", "guest_poss"):
        out.setdefault(k, False)
    out["possession"] = "H" if out["home_poss"] else "V" if out["guest_poss"] else ""
    result = dict(out)
    return (result, raw - out.written) if _split else result


def _period(v, o, name, ordinal=None):
    p = v[name].strip()
    o["period"] = p
    o["period_ordinal"] = v[ordinal] if ordinal else _ordinal(p) if p else ""


def _poss(v, o):
    o["home_poss"] = _flag(v["HomePossession"])
    o["guest_poss"] = _flag(v["GuestPossession"])


def _football(v, o):
    _period(v, o, "Quarter", "QuarterOrdinal")
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    pc = v["PlayClock"].strip()
    o["play_clock"] = (pc.lstrip("0") or "0") if pc else ""
    _poss(v, o)
    o["home_timeouts"], o["guest_timeouts"] = v["HomeTimeouts"].strip(), v["GuestTimeouts"].strip()
    d = v["Down"].strip()
    dtxt = _ordinal(d) if d.isdigit() else d
    togo = _n(v["ToGo"])
    o["down"], o["to_go"], o["ball_on"] = dtxt, togo, _n(v["BallOn"])
    o["down_distance"] = f"{dtxt} & {togo}" if dtxt and togo else dtxt
    o["horn"] = _flag(v["Horn"])


def _soccer(v, o):
    _period(v, o, "Period", "PeriodOrdinal")
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    o["home_shots"], o["guest_shots"] = _n(v["HomeShots"]), _n(v["GuestShots"])
    o["home_corners"], o["guest_corners"] = _n(v["HomeCornerKicks"]), _n(v["GuestCornerKicks"])
    o["home_saves"], o["guest_saves"] = _n(v["HomeSaves"]), _n(v["GuestSaves"])
    o["home_penalties"], o["guest_penalties"] = _n(v["HomePenalties"]), _n(v["GuestPenalties"])
    o["home_timeouts"], o["guest_timeouts"] = v["HomeTimeouts"].strip(), v["GuestTimeouts"].strip()
    _poss(v, o)
    o["horn"] = _flag(v["Horn"])


def _basketball(v, o):
    _period(v, o, "Period", "PeriodOrdinal")
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    o["shot_clock"] = v["ShotClock"].strip()
    o["home_fouls"], o["guest_fouls"] = _n(v["HomeFouls"]), _n(v["GuestFouls"])
    o["home_bonus"], o["guest_bonus"] = _flag(v["HomeBonus"]), _flag(v["GuestBonus"])
    o["home_double_bonus"], o["guest_double_bonus"] = _flag(v["HomeDoubleBonus"]), _flag(v["GuestDoubleBonus"])
    o["home_timeouts"], o["guest_timeouts"] = v["HomeTimeouts"].strip(), v["GuestTimeouts"].strip()
    o["timeout_clock"] = v["TimeoutClock"].strip()
    _poss(v, o)
    o["horn"] = _flag(v["Horn"])


def _baseball(v, o):
    inn = _n(v["Inning"])
    o["inning"], o["inning_ordinal"] = inn, v["InningOrdinal"]
    o["period"], o["period_ordinal"] = inn, v["InningOrdinal"]
    o["home_score"], o["guest_score"] = v["HomeRuns"], v["GuestRuns"]
    o["home_runs"], o["guest_runs"] = v["HomeRuns"], v["GuestRuns"]
    o["balls"], o["strikes"], o["outs"] = (v[k].strip() for k in ("Balls", "Strikes", "Outs"))
    o["home_hits"], o["guest_hits"] = _n(v["HomeHits"]), _n(v["GuestHits"])
    o["home_errors"], o["guest_errors"] = v["HomeErrors"].strip(), v["GuestErrors"].strip()
    top = v["TopBottomInning"] == "T" or (_flag(v["TopOfInning"]) and not _flag(v["BottomOfInning"]))
    bot = v["TopBottomInning"] == "B" or (_flag(v["BottomOfInning"]) and not _flag(v["TopOfInning"]))
    o["inning_half"] = "top" if top else "bottom" if bot else ""
    o["on_first"], o["on_second"], o["on_third"] = (_flag(v[k]) for k in ("OnFirst", "OnSecond", "OnThird"))
    o["at_bat"] = _n(v["AtBat"])
    o["pitch_speed"], o["pitch_count"], o["pitch_clock"] = v["PitchSpeed"].strip(), v["PitchCount"].strip(), \
        v["PitchClock"].strip()


def _hockey(v, o):
    _period(v, o, "Period", "PeriodOrdinal")
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    o["home_shots"], o["guest_shots"] = _n(v["HomeShotsOnGoal"]), _n(v["GuestShotsOnGoal"])
    o["home_saves"], o["guest_saves"] = _n(v["HomeSaves"]), _n(v["GuestSaves"])
    o["shot_clock"] = v["ShotClock"].strip() if v["ShotClockTens"] != " " or v["ShotClockOnes"] != " " else ""
    o["home_timeouts"] = (v["HomeTimeOut"].strip() or v["HomeFullTimeoutsRemaining"].strip())
    o["guest_timeouts"] = (v["GuestTimeOut"].strip() or v["GuestFullTimeoutsRemaining"].strip())
    for side in ("Home", "Guest"):
        o[side.lower() + "_penalties"] = sum(1 for i in (1, 2, 3) if v[f"{side}PenaltyPlayer{i}"].strip())
    _poss(v, o)
    o["horn"] = _flag(v["Horn"])


def _volleyball(v, o):
    o["set"], o["set_ordinal"] = v["Set"].strip(), v["SetOrdinal"]
    o["period"], o["period_ordinal"] = o["set"], o["set_ordinal"]
    o["game"] = v["Game"].strip()
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    o["home_sets"], o["guest_sets"] = v["HomeGamesWon"].strip(), v["GuestGamesWon"].strip()
    o["home_games"], o["guest_games"] = o["home_sets"], o["guest_sets"]
    o["home_serve"], o["guest_serve"] = _flag(v["HomeServe"]), _flag(v["GuestServe"])
    o["home_poss"], o["guest_poss"] = o["home_serve"], o["guest_serve"]
    o["home_timeouts"], o["guest_timeouts"] = v["HomeTimeout"].strip(), v["GuestTimeout"].strip()
    o["timeout_clock"] = v["TimeoutClock"].strip()


def _wrestling(v, o):
    _period(v, o, "Period", "PeriodOrdinal")
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    o["home_match_score"], o["guest_match_score"] = v["HomeMatchScore"], v["GuestMatchScore"]
    o["weight_class"] = v["WeightClass"].strip()
    o["advantage_time"] = v["AdvantageTime"].strip()
    o["advantage_home"], o["advantage_guest"] = _flag(v["AdvantageHome"]), _flag(v["AdvantageGuest"])
    o["horn"] = _flag(v["Horn"])


def _waterpolo(v, o):
    _period(v, o, "Period", "PeriodOrdinal")
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    o["shot_clock"] = v["ShotClock"].strip()
    o["home_timeouts"], o["guest_timeouts"] = v["HomeTimeouts"].strip(), v["GuestTimeouts"].strip()
    o["timeout_clock"] = v["Timeout"].strip()
    for side in ("Home", "Guest"):
        o[side.lower() + "_penalties"] = sum(1 for i in (1, 2) if v[f"{side}PenaltyPlayer{i}"].strip())


def _futsal(v, o):
    _period(v, o, "Period", "PeriodOrdinal")
    o["home_score"], o["guest_score"] = v["HomeScore"], v["GuestScore"]
    o["home_fouls"], o["guest_fouls"] = v["HomeFouls"].strip(), v["GuestFouls"].strip()
    o["home_timeouts"], o["guest_timeouts"] = v["HomeTimeOut"].strip(), v["GuestTimeOut"].strip()
    for side in ("Home", "Guest"):
        o[side.lower() + "_penalties"] = sum(1 for i in (1, 2, 3) if v[f"{side}PenaltyPlayer{i}"].strip())
    o["horn"] = _flag(v["Horn"])


def _tennis(v, o):
    o["set"], o["set_ordinal"] = v["Set"].strip(), v["SetOrdinal"]
    o["period"], o["period_ordinal"] = o["set"], o["set_ordinal"]
    o["home_score"], o["guest_score"] = v["TopPoints"].strip() or "0", v["BottomPoints"].strip() or "0"
    o["home_serve"], o["guest_serve"] = _flag(v["TopServe"]), _flag(v["BottomServe"])
    o["home_poss"], o["guest_poss"] = o["home_serve"], o["guest_serve"]
    o["home_name"] = (v["TopPlayerName"].strip() or v["TopTeamName"].strip() or v["HomeTeamName"].strip())
    o["guest_name"] = (v["BottomPlayerName"].strip() or v["BottomTeamName"].strip() or v["GuestTeamName"].strip())
    o["home_sets"] = [v[f"TopSet{i}Tens"] + v[f"TopSet{i}Ones"] for i in range(1, 6)]
    o["home_sets"] = [_n(s) for s in o["home_sets"]]
    o["guest_sets"] = [_n(v[f"BottomSet{i}Tens"] + v[f"BottomSet{i}Ones"]) for i in range(1, 6)]
    o["game"] = _n(v["GameNumberTens"] + v["GameNumberOnes"])


def _tabletennis(v, o):
    o["set"], o["set_ordinal"] = v["Set"].strip(), v["SetOrdinal"]
    o["period"], o["period_ordinal"] = o["set"], o["set_ordinal"]
    o["home_score"], o["guest_score"] = v["HomePoints"].strip() or "0", v["GuestPoints"].strip() or "0"
    o["home_sets"], o["guest_sets"] = v["HomeSetsWon"].strip(), v["GuestSetsWon"].strip()
    o["home_serve"], o["guest_serve"] = _flag(v["HomeServe"]), _flag(v["GuestServe"])
    o["home_poss"], o["guest_poss"] = o["home_serve"], o["guest_serve"]


def _generic(v, o):
    _period(v, o, "Period", "PeriodOrdinal")
    o["home_score"], o["guest_score"] = _n(v["Home"], "0"), _n(v["Guest"], "0")
    o["home_fouls"], o["guest_fouls"] = v["HomeFouls"].strip(), v["GuestFouls"].strip()
    o["home_timeouts"], o["guest_timeouts"] = v["HomeNumberOfTO"].strip(), v["GuestNumberOfTO"].strip()
    d = [v[f"ClockDigit{i}"] for i in (1, 2, 3, 4)]
    sep = "." if v["ClockMode"] == "." else ":"
    o["clock"] = f"{d[0]}{d[1]}{sep}{d[2]}{d[3]}".strip(" :.") if "".join(d).strip() else ""
    o["clock_running"] = v["ClockStatus"] == "R" or v["ClockRun"] == "R"
    o["play_clock"] = v["PlayClock"].strip()
    o["timeout_timer"] = v["TOTimer"].strip()


def _timer(v, o):
    o["clock"] = v["Clock"].strip()


_ALIASES = {
    "Football": _football, "Soccer": _soccer, "Basketball": _basketball, "BaseballSoftball": _baseball,
    "HockeyLacrosse": _hockey, "Volleyball": _volleyball, "Wrestling": _wrestling, "WaterPolo": _waterpolo,
    "FutsalHandball": _futsal, "Tennis": _tennis, "TableTennisBadminton": _tabletennis, "Generic": _generic,
    "Timer": _timer,
}
