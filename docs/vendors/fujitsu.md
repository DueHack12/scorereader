# Fujitsu (Fujitsu_Basketball)

Wiring (catalog): RS-232 57600, start 02, stop 04 on Ethernet.

Frame: `STX(02) <type> ... CR(0D)`, exactly 100 bytes STX..CR inclusive, ASCII, no checksum. The first CR ends the packet and the first STX before it starts it; other lengths are rejected. Upstream leaves the buffer untouched when the STX is missing or after the CR (wedging on a stray CR); here those bytes are dropped.

All types: clock p2-3/p5-6 (p4=='.' means sec p2-3 + tenths p5, mode '.'; else mm:ss), shot clock p8-10 (p9=='.' means ones p8 + tenths p10).

| type | fields |
|---|---|
| '1' game | HomeTeamName p13-15, GuestTeamName p16-18, Period p19, p20=='2' = guest possession '>' else home '<', Home score p21-23, Guest p24-26, fouls p27/p28, timeouts p29/p30 |
| '2' home players | HomePlayerN p13+2(N-1) (2 chars), Points p45.., FoulNumber p77+N-1 |
| '3' guest players | same offsets, Guest |

Open: no capture available; possession defaults to home when p20 is anything but '2'.
