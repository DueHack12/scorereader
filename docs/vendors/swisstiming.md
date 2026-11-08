# Swiss Timing (`scoreboards/swisstiming.py`)

Ids: `SwissTiming_Basketball`, `SwissTiming_Hockey`, `SwissTiming_WaterPolo` (catalog vendor "Swiss Timing"),
`SwissTimmingTransmission_Basketball`, `SwissTimingTransmission_Swimming` (vendor "Swiss Timing TP"; note the
doubled "m" in the basketball id).

## Wiring (catalog)
- Swiss Timing: PIC RS-485/422, no decode, 9600 baud, wired or inverted. ScoreLink serial framing: start 0x02, stop 0x04.
- Swiss Timing TP: no PIC hardware config, serial or UDP; start 0x02, stop 0x04, 3 ms delay.

## Main protocol (hockey, basketball, water polo)
`02 type payload 03 xor`. `xor` = XOR of the bytes STX..ETX. The frame is consumed through the ETX; the checksum
byte stays in the buffer and is skipped when the next STX is searched (first 0x02 in the buffer; if followed by
another 0x02, the second starts the frame). A frame waits until its checksum byte has arrived (Windows build).
Bad checksums are counted in `bad` on every occurrence (Windows ScoreConnect only flags every 5th in a row).

Types: `N` names (home at 2..9, guest at 14..21, applied only if the first character is not blank), `D` data, `O`
hockey penalties. Clock (D, bytes 2..6): `:` at 4 -> MM:SS, tenths `0`; `.` at 4 -> SS.t (bytes 2,3,5), minutes `00`;
anything else is passed through as `ClockMode`.

| D byte | Basketball | Hockey (HockeyLacrosse) | Water polo |
|---|---|---|---|
| 7-9 / 10-12 | Home / Guest score H,T,O | - | - |
| 8-9 / 11-12 | - | Home / Guest score T,O | same as hockey |
| 13 / 14 | HomeFoulOnes / GuestFoulOnes | - | - |
| 15 / 16 | HomeTimeouts / GuestTimeouts | Home/GuestFullTimeoutsRemaining | HomeTimeouts / GuestTimeouts (see quirk) |
| 17 | Period | Period | Period |
| 18 | possession 0/1/2/3 -> `<` `>` arrows (other values keep previous) | - | - |
| 20 | Horn (`0` -> blank, else `H`) | - | - |
| 23-24 | ShotClockSecondTens/Ones | - | ShotClockTens/Ones |

Hockey `O` record: three penalty slots per team, 7 bytes each (player 2, minutes 2, `:`, seconds 2). Home bases
2, 9, 16; guest 23, 30, 37. Fields `{Home|Guest}PenaltyPlayer{1-3}{Tens|Ones|ClockMinutesTens|ClockMinutesOnes|ClockSecondTens|ClockSecondOnes}`.
It also blanks HomeShotOnGoalTens/Ones and GuestShotOnGoalTens (ScoreConnect never touches GuestShotOnGoalOnes).

## Transmission protocol
`01 … 04`, no checksum; packet starts at the first SOH in the buffer. Packets without a SOH before the EOT are dropped.

**Basketball**: ASCII, `|` separated: `f[0]` contains `4`, `f[1]` = `6`, `f[2]` record id, values from `f[4]`.
1 scores (`f[4]`,`f[5]`); 2 fouls `f[4]`,`f[5]`, bonus `f[6]`,`f[7]` (`1` = bonus); 3 timeouts `f[4]`,`f[5]`;
4 period (`f[4]`=`3` -> `f[5]`; `f[4]`=`4` -> overtime `5`); 7 horn `f[4]`; 30 game time `f[4]` (`M:SS` or `S.t`);
31 shot clock `f[4]`, running flag `f[7]` -> `PlayClockStatusInternal` R/S.

**Swimming** (`SwimmingMixed`, nested `SwimmingEvent` / `SwimmingRows` dicts, `PacketType` Event|Rows): `packet[1]`=19
text record: bytes 6-7 sub-type, 8-9 record. Record 0 = event name (10..), record 1 sub 0 = event record text, record 1
sub 20 (8 chars) = clock `MM:SS.hh` at 10,11,13,14,16,17; other records with lane number at 10-11 (1-9): lane, swimmer
(13, 16 chars), team (30, 4), time (35, 8), place (44-45) into row A/B/C (lane mod 3) of block Row1To3/4To6/7To9.
`packet[1]`=2, `packet[2]`=12 clears event and rows.

## Differences from ScoreConnect (deliberate)
- Transmission basketball fouls: ScoreConnect compares the bonus strings with a `char`, which throws in .NET; here the
  bonus lamps are decoded (`1` = `B`).
- Transmission shot-clock empty value clears `ClockTenthsSecond` (the game clock's), as in ScoreConnect.
- Short packets are ignored instead of throwing.

## Open questions
- No captures; all tests use synthetic frames. Swimming column layout is taken from the decoder only.
- Water polo timeout rule: a new value exactly one below the previous is ignored (kept as ScoreConnect does).
