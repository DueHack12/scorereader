# Tissot (`scoreboards/tissot.py`)

Id: `Tissot_Basketball`. Catalog: PIC RS-485/422, 115200 baud, wired or inverted; start 0x02 / stop 0x04.

Frame: `01 34 7C 36 …` up to `04` (`\x014|6|<id>|…`), no checksum. The packet starts at the first SOH; packets with another
header are rejected. Text between SOH and EOT is split on `|`.

| id | content |
|---|---|
| 1 | `f[4]`/`f[5]` home/guest score, right-aligned 3 chars |
| 2 | `f[4]`/`f[5]` fouls; `f[6]`/`f[7]` bonus: `1` -> Bonus, `2` -> DoubleBonus |
| 4 | `f[5][0]` Period |
| 5 | `f[4]` possession 1 home `<`, 2 guest `>`, 3 both, else none |
| 17 | `f[4]`/`f[5]` team names |
| 30 | `f[4]` game clock, `f[6]` timeout clock `M:SS`, `f[9]` = `1` -> InternalClockStatus `S` else `R` |
| 31 | `f[4]` shot clock (tenths only when it contains `.`) |
| 32 | `f[7]`/`f[8]` timeouts |

## Windows build change (followed)
Game clock parsing (`TissotClock`): `MM:SS` and `SS.t` use lenient integer parsing and keep only the last two digits
(`123:45` -> 23:45). The older Mac build rolled minutes over like a TimeSpan. In `SS.t` mode the tenths come from the
TimeSpan text of `sec + frac*100+1 ms`, i.e. the fraction digit itself. The timeout clock still uses TimeSpan rolling
(`M:SS` -> minutes ones, seconds), per `TissotTimeoutClock`.

## Open questions
- No captures. Shot-clock strings are right-aligned with spaces, assumed from `StringToCharRight`.
