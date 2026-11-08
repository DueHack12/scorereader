# Colorado Timing (`scoreboards/coloradotiming.py`)

Ids: `ColoradoTiming_Waterpolo`, `ColoradoTiming_Swimming`, `ColoradoTimingV2_Waterpolo`, `ColoradoTimingV2_Swimming`.
Wiring (catalog): V1 RS-232 9600 or 115200; V2 RS-232 115200.

## Framing
ASCII packet = first start byte in the buffer through the first `04` (EOT). No checksum.
- V1: start `02`; packet must begin `02 'C' 'T'`, otherwise rejected.
- V2: start is the first `01` or `02`; any content accepted.
EOT with no start byte before it is rejected (counted in `bad`).

## Water polo (contract `WaterPolo`, event `WaterPolo`), all plain ASCII
| byte | field | byte | field |
|---|---|---|---|
| 11,12 | ClockMinutesTens/Ones | 22 | TimeoutMinutesOnes |
| 14,15 | ClockSecondTens/Ones | 24,25 | TimeoutSecondsTens/Ones |
| 17,18 | ClockTenthsSecond, ClockHundreths | 26,27,28 | GuestScoreTens/Ones, GuestTimeouts |
| 19,20 | ShotClockTens/Ones | 61,62,63 | HomeScoreTens/Ones, HomeTimeouts |
| 21 | Period | | ClockMode always `:` |

Packets shorter than 64 bytes are ignored.

## Swimming (contract `SwimmingDetail`, event `Swimming`)
Type = bytes 1-2. `RE` reset (clock digits `0`, per lane Split/Clock `""`, Place/FinishFlag blank).
`SR` running clock: 3,4 minutes, 6,7 seconds, 9 tenths. `ST` split: lane = ASCII int at 3-4 (1-8), Place 6, Split 7-8, Clock = bytes 9-12 + 14-16. `FT` finish: Place 6, Clock = 7-10 + 12-14, FinishFlag `.`.
Output keys per lane: `Place<n>`, `Split<n>`, `Clock<n>`, `FinishFlag<n>`.

## Oddities / open questions
- `ColoradoTiming_Swimming` (V1) only accepts `02 'C' 'T'` packets, but the swimming decoder only understands `RE/SR/ST/FT`, so V1 swimming decodes nothing (same as ScoreConnect). Use V2 for swimming unless a capture shows otherwise.
- A reset leaves lane strings empty, not blank.
