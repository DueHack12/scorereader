# Anatec (Anatec_Baseball, Anatec_Basketball, Anatec_Wireless_Baseball, Anatec_Wireless_Basketball)

Wiring (catalog): RS-232 9600 (wired); wireless receiver 9600. Ethernet framing: start 0D, stop 0A.

Frame: `CR(0D) <ASCII> LF(0A)`, no checksum. First LF ends a packet, first CR before it starts one; the span (CR..LF inclusive) must be exactly 13 bytes (wired) or 23 (wireless), else rejected.

## Baseball (BaseballSoftball / Baseball)
p1-2 AtBat, p3 Balls, p4 Strikes, p5 Outs, p6-7 Inning, p8-9 GuestRun, p10-11 HomeRun. ClockMode ':'. Top/bottom is inferred: inning changed (or 0) = Top; same inning and fewer outs than the last packet = Bottom; otherwise unchanged. Sets TopBottomInning, TopOfInning/BottomOfInning ('.').

## Basketball (Basketball)
23-byte layout: p14==' ' means seconds.tenths clock (sec p20-21, tenths p15) else mm:ss (min p20-21, sec tens p15, ones p14). Horn when p16==7. Home score p17-19, guest score p13,12,11 (reversed), timeouts home p10 / guest p9, Period p7, fouls p3-4 home, p5-6 guest. Shot clock: p2 a digit = p1-2 whole seconds, else p1 ones and tenths from p2 (0x40+n). Possession: p8 'T' = home '<', 'G' = guest '>'.

## Oddities / open questions
- Upstream registers Anatec_Basketball on the 13-byte wired protocol but its decoder reads byte 21, so it could never decode. Here Anatec_Basketball uses the 23-byte packet (same as wireless). Unverified against hardware.
- Catalog lists Anatec_Wireless_Basketball with event type Football; decoder uses Basketball.
