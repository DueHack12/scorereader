# iCast (`scoreboards/icast.py`)

Id: `ICast_Basketball` (contract `Basketball`). Wiring: catalog lists "no hardware configuration" (network/serial text feed).

## Framing
NUL bytes are removed. If the buffer contains `Game Time`, the packet ends 4 bytes after the first `T` in the buffer; else if it contains `Intermission Half`, 4 bytes after the first `H`. The packet must split on `;` into exactly 14 fields, else it is rejected. Non-ASCII bytes count as `?`.

## Fields (0-based, split on `;`)
| n | content |
|---|---|
| 0 | clock `m:ss`/`mm:ss` (mode `:`, tenths blank) or `s.t`/`ss.t` (mode `.`) |
| 1 / 2 | home / guest score (1-3 chars, right-justified) |
| 3 | Period (1 char) |
| 4 / 5 | HomeTimeouts / GuestTimeouts (1 char) |
| 6 / 7 | home / guest fouls (1-2 chars) |
| 8 | possession `0` none, `1` home `<`, `2` guest `>` |
| 9 | shot clock `ss`, `s`, or `s.t` |
| 10 | timeout running flag (`0` = no; clears timeout clock) |
| 11 | timeout clock `m:ss` or `ss` (only used while running) |
| 12, 13 | unused (last is the `Game Time` / `Intermission Half` label) |

Malformed fields are skipped (ScoreConnect would abort the packet).

## Open questions
The first `T`/`H` rule breaks if an earlier field contains those letters; matches ScoreConnect.
