# Nisasport (`scoreboards/nisasport.py`)

Ids: `Nisasport_Basketball` (RS-485/422, 10000 baud), `NisasportTv_Basketball` (RS-232 or RS-485, 9600). Contract `Basketball`.

## Main feed
`FF` + 18 data bytes + `FF` (the closing FF opens the next packet). Other lengths are rejected. No checksum, but the main page must pass a tag test.
- Byte 0: bit 5 (0x20) -> InternalClockStatus `R` else `S`; bit 1 (0x02) -> Horn `H`.
- Byte 1: `0x80` main page, `0xA0` period page.
- Digits are the low BCD nibble (A-F = blank); high nibbles are position tags. Main page is accepted only if tags fit: byte6 hi=1, 7 hi=0, 5 hi=0 (or =0x7F), 8 hi=1 (or 0x7F), 12 hi=0 (or 0x1F), 13 hi nibble 0, 2/3/4 hi=0, 9/10/11 hi=0.

| bytes | field |
|---|---|
| 5-8 | clock; if byte 8 low nibble is blank: ss.t from 5,6,7 (mode `.`) else mm:ss |
| 12,13 | ShotClockSecondTens/Ones |
| 2,3,4 | home score, right-justified when byte 4 is blank |
| 9,10,11 | guest hundreds, tens, ones (ones only updated if byte 11 hi = 0) |
| 14, 17 | HomeFoulOnes, GuestFoulOnes (only when high nibble = 1) |
| period page, byte 5 | Period = low nibble when high nibble = 2 |

## TV feed
`01 13 'T'` + ASCII ... + `04`, 37 bytes ending at the first EOT. Home score 3-5 (right-justified, blank keeps old), clock 6-9 (byte 9 = space -> ss.t from 6,7,8), guest score 10-12, shot clock 13,14, HomeFoulOnes 15, GuestFoulOnes 18.

## Oddities
- Main feed timeouts: ScoreConnect tests `(byte & 7) != 15`, always true, so timeouts are always blank.
- Open: no periods on the TV feed; tag-test failures drop the whole main page silently.
