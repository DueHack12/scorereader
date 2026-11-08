# Varsity Scoreboards (Varsity and Varsity Gen2)

Module: `scoreboards/varsity.py`. Facts taken from ScoreConnect III 1.3.0.21 behaviour.

## Wiring (catalog.json)
| Vendor | Hardware | Baud |
|---|---|---|
| Varsity | ScoreLinkII `PIC_RS485/22_NODECODE_9600_NORMAL` (RS-485, no PIC decode) | 9600 |
| Varsity Gen2 | `PIC_RS485/22_NODECODE_115200_NORMAL` | 115200 |

Network option for both: serial-over-Ethernet `MODEDELAY_DELAY3_STRTCHR02_STPCHR04_INT4D`.

## Varsity (Main): `Varsity_Basketball`, `Varsity_Baseball`, `Varsity_Soccer`
Frame: `[n, type, data..., chk]`. `n` is the length of the whole packet, 3-19. Byte sum of the packet must be 0xAA.
Resync: a byte outside 3..19, or a checksum failure, drops one byte and rescans (a checksum failure is counted as rejected).

Data bytes are consecutive registers: byte `i` (from 2) is register `type + (i-2)`.

Clock messages (basketball: 73/76/77/78; soccer: 73/76 only; baseball: none): `[n, type, x, c3, c4, c5, c6, ...]`,
time = big-endian `c3..c6` in centiseconds. 73 = main clock running, 76 = main stopped, 77 = shot clock running,
78 = shot clock stopped. Byte 2 is not used.

| Reg | Basketball | Soccer | Baseball |
|---|---|---|---|
| 0 | HomeScoreHundreds/Tens/Ones (blank-left) | HomeScoreTens/Ones (3-digit decode, blank-left) | HomeRunTens (zero blanked)/Ones |
| 1 | GuestScore* | GuestScore* | GuestRun* |
| 2 | HomeFoulTens/Ones | HomePenalties (2 chars string) | HomeHits* |
| 3 | GuestFoul* | GuestPenalties | GuestHits* |
| 4 | bit0: HomePossession `<` else GuestPossession `>` | same | |
| 4/5 (baseball) | | | HomeErrors / GuestErrors (ones digit) |
| 6 | Period | Period | InningTens/Ones |
| 9 | HomeBonus `B` if ones digit == 1 | HomeShotTens/Ones | Balls |
| 10 | GuestBonus | GuestShotTens/Ones | Strikes |
| 11 | | | Outs |
| 14 | | | AtBatTens/Ones (hex nibble, `A` = blank) |
| 15 | | | ErrorFlag: 12 `H`, 13 `E`, else blank |
| 16-25 / 26-35 | | | HomeInning1-10 / GuestInning1-10 |
| 41 / 42 | | | value 1: BottomOfInning `.` + TopBottomInning `B` / TopOfInning `.` + `T`; else the lamp is blank |
| 45 / 46 | HomeTimeouts / GuestTimeouts | same | |
| 50 / 51 | HomeDoubleBonus / GuestDoubleBonus | | |

Contracts: Basketball, Soccer, BaseballSoftball (event Baseball). Basketball shot clock writes
`ShotClockSecondTens/Ones`.

## Varsity Gen2: `VarsityGen2_Basketball|Football|Hockey|Soccer|Baseball|Volleyball`
Frame: `F6 len ...`, `len + 1` bytes in all, byte sum (the F6 included) == 0xA0. Bytes before an F6 are discarded.
On a checksum failure the decoder drops the F6 and rescans (ScoreConnect instead drops `len-1` bytes from the start of
its buffer; this port keeps more of the stream).
Byte 5 = page: 0 = state, 1 = clock, 6 = team names (not baseball/volleyball).

Clock page (byte 6): 0 main run, 1 main stop; time = little-endian ms in bytes 7..10. 4 play clock run, 5 stop;
time = little-endian ms in bytes 8..11. 2 and 3 are ignored. Soccer takes only 0/1.
Names: byte 7 = 0 home / 1 guest, 8 ASCII characters from byte 8 (`HomeTeamName`, `GuestTeamName`).

Page 0 offsets (Dec3 = 3-digit decimal, `_` = leading zero blanked):
| Offset | Basketball | Football | Hockey | Soccer |
|---|---|---|---|---|
| 11 | Home score H/T/O (Dec3, blank-left) | HomeScore T_/O | HomeScore T_/O | same |
| 12 | Guest score | GuestScore | GuestScore | same |
| 13 | HomeFoul T_/O | | HomeShotOnGoal T/O | |
| 14 | GuestFoul | | GuestShotOnGoal | |
| 15 / 16 | byte == 1: HomePossession `<` / GuestPossession `>` | same | same | same |
| 17 | Period | Quarter | Period | Period |
| 27 / 28 | Home/GuestBonus (== 1 -> `B`) | Down / ToGo T/O | | |
| 29 | | BallOn T/O | | |
| 30 / 31 | | Home/GuestTimeouts | | |
| 63 / 64 | Home/GuestTimeouts | | | |
| 68 / 69 | Home/GuestDoubleBonus | | | |

Baseball (page 0, frames of 62 bytes or fewer): 11/12 runs (T_/O), 17 inning (T_/O), 27 Balls, 28 Strikes, 29 Outs,
32 AtBat (hex nibbles, `F` = blank), 33 ErrorFlag (172 `H`, 173 `E`).
Volleyball (page 0, each field read only if the length byte covers it): 11/12 score (T_/O), 13/14 games won (zero
blank), 15/16 serve (bit0 -> `*`), 17 Game (zero blank).
Contracts: Basketball, Football, HockeyLacrosse (event Hockey), Soccer, BaseballSoftball (Baseball), Volleyball.
Play clock keys: basketball `ShotClockSecondTens/Ones`, football `PlayClockTens/Ones`, hockey `ShotClockTens/Ones`.

## Clocks (both formats)
The boards send start/stop messages, not ticks; ScoreConnect runs a 50 ms countdown. The decoder stores the value and
`refresh()` recomputes the clock fields from `time.monotonic()` (override `decoder.now` in tests). `Protocol.snapshot()`
and `Protocol.version` call `tick()`, so a running clock shows up when polled. Behaviours kept from ScoreConnect:
- Clock text is `MMSSt`; when the minutes are `00` -> mode `.` with tenths, otherwise mode `:` with tenths `0`.
- Main rounds seconds up at a minute or more and shows tenths below; Gen2 adds one to the tenths for any non-zero
  fraction (0.5 s shows 0.6), and rounds seconds up whenever there is a fraction.
- Varsity Main writes the main clock only when its text changes from the last written value (initially `00000`), so
  a clock stopped at 0:00 before any other value never writes clock fields. Gen2 always writes.
- A start message received while the clock is already running does not re-anchor it (only stop then start does).
- The play/shot clock exists from construction and shows `00` until set. It shows whole seconds (no rounding).
- Time values that overflow a signed 32-bit int are treated as 0.

## Open questions
- Bytes 2-4 of Gen2 frames and byte 2 of Main clock messages are never read; their meaning is unknown.
- Clock status fields (`InternalClockStatus`, `PlayClockStatusInternal`) are set to `R`/`S` here; the contracts module's
  ClockStatusEmulator only runs in `Protocol.feed`, not on `tick()`.
- ScoreConnect gets team names from configuration (`InsertSportTeamNames`); Main has no on-wire names.
- Nothing was verified against real hardware.
