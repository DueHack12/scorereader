# Contracts (`scoreboards/contracts.py`)

Output layer for every vendor decoder. A decoder fills a **contract dict** (exact Sportzcast property names, one
character per `char` property, missing = `" "` for chars and `""` for strings, `EventId` = EventType name).
`contracts.py` turns it into the Sportzcast MQTT JSON, the 150-character sbdata string and ScoreReader's flat fields.
Source: the Windows ScoreConnect III 1.3 `Contracts/*`, `ClockStatusEmulator`, `Utilities/EventType`, `OriginType*`,
`HexDateTime12`. Ingress (re-parsing sbdata) is not implemented.

## API

| call | result |
|---|---|
| `CONTRACTS` | `Football, Soccer, Basketball, BaseballSoftball, HockeyLacrosse, Volleyball, Wrestling, WaterPolo, Tennis, TableTennisBadminton, FutsalHandball, DragRacing, Rodeo, Timer, Generic, SwimmingDetail, SwimmingEvent, SwimmingRows, SwimmingMixed` |
| `ClockStatusEmulator(contract=None).apply(c, now=None)` | stateful; writes `EmulatedClockStatus` / `EmulatedPlayClockStatus` into `c` |
| `sportzcast_json(contract, c, meta)` | dict of every serialised property (computed ones included, `[JsonIgnore]` ones omitted) |
| `sbdata(contract, c, meta)` | 150-char string |
| `flat(contract, c)` | snake_case fields + aliases |
| `swap_teams(contract, c)` | `SwapTeamInformation` on a copy |
| `event_code(name)` | sbdata chars 0-1 (`"Softball"` -> `"04"`) |

`meta`: `bot_number`, `home_team_name`, `guest_team_name` (non-empty wins over the contract), `publish_rate`,
`now` (epoch seconds), `channel` (default `"1"`), `origin` (default 1 = Local), optional `venue_name`, `venue_id`,
`venue_genius_id`.

Property order in the JSON: base-class properties first (the order of the existing `build_payloads()` is kept except
`ClockMode`, which follows `Sport.cs`: after `VendorSportId`), then the sport's own in declaration order. Json.NET's
real order for derived classes is unverified; consumers should not depend on it.

### Contract-specific input keys
* `Timer`: `ParseType` = `Lanes` / `FullClock` (default) / `OnlySecondsClock` (or 0/1/2). Alge lane timers and FarmTek
  timing must set it (ScoreConnect passes it to the constructor).
* `DragRacing`: `IsDetailed` (bool) picks the sbdata layout.
* `SwimmingRows`: `RowType` (`Row1To3`/`Row4To6`/`Row7To9` or 0-2) derives `RowA/B/CNumber` unless given.
* `SwimmingMixed`: `PacketType` (`Event`/`Rows` or 1/2) selects `c["SwimmingEvent"]` / `c["SwimmingRows"]` (nested
  contract dicts); sbdata is the sub-contract's.

## Behaviours ported (worth knowing)
* `Clock`: `:`/blank mode gives `M:SS` (leading blank/zero minute tens dropped, trimmed: `4:32`, `0:45`); other modes give
  `SS.t` with a leading zero dropped (`59.8`, `5.3`). `FullClock` is always `MM:SS.t`.
* `ClockStatus` / `PlayClockStatus` = the internal value if not blank, else the emulated one. Without calling the
  emulator they stay `" "`.
* Computed score strings (`HomeScore`, `GuestScore`, `HomeRuns`, `HomeMatch`, ...) use `BuildScore`: control characters
  become blanks, leading blanks and zeros are trimmed, empty becomes `"0"`. **sbdata does not use it**: positions get the raw
  digit characters (right aligned), so a 7 is `" 7"`.
* `Basketball.Period` collapses anything above `'4'` to `'E'`.
* `WeightedCoverage` exists only for Football, Soccer and Basketball (0.0 elsewhere). Several terms test "string not
  empty" on concatenations that are never empty, so a bare Football contract already scores 0.7. Soccer's weights can sum
  to 1.02 (team names 5 each in the code, 6 in `CoverageWeights/Soccer.cs`; the code was followed).
* Soccer sbdata 47/48 hold the second-to-last character of the corner strings (only when two or more characters).
* Basketball swap does not touch `HomeScoreHundreds`/`GuestScoreHundreds` (ScoreConnect omits them).
* **Tennis and DragRacing swap**: ScoreConnect flips `Advantage` / `Win` on the source object, not on the returned clone,
  so the returned copy keeps the old value. Reproduced; the input dict is never modified.
* Volleyball, Wrestling, WaterPolo, Futsal/Handball, Hockey/Lacrosse (apart from possession), Generic (only names) swap
  team names (and the listed fields) only; Timer, Rodeo, Swimming* swap nothing.
* Tennis/TableTennis `Clock` is `{HourOnes}{HourTens}:{MM}` (hour digits reversed relative to sbdata 2-3). The `{58}`/`{46}`
  holes in the decompiled interpolations are treated as `:` and `.`.
* Rodeo `Clock` uses `ClockMinutesOnes` where seconds-ones would be expected (copied: `01:21.456` for 01:23.456).
* Emulator: main clock = `R` when the digits change, `S` when unchanged for 1.5 s (`:` mode) / 0.15 s (`.` mode) or
  when the clock is 0; play clock (Football `PlayClock`, Basketball shot clock, Hockey shot clock) unchanged for 1.5 s -> `S`.
  Internal statuses disable the emulation; a blank result becomes `S`. `apply(c, now=)` takes a monotonic time for tests.

## Windows build vs Mac build (1.3.0.21)
| area | change in Windows build (used here) |
|---|---|
| `Sport.cs` | new serialised properties `BotNumber` (int), `TimeStampFull`, `TimeStampEpoch`, `VenueName`, `VenueId`, `VenueGeniusId` |
| `Sport.BuildScore` | new; trims leading blanks/zeros, empty -> `"0"`. Used by the computed `HomeScore`/`GuestScore`... in Football, Soccer, Basketball, BaseballSoftball (`HomeRuns`/`GuestRuns`), HockeyLacrosse, Volleyball, WaterPolo, FutsalHandball, Wrestling (4 more). Mac concatenated raw digits. sbdata inserts still use the raw `{tens}{ones}` text |
| `BuildTenthOfSecondClock` | now drops a leading blank/zero tens digit and trims (`05.3` -> `5.3`); Mac gave `05.3` |
| `SportConstants` | extra `c` constant |
| `OriginType` | extra `LocalEmulated` (5, "Local emulated") |
| EventType, HexDateTime12, ClockStatusEmulator, CoverageWeights | unchanged |

Timestamps in the Windows build: `TimeStamp` = first 12 hex digits of the UTC .NET ticks, `TimeStampFull` = .NET `"O"`
(`2023-11-14T22:13:20.2500000Z`, 7 fractional digits), `TimeStampEpoch` = Unix **milliseconds** as a string.

## `flat()`
Every base and sport property in snake_case (`HomeScoreTens` -> `home_score_tens`, `TOTimer` -> `to_timer`); blank
characters become `""`, strings are trimmed, bools stay bool. Aliases override same-named snake fields:
`sport, clock, clock_running (ClockStatus == 'R'), home_name, guest_name, period, period_ordinal, home_score,
guest_score (blank -> "0"), home_timeouts, guest_timeouts, home_poss, guest_poss, possession`, plus:

| contract | aliases |
|---|---|
| Football | `play_clock, down ("3rd"), to_go, ball_on, down_distance, horn` |
| Soccer | `home_shots, home_corners, home_saves, home_penalties, horn` (and guest) |
| Basketball | `shot_clock, home_fouls, home_bonus, home_double_bonus, timeout_clock, horn` |
| BaseballSoftball | `inning, inning_ordinal, inning_half, balls, strikes, outs, home_hits, home_errors, on_first/second/third, at_bat, pitch_*`, scores = runs |
| HockeyLacrosse | `home_shots (on goal), home_saves, shot_clock, home_penalties (count), horn` |
| Volleyball | `set, set_ordinal, game, home_sets/home_games (games won), home_serve`, serve also sets `home_poss` |
| Wrestling | `home_match_score, weight_class, advantage_time, advantage_home, horn` |
| WaterPolo / Futsal | `shot_clock, timeout_clock, home_fouls, home_penalties, horn` |
| Tennis / TableTennis | `set, home_score` (= top / home points), `home_serve`, `home_sets`; tennis `home_name` = top player |
| Generic | `clock` from `ClockDigit1-4`, `play_clock, timeout_timer` |

## Differences from `sportzcast_mqtt.build_payloads()` (not edited)
Football and Soccer sbdata are **identical** for the tested game states (see `tests/test_sb_contracts.py`). JSON
differences for the same state:

1. `ClockTenthsSecond`: build_payloads emits `"0"` in `:` mode; ScoreConnect leaves it `" "` unless the board sends it.
2. `FullClock`: build_payloads keeps the blank minute tens (`" 4:32.0"`); ScoreConnect `BuildFullClock` drops it (`"4:32.0"`).
3. `TimeStampFull`: build_payloads has 3 fractional digits (`.250Z`); .NET `"O"` has 7 (`.2500000Z`).
4. `TimeStampEpoch`: build_payloads uses seconds; the Windows build uses milliseconds.
5. `WeightedCoverage`: build_payloads always 1.0; computed here (Football 0.95 in the test, Soccer 0.82).
6. Football JSON has an extra `Possession` ("H"/"V") that no contract defines; not emitted here. If OSE reads it, keep it in the caller.
7. `ClockStatus` comes from `InternalClockStatus` (or the emulator) instead of `clock_running`; `PlayClockStatus` likewise (build_payloads: `" "`).
8. Key order: build_payloads puts `ClockMode` before `VendorSportId`; this module follows `Sport.cs`.
9. Unset strings (`HomeSaves`, yards ...) are `""` in both; real ScoreConnect would send `null` for never-assigned strings (unverified).
10. Scores with leading zeros differ from the old `_norm_score` only in the 3-digit/odd cases; both give `"0"` for blank.

## Open questions
* Json.NET member order for inherited classes; whether unset strings serialise as `null`.
* Whether `{58}`/`{46}` in the decompiled Tennis/Rodeo/Swimming/Timer clocks really print `:`/`.` (assumed) rather than "58"/"46".
* `Venue*` come from app settings in ScoreConnect; here from optional meta keys (default `""`/0).
* Generic's `clock`/`clock_running` aliases are guesses (digit layout and `ClockRun` meaning unverified).
* `Football.Possession` (see above) and whether OSE needs it.
