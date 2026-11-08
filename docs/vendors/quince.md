# Quince (Quince_Basketball)

Wiring (catalog): RS-232 19200, start 02, stop 03 on Ethernet.

Frame: `01 00 LEN <LEN bytes counting LEN itself, the last being a trailer> 0D`. The decoder packet is the LEN bytes beginning at LEN (`p[0]`=LEN). No checksum. Upstream detects a frame only when the next `0D 01` arrives (one frame of latency); this port completes a frame at its own CR when LEN matches, producing the same packets. Wrong CR position = rejected.

| p[1]/p[2]/p[3] | fields |
|---|---|
| p1==0xC5 | InternalClockStatus: p3==1 'R' else 'S' |
| p2==0x45 | shot clock BCD at p5-6 (p3==1) else p6-7; ignored if LEN==7 and p6==0x91 |
| p3=0x02 | clock p6 (mm), p7 (ss), p8 high nibble tenths; mode '.' when mm and ss-tens are blank/0 |
| 0x36 / 0x46 | Home / Guest score: p4 low nibble hundreds, p5 tens/ones |
| 0x38 / 0x48 | Home / Guest fouls p4 |
| 0x33 / 0x43 | Home / Guest timeouts p4 low nibble |
| 0x53/0x63, 0x51/0x61 | Home/Guest players, points p4-8 (BCD pair) |
| 0x54 / 0x64 | player fouls, one nibble each p4-6 |
| 0x31 / 0x41 | Home / Guest team name p5..len-3 (ASCII) |
