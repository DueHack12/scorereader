# OES scoreboards (`scoreboards/oes.py`)

Ids: `OES_AutoDetect`, `OES_BaseballISC85X`, `OES_BaseballPro`, `OES_BaseballStandard`, `OES_Baseball_Code50`,
`OES_Baseball_Code53`, `OES_Baseball_Code85`, `OES_Basketball`, `OES_Basketball_Tissot_Adapter`, `OES_Football`,
`OES_FootballWireless`, `OES_HockeyPro`, `OES_HockeyStandard`, `OES_Hockey_ISC85X`, `OES_Lacrosse`,
`OES_ShortHockeyStandard`, `OES_SoccerPro`, `OES_Volleyball`, `OES_Wrestling` (all 19 implemented).

## Wiring (catalog.json, vendor OES)
| Connection | Hardware | Notes |
|---|---|---|
| Wired | `PIC_RS232_NODECODE_9600_NORMAL` | 9600 baud, raw bytes (no PIC decode) |
| Wired RS-422/485 | `PIC_RS485/22_NODECODE_9600_NORMAL` | 9600 baud |
| Wireless | `DIGI_XBEE_VERSION_CHECK_NODECODE_57600_NORMAL` | 57600 baud |

## Wire format
`STX(0x02) kind data... checksum CR(0x0D)`; `kind` is `t` (0x74, game state) or `s` (0x73, soccer state, or
basketball player stats). Checksum = `sum(STX..last data byte) & 0x7F`, +0x20 if below 0x20. Data bytes are
ASCII; bit 7 is masked (`oes_ascii`), and `:` and non-printables read as blank.

Framing quirks reproduced: ScoreConnect takes the first CR, then the first STX in the buffer. If the STX is
before the CR the span is a packet; otherwise bytes through the CR are dropped. Everything through the CR is
consumed even when the checksum fails. There is no length field, so no length rejection. ScoreConnect counts a
packet error only on the 10th consecutive bad checksum; ScoreReader counts every one in `bad`. Packet length
(STX..CR inclusive) matters only for autodetect and `OES_BaseballPro`.

Decoders update only the bytes they can reach in a short packet and then stop quietly (ScoreConnect throws and
keeps the partial update). Fields a packet does not provide keep their previous value (sticky contract).

## Clock (all sports except baseball)
Byte 5 blank (after `oes_ascii`): `ClockMinutes*="0"`, seconds from bytes 2-3, tenths byte 4, `ClockMode="."`.
Otherwise MM at 2-3, SS at 4-5, tenths `"0"`, `ClockMode=":"`. Baseball sets `ClockMode=":"` only.

## Autodetect (`OES_AutoDetect`, by packet length incl. STX/CR)
21 FootballWireless, 23 Basketball, 25 Football, 31 Volleyball, 32 SoccerPro, 36 ShortHockeyStandard,
44 HockeyStandard, 45 HockeyPro, 47 Lacrosse, 48 BaseballCode85, 52 BaseballISC85X, 75 BaseballStandard,
72 and 117 BaseballPro. A new decoder (fresh contract) is created when a packet with a listed length differs
from the length that selected the current one; other lengths go to the current decoder. `Autodetect.contract`,
`.event`, `.c` follow the selected decoder; `.detected` is the id, `.on_detect` an optional callback.
Not auto-detectable (configure explicitly): Code50, Code53, Hockey_ISC85X, Wrestling, Tissot adapter.

## Per sport (byte index in the whole packet, STX = 0)
Football (`Football`/`Football`): clock; Quarter 6; HomeScore 7-8; GuestScore 9-10; HomeTimeouts 11; GuestTimeouts 12;
HomePossession `<` if byte 13 == 0xB8; GuestPossession `>` if byte 14 == 0xB8; Down 15; ToGo 16-17; BallOn 18-19;
PlayClock 20-21.
FootballWireless: clock; HomeScore 7-8; GuestScore 11-12; Quarter 15; ToGo 17-18.

Basketball (`Basketball`/`Basketball`), `t`: clock; InternalClockStatus `S` if bit 7 of byte 2 else `R` (omitted for
`OES_Basketball_Tissot_Adapter`); Period 6; HomeScore 7-8 with Hundreds `1` if bit 7 of byte 7; Guest 9-10 (bit 7 of 9);
Home/GuestTimeouts and FullTimeouts 11/12; Fouls 13/14 (bit 7 = tens `1`); flags byte 16 (home) / 17 (guest):
bit0 possession (`<`/`>`), bit1 Bonus, bit2 DoubleBonus, bits 2-3 PartialTimeouts (overlaps bit 2, as in
ScoreConnect); ShotClockSecond 18-19 (both 0xB0 = unused, keep previous; bit 7 on byte 18 = single digit in 18).
`s`: byte 2 `H`/`G`, byte 3 `1`-`5`: Player{n} 4-5, FoulNumber 6, Points 7-8.

HockeyStandard / HockeyPro / Hockey_ISC85X / ShortHockeyStandard (`HockeyLacrosse`/`Hockey`): clock; HomeScore 7-8;
GuestScore 9-10; Period 6; goal, timeout and horn fields constant blank. Shots on goal (home tens/ones, guest tens/ones): Standard 11-14, Pro 18-21,
ISC85X 11-14, Short 11-14. Penalties, 4 slots in order home1, home2, guest1, guest2, each = player(2) minutes(1)
seconds(2): Standard from 19, Pro from 22, ISC85X from 17. Short has no player numbers, 3-byte clocks from 19. Slot 3
and minutes-tens are constant blank. Standard, Pro and ISC85X require byte 1 == `t`; Short does not.
Lacrosse (`HockeyLacrosse`/`Lacrosse`): like Pro (shots 18-21, penalties from 22, slots 1-2 only), ShotClock 42-43,
no byte-1 check.

SoccerPro (`Soccer`/`Soccer`, requires `s`): clock; Period 6; Score 7-8/9-10; home Shots 11-12, Saves 13-14,
Corners 15-16, Penalties 17-18; guest Shots 19-20, Saves 21-22, Corners 23-24, Penalties 25-26.
Volleyball (requires `t`): clock; InternalClockStatus as basketball; Set 6 (IsSet3); Score 7-8/9-10; Timeout 11/12;
Serve `*` if byte 17 / 18 == '1'; GamesWon 20 / 22.
Wrestling: clock; Period 6; Score 7-8/9-10; MatchScore 19-20 (home) 21-22 (guest); HomeMatch 25-26.

Baseball (`BaseballSoftball`/`Baseball`, require `t` except ISC85X and Pro's length switch). Layouts (index):
| | Std (75) | Code50 | Code53 | Code85 (48) | ISC85X (52) | Pro long (117) | Pro short (72) |
|---|---|---|---|---|---|---|---|
| Balls/Strikes/Outs | 25/26/27 | 4/17/18 | 10/11/12 | 12/29/30 | 4/5/6 | 30/31/32 | 25/26/27 |
| ErrorFlag | raw 28 (G=E, I=H, `:`=blank) | - | 13 (9=E 6=H 0=blank) | 13 (same) | - | 33 | 6 |
| Guest R,H,E | 30-31, 32-33, 34 | 35-36, 39-40, 42 | 17-18, 19-20, 21 | 33-34, 35-36, 37 | 44-45, 47(ones), 48 | 35-36, 37-38, 39 | 30-31 |
| Home R,H,E | 35-36, 37-38, 39 | 33-34, 37-38, 41 | 22-23, 24-25, 26 | 38-39, 40-41, 42 | 36-37, 39(ones), 40 | 40-41, 42-43, 44 | 35-36 |
| Guest innings 1-10 | 40-49 | 11-15, 26-30 | 27-36 | 2-5, 17-22 | 25-31, 41-43 | 66,68..84 | - |
| Home innings 1-10 | 50-59 | 6-10, 21-25 | 37-46 | 6-9, 23-28 | 17-23, 33-35 | 86,88..104 | - |
| AtBat | 5-6 | 2-3 | 5-6 | 10-11 | 2-3 | 7-8 | - |
| Inning | 3-4 | derived | 3-4 | derived | - | 3-4 | 3-4 |
| Half | byte 2: `1` top, `2` bottom, else blank | byte 49 `1` top else bottom | byte 2 `1` top else bottom | derived | - | byte 2 `G` top else bottom | byte 2 `G` |
| PitchSpeed / PitchCount | 22-24 / " "+12-13 | - | 47-49 / 50-52 | - | - | 27-29 / 14-16 | - |
"Derived" inning (Code50 inning only, Code85 inning and half, and always for Code85 even for non-`t` packets): scan
innings 10 to 1; first inning where the guest linescore is marked decides: both teams marked -> inning+1, `T`;
guests only -> that inning, `B`; none -> `01`, `T`. Half sets `TopBottomInning`, `TopOfInning` (`.`),
`BottomOfInning` (`.`).

## Open questions / oddities
- Basketball bit 2 of the flag bytes feeds both DoubleBonus and the partial-timeout count; copied as is.
- Which baseball layout a given controller sends (Code50/53/85/ISC) is not auto-detectable except by length.
- `HomePlayerPopUp`/`GuestPlayerPopUp` are set to null by ScoreConnect on hockey; not set here.
- No real captures were available; tests use synthetic packets built from the decoded layouts.
