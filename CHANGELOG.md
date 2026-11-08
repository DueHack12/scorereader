# Changelog

## Unreleased
- **Every ScoreConnect scoreboard brand:** about 300 brand/sport layouts across 50 brands, in the new `scoreboards/` package, picked in Settings or with `--scoreboard ID`. The ScoreBot is configured for the chosen brand and wiring automatically, and MQTT payloads come from the Sportzcast contract. These are untested on real boards; Daktronics All Sport 5000 stays the default with the original decoders.
- **Settings panel** in the dashboard: data source (including demo and replay), scoreboard brand, team names, abbreviations and colors, vMix, MQTT, files and ports. Source changes apply live.
- **Mac, Linux and Raspberry Pi:** launchers, an installer (packages, udev rule, optional systemd service) and CI builds for macOS arm64, Linux x64 and Linux arm64.
- **Fixed:** command-line options (`--demo`, `--replay`, `--no-mqtt` …) were written into `scorereader_config.json` when the sport was changed from the dashboard. Demo and replay are now never saved.
- **Fixed:** team names were missing from data.json and vMix in current-loop mode.
- **Changed:** remembering the board state across restarts is now optional and off by default.
- **Fixed:** changing a setting could change the built-in defaults (shared nested dicts in `deep_merge`).

## 1.0.0 — 2026-11-07
First release. It replaced ScoreConnect III 1.5.0.1 after that update broke the ScoreBot, and has since been used for football and soccer at Rafferty Stadium.

- **ScoreLinkII/ScoreBot support:**
  - Talks to the bot directly over USB (MCP2221): switches GP2 between command and data mode, and probes or configures the PIC.
  - On Windows, uses the system's built-in HID DLLs, so `hidapi` isn't needed.
- **Daktronics current-loop decoder:**
  - Football (code 6601), with clock, play clock, score, quarter, possession, timeouts, down, to-go and ball-on.
  - Soccer (code 7601), with clock, score, half, shots and corners.
  - Picks the sport from the console code automatically.
- **Daktronics RTD decoder** for every sport in the RTD manual.
- **vMix output:** a JSON/XML/CSV Data Source, plus direct TCP `SetText` push.
- **ScoreConnect-compatible MQTT broker** (1883 + WebSocket 8083) publishing `bot/N/json`, `sbdata` and `raw`, for OSE.
- **Derived fields:** `down_distance` ("1st & 10") and `possession` (H/V/blank).
- **`custom_fields`** to remap any value to a different address and byte.
- **Live dashboard** with an address/byte inspector.
- **Debugging tools:** raw capture logging, `--replay`, `--sniff`, `--demo`.
