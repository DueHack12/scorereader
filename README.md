# ScoreReader

**ScoreReader is an open-source replacement for Sportzcast ScoreConnect III.** It reads live scoreboard data straight from a Sportzcast **ScoreBot / ScoreLinkII** over USB, decodes **every scoreboard brand ScoreConnect supports** (Daktronics, Nevco, Fair-Play, Electro-Mech, OES, Varsity, Eversan, All American, Spectrum and about 40 more), and serves the data to vMix, OSE, and anything else that speaks HTTP or MQTT. It runs on **Windows, macOS, Linux and Raspberry Pi**.

It was built in one evening after a ScoreConnect III update (1.5.0.1) stopped working the night before a game. It has since been used for Fairfield Prep football and soccer broadcasts at Rafferty Stadium.

```
All Sport 5000 ──current loop──▶ ScoreLinkII (USB) ──▶ ScoreReader ──┬─▶ vMix Data Source (JSON/XML/CSV)
                                                                     ├─▶ vMix TCP API (SetText push)
                                                                     ├─▶ MQTT, ScoreConnect-compatible (OSE …)
                                                                     └─▶ Web dashboard / text files
```

## Features

- **Reads the ScoreLinkII bot directly**, so ScoreConnect isn't needed. ScoreReader switches the bot's MCP2221 between command and data mode, and can query and reconfigure the bot's PIC.
- **About 300 brand/sport layouts** (Settings → Scoreboard), with the ScoreBot configured automatically for the chosen brand and wiring. See [Scoreboard brands](#scoreboard-brands).
- **Built-in Daktronics All Sport 5000 decoders** (the default), which detect what's arriving:
  - **Current-loop** scoreboard-driver data (7-segment frames): football (code 6601) and soccer (code 7601).
  - **RTD** text data from the J6 port: every sport in the Daktronics RTD manual.
- **vMix:** a JSON/XML/CSV Data Source, or direct `SetText` push over the TCP API that only sends changed values.
- **MQTT:** a built-in broker on ports 1883 and 8083 (WebSocket) that mirrors ScoreConnect III's local topics `bot/{N}/json`, `sbdata` and `raw`, so existing integrations such as OSE keep working.
- **Live dashboard** showing the decoded values, the raw address/byte table, logs and connection status, plus a **Settings** panel (data source, scoreboard brand, team names and colors, vMix, MQTT, files). Demo and replay are never saved, so ScoreReader always starts on live data, and a banner shows while they run.
- **`custom_fields`** let you remap any value to a different address and byte when your board is wired differently.
- **Raw capture logging and replay** (`--replay`) for debugging away from the stadium.
- **Pure Python with a single runtime dependency** (`pyserial`). On Windows it talks to the USB HID chip through Windows' built-in DLLs, so no compiler is needed.

## Quick start (Windows)

1. Download **`ScoreReader.exe`** from [Releases](../../releases) (or the latest CI run's artifacts). Alternatively, install Python 3, tick "Add to PATH", and use the scripts in `windows\`.
2. **Stop ScoreConnect III.** Its Windows service holds the COM port. Run `windows\Stop ScoreConnect service (run as admin).bat` as administrator, or set the **ScoreConnectIII** service's Startup type to *Disabled*.
3. Plug in the ScoreBot and turn the console on.
4. **Probe the bot:** run `ScoreReader.exe --probe`, or `windows\2 - Check Bot (probe).bat`. You should see:
   ```
   COM5   04D8:00DD  USB Serial Device  <-- ScoreLinkII / MCP2221
   PIC R?   -> R1.14
   PIC M8?  -> M8I1N
   GP2 after:  value=1 (DATA mode)
   ```
5. **Run it:** run `ScoreReader.exe` or `windows\1 - Start ScoreReader.bat`, then open **http://localhost:8765/**.

> The console only sends a value when it changes, so bump each score and period once at the start. To keep the last RTD values across a restart, turn on **Remember board values after a restart** in Settings (off by default; `--fresh` clears it).

No hardware handy? `ScoreReader.exe --demo` runs a simulated football game, so you can build graphics without a console.

## Mac, Linux and Raspberry Pi

Download the build for your system from [Releases](../../releases) (`ScoreReader-macos-arm64`, `ScoreReader-linux-x64`, or `ScoreReader-linux-arm64` for a Raspberry Pi 4/5 on 64-bit Raspberry Pi OS), or run from source:

- **Mac:** install Python 3 from python.org, then double-click `mac/Start ScoreReader.command`. The first run sets up its packages, then the dashboard opens.
- **Linux / Raspberry Pi:**
  ```bash
  ./linux/install.sh            # packages + USB permissions for the ScoreBot (asks for sudo)
  ./linux/start.sh              # then open http://<this-machine>:8765/
  ```
  `./linux/install.sh --service` also starts ScoreReader at boot (see the logs with `journalctl -u scorereader -f`). The installer adds a udev rule (non-root access, `/dev/scorebot`, keeps ModemManager off the port) and blacklists the kernel's `hid_mcp2221` driver so ScoreReader can switch the bot's mode. Unplug and replug the bot afterwards.

The bot's serial port is `/dev/cu.usbmodem…` on a Mac and `/dev/ttyACM0` (or `/dev/scorebot`) on Linux; `port: auto` finds it.

## Scoreboard brands

Pick the brand and sport in **Settings → Scoreboard** (or start with `--scoreboard ID`; `--list-scoreboards` prints every id). Leave the brand on **Daktronics All Sport 5000 (built-in)** for the original decoders, which detect football/soccer from the console and handle the Rafferty Stadium board's quirks.

When you choose a brand, ScoreReader configures the ScoreBot for it (the same PIC commands and baud ScoreConnect uses, with read-back checks) the first time it connects, and remembers that. **Re-init bot** sends it again. Outputs keep the same field names (`clock`, `home_score`, `period`, …), plus every field of the Sportzcast contract in snake_case, and MQTT publishes the same JSON and sbdata ScoreConnect would.

> The non-Daktronics decoders were written from ScoreConnect's decoder tables and tested with synthetic data. They haven't met a real board yet. If something reads wrong, save a capture (`logs/raw_*.bin`) and open an issue with the brand and sport. Per-brand wire formats are in [docs/vendors/](docs/vendors/).

## vMix

**Data Source (easiest):** in vMix, go to *Settings → Data Sources → Add → JSON*, enter `http://localhost:8765/data.json`, and set the shortest refresh interval. XML is also served at `/data.xml` and CSV at `/data.csv`.

**Direct push (fastest clock):** in `scorereader_config.json`:
```json
"vmix": {
  "enabled": true, "host": "127.0.0.1", "port": 8099, "input": "Scorebug",
  "fields": {
    "clock": "Clock.Text",
    "home_score": "HomeScore.Text",
    "down_distance": "DownDistance.Text",
    "home_poss": {"name": "HomePoss.Text", "true": "◀", "false": ""},
    "guest_poss": {"name": "GuestArrow.Source", "visible": true}
  }
}
```
A plain string mapping uses `SetText`. `{"visible": true}` uses `SetImageVisibleOn`/`SetImageVisibleOff` for `.Source` layers, or `SetTextVisibleOn`/`SetTextVisibleOff` for `.Text` layers. `true`/`false` mappings convert a boolean into text.

## MQTT (OSE and ScoreConnect clients)

| | |
|---|---|
| MQTT | `<pc-ip>:1883` |
| WebSocket | `ws://<pc-ip>:8083/mqtt` |
| Topics | `bot/<N>/json` (Sportzcast JSON contract), `bot/<N>/sbdata` (150-char string), `bot/<N>/raw` |
| Auth / QoS | none / 0, same as ScoreConnect local |

- **Bot number:** set `mqtt.bot_number` (or `--mqtt-bot N`) to the bot number your client subscribes to.
- **Team names:** set them in **Settings → Teams** (also used in data.json and vMix). Older configs' `mqtt.home_team_name`/`guest_team_name` still work as a fallback.
- **Republishing:** values are published on every change and at least once per second, and new subscribers immediately receive the latest values.
- **External broker:** set `"mode": "client"` and `broker_host` to publish into an existing broker such as Mosquitto instead.

## Data fields

All fields are served at `/data.json`. The dashboard lists every key and where it comes from.

**Football**

| key | example |
|---|---|
| `clock`, `clock_running` | `4:32`, `59.8` · `1`/`0` |
| `play_clock` | `25` |
| `home_score`, `guest_score` | `14` |
| `period`, `period_ordinal` | `2`, `2nd` |
| `down_distance` | `3rd & 7` |
| `down`, `to_go`, `ball_on` | `3rd`, `7`, `35` |
| `home_timeouts`, `guest_timeouts` | `3` |
| `possession` | `H`, `V` or blank |
| `home_poss`, `guest_poss` | `1`/`0` |

**Soccer:** `clock`, `clock_running`, `home_score`, `guest_score`, `period`, `period_ordinal`, `home_shots`, `guest_shots`, `home_corners`, `guest_corners`, `horn`.

**RTD mode** (J6 serial) exposes every field in the Daktronics RTD manual for the selected sport, plus the friendly aliases above.

### `custom_fields`: remap without code changes

To find where a value lives on your board:

1. Change the value on the console.
2. In the dashboard's address table, note which row (address) and which byte changed. The hex column counts from byte 0.
3. Add an entry like this to `scorereader_config.json`:

```json
"custom_fields": {
  "home_corners":  {"addr": 72, "bytes": [0, 1]},
  "guest_corners": {"addr": 72, "bytes": [10, 11]}
}
```

## Command line

```
scorereader.py [--port COM5] [--baud 19200] [--sport soccer] [--source scorelink|serial|tcp|demo|replay]
               [--vmix] [--vmix-input NAME] [--http-port 8765] [--mqtt-bot N] [--no-mqtt]
               [--scoreboard ID] [--list-scoreboards]
               [--list-ports] [--probe] [--configure-bot] [--sniff [SECONDS]] [--replay FILE]
               [--fresh] [--demo] [--version]
```

| Flag | Use |
|---|---|
| `--list-ports` | serial ports, with the ScoreLinkII tagged |
| `--list-scoreboards` | every supported brand/sport id |
| `--scoreboard ID` | use that brand/sport for this session (Settings saves it permanently) |
| `--probe` | query the bot's PIC (firmware and configuration), then leave it in data mode |
| `--configure-bot` | re-send ScoreConnect's Daktronics football setup (`M0X0X T0 D0 M8I1N`) |
| `--sniff 20` | hex-dump the raw bytes for 20 seconds |
| `--replay logs\raw_….bin` | play back a capture |
| `--source serial` | no bot: a plain USB-serial adapter on the console's J6 RTD port |

Settings live in `scorereader_config.json` next to the program, which is created on first run.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Access is denied` / port busy | ScoreConnect III or its service still has the port. Stop the service. |
| Probe gets no PIC reply | Unplug the bot, wait 5 seconds, plug it back in, and probe again. Check `--list-ports` for the ScoreLinkII tag. |
| Connected but 0 bytes | Make sure the console is on, then run `--sniff`. Run `--configure-bot` once if needed. |
| Bytes arrive but 0 packets | Wrong baud: try `--baud 9600`. |
| A value is wrong or missing | Find the right address and byte in the dashboard's address table, then add a `custom_fields` entry. |
| Stale values after a restart | Use `--fresh` (only with "Remember board values" on). |
| Linux: `Permission denied` on the port or GPIO | Run `./linux/install.sh`, then unplug and replug the bot. |

Raw bytes are always logged to `logs/raw_*.bin`. Send one of those files with any bug report.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python scorereader.py --demo        # dashboard at http://localhost:8765
```

- **Architecture and contributor notes:** see [CLAUDE.md](CLAUDE.md).
- **Wire formats:** see [docs/PROTOCOL.md](docs/PROTOCOL.md).
- **CI:** runs the tests on Windows, macOS and Linux and builds one-file apps for Windows x64, macOS arm64, Linux x64 and Linux arm64 (Raspberry Pi) with PyInstaller. Pushing a tag `v*` publishes a GitHub Release with all four attached.

## Credits and disclaimer

- **Other brands:** wire formats were worked out from the ScoreConnect III software the user owns (Windows and Mac builds), for interoperability. Only facts (framing, byte positions, field names) went into ScoreReader's own Python code; no vendor code or files are included.
- **Field positions:** the Daktronics RTD field table is derived from the MIT-licensed [daktronics-allsport-5000-rs](https://crates.io/crates/daktronics-allsport-5000) project. See [NOTICE](NOTICE).
- **No affiliation:** ScoreReader isn't affiliated with or endorsed by Sportzcast, Genius Sports or Daktronics. Product names are trademarks of their owners.
- **Interoperability:** protocol details were determined by observing the hardware and its public interfaces, so that it can work with equipment its owner already has. No vendor code is included.

MIT License © 2026 Jack Singewald
