# Sportzcast sbdata input (`scoreboards/sportzcast.py`)

Decodes another Sportzcast bot or controller's 150-character `sbdata` stream back into a contract. Source: ScoreConnect `SportzCast.Main` and `SportzCast.VirtualBot`. The `Contracts.Ingress` classes are a separate JSON/HTTP path (numbers in, contract out) and are not used.

## Wire format and wiring
- 150 ASCII characters followed by LF (0x0A). Characters 0-1 are the sport code. No checksum.
- A frame is valid only if exactly 150 bytes precede the LF. Anything else is rejected and consumed (this includes garbage before a frame, which fails as a short/long line).
- Catalog: SportzCastSbData, wired RS-232 via PIC, no decode, 19200 baud. Virtual Bot has no hardware.

## Standard clock (`SetClock`)
Used by baseball, softball, football, basketball, hockey, lacrosse, soccer, volleyball, futsal, handball, table tennis, badminton.
- Offset 116 `R`/`S` (case-insensitive) sets `InternalClockStatus`; other values leave it unchanged.
- Offset 117 or 118 `:` or `.` sets `ClockMode` (118 wins). The mode is sticky.
- Mode `:` or blank: minutes tens/ones = 2,3; seconds = 4,5; tenths `0`. Mode `.`: minutes `00`, seconds = 2,3, tenths = 4.

Wrestling, swimming, tennis, water polo and generic read the clock fields directly (below).

## Per-sport offsets (0-based, every value is one character unless a range is shown)
| Sport (id) | Contract / event | Fields |
|---|---|---|
| Football (code 02) | Football | PlayClockTens/Ones 8-9, Flag 10, HomeScore 11-12, Horn 13, GuestScore 14-15, Home/GuestPossession 16/17, Home/GuestTimeouts 18/19, Down 20, ToGo 21-22, BallOn 23-24, Quarter 25, names 26-33 / 34-41, yards (4 each) 42..65 (home rush, pass, total, visitor rush, pass, total), first downs 66-67 / 68-69, quarter scores (2 each) home 70-77, visitor 78-85 |
| Soccer (08) | Soccer | HomeScore 11-12, HomePossession 13, GuestScore 14-15, GuestPossession 16, shots 17-18 / 20-21, corners = char 47 then 19 (home), 48 then 22 (guest), saves 23-24 / 25-26, timeouts 27/28, Period 29, names 31-38 / 39-46, penalties 49-50 / 51-52 |
| Basketball (03) | Basketball | double bonus 6/7, ShotClock 8-9, HomeScore 10-12, GuestScore 13-15, possession 16/17, timeouts 18/19, bonus 20/21, fouls 22-23 / 24-25, foul player 26-27 + count 28, Period 29, Horn 30, names 31/39, players (number, foul, points): home 47/49/50, 52/54/55, 67/69/70, 72/74/75, 77/79/80; guest 83/85/86, 88/90/91, 93/95/96, 121/123/124, 126/128/129; Full/Partial timeouts 60/62/64/66, HomeBottomCenter 82, TimeoutClock 112,114,115 |
| Baseball 01 / Softball 04 | BaseballSoftball | Balls 6, Strikes 7, Outs 8, Inning 9-10, GuestRun 11-12, HomeRun 13-14, TopBottomInning 15, hits 16-17 / 18-19, errors 20/21, AtBat 22-23, ErrorFlag 24, GuestErrorNumber 25, TopOfInning 26, BottomOfInning 27, innings guest `28+2n`, home `29+2n` (n = 1..10), names 50-57 (guest) / 58-65 (home), bases 66-68, PitchSpeed 69-71, PitchCount 72-74 |
| Hockey 05 / Lacrosse 07 | HockeyLacrosse | ShotClock 8-9, HomeScore 11-12, HomeGoal 13, GuestScore 14-15, GuestGoal 16, TimeOut 18/19, PlayerPopUp 20-21 / 22-23, SOG 24-25 / 26-27, Period 29, Horn 30, names 31/39, penalty boxes 6 chars each (number tens/ones, minutes tens/ones, seconds tens/ones): home 47, 53, 59; guest 65, 71, 77; timeouts remaining 83-86, saves 87-88 / 89-90, possession 91/92, penalty types (2 chars per player) home 119-124, guest 125-130 |
| Futsal 29 / Handball 30 | FutsalHandball | HomeScore 11-12, GuestScore 13-14, TimeOut 15/16, Fouls 17/18, Period 19, Horn 20, names 21/29, penalty boxes as hockey (home 47, guest 65, three each) |
| Volleyball (06) | Volleyball | HomeGamesWon 6, HomeScore 7-8, GuestGamesWon 9, GuestScore 10-11, serve 12/13, timeout 14/15, set scores (2 chars) home `16+4(n-1)`, guest `18+4(n-1)` for sets 1-4, set 5 home 102-103 / guest 104-105, IsSet3 106, Set 119, Game 120, names 32/40, players (number 2, kills 1, digs 2): home 48 + 5(n-1) for n=1..6, guest 78 + 5(n-1) for n=1..4, guest 5 at 121, guest 6 at 126 |
| Wrestling (12) | Wrestling | status 116, mode 117, play-clock status 118; clock mm ss t = 2-6; HomeMatch 8-10, HomeScore 11-12, HomeMatchScore 13-14, GuestScore 15-16, GuestMatchScore 17-18, WeightClass 19-21, Advantage time 22-24, AdvantageHome/Guest 25/26, Period 29, Horn 30, names 31/39 |
| Swimming (13) | SwimmingDetail | status 116, mode 117, play-clock status 118, clock 2-6; lane n=1..8 starts at `7+11(n-1)`: FinishFlag, Split (2), Place, Clock (7 chars) |
| Tennis (16) | Tennis | ClockHour 2-3, ClockMinutes 4-5, Set 6, points 7-8 / 9-10, set games ones top 11-15 / bottom 18-22, tens top 86-90 / bottom 91-95, serve 16/17, Court 23, game number ones 24 / tens 85, team scores 25-26 / 27-28, IsDeuce 29, Advantage 30, player names 31/39, team names 47/55, IsTieBreak 63, tie-break scores (2 chars) top `64+4(n-1)` bottom `66+4(n-1)`, IsSet3 84, PacketTwittle 97 |
| Water polo (24) | WaterPolo | clock mm 2-3, ss 5-6, tenths 8, hundredths 9, ShotClock 10-11, Period 12, timeout clock 13,15,16, GuestScore 17-18, GuestTimeouts 19, HomeScore 20-21, HomeTimeouts 22, names 23/31, penalty boxes home 39, 45; guest 51, 57; status 116, mode 117 |
| Table tennis 31 / Badminton 32 | TableTennisBadminton | Set 6, points 7-8 / 9-10, sets won 11/12, serve 13/14, set points home `15+4(n-1)`, guest `17+4(n-1)` (n=1..4), names 31/39 |
| Generic (28, autodetect only) | Generic | time-out timer 2-4, ClockDigit1-4 5-8, Home 9-11, Guest 12-14, Period 15, fouls 16/17, timeouts 18/19, ClockMode 20, status 21, PlayClockStatus 22, PlayClockDisplay 23, PlayClock 24-25 |

## Autodetect (`SportzcastSBData_Autodetect`) and Virtual Bot (`Sportzcast_VirtualBot`)
Code to layout: 01 baseball, 02 football, 03 basketball, 04 softball, 05 hockey, 06 volleyball, 07 lacrosse, 08 soccer, 12 wrestling, 13 swimming, 16 tennis, 24 water polo, 28 generic, 29 futsal, 30 handball, 31 table tennis, 32 badminton.
- Autodetect re-selects whenever a known, different code arrives; the new layout starts with a fresh contract.
- Virtual Bot picks the layout from the first packet and keeps it. Codes 28-32 are not accepted by the Virtual Bot (a first packet with one raises and counts as a bad packet).
- Contract, event and field dict follow the selected layout.

## Notes and open questions
- ScoreConnect's Autodetect builds its code from the byte values (`"{b0}{b1}"`, so ASCII "02" becomes "4850" and never matches). That looks like a bug, so we use the ASCII digits and also accept the raw form for compatibility (binary 0x00 0x02 gives "02" in decimal concatenation).
- `SportzcastSBData_Generic` is in the catalog but not in this assignment; the layout exists here (used by Autodetect code 28).
- Mac and Windows builds have identical decoders for this module.
