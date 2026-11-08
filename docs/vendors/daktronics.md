# Daktronics (current loop, ScoreConnect "Daktronics Main")

Module: `scoreboards/daktronics.py`. Tests: `tests/test_sb_daktronics.py`. Ids: all 29 `Daktronics_*` entries of the
ScoreConnect III 1.3.0.21 map (the Mac and Windows decompiles are identical for `Daktronics.Main`).
This is a separate implementation from `DaktronicsCurrentLoop` in `scorereader.py`, which is unchanged.

## Wire format and wiring
- Catalog configs: wired `PIC_CURRENTLOOP_NODECODE_19200_INVERTED` (PIC 55 AA mode, delay 2), wireless
  `LAIRD_XBEE_NODECODE_57600_NORMAL`.
- Frame: `55 AA | addr | len | x | x | 22 | data[len-1] | checksum`. Total `len + 7` bytes from the 55.
  `(sum(addr..checksum) + 0x55 + 0xAA) & 0xFF == 0`.
- Decoders receive `p = addr len x x 22 data… checksum 55 AA`; `p[5]` is the first data byte. `n = p[1] + 5` is the
  length ScoreConnect guards against (`if n > k` before reading `p[k-1]`); `Hockey9405` uses `p[1] + 7`.
- Framing is faithful to ScoreConnect: a 55 AA with a bad checksum drops the whole `len + 7` bytes (count in `bad`).
  A stray `55 AA` in line noise can therefore swallow a following frame; it self-heals on the next good frame.
- Data bytes are 7-segment patterns (`digit()`), except the 5500 family (ASCII) and addresses 0xDC/0xDD/0xDD (bitmap
  team names, 8-character result, decoded from column bytes by `_dak_text`).
- Contract state persists between packets (the console sends only changes). Short packets that make an unguarded
  read go out of range abort that packet (`decoder.short` counts them); ScoreConnect would wedge its buffer instead.

## Clock rules shared by most sports
`ClockMode` = `.` if `p[8] == 0` else `:` (addr 1). Clock packet: `:` mode reads `p[5..8]` as MM SS and sets tenths `0`;
`.` mode sets minutes `00` and reads `p[5..7]` as SS t. `InternalClockStatus` = `R` if `p[11] & 0x40 == 0`, else `S`
(addr 1, `n > 12`).

## Per sport (p index, contract field)
| id | addr: fields |
|---|---|
| Football (6601) | 1: p9-10 PlayClock, mode, status. 15: clock, p11-14 scores, p17 possession (7 home, 56 guest), p18/19 timeouts, p15 Quarter. 16: p5-6 BallOn, p7 Down, p8-9 ToGo |
| FootballCode6103 | 1 as Football. 12: p9-12 scores, p17-18 ToGo, p19 Down, p20 Quarter. 13: p13 Quarter. 14: p7/p13 timeouts. 15: clock, scores, possession, timeouts. 16 as Football. 220: p14 possession (64 home, 128 guest) |
| 3000_Football | 1: play clock p9-10, mode. 12: clock, p9-12 scores, p13 possession, p19 Quarter. 23: ball on / down / to go (p5-9) |
| JvcPracticeFootball | as Football but addr 15 sets only the guest score (p13-14) |
| Football1600 | `ClockMode=':'` on every packet. 11: p5-8 clock, p15-18 scores, p19 Down |
| Soccer | 1: mode, status. 11: clock, p15-18 scores, p19 Period. 12: p13&0x80 Horn, p15-18 shots. 13: p15-16/p17-18 corner kicks (2-char strings). 17: p7-8 HomeSaves, p15-16 GuestSaves |
| Basketball | 1: shot clock (p9-10, or p13-15 when n>15), mode, status. 12: clock, p9-12 scores, p14 bits 3/0xC hundreds, p13 bits 4/8/0x10/0x20 possession+bonus, p14 0x30/0xC0 foul tens, p15-16 foul ones, p17-19 foul player, p20 Period, p13&0x80 Horn. 17: p13/14 timeouts. 220: p14 bits 4/8 double bonus. 23-26: player blocks (number p+0..1, fouls p+2, points p+3..4, 5 bytes per player; p20 timeouts; 24: p17 HomeBottomCenter; 26: p17 InboundChannelNumber). 221: team-name bitmaps from p5 |
| Basketball9122 | 1: p13-14 shot clock, clock, status, Horn p11&0x10. 13: timeouts p17/p20, p14 flags (4/8 double bonus, 0x40/0x80 possession, 1/2 bonus), fouls p15-16/p18-19, Period p13, scores p9-12 (+0x80 hundreds). 14: foul player p8-10, Horn p13&0x80. 23-26, 221 as Basketball |
| Basketball5500 | ASCII. Group `p6` / item `p7`. 17/1: status p13 (67 R, 48 S), clock p14-18 (p19 = 32 `:` or 46 `.` with tenths p20). 17/4 shot clock p10-11. 33/1,2: scores at p10-12 (p9=32) or p14-16 (p9=155). 33/6,10,11,12,13,14 timeouts, period, fouls. 81/1,2 team names p13-20 (padded to 8). 49/3,5,7,9 possession, bonus ('1' = on) |
| Volleyball | 1: mode, status. 12: clock, scores p9-12, serve p13 bits 4/8, games won p15-16, Game p19, Set p20. 15: set scores. 17: timeouts p13-14. 23-26 player blocks (number, kills, digs). 221: names from **p4** |
| Volleyball5500 | ASCII, like Basketball5500. Names are not padded. 33/12 HomeGamesWon reads p14 (kept) |
| Hockey5000 / Lacrosse5000 | 1: shot clock p9-10, mode, status. 17: timeouts p13-14. 71: clock, scores, Period p20, Horn. 72/73: penalties p5-14 (two players), shots p15-16, player 3 blanked |
| Hockey5000Code4103 / Lacrosse | 1: mode, status. 11: clock, scores p9-12. 12: Period p20. 13: shots/timeouts p15-20. 23/25: penalties |
| Hockey5000Code9405 | `n = p1+7`. 1: clock (DigitNB for the leading digit), shot clock p9-10, status. 11: shots p5-6 / p9-10. 12: scores (blank ones digit => `00`), Period p20 |
| Baseball / Softball | 64: balls/strikes/outs p7-9, error flag p10 (246 H, 249 E), runs/hits/errors p11-20. 65/66: inning scores p5-14. 61: p11&0xF 1=top 2=bottom. 12: inning p5-6, at bat p7-8. 11: clock. 3: PitchCount (n==12 and bottom, or n==14 and top) |
| Baseball1600 | 61: balls/strikes/outs p13-15 (DigitNB), inning p9, runs p5-8 |
| Baseball5601 | 12: runs p9-12, balls p14, strikes p16, inning p18, outs p19 |
| 3000_Baseball | 63: balls/strikes/outs/inning p5-8, runs/hits p9-17. 11: clock |
| Baseball_Pitch_Clock | 11: p5-8 PitchClock mm:ss |
| BaseBall_Pitch_Speed | 1: p6-8 PitchSpeed |
| Swimming | 1: p5-8 clock, tenths `0` |
| Timer8601 | 1: status. 12: p5-8 clock, p20 tenths (EventId `SingleTimer`) |
| Waterpolo2000 | 1: clock, shot clock, status. 11: scores, Period p13. 15/16: home/guest penalties |
| Wrestling3000 | `ClockMode=':'` always. 11: clock, scores, Period via `Dak3000Period(p13)` (1,67,7,15 => 1-4). 12: advantage flags p13 bits 4/8. 14: match scores. 104: advantage time p17-19, match number p5-7 |
| Rodeo2000 | `ClockMode='.'`. 11: RiderNumber p5-8; running clock p9-12; resets on a new rider while stopped. 12: status from p12, milliseconds |

## Autodetect
`Daktronics_Autodetect` watches address 0xFE (`p[5..8]` ASCII console code) and instantiates a fresh sub-decoder when
the code is known and differs from the current one; `contract`, `event` and `c` follow it. Before any detection the
contract is empty (`EventId: AutoDetect`). Table: 1101/1103 Basketball, 6601 Football, 4401/4402 Hockey5000, 2101
Volleyball, 5501 Baseball, **7701 Soccer**, 0003 Baseball1600, 3101/3102 Wrestling3000. Not selectable by autodetect:
FootballCode6103, 3000_Baseball, Pitch_Clock, Waterpolo2000, Hockey9405 and Softball codes.

**ScoreConnect 1.3.0.21's autodetect table maps soccer to code 7701, while the Rafferty Stadium board sends 7601.** With
that board autodetect never selects soccer; choose `Daktronics_Soccer` explicitly (or add 7601 to `DAK_CODES`).
`ProtocolV3`'s autodetect also reports the choice through `Autodetect.selected` and the `on_detect` callback.

## Real capture through `Daktronics_Soccer`
The `SOCCER` dict from `tests/test_current_loop.py` (code 7601, board showing 60:00, 5-6, half 7) decodes to:
`60:00` stopped (`S`), `HomeScoreOnes=5`, `GuestScoreOnes=6` (tens blank), `Period=7`, shots 1/2, `Horn` off,
saves `00` / ` 1`. **Corner kicks come out blank** (`"  "`): ScoreConnect reads them from address 13, which this
board sends as zeros. The real corners (3/4) are on the address 72 stats panel, which this decoder ignores;
ScoreReader's own `DaktronicsCurrentLoop` handles that, this module does not.

## ScoreConnect oddities reproduced
- Baseball1600 and 3000_Baseball pass the inning and out *characters* as ints (code points) into the top/bottom
  heuristic, so it always answers `T`. Baseball5601 passes real digits, so it works: new inning => `T`, same inning
  with fewer outs than before => `B`.
- Hockey5000 addr 72 writes `HomePenaltyPlayer2Tens` twice (p10 then p11); `...Player2Ones` is never set. Hockey 4103
  addr 23/25 blank `...Player3ClockSecondTens` twice and never `...SecondOnes`.
- Volleyball5500 `HomeGamesWon` reads p14 (the guest counterpart reads p10). Volleyball names start at p4.
- Basketball9122 addr 1 guards the shot clock with `n > 10`/`n > 11` but reads p13/p14.
- Timer8601 tests `ClockMode == 'R'`/`'S'`, which is never set, so hundredths are never decoded.
- Rodeo `Clock` property in the contract uses `ClockMinutesOnes` where seconds tens belongs (contracts concern).
- Basketball5500 names pad to 8; Volleyball5500 names do not (zero bytes after the text read as spaces).

## Open questions
- Only the soccer layout is verified on hardware; every other layout follows the C# unchanged and has only synthetic tests.
- The numeric `VendorSport` ids behind `AutodetectCode` are unknown; `selected` holds the id string instead.
