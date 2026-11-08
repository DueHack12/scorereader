# Harris Time (`scoreboards/harristime.py`)

Ids: `HarrisTime_Basketball`, `HarrisTime_Hockey` (CTL2K), `HarrisTimeV2_Hockey`.
Wiring (catalog): Harris Time RS-485/422 115200 or XBee 115200; V2 RS-232 9600.

## CTL2K framing
Packet = first `:` (0x3A) through the first LF (0x0A), at least 74 bytes. Decoded only if bytes 1-4 are `4321`.
ScoreConnect regenerates a checksum into bytes 70-71 but never compares it (its test is always 0), so **no checksum is verified**; only the length is. A LF with no `:` before it is dropped.

## CTL2K digit coding
Bytes `0x20-0x39` are ASCII. Digits with a status flag are sent as `'0'..'9'` plus 12+11*(k-1) for k = 1..7 (ranges 60-69, 71-80, 82-91, 93-102, 104-113, 115-124, 126-135). Anything else is blank.

## Basketball (contract `Basketball`)
| byte | field |
|---|---|
| 9,10 / 15,16 | Home/Guest ScoreTens/Ones (HomeScoreHundreds = `1` if byte 9 > 57; same for guest byte 15) |
| 11-14 | clock. If byte 14 is blank: seconds.tenths from 11,12,13, mode `.`; else mm:ss, mode `:` |
| 17 | Period |
| 18,19 / 20,21 | Home/Guest FoulOnes / Timeouts |
| 22,23,24 | FoulPlayerOnes, FoulPlayerTens, FoulPlayerNumberOfFouls |
| 25,26 | ShotClockSecondTens/Ones |
| 10 / 16 | Bonus = `B` if byte > 60, DoubleBonus = `B` if byte > 71 (home / guest) |
| 12 | possession: 104-114 home `<`, 60-70 guest `>`, else unchanged |
| 58 | Horn: `H` unless byte is `'0'` |

## Hockey (contract `HockeyLacrosse`, event `Hockey`)
Clock 11-14 (mm:ss), HomeScore 9,10, GuestScore 15,16, Period 17, HomeShotOnGoal 18,19, GuestShotOnGoal 20,21, then four 5-byte penalty blocks (Tens, Ones, ClockMinutesOnes, ClockSecondTens, ClockSecondOnes) from byte 22: Home P1, Home P2 (27), Guest P1 (32), Guest P2 (37).

## V2 hockey
Packet = first `@` of the first `@@` through the second `#` of the first `##`; must be exactly 62 bytes. Plain ASCII, **least significant digit first**: clock 15=sec ones,16=sec tens,17=min ones,18=min tens; home score 20 ones,21 tens; guest 23,24; Period 26; home SOG 28,29; guest SOG 31,32; penalty blocks (SecondOnes, SecondTens, MinutesOnes, Ones, Tens) at 34 (home 1), 40 (home 2), 46 (guest 1), 52 (guest 2). ClockMode `:`.

## Oddities
- Bonus tests use `> 60` / `> 71`, so a digit `0` with flag 1 (byte 60) does not light the bonus.
- Possession is carried on the clock minutes-ones byte and keeps its last value when neither range matches.
- Open: the real checksum encoding in bytes 70-71 is unknown.
