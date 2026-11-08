# Atlas Servis CZ (`scoreboards/atlasservis.py`)

Id: `AtlasServisCZ_Basketball` (contract `Basketball`). Wiring (catalog): RS-485/422 or RS-232, 38400.

## Framing (as ScoreConnect does it)
Each time data arrives, nothing happens unless the buffer holds `B5 FF`. The first packet is everything before that `FF` (so it ends with the `B5`); after it, every packet in the buffer ends at the next `0D`. Packets must start `B5 65` and have length 159, 164, 198, 200, 228 or 232, else they are rejected. No checksum.

## Digits
Atlas 7-segment (byte & 0x7F): 119=0, 17=1, 62=2, 59=3, 89=4, 107=5, 111=6, 49=7, 127=8, 123=9, 0=blank. The 159-byte layout uses standard 7-segment (3F,06,5B,4F,66,6D,7D,07,7F,6F). Bit 7 of a byte is a flag.

## Layouts (index of first byte)
| size | clock | home score (h,t,o) | guest score | period | home/guest foul | shot clock | timeout clock | timeout lamps (home,guest) |
|---|---|---|---|---|---|---|---|---|
| 232 | 8 | 5 | 16 | 14 | 15 / 4 | 185 | - | - |
| 228 | 7 | 12 | 16 | 15 | 11 / 6 | 213 | - | - |
| 164 | 7 | 4 | 14 | 12 | 11 / 13 | 149 | 2,3 | 4-6 / 14-16 |
| 198, 200 | 7 | 12 | 16 | 15 | 11 / 6 | 151 | 4,5 | 12-14 / 16-18 |
| 159 | 9 | 3,4 (no hundreds) | 6,7 | 5 | 5 / 13 | 144,145 | - | - |

Clock: if bit 7 of the 2nd clock byte is set, mm:ss (a blank minutes-tens becomes `0`, tenths `0`); otherwise ss.t with minutes `00`. Shot clock: bit 7 of its 2nd byte set means s.t (tens `0`), else ss (tens blank becomes `0`; tenths blank in 232, `0` elsewhere). Possession: bit 7 of the clock's first byte = home `<`, else guest `>` (not in 159).
Timeout lamps: count = highest of the three bytes with bit 7 set (3/2/1, else 0). If the count equals the displayed value minus 1 the displayed value is kept (flicker filter), otherwise it is replaced.

## Oddities / open questions
- In 164/198/200 the timeout lamp bytes are the same bytes as the score digits.
- In 198/200 the guest filter is fed the *home* timeout value (copied from ScoreConnect).
- In 159, Period and HomeFoulOnes both come from byte 5.
- The `B5 FF` / `0D` framing looks accidental; real stream layout is unconfirmed, so a capture is needed.
