# Skorled (Skorled_Basketball)

Wiring (catalog): RS-232 115200.

Frame: `STX(02) b1 LEN b3 b4 TYPE data... XOR`, total `LEN+4` bytes; XOR = xor of all bytes before it. Byte 5 = type. Bad checksum: rejected (upstream drops the whole claimed length and counts every tenth failure; here only the STX is dropped so the stream resynchronises).

| type | fields |
|---|---|
| 'B' (0x42) | clock p10-14 (p12 ':' or ' ' = mm:ss else sec p10-11, tenths p13); shot p15-17 (p17 ' ' = whole, '.' = tenths); Period p24; Horn p8=='8'; Home score p25-27, fouls p28-29, flag p30, timeouts p31; Guest score p32-34, fouls p35-36, flag p37, timeouts p38; p18: G/H/g/h = TimeoutClock p22-23, 'T' running, 't' stopped |
| 'C' / 'E' | Home / Guest player FoulNumber p18+3n, Points p19-20+3n (n=0..4) |
| 'D' / 'F' | Home / Guest player numbers p14+2n |

Flag char (p30/p37): '1','9' = Bonus; '2',':' = DoubleBonus; > '8' = possession. Upstream sets **both** teams' possession to '<' (guest should presumably be '>'); reproduced. Needs at least 40 bytes for type 'B'.
