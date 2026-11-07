# Protocol notes

This file documents what ScoreReader has to understand on the wire. The ScoreLinkII and ScoreConnect III details come from observing the hardware and reading the public interfaces of ScoreConnect III 1.4.1.0. The goal was interoperability, so no Sportzcast code is included in this repository.

---

## 1. Sportzcast ScoreLinkII / ScoreBot (USB)

| | |
|---|---|
| USB chip | Microchip **MCP2221** USB-to-UART bridge, VID `04D8`, PID `00DD` |
| Host sees | a CDC serial port (COMx / `/dev/cu.usbmodem…`) **and** a HID interface (GPIO / config) |
| Mode select | MCP2221 **GP2**: `0` = PIC command mode, `1` = data (passthrough) mode |

### Command mode (GP2 = 0)
- Serial **57600 8N1**. Commands are ASCII, prefixed with `>` and terminated with `\r`. Replies are terminated with CR, and they echo the command letter.
- Commands seen in ScoreConnect's "Bot Configuration" log for Daktronics football:

| Command | Reply | Meaning (best understanding) |
|---|---|---|
| `>R?` | `R1.14` | PIC firmware revision |
| `>B?` | `B6` | baud setting index (6 is assumed to be 19200) |
| `>U?` | `U005B1226` | chip unique ID |
| `>M0X0X` / `>M?` | `M0X0X` | multiplexer slot 0 |
| `>T0` / `>T?` | `T0` | |
| `>D0` / `>D?` | `D0` | PIC decoding off (raw passthrough) |
| `>M8I1N` / `>M8?` | `M8I1N` | input = **current loop**, polarity **I**nverted, 8N1 |

The PIC writes its settings to EEPROM. ScoreConnect waits about 300 ms after each write.

### Data mode (GP2 = 1)
The port is reopened at the **scoreboard's baud** (19200 for Daktronics), and the raw console bytes pass straight through.

### MCP2221 HID (64-byte reports, report ID 0)
| Cmd | Use |
|---|---|
| `0x51` Get GPIO values | response `[6]` = GP2 value, `[7]` = GP2 direction (`0xEE`/`0xEF` = not GPIO) |
| `0x61` Get SRAM settings | response `[22..25]` = GP0..GP3 settings |
| `0x60` Set SRAM settings | `[7]=0x80` alter GPIO config, `[8..11]` = GP0..GP3 (bit4 value, bit3 dir 0=out, bits2:0 000=GPIO) |
| `0x50` Set GPIO output values | GP2 block `[10..13]` = alter-out (0xFF), value, alter-dir (0xFF), dir (0) |

On Windows, ScoreReader talks to the HID interface through `hid.dll`, `setupapi` and `kernel32` using ctypes. On macOS and Linux it uses `hidapi`.

---

## 2. Daktronics current loop (scoreboard driver output)

This is what the bot receives when it's wired to the console's current-loop output (`M8I1N`).

```
55 AA | addr | len | x | x | 22 | data[len-1] ... | checksum
        └────────── len + 5 bytes ────────────────────────┘
```
- The checksum is valid when `(sum(addr..checksum) + 0x55 + 0xAA) & 0xFF == 0`. The byte at index 4 is always `0x22`.
- Data bytes are **7-segment patterns**: `value & 0x7F` → `3F`=0 `06`=1 `5B`=2 `4F`=3 `66`=4 `6D`=5 `7D`=6 `07`=7 `7F`=8 `6F`/`67`=9 `00`=blank. Bit 7 is a decimal point or colon.
- Addresses `0xE0` and up carry LED-matrix bitmaps (team names drawn as pixels) and are ignored.
- Address `0xFE` carries the **console code** as ASCII, e.g. `66015000430` → code `6601`.

Byte indices below are into the frame after `55 AA` (`p[0]` = addr, so `p[5]` = first data byte). Address 1 is the same in both sports:

- `p[5..8]`: clock digits. In `:` mode they're MM:SS; in `.` mode (under a minute) they're SS.t.
- `p[8]`: `0` means `.` mode, any other value means `:` mode.
- `p[9..10]`: play clock.
- `p[11] & 0x40`: clock stopped.

### Football, code 6601 (ScoreConnect "Daktronics Main FootballDecoder")
| addr | bytes |
|---|---|
| 15 | `p[5..8]` clock · `p[11..12]` home score · `p[13..14]` guest score · `p[15]` quarter · `p[17]` possession (`0x07` home, `0x38` guest) · `p[18]`/`p[19]` home/guest time-outs |
| 16 | `p[5..6]` ball on · `p[7]` down · `p[8..9]` to go |

### Soccer, code 7601 (ScoreConnect "SoccerDecoder" plus a board-specific stats panel)
| addr | bytes |
|---|---|
| 11 | `p[5..8]` clock · `p[15..16]` home score · `p[17..18]` guest score · `p[19]` half |
| 12 | `p[13]&0x80` horn · `p[15..16]` home shots · `p[17..18]` guest shots |
| 13 | ScoreConnect reads corners from `p[15..16]` / `p[17..18]`. **Rafferty Stadium's board sends zeros here**, so ScoreReader ignores it while address 72 is active. |
| 72 | stats panel: `p[5..6]` home CKICKS · `p[8..9]` home SOG · `p[15..16]` guest CKICKS · `p[18..19]` guest SOG |

You can remap any field without changing code using the `custom_fields` setting in `scorereader_config.json` (see README).

---

## 3. Daktronics RTD (J6 serial / "Enhanced RTD")

```
16 (SYN) … 01 (SOH) "004210" + offset(4) 02 (STX) text… 04 (EOT) checksum 17 (ETB)
```
Each packet writes `text` into a roughly 1 KB buffer at `offset`, which is zero-based. Field positions in `daktronics_fields.json` are one-based, following the Daktronics All Sport 5000 Enhanced RTD manual (ED-12483). The table was converted from the MIT-licensed [daktronics-allsport-5000-rs](https://crates.io/crates/daktronics-allsport-5000) project.

---

## 4. ScoreConnect III-compatible MQTT

| | |
|---|---|
| Broker | TCP `1883`, WebSocket `8083` path `/mqtt`, no auth, QoS 0 |
| Topics | `bot/{botNumber}/json`, `bot/{botNumber}/sbdata`, `bot/{botNumber}/raw` |

### `json`: Sportzcast contract
- **Sport base fields:** `OriginTypeId`, `OriginType`, the `Clock*` digit fields, `ClockMode`, `Clock`, `FullClock`, `EventId` (football 2, soccer 8), `ClockStatus` (`R`/`S`), `BotNumber`, `BotNumberHex` (X6), `TimeStamp` (.NET ticks in hex, first 12 characters), `TimeStampFull` (ISO UTC), `TimeStampEpoch`, `HomeTeamName`, `GuestTeamName`, …
- **Football fields:** `PlayClock`, `HomeScore`, `GuestScore`, `Quarter`, `QuarterOrdinal`, `Down`, `ToGo`, `BallOn`, `HomePossession` (`<`), `GuestPossession` (`>`), `HomeTimeouts`, …
- **Soccer fields:** `HomeShots`, `HomeCornerKicks`, `Period`, `PeriodOrdinal`, `Horn`, …

### `sbdata`: 150-character fixed-width string (zero-based positions)
| pos | football (`02`) | soccer (`08`) |
|---|---|---|
| 0–1 | event `02` | event `08` |
| 2–5 | clock digits (MMSS, or SSt␠ in tenths mode) | same |
| 8–9 | play clock | |
| 11–12 / 14–15 | home / guest score | home / guest score |
| 13 / 16 | | home / guest possession |
| 16 / 17 | home `<` / guest `>` possession | |
| 17–18 / 20–21 | | home / guest shots |
| 19 / 22 (+47/48 tens) | | home / guest corners |
| 18 / 19 | home / guest time-outs | |
| 20 · 21–22 · 23–24 · 25 | down · to go · ball on · quarter | |
| 26–33 / 34–41 | home / guest name | (31–38 / 39–46) |
| 29 / 30 | | period / horn |
| 116 · 117 · 118 | clock status · clock mode · play-clock status | same |
| 131 · 132–137 · 138–149 | channel · bot number hex · timestamp | same |
