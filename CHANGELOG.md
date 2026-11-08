# Changelog

## 2.1.0 — 2026-11-08
- **Mac app:** the Mac download is now `ScoreReader-macos-arm64.dmg` with `ScoreReader.app` (drag it to Applications). It runs in the menu bar and Dock with its own name and logo, without a Terminal window, and opens the dashboard when it starts. Its settings and logs are in `~/Library/Application Support/ScoreReader`.
- **Logo:** a new ScoreReader icon (a seven-segment S with a signal), used for the Windows app, the Mac Dock and menu bar, and the dashboard's browser tab.
- **Windows:** `ScoreReader.exe` shows the logo, and its window is titled "ScoreReader <version>", so the taskbar shows the name and logo.
- **Mac menu bar:** live status and score, Open dashboard, Re-init bot, Demo mode, Open logs folder and Quit. Closing the Terminal window keeps ScoreReader running in the menu bar (the log goes on in `logs/scorereader.log`). The app menu has **Quit ScoreReader** (⌘Q). `--no-menubar` turns the icon off.

## 2.0.0 — 2026-11-08
- **Every ScoreConnect scoreboard brand:** about 300 brand/sport layouts across 50 brands, in the new `scoreboards/` package, picked in Settings or with `--scoreboard ID`. The ScoreBot is configured for the chosen brand and wiring automatically, and MQTT payloads come from the Sportzcast contract. These are untested on real boards; Daktronics All Sport 5000 stays the default with the original decoders.
- **Settings panel** in the dashboard: data source (including demo and replay), scoreboard brand, team names, abbreviations and colors, vMix, MQTT, files and ports. Source changes apply live.
- **Mac, Linux and Raspberry Pi:** launchers, an installer (packages, udev rule, optional systemd service) and CI builds for macOS arm64, Linux x64 and Linux arm64.
- **Fixed:** command-line options (`--demo`, `--replay`, `--no-mqtt` …) were written into `scorereader_config.json` when the sport was changed from the dashboard. Demo and replay are now never saved.
- **Fixed:** team names were missing from data.json and vMix in current-loop mode.
- **Changed:** remembering the board state across restarts is now optional and off by default.
- **Fixed:** changing a setting could change the built-in defaults (shared nested dicts in `deep_merge`).
- **Daktronics console sports:** console codes other than football (6601) and soccer (7601), such as basketball, baseball, hockey, volleyball and wrestling, now switch automatically to ScoreConnect's layout for that sport instead of being read as football.
- **Fixed:** on the built-in RTD path, MQTT sent a football-shaped message for every sport; basketball, baseball, softball, hockey, lacrosse and volleyball now send their own.
- **Fixed:** switching back to the built-in Daktronics decoders after using another brand now restores the Daktronics ScoreBot setup.
- **Docs:** shorter README for operators; full details moved to `docs/REFERENCE.md`, and per-brand wire formats are in `docs/vendors/`.

## 1.0.0 — 2026-11-07
First release. It replaced ScoreConnect III 1.5.0.1 after that update broke the ScoreBot, and has since been used live for football and soccer.

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
