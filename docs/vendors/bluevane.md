# Blue Vane (BlueVane_Basketball, BlueVane_Basketball_SwappedTeamsInfo)

Wiring (catalog): RS-232 4800, start 02, stop 03.

Frame: `STX(02) <16 data bytes> ETX(03)`, no checksum/length. The first ETX ends a packet and the first STX before it starts it; fewer than 16 bytes is rejected.

| data | field |
|---|---|
| 0-3 | clock digits (blank reads as 0). If flag 0x04 set and byte 2 is blank: seconds p0-1 + tenths p3, ClockMode '.', else mm:ss |
| 4 / 5 | team fouls (first team / second team) |
| 6-7, 8-9 | scores (first team / second team); hundreds '1' if flag 0x20 / 0x10 and neither digit is '9' |
| 10-11 | shot clock (flag 0x40: ones p10 + tenths p11) |
| 12 / 13 | timeouts first / second team |
| 14 | Period |
| 15 | flags: 0x02 horn, 0x04 clock tenths, 0x10/0x20 hundreds, 0x40 shot tenths |

## Swapped variant
In `BlueVane_Basketball` the first team on the wire is Home. `BlueVane_Basketball_SwappedTeamsInfo` is a separate decoder in which the first team is the **Guest** (fouls, scores, hundreds flag 0x20/0x10, timeouts all exchanged), so its contract is already in true home/guest orientation. It also writes ShotClockTenthsSecond '0' (not ' ') when the shot clock has no tenths.

ScoreConnect additionally has a separate per-scoreboard **SwapTeamInformation** setting (Edit Scoreboard page). When on, after decoding `Sport.SwapTeamInformation()` clones the contract and exchanges Home/Guest scores, fouls, timeouts, bonus/double bonus, possession arrow, team names, players and full timeouts, and the swapped copy feeds sbdata and the JSON. That is independent of this decoder; ScoreReader should not apply both unless the operator wants a double swap.
