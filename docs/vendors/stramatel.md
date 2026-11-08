# Stramatel (module: `scoreboards/stramatel.py`)

Source: ScoreConnect III decoders `Stramatel`, `Stramatel.Main`, `Stramatel.Shared`, `Stramatel.BE04030` (Windows and Mac builds identical).

Wiring (catalog): Stramatel = RS-485, no PIC decode, 19200; Stramatel BE04030 = RS-485, 9600. 

## Framing (no checksum)
- **Standard** (`StramatelProtocol`): the first byte `0xF8..0xFD` (channel) before the first `0x0D` starts the packet, which ends at that `0x0D`. Must be exactly 54 bytes. Otherwise rejected. Packet = `channel, sport char, ... , 0x0D`. A channel-range byte in garbage ahead of a frame costs that frame (as in ScoreConnect).
- **BE04030**: wire = `F8 F8 <...> 0D 0D`. The packet starts at the second `F8` and ends at the second `0D`, and must be 55 bytes (the standard layout plus one trailing `0D`).
- Text fields are ASCII; non-printable reads blank. "slz" below = a `0` is shown blank.

`p[1]` is the sport character/code and selects the layout. Team names: sport `w` (0x77) home, `b` (0x62) guest; 8 bytes at offset 6 (7 on BE04030 ice hockey) decoded as UTF-16LE; only the first non-blank name is kept.

Clock (all but racket sports): `p4..p7`. If `p6` and `p7` are both non-blank: `p4(slz) p5 : p6 p7`, mode `:`, tenths `0`. Otherwise seconds mode `.`: seconds `p4(slz) p5`, tenths `p6`, minutes `00`. Clock status: `p20 == '0'` -> `R` else `S` (`'1'` on BE04030 ice hockey). Horn: `p19 == '1'`.

## Sports
| Id | Contract / event | Sport char(s) | Notes |
|---|---|---|---|
| Stramatel_Basketball, _BasketballBE04030 | Basketball / Basketball | `3`,`4` main; `8` home player points; `7` guest player points | possession `p3` (`1` home `<`, `2` guest `>`); score hundreds/tens/ones home `p8-10`, guest `p11-13`; period `p14`; fouls `p15/16`; timeouts `p17/18`; timeout clock `p21,p46,p47`; shot clock `p48,p49` (bit 6 of `p49` = seconds + tenths, tenths in low nibble); player fouls home `p22-26`, guest `p34-38`; `PlayClockStatusInternal` `R` if `p51 == '0'`; points are pairs from `p22` |
| Stramatel_Hockey, _RinkHockey | HockeyLacrosse / Hockey | `5` main; `7`,`8` shot clock | scores `p9,10` / `p12,13`; period `p14`; timeouts `p17/18`; 3 penalty clocks per side (home `p22-30`, guest `p35-43`, minutes-ones/sec-tens/sec-ones) |
| Stramatel_Hockey452 | same | `5` | penalties home `p24-26,29-31,34-36`, guest `p39-41,44-46,49-51` |
| Stramatel_IceHockey | same | `0x93` main; `7`,`8` shot clock | scores `p8-11`, period `p12`, one home penalty clock `p16-18`, no timeouts |
| Stramatel_IceHockeyBE04030 | same | `0x93` | names at offset 7; scores `p9,10,12,13`; period `p14`; timeouts; status code `'1'`; 2 penalties/side with minutes tens: home `(p29,22,23,24)`, `(p30,26,27,28)`, guest `(p43,36,37,38)`, `(p44,40,41,42)`; no shot clock |
| Stramatel_Futsal / _HandBall | FutsalHandball / Futsal or Handball | `53` or `60` (both accepted by both ids); `37`,`38` clock only | fouls `p8/p11`; scores slz `p9,10 / p12,13`; period `p14`; timeouts `p17/18`; penalties: home1 num `p31,32` clock `p22-24`, home2 num `p46,47` clock `p35-37`, guest1 num `p33,34` clock `p25-27`, guest2 num `p48,49` clock `p38-40` |
| Stramatel_TableTennis / _Badminton | TableTennisBadminton / TableTennis or Badminton | `58` or `108` (both accepted) | `ClockHour*/Minutes*` = `p4-7`; set `p14`; points `p9,10 / p12,13`; sets won `p15/16`; serve `p50` (`1,2` home, `3,4` guest); set points 1-4 home `p24+4n`, guest `p26+4n` |
| Stramatel_Tennis | Tennis / Tennis | `57` | clock `p4-7`; points slz `p9,10 / p12,13`; set `p14`; set games 1-2 `p24-31` (slz), 3-4 `p37-44`; `TopServe` only (`p50` in `0,1`); `IsTieBreak` `p52 == '1'`; status |
| Stramatel_Volleyball | Volleyball / Volleyball | `54` | scores slz `p9,10 / p12,13`; set `p14`; games won `p15/16`; timeouts `p17/18`; set scores home `p22+4n`, guest `p24+4n` (slz) |

## Oddities and open questions
- Tennis: ScoreConnect's second serve branch repeats the first test, so `BottomServe` is never set unless `TopServe` is.
- Hockey uses `HomeTimeOut`, Basketball `HomeTimeouts`, Volleyball `HomeTimeout` (contract names differ).
- Decoders ignore packets shorter than the expected 54/55 bytes.
- No captures were available; tests use synthetic frames.
