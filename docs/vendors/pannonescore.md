# PannoneScore (`scoreboards/pannonescore.py`)

Id: `PannoneScore_Autodetect`. Wiring (catalog): RS-485/422, 38400.

## Framing
`82 ... xor 83`. Packet = first `82` to first `83`; checksum byte (second to last) = XOR of bytes 1 .. n-3. Failures are rejected.

## Autodetect
Byte 61 = sport code. `0` = basketball (only code known). Unknown codes keep the current layout; nothing is decoded before the first known code. Packets under 62 bytes are ignored.

## Nibble glyphs
Nibble A-F: `-`, `_`, `E`, `C`, degree sign, blank.

## Pages
Byte 1 selects three pages: 1 ABD, 2 ACE, 3 ABF, 4 ACG, 5 ABH, 6 ACD, 7 ABE, 8 ACF, 9 ABG, 10 ACI (B, C, I carry nothing used).
| page | content |
|---|---|
| A | bytes 2-3 clock: if high nibble of byte 3 is A, ss.t (2 hi/lo = seconds, 3 lo = tenths, mode `.`), else mm:ss (mode `:`); byte 4 = ShotClockSecondTens/Ones |
| F | HomeScoreHundreds = 51 lo, Tens/Ones = 52; GuestScoreHundreds = 53 lo, Tens/Ones = 54 |
| H | Period = 60 lo |
| D / E | Home / Guest FoulTens, FoulOnes = 60 hi/lo |
| G | if (byte 37 & 0x1F) == 3: byte 36 bit 7 clear sets HomeTimeouts, set sets GuestTimeouts, value = 38 lo |

Contract `Basketball`, event `Basketball`.

## Open questions
Only basketball is registered in ScoreConnect; other sport codes are unknown.
