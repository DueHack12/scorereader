# CLAUDE.md: working on ScoreReader

Context for Claude Code (or any contributor) picking up this project.

## What this is
ScoreReader replaces Sportzcast **ScoreConnect III** for a high-school broadcast crew (Fairfield Prep Media, Rafferty Stadium). It reads a **Sportzcast ScoreLinkII/ScoreBot** over USB, decodes a **Daktronics All Sport 5000** console (plus every other brand ScoreConnect supports, via `scoreboards/`), and publishes the data to vMix (HTTP JSON/XML/CSV or TCP `SetText`) and to OSE through a **ScoreConnect-compatible MQTT broker**.

**Windows is the main platform; macOS, Linux and Raspberry Pi are supported too.** It's used live on game days, so reliability beats features. Never break a working sport layout while adding another.

## Layout
| File | Role |
|---|---|
| `scorereader.py` | Everything except MQTT: config, serial/HID (`MCP2221`, `WinHID`), PIC commands, sources (`Reader`: scorelink, serial, tcp, demo, replay), decoders (`DaktronicsRTD`, `DaktronicsCurrentLoop`, `SportMap`), outputs (`VmixPusher`, text files), HTTP server and dashboard (`App`, `DASHBOARD_HTML`), CLI |
| `sportzcast_mqtt.py` | `build_payloads()` (Sportzcast JSON plus 150-char sbdata, football and soccer), `MiniBroker` (dependency-free MQTT 3.1/3.1.1/5 broker with WebSocket support), `MqttPublisherClient`, `SportzcastMqttOutput` glue |
| `scoreboards/` | Multi-vendor decoders: `base.py` (Protocol/Decoder framework), `common.py` (digit/BCD/checksum helpers), `pic55aa.py` (PIC decode-mode framing), one module per brand, `contracts.py` (contract → output fields, Sportzcast JSON, sbdata, clock-status emulation), `hardware.py` (bot set-up per wiring option), `catalog.json` (brands, sports, wiring from ScoreConnect's config DB). Per-brand wire docs in `docs/vendors/`. |
| `linux/`, `mac/` | `install.sh` (packages, udev rule, hid_mcp2221 blacklist, optional systemd service), launchers |
| `daktronics_fields.json` | RTD field positions for every Daktronics sport (1-based), loaded by `SportMap` |
| `README.md` / `docs/REFERENCE.md` | README is the short operator guide (get started, connect graphics, troubleshooting); every detail (settings, fields, MQTT, CLI, custom_fields) goes in REFERENCE.md |
| `docs/PROTOCOL.md` | Wire formats: ScoreLinkII/MCP2221/PIC, current loop, RTD, MQTT/sbdata. **Read this before touching decoders.** |
| `tests/` | pytest. `conftest.make_cl_frame()` builds current-loop frames. `test_current_loop.py` contains real captured soccer bytes. |
| `windows/` | `.bat` launchers for non-technical operators, plus `build_exe.bat` |
| `.github/workflows/ci.yml` | tests on Windows and Linux, PyInstaller exe artifact, release on `v*` tag |

## Data flow
`Reader` thread → `_feed(bytes)` → `DaktronicsCurrentLoop.feed` (once more than 20 current-loop packets have arrived, RTD decoding is skipped) and `DaktronicsRTD.feed` → `App.update_loop` polls the decoders' `version` → builds a flat dict `d` → vMix push, MQTT `update`, text files → HTTP serves `App.current()`.

- **Output keys** are snake_case (`home_score`, `down_distance`, `possession`, …). Booleans become `"1"`/`"0"` in JSON/XML/CSV.
- **The current-loop sport** is chosen from the console code at address `0xFE` (`CODE_SPORT`: 6601 = football, 7601 = soccer). For any other code, the configured sport is used.
- **`custom_fields`** in the config override or add fields after decoding (`DaktronicsCurrentLoop._custom`).
- **Other brands:** when `scoreboard.protocol` is set (a ScoreConnect vendor-sport id), `App._new_decoders` creates `scoreboards.create(id)`, `Reader._feed` sends bytes only there, and `App.build_data` uses `contract_to_data()` → `contracts.flat()`. MQTT uses `contracts.sportzcast_json/sbdata`. `App.bot_plan()` gives the PIC commands/baud for the brand's wiring; they're sent once per brand/wiring (`scorelink.configured_for`). Blank protocol = the original Daktronics path, untouched.
- **Config:** `App.cfg` is the running config (file + CLI options); `App.saved` is what's on disk. `apply_settings()` validates against `SETTINGS`, writes only `saved`, never persists demo/replay, and restarts the reader or vMix when needed.

## Conventions and gotchas
- **Dependencies:** keep runtime deps to `pyserial` only (`hidapi` only on macOS/Linux). `hidapi` fails to build on new Python versions on Windows, which is why `WinHID` uses ctypes. Keep `scorereader.py` importable without `hid`.
- **ScoreConnect compatibility:** MQTT payload names and positions must stay byte-compatible with ScoreConnect III, because OSE consumes them. Check `docs/PROTOCOL.md §4` before renaming anything.
- **Board quirk:** Rafferty Stadium's soccer board sends zeros for corners on address 13 (where ScoreConnect reads them), so corners come from the address 72 stats panel. Don't "fix" this back.
- **The console only transmits on change.** With `save_state` on (off by default), `scorereader_state.bin` keeps the last RTD buffer between runs.
- **Vendor decoders are unverified on hardware.** They follow ScoreConnect's tables (Windows build preferred over the older Mac build), quirks included; each `docs/vendors/*.md` lists them. Fix them only against a real capture. `Protocol.snapshot()` is the pure decoded contract; `full_contract()` adds the emulated clock status.
- **Never edit a user's `scorereader_config.json` in the repo.** It's gitignored and auto-created from `DEFAULT_CONFIG`, and `deep_merge` adds new keys to old configs.
- **Unverifiable code:** the Windows HID path (`WinHID`) can't be tested in CI without hardware. Be careful there, and keep the "no GPIO → still read data" fallback.
- **Adding a sport:** to add a sport on the current loop, decode a capture first (`--replay`, the dashboard address table), add `_apply_<sport>` plus a `data()` branch, add `CODE_SPORT` and MQTT payload branches, and write a test with real bytes.

## Commands
```bash
python -m pytest -q                       # run before every commit
python -m pyflakes scorereader.py sportzcast_mqtt.py scoreboards
python scorereader.py --demo              # dashboard on :8765, MQTT on :1883/:8083
python scorereader.py --replay logs/raw_X.bin --no-mqtt
python scorereader.py --list-scoreboards  # every brand/sport id
```

## Ideas / backlog
- Verify the vendor decoders against real captures, one board at a time.
- Network ScoreBots (BOTDiscovery/BOTClient, UDP/TCP) and radio set-up (Laird/Digi/SiLabs): `hardware.py` documents them, but ScoreReader only drives the USB ScoreLinkII.
- Optional Windows service / tray mode for auto-start.
- The PyInstaller exe is unsigned, so SmartScreen warns about it; consider code signing.
