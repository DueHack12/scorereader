# Small vendors, group C

Eighteen small modules in one document. Facts come from the ScoreConnect III decompiles (Windows build is primary;
these decoders are identical in the Mac build). Contract names are the Sportzcast contract property names. All
protocols have no ACK/handshake; wiring is the ScoreBot hardware string from `catalog.json`. "Decoder ignores packets
shorter than N" means ScoreConnect would throw on such a packet; here the packet is skipped.

| Module | Ids | Wiring (catalog) | Frame | Check |
|---|---|---|---|---|
| uno | Uno_Basketball, Uno_Generic | RS485/422, 115200 inverted | F8 .. 0D | none |
| baybor | Baybor_Basketball | RS485/422, 57600 (or 19200 8N1) | first byte >= 80; 12 bytes, 14 if first in {92,93,96,A0,BE} | none |
| ultrascore | UltraScore | UDP | FE FF type x len ..; total len+6 | none |
| mondo | Mondo_Basketball, Cuma_Basketball | Mondo RS232 19200; Cuma RS485 19200 | 02 type(0-6) .. 03 | none |
| lgr | LGR_Basketball | RS485/422 or RS232, 9600 | 02 .. 03, len > 3 | none |
| esk | ESK_Basketball | RS232 19200 | F8 .. 0D | none |
| colosseo | Colosseo_basketball | RS232/RS485 19200 | 01 LEN type data xor 03; total LEN+5 | xor of all before it, OR 0x80 |
| bertelle | Bertelle_Basketball | RS485/422 9600 | ':' .. (to next ':') | last byte = xor of the rest |
| elakemk | ElakEmk_Basketball | RS485/422 9600 | D3 '4' '1' .. 0D | none |
| scoretec | ScoreTec_Basketball | none listed | see quirk below | none |
| trackman | Trackman_BaseballPitchSpeed | UDP | one JSON datagram | none |
| majordisplay | MajorDisplay_Baseball | XBee 57600 | '!' .. (to next '!'), >= 51 bytes | none |
| hamiltondigital | HamiltonDigital_Hockey | none listed | first byte D4 or 'T' .. 0A | none |
| macfinish | MacFinish_Basketball | none listed | 'D' .. 0D | none |
| farmtek | Farmtek_Timing | RS232 9600 | exactly 7 bytes + 0D | none |
| prospecta | Prospecta_Basketball | RS232/RS485 9600 | D1 LEN type .. sum8; total LEN+2 | sum8 of all but last |
| bicen | Bicen_Basketball | RS232 57600 | FA 44 .. 160 bytes | 16-bit sum of bytes 0..157, big endian at 158-159 |
| grunewald | Grunewald_basketball | RS232 19200 | '#' + 23 bytes + 0D = 25 | none |

## Field maps (packet index -> contract field; ASCII unless noted)

**Uno_Basketball** (index 0 = F8). Clock: p19=='1' -> tenths mode, MM=00, SS=p4,p5, tenths p6; else p4..p7 = MMSS.
Shot clock p23,p24 only when p22=='1' (else 00). Home score p8-10, guest p11-13, Period p14, HomeFoulOnes p15,
**GuestFoulTens p16** (ScoreConnect bug kept: GuestFoulOnes never set), timeouts p17/p18.
**Uno_Generic**: TOTimer p1-3, ClockDigit1-4 p4-7, Home/Guest hundreds..ones p8-13, Period p14, fouls p15/16,
HomeNumberOfTO/Guest p17/18, ClockMode '.' if p19=='1', InternalClockStatus R if p20=='1', PlayClockStatusInternal R
if p21=='1', PlayClockDisplay p22=='1', PlayClock p23,p24.

**Baybor** by first byte: 80 clock (p4 ':' = MM:SS in p2,p3,p5,p6; p4 ' ' = SS.t in p2,p3,p5), possession p7=='p'
home, p9=='p' guest, timeouts p8/p10 ('@' none, 'A'=1, 'B'=2, other=3). 81 shot clock (p1 in ' ',1 = SS from p2,p3;
2,3 = S.t) and PlayClockStatusInternal p9=='1'. 82 scores p1-6, bonus p7/p9=='B', Period p8. 83 fouls
p7-8/p9-10, FoulPlayer p2,p3, FoulPlayerNumberOfFouls p6. 92/93 (146/147) team names p1..; 94 (148) Horn.
96/A0/BE are framed (14 bytes) but not decoded.

**UltraScore** type p2. 1: Period low nibble of p6; InternalClockStatus p7 17=R 18=S; clock p8 MM,p9 SS,p10 tenths
(decimal bytes; any 255 = blank); shot p11 SS, p12 tenths; timeout clock p13; scores p16/p17; fouls p18/p19;
timeouts p20/p21; possession p22/p23 ==1. 2/3 (home/guest): player triples (number, points, fouls) at 7,10,13,16,19,22.
ScoreConnect stores both the 16 and 19 triples in player 4 (19 wins) and the 22 triple in player 5; reproduced.

**Mondo/Cuma**: fields are found by marker byte anywhere in the packet: 0x11 clock (p+1,+2 MM, +4,+5 SS), 0x12
last-minute clock (SS at +4,+5, tenths +7), 0x13 shot (+1,+2), 0x15 period (+1), 0x17 home score, 0x1F guest score,
0x0E home fouls, 0x0F guest fouls. A score has 3 digits unless a marker follows after 2 (then 2 digits) or after 1.
Digits that are not ASCII 0-9 are blank; a leading 0 in hundreds and fouls tens is blanked.

**LGR** type p1: 'i' clock (minutes mode only if p2 >= '0' and p3 > '0': exactly 10:00 reads as 00:00.x), p7,p8 shot
clock, or timeout clock when p10=='T' else InternalClockStatus=p10; '2' scores p2-7; '3' fouls p2-3/p7-8, timeouts
p4/p6 ('0','1' as is, '3'=2, '7'=3), Period p5; '*' possession (p3 '0' none, '1' home, p2=='2' guest).

**ESK** type p1 in '3','7','8'. Clock: p4,p5 and p6,p7 trimmed; 2 chars + 1 char = SS.t, else MM:SS. Horn p19,
shot clock p48,p49 (p52 '1' = SS, '.' = S.t). Type '3' also: possession p3 ('1' home, '2' guest), scores p8-13,
Period p14, fouls p15/16, timeouts p17/18, TimeoutClockMinutesOnes p21, timeout clock p46,p47. ScoreConnect throws on
an unreadable clock and aborts the rest of the packet; here the clock is left alone and decoding continues.

**Colosseo** type p2. 1: Period p4 when p5=='P'; clock p6-7 ':' p9-10 (MM:SS) or SS p6,p7 tenths p9 (p8 not ':');
p3 R/S is stored then immediately overwritten by ClockMode, so run state is not available. 2: scores p3-8, timeouts
p15/16, fouls p17/18, possession p19=='1' home else guest. 17: shot clock. 7: timeout clock p4,p5.

**Bertelle** p1 'P', p2 'W', p3 16: clock p8..p11 (ones first; p8==0x0F -> tenths mode p9,p10,p11), guest score
p6(hundreds),p12,p13; home p7,p14,p15; fouls p16-19; Period from p5 when even ((p5&15)/2), odd leaves it unchanged.
p1 'T', p2 'W', p3 4: shot clock p4,p5.

**ElakEmk** p3 type: 'T'+'P' clock (p6,p7 blank = SS.t from p9,p10,p12; else MM p6,p7 SS p9,p10); 'T'+'O'+':' timeouts
p7/p10; 'T'+'O'+'T' timeout clock p7,p8; 'R' scores p6-8/p11-13; 'A'+'T' shot clock p6,p7.

**ScoreTec** (7-segment bytes): clock p25,p24,p23,p22; possession p16 bit2 home, bit0 guest (no bit = unchanged);
bonus p16 bit3 home, bit1 guest; Period low BCD nibble of p14; score hundreds '1' if p21 & 0x32 (home) / 0x16 (guest);
tens/ones p20,p19 / p18,p17; team fouls p13,p12 / p8,p7; foul player p10,p9, count p11.

**Trackman**: JSON `{"Time":..,"Pitch":{"Speed":"87.3"}}`; PitchSpeed is the integer part. A datagram that is not valid JSON
is appended to a pending buffer (capped 64 KiB) and retried, which reassembles split datagrams.

**MajorDisplay** (custom 7-segment table 6F=0 06=1 CD=2 8F=3 A6=4 AB=5 EB=6 0E=7 EF=8 AF=9): at bat p7,p6; balls p8;
strikes p9; outs p38; runs guest p41,p40, home p46,p45; guest innings p10-13,22-26; home p14-17,28-32. If the packet
contains `TNCHEAD`, team names are 8 characters (not trimmed) after `TNCHEAD:1:1:` and `TNCENDTNCHEAD:2:1:`.

**HamiltonDigital**: ClockMode=p3; ':' MM p1,p2 SS p4,p5, else SS p1,p2 tenths p4. Penalty clocks (MM, SS) home 1 at p7,p8,p10,p11;
guest 1 p13,p14,p16,p17; home 2 p19,p20,p22,p23; guest 2 p25,p26,p28,p29. First byte D4: low BCD nibble; 'T': ASCII.

**MacFinish**: p1-4 MMSS, p5,p6 shot clock. **FarmTek** (Timer contract, parse type OnlySecondsClock): p0-2 seconds, p3 mode,
p4 tenths, p5 hundredths, p6 milliseconds.

**Prospecta** (ALGE CKN V1, multiplier 1) type p2: 4 clocks; 10 team names (p3-10, p15-22, raw bytes); 13 fouls p3,p4,
foul player p5, count p6; 22 clocks + timeout clock p7 + scores p8/p9 + Period p10 + flag byte p11 (bit7 home poss, bit3 guest
poss, bits5-4 home TO, bits1-0 guest TO, bit6 home bonus, bit2 guest bonus) + fouls p12/p13. Clocks: p3 > 0 = MM p3, SS p4;
else SS.t with tenths = high nibble of p5; shot p6 (0xAA = off). Values are decimal bytes.

**Bicen** (BCD nibbles, `Bcd(b, 1)` high / `Bcd(b, 0)` low, A-F blank): scores p52-p54 (6 nibbles), shot p55, clock p56-p58 (low nibble
of p58 blank = tenths mode), Period p61 low, p60 high nibble blank = home fouls in p60 low else timeout clock p60;
p62 low nibble blank = guest fouls in p63 high else timeout clock p62 low/p63 high. Shot clock has no tenths when p63 bit1.

**Grunewald**: Period p1; p2 'C' running 'c' stopped; clock p3-6 (p3,p4 both '0' = SS.t, tenths p7); shot p8-10 when
p17=='A'; scores p11-13/p14-16; timeouts p19/p20; possession p21 '<' or '>'; fouls p22/p23.

## Differences from ScoreConnect

* Scoretec: ScoreConnect copies the packet from the *wrong offset* (`Array.Copy(buf, n, ...)`), so a valid packet is `@` plus
  the 26 bytes after an `@` at buffer index 27. Reproduced exactly (frames are 27 bytes + `@`, decoded one frame late).
* Colosseo decodes as soon as a frame is complete instead of waiting for the next frame's `03 01`.
* MajorDisplay always splits on `!` (ScoreConnect switches to `:` after the first packet in a read).
* ElakEmk ends frames at 0D (ScoreConnect's first pass per read looks for 00).
* Hamilton, MacFinish: ScoreConnect leaves an empty packet stuck at the buffer head forever; here it is dropped.
* Bertelle counts a rejection for every bad checksum (ScoreConnect only on the tenth in a row).
* Trackman has no EventId in ScoreConnect; "Baseball" is used (the catalog event type).

## Open questions

* Scoretec: is the real frame `@`-terminated 27 bytes (so ScoreConnect reads one byte early)? Needs a capture.
* Colosseo run state (p3 R/S) is lost in ScoreConnect; `InternalClockStatus` could be set from it.
* ElakEmk: does the real stream contain 00 separators? Irrelevant here, but unconfirmed.
* Trackman `Time`/`TrackStartTime` are not validated as dates.
