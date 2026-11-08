# ScoreReader reference

The details behind the [README](../README.md): outputs, settings, the command line and how to fix a value that reads wrong.

## Contents
- [vMix](#vmix)
- [MQTT (OSE and ScoreConnect clients)](#mqtt-ose-and-scoreconnect-clients)
- [Data fields](#data-fields)
- [Scoreboard brands](#scoreboard-brands)
- [Fixing a value that reads wrong (`custom_fields`)](#fixing-a-value-that-reads-wrong-custom_fields)
- [Mac, Linux and Raspberry Pi details](#mac-linux-and-raspberry-pi-details)
- [Command line](#command-line)
- [Settings file](#settings-file)
- [Development](#development)

## vMix

**Data Source (easiest):** in vMix, go to *Settings → Data Sources → Add → JSON*, enter `http://localhost:8765/data.json`, and set the shortest refresh interval. XML is also served at `/data.xml` and CSV at `/data.csv`.

**Direct push (fastest clock):** turn on **Settings → vMix → Push values to vMix** and enter the title input's name. To choose which title fields get which values, edit `vmix.fields` in `scorereader_config.json`:

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

- A plain string uses `SetText`.
- `{"visible": true}` shows or hides a layer: `SetImageVisibleOn`/`Off` for `.Source` layers, `SetTextVisibleOn`/`Off` for `.Text` layers.
- `true`/`false` turns an on/off value into text.

Only changed values are sent.

## MQTT (OSE and ScoreConnect clients)

ScoreReader runs its own MQTT broker that looks like ScoreConnect III's, so OSE and other ScoreConnect clients keep working.

| | |
|---|---|
| MQTT | `<pc-ip>:1883` |
| WebSocket | `ws://<pc-ip>:8083/mqtt` |
| Topics | `bot/<N>/json` (Sportzcast JSON), `bot/<N>/sbdata` (150-character string), `bot/<N>/raw` |
| Login / QoS | none / 0, same as ScoreConnect |

- **Bot number:** set it in **Settings → MQTT** (or `--mqtt-bot N`) to the number your client subscribes to.
- **Team names:** come from **Settings → Teams**. Older configs' `mqtt.home_team_name`/`guest_team_name` still work as a fallback.
- **Updates:** values are published on every change and at least once a second, and a new subscriber gets the latest values straight away.
- **Existing broker:** set mode to `client` and enter the broker's host to publish into Mosquitto or similar instead.

## Data fields

Everything is served at `/data.json`, and the dashboard lists every field with its current value. On/off values are `1`/`0`.

**Football**

| field | example |
|---|---|
| `clock`, `clock_running` | `4:32` or `59.8`, `1`/`0` |
| `play_clock` | `25` |
| `home_score`, `guest_score` | `14` |
| `period`, `period_ordinal` | `2`, `2nd` |
| `down_distance` | `3rd & 7` |
| `down`, `to_go`, `ball_on` | `3rd`, `7`, `35` |
| `home_timeouts`, `guest_timeouts` | `3` |
| `possession` | `H`, `V` or blank |
| `home_poss`, `guest_poss` | `1`/`0` |

**Soccer:** `clock`, `clock_running`, `home_score`, `guest_score`, `period`, `period_ordinal`, `home_shots`, `guest_shots`, `home_corners`, `guest_corners`, `horn`.

**Every sport** also has `home_name`, `guest_name`, `home_abbr`, `guest_abbr`, `home_color` and `guest_color` from Settings → Teams.

**Other sports and brands** add their own fields (for example `shot_clock`, `home_fouls`, `balls`, `strikes`, `outs`), plus every field of the Sportzcast contract in snake_case. Daktronics RTD (the console's J6 port) also exposes every field in the Daktronics RTD manual.

## Scoreboard brands

ScoreReader can decode about 300 brand/sport layouts, which covers everything ScoreConnect III supports. Pick one in **Settings → Scoreboard**: the brand, then the sport or console layout, then the wiring if the brand has more than one. You can also start with `--scoreboard ID`; `--list-scoreboards` prints every ID.

- **Daktronics All Sport 5000 (built-in)** is the default. It detects football or soccer from the console by itself and handles known board quirks (such as soccer corners on the stats panel).
- **Bot setup:** when you choose another brand, ScoreReader sets up the ScoreBot for it the first time it connects, using the same commands and speed ScoreConnect uses, and remembers that. **Re-init bot** sends the setup again.
- **Not yet tested on real boards:** the other brands were written from ScoreConnect's decoder tables and tested with made-up data. If something reads wrong, send a capture (`logs/raw_*.bin`) along with the brand and sport. Each brand's wire format is in [vendors/](vendors/).

## Fixing a value that reads wrong (`custom_fields`)

Daktronics current-loop boards can be wired differently. To point a field at the right place:

1. Change the value on the console.
2. In the dashboard's address table, note which row (address) and which byte changed. The hex column counts from byte 0.
3. Add an entry like this to `scorereader_config.json`:

```json
"custom_fields": {
  "home_corners":  {"addr": 72, "bytes": [0, 1]},
  "guest_corners": {"addr": 72, "bytes": [10, 11]}
}
```

## Mac, Linux and Raspberry Pi details

- **Serial port:** the bot shows up as `/dev/cu.usbmodem…` on a Mac and as `/dev/ttyACM0` or `/dev/scorebot` on Linux. Port `auto` finds it.
- **What `linux/install.sh` does:**
  - Installs `python3-serial` and `python3-hid`.
  - Adds a udev rule, so ScoreReader can reach the bot without root. The rule also creates `/dev/scorebot` and keeps ModemManager off the port.
  - Stops the kernel's `hid_mcp2221` driver from taking the bot's mode-switch line.
- **Start at boot:** `./linux/install.sh --service` installs a systemd service named `scorereader`. Check it with `systemctl status scorereader`, and follow its log with `journalctl -u scorereader -f`.
- **Raspberry Pi:** use 64-bit Raspberry Pi OS on a Pi 4 or 5 for the ready-made `ScoreReader-linux-arm64` build. Any Pi with Python 3 can run from source.

## Command line

```
scorereader.py [--port COM5] [--baud 19200] [--sport soccer] [--source scorelink|serial|tcp|demo|replay]
               [--scoreboard ID] [--list-scoreboards]
               [--vmix] [--vmix-input NAME] [--http-port 8765] [--mqtt-bot N] [--no-mqtt]
               [--list-ports] [--probe] [--configure-bot] [--sniff [SECONDS]] [--replay FILE]
               [--fresh] [--demo] [--version]
```

| Option | Use |
|---|---|
| `--demo` | a simulated football game, for building graphics without a console |
| `--list-ports` | serial ports, with the ScoreBot tagged |
| `--probe` | ask the bot for its firmware and settings, then leave it ready to read data |
| `--configure-bot` | re-send the Daktronics football bot setup (`M0X0X T0 D0 M8I1N`) |
| `--sniff 20` | show the raw bytes for 20 seconds |
| `--replay logs/raw_….bin` | play back a capture |
| `--list-scoreboards` | every supported brand/sport ID |
| `--scoreboard ID` | use that brand/sport for this session only (Settings saves it) |
| `--source serial` | no bot: a plain USB-serial adapter on the console's J6 RTD port |
| `--fresh` | forget remembered board values (only used with "Remember board values" on) |

Command-line options apply to that session only and are never saved.

## Settings file

Settings are stored in `scorereader_config.json` next to the program, which is created on first run. The Settings panel edits it for you; demo and replay are never saved, so ScoreReader always starts on live data. Raw bytes are logged to `logs/raw_*.bin` unless you turn that off.

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python scorereader.py --demo        # dashboard at http://localhost:8765
```

- **Code layout and contributor notes:** [CLAUDE.md](../CLAUDE.md).
- **Wire formats:** [PROTOCOL.md](PROTOCOL.md) for Daktronics and the ScoreBot, and [vendors/](vendors/) for every other brand.
- **CI:** runs the tests on Windows, macOS and Linux and builds one-file apps for Windows, macOS (Apple silicon), Linux and Raspberry Pi. Pushing a `v*` tag publishes a release with all four attached.
