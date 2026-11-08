# Nevco (module `scoreboards/nevco.py`)

## Wire format
- Source: ScoreLinkII/ScoreBot PIC in Nevco decode mode (catalog config `PIC_NEVCO_DECODENEVCO_57600_NORMAL`, serial options `MODEDELAY_DELAY3_STRTCHR02_STPCHR04_INT4D`, 57600 baud, wired).
- Frame: `55 AA B7 L b4 b5 b6 01 payload(L) checksum`; total `L + 9` bytes, all bytes sum to 0 mod 256. Handled by `pic55aa.Pic55AANevco` (verified against ScoreConnect's `PIC55AANevcoProtocol`: code 183, `frame[7] == 1`, checksum, same slice).
- Decoder packet = `frame[6 : 6 + L + 3]`, so `packet[0]` = b6, `packet[1]` = `01`, `packet[2 + k]` = payload byte k, and the last byte is the frame checksum. All indexes below are packet indexes. Real `L` is not known; the tests use 33 (36-byte packet). Decoders need at least highest-index + 1 bytes (34, or 35 for MPC7 types) and ignore shorter packets.
- Minor framing difference: on a frame with the wrong code or no `01`, ScoreConnect clears the whole buffer; `pic55aa.py` skips two bytes and rescans.
- Nibbles: `bcd(b, 0)` is the LOW nibble, `bcd(b, 1)` the HIGH nibble. A-F read blank. State persists between packets.
- Nevco digit code (periods): nibble 0,1,2,4,8,9,A,C,D,E = digits 0-9, anything else blank. Shot clock tens: `byte & 7`, 7 = blank.

## Registered ids
Keys are `PIC55AA_Nevco_<X>`. Contract / event in brackets.

| X | decoder | contract / event |
|---|---|---|
| Football | NevcoFootball | Football / Football |
| Football_Code827 | NevcoFootball827 | Football / Football |
| FootballMPC7, FootballMPC7_Code1 | NevcoFootballMPC7(Code1) | Football / Football |
| Basketball, Basketball_2745 | NevcoBasketball, NevcoBasketball2745 | Basketball / Basketball |
| BasketballMPC7, BasketballMPC7_Code1 | | Basketball / Basketball (only packets with byte 34 = 244) |
| Hockey, HockeyMPC7 | NevcoHockey (ScoreConnect uses the same class for both) | HockeyLacrosse / Hockey |
| LacrosseMPC7 | | HockeyLacrosse / Lacrosse (byte 34 = 112) |
| Soccer, Soccer_Code761, SoccerMPCX | | Soccer / Soccer |
| Volleyball, VolleyballMPC7 | | Volleyball / Volleyball (MPC7: byte 34 = 4) |
| Wrestling | | Wrestling / Wrestling |
| Baseball | full line score | BaseballSoftball / Baseball |
| Baseball_MPCX_Code706 | byte 4 = 247 | BaseballSoftball / Baseball |
| Baseball_MPCX_code_252, SimpleBaseball_Code925, SimpleBaseball_Code673, HandheldBaseball_Code673, SimpleBaseballMPC7 | | BaseballSoftball / Baseball |

There is no autodetect: the sport/model is chosen by the id.

## Per-sport byte map (packet index -> field; `lo`/`hi` = nibble)
Football: clock min tens/ones = 17lo/19lo, sec 21lo/23lo (mm:ss when minutes > 0, else ss.t with tenths 32lo); home score 15lo / 13lo(zero-blank), guest 33lo / 31lo; possession 29 (&3 home `<`, &0xC guest `>`); ball on 5lo/3lo; play clock 4lo (7+ blank) / 6lo; down 7lo; to go 11lo/9lo; quarter 27lo; timeouts home 31hi, guest 33hi.
Football 827: scores home 15hi/13hi, guest 33lo/31lo; possession 11 (&2 home, &4 guest; low nibble 0xF clears guest); ball on 19hi/17hi; play clock (4 & 0xF7)lo, 7+ blank / 6lo; down 27hi; to go 33hi/31hi; quarter 7lo; timeouts home 25hi, guest 21hi; clock as Football.
Football MPC7 (/Code1): clock sec 24, min 26 (tens = lo, ones = hi; high nibble of 24 blank = ss.t with tenths 24lo); guest score 6, home 8; possession 14 (&4/&8), flag 14&0x10 `F`; play clock 16; quarter 33hi; timeouts 11lo/11hi. MPC7: ball on 29, down 4hi, to go 31. Code1: ball on 4, down 31lo, to go 29.
Basketball: clock minutes tens digit = low nibble of `(b30 & 0xC) | (b17 & 3)`, ones 19lo, sec tens (21 & 7), ones 23lo, tenths 32lo (used under one minute); score home 15lo/13lo + hundreds 29&4, guest 33lo/31lo + hundreds 29&8; possession 25 (&4 `<`, &8 `>`), horn 21&8, bonus 17&4/&8, period = Nevco digit of 27lo; shot clock tens (4 & 7), ones 6lo, blank unless 6lo is a digit. Model-specific: Basketball fouls team 11lo/9lo + tens 29&1/&2, timeouts 28 home/26 guest, player foul 5/7, count 3; 2745 fouls 11hi/31hi, timeouts home 29hi, guest 23hi; MPC7 adds double bonus 20&4/&8, guest fouls 9lo (player 3/5, count byte 1 = constant `1`); Code1 guest foul tens 22lo, ungated shot clock, score ones not zero-blanked.
Hockey: clock min tens (17 & 3)lo, ones 19lo, sec tens (21 & 7), ones 23lo, tenths 32lo; shot clock 4/6; scores 15/13, 33/31; goal lamp 17&4 -> `*`; guest goal 17&8 -> guest score ones digit; shots on goal 16hi/14hi, 12hi/10hi; period 27lo; horn 21&8; penalties home p1 9/7 etc. (see `NevcoHockey.rows`).
Lacrosse MPC7: as MPC clock; penalties home 7, 19; guest 5, 17; period 10hi; shot clock 16; scores home 8, guest 6.
Soccer: clock 17/19/21/23 lo; scores 15/13, 33/31; shots home 5/3, guest 11/9; period 27. 761: scores home hi nibbles of 15/13, shots home 33hi/31hi, guest 19hi/17hi, period 7. MPCX: clock 26/24, home score 8, guest 6, shots 4 and 33, period 10hi.
Volleyball: game 5lo, games won home 11lo / guest 9lo, scores 15/13, 33/31, clock min tens (17 & 3), ones 19lo, sec (21 & 7)/23lo, serve 25&4/&8 `*`. MPC7: set = game = 5lo, timeouts 28/26, clock as football.
Wrestling: clock 17(0 blank)/19/21/23, scores 15/13, 33/31, match scores 29&1 / 11lo and 29&2 / 9lo, period Nevco digit 27lo; byte 25 = 12 shows weight class (3,5,7 lo) else advantage time; 25 = 4 / 8 sets advantage home / guest.
Baseball (full): balls/strikes/outs 28/26/24, inning 18/16, runs 13/11 (hi guest, lo home), line score 10 innings at byte 35-2n (hi guest, lo home), hits 9/7, errors 5, at bat 32/30, error flag 22 (12 `E`, 3 `H`). Half inning: bottom when the home line score of the current inning is filled.
Other baseball variants: see `rows` in the module (252 uses bit-coded B/S/O lamps; 673 infers the half inning from outs/inning changes).

## Differences from the Mac build (Windows decompile is primary)
- `BasketBallMPC7Decoder`: `GuestFoulOnes` reads byte 9 (Mac: byte 7).
- `FootBallDecoder`: play clock tens of 7 or more is blanked.
- `Football827Decoder`: play clock tens uses `byte4 & 0xF7`, and 7 or more is blanked.
- The other Nevco decoders and the Nevco protocol/registrations are identical.

## Oddities reproduced
- MPC7 basketball foul count reads packet[1], the constant `01`, so it always shows `1`.
- Hockey guest "goal" shows the guest score ones digit.
- A packet shorter than needed is ignored whole (ScoreConnect would throw part way, leaving earlier fields written).
- `HockeyMPC7` uses the plain hockey byte map, as in ScoreConnect.

## Open questions
- Real payload length `L` (the MPC7 marker at packet[34] equals the frame checksum when `L = 32`).
- Nothing was tested against a real Nevco board; all layouts come from the decompiled decoders.
