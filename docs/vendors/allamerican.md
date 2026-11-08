# All American Scoreboards (`scoreboards/allamerican.py`)

Three unrelated wire formats, all raw serial (`NODECODE`), frames start at the first `0xFC` byte. Garbage
before a frame is dropped. After a failed checksum the whole frame is consumed (the next `0xFC` is searched
after it), as in ScoreConnect.

| Model | Catalog wiring | Baud | Frame |
|---|---|---|---|
| 8000 (ids `AllAmerican_*`) | Wired RS485/422 (PIC), Wireless XBee | 9600 wired, 57600 XBee | 32 bytes |
| 3000 | Wired RS485/422 | 9600 (or 2400 "Wired Slow") | 20 bytes |
| 9000 | XBee 57600, RS485/422 or RS232 | 57600 XBee, 115200 wired | 34 bytes |

## Model 8000 (32 bytes)
`FC` … bytes 30-31 = sum of bytes 3..29 (16-bit, little-endian; a computed byte equal to `0xFC` is sent as `0x69`).
Byte 9 selects the sub-packet: `0x11` main data, `0x22` second page (baseball innings, hockey penalties). A
packet only updates its own page; other fields keep their last value. Values are BCD nibbles (A-F read as
blank). Header bytes 4-6 are the clock, byte 7 the play/shot clock, byte 3 bit 7 the horn.

Clock: if byte 4 is `00` the clock is `00.SS.t` (mode `.`; seconds in byte 5, tenths = low nibble of byte 6),
else `MM:SS` (mode `:`, tenths `0`). A blank nibble counts as 0 for this test.

| Field (page 0x11 unless noted) | Football | Basketball | Hockey | Soccer | Volleyball | Baseball |
|---|---|---|---|---|---|---|
| Home score (BCD) | 10 | 10 (+hundreds: byte 11 & 0x86) | 10 | 10 | 10 | HomeRun 10 |
| Guest score | 12 | 12 (hundreds: byte 13 & 0x86) | 12 | 12 | 12 | GuestRun 12 |
| Home / guest possession (bit 0) | 11 / 13 | 11 / 13 | | | serve: 11 / 13 | |
| Quarter / period / game | 14 low | 14 low | 14 low | 14 low | Game 14 low | Inning 14 |
| Timeouts (hi = home, lo = guest) | 19 | 19 | 19 | 19 | 19 | |
| Play / shot clock (header, every packet) | 7 PlayClock | 7 ShotClockSecond | 7 ShotClock | | | |
| To go / down / ball on | 17 / 18 low / 20 | | | | | |
| Bonus (byte 11/13 bit 8) / double bonus | | HomeBonus, GuestBonus (see quirks) | | | | |
| Fouls home / guest, foul player, his fouls | | 15 / 16, 17, 18 low | | | | |
| Saves home / guest (2 chars) | | | 20 / 21 | | | |
| Shots on goal / shots | | | 15 / 16 | shots 15 / 16 | | |
| Corner kicks home / guest (2 chars) | | | | 20 / 21 | | |
| Games won home / guest | | | | | 15 low / 16 low | |
| Set scores H/G (2 chars) | | | | | S1 20/21, S2 22/23, S3 24/25, S4 26/27 | |
| Balls / strikes / outs | | | | | | 18 low / 17 hi / 17 lo |
| Home / guest hits, errors | | | | | | hits 21 / 22; errors 16 hi (home) / 16 lo (guest); GuestErrorNumber 27 low |
| At bat, top/bottom | | | | | | 20; byte 13 bit 0 set = top |
| Horn (byte 3 bit 7) | yes | yes | | yes | | |

Page 0x22 (hockey): per penalty slot, player / minutes / seconds bytes: Home1 12/10/11, Home2 15/13/14, Guest1
18/16/17, Guest2 21/19/20. Slot 3 fields are set to blank. Page 0x22 (baseball): `GuestInningN` = byte 9+N,
`HomeInningN` = byte 19+N (low nibble).

Possession and serve are only written when the lamp bit is set (home first, then guest, so guest wins if
both), never cleared by a packet that lacks them. Baseball sends no clock, so it is not decoded.

## Model 3000 (20 bytes, no checksum)
One digit per byte (low nibble): home score tens 3 / ones 2, guest tens 6 / ones 5, to-go tens 9 / ones 8,
ball-on tens 11 / ones 10, down 12, quarter 13, clock minutes tens 18 / ones 17, seconds tens 16 / ones 15.
Byte 1 bit 0 = home possession, bit 1 = guest possession. The clock is always `MM:SS`.

## Model 9000 (34 bytes, CRC)
Bytes 32-33 = CRC-16/CCITT (poly 0x1021, init 0xFFFF) of bytes 0..31, high byte first. Values are plain decimal
bytes (`dec`), so a byte of 100+ misreads as ScoreConnect does. Clock as Model 8000 but decimal (bytes 4-6).
Possession: byte 14 bit 4 = home, bit 5 = guest; horn byte 14 bit 0.

| Field | Football | Basketball | Hockey |
|---|---|---|---|
| Home / guest score | 15 / 16 (2 digits, leading zero blank) | 15 / 16 (3 digits) | 15 / 16 |
| Quarter / period | 17 | 17 | 17 |
| Play clock / shot clock | 12 | 9 | |
| Down / ball on / to go | 18 / 19 / 20 | | |
| Timeouts home / guest | 21 / 22 | 23 / 24 | 20 / 21 |
| Fouls home / guest | | 18 / 19 | |
| Foul player (BCD) / his fouls | | 20 / 21 | |
| Bonus H, G, double H, G | | byte 22 bits 0, 1, 2, 3 | |
| Shots on goal home / guest | | | 18 / 19 |
| Saves | | | 22 (see quirks) |

## ScoreConnect quirks reproduced
* Main basketball: `HomeDoubleBonus` is first read from byte 11 bit 0x10 and then overwritten from byte 13 bit
  0x10; `GuestDoubleBonus` is never written. `Period` is read from both nibbles of byte 14, the low nibble wins.
* 9000 hockey: `HomeSaves` is set from byte 22 and then from byte 23; `GuestSaves` is never written.
* Model 3000 has no checksum, so a stray `0xFC` inside the data can misalign frames until the stream resyncs.
* ScoreConnect counts a packet error whenever a partial 3000 frame is buffered; here a partial frame just waits.

## Open questions
* No captures were available; the byte tables come from the decoder logic only. The meaning of bytes
  1, 2, 8 and 15+ not listed above is unknown.
* Whether the 8000 hundreds test (`& 0x86`) really also covers bits 1 and 2 is unverified (copied behaviour).
