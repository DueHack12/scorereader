# ScoreBot hardware configuration

Facts about how ScoreConnect III configures the bot for each catalog wiring option, implemented in
`scoreboards/hardware.py` (`HARDWARE`, `pic_commands`, `data_baud`, `radio_setup`, `radio_baud_setup`,
`eth_serial`, `dynamic_config`, `configs_for_vendor`, `plan`). Sources: Mac build 1.3.0.21 (bot init flow, PIC
conversation, network bots) and the newer Windows build (hardware layer, entities, radios). **Differences are
marked "Win".** The bot-init code (`ScoreLink_Init`) is only in the Mac decompile; the Windows build is assumed
identical there (unverified). Items marked **(unverified)** are inference or untested on hardware.

## Model
Each catalog wiring option names a `HardwareConfigurationType`: interface (pic, laird, digi, digi_check_version,
digi_24ghz, silabs, silabs_zigbee, receiver, udp; Win adds tcp_server), source (rs232 `2`, rs485 `4`, nevco `N`,
current loop `C`, xbee `X`), PIC decoder (`0` none, `N` Nevco, `F` MP69, `7` MP70, `D` Daktronics 4000, `S` serial
non-standard), baud, polarity (`I`/`N`). Names in the catalog use `/` and spaces (`PIC_RS485/22_...`,
`NO HARDWARE CONFIGURATION`); `normalize()` maps them to the enum spelling. `HARDWARE[name]` has `device`
(pic | laird | digi_xbee | silabs | receiver | udp | tcp | none; `receiver` and `tcp` are additions to the suggested
list), `interface`, `source`, `decode`, `baud`, `inverted`, `command_baud`.

* **Baud is the baud of the data the host reads.** The PIC is a signal router (mux), so for pass-through
  configurations it equals the scoreboard baud. With an on-board decoder (Dak4000, Nevco, MP69/70, serial) the
  PIC re-emits decoded data at 57600. `62100` and `10000` are legacy odd bauds; pyserial may reject them
  on some drivers **(unverified)**.
* `NO HARDWARE CONFIGURATION`: ScoreConnect sends nothing to the PIC. Win: empty configs default to 9600 baud
  (Mac default was the enum's first value, 110). Used by software feeds (Virtual Bot, ICast, View All ...).
* `UDP`, `TCP_SERVER` (Win): no PIC conversation; data arrives over the network.
* Win `CUTOM_DYNAMYC_BUILD` (sic, DB id 110): operator picks source, baud, polarity. See `dynamic_config()`.
  Nevco forces decode N at 57600; a custom baud (100..99999) forces decode S at 57600 with
  `nonstandard_serial = f"{baud:05d}8N1"`; polarity only honoured for rs485 and current loop.

## ScoreLinkII (USB) conversation, as ScoreConnect does it
1. Open the CDC port at **57600 8N1**.
2. MCP2221 GP2 low = PIC command mode (library call: configure GP2 as output, set value; device opened and
   closed per call). Sleep 50 ms, drain input (20 ms read timeout).
3. `>R?` (firmware, `>R1.14` -> 1.14), `>B?` (must be non-empty or abort with "cannot communicate with the
   selector chip"). Skipped quirks: `>U?` (unique id) is read for serial number only.
4. Config commands (below), each terminated with `\r`.
5. GP2 high = data mode, sleep 50 ms, set host baud to `data_baud`. Then radio set-up if the interface is a radio
   (skipped for interface pic, receiver, udp).
ScoreConnect only does this when a configuration change is pending (`init_needed`); afterwards the PIC keeps
the setting in EEPROM and data mode is just GP2 high at the right baud. ScoreLinkPi (Raspberry Pi) does the
same with GPIO 23 (low = command mode, 50 ms) and GPIO 25 (reset, held high) and serial `/dev/ttyS0`.

### Command sequence (`pic_commands`)
Always `>M0X0X`, `>T0`, `>D<decode>` (`>DS` falls back to `>D0` unless PIC firmware is exactly 1.14), then by source:

| source / decode | commands after `>D` |
|---|---|
| C, none | `>M8<p>1N` |
| C, D (Dak4000) | `>M8I6N`, `>M5N1N` (polarity always I) |
| 2 (rs232) | `>I2`, `>M4<p>1N`, `>M1<p>4N` |
| 4, none | `>I4`, `>M4<p>1N`, `>M1<p>4N` |
| 4, 7 or F | `>I4`, `>M4<p>6N`, `>M5N1N` |
| 4, S, fw 1.14 | `>I4`, `>M4<p>6N`, and if `nonstandard_serial`: `>M5N1N`, `>S<nonstandard_serial>` |
| 4, S, other fw | `>I4`, `>M4<p>1N`, `>M5N1N` (with `>D0`) |
| X (xbee radios) | `>M1<p>3N`, `>M3<p>1N` |
| N (Nevco) | `>M1<p>5N`, `>M5<p>1N` |

`<p>` is `I` or `N`. Daktronics current loop gives exactly `>M0X0X >T0 >D0 >M8I1N`, which is also
ScoreReader's `config_commands`. Reading of the mux letters (inference, **unverified**): `M<in><pol><out><pol>`
routes port `in` to port `out`; 1 = USB, 3 = radio, 4 = RS232/485, 5 = PIC TX, 6 = PIC RX, 8 = current loop,
`0X0X` clears. `nonstandard_serial` = `<baud 5 digits><data bits><parity><stop bits>`: `621009N2` = 62100 baud, 9 data
bits, no parity, 2 stop (Eversan); `192009N1` (Favero, Baybor); `560009N2` (Nautronic NG 08). Radio wiring options
(`LAIRD_*`, `DIGI_*`, `SILABS_*`) also run the PIC routing above.

### Verification, timing and retries (`PIC_TIMING`, `readback_query`, `verify_reply`)
* Each command is written, then ScoreConnect waits **300 ms** (EEPROM write), sends a read-back query and compares
  the reply; failure waits 300 ms and rewrites. **`>M...` commands: up to 10 tries; all others: 4.** 100 ms
  pause after each command.
* Queries: `>M<n>?` style for `>M`: the first three characters plus `?` (`>M8?`); for slot-clear `>M0X0X` it
  asks `>M?`. Others: first two characters plus `?` (`>T?`, `>D?`, `>I?`, `>S?`).
* Replies start with the `>` echo. Only characters are compared: `>M` commands: indexes 0, 2, 4 (index 3 and 5,
  polarity/last, are not checked); `>M0X0X`: reply[2] against cmd[4]; others: index 2 only (`>S` therefore checks only the first digit).
* Reply read: write, wait 200 ms, read to CR with a 500 ms timeout. The write itself is sent without reading its
  reply, and the input buffer is not flushed before the query, so the compared line may be the echo of the write
  rather than the query answer **(unverified; ScoreReader's `reset_input_buffer` avoids the ambiguity)**.

### Differences from `scorereader.py`
* ScoreReader: GP2 low, 50 ms, baud 57600, 50 ms, flush; queries `R? B? U? M? T? D? M8?` (log only); per
  command: write, 300 ms, one read-back (`c[:3]?` for `>M`, `c[:2]?` otherwise), logged, **no retry or comparison**.
  GP2 high, 50 ms, `cfg["baud"]`, 50 ms, flush.
* ScoreReader's read-back for `>M0X0X` is `>M0?`; ScoreConnect uses `>M?`.
* ScoreReader does not read `>R?` or change commands by firmware (matters only for serial decode).
* ScoreReader uses one global `baud`; use `data_baud(hardware)` per wiring option.
* ScoreReader resets GP2 through SRAM read-modify-write; ScoreConnect just configures GP2 as output and sets it.
  Equivalent **(unverified)**.
* ScoreConnect flushes input after entering command mode and not after leaving; harmless.

## Radios (`radio_setup`, `radio_baud_setup`)
Run on the data-mode stream at `baud` after the PIC is back in data mode. All parameters come from per-vendor
wireless tables not in the catalog, so the caller supplies `sys_id`, `channel`, `group`. Replies are matched
exactly (Laird, `equals`) or by substring (`contains`). Steps are `RadioStep(kind, send, expect, match, delay_ms,
timeout_ms, tries)`.

* **Laird**: `AT+++\r` -> `CC 43 4F 4D`; set sys id `CC C1 76 01 id` -> `76 01 id`; channel `CC C1 40 01 ch` ->
  `40 01 ch` (with group: `group*8+channel` when both valid, else `group`); read antenna register `CC C0 C1 01` ->
  `CC C1 01 v`, write `CC C1 C1 01 v'` (`v|0x20` external, `v&0xDF` internal) -> `C1 01 v'`; reset `CC FF`.
  The module assumes register 0 when the read has not happened. Win only: baud change `CC C1 42 01 id`, read `CC C0 42 01`
  -> `CC 42 01 id`, reset (ids 115200=9, 57600=8, 38400=7, 28000=6, 19200=5, 14400=4, 9600=3, 4800=2, 2400=1, 1200=0).
  Win also builds Latin-1 command strings (Mac used UTF-8 for those list helpers, which mangles bytes >= 0x80; the
  live path used raw bytes in both).
* **Digi XBee**: `+++` -> `OK\r` (4 tries, 500 ms); `ATVR\r` firmware must be: check_version >= 8074, 24ghz <= 2012,
  plain 2013..3014. Then each command `-> OK\r` (50 ms, 2 s window, one try): plain Digi (no group): `ATHP<hp>`, `ATDT<dt>`,
  `ATWR` with (hp, dt) from a 100-entry table indexed by the *channel* value; check_version: `ATIDE55`, `ATHP<group:02X>`,
  `ATCM<mask>` (mask `FFFFFF8000000000` if channel == 1 else `FFFFFFFFFFF7FFFF`), `ATWR`; 24 GHz: `ATID<group:04X>`,
  `ATCH<ch:02X>`, `ATWR`. Finally `ATCN\r`. Win only: baud `ATBD<id>` (57600=6 ... 1200=0), read `ATBD` -> `<id>`, `ATWR`, `ATCN`.
* **Silicon Labs** (Custom and ZigBee): `receive 0 \n`, `set_phy_config 0\n` (id 0 for both; the expected answer names Custom
  or ZigBee), `save_channel <ch> \n` (space before newline), `receive 1 \n`. Win adds no baud change.
* Interface 6 (`WIRELESS_NOCONFIG`), pic, udp: no radio steps.

## ScoreLink (I), ScoreLinkPi, "ScoreBot1000"
* **ScoreLink (I)** (`SetPinsScoreLink`): the PIC is on the serial interface at 57600 and only configured after `>T?` -> `>T0`.
  Commands `>I<source>`, `>D<decode>`, `>T0`, `>S<P|S>` (P if a PIC decoder is used else S), `>P<polarity>`,
  each retried up to 5 times with a read-back that must equal the command. The legacy catalog group
  "Wired Legacy ScoreLinkI" (Eversan 62100 baud) targets it. It has no MCP2221 mode line; its mode is chosen
  via network/serial. Its xPico side is configured over a Telnet/JSON console (port 9999, password-protected).
* **ScoreLinkPi / ScoreLink Plus**: ScoreLinkII commands over `/dev/ttyS0` with GPIO 23 for mode.
* **ScoreBot1000** (UDS1100): network serial server only, configured with the `eth_serial` fields (below).

## Network bots (BOTDiscovery / BOTServer / BOTClient)
* **Discovery**: UDP broadcast on each active IPv4 NIC to port **30718** with `00 00 00 F6`; replies are 30 bytes with
  byte 3 = `F7`, bytes 8..9 = model (`Y2` ScoreLinkII, `X6` ScoreLink, `U3` ScoreBot1000), bytes 24..29 = MAC. Setup
  records are read from TCP 30718 (`00 00 00 E0+rec` -> 130 bytes; bot number text at offset 53) and written with
  `C0+rec` (ack `B0+rec`). ScoreLink firmware query: UDP `00 01 00 F4` -> 33-byte reply; bot number `00 00 00 E2`.
* **ScoreLinkII (network)**: xPico240 with HTTP JSON POST to `/webAPI.json` (basic auth with fixed vendor credentials,
  not reproduced here); version banner on TCP 1410; command mode is the xPico pin CP11 (0 = command, 1 = data).
  Order: set CP11 low, set PrimaryServer `<host>:1402`, serial 57600, save, reboot, wait up to 60 s for the bot to
  connect to the local server, configure PIC as above, CP11 high, set serial server (baud, mode, delay, start/stop
  chars), save, reboot. Cloud fallback servers and a control server are also written (Sportzcast cloud, not needed).
* **BOTServer**: TCP listener on **1402**. The bot connects out to it. First 2 bytes of the first message select a
  command: `BO` + 5-digit bot number (`BO` bot handshake; the rest of the stream is raw scoreboard bytes), `PG` (reply
  `ip|time`), `PC` (web port), `CV` (`OK|||`), `GT` (bot list), `CN`, `FB`, `EX`, and `ST`/`XB`/`JB` + bot number
  (stream the 150-char sbdata, XML or JSON about every 2 s or on change). Firewall note in ScoreConnect: ports 1400-1410.
* **To support them ScoreReader would need**: a UDP 30718 discovery client; a TCP listener on 1402 that accepts
  the `BO` handshake and treats the rest as the data stream (existing `tcp` source, plus handshake); and for
  configuration, the xPico HTTP/JSON or Telnet clients with their credentials, which are not in this repo. Read-only
  support (listen on 1402 for bots already pointed at the PC, plus the `ST` stream) needs only the listener.
  Reading wired USB bots needs none of this.

## EthSerialConfiguration strings (`eth_serial`)
`MODE<mode>_DELAY<n>_STRTCHR<hex>_STPCHR<hex>_INT<4C|4D>` (or `LENGTH<n>` instead of the stop char). They are the
serial-server (framing) settings pushed to a network bot's xPico/UDS so it forwards complete frames:
`mode` = `55aa`, `delay` (inter-byte gap ends a packet), `16/17`, `start/length`, `start/end`, `delay+framing`;
`delay` = packet gap in character times (1..8, 50); `start`/`stop` = delimiter bytes (`02h` STX, `04h` EOT, `03h` ETX,
`0Dh`...); `INT4C/4D` = interface-mode byte (`4Ch`/`4Dh`; meaning not decoded **(unverified)** - likely RS-232 vs RS-422/485 setup of the
xPico). `LENGTH` variants have no stop char: ScoreConnect sends the default `04h` and never sends the length
**(unverified whether the device needs it)**. Mode spellings with spaces (`start length`) exist for the ScoreLinkII
device type but ScoreConnect always sends the ScoreLink (I) spellings. For USB bots these are unused. `read_timeout`
(catalog, ms) enables ScoreConnect's frame-on-time reading: instead of reading blocks it accumulates bytes until the
port read times out for that many milliseconds, then decodes the buffer as one frame (Colorado Timing 2 ms,
FairPlay MP80 50 ms, plus three more in the Windows catalog).

## Open questions
Exact PIC firmware behaviour (mux letter meanings, `>B` baud index); whether `>M0X0X` followed by the first route is
required each time; Windows bot-init flow identical to Mac; whether UDP/TCP_SERVER configs ever touch the PIC;
radio parameter tables (not in catalog); whether serial `>S` stores the string verbatim.
