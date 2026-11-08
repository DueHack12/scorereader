# Fair-Play models (`scoreboards/fairplay_models.py`)

Decoders and protocols checked against the newer Windows decompile (win_src); the Mp80, Proline, Mp69 and PIC55AA
Fair-Play namespaces are identical to the Mac build. Contract field names are the Sportzcast ones.

## Wiring (from catalog.json)
| Vendor | Config | Baud | Notes |
|---|---|---|---|
| Fairplay MP69 | PIC RS485/422, `DECODEMP69`, inverted or normal | 57600 | ScoreLinkII decodes; frames are PIC 55 AA code 0xBA |
| Fairplay MP70 | PIC RS485/422, `DECODEMP70`, normal | 57600 | PIC 55 AA code 0xBF |
| Fairplay Proline | PIC RS232, no decode | 9600 | ASCII, STX/ETX |
| FairPlay MP80 Wireless | Digi XBee, no decode, read timeout 50 ms | 57600 | packets delimited by the radio link, not by bytes |

## MP80 / MP70 inline baseball (wireless)
No delimiters. A packet is a series of 2-byte words, `word16 = (address << 4) | nibble`, followed by a
checksum word: big-endian sum (not mod 256) of all preceding bytes. The last word is never decoded.
ScoreConnect treats each read as one packet and discards the buffer. ScoreReader keeps the buffer until the whole
thing validates; if it doesn't, it looks for the longest tail (>= 6 bytes, even length, non-zero checksum) that
does, so garbage or a bad frame in front of a good one is dropped. Over 512 bytes without a match the buffer is
dropped. One frame per read is assumed (two frames in one read keep only the last).

A 32-byte packet starting `3F D0` carries team names: home from byte 6 up to 0x00/0x0A, then guest up to 0x00/0x0D
(0x0A skipped).

Nibble decoding is BCD (A-F = blank). Clock (all but baseball): address 10 is the seconds-ones nibble; a blank
nibble selects tenths mode (`ClockMode` `.`), otherwise `:`. Address 7/8 are minutes tens/ones (colon) or seconds
tens/ones (tenths, minutes forced `0`); 9 is seconds tens (colon, tenths `0`) or tenths. Order within the packet
matters (mode is remembered from the previous word/packet).

| Sport (contract/event) | address -> field |
|---|---|
| Football | 2/1 HomeScoreTens/Ones, 5/4 Guest, 19 HomeTimeouts, 20 GuestTimeouts, 260 HomePossession `<` (nibble != 0), 259 GuestPossession `>`, 36 Quarter, 35 Down, 17/18 BallOnTens/Ones, 37/38 ToGoTens/Ones, 210/209 PlayClockTens/Ones |
| Basketball | scores as above plus 3 / 6 Home/GuestScoreHundreds (0 reads blank), 123/121 HomeFoulTens/Ones, 124/122 Guest, 19/20 Timeouts, 260/259 possession, 262/261 Bonus (nibble == 1), 268/267 DoubleBonus, 210/209 ShotClockSecondTens/Ones, 36 Period, 15 Horn (== 1) |
| Hockey (HockeyLacrosse/Hockey) | scores, 36 Period, 15 Horn, 148/149 HomeShotOnGoalOnes/Tens, 150/151 Guest |
| Soccer | scores, 36 Period, 37/38 HomeShotTens/Ones, 17/18 Guest; two-character strings: HomeCornerKicks 282 (first char) 306 (second), GuestCornerKicks 255/298, HomeSaves 313/314, GuestSaves 303/305 |
| Volleyball | scores, 121 HomeGamesWon, 122 GuestGamesWon, 19/20 Home/GuestTimeout, 36 Game |
| Baseball (BaseballSoftball/Baseball) | 41 Balls, 42 Strikes, 43 Outs, 2/1 HomeRun, 5/4 GuestRun, 49/50 HomeHits, 47/48 GuestHits, 146 HomeErrors, 145 GuestErrors, 45/46 AtBat, 44/36 InningTens/Ones, 260 top/bottom (1 = `B`), line score: guest innings 1-10 at 265,263,247,245,188,189,190,191,192,219; home 253,256,296,278,199,200,201,203,204,220 |
| MP70 inline baseball | same as baseball without 44/36; inning derived from the line score: scanning from inning 10 down, both halves filled = next inning (n+1), only guest filled = inning n bottom pending |

Oddities: unset line-score cells are treated as blank (ScoreConnect's C# default is NUL, which would make the inline
derivation read "11"); the nibble for possession/bonus flags is raw, not BCD.

## Proline (RS-232)
`02 <letter A-Z> ... 03`. The first STX in the buffer starts the message ending at the first ETX; a non-letter second byte
is rejected; an ETX with no STX before it is skipped. Fields are ASCII (`ascii_char`, `slz` = leading zero blanked).
Indices count STX as byte 0. Names are 8 characters, not trimmed.

Clock message `C`: bytes 2-5 mm ss, 6 tenths. Colon mode if mm >= 1 or byte 6 is blank (tenths `0`, except football
which leaves tenths untouched); otherwise tenths mode (minutes `00` except football). Then Period/Quarter at 7.

| Sport | message -> bytes |
|---|---|
| Football `F`(70 decimal letter 'F') | name 2, HomeScore 12-13, HomeTimeouts 14, guest name 15, GuestScore 25-26, GuestTimeouts 27, Down 28, ToGo 29-30, BallOn 31-32, possession 33 (`H`/`V`). `C`: Quarter 7, PlayClock 8-9 |
| Soccer `R` | home name 2, score 12-13, shots 14-15, saves 16-17, corners 19 (stored as `" "+digit`); guest name 20, score 30-31, shots 32-33, saves 34-35, corners 37. `C`: Period 7 |
| Basketball `B`+`H`/`V` | name 3, score 13-15 (hundreds, tens, ones), fouls 16-17, timeouts 18, possession 19, bonus 20, double bonus 21 (non-`0` = on). `C`: Period 7, ShotClockSecond 8-9 |
| Baseball `A` | inning 2-3, balls 4, strikes 5, outs 6, half 7 (`H` = bottom), at bat 8-9, ErrorFlag 10, PitchCount 12-14. `T`+`H`/`V`: runs 13-14, hits 15-16, errors 17, innings 1-10 at 19,21,...,37 |
| Hockey `H` | home name 2, score 12-13, SOG 14-15, penalties 1-2 (6 bytes each from 16); guest name 28, score 38-39, SOG 40-41, penalties from 42. `C`: Period 7, ShotClock 8-9 |
| Lacrosse `L` | home name 2, score 12-13, TimeOut 14, SOG 15-16, Saves 17-18, penalties 1-3 from 19; guest name 37, score 47-48, TimeOut 49, SOG 50-51, Saves 52-53, penalties from 54; possession 72. `C`: ShotClock 8-9, Period 7 |
| Volleyball `V`+`H`/`V`; `Y`+`H`/`V` | `V`: name 3, score 13-14, GamesWon 15, Timeout 16, Game 17, serve 18 (`1`). `Y`: players 1-6, 6 bytes each from 3: number (2), kills (+3), digs (+4,+5) |

Oddities kept: basketball with a three-digit score never refreshes the tens digit; basketball packets shorter than 19
bytes only update the team name (ScoreConnect reads past the end); volleyball writes `HomeServe` from either side's message.
Messages shorter than the last index they need are ignored.

## MP69 via PIC 55 AA (code 0xBA)
Payload (frame bytes 8..8+L, needs >= 7): b0 bits 0x60 = horn; b1 flags: 0x08 home possession, 0x04 guest possession,
0x80/0x40 home/guest score hundreds ("1"), 0x20/0x10 home/guest bonus (basketball), football 0x08/0x04 as above,
baseball 0x04 top / 0x08 bottom; b2 low nibble quarter / period / inning ones; b3 guest score BCD, b4 home score BCD;
baseball b5 low = outs, b6 = balls (high) strikes (low). Clock: b5 low nibble F = tenths mode (b6 seconds, b5 high
tenths), else b6 minutes, b5 seconds. Basketball Code0 and Code42 share the decoder.

## MP70 auto-detect via PIC 55 AA (code 0xBF)
Payload plus nine zero bytes is a normal Fair-Play packet; byte 0 is the sport code. The decoder switches to a fresh
Fair-Play main-family decoder when the code changes (0-12 basketball variants, 13/14 hockey, 21 lacrosse, 22/36 soccer,
23-27 football, 30-35 baseball). It resolves them lazily from `scoreboards.create("Fairplay_<Sport>_Code<N>")`, so it needs
`fairplay.py` to be registered; unknown or unavailable codes are ignored. `contract`, `event`, `c` follow the selection.

## Open questions
* MP80 real-world framing (does each radio read hold exactly one packet?).
* Proline clock: ScoreConnect's `forceTeamNameOverride` change in win_src only affects team-name insertion, not decoding.
