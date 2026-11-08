# Electro-Mech (ElectroMech V2)

Module `scoreboards/electromech.py`; tests `tests/test_sb_electromech.py`. Source: ScoreConnect `Electromech.Main.*`.

## Wiring (catalog.json, vendor "ElectroMech V2")
| Connection | Hardware | Serial hint |
|---|---|---|
| Wired | `PIC_CURRENTLOOP_NODECODE_2400_INVERTED` | `MODEDELAY_DELAY6_STRTCHR02_STPCHR04_INT4D` |
| Wireless | `LAIRD_XBEE_NODECODE_57600_NORMAL` | `MODEDELAY_DELAY3_STRTCHR02_STPCHR04_INT4C` |

The PIC is not decoding: raw current-loop bytes (2400 baud, inverted) or XBee bytes (57600) arrive as-is.

## Wire format
The console sends 2-byte cells, continuously, with no checksum or header.

    byte A: 0 d6 d5 d4 d3 d2 d1 d0
    byte B: 1 a4 a3 a2 a1 a0 flag d7
    address = (B & 0x7C) >> 2    flag = B & 2    value = (d7<<7) | (A & 0x70) | (A & 0x0F)

Framing: find the first byte with bit 7 set; the packet is that byte plus the one before it; everything up to
and including it is consumed (garbage before it is dropped). A bit-7 byte at the start of the buffer (no data
byte in front) is dropped and counted as a rejected packet. Nothing else can be validated. ScoreConnect waits
until the buffer holds more than 3 bytes before decoding, so it lags one cell; ScoreReader decodes at once.

Value helpers: `Bcd(v,1)` / `Bcd(v,0)` = high / low hex nibble of `v` (A-F read as blank); `Digit(v)` = standard
7-segment byte (bit 7 ignored); `BZ` = leading zero blanked; `flag` = B bit 1.

## Clock (Football, Basketball, Soccer, LxSoccer)
Minutes and seconds arrive in different cells, so the decoder keeps a 6-char clock `[mode, m, m, s, s, t]` and
a "running" detector (previous text differs by exactly 1 or 10 units; stays "running" for 2 more cells). While
running it repairs half-updated values at rollovers (minutes ticked but seconds not yet 59, and the reverse,
or seconds wrapping at 0.0 in tenths mode). Output: mode `:` gives minutes (tens blanked when 0), seconds,
tenths `0`; mode `.` gives minutes `00`, seconds (tens blanked), tenths. Mode comes from the period cell flag
(flag set = `:`), or on LX boards from the low nibble of the seconds cell (blank nibble = `.`). Cells for the
clock are ignored until a mode has been seen. Quirk kept: after a stale start the first rollover repair can pick
the wrong minute until a few ticks have been seen.
Hockey, Volleyball and LxHockey/Lacrosse do not correlate; they write fields straight from the cells using the
current `ClockMode` (anything but `.` is treated as mm:ss).

## Layouts (address -> contract field)
**Football** (Football/Football): 1 minutes, 0 seconds, 2 Quarter=Digit + mode(flag); 8 HomeScoreTens(BZ)/Ones, flag -> HomePossession `<` (and clears Guest), else Home blank; 9 same for Guest `>`; 16 GuestTimeouts=hi, HomeTimeouts=lo; 12 ToGoTens(BZ)/Ones; 13 BallOnTens(BZ)/Ones; 14 Down=Digit.

**Basketball** (Basketball/Basketball): 1/0 clock; 2 Period=Digit + mode(flag); 4 ShotClockSecondTens/Ones; 8 Home score (flag -> Hundreds `1`, tens blank-zero relative to hundreds); 9 Guest score; 15 HomeTimeouts=Digit; 11 GuestTimeouts=Digit; 10 low nibble bits: 1 HomePossession `<`, 2 GuestPossession `>`, 4 HomeBonus `B`, 8 GuestBonus `B`; 12 HomeFoulTens=flag?`1`, HomeFoulOnes=lo, GuestFoulOnes=hi; 13 GuestFoulTens=flag?`1`, FoulPlayerTens=hi, FoulPlayerOnes=lo; 14 FoulPlayerNumberOfFouls=Digit.

**Basketball_SwappedTeams**: identical cells, with teams exchanged. ScoreConnect does *not* call `Sport.SwapTeamInformation`; it has a second decoder class with every Home/Guest field exchanged: 8 -> Guest score, 9 -> Home score, 15 -> GuestTimeouts, 11 -> HomeTimeouts, 10 bit1 GuestPossession `>`, bit2 HomePossession `<`, bit4 GuestBonus, bit8 HomeBonus, 12 -> Guest fouls tens/ones + HomeFoulOnes, 13 -> HomeFoulTens. The possession arrows stay with their team (`<` home, `>` guest). Clock, period, shot clock and foul-player cells are not team-specific. Our output is therefore already swapped.

**Soccer** (Soccer/Soccer): 1/0 clock; 2 Period + mode; 4 ClockSecondTens/Ones (overwrites the clock seconds, kept as is); 8/9 Home/Guest score (BZ); 12 HomeShotTens(BZ)/Ones; 13 GuestShot.
**LxSoccer**: 20 minutes, 21 seconds+mode; 31 Period=Digit; 25 Home score, 24 Guest score.

**Hockey** (HockeyLacrosse/Hockey): 1 minutes (mode `.`: minutes 00, seconds), 0 seconds/tenths; 2 Period + ClockMode(flag); 4 ShotClockTens/Ones; 8 HomeScore hi/lo (not blanked); 9 GuestScore; 11/10 GuestShotOnGoalTens/Ones (Digit); 15/3 HomeShotOnGoalTens/Ones (Digit); Guest penalty 1: 12 seconds, 13 minutes ones (lo) + PlayerOnes (hi), minutes tens blank, 14 PlayerTens (Digit); Guest penalty 2: 16 seconds + HomeGoal=`G` if flag, 17 minutes/player ones + GuestGoal=`G` if flag, 18 PlayerTens; Home penalty 1: 24/25/26; Home penalty 2: 28/29/30. (Goal lamps ride on the guest slot-2 cells; real behaviour, not a typo.)
**LxHockey / LxLacrosse** (HockeyLacrosse/Hockey or Lacrosse, same layout): Guest P1 0 player(hi tens, lo ones), 1 seconds, 2 minutes ones (Digit); Guest P2 12/13/14; Home P1 8 player, 9 seconds, 10 minutes tens/ones (BCD); Home P2 26 PlayerTens, 27 PlayerOnes, 3 SecondTens, 11 SecondOnes, 15 minutes ones (all Digit); 16 HomeShotOnGoal hi/lo + HomeGoal(flag); 17 Guest likewise; 4 shot clock; 20 minutes; 21 seconds/tenths, ClockMode `:` when low nibble is a digit else `.`; 31 Period=Digit; 24 HomeScore (BZ); 25 GuestScore.

**Volleyball** (Volleyball/Volleyball): 1/0 clock (direct); 2 ClockMode only (no period cell); 8/9 scores (BZ); 15 HomeTimeout=Digit; 11 GuestTimeout=Digit; 12 HomeGamesWon=lo, GuestGamesWon=hi; 13 Game=lo.

**Baseball / Softball** (BaseballSoftball, event Baseball or Softball): 4 home runs (BZ; clears InningTens), 5 guest runs (BZ) + ErrorFlag `E` if flag, 6 InningOnes=Digit (if it changed, TopBottomInning=`T`), 12 Balls=lo, Strikes=hi (blank->0), 13 Outs=lo (if it drops while `T`, TopBottomInning=`B`).
**LxBaseball**: same but 8 home runs, 9 guest runs, 10 inning; 12, 13 unchanged.
**BaseballSoftball14x15x**: 12 HomeRun, 13 HomeHits, 8 GuestRun, 9 GuestHits (all BZ), 10 GuestErrors, 14 HomeErrors (Digit), 5 balls/strikes, 6 Outs=Digit (drop while `T` -> TopBottomInning `B`, TopOfInning ` `, BottomOfInning `.`), 16 Inning tens/ones BCD (greater than the stored inning -> `T`, TopOfInning `.`, BottomOfInning ` `), 4 AtBat tens/ones.
**LineScoreBaseball**: 0 HomeRun, 1 HomeHits (BZ), 2 InningOnes=Digit, InningTens=`1` if value bit 7, 3 HomeErrors, 4 AtBat, 5 balls/strikes, 6 Outs=Digit, 7 GuestErrors, 14 value bit7 -> top (`T`, `.`, ` `), 15 bit7 -> bottom (`B`, ` `, `.`), 16 GuestRun, 17 GuestHits (not blanked), 19 GuestErrors; line score: Home 8..13, Guest 24..29: cells 8/9/12/13 (and 24/25/28/29) hold two innings (lo = earlier: 8 -> inn 1,2; 9 -> 3,4; 12 -> 7,8; 13 -> 9,10), 10, 11 (26, 27) one inning each (Digit, innings 5, 6).

## Open questions / oddities
- LineScoreBaseball: address 7 and address 19 both set `GuestErrors`; address 19 wins. Probably one was meant for another field; kept.
- Soccer address 4 writes the clock seconds directly (likely a stop-time/second clock on the real board).
- ScoreConnect's frame loop holds back the last cell until 4+ bytes are buffered; not reproduced.
- No sample capture from real hardware; the tests use synthetic cells built from the layouts above.
