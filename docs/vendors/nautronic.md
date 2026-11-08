# Nautronic (modules: `scoreboards/nautronic.py`)

Source of truth: ScoreConnect III decoders `Nautronic.Main` and `Nautronic.Ng08` (the Windows and Mac builds are identical for these).

| Id | Catalog vendor | Wiring (catalog) | Protocol / decoder |
|---|---|---|---|
| `Nautronic_Basketball` | Nautronic | RS-485, no PIC decode, 115200 | `FF 71` frames / `NautronicBasketball` |
| `Nautronic_Hockey` | Nautronic | same | `FF 71` frames / `NautronicHockey` |
| `NautronicNg08_Basketball` | Nautronic NG 08 | RS-485, PIC "DECODESERIAL", 57600, non-standard serial `560009N2` | NG08 frames / `_Ng08Basketball` |
| `NautronicNTPult_Basketball` | Nautronic NG 08 | same | NG08 frames / `_NtPultBasketball` |

Nautronic also lists wireless and ZigBee 115200 variants; the data is the same.

## Main family framing (`Nautronic_*`)
`FF 71 L xx 80 xx <sub-packets>`; a frame runs until the next `FF 71` (so a frame is only decoded when the following header arrives). Accepted when `len >= 5`, `byte[4] == 0x80` and `len - (L + 4) < 3` (an upper bound only; a plausible `L` is `len - 4`). Failures are counted as rejected. No checksum. Bytes before the first `FF 71` are dropped.

Sub-packets start at byte 6: `n, id_hi, id_lo, data...`, `n` = length of what follows (must be >= 3 and fit). The 16-bit id selects the field group. A "digit at offset k" is a nibble of `sub[k + 2]`; "hi/lo" is the nibble. Nibble characters `A B C D F` read as blank (`E` stays `E`); the player-number readers blank `A B C E F` instead (ScoreConnect has two readers, both reproduced).

### Basketball (contract `Basketball`, event `Basketball`)
| Id | Content |
|---|---|
| C0D3 | `sub[2]==0x00`: HomeTeamName (10 ASCII from `sub[8]`, left-trimmed, needs len >= 18); `0x80`: GuestTeamName (20 chars) |
| 400C | Clock. If digit 3 is not blank: minutes/seconds from digits 0-3, mode `:`, tenths `0`. Else seconds from digits 0-1, tenths digit 2, minutes `00`, mode `.`. InternalClockStatus = `R` if hi nibble of digit 2 is `6`, else `S` |
| 4000 / 407C | Home score tens/ones = lo digits 0,1 / guest 4,5. Hundreds = `1` if hi nibble of digit 1 / 5 is anything but `0` (even blank), else blank |
| 4006 | Period = lo digit 1 |
| 4013, 4093 | Timeout clock (`TimeoutClockMinutesOnes`, `SecondTens`, `SecondOnes` = lo digits 0-2) when `sub[3] & 0xF0 == 0x20`; when `sub[3] == 0x0F` for more than 10 consecutive updates it is blanked |
| 4020 / 40A0 | Home / guest player numbers 1-5 (two digits each, digits 0-9; len > 14) |
| 4050 / 40D0 | Home / guest player points 1-5 |
| 8005 | Hi nibble of digit 0: `1` -> HomePossession `<`; `0` -> GuestPossession `>` |
| 8007 / 8087 | Home / guest fouls: raw 0,1,3,7,15,31 -> 0..5 (thermometer) |
| 8000 / 8080 | Home / guest timeouts: raw 0,1,5,21 -> 0..3 |
| 40CA | Shot clock, only if len == 5. `sub[4]==1` (tenths): tens blank, ones/tenths = digits 0,1 (ignored if `sub[2]` and `sub[3]` both 0). Otherwise tens/ones = digits 0,1, tenths blank |

### Hockey (contract `HockeyLacrosse`, event `Hockey`)
| Id | Content |
|---|---|
| C0D3 | Names as above (home 8 chars) |
| 4000 | HomeScore tens/ones = digits 0,1; HomeShotOnGoal = 4,5; Period = 7 |
| 407C | GuestScore = digits 4,5; GuestShotOnGoal = 8,9 |
| 400C | Clock digits 0-3, mode always `:`, status as in basketball |
| 4011 / 4091 | Home / guest penalties 1-3, five digits each: player tens, ones, clock minutes ones, seconds tens, seconds ones (minutes tens blank) |
| 8000 | **GuestFullTimeoutsRemaining** from `sub[2]`; and **Home**PlayerNPenaltyType1/2 from digits 2,4,6 (`1`->`2 `, `3`->`22`, `4`->`5 `, `5`->`25`) |
| 8080 | **HomeFullTimeoutsRemaining**; and **Guest**PlayerNPenaltyType1/2 |

Oddity kept on purpose: ids 8000 and 8080 cross the sides (timeouts of one side travel with the penalty types of the other). ScoreConnect does this; confirm with a real board. Partial timeouts are set blank.

## NG08 family framing
A packet ends at the first byte `>= 0x80` (included in the packet) and starts at the first byte in `{3, 10, 40, 70}` anywhere in the buffer. A terminator with no start byte before it is rejected. A garbage byte equal to one of the start values ahead of a frame corrupts that frame (as in ScoreConnect). No checksum. Packet: `addr, kind, data...`; each BCD byte holds digits in the low nibble (hi nibble is a flag; `A-F` read blank).

### `NautronicNg08_Basketball`
| Packet | Content |
|---|---|
| `10|40, 12` | Clock. Status `S` if hi nibble of p[4] is `2`, else `R`. Updated only when hi nibbles of p[2] and p[5] are not `2`. If lo p[5] is not blank: `p2 p3 p4 p5` as mm:ss; else seconds `p2 p3`, tenths `p4`, mode `.` |
| `10|40, 13` | Alternate clock: status from hi p[3]; only when running: minutes ones p2, seconds p3 p4 (mode `:`) or seconds ones p2 + tenths p3 (mode `.`); minutes tens is not updated in `:` mode |
| `10, 17` / `40, 0` | Shot clock. Check nibble at p2 / p4 equal `1` -> under 5 s: tens `0`, ones, tenths. Else tens, ones |
| `10, 18` | Partial shot clock update (uses the under-5 s flag remembered from the last full one) |
| `10, 0` (len > 6) | Period p4; home hundreds `1` if hi p2 is `2`, tens p2, ones p3; guest hundreds hi p5, tens p5, ones p6 |
| `3, 5, 10, 5, 0|1` (len > 13) | Home (0) / guest (1) score as a decimal byte at p11 and fouls as a decimal byte at p12 |
| `10, 48` | Timeout on/off flag; read but never used |

### `NautronicNTPult_Basketball`
Same clock packets (without the flag gating on kind 12). Shot clock: `40,0` / `10,18` digits p2 p3; `10,17` digits p3 p4. Scores: `10,0` home / `10,3` guest, len 4-6, hundreds from hi p2 (`2` -> `1`), tens p2 (blank digit reads `0` when no hundreds), ones p3. Possession and timeout clock: `10,5` (home `<`) / `10,8` (guest `>`) when hi nibble of p4 is `2`; timeout clock `p2 p3 p4`, hidden while `InternalClockStatus == R`.

## Differences from ScoreConnect and open questions
- Out-of-range reads in ScoreConnect throw and lose the packet. Here, short sub-packets or packets are skipped field by field.
- Exact meaning of `L` in the Main header is unknown; the check is reproduced as is.
- `560009N2` serial setting is taken from the catalog and not interpreted here.
- No captures were available; tests use synthetic packets built from the decoder logic.
