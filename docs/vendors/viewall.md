# View All (ViewAll_Basketball)

Wiring (catalog): no hardware configuration; UDP also. Ethernet start 02, stop 04.

Frame: `STX(02) f0;f1;...;f12 ETX(03)`, exactly twelve ';' (else rejected). First ETX ends, first STX before it starts. Fields split on ';' and the ETX; field 0 includes the STX and is unused, 1-2 unused.

| field | content |
|---|---|
| 3 / 4 | Home / Guest team name (first 8 chars; empty ignored) |
| 5 / 6 | Home / Guest score, 1-3 chars left-padded with '0' |
| 7 | Period (second char if 2+ chars) |
| 8 | InternalClockStatus (first char as sent) |
| 9 | clock: char 2 is the mode; ':'/' ' = mm:ss, else ss.t |
| 10 | shot clock: empty = " 0", 2 chars = tens+ones, else ones |
| 11 / 12 | Home / Guest fouls (1 char = ones) |

Short or empty fields in 7-12 are skipped (upstream would throw).
