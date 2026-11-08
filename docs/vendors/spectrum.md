# Spectrum scoreboards (`scoreboards/spectrum.py`)

Raw serial (`NODECODE`), 9600 baud, RS485/422 (PIC) or RS232; Spectrum MS250 has no catalog wiring entry.
No checksums. Characters are 7-bit ASCII (the high bit is masked); `:` reads as blank. On V2E and the baseball
layout `F` also reads as blank.

## Framing
| Family | Ids | Framing |
|---|---|---|
| V2 | `SpectrumV2_Basketball` | text line, first byte `>`, ends with LF (a leading or empty line is rejected) |
| V2W | `SpectrumV2W_*` | data ends with LF; data length must be 35, 41 or 44 |
| V2E | `SpectrumV2E_*`, `SpectrumMSX_Hockey` | frame ends `LF NUL`; length counted up to and including the LF must be 36 or 44 |
| MS250 | `SpectrumMS250_Baseball` | 13 bytes starting `00 0F`, no terminator |

Garbage glued to the front of a V2W/V2E frame changes its length and the frame is rejected (as in
ScoreConnect); the next frame is fine. Every decoder only reads bytes 1..31 (baseball up to 40).

## V2 basketball text
`>MM:SS.t,home,guest,period<` (the first and last characters are dropped, then split on commas). If MM is `00`
the clock is `.` mode: seconds = chars 3-4, tenths = char 6; otherwise `:` mode. Scores are 1-3 right-aligned
characters (hundreds/tens blank when absent); period is the first character of field 3.

## V2W / V2E byte map (index into the packet, byte 0 is the start byte)
Clock minutes tens/ones 1-2, seconds tens/ones 3-4, home score tens/ones 5-6, guest 7-8.

| Contract field | Football | Soccer | Basketball | Volleyball |
|---|---|---|---|---|
| To go tens/ones | 9, 10 | | | |
| Ball on | 15, 16 | | | |
| Down | 21 | | | |
| Home / guest timeouts | 22 / 24 | | 30 / 31 | |
| Quarter / period | 23 | 12 | 23 | |
| Play clock | 25, 26 | | | |
| Home shots tens/ones, guest shots | | 9-10, 15-16 | | |
| Penalties home / guest (2 chars, byte order reversed) | | 22,21 / 24,23 | | |
| Shot clock | | | 25, 26 | |
| Fouls home tens/ones, guest tens/ones | | | 21,22 / 16,24 | |
| Games won home / guest, set | | | | 22 / 24, 23 |

Possession: V2W football byte 12 bit 0 = home, bit 1 = guest. V2E football: byte 12 == `5` home, == `A` guest.

Basketball status bytes (V2E subtracts 7 first from any status byte >= 64):

| Meaning | V2W | V2E |
|---|---|---|
| mm:ss clock (else SS.t) | byte 12 bit 3 | adjusted byte 12 bit 3 |
| possession home / guest | byte 12 bit 0 / 1 | adjusted byte 12 bit 0 / 1 |
| score hundreds home / guest ("1") | byte 14 bit 0 / 1 | adjusted byte 14 bit 0 / 1 |
| bonus home / guest | byte 14 bit 2 / 3 | adjusted byte 14 bit 2 / 3 |
| double bonus home / guest | byte 11 bit 3 / 2 | adjusted byte 11 bit 3 / 2 |

Full/partial timeout fields are set to blank. Sub-minute clock reads seconds/tenths from bytes 1-3.

## Baseball (V2W and V2E, ASCII)
Balls 1, strikes 2, outs 3, home runs 5-6, guest runs 7-8, at bat 9-10, home hits 15-16, guest hits 17-18, home
errors 19, guest errors 20. Line score: guest inning N at 19+2N, home inning N at 20+2N (N = 1..10).
The current inning and half are derived from the line score (highest inning with a non-blank home entry =
bottom, else a guest entry = top; none = inning 01, top).

## MS250 baseball (13 bytes, `00 0F` header)
Inning ones = low nibble of byte 2; home runs tens/ones bytes 3/4; guest runs bytes 5/6 (low nibbles).
Balls byte 10 & 7: 0,1,3,7 = 0,1,2,3. Strikes byte 11 & 3: 0,1,3 = 0,1,2. Outs byte 12 & 3: 0,1,3 = 0,1,2.
Other patterns leave the previous value. Top/bottom: byte 11 bit 2 clear = T, set = B. No inning tens.

## MSX hockey (V2E framing)
Clock minutes 1-2, seconds 3-4, home score 5-6, guest score 7-8, period 23 (all V2E ASCII). Byte 12: after
subtracting 7 when >= 64, bit 3 set = `MM:SS`, else `SS.t` from bytes 1-3. Possession: byte 12 == `5` home,
== `A` guest (raw byte). Penalties only in 44-byte frames (minutes tens always blank):

| Slot | Player tens/ones | Minutes ones | Seconds tens/ones |
|---|---|---|---|
| Home 1 | 20, 21 | 22 | 24, 25 |
| Home 2 | 31, 32 | 33 | 34, 35 |
| Guest 1 | 26, 27 | 28 | 29, 30 |
| Guest 2 | 36, 37 | 38 | 39, 40 |

Taken from the newer Windows ScoreConnect decompile; shots, saves and timeouts are not provided.

## Quirks reproduced
* V2W football tests `(byte12 & 8) == 1`, which is never true, so its clock is always `MM:SS`.
* Baseball frames shorter than 41 bytes fill only the fields they reach; ScoreConnect would throw partway through.
* MS250 framing: ScoreConnect does not discard bytes before the `00 0F` header; here they are discarded.
* V2 basketball: an empty line stalls ScoreConnect's framer; here it is rejected.

## Open questions
* No captures were available. Which console models send the 41-byte V2W frame, and whether baseball always
  uses the 44-byte one, is unknown.
* The V2E "minus 7" status bytes look like ASCII letters standing in for nibbles above 9.
