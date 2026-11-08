# Eversan (`scoreboards/eversan.py`)

Source: ScoreConnect `Eversan.Main`, `Model9364`, `Model9775_9694` (Windows build; identical to Mac for these). Digits are 7-bit ASCII; the high bit is ignored and `:` (colon lamp) reads as blank. `EversanPeriod` and `EversanAscii` are private here.

## Wiring (catalog)
Wired RS-485 via PIC, serial decode, 57600 (nonstandard 621009N2 on some units); wireless via Laird XBee 57600; legacy ScoreLinkI RS-485 at 62100. Same for Eversan, Eversan V2, Model 9364, Model 9775 (wireless only for the first two).

## Framing
| Family | Start | Length | Checksum |
|---|---|---|---|
| Legacy (`Eversan_*`) | first byte 0x01 or 0x02 | byte 1 = total length | byte 2. Packets over 15 bytes: sum of bytes 6..L-1 (mod 256). Up to 15 bytes: ScoreConnect compares XOR of bytes 2..L-1 with byte 2, so bytes 3..L-1 must XOR to zero. |
| V2 (`EversanV2_*`) | the console's sport code | byte 1 = total length | XOR of bytes 4..L-1. Stored at byte 3 for codes 70 and 129 (also accepts byte 2 for 129), at byte 2 for 131, at byte 2 for 135 (also accepts byte 3). |
| Model 9xxx | 129 (9364) or 131 (9775/9694) | none | none; a packet ends where the next start byte begins (so it is released when the next packet starts) |

Deviation: for codes of 128 and above ScoreConnect searches for the first byte >= 128 and silently drops a frame starting with a different byte; we search for the configured code, with the same result on clean streams. Length bytes below 5 (V2) or 3 (legacy) are treated as noise. Short packets (too short for the layout) are ignored.

V2 codes: Baseball 135 or 70, Basketball 129, Football 129 (ScoreConnect forces 129), Football Code111 uses 129 (ScoreConnect takes the operator-entered vendor code; its decoder only accepts first byte 1 or 129, and the enum value 111 is not a wire code), Hockey 131, Lacrosse/Soccer 135.

## Common pieces
Clock `mm ss t` (offset noted per sport): if both minute digits are `0`, mode `.` with seconds.tenths from the next three characters, else mode `:` with tenths `0`.

## Sports (offsets are packet byte indexes; "A" = Eversan ASCII)
| Id | Contract / event | First byte | Fields |
|---|---|---|---|
| Eversan_Basketball_Code25 | Basketball | 1, 18 | clock@6; HomeScore 11-13 (hundreds digit-or-blank), GuestScore 14-16; fouls home 17-18, guest 23-24, foul player 19-20, count 22; Period from low nibble of byte 5 (8, 12, 14, 15 = 1-4); bit 0x10 of byte 5 clear = home possession `<`, set = guest `>`; HomeBonus byte 5 & 0x40, GuestBonus & 0x20 |
| | | 2 | ShotClockSecond 11-12 |
| Eversan_Basketball_Code29 | Basketball | 1 | clock@6; HomeScore 11-13, GuestScore 15-17, Period 14, HomeFoul 18-19, HomeTimeouts 20, foul player 21-22 count 23, GuestTimeouts 24, GuestFoul 25-26, ShotClock 27-28; possession bit 0x10 set = home (inverted vs Code25); bonus 0x40/0x20, double bonus 0x08 (home) / 0x04 (guest) |
| EversanV2_Basketball | Basketball | 129 | Code25 layout (clock, scores, fouls, period, possession, bonus) plus ShotClock 25-26 |
| Eversan_Football, EversanV2_Football | Football | 1, 129 | clock@6; HomeScore 12-13, GuestScore 14-15, ToGo 16-17, BallOn 18-19, Down 20, Quarter 21, timeouts 22/23; possession byte 4 & 0x40 clear = home `<` |
| EversanV2_Football_Code111 | Football | 1, 129 | same but ToGo 18-19, BallOn 16-17 |
| EversanModel9364_Football | Football | (129 framing) | Football layout, no first-byte check |
| Eversan_Lacrosse_Code15, Eversan_Soccer_Code15 | HockeyLacrosse / Soccer | 1 | clock@5; HomeScore 10-11, GuestScore 12-13, Period 14 |
| EversanV2_Lacrosse_Code135, EversanV2_Soccer_Code135 | same | 135 | clock@5; HomeScore 16-17, GuestScore 11-12, Period 10 |
| EversanModel9364_Lacrosse | HockeyLacrosse | (129 framing) | clock@6; scores 12-13 / 14-15; HomePlayerPopUp = bytes 20,16; GuestPlayerPopUp = 17,18; HomeShotOnGoal tens 19, ones 21; timeouts 22/23 |
| EversanV2_Baseball_Code135 / _Code70 | BaseballSoftball (Baseball) | 135 / 70 | Balls 7, Strikes 8, Outs 9, GuestRun 12-13, GuestHits 14-15, GuestErrors 16, HomeRun 17-18, HomeHits 19-20, HomeErrors 21, GuestInning1-10 22-31, HomeInning1-10 32-41. Inning is derived: from inning 10 downward the latest inning with a guest entry; no home entry = bottom of that inning, home entry too = top of the *next* inning (ScoreConnect behaviour); nothing entered = 01 |
| EversanV2_Hockey_Code131 | HockeyLacrosse (Hockey) | 131 | clock@6; HomeScore 13-14, Period 15, GuestScore 17-18, SOG 22-23 / 24-25; penalty players 6 bytes each (number 2, minutes tens, minutes ones, seconds 2): home 26, 32; guest 38, 44. Minutes tens is always blank |
| EversanModel9694_Hockey | same | 131 | as above, but minutes tens read from bytes 28, 34, 40, 46 |
| EversanModel9775_Hockey | same | any | clock@7; HomeScore 12-13, GuestScore 14-15, SOG ones 17 / 19; penalties home 20, 26; guest 32, 38; minutes tens blank |

## Open questions
- `EversanModel9694_Hockey` has no row in ScoreConnect's config database; registered anyway as requested.
- The catalog lists `EversanV2_Football_Code111` with event type Basketball; the decoder produces a Football contract.
- No real captures were available; tests use synthetic frames built from the framing rules above.
