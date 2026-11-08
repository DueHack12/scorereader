# ALGE-Timing (`scoreboards/alge.py`)

Ids: `AlgeTimingCKN_V1_Basketball`, `AlgeTimingCKN_V2_Basketball` (vendor "Alge Timing CKN"), `Alge_Timing` (vendor "Alge").

## Wiring (catalog)
CKN: RS-232 9600, RS-422/485 9600, or ZigBee 115200 (PIC/SiLabs, no decode). Alge: no hardware config, wired,
start 0x02 / stop 0x04.

## CKN framing
- V1: `D1 n type … chk`, length `n+2`, `chk` = sum of all previous bytes mod 256. A doubled `D1 D1` start uses the
  second. A bad packet is consumed whole.
- V2: each word is followed by one extra byte; length `2n+2` (`n` = byte 2), checksum = sum of even-indexed bytes
  (0..2n) mod 256 at the last byte. A start is `D1` not followed by `D1` or `2E`. A packet is released when the next
  start byte is seen (one packet of latency) and everything before that start is discarded.

Word `k` is `packet[mode*k]`. Type = word 2: 4 clocks, 10 team names, 13 fouls, 22 main.

| Word | Meaning |
|---|---|
| 3 | minutes (BCD-free decimal); 0 means under a minute |
| 4 | seconds |
| 5 | tenths = high nibble (hex letters read as 0), under a minute only |
| 6 | shot clock; `0xAA` = blank |
| 7 | timeout clock seconds (`& 0x7F`), types 4 and 22 |
| 8 / 9 | home / guest score (type 22) |
| 10 | period |
| 11 | flags: 0x80 home possession, 0x08 guest possession, 0x30 home timeouts, 0x03 guest timeouts, 0x40 / 0x04 bonus |
| 12 / 13 | home / guest team fouls (type 22) |
| type 13: 3 / 4 / 5 / 6 | home fouls, guest fouls, fouling player number, that player's fouls |

Team names (type 10): raw bytes 3..10 and 15..22 regardless of mode (so V2 names are interleaved, as in ScoreConnect).

## Alge_Timing
CR-terminated ASCII lines of exactly 21 or 23 characters (anything else is counted as bad). Letter `A`-`H` = lane 1-8,
id at 1-3, status at 4 (space -> S, `.` -> R, `C` -> F, else S), clock text at 12-20. Contract `Timer`:
`Lane{n}ClockStatus`, `Lane{n}Id`, `Lane{n}Clock`; event `Timing`.

## Open questions
- No real V2 captures: what the odd bytes carry is unknown. ScoreConnect has unused MainScore/MainTimeScore layouts (not implemented).
