# Fair-Play, plain RS-485 layout (`scoreboards/fairplay.py`)

Covers ScoreConnect's `Fairplay.Main` ids (vendor "Fairplay", catalog id 2). Wiring: `PIC_RS485/22_NODECODE_57600_NORMAL` (raw bytes, no PIC decode), serial settings `STRTCHR02 STPCHR04`.

## Framing
```
code  type  ??  L  data[L]  sum_lo  sum_hi          total = L + 6
```
- `code` = the catalog `vendor_sport_code` (also the sport selector on the console). The protocol searches the stream for the first byte equal to its code.
- Trailer: 16-bit little-endian sum (not truncated) of every byte before it.
- Bad sum: drop one byte and search again; counted via `reject()`.
- `type`: `0x81` main scoreboard, `0xC1` second clock (shot / play clock, byte 7), `0xB1` home players, `0xB4` guest players (basketball).
- Data byte `n` of the sub-packet is packet offset `n`; offsets below are packet offsets. Most fields are packed BCD (`hi`/`lo` nibble; A-F read as blank).
- Clock (0x81, bytes 4-5): if the low nibble of byte 5 is a digit it is `MM:SS` (tenths `0`); otherwise `.` mode, `SS.t` with seconds in byte 4 and tenths in the high nibble of byte 5.
- Autodetect (not implemented here): ScoreConnect maps code byte -> id (0,1,2,4,5,6,9,10,11,12 basketball; 13,14 hockey; 21 lacrosse; 22,36 soccer; 23-27 football; 30-35 baseball/softball).

## Fields (0x81 unless noted)
| Sport (ids) | Fields |
|---|---|
| Football 23-27 | scores 6 / 7; Down hi8, Quarter lo8; ToGo 9; HomePossession `<` p10&8, GuestPossession `>` p10&4; Horn p11&0x30; BallOn 12; Timeouts 13 (home hi, guest lo); 0xC1: PlayClock 7 |
| Basketball 1,2,9,10,11,12 | scores 6/7 (+ hundreds `1` from p10&0x30 / &0xC0); Timeouts 16 (hi/lo); Horn only if p11&0x30 == 0x30; possession `<` p10&2, `>` p10&1; Bonus p10&8 / &4; DoubleBonus p11&2 / &1; team fouls 12/13; FoulPlayer 14; FoulPlayerNumberOfFouls lo15; Period lo8; 0xC1 ShotClockSecond 7; 0xB1/0xB4 players 1-5: number 4-8, points 12-16, fouls lo20-24 |
| Basketball 5, 6 | as above without the double-bonus lamps |
| Basketball 0 | scores, possession, Bonus, DoubleBonus, Period; Horn if *either* p11 horn bit; no timeouts/fouls/shot clock |
| Basketball 4 | as 1 but HomeTimeouts hi8, GuestTimeouts hi15; no double bonus, no player pages |
| Volleyball 0 | scores 6/7, Game lo8 |
| Volleyball 4 | scores; Game hi16; Set lo8; GamesWon lo12/lo13; Set1 20/21; Set2 22/23; Set3 30/31; Timeout hi8 / hi15; Serve p10&0xF: 2 home `*`, 1 guest `*` |
| Hockey 13 | scores 6/7; Period lo8; penalties: players 15,16 (home) 23,24 (guest); minutes hi/lo of 12 (home) 20 (guest); seconds 13,14 / 21,22; 0xC1 ShotClock 7 |
| Hockey 14 | as 13 with ShotOnGoal 12/13, home penalties players 23,24 minutes 20 seconds 21,22, guest players 31,32 minutes 28 seconds 29,30 |
| Lacrosse (21) | scores 6/7, Period lo8, 0xC1 ShotClock 7 |
| Soccer 22 | scores; Shots 12 / 15; possession p11&2 `<`, &1 `>`; Saves 13 / 16; Corners lo14 / lo17; Period lo8 |
| Soccer 36 | scores; Shots 8 / 9; Period = 7-segment digit in byte 10 |
| Baseball 30 | Balls/Strikes/Outs = hex letters A,B,C -> 1,2,3 (high nibble 8; low nibble 9; high nibble 9; zero shows blank); Inning 8 (shares the balls nibble); runs 6/7; byte 10 low nibble 0/4 top (pitch count from 13), 8 bottom (pitch count from 12); high nibble 4 none, 6 `H`, 5/7 `E` |
| Baseball / Softball 31 | Balls hi8, Strikes lo9, Outs hi9, InningOnes lo8, runs 6/7, AtBat 5; p10: 0x20 `H`, 0x10 `E`, 4 top, 8 bottom |
| Baseball 32 | as 30's lamps, InningOnes lo8, runs 6/7, flags as 31 |
| Baseball 33 | Balls hi6, Strikes lo6, Outs lo9, errors guest hi5 / home hi8, hits ones lo5 / lo8 (tens `1` from p10&0x0C / &0x03), InningTens `1` if p10&0x30, InningOnes hi9, runs guest 4 / home 7, AtBat 12, p10&0x40 top, &0x80 bottom |
| Baseball 34 | Balls hi9, Strikes lo8, Outs hi8; line score 10 innings, guest 12-16, home 20-24 (low nibble = odd inning); runs guest 17 / home 25; hits 5 / 7; errors lo6 (guest) / hi6 (home); AtBat 4; inning number and half derived from the line score |
| Baseball 35 | Balls hi8, Strikes hi16, Outs = byte 18 (0xBF 0, 0x86 1, 0xDB 2); line score 9 innings, guest 4-8 (9th = lo8), home 12-16 (9th = lo16); runs 9 / 17; AtBat 20 |

All baseball ids also set `InternalClockStatus=" "` and `ClockMode=":"` on every packet.

## Oddities kept from ScoreConnect
- Softball_Code31 uses the baseball decoder and so reports `EventId` "Baseball" although the catalog says Softball.
- Volleyball 4 writes Set 3 twice (28/29 then 30/31); the later pair wins.
- Baseball 34 derives the inning by scanning the line score from the 10th column down: home column filled = bottom, else guest filled = top; the inning number counts down from 10 for each empty column pair. Empty columns must read blank (BCD A-F), unset ones are treated as filled.
- Baseball 30 shows balls/strikes/outs as blank when the count is 0 (only A, B, C map to digits).
- Baseball 34/35 `ClockMode`/`InternalClockStatus` are fixed.

## Open questions
- Autodetect and "Fairplay_Basketball_Code5" / "Fairplay_Football_Code24" are in the same ScoreConnect table; code 5 and 24 are registered here too although outside the assignment id list.
- No real captures were available; all layouts come from ScoreConnect's decoders. Hundreds-of-score bits and the second-clock packet (0xC1) are the least certain.
