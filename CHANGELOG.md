# Changelog

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
