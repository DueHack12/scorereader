# Daktronics serial protocols (`scoreboards/daktronics_serial.py`)

Four wire formats, 32 ids. Derived from ScoreConnect III (Windows build) behaviour; the Daktronics All Sport 5000 current loop (football 6601 / soccer 7601) is handled separately in `scorereader.py`.

| Family | Ids | Catalog wiring |
|---|---|---|
| Daktronics Public (RTD text) | `DaktronicsPublic_{Baseball,Softball,Football,Basketball,Hockey,Lacrosse,Volleyball,Soccer,Swimming,Rodeo}` | RS-232 via PIC, no decode, 19200, normal polarity. Eth-serial: start 0x16, stop 0x17 |
| AllSport CG | `DaktronicsAllSportsCG_{Football,Basketball,BasketballUNCG,Hockey,Volleyball,Baseball,Wrestling}` | RS-232 via PIC, no decode, 9600, normal. Start 0x02, stop 0x04 |
| 4000 V2 | `Daktronics4000_{Football,Football_Code27,Hockey,BaseballSoftball,Volleyball,Soccer,Basketball_Code3,Basketball_Code4}` | catalog: "no hardware configuration" (serial/Ethernet bytes). Eth-serial start 0xAA, stop 0xAB. Console sport codes: basketball 3/4, football 22/27 |
| PIC 55 AA 4000 | `PIC55AA_Daktronics4000_{Football,Football_Code27,Hockey,BaseballSoftball,Volleyball,Soccer,Basketball}` | current loop, PIC decode `DECODEDAK4000`, 57600, inverted |

## Framing and checksums

**Public** (`PublicProtocol`): `SYN(0x16) … SOH(0x01 at frame offset 9) … ASCII offset at offsets 17-19 … STX text EOT … ETB(0x17)`. The text between STX and EOT is written into a persistent 1024-byte image (spaces initially) at the zero-based offset; the decoder reads fixed columns of the whole image after every frame. No checksum is checked. Only the SOH at offset 9 is tested. Rejected: SOH missing, frame < 20 bytes, no EOT, write past 1024. Header-only frames (no STX) are ignored silently.

**AllSport CG** (`AllSportCGProtocol`): everything up to the first EOT(0x04) is one packet including SOH(0x01) at index 0 and the EOT; all column numbers below count from the SOH. No checksum. ScoreConnect discards a packet that does not start with SOH; here junk before an SOH is dropped (one reject) and the frame is still decoded. Packets shorter than the layout needs are rejected (ScoreConnect would hit an index error and publish nothing).

**4000 V2** (`Dak4000V2Protocol`): `AA <16 data bytes> AB`, 18 bytes, no checksum. Data bytes are active-low 7-segment bytes: 64=0 121=1 36=2 48=3 25=4 18=5 2=6 120=7 0=8 24=9, 255=blank, anything else reads as blank. The frame is the 18 bytes ending at the first AB; ScoreConnect takes the first AA instead, so junk with an AA ahead of a frame loses that frame there but not here. An 0xAA inside the data is fine; an 0xAB would end the frame early in both.

**PIC 55 AA** reuses `pic55aa.Pic55AADak4000` (code 0xBD, sum-to-zero checksum). The payload is the L data bytes zero-padded; the same 16-byte decoders apply. A payload shorter than 16 bytes is ignored.

## Clock (all families)

* Public: `a[2] == '.'` means SS.t at `a[0..1]` and `a[3]`, minutes forced to `00`, `ClockMode='.'`; otherwise MM at 0-1, SS at 3-4, tenths `0`, `ClockMode=a[2]` (normally `:`). `InternalClockStatus = 'R'` when column 27 (0-based) is blank, `'S'` otherwise (not set for soccer, swimming).
* CG: `a[6] == '.'` means SS at 4-5 and tenths at 7 (`ClockMode '.'`), otherwise MM at 1-2, SS at 4-5 (`ClockMode ':'`). Wrestling tests column 3 for the dot instead.
* 4000: if byte 3 decodes blank the clock is SS.t from bytes 0-2 (`'.'`), else MM from bytes 0-1, tens of seconds byte 2, ones of seconds byte 3 (`':'`).

## Public layout (0-based columns of the image)

Team names: home 47-54, guest 67-74 (8 chars; the RTD manual's field is 20 wide). Scores are the last two (three for basketball) characters of the manual's 4-wide score field.

| Sport | Columns -> contract |
|---|---|
| Football | playclock 203-204; score H 109-110, G 113-114; possession H 209, G 214; timeouts H 122, G 130; Quarter 142; BallOn 219-220; Down 221; ToGo 224-225; HomeScoreQuarter1-4 246-253 (pairs); Home/Visitor yards rushing/passing/total 266-289 (4 each); first downs H 290-291, V 292-293; Flag 310 |
| Basketball | shot clock 203-204; score H 108-110, G 112-114; poss H 209, G 215; timeouts H 122, G 130; Period 142; bonus H 223, G 230; team fouls H 235-236, G 237-238; FoulPlayer 255-256 + count 257; Horn 208; full/partial timeouts H 115/117, G 123/125; players: home at 304 + 7n, guest at 475 + 7n (n=0..4): number 2, FoulNumber +3, Points +4..5 |
| Hockey / Lacrosse | shot clock 203-204; score 109-110 / 113-114; TimeOut H 131, G 136; full/partial remaining H 116/118, G 124/126; SOG H 422-423, G 468-469; Period 142; Horn `'H'` if column 28 is `h`; penalties home 225/235/245, guest 285/295/305: number +0..1, minutes +2..3, seconds +5..6; PlayerPopUp blank |
| Baseball / Softball | Balls 221, Strikes 222, Outs 223; Inning 141-142; runs H 109-110, G 113-114; hits H 202-203, G 208-209; errors H 205, G 211; AtBat 214-215; ErrorFlag 226; `TopBottomInning 'T'` if column 201 is `>`; TopOfInning/BottomOfInning `.` from 201 `>` / 200 `<`; line score home 258 + 2n, guest 282 + 2n (n=0..9) |
| Soccer | score 109-110 / 113-114; Period 142; timeouts 122/130; poss H 200, G 205; shots H 259-260, G 303-304; saves H 270-271, G 314-315; corners H 281-282, G 325-326; penalties H 292-293, G 336-336 |
| Volleyball | score 109-110 / 113-114; GamesWon H 215, G 217; serve H 200, G 207; timeout H 122, G 130; set scores home 221-228 (pairs), guest set 1 at 247-248; Set 220; Game 142; players home 262 + 7n, guest 429 + 7n (n=0..5): number 2, Kills +3, Digs +4..5 |
| Swimming | minutes 0-1, seconds 3-4, tenths 6 (no mode, no names) |
| Rodeo | clock mm:ss.ttt at 0-1, 3-4, 6, 7, 8 (`ClockHundreths`, `ClockMilliSeconds`); Rider number 30-33, score 17-18/20-21/23-25; Leader number 61-64, score 52-53/55-56/58-60; Prev rider number 84-87, score 75-76/78-79/81-83; ReRide `R` if 204 is `F`; Penalty `P` if 205 is `P` |

`EventId` for the softball id is `Baseball` (ScoreConnect ignores the softball event type in the decoder).

## AllSport CG layout (columns from SOH)

| Sport | Columns -> contract |
|---|---|
| Football | names H 6-13, G 16-23; clock `:` MM 1-2 SS 4-5; playclock 38-39; score H 26-27, G 28-29; poss H `<` / G `>` when 36 / 37 non-blank; Quarter 30; BallOn 31-32; Down 33; ToGo 34-35; timeouts H 25, G 28 (see quirks) |
| Basketball | InternalClockStatus = char at 8; shot clock 9-10; score H 13-15, G 16-18; fouls H 19-20, G 21-22; full/partial/timeouts H 23/24/25, G 26/27/28; Period 29 |
| Basketball UNCG | same, shifted: shot clock 9-10; score H 11-13, G 14-16; fouls 17-18 / 19-20; timeouts H 21/22, G 23/24; Timeouts H 25, G 26; Period 27 |
| Hockey | score H 9-10, G 11-12; TimeOut H 13, G 14; Period 19; SOG home tens 17 (ones 16), guest tens 18; penalties home 21, 28; guest 35, 42 (number +0..1, minutes +2..3, seconds +5..6) |
| Volleyball | status `S` if column 8 is `s` else `R`; score H 9-10, G 11-12; timeouts 13 / 14; serve 15 / 16; GamesWon 17 / 18; Game 19; Set 20; HomeScoreSet1-4 pairs from 20; GuestScoreSet1-4 pairs from 28 |
| Baseball | needs > 159 bytes; runs G 7-8, H 3-4; AtBat 41-42; Inning 9-10; hits H 28-29, G 34-35; errors H 31, G 37; B/S/O 48-50; ErrorFlag `E` if 52 non-blank, else `H` if 51 non-blank; line score home 85 + 2n, guest 109 + 2n (n=0..9); PitchCount = three chars ending at 165 (top) or 148 (bottom), only when the packet is long enough |
| Wrestling | clock dot test at column 3 (`.` -> SS 4-5, tenths 7; else MM 1-2, SS 4-5); status `S` if 8 is `s`; score H 9-10, G 11-12; GuestMatchScore 15-16; Period 17; advantage time 22, 24, 25; AdvantageHome / Guest `*` if 26 / 27 non-blank |

## 4000 layout (data byte index; every byte through the digit table unless noted)

| Sport | Bytes -> contract |
|---|---|
| Football (22) | score H 4-5, G 6-7; Down 9; ToGo 10-11; BallOn 12-13; Quarter 14 |
| Football Code 27 | score H 6-7, G 8-9; Quarter 10; timeouts H 13, G 14; possession from raw byte 12: 248 -> home `<`, 199 -> guest `>` |
| Basketball (codes 3 and 4, same decoder) | score tens/ones H 4-5, G 6-7; hundreds `1` when byte 9 bits 0-1 (home) / 2-3 (guest) are clear; team-foul tens `1` when byte 9 bits 4-5 / 6-7 clear; foul ones H 10, G 11; possession `<`/`>` when byte 8 bit 2 / 3 clear; bonus `B` when bit 4 / 5 clear; FoulPlayer 12-13, count 14; Period 15; shot clock and timeouts blank |
| Hockey | score H 4-5, G 6-7; SOG H 10-11, G 12-13; Period 15 |
| Baseball / Softball | no clock. AtBat 0-1; B 2, S 3, O 4, ErrorFlag 5; guest runs 6-7, hits 8-9, errors 10; home runs 11-12, hits 13-14, errors 15. No inning field |
| Volleyball | score H 4-5, G 6-7; serve `*` when byte 9 bit 1 (home) / bit 0 (guest) is **set**; GamesWon H 10, G 11; Game 14 |
| Soccer | score H 4-5, G tens 6; Period from byte 8 (252 -> 1, 231 -> 2); corners H byte 11, G byte 13 (as two chars, leading blank); shots, saves, timeouts blank |

## Comparison with ScoreReader's generic RTD decoder

* Framing: ScoreReader (`DaktronicsRTD`) accepts SYN ... ETB, finds the first SOH anywhere, requires the header to start `004210` (strict mode), and reads a 4-digit offset from the last 4 header characters. ScoreConnect requires SOH at exactly frame offset 9, checks no header string at all, and reads only 3 digits (offsets 17-19), so the thousands digit of the offset is ignored. Both write into a 1 KB image at a zero-based offset and neither checks the checksum.
* Columns: every ScoreConnect Public column equals the 1-based `pos - 1` in `daktronics_fields.json` (checked for football, basketball, baseball, hockey, soccer, volleyball and rodeo), e.g. `main_clock_stopped` pos 28 = column 27, `home_team_score` pos 108 (4 wide) -> tens/ones read at 109-110. ScoreConnect reads only the last digit of the 2-3 char fields it treats as a character (Down at 221 is the first of 221+3, Quarter at 142 the ones digit of 141+2, GamesWon 215 the ones of 214+2) and only 8 characters of the 20-wide team names.
* Not in the JSON table: football Flag (310), rodeo Penalty/ReRide (205/204) and rodeo previous-rider columns 75-87; basketball foul-number columns 306-307 are 306+2 in the JSON but ScoreConnect reads 307.

## Quirks reproduced from ScoreConnect

* Public football: `HomeScoreQuarter1-4` are read from 226-233 and then overwritten from 246-253; visitor quarter scores are never set.
* Public volleyball: `GuestScoreSet1` is overwritten four times (final value 247-248); `GuestScoreSet2-4` never set.
* Public soccer: `GuestPenalties` reads column 336 twice. Public rodeo `Penalty` is only ever set to `P` (sticky).
* CG football: timeouts are read from 40/41 and overwritten by 25 and 28; column 28 is the guest score tens digit, so `GuestTimeouts` mirrors it.
* CG hockey: `HomeShotOnGoalTens` is overwritten from 17; `GuestShotOnGoalOnes` is never set. CG wrestling: `HomeMatchScore*` is never set (13-14 are read, then replaced by 15-16 as the guest match score).
* CG baseball: "top of inning" is `half[n-1] != ' ' and half[n] == ' '` with n the inning number over the interleaved line score G1,H1,G2,H2,..., which only makes sense in early innings. Out-of-range innings read as bottom.
* 4000 soccer: `GuestScoreOnes` is blanked. Flag `_D4Soccer.blank_guest_score_ones = False` keeps the real digit.
* Baseball and softball both report `EventId` Baseball.
* PIC 4000 payloads are zero padded, and a zero byte decodes to "8".

## Open questions

* AllSport CG `InternalClockStatus` for basketball is the raw character at column 8 (expected `R`/`S`); other values pass through.
* Public columns for lacrosse are the hockey ones; the manual may differ.
* The 4000 V2 basketball code 3 / code 4 ids use the same decoder in ScoreConnect; the difference may be in what the console sends, which is unverified.
* No captures were available for any of these boards; all tests use synthetic frames.
