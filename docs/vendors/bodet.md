# Bodet (Bodet_Basketball, Bodet_Volleyball)

Wiring (catalog): RS-232, PIC no-decode, 9600 baud; also UDP.

Frame: `SOH(01) <addr> STX(02) <message> ETX(03)`. No checksum, no length. The first ETX ends a frame, the first SOH before it starts one, and byte 2 must be STX (otherwise rejected). The decoder gets everything after the STX, ETX included: `p[0]` unknown, `p[1:3]` two ASCII digits = message type, `p[3]` flag byte, `p[4..]` ASCII data. Flags: bit 1 (0x02) set = clock stopped; bit 2 (0x04) = horn (basketball) or home serve (volleyball). Numbers are read like .NET `Convert.ToInt32` (blanks trimmed, junk = 0).

## Basketball (contract Basketball, event Basketball)
| type | bytes | fields |
|---|---|---|
| 18 | p5-8 (skipped if p7=='D'), p3, p9/p10, p13 | Clock digits (mode ':' tenths '0'), InternalClockStatus R/S, Horn, Home/GuestTimeouts and Home/GuestFullTimeouts, Period |
| 50 | p3 (&0x90==0x90 = tenths), p4-5 | ShotClock tens/ones/tenths, PlayClockStatusInternal |
| 30 | p4-6, p7-9 | Home/Guest score hundreds-ones; zero shows blank |
| 31 | p5, p7, p8-9, p10 | HomeFoulOnes, GuestFoulOnes, FoulPlayerTens/Ones, FoulPlayerNumberOfFouls |
| 36 | p3-5 | final-minute clock, ClockMode '.', tenths |
| 98 / 99 | p3..p10 | Home / Guest team name (8 chars) |
| other (not 19, 32-34) | | possession arrows cleared |

## Volleyball (contract Volleyball)
| type | bytes | fields |
|---|---|---|
| 6 | p5, p7, p8-11, p12-15 | Set, HomeGamesWon, scores, timeouts, TimeoutClock seconds |
| 7 | p5-8 | clock |
| 8 | p5-16 | HomeScoreSet1..3 / GuestScoreSet1..3 (2 chars each) |
All three set InternalClockStatus and HomeServe/GuestServe ('*').

## Oddities
- Volleyball type 6 assigns HomeGamesWon twice (p6 then p7); GuestGamesWon is never set. Reproduced.
- Catalog lists Bodet_Basketball with event type Football; the decoder sets Basketball.
- Unknown: meaning of `p[0]` and the byte after SOH.
