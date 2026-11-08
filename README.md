# ScoreReader

**A free replacement for Sportzcast ScoreConnect III.** Plug in your Sportzcast ScoreBot, and ScoreReader sends the live scoreboard (clock, score, period and more) to vMix, OSE, or anything else that can read a web address.

- Works with the scoreboard brands ScoreConnect supports, including Daktronics, Nevco, Fair-Play, Electro-Mech and OES.
- Runs on Windows, Mac, Linux and Raspberry Pi.
- Built for Fairfield Prep broadcasts at Rafferty Stadium after a ScoreConnect update broke the night before a game.

```
Scoreboard console ──▶ ScoreBot (USB) ──▶ ScoreReader ──▶ vMix · OSE · web dashboard
```

## Get started

**1. Get ScoreReader.** Download the version for your computer from [Releases](../../releases):

| Computer | What to do |
|---|---|
| **Windows** | Download `ScoreReader-windows-x64.exe` and double-click it. |
| **Mac** (Apple silicon) | Download `ScoreReader-macos-arm64.tar.gz`, open it, then right-click `ScoreReader` and choose **Open** (needed the first time, because the app isn't signed). |
| **Linux or Raspberry Pi** | Download the source (**Code → Download ZIP**), then run `./linux/install.sh` once and `./linux/start.sh` to start. `./linux/install.sh --service` makes it start automatically at boot. |

<details><summary>Other ways to run it</summary>

- **Windows from source:** install Python 3 (tick "Add to PATH"), then use the scripts in the `windows\` folder.
- **Mac from source:** install Python 3 from python.org, then double-click `mac/Start ScoreReader.command`.
- **Linux/Pi ready-made app:** `ScoreReader-linux-x64` and `ScoreReader-linux-arm64` (Pi 4/5 on 64-bit Raspberry Pi OS) are also on Releases. Run `./linux/install.sh` from the source once anyway, for the USB permissions.
</details>

**2. Close ScoreConnect III.** It holds the ScoreBot's port. On Windows, run `windows\Stop ScoreConnect service (run as admin).bat` as administrator, or set the **ScoreConnectIII** service to *Disabled*.

**3. Plug in the ScoreBot, turn on the console, and start ScoreReader.** Open **http://localhost:8765/** to see the dashboard.

**4. Pick your scoreboard.** Click **Settings → Scoreboard**. For a Daktronics All Sport 5000, leave it on **Daktronics All Sport 5000 (built-in, automatic)**; it detects football or soccer by itself. For any other board, choose the brand and sport. Enter your team names under **Settings → Teams**.

> **Tip:** the console only sends a value when it changes, so bump each score and the period once before the game.

No scoreboard handy? Choose **Settings → Source → Demo** (or run with `--demo`) for a pretend football game, which is handy for building graphics. Demo mode is never saved, so ScoreReader always starts with live data.

## Connect your graphics

**vMix:** in vMix, go to *Settings → Data Sources → Add → JSON*, enter `http://localhost:8765/data.json` and set the shortest refresh time. For an even faster clock, turn on **Settings → vMix → Push values to vMix**.

**OSE and other ScoreConnect clients:** point them at this computer's address, port **1883** (or `ws://<this-computer>:8083/mqtt`), and set **Settings → MQTT → Bot number** to the bot number they expect. They receive the same data as from ScoreConnect.

Field names such as `clock`, `home_score`, `period` and `down_distance` are listed on the dashboard and in the [reference](docs/REFERENCE.md#data-fields).

## If something's wrong

| Problem | Try this |
|---|---|
| "Access is denied" or "port busy" | ScoreConnect or its service is still running. Stop it (step 2). |
| Connected, but nothing changes | Is the console on? Bump a score. Then click **Re-init bot** in the dashboard. |
| Linux: "Permission denied" | Run `./linux/install.sh`, then unplug and replug the ScoreBot. |
| A value is wrong or missing | See [fixing a value that reads wrong](docs/REFERENCE.md#fixing-a-value-that-reads-wrong-custom_fields). |
| Still stuck | Send the newest `logs/raw_*.bin` file with a description of the problem. |

The non-Daktronics brands haven't been tested on a real board yet. If yours reads wrong, the `logs/raw_*.bin` capture is what we need to fix it.

## More information

- **[Reference](docs/REFERENCE.md):** every setting, data field, MQTT detail and command-line option.
- **[How the data is decoded](docs/PROTOCOL.md):** Daktronics and the ScoreBot, plus [every other brand](docs/vendors/).
- **[Contributor notes](CLAUDE.md)** and the [changelog](CHANGELOG.md).

## Credits

- **Daktronics RTD field table:** derived from the MIT-licensed [daktronics-allsport-5000-rs](https://crates.io/crates/daktronics-allsport-5000) project (see [NOTICE](NOTICE)).
- **Other brands:** worked out from the ScoreConnect III software the owner already has, so that it can work with equipment the owner already has. No vendor code or files are included.
- **No affiliation:** ScoreReader isn't affiliated with or endorsed by Sportzcast, Genius Sports or Daktronics. Product names are trademarks of their owners.

MIT License © 2026 Jack Singewald
