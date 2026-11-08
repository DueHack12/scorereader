# Favero (Favero_Basketball)

Wiring (catalog): RS-485, PIC decode-serial, 57600 hardware setting with non-standard serial "192009N1".

Frame: no delimiters. First byte >= 0x80 begins a packet: 14 bytes if it is one of 0x92, 0x93, 0x96, 0xA0-0xAE, 0xB0-0xBE (upstream list), else 12. Earlier bytes are discarded. No checksum.

| cmd | fields |
|---|---|
| 0x80 | clock (p4 ':' = mm:ss p2-3,p5-6; '.' = ss.t p2-3,p5); p7=='p' home possession, p9=='p' guest; timeouts p8 / p10 (0x40 blank, 'A'=1, 'B'=2, else 3) |
| 0x81 | shot clock (p1 ' ' or '1': p2-3 whole; '2','3': ones p2 + tenths p3); PlayClockStatusInternal p9=='1' R else S |
| 0x82 | scores p1-3 / p4-6, bonus p7 / p9 =='B', Period p8 |
| 0x83 | fouls p7-8 / p9-10, FoulPlayer p2-3, FoulPlayerNumberOfFouls p6 |
| 0x92 / 0x93 | Home / Guest team name p1-13 (not trimmed) |
| 0x94 | Horn if p1 or p4 == '1' |

Open: bytes >= 0x80 inside the stream would resync wrongly; no capture checked.
