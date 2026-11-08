# Westerstrand (`scoreboards/westerstrand.py`)

Ids: `Westerstrand_Basketball` (Basic 250, RS-485 115200) and `Westerstrand200_basketball` (Basic 200, RS-485 19200).
Both: wired, ScoreLink start 0x02 / stop 0x03, no decode.

## Basic 250
90-byte frame `02 … 03 chk`; `chk` = XOR of bytes 1..88 (ETX included). The scan takes the first ETX, the first STX
before it, and consumes through the checksum byte. A wrong length or checksum is counted as bad.

| Bytes | Field |
|---|---|
| 5,6 / 8,9 | clock MM:SS; if byte 9 is blank the clock is SS.t (5,6,8) |
| 7 | `A` -> InternalClockStatus S, `B` -> R |
| 13-15 | shot clock; byte 15 `.` -> ones 13, tenths 14 |
| 31-33 | home score (byte 33 blank -> two digits at 31,32) |
| 34-36 | guest score |
| 74 | Period (unchanged if blank) |

## Basic 200
`3F … 03 chk`, variable length. `chk` = XOR of all bytes from `3F` through the ETX; a result of 2 or 3 is sent as 0x20.
Record type is `packet[4]`:

| Type | Content |
|---|---|
| `!` (33) | game clock at 6-9 (byte 9 blank -> SS.t at 6,7,8) |
| `$` (36) | p5 blank: shot clock (p7 `.` -> ones 6, tenths 8; else tens 6, ones 8); p5 `$` and p10 `C`: game clock; p5 `$` and p10 blank: timeout clock seconds 6,7 |
| `&` (38) | p5 `!` home score at 6-8; p5 `)` guest score at 6-8 |
| `%` (37) | p5 `"`: possession (p6 blank, p7 `8` -> guest `>`; p6 `8`, p7 blank -> home `<`); other than `%`: Period = p6 |
| `#` (35) | p5 `$`: guest fouls 6,7; otherwise home fouls 5,6 |

Quirks kept: a two-digit guest score (byte 8 blank) reads as ones = byte 7 only. Short records are padded with blanks.

## Open questions
- No captures; the Basic 200 guest score and foul layouts look odd and should be checked on a real board.
