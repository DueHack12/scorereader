#!/usr/bin/env python3
"""
ScoreReader - open-source replacement for Sportzcast ScoreConnect III
=====================================================================

Reads live scoreboard data straight from a Sportzcast ScoreLinkII / ScoreBot over
USB (Microchip MCP2221, VID 04D8 PID 00DD) - or any USB-serial adapter wired to the
console - decodes Daktronics All Sport 5000 data, and serves it to graphics:

  * Web dashboard ........ http://localhost:8765/
  * vMix Data Source ..... http://localhost:8765/data.json   (also /data.xml, /data.csv)
  * vMix TCP API push .... SetText straight into a title input (optional)
  * MQTT ................. ScoreConnect-compatible broker, bot/{N}/json|sbdata|raw
  * Plain text files ..... one .txt per field (optional)

Protocols (auto-detected):
  * Daktronics current loop (scoreboard driver output, 55 AA frames, 7-segment data)
    - football (console code 6601) and soccer (7601)
  * Daktronics RTD (J6 serial port, SYN/SOH/STX/ETB text packets) - all sports

See docs/PROTOCOL.md for the wire formats and README.md for usage.
Run  `python scorereader.py --help`  for options.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as _dt
import io
import json
import os
import queue
import random
import signal
import socket
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape as xml_escape

__version__ = "2.1.2"

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)  # PyInstaller support
# A Mac app (ScoreReader.app) can't write inside itself (macOS may even run it from a read-only copy), so its
# settings, logs and text files live in ~/Library/Application Support/ScoreReader. Everything else keeps them
# next to the program, as before.
MAC_APP = sys.platform == "darwin" and getattr(sys, "frozen", False) and ".app/Contents/" in APP_DIR
DATA_DIR = (os.path.join(os.path.expanduser("~"), "Library", "Application Support", "ScoreReader")
            if MAC_APP else APP_DIR)
ASSETS_DIR = os.path.join(RES_DIR, "assets")  # icon.svg / icon.png / menubar.png
CONFIG_PATH = os.path.join(DATA_DIR, "scorereader_config.json")
FIELDS_PATH = os.path.join(RES_DIR, "daktronics_fields.json")
STATE_PATH = os.path.join(DATA_DIR, "scorereader_state.bin")
LOG_DIR = os.path.join(DATA_DIR, "logs")

SCORELINK_VID, SCORELINK_PID = 0x04D8, 0x00DD

DEFAULT_CONFIG = {
    "source": "scorelink",          # scorelink | serial | tcp | demo
    "port": "auto",                 # auto | COM5 | /dev/cu.usbmodem1101 ...
    "baud": 19200,                  # scoreboard data baud (Daktronics All Sport 5000 = 19200)
    "sport": "football",
    # Scoreboard brand + sport, as a ScoreConnect vendor-sport id (see scoreboards/catalog.json), e.g.
    # "PIC55AA_Nevco_Basketball". Blank = the built-in Daktronics All Sport 5000 decoders (current loop + RTD),
    # which pick football/soccer from the console automatically. "connection" picks the wiring option.
    "scoreboard": {"protocol": "", "connection": 0},
    "scorelink": {
        "use_gpio_mode_switch": True,   # drive MCP2221 GP2 (needs `hidapi`)
        "probe_on_start": True,         # ask the PIC its version/config at startup (log only)
        "send_config_on_start": False,  # re-send config_commands every start
        "command_baud": 57600,
        # exactly what ScoreConnect III sent for Daktronics football (current loop, inverted):
        "config_commands": [">M0X0X", ">T0", ">D0", ">M8I1N"],
        "configured_for": "",           # brand/wiring the bot was last configured for (set automatically)
    },
    "tcp": {"host": "", "port": 0},     # for serial-to-ethernet converters
    "http_port": 8765,
    "vmix": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8099,
        "input": "Scorebug",
        # field -> title element. String = SetText. Object forms:
        #   {"name": "HomePoss.Source", "visible": true}       -> SetImageVisibleOn/Off
        #   {"name": "HomePoss.Text", "true": "<", "false": ""} -> SetText with mapped text
        "fields": {
            "clock": "Clock.Text",
            "play_clock": "PlayClock.Text",
            "home_score": "HomeScore.Text",
            "guest_score": "GuestScore.Text",
            "period_ordinal": "Quarter.Text",
            "down_distance": "DownDistance.Text",
            "ball_on": "BallOn.Text",
            "home_timeouts": "HomeTOL.Text",
            "guest_timeouts": "GuestTOL.Text",
            "home_poss": {"name": "HomePoss.Text", "true": "◀", "false": ""},
            "guest_poss": {"name": "GuestPoss.Text", "true": "▶", "false": ""},
        },
    },
    "mqtt": {
        # Sportzcast/ScoreConnect III-compatible MQTT (for OSE etc.)
        "enabled": True,
        "mode": "broker",            # broker = host our own (like ScoreConnect), client = publish to broker_host
        "bot_number": 0,             # topics bot/{bot_number}/json|sbdata|raw  - match what OSE expects
        "tcp_port": 1883,
        "ws_port": 8083,
        "broker_host": "127.0.0.1",
        "broker_port": 1883,
        "publish_rate": 10,          # max messages/sec on json & sbdata
        "heartbeat_seconds": 1.0,    # re-publish even when nothing changed
        "publish_raw": True,
    },
    # Team info added to every output (data.json, vMix, MQTT). A blank name falls back to the name the
    # console sends (RTD only), then to the legacy mqtt.home_team_name / guest_team_name, then HOME / GUEST.
    "teams": {"home_name": "", "guest_name": "", "home_abbr": "", "guest_abbr": "",
              "home_color": "", "guest_color": ""},
    "text_files": {"enabled": False, "folder": "text_out"},
    "record_raw": True,
    "save_state": False,             # restore the last RTD buffer after a restart (scorereader_state.bin)
    # data.json/xml/csv and text files carry only the fields used in the sport; True adds every raw field
    # (Daktronics RTD manual fields, Sportzcast contract fields). The dashboard always shows everything.
    "output_all_fields": False,
    "strict_daktronics_header": True,
}

BUILTIN_BOT_KEY = "daktronics-builtin"  # scorelink.configured_for after the bot is set up for the built-in decoders

# Sources that are never written to scorereader_config.json, so the next normal start is always live data.
RUNTIME_ONLY_SOURCES = ("demo", "replay")


# --------------------------------------------------------------------------- utils
_PRINT_LOCK = threading.Lock()


def log(msg: str) -> None:
    line = f"{_dt.datetime.now():%H:%M:%S} {msg}"
    with _PRINT_LOCK:
        try:
            print(line, flush=True)
        except (OSError, ValueError, AttributeError):
            pass  # the console window was closed (Mac menu bar keeps running): the line still reaches the dashboard
    STATUS.add_log(line)


def detach_console(path: str) -> None:
    """Send further console output to a log file, so the program keeps running after its window is closed."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        f = open(os.devnull, "w")
    with _PRINT_LOCK:
        sys.stdout = sys.stderr = f


def set_window_title(title: str) -> None:
    """Name the console window/tab, so the taskbar (Windows) or Terminal (Mac/Linux) shows "ScoreReader"."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(title)
        elif sys.stdout is not None and sys.stdout.isatty():
            sys.stdout.write(f"\033]0;{title}\007")
            sys.stdout.flush()
    except Exception:
        pass


def deep_merge(base: dict, over: dict) -> dict:
    """Recursive merge that returns a fully independent copy (changing it never touches base/over)."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "fields":
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return deep_merge(DEFAULT_CONFIG, json.load(f))


def save_config(cfg: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH) or ".", exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def get_path(d: dict, path: str, default=None):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def set_path(d: dict, path: str, value) -> None:
    *parents, last = path.split(".")
    for k in parents:
        d = d.setdefault(k, {})
    d[last] = value


# Settings editable from the dashboard.  path: (group, label, type, apply)
#   type:  str | int | port | bool | color | choice
#   apply: live    = takes effect immediately
#          reader  = restarts the data source (and clears the decoded values)
#          vmix    = reconnects the vMix TCP push
#          restart = saved now, used the next time ScoreReader starts
SETTINGS = {
    "source": ("Data source", "Source", "choice", "reader"),
    "port": ("Data source", "Serial port", "str", "reader"),
    "baud": ("Data source", "Baud", "int", "reader"),
    "tcp.host": ("Data source", "TCP host", "str", "reader"),
    "tcp.port": ("Data source", "TCP port", "port", "reader"),
    "replay_file": ("Data source", "Capture to replay", "choice", "reader"),
    "scorelink.probe_on_start": ("Data source", "Ask the bot for its settings at start", "bool", "reader"),
    "scorelink.send_config_on_start": ("Data source", "Re-send the bot configuration at start", "bool", "reader"),
    "scoreboard.protocol": ("Scoreboard", "Scoreboard brand and sport", "choice", "reader"),
    "scoreboard.connection": ("Scoreboard", "Wiring", "int", "reader"),
    "sport": ("Scoreboard", "Sport (used when the console doesn't identify itself)", "choice", "live"),
    "teams.home_name": ("Teams", "Home name", "str", "live"),
    "teams.home_abbr": ("Teams", "Home abbreviation", "str", "live"),
    "teams.home_color": ("Teams", "Home color", "color", "live"),
    "teams.guest_name": ("Teams", "Guest name", "str", "live"),
    "teams.guest_abbr": ("Teams", "Guest abbreviation", "str", "live"),
    "teams.guest_color": ("Teams", "Guest color", "color", "live"),
    "vmix.enabled": ("vMix", "Push values to vMix (TCP API)", "bool", "vmix"),
    "vmix.host": ("vMix", "vMix host", "str", "vmix"),
    "vmix.port": ("vMix", "vMix TCP port", "port", "vmix"),
    "vmix.input": ("vMix", "Title input name or number", "str", "vmix"),
    "mqtt.enabled": ("MQTT (OSE)", "MQTT output", "bool", "restart"),
    "mqtt.bot_number": ("MQTT (OSE)", "Bot number (topics bot/N/…)", "int", "live"),
    "mqtt.mode": ("MQTT (OSE)", "Mode", "choice", "restart"),
    "mqtt.tcp_port": ("MQTT (OSE)", "Broker TCP port", "port", "restart"),
    "mqtt.ws_port": ("MQTT (OSE)", "Broker WebSocket port", "port", "restart"),
    "mqtt.broker_host": ("MQTT (OSE)", "External broker host (client mode)", "str", "restart"),
    "mqtt.broker_port": ("MQTT (OSE)", "External broker port (client mode)", "port", "restart"),
    "text_files.enabled": ("Files", "Write one .txt file per field", "bool", "live"),
    "record_raw": ("Files", "Record raw bytes to logs/", "bool", "live"),
    "save_state": ("Files", "Remember board values after a restart (RTD only)", "bool", "live"),
    "http_port": ("Advanced", "Dashboard / data.json port", "port", "restart"),
    "output_all_fields": ("Advanced", "Include every raw field in data.json / XML / CSV", "bool", "live"),
}


def list_captures() -> list[str]:
    try:
        names = [n for n in os.listdir(LOG_DIR) if n.endswith(".bin")]
    except OSError:
        return []
    return sorted(names, key=lambda n: os.path.getmtime(os.path.join(LOG_DIR, n)), reverse=True)[:50]


def coerce_setting(path: str, value, choices: dict):
    """Validate one dashboard setting. Returns the clean value or raises ValueError with a readable message."""
    kind = SETTINGS[path][2]
    if kind == "bool":
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if kind in ("int", "port"):
        try:
            n = int(str(value).strip())
        except ValueError:
            raise ValueError("must be a whole number") from None
        lo, hi = (1, 65535) if kind == "port" else (0, 10_000_000)
        if path == "mqtt.ws_port":
            lo = 0  # 0 = WebSocket off
        if not lo <= n <= hi:
            raise ValueError(f"must be between {lo} and {hi}")
        return n
    if kind == "color":
        v = str(value or "").strip()
        if v and not (len(v) == 7 and v[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in v[1:])):
            raise ValueError("must look like #1E3A8A (or be blank)")
        return v.upper()
    if kind == "choice":
        v = str(value)
        if v not in choices.get(path, ()):
            raise ValueError(f"'{v}' is not one of: {', '.join(choices.get(path, ())) or 'none available'}")
        return v
    v = str(value if value is not None else "").strip()
    if len(v) > 200:
        raise ValueError("is too long")
    return v


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


class Status:
    def __init__(self):
        self.lock = threading.Lock()
        self.source_state = "starting"
        self.source_detail = ""
        self.bytes_in = 0
        self.packets = 0
        self.bad_packets = 0
        self.unknown_headers: dict[str, int] = {}
        self.last_packet_time = 0.0
        self.last_byte_time = 0.0
        self.vmix_state = "disabled"
        self.pic_info: dict[str, str] = {}
        self.logs: list[str] = []
        self.recent_hex = ""

    def add_log(self, line: str):
        with self.lock:
            self.logs.append(line)
            del self.logs[:-200]

    def set_source(self, state: str, detail: str = ""):
        with self.lock:
            self.source_state, self.source_detail = state, detail

    def reset_counters(self):
        """Called when the data source changes, so the dashboard doesn't mix the old and new sources."""
        with self.lock:
            self.bytes_in = self.packets = self.bad_packets = 0
            self.unknown_headers = {}
            self.last_packet_time = self.last_byte_time = 0.0
            self.pic_info = {}
            self.recent_hex = ""


STATUS = Status()


# --------------------------------------------------------------------------- RTD decoder
class DaktronicsRTD:
    """Daktronics 'Enhanced RTD' stream decoder.

    Packet: SYN(0x16) ... SOH(0x01) header STX(0x02) data EOT(0x04) checksum ETB(0x17)
    header = '004210' + 4-digit zero-based offset into the console's RTD buffer.
    Only changed regions are sent, so we keep a persistent buffer.
    """

    SYN, SOH, STX, EOT, ETB = 0x16, 0x01, 0x02, 0x04, 0x17

    def __init__(self, strict_header: bool = True, size: int = 1024):
        self.buf = bytearray(b" " * size)
        self.changed_at = [0.0] * size
        self.pending = bytearray()
        self.strict = strict_header
        self.lock = threading.Lock()
        self.version = 0  # bumps on every change

    def load(self, path: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
            with self.lock:
                self.buf[: len(data)] = data[: len(self.buf)]
            log(f"Restored last known scoreboard state ({len(data)} bytes)")
        except FileNotFoundError:
            pass
        except Exception as e:
            log(f"Could not restore state: {e}")

    def save(self, path: str):
        with self.lock:
            data = bytes(self.buf)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def feed(self, data: bytes) -> int:
        """Feed raw bytes; returns number of packets applied."""
        self.pending += data
        applied = 0
        while True:
            s = self.pending.find(self.SYN)
            if s < 0:
                self.pending.clear()
                break
            e = self.pending.find(self.ETB, s + 1)
            if e < 0:
                if s:
                    del self.pending[:s]
                if len(self.pending) > 4096:  # garbage / wrong baud
                    self.pending.clear()
                break
            pkt = bytes(self.pending[s + 1 : e])
            del self.pending[: e + 1]
            if self._apply(pkt):
                applied += 1
        return applied

    def _apply(self, pkt: bytes) -> bool:
        soh = pkt.find(bytes([self.SOH]))
        if soh < 0:
            STATUS.bad_packets += 1
            return False
        rest = pkt[soh + 1 :]
        stx = rest.find(bytes([self.STX]))
        if stx < 0:
            return False  # header-only packet (no data)
        header, rest = rest[:stx], rest[stx + 1 :]
        eot = rest.find(bytes([self.EOT]))
        data = rest[:eot] if eot >= 0 else rest
        h = header.decode("latin-1", "replace")
        if self.strict and not h.startswith("004210"):
            key = "".join(c if 32 <= ord(c) < 127 else "." for c in h[:24])
            if len(STATUS.unknown_headers) < 20 or key in STATUS.unknown_headers:
                STATUS.unknown_headers[key] = STATUS.unknown_headers.get(key, 0) + 1
            return False
        try:
            offset = int(h[-4:])
        except ValueError:
            STATUS.bad_packets += 1
            return False
        if not data:
            return False
        end = offset + len(data)
        with self.lock:
            if end > len(self.buf):
                grow = end - len(self.buf) + 256
                self.buf += b" " * grow
                self.changed_at += [0.0] * grow
            if self.buf[offset:end] != data:
                now = time.time()
                for i in range(offset, end):
                    if self.buf[i] != data[i - offset]:
                        self.changed_at[i] = now
                self.buf[offset:end] = data
                self.version += 1
        STATUS.packets += 1
        STATUS.last_packet_time = time.time()
        return True

    def snapshot(self) -> bytes:
        with self.lock:
            return bytes(self.buf)


def encode_rtd_packet(offset: int, text: str) -> bytes:
    """Build a Daktronics RTD packet (used by demo mode / tests)."""
    body = b"\x01" + f"004210{offset:04d}".encode() + b"\x02" + text.encode("latin-1") + b"\x04"
    csum = f"{sum(body) & 0xFF:02X}".encode()
    return b"\x16" + body + csum + b"\x17"


# --------------------------------------------------------------------------- Daktronics current-loop (scoreboard driver) protocol
SEG7 = {0x3F: "0", 0x06: "1", 0x5B: "2", 0x4F: "3", 0x66: "4", 0x6D: "5", 0x7D: "6", 0x07: "7", 0x7F: "8",
        0x6F: "9", 0x67: "9", 0x00: " "}


def seg(b: int) -> str:
    return SEG7.get(b & 0x7F, " ")


class DaktronicsCurrentLoop:
    """Decoder for the All Sport 5000 *current loop* output (what a ScoreBot on M8 / current-loop receives).

    Frame: 55 AA | addr | len | x | x | 22 | data ... | checksum      (len+5 bytes after 55 AA)
    sum(addr..checksum) + 0x55 + 0xAA == 0 (mod 256).  Data bytes are 7-segment patterns.
    Field layout = ScoreConnect III 'Daktronics Main FootballDecoder' (console code 6601).
    """

    def __init__(self):
        self.pending = bytearray()
        self.frames: dict[int, tuple[bytes, float]] = {}
        self.lock = threading.Lock()
        self.version = 0
        self.packets = 0
        self.bad = 0
        self.last_time = 0.0
        self.console_code = ""
        self.sport_fallback = lambda: "football"  # set by App -> configured sport
        self.custom_fields = lambda: {}  # set by App -> cfg["custom_fields"]
        self.st = {"clock_mode": ":", "clock_digits": "    ", "tenths": "", "play_clock": "",
                   "home_shots": "", "guest_shots": "", "home_corners": "", "guest_corners": "", "horn": False,
                   "clock_running": False, "home_score": "", "guest_score": "", "period": "",
                   "home_poss": False, "guest_poss": False, "home_timeouts": "", "guest_timeouts": "",
                   "ball_on": "", "down": "", "to_go": ""}

    def feed(self, data: bytes) -> int:
        self.pending += data
        n_ok = 0
        while True:
            i = self.pending.find(b"\x55\xaa")
            if i < 0:
                if len(self.pending) > 1:
                    del self.pending[:-1]
                break
            if i:
                del self.pending[:i]
            if len(self.pending) < 4:
                break
            ln = self.pending[3]
            total = 2 + ln + 5
            if len(self.pending) < total:
                break
            pkt = bytes(self.pending[2:total])
            if pkt[4] == 0x22 and (sum(pkt) + 0x55 + 0xAA) & 0xFF == 0:
                del self.pending[:total]
                self._apply(pkt)
                n_ok += 1
            else:
                self.bad += 1
                del self.pending[:2]
        return n_ok

    CODE_SPORT = {"6601": "football", "7601": "soccer"}

    @property
    def sport(self) -> str:
        return self.CODE_SPORT.get(self.console_code) or self.sport_fallback()

    def _apply(self, p: bytes):
        addr, n = p[0], len(p)
        now = time.time()
        self.packets += 1
        self.last_time = now
        STATUS.packets += 1
        STATUS.last_packet_time = now
        st = dict(self.st)
        if addr == 0xFE:
            self.console_code = p[5:9].decode("latin-1", "replace")
        elif addr == 1:
            if n > 10:
                st["play_clock"] = (seg(p[9]) + (seg(p[10]) if n > 11 else "")).strip()
            if n > 9:
                st["clock_mode"] = ":" if p[8] else "."
            self._set_clock(st, p, n)
            if n > 12:
                st["clock_running"] = (p[11] & 0x40) == 0
        elif self.sport == "soccer":
            self._apply_soccer(st, p, addr, n)
        elif addr == 15:
            self._set_clock(st, p, n)
            if n > 13:
                st["home_score"] = (seg(p[11]) + seg(p[12])).strip()
            if n > 15:
                st["guest_score"] = (seg(p[13]) + seg(p[14])).strip()
            if n > 18:
                st["home_poss"] = p[17] == 7
                st["guest_poss"] = p[17] == 56
            if n > 19:
                st["home_timeouts"] = seg(p[18]).strip()
            if n > 20:
                st["guest_timeouts"] = seg(p[19]).strip()
            if n > 16:
                st["period"] = seg(p[15]).strip()
        elif addr == 16:
            if n > 7:
                st["ball_on"] = (seg(p[5]) + seg(p[6])).strip()
            if n > 8:
                st["down"] = seg(p[7]).strip()
            if n > 10:
                st["to_go"] = (seg(p[8]) + seg(p[9])).strip()
        with self.lock:
            prev = self.frames.get(addr)
            self.frames[addr] = (p, now)
            if st != self.st or prev is None or prev[0] != p:
                self.st = st
                self.version += 1

    def _apply_soccer(self, st, p, addr, n):
        """ScoreConnect 'Daktronics Main SoccerDecoder' (code 7601) + addr 72 stats panel."""
        two = lambda a: (seg(p[a]) + seg(p[a + 1])).strip() if n > a + 1 else ""  # noqa: E731
        if addr == 11:
            self._set_clock(st, p, n)
            if n > 17:
                st["home_score"] = two(15)
            if n > 19:
                st["guest_score"] = two(17)
            if n > 20:
                st["period"] = seg(p[19]).strip()
        elif addr == 12:
            if n > 14:
                st["horn"] = bool(p[13] & 0x80)
            if n > 17:
                st["home_shots"] = two(15)
            if n > 19:
                st["guest_shots"] = two(17)
        elif addr == 13:
            # ScoreConnect's spot for corners - only used if this board has no stats panel (addr 72)
            hc, gc = two(15), two(17)
            seen72 = self.frames.get(72)
            if (hc or gc) and not (seen72 and time.time() - seen72[1] < 10):
                st["home_corners"], st["guest_corners"] = hc, gc
        elif addr == 72 and n > 20:
            # stats panel: [CKICKS h][SOG h] ... [CKICKS g][SOG g]
            st["home_corners"], st["guest_corners"] = two(5), two(15)
            hs, gs = two(8), two(18)
            if hs or gs:
                st["home_shots"], st["guest_shots"] = hs, gs

    @staticmethod
    def _set_clock(st, p, n):
        d = [seg(p[i]) if n > i + 1 else " " for i in range(5, 9)]
        if st["clock_mode"] == ".":
            st["clock_digits"], st["tenths"] = d[0] + d[1], d[2]
        else:
            st["clock_digits"], st["tenths"] = "".join(d), ""

    def data(self) -> dict:
        st = self.st
        if st["clock_mode"] == ".":
            clock = f"{st['clock_digits'].strip()}.{st['tenths']}".strip(".")
        else:
            c = st["clock_digits"]
            clock = f"{c[:2].strip()}:{c[2:]}".strip(":") if c.strip() else ""
        per = st["period"]
        if self.sport == "soccer":
            return self._custom({
                "clock": clock.strip(),
                "clock_running": st["clock_running"],
                "home_score": st["home_score"] or "0",
                "guest_score": st["guest_score"] or "0",
                "period": per,
                "period_ordinal": ordinal(int(per)) if per.isdigit() and int(per) > 0 else per,
                "home_shots": st["home_shots"],
                "guest_shots": st["guest_shots"],
                "home_corners": st["home_corners"],
                "guest_corners": st["guest_corners"],
                "horn": st["horn"],
                "sport": "soccer",
                "console_code": self.console_code,
                "protocol": "daktronics_current_loop",
            })
        down = st["down"]
        dtxt = ordinal(int(down)) if down.isdigit() else down
        out = {
            "sport": "football",
            "clock": clock.strip(),
            "clock_running": st["clock_running"],
            "play_clock": st["play_clock"].lstrip("0") or ("0" if st["play_clock"] else ""),
            "home_score": st["home_score"] or "0",
            "guest_score": st["guest_score"] or "0",
            "period": per,
            "period_ordinal": ordinal(int(per)) if per.isdigit() and int(per) > 0 else per,
            "home_poss": st["home_poss"],
            "guest_poss": st["guest_poss"],
            "home_timeouts": st["home_timeouts"],
            "guest_timeouts": st["guest_timeouts"],
            "ball_on": st["ball_on"],
            "down": dtxt,
            "to_go": st["to_go"],
            "down_distance": f"{dtxt} & {st['to_go']}" if dtxt and st["to_go"] else dtxt,
            "console_code": self.console_code,
            "protocol": "daktronics_current_loop",
        }
        return self._custom(out)

    def _custom(self, out: dict) -> dict:
        """Apply config 'custom_fields': {"name": {"addr": 72, "bytes": [0, 1]}} (byte index = hex column position)."""
        for name, spec in (self.custom_fields() or {}).items():
            try:
                fr = self.frames.get(int(spec["addr"]))
                if fr is None:
                    continue
                body = fr[0][5:-1]
                out[name] = "".join(seg(body[i]) for i in spec["bytes"] if i < len(body)).strip()
            except (KeyError, TypeError, ValueError):
                continue
        return out

    def address_table(self) -> list:
        now = time.time()
        with self.lock:
            items = sorted(self.frames.items())
        rows = []
        for a, (p, t) in items:
            body = p[5:-1]
            rows.append({"addr": a, "len": p[1], "age": round(now - t, 1),
                         "digits": "".join(seg(b) if (b & 0x7F) in SEG7 else "?" for b in body[:40]),
                         "hex": body[:40].hex(" ")})
        return rows

# --------------------------------------------------------------------------- sport fields
class SportMap:
    def __init__(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            self.sports = json.load(f)

    def names(self):
        return sorted(self.sports)

    def fields(self, sport: str):
        return self.sports.get(sport, {"fields": []})["fields"]

    @staticmethod
    def _clean_clock(s: str) -> str:
        s = s.strip()
        if ":" in s:
            m, sec = s.split(":", 1)
            if m.strip() in ("", "0", "00"):
                s = sec.strip()
        if s.isdigit():
            s = str(int(s)) if s else s
        return s

    def extract(self, sport: str, buf: bytes) -> dict:
        out: dict = {}
        for f in self.fields(sport):
            p, ln = f["pos"] - 1, f["len"]
            raw = buf[p : p + ln].decode("latin-1", "replace") if p < len(buf) else ""
            if f["type"] == "bool":
                val = raw.strip() != ""
            elif f["type"] == "int":
                t = raw.strip()
                val = int(t) if t.isdigit() else t
            else:
                val = raw.strip()
            out[f["name"]] = val
        out.update(self.simple(sport, out))
        return out

    def simple(self, sport: str, d: dict) -> dict:
        """Friendly, sport-agnostic aliases for graphics."""
        g = d.get
        s: dict = {}

        def score(v):
            v = str(v if v is not None else "").strip()
            return str(int(v)) if v.isdigit() else (v or "0")

        s["clock"] = str(g("main_clock_time", "")).strip()
        s["home_name"] = g("home_team_name", "")
        s["guest_name"] = g("guest_team_name", "")
        s["home_abbr"] = g("home_team_abbreviation", "")
        s["guest_abbr"] = g("guest_team_abbreviation", "")
        s["home_score"] = score(g("home_team_score"))
        s["guest_score"] = score(g("guest_team_score"))
        s["home_timeouts"] = str(g("home_time_outs_left_total", ""))
        s["guest_timeouts"] = str(g("guest_time_outs_left_total", ""))
        per = next((g(k) for k in ("period", "quarter", "half", "inning") if k in d), "")
        s["period"] = str(per)
        s["period_ordinal"] = ordinal(per) if isinstance(per, int) and per > 0 else str(per)
        per_txt = next((g(k) for k in ("period_text", "quarter_text", "half_text", "inning_text") if k in d), "")
        s["period_text"] = str(per_txt or "").strip()
        s["home_poss"] = bool(g("home_possession_indicator", False))
        s["guest_poss"] = bool(g("guest_possession_indicator", False))
        s["clock_running"] = not bool(g("main_clock_stopped", False))
        if "play_clock_time" in d:
            s["play_clock"] = self._clean_clock(str(g("play_clock_time")))
        if "shot_clock_time" in d:
            s["shot_clock"] = self._clean_clock(str(g("shot_clock_time")))
        if sport == "football":
            down = str(g("down", "")).strip()
            togo = g("to_go", "")
            s["down"], s["to_go"] = down, str(togo)
            s["down_distance"] = f"{down} & {togo}" if down and togo != "" else down
            s["ball_on"] = str(g("ball_on", ""))
        if sport == "soccer":  # same names as the current-loop soccer output
            for side in ("home", "guest"):
                s[f"{side}_shots"] = str(g(f"{side}_shots_on_goal_total", "")).strip()
                s[f"{side}_corners"] = str(g(f"{side}_corner_kicks_total", "")).strip()
                s[f"{side}_saves"] = str(g(f"{side}_saves_total", "")).strip()
        if sport == "basketball":
            s["home_fouls"] = str(g("home_team_fouls", ""))
            s["guest_fouls"] = str(g("guest_team_fouls", ""))
            s["home_bonus"] = bool(g("home_1_on_1_bonus_indicator") or g("home_2_shot_bonus_indicator"))
            s["guest_bonus"] = bool(g("guest_1_on_1_bonus_indicator") or g("guest_2_shot_bonus_indicator"))
        if sport == "baseball":
            for k in ("ball", "strike", "out"):
                s[k + "s"] = str(g(k, ""))
            s["home_hits"], s["guest_hits"] = str(g("home_hits", "")), str(g("guest_hits", ""))
            s["home_errors"], s["guest_errors"] = str(g("home_errors", "")), str(g("guest_errors", ""))
        return s


# --------------------------------------------------------------------------- multi-vendor contracts -> output fields
def _snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and (not name[i - 1].isupper() or (i + 1 < len(name) and name[i + 1].islower())):
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


class Data(dict):
    """Output fields plus `raw_keys`: fields that aren't used by the sport's graphics (raw RTD/contract fields).
    The dashboard shows everything; data.json/xml/csv and text files leave raw_keys out by default."""
    raw_keys: frozenset = frozenset()

    def copy(self):
        d = Data(self)
        d.raw_keys = self.raw_keys
        return d

    def public(self) -> dict:
        return {k: v for k, v in self.items() if k not in self.raw_keys}


def contract_to_data(contract: str, c: dict) -> dict:
    """ScoreReader output fields for a brand decoder's contract (scoreboards.contracts.flat), with a plain
    snake_case fallback so data still flows if the contracts module can't handle this contract."""
    try:
        from scoreboards import contracts

        full, raw = contracts.flat(contract, c, _split=True)
        if isinstance(full, dict):
            d = Data(full)
            d.raw_keys = frozenset(raw)
            return d
    except Exception as e:
        if not getattr(contract_to_data, "_warned", False):
            contract_to_data._warned = True
            log(f"Output mapping for {contract} unavailable ({e}); showing raw contract fields")
    d = {_snake(k): (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in c.items()}
    d.setdefault("sport", str(c.get("EventId", "")).lower())
    return d


RTD_CONTRACTS = {"basketball": ("Basketball", "Basketball"), "baseball": ("BaseballSoftball", "Baseball"),
                 "softball": ("BaseballSoftball", "Softball"), "hockey_lacrosse": ("HockeyLacrosse", "Hockey"),
                 "hockey": ("HockeyLacrosse", "Hockey"), "lacrosse": ("HockeyLacrosse", "Lacrosse"),
                 "volleyball": ("Volleyball", "Volleyball")}


def rtd_contract(sport: str, d: dict):
    """(contract, dict) for MQTT from the built-in RTD decoder's fields, for sports other than football/soccer
    (those keep build_payloads). Only sets fields the sport's Sportzcast contract has. None if not mapped."""
    if sport not in RTD_CONTRACTS:
        return None
    name, event = RTD_CONTRACTS[sport]

    def digits(v, n):
        t = str(v if v is not None else "").strip()
        return list(t.rjust(n)[-n:])

    c = {"EventId": event, "InternalClockStatus": "R" if d.get("clock_running") else "S"}
    clock = str(d.get("clock", "")).strip()
    if "." in clock and ":" not in clock:
        sec, t = clock.split(".", 1)
        st, so = digits(sec, 2)
        c.update(ClockMode=".", ClockSecondTens=st, ClockSecondOnes=so, ClockTenthsSecond=(t[:1] or "0"))
    elif ":" in clock:
        m, sec = clock.split(":", 1)
        mt, mo = digits(m, 2)
        st, so = digits(sec.rjust(2, "0"), 2)
        c.update(ClockMode=":", ClockMinutesTens=mt, ClockMinutesOnes=mo, ClockSecondTens=st, ClockSecondOnes=so)
    period = str(d.get("period", "")).strip()[-1:] or " "
    if name == "BaseballSoftball":
        for side, run in (("Home", "home_score"), ("Guest", "guest_score")):
            c[f"{side}RunTens"], c[f"{side}RunOnes"] = digits(d.get(run), 2)
            c[f"{side}HitsTens"], c[f"{side}HitsOnes"] = digits(d.get(f"{side.lower()}_hits"), 2)
            c[f"{side}Errors"] = (str(d.get(f"{side.lower()}_errors", "")).strip()[-1:] or " ")
        c["InningTens"], c["InningOnes"] = digits(d.get("period"), 2)
        for k in ("balls", "strikes", "outs"):
            c[k.capitalize()] = str(d.get(k, "")).strip()[-1:] or " "
    else:
        width = 3 if name == "Basketball" else 2
        for side in ("Home", "Guest"):
            ds = digits(d.get(f"{side.lower()}_score"), width)
            if width == 3:
                c[f"{side}ScoreHundreds"] = ds.pop(0)
            c[f"{side}ScoreTens"], c[f"{side}ScoreOnes"] = ds
            c[f"{side}Timeouts"] = str(d.get(f"{side.lower()}_timeouts", "")).strip()[-1:] or " "
            c[f"{side}Possession"] = ("<" if side == "Home" else ">") if d.get(f"{side.lower()}_poss") else " "
        c["Period"] = period
        if name == "Basketball":
            for side in ("Home", "Guest"):
                c[f"{side}FoulTens"], c[f"{side}FoulOnes"] = digits(d.get(f"{side.lower()}_fouls"), 2)
            c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = digits(d.get("shot_clock"), 2)
    try:
        from scoreboards import contracts

        allowed = {p[0] for p in contracts._spec(name).props} | set(contracts._BASE_CHARS) | {
            "EventId", "InternalClockStatus", "ClockMode"}
        c = {k: v for k, v in c.items() if k in allowed}
    except Exception:
        return None
    return name, c


# --------------------------------------------------------------------------- Windows HID (no hidapi needed)
class WinHID:
    """Talk to a HID device on Windows using only built-in DLLs (hid.dll / setupapi / kernel32)."""

    def __init__(self, vid: int, pid: int):
        import ctypes
        from ctypes import wintypes as wt

        self.ct, self.wt = ctypes, wt
        hid = ctypes.WinDLL("hid")
        sa = ctypes.WinDLL("setupapi", use_last_error=True)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.hid, self.k32 = hid, k32

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

        class IFDATA(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wt.DWORD),
                        ("Reserved", ctypes.c_size_t)]

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                        ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]

        self.OVERLAPPED = OVERLAPPED
        guid = GUID()
        hid.HidD_GetHidGuid(ctypes.byref(guid))
        sa.SetupDiGetClassDevsW.restype = wt.HANDLE
        sa.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
        sa.SetupDiEnumDeviceInterfaces.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD,
                                                   ctypes.POINTER(IFDATA)]
        sa.SetupDiGetDeviceInterfaceDetailW.argtypes = [wt.HANDLE, ctypes.POINTER(IFDATA), ctypes.c_void_p,
                                                        wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
        sa.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
        k32.CreateFileW.restype = wt.HANDLE
        k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
        k32.CreateEventW.restype = wt.HANDLE
        k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        for fn in ("ReadFile", "WriteFile"):
            getattr(k32, fn).argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                         ctypes.POINTER(OVERLAPPED)]
        k32.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wt.DWORD), wt.BOOL]
        k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
        k32.WaitForSingleObject.restype = wt.DWORD
        k32.CancelIo.argtypes = [wt.HANDLE]
        k32.CloseHandle.argtypes = [wt.HANDLE]
        hid.HidD_FlushQueue.argtypes = [wt.HANDLE]

        want = f"vid_{vid:04x}&pid_{pid:04x}"
        hdev = sa.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, 0x02 | 0x10)  # PRESENT | DEVICEINTERFACE
        paths = []
        try:
            i = 0
            while True:
                ifd = IFDATA()
                ifd.cbSize = ctypes.sizeof(IFDATA)
                if not sa.SetupDiEnumDeviceInterfaces(hdev, None, ctypes.byref(guid), i, ctypes.byref(ifd)):
                    break
                i += 1
                need = wt.DWORD(0)
                sa.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
                buf = ctypes.create_string_buffer(need.value + 4)
                ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
                if sa.SetupDiGetDeviceInterfaceDetailW(hdev, ctypes.byref(ifd), buf, need.value + 4, None, None):
                    path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                    if want in path.lower():
                        paths.append(path)
        finally:
            sa.SetupDiDestroyDeviceInfoList(hdev)
        if not paths:
            raise RuntimeError("ScoreLinkII HID interface not found in Windows (is the bot plugged in?)")
        GENERIC_RW, SHARE_RW, OPEN_EXISTING, OVERLAPPED_FLAG = 0xC0000000, 0x3, 3, 0x40000000
        self.h = k32.CreateFileW(paths[0], GENERIC_RW, SHARE_RW, None, OPEN_EXISTING, OVERLAPPED_FLAG, None)
        if self.h in (None, 0, ctypes.c_void_p(-1).value):
            raise OSError(f"Could not open ScoreLinkII HID (error {ctypes.get_last_error()})")
        self.event = k32.CreateEventW(None, True, False, None)

    def _io(self, fn, buf, n, timeout_ms):
        ct, wt, k32 = self.ct, self.wt, self.k32
        ov = self.OVERLAPPED()
        ov.hEvent = self.event
        done = wt.DWORD(0)
        ok = fn(self.h, buf, n, ct.byref(done), ct.byref(ov))
        if not ok:
            err = ct.get_last_error()
            if err != 997:  # ERROR_IO_PENDING
                raise OSError(f"HID I/O error {err}")
            if k32.WaitForSingleObject(self.event, timeout_ms) != 0:
                k32.CancelIo(self.h)
                raise IOError("HID I/O timed out")
            if not k32.GetOverlappedResult(self.h, ct.byref(ov), ct.byref(done), False):
                raise OSError(f"HID I/O error {ct.get_last_error()}")
        return done.value

    def write(self, data):
        buf = self.ct.create_string_buffer(bytes(data), 65)
        self._io(self.k32.WriteFile, buf, 65, 1000)

    def read(self, n=64, timeout_ms=1000):
        buf = self.ct.create_string_buffer(65)
        got = self._io(self.k32.ReadFile, buf, 65, timeout_ms)
        return list(buf.raw[1:got])  # drop report id

    def flush(self):
        self.hid.HidD_FlushQueue(self.h)

    def close(self):
        self.k32.CloseHandle(self.event)
        self.k32.CloseHandle(self.h)

# --------------------------------------------------------------------------- MCP2221 (ScoreLinkII) GPIO
class MCP2221:
    """Minimal MCP2221 HID driver: just enough to drive GP2 (ScoreLinkII mode select)."""

    def __init__(self):
        self.flush = lambda: None
        if sys.platform == "win32":  # built-in Windows HID, no extra packages
            w = WinHID(SCORELINK_VID, SCORELINK_PID)
            self.dev = w
            self._write = w.write
            self._read = lambda: w.read(64, 1000)
            self.flush = w.flush
            return
        import hid  # mac/linux: pip install hidapi

        devs = [d for d in hid.enumerate(SCORELINK_VID, SCORELINK_PID)]
        if not devs:
            raise RuntimeError("MCP2221 HID interface not found (is the ScoreBot plugged in?)")
        path = devs[0]["path"]
        if hasattr(hid, "device"):  # cython-hidapi ("hidapi" on PyPI)
            self.dev = hid.device()
            self.dev.open_path(path)
            self._write = lambda b: self.dev.write(b)
            self._read = lambda: self.dev.read(64, 1000)
        else:  # "hid" ctypes package
            self.dev = hid.Device(path=path)
            self._write = lambda b: self.dev.write(bytes(b))
            self._read = lambda: list(self.dev.read(64, 1000))

    def cmd(self, payload: list[int]) -> list[int]:
        buf = [0] * 64
        buf[: len(payload)] = payload
        self.flush()
        self._write([0x00] + buf)  # report id 0
        resp = self._read()
        if not resp or resp[0] != payload[0]:
            raise IOError(f"MCP2221 bad response to 0x{payload[0]:02X}: {resp[:8] if resp else resp}")
        return resp

    def get_gp2(self):
        r = self.cmd([0x51])
        return r[6], r[7]  # value, direction (0xEE = pin not in GPIO mode)

    def set_gp2(self, high: bool):
        val, direction = self.get_gp2()
        if val == 0xEE or direction != 0:
            # pin not configured as GPIO output -> read-modify-write SRAM GP settings
            sram = self.cmd([0x61])
            gp = list(sram[22:26])
            gp[2] = (0x10 if high else 0x00)  # bit4 value, bit3 dir(0=out), bits2:0 = 000 GPIO
            self.cmd([0x60, 0, 0, 0, 0, 0, 0, 0x80] + gp)
        # Set GPIO output values: GP2 block = bytes 10..13 (alter out, value, alter dir, dir)
        p = [0x50, 0] + [0] * 16
        p[10:14] = [0xFF, 1 if high else 0, 0xFF, 0]
        self.cmd(p)

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- sources
def list_serial_ports():
    from serial.tools import list_ports

    return list(list_ports.comports())


def find_scorelink_port() -> str | None:
    for p in list_serial_ports():
        if p.vid == SCORELINK_VID and p.pid == SCORELINK_PID:
            return p.device
    for p in list_serial_ports():
        txt = f"{p.description} {p.manufacturer} {p.product}".lower()
        if "scorelink" in txt or "mcp2221" in txt:
            return p.device
    return None


def resolve_port(cfg) -> str:
    port = cfg.get("port", "auto")
    if port and port != "auto":
        return port
    p = find_scorelink_port()
    if p:
        return p
    ports = [p.device for p in list_serial_ports() if "bluetooth" not in p.device.lower()]
    if len(ports) == 1:
        return ports[0]
    raise RuntimeError(
        "Could not auto-detect the ScoreBot COM port. Ports seen: "
        + (", ".join(ports) or "none")
        + ". Set \"port\" in scorereader_config.json or pass --port COMx"
    )


def pic_command(ser, cmd: str, timeout=0.6) -> str:
    """Send '>XX\\r' to the ScoreLinkII PIC (command mode) and return the CR-terminated reply."""
    if not cmd.startswith(">"):
        cmd = ">" + cmd
    ser.reset_input_buffer()
    ser.write((cmd + "\r").encode("ascii"))
    ser.flush()
    deadline = time.time() + timeout
    resp = bytearray()
    while time.time() < deadline:
        b = ser.read(1)
        if not b:
            continue
        if b == b"\r":
            if resp:
                break
            continue
        resp += b
    text = resp.decode("latin-1", "replace").strip()
    if ">" in text:
        text = text[text.index(">") + 1 :]
    return text


def _readback(cmd: str) -> tuple:
    """(query, verify) for a PIC write, the way ScoreConnect checks it (falls back to a simple check)."""
    try:
        from scoreboards import hardware

        return hardware.readback_query(cmd), lambda reply: hardware.verify_reply(cmd, reply)
    except Exception:
        q = cmd[:3] + "?" if cmd.startswith(">M") else cmd[:2] + "?"
        return q, lambda reply: bool(reply)


def scorelink_session(cfg, ser, mcp, send_config: bool, probe: bool, commands=None, data_baud=None) -> dict:
    """Enter command mode, query/configure the PIC, return to data mode. Returns info dict.

    commands/data_baud: the brand's bot configuration (from scoreboards.hardware); default = the configured
    scorelink.config_commands at cfg["baud"] (Daktronics current loop, 19200).
    """
    sl = cfg["scorelink"]
    commands = list(commands if commands is not None else sl["config_commands"])
    data_baud = int(data_baud or cfg["baud"])
    info = {}
    if mcp is None:
        log("ScoreLink: no GPIO control available -> skipping PIC command mode")
        return info
    mcp.set_gp2(False)  # command mode
    time.sleep(0.05)
    ser.baudrate = sl["command_baud"]
    time.sleep(0.05)
    ser.reset_input_buffer()
    try:
        if probe or send_config:
            for q in ("R?", "B?", "U?", "M?", "T?", "D?", "M8?"):
                r = pic_command(ser, ">" + q)
                info[q] = r
                log(f"PIC {q:4} -> {r or '(no reply)'}")
        if send_config:
            ok = True
            for c in commands:
                query, verify = _readback(c)
                for attempt in range(10 if c.startswith(">M") else 4):  # ScoreConnect's retry counts
                    pic_command(ser, c)
                    time.sleep(0.3)  # PIC writes EEPROM
                    r = pic_command(ser, query)
                    if verify(r):
                        break
                else:
                    ok = False
                log(f"PIC set {c} -> readback {r or '(no reply)'}" + ("" if verify(r) else "  (NOT CONFIRMED)"))
            info["configured"] = ok
    finally:
        mcp.set_gp2(True)  # data mode
        time.sleep(0.05)
        ser.baudrate = data_baud
        time.sleep(0.05)
        ser.reset_input_buffer()
    STATUS.pic_info = info
    return info


class Reader(threading.Thread):
    def __init__(self, cfg, decoder: DaktronicsRTD, stop: threading.Event, cl=None, vendor=None, bot=None):
        """vendor: a scoreboards Protocol for the chosen brand/sport (None = built-in Daktronics decoders).
        bot: the ScoreBot set-up for that brand, see App.bot_plan()."""
        super().__init__(daemon=True)
        self.cfg, self.decoder, self.stop = cfg, decoder, stop
        self.cl = cl
        self.vendor = vendor
        self.bot = bot or {}
        self.cl_other = None  # ScoreConnect's Daktronics autodetect, for console codes other than 6601/7601
        self.raw_file = None
        self.reinit_request = threading.Event()
        self.raw_sink: queue.Queue | None = None  # for --sniff
        self.raw_hook = None  # e.g. MQTT bot/N/raw

    def _feed(self, data: bytes):
        if self.raw_hook is not None:
            self.raw_hook(data)
        if self.vendor is not None:
            n = self.vendor.feed(data)
            if n:
                STATUS.packets += n
                STATUS.last_packet_time = time.time()
            return
        if self.cl is not None:
            self.cl.feed(data)
            if self.cl_other is not None:
                self.cl_other.feed(data)
            if self.cl.packets > 20:
                return  # current-loop stream confirmed: RTD decoder would only see noise
        self.decoder.feed(data)

    def _record(self, data: bytes):
        if self.raw_sink is not None:
            self.raw_sink.put(data)
        STATUS.bytes_in += len(data)
        STATUS.last_byte_time = time.time()
        STATUS.recent_hex = (STATUS.recent_hex + data.hex(" ") + " ")[-600:]
        if self.cfg.get("record_raw"):
            if self.raw_file is None:
                os.makedirs(LOG_DIR, exist_ok=True)
                fn = os.path.join(LOG_DIR, f"raw_{_dt.datetime.now():%Y%m%d_%H%M%S}.bin")
                self.raw_file = open(fn, "ab")
            self.raw_file.write(data)
            self.raw_file.flush()

    def run(self):
        src = self.cfg["source"]
        try:
            while not self.stop.is_set():
                try:
                    if src == "demo":
                        self.run_demo()
                    elif src == "replay":
                        self.run_replay()
                    elif src == "tcp":
                        self.run_tcp()
                    else:
                        self.run_serial(scorelink=(src == "scorelink"))
                except Exception as e:
                    if self.stop.is_set():
                        break
                    msg = str(e)
                    if "Access is denied" in msg or "PermissionError" in repr(e) or "busy" in msg.lower():
                        msg += "  -> The port is in use. Quit ScoreConnect III AND stop its Windows service " \
                               "(admin cmd: net stop ScoreConnectIII), then this will retry automatically."
                    STATUS.set_source("error", msg)
                    log(f"Source error: {msg}")
                    if os.environ.get("SCOREREADER_DEBUG"):
                        traceback.print_exc()
                self.stop.wait(3)
        finally:
            if self.raw_file is not None:
                try:
                    self.raw_file.close()
                except OSError:
                    pass
                self.raw_file = None

    def run_serial(self, scorelink: bool):
        import serial

        port = resolve_port(self.cfg)
        STATUS.set_source("connecting", port)
        mcp = None
        if scorelink and self.cfg["scorelink"].get("use_gpio_mode_switch", True):
            try:
                mcp = MCP2221()
            except ImportError:
                log("hidapi not installed -> can't switch ScoreLinkII modes (Mac/Linux: pip install hidapi)")
            except Exception as e:
                log(f"MCP2221 GPIO unavailable: {e}")
        bot = self.bot
        baud = int(bot.get("baud") or self.cfg["baud"]) if scorelink else int(self.cfg["baud"])
        ser = serial.Serial(port, baud, bytesize=8, parity="N", stopbits=1, timeout=0.2)

        def session(configure: bool):
            info = scorelink_session(self.cfg, ser, mcp, configure, configure or sl.get("probe_on_start", True),
                                     commands=bot.get("commands"), data_baud=baud)
            if configure and info.get("configured") and bot.get("on_configured"):
                bot["on_configured"]()
            return info

        try:
            log(f"Opened {port}")
            sl = self.cfg["scorelink"]
            if scorelink and bot.get("note"):
                log(bot["note"])
            if scorelink and mcp is not None:
                configure = bool(sl.get("send_config_on_start", False) or bot.get("configure"))
                if bot.get("configure"):
                    log(f"Configuring the ScoreBot for {bot.get('label', 'this scoreboard')}")
                session(configure)
                log(f"ScoreLinkII in DATA mode, reading at {baud} baud")
            STATUS.set_source("connected", f"{port} @ {baud}")
            while not self.stop.is_set():
                if self.reinit_request.is_set():
                    self.reinit_request.clear()
                    if scorelink and mcp is not None:
                        session(True)
                data = ser.read(4096)
                if data:
                    self._record(data)
                    self._feed(data)
        finally:
            ser.close()
            if mcp:
                mcp.close()

    def run_replay(self):
        path = self.cfg.get("replay_file") or ""
        if not path:
            raise RuntimeError("No capture chosen to replay (pick one in Settings, or pass --replay FILE)")
        if not os.path.isabs(path) and not os.path.exists(path):
            path = os.path.join(LOG_DIR, path)  # dashboard picks a file name from logs/
        STATUS.set_source("connected", f"REPLAY {os.path.basename(path)}")
        with open(path, "rb") as f:
            raw = f.read()
        log(f"Replaying {len(raw)} bytes from {path} (~19200 baud speed)")
        for i in range(0, len(raw), 192):
            if self.stop.is_set():
                return
            chunk = raw[i : i + 192]
            STATUS.bytes_in += len(chunk)
            self._feed(chunk)
            time.sleep(0.1 / self.cfg.get("replay_speed", 1))
        log("Replay finished")
        self.stop.wait(3600)

    def run_tcp(self):  # noqa
        host, port = self.cfg["tcp"]["host"], int(self.cfg["tcp"]["port"])
        STATUS.set_source("connecting", f"{host}:{port}")
        with socket.create_connection((host, port), timeout=5) as s:
            s.settimeout(1)
            STATUS.set_source("connected", f"tcp {host}:{port}")
            while not self.stop.is_set():
                try:
                    data = s.recv(4096)
                except socket.timeout:
                    continue
                if not data:
                    raise ConnectionError("TCP source closed")
                self._record(data)
                self._feed(data)

    def run_demo(self):
        STATUS.set_source("connected", "DEMO simulator (fake football game)")
        log("DEMO mode: generating a fake Daktronics football stream")
        clock = 12 * 60
        play = 40
        home = guest = 0
        q = 1
        pos_home = True
        down, togo, ball = 1, 10, 25
        last_play = time.time()
        while not self.stop.is_set():
            pk = b""

            def put(pos, length, text, right=False):  # pos is 1-based, like the Daktronics manual
                t = str(text)
                t = t.rjust(length) if right else t.ljust(length)
                return encode_rtd_packet(pos - 1, t[:length])

            m, s = divmod(clock, 60)
            pk += put(1, 5, f"{m:2d}:{s:02d}")
            pk += put(201, 8, play, right=True)
            if time.time() - last_play > 6:
                last_play = time.time()
                if random.random() < 0.15:
                    if pos_home:
                        home += 7
                    else:
                        guest += 3
                    pos_home = not pos_home
                    down, togo, ball = 1, 10, 25
                else:
                    gain = random.randint(-2, 12)
                    togo -= gain
                    ball = max(1, min(49, ball + gain))
                    down = 1 if togo <= 0 else down + 1
                    togo = 10 if togo <= 0 else togo
                    if down > 4:
                        pos_home, down, togo = not pos_home, 1, 10
                play = 40
            pk += put(48, 20, "HOME TEAM") + put(68, 20, "VISITORS")
            pk += put(88, 10, "HOME") + put(98, 10, "VIS")
            pk += put(108, 4, home, right=True) + put(112, 4, guest, right=True)
            pk += put(122, 2, 3, right=True) + put(130, 2, 2, right=True)
            pk += put(142, 2, q, right=True)
            pk += put(210, 1, "<" if pos_home else " ") + put(215, 1, ">" if not pos_home else " ")
            dtxt = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}[min(down, 4)]
            pk += put(220, 2, ball, right=True) + put(222, 3, dtxt) + put(225, 2, togo, right=True)
            # simulate serial chunking
            for i in range(0, len(pk), 37):
                chunk = pk[i : i + 37]
                self._record(chunk)
                self._feed(chunk)
            time.sleep(1.0)
            clock = clock - 1 if clock > 0 else 12 * 60
            play = play - 1 if play > 0 else 40
            if clock == 0:
                q = q % 4 + 1


# --------------------------------------------------------------------------- outputs
class VmixPusher(threading.Thread):
    def __init__(self, cfg, stop):
        super().__init__(daemon=True)
        self.cfg, self.stop = cfg, stop
        self.q: queue.Queue = queue.Queue()
        self.last_sent: dict = {}
        self.sock = None

    def submit(self, data: dict):
        self.q.put(data)

    def _commands(self, data: dict):
        v = self.cfg["vmix"]
        inp = urllib.parse.quote(str(v["input"]))
        for field, target in v.get("fields", {}).items():
            if field not in data:
                continue
            val = data[field]
            if isinstance(target, dict):
                name = target.get("name", "")
                if target.get("visible"):
                    kind = "Image" if name.endswith(".Source") else "Text"
                    fn = f"Set{kind}Visible{'On' if val else 'Off'}"
                    yield (field, fn, f"Input={inp}&SelectedName={urllib.parse.quote(name)}", bool(val))
                    continue
                if isinstance(val, bool):
                    val = target.get("true", "1") if val else target.get("false", "")
            else:
                name = target
                if isinstance(val, bool):
                    val = "1" if val else ""
            yield (field, "SetText",
                   f"Input={inp}&SelectedName={urllib.parse.quote(name)}&Value={urllib.parse.quote(str(val))}",
                   str(val))

    def _connect(self):
        v = self.cfg["vmix"]
        s = socket.create_connection((v["host"], int(v["port"])), timeout=3)
        s.settimeout(None)
        threading.Thread(target=self._drain, args=(s,), daemon=True).start()
        self.sock = s
        self.last_sent.clear()  # full refresh after (re)connect
        STATUS.vmix_state = f"connected {v['host']}:{v['port']}"
        log(f"vMix TCP API connected ({v['host']}:{v['port']}) -> input '{v['input']}'")

    @staticmethod
    def _drain(s):
        try:
            while s.recv(4096):
                pass
        except OSError:
            pass

    def _close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def run(self):
        latest = None
        while not self.stop.is_set():
            try:
                latest = self.q.get(timeout=0.5)
                while not self.q.empty():
                    latest = self.q.get_nowait()
            except queue.Empty:
                pass
            if latest is None or self.stop.is_set():
                continue
            try:
                if self.sock is None:
                    self._connect()
                for field, fn, query, key in self._commands(latest):
                    if self.last_sent.get(field) == key:
                        continue
                    self.sock.sendall(f"FUNCTION {fn} {query}\r\n".encode("utf-8"))
                    self.last_sent[field] = key
            except OSError as e:
                STATUS.vmix_state = f"error: {e} (retrying)"
                self._close()
                self.stop.wait(2)
        self._close()


def write_text_files(folder: str, data: dict, cache: dict):
    os.makedirs(folder, exist_ok=True)
    for k, v in data.items():
        sv = ("1" if v else "") if isinstance(v, bool) else str(v)
        if cache.get(k) != sv:
            with open(os.path.join(folder, f"{k}.txt"), "w", encoding="utf-8") as f:
                f.write(sv)
            cache[k] = sv


# --------------------------------------------------------------------------- web server
DASHBOARD_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>ScoreReader</title>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0e1116;--card:#171b22;--ink:#e8ecf1;--mut:#8a94a3;--ok:#2fbf71;--bad:#e5484d;--warn:#f5a524;--acc:#5b8def}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,Segoe UI,sans-serif}
header{display:flex;gap:16px;align-items:center;padding:12px 18px;border-bottom:1px solid #222a35;flex-wrap:wrap}
h1{font-size:18px;margin:0}.pill{padding:3px 10px;border-radius:99px;background:#222a35;font-size:12px}
.ok{background:rgba(47,191,113,.18);color:var(--ok)}.bad{background:rgba(229,72,77,.18);color:var(--bad)}.warn{background:rgba(245,165,36,.18);color:var(--warn)}
main{padding:16px 18px;display:grid;gap:16px}
.card{background:var(--card);border:1px solid #222a35;border-radius:10px;padding:14px}
.bug{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;align-items:center;text-align:center}
.team{font-size:15px;color:var(--mut)}.score{font:700 64px/1 ui-monospace,Consolas,monospace}
.mid .clock{font:700 48px/1 ui-monospace,Consolas,monospace}.mid .sub{color:var(--mut);margin-top:6px;font-size:15px}
.poss{color:var(--warn);font-weight:700}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:3px 6px;border-bottom:1px solid #222a35;text-align:left}
th{color:var(--mut);font-weight:500}td.v{font-family:ui-monospace,Consolas,monospace}
.grid{font:12px/1.2 ui-monospace,Consolas,monospace;overflow:auto}
.row{display:flex;white-space:pre}.row .n{width:46px;color:var(--mut)}.c{width:13px;text-align:center;border-left:1px solid #1d232c}
.c.hot{background:var(--acc);color:#fff}.c.warm{background:rgba(91,141,239,.3)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:900px){.cols{grid-template-columns:1fr}}
pre{margin:0;max-height:220px;overflow:auto;font-size:12px;color:var(--mut);white-space:pre-wrap}
select,button,input{background:#222a35;color:var(--ink);border:1px solid #333d4b;border-radius:6px;padding:5px 9px}
button{cursor:pointer}a{color:var(--acc)}.mut{color:var(--mut)}
.banner{background:var(--warn);color:#111;padding:10px 18px;font-weight:600;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.banner[hidden],#settings[hidden]{display:none}.banner button{background:#111;color:#fff;border-color:#111}
.tbar{height:4px;width:60px;margin:6px auto 0;border-radius:2px}
#settings{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;justify-content:flex-end;z-index:10}
#settings .panel{background:var(--card);width:min(560px,100%);height:100%;overflow:auto;padding:16px 18px;border-left:1px solid #222a35}
#settings h2{font-size:17px;margin:0 0 4px}fieldset{border:1px solid #222a35;border-radius:8px;margin:0 0 14px;padding:8px 12px}
legend{color:var(--mut);padding:0 6px}label.set{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;padding:5px 0}
label.set[hidden]{display:none}label.set input:not([type=checkbox]),label.set select{width:230px;max-width:52vw}
.colr{display:flex;gap:6px}.colr input[type=color]{width:34px!important;padding:0;height:30px}
.setbar{position:sticky;bottom:-16px;background:var(--card);padding:12px 0;display:flex;gap:10px;align-items:center;border-top:1px solid #222a35}
.primary{background:var(--acc);border-color:var(--acc);color:#fff}#setmsg{flex:1;font-size:13px}#setmsg.bad{background:none}
</style></head><body>
<header><h1>ScoreReader</h1><span id="src" class="pill">…</span><span id="age" class="pill">…</span><span id="vmix" class="pill">vMix</span><span id="mqtt" class="pill">MQTT</span>
<span class="mut" id="stats"></span><span style="flex:1"></span>
<label class="mut">Sport <select id="sport"></select></label>
<button onclick="reinit()" title="Re-run ScoreLinkII probe + config">Re-init bot</button>
<button onclick="openSettings()">Settings</button>
<a href="/data.json" target="_blank">data.json</a><a href="/data.xml" target="_blank">data.xml</a></header>
<div class="banner" id="demo" hidden><span id="demotxt"></span><button onclick="goLive()">Back to live data</button></div>
<div id="settings" hidden onclick="if(event.target===this)closeSettings()"><div class="panel">
 <h2>Settings</h2><p class="mut" style="margin:0 0 12px">Saved to <span id="cfgpath"></span>. Demo and replay are never saved: ScoreReader always starts with live data.</p>
 <div id="setform"></div><datalist id="portlist"></datalist>
 <div class="setbar"><button class="primary" onclick="saveSettings()">Save</button><button onclick="closeSettings()">Close</button><span id="setmsg" class="mut"></span></div>
</div></div>
<main>
<div class="card bug">
 <div><div class="team" id="hn">HOME</div><div class="tbar" id="hc"></div><div class="score" id="hs">0</div><div class="poss" id="hp"></div></div>
 <div class="mid"><div class="clock" id="clk">--:--</div><div class="sub" id="sub"></div></div>
 <div><div class="team" id="gn">GUEST</div><div class="tbar" id="gc"></div><div class="score" id="gs">0</div><div class="poss" id="gp"></div></div>
</div>
<div class="cols">
 <div class="card"><b>Fields</b> <span class="mut">(names = keys in data.json)</span>
   <input id="flt" placeholder="filter…" style="float:right"><table id="ft"></table></div>
 <div class="card"><b id="ptitle">Raw data</b><div id="cltab"></div><div class="grid" id="grid"></div>
   <br><b>Log</b><pre id="log"></pre><br><b>Last bytes (hex)</b><pre id="hex"></pre></div>
</div></main>
<script>
let fieldsMeta=[];const H={'X-ScoreReader':'1'};
const esc=v=>String(v??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
async function reinit(){await fetch('/api/reinit',{method:'POST',headers:H});}
document.getElementById('sport').onchange=async e=>{await fetch('/api/sport?name='+encodeURIComponent(e.target.value),{method:'POST',headers:H});fieldsMeta=[];};
async function postSettings(ch){const r=await fetch('/api/settings',{method:'POST',headers:{...H,'Content-Type':'application/json'},body:JSON.stringify(ch)});return r.json();}
async function goLive(){await postSettings({source:window._live||'scorelink'});}
const SRC={scorelink:'ScoreBot / ScoreLinkII (USB)',serial:'Serial cable to the console',tcp:'Network serial server (TCP)',
 demo:'Demo: simulated game (not saved)',replay:'Replay a capture (not saved)'};
let S=null;
async function openSettings(){S=await (await fetch('/api/settings')).json();renderSettings();document.getElementById('settings').hidden=false;}
function closeSettings(){document.getElementById('settings').hidden=true;}
function sid(p){return 'set_'+p.replace(/\./g,'_');}
function brandOf(pid){for(const b of S.scoreboards)if(b.sports.some(x=>x.id==pid))return b;return null;}
function sbPicker(){const pid=S.values['scoreboard.protocol']||'',b=brandOf(pid);
 let h=`<label class="set"><span>Scoreboard brand</span><select id="sb_brand" onchange="sbBrand()"><option value="">Daktronics All Sport 5000 (built-in, automatic)</option>`+
  S.scoreboards.map(x=>`<option ${b&&b.name==x.name?'selected':''}>${esc(x.name)}</option>`).join('')+'</select></label>';
 h+=`<label class="set" id="sb_sport_l"><span>Sport / console layout</span><select id="${sid('scoreboard.protocol')}" onchange="showFor()"></select></label>`;
 h+=`<label class="set" id="sb_conn_l"><span>Wiring</span><select id="${sid('scoreboard.connection')}"></select></label>`;return h;}
function sbBrand(keep){const bn=document.getElementById('sb_brand').value,b=S.scoreboards.find(x=>x.name==bn);
 const sp=document.getElementById(sid('scoreboard.protocol')),cn=document.getElementById(sid('scoreboard.connection'));
 sp.innerHTML=b?b.sports.map(x=>`<option value="${esc(x.id)}">${esc(x.description)}</option>`).join(''):'<option value=""></option>';
 cn.innerHTML=b?b.connections.map((c,i)=>`<option value="${i}">${esc(c)}</option>`).join(''):'<option value="0"></option>';
 if(keep){sp.value=S.values['scoreboard.protocol']||'';cn.value=String(S.values['scoreboard.connection']||0);}
 document.getElementById('sb_sport_l').hidden=!b;document.getElementById('sb_conn_l').hidden=!b||b.connections.length<2;showFor();}
function inputFor(sp){const v=S.values[sp.path],id=sid(sp.path);
 if(sp.type=='bool')return `<input type="checkbox" id="${id}" ${v?'checked':''}>`;
 if(sp.type=='choice'){const ch=S.choices[sp.path]||[];if(!ch.length)return '<span class="mut">none yet</span>';
  return `<select id="${id}">`+ch.map(c=>`<option value="${esc(c)}" ${c==v?'selected':''}>${esc(sp.path=='source'?(SRC[c]||c):c)}</option>`).join('')+'</select>';}
 if(sp.type=='color')return `<span class="colr"><input type="color" value="${esc(v||'#000000')}" oninput="${id}.value=this.value.toUpperCase()"><input id="${id}" value="${esc(v)}" placeholder="#1E3A8A"></span>`;
 return `<input id="${id}" value="${esc(v)}"${sp.path=='port'?' list="portlist"':''}${sp.type=='int'||sp.type=='port'?' inputmode="numeric"':''}>`;}
const SHOW={port:['scorelink','serial'],baud:['scorelink','serial'],'scorelink.probe_on_start':['scorelink'],
 'scorelink.send_config_on_start':['scorelink'],'tcp.host':['tcp'],'tcp.port':['tcp'],replay_file:['replay']};
function renderSettings(){const groups={};S.spec.forEach(sp=>(groups[sp.group]=groups[sp.group]||[]).push(sp));let h='';
 for(const [g,list] of Object.entries(groups)){h+=`<fieldset><legend>${esc(g)}</legend>`;
  list.forEach(sp=>{if(sp.path=='scoreboard.protocol'){h+=sbPicker();return;}if(sp.path=='scoreboard.connection')return;
   h+=`<label class="set" data-path="${sp.path}"><span>${esc(sp.label)}${sp.apply=='restart'?' <em class="mut">(after restart)</em>':''}</span>${inputFor(sp)}</label>`});
  if(g=='Files')h+=`<p class="mut" style="margin:4px 0">Text files go to ${esc(S.text_folder)}</p>`;h+='</fieldset>';}
 setform.innerHTML=h;cfgpath.textContent=S.config_path;setmsg.textContent='';setmsg.className='mut';
 portlist.innerHTML='<option value="auto">auto-detect</option>'+S.ports.map(p=>`<option value="${esc(p.device)}">${esc(p.description)}${p.scorelink?' (ScoreBot)':''}</option>`).join('');
 const src=document.getElementById(sid('source'));if(src){src.onchange=showFor;}sbBrand(true);}
function showFor(){const src=(document.getElementById(sid('source'))||{}).value,bp=document.getElementById('sb_brand');
 document.querySelectorAll('label.set[data-path]').forEach(l=>{const w=SHOW[l.dataset.path];l.hidden=(!!w&&!w.includes(src))||(l.dataset.path=='sport'&&bp&&bp.value!='');});}
async function saveSettings(){const ch={};
 S.spec.forEach(sp=>{const el=document.getElementById(sid(sp.path));if(!el)return;const lab=el.closest('label');if(lab&&lab.hidden&&sp.path!='source'&&sp.path!='scoreboard.protocol')return;
  let v=sp.type=='bool'?el.checked:el.value;if(sp.path=='scoreboard.protocol'&&document.getElementById('sb_brand').value=='')v='';
  if(String(v)!==String(S.values[sp.path]??''))ch[sp.path]=v;});
 if(!Object.keys(ch).length){setmsg.textContent='Nothing changed.';return;}
 const r=await postSettings(ch);
 if(!r.ok){setmsg.className='bad';setmsg.textContent=Object.values(r.errors).join(' · ');return;}
 S=await (await fetch('/api/settings')).json();renderSettings();
 setmsg.className='';setmsg.textContent='Saved.'+(r.restart_needed.length?' Restart ScoreReader to apply: '+r.restart_needed.join(', '):'');}
async function tick(){
 try{
  const r=await fetch('/api/state');const s=await r.json();
  const sel=document.getElementById('sport');
  if(!sel.options.length){s.sports.forEach(n=>{const o=new Option(n,n);sel.add(o)});}
  sel.value=s.sport;sel.parentElement.style.display=s.vendor_mode?'none':'';
  const src=document.getElementById('src');src.textContent=s.source_state+' — '+s.source_detail;
  src.className='pill '+(s.source_state=='connected'?'ok':(s.source_state=='error'?'bad':'warn'));
  const age=document.getElementById('age');
  if(s.packet_age==null){age.textContent='no packets yet';age.className='pill warn'}
  else{age.textContent='last packet '+s.packet_age.toFixed(1)+'s ago';age.className='pill '+(s.packet_age<5?'ok':'warn')}
  const vm=document.getElementById('vmix');vm.textContent='vMix: '+s.vmix_state;vm.className='pill '+(s.vmix_state.startsWith('connected')?'ok':(s.vmix_state=='disabled'?'':'bad'));
  const mq=document.getElementById('mqtt');mq.textContent='MQTT: '+s.mqtt_state;mq.className='pill '+(s.mqtt_state.startsWith('listening')||s.mqtt_state.startsWith('connected')?'ok':(s.mqtt_state=='disabled'?'':'bad'));
  document.getElementById('stats').textContent=`${s.bytes_in} bytes · ${s.packets} pkts · ${s.bad_packets} bad`+(Object.keys(s.unknown_headers).length?' · unknown hdrs: '+JSON.stringify(s.unknown_headers):'');
  window._live=s.live_source;const dm=document.getElementById('demo');dm.hidden=s.source_saved;
  if(!s.source_saved)demotxt.textContent=s.source=='demo'?'DEMO MODE: simulated game, not the scoreboard':'REPLAY: playing back '+(s.replay_file||'a capture')+', not live data';
  const d=s.data;
  hc.style.background=d.home_color||'transparent';gc.style.background=d.guest_color||'transparent';
  hn.textContent=d.home_name||'HOME';gn.textContent=d.guest_name||'GUEST';hs.textContent=d.home_score;gs.textContent=d.guest_score;
  hp.textContent=d.home_poss?'◀ POSS':'';gp.textContent=d.guest_poss?'POSS ▶':'';
  clk.textContent=d.clock||'--:--';
  let sub=[d.period_ordinal];if(d.play_clock!==undefined)sub.push('Play '+d.play_clock);if(d.shot_clock!==undefined)sub.push('Shot '+d.shot_clock);
  if(d.down_distance)sub.push(d.down_distance+(d.ball_on?' · ball on '+d.ball_on:''));if(d.balls!==undefined)sub.push(`B${d.balls} S${d.strikes} O${d.outs}`);
  if(d.home_shots!==undefined)sub.push(`SOG ${d.home_shots||0}-${d.guest_shots||0}`);if(d.home_corners!==undefined)sub.push(`CK ${d.home_corners||0}-${d.guest_corners||0}`);
  document.getElementById('sub').textContent=sub.filter(Boolean).join('  ·  ');
  const f=document.getElementById('flt').value.toLowerCase();
  let h='<tr><th>key</th><th>value</th><th>pos</th></tr>';
  const meta={};s.fields.forEach(m=>meta[m.name]=m);
  for(const [k,v] of Object.entries(d)){ if(f&&!k.includes(f))continue; const m=meta[k];
   if(m && (v===''||v===false) && !f)continue;
   h+=`<tr><td>${k}</td><td class="v">${String(v).replace(/</g,'&lt;')}</td><td class="mut">${m?m.pos+'+'+m.len:'derived'}</td></tr>`;}
  ft.innerHTML=h;
  const raw=s.raw, ch=s.changed_ago;let g='';const W=50;let last=0;
  for(let i=0;i<raw.length;i++)if(raw[i]!=' ')last=i;
  for(let r=0;r<=last;r+=W){g+=`<div class="row"><span class="n">${r+1}</span>`;
   for(let i=r;i<Math.min(r+W,raw.length);i++){const a=ch[i];const cls=a<1?'hot':(a<10?'warm':'');
    const c=raw[i]==' '?'&nbsp;':raw[i].replace('&','&amp;').replace('<','&lt;');g+=`<span class="c ${cls}" title="pos ${i+1}">${c}</span>`;}
   g+='</div>';}
  if(s.contract&&s.contract.length){grid.innerHTML='';document.getElementById('ptitle').textContent=s.protocol+' — decoded fields';
   cltab.innerHTML='<table><tr><th>field</th><th>value</th></tr>'+s.contract.map(r=>`<tr><td>${esc(r.k)}</td><td class="v">${esc(r.v).replace(/ /g,'·')}</td></tr>`).join('')+'</table>';}
  else if(s.cl_table.length){grid.innerHTML='';document.getElementById('ptitle').textContent=s.protocol+' — addresses';
   let t='<table><tr><th>addr</th><th>len</th><th>7-seg digits</th><th>age</th><th>hex (byte 0, 1, 2 …)</th></tr>';
   s.cl_table.filter(r=>r.addr<0xE0).forEach(r=>{t+=`<tr><td>${r.addr}</td><td>${r.len}</td><td class="v">${r.digits.replace(/ /g,'·')}</td><td class="mut">${r.age}s</td><td class="mut v" style="font-size:11px">${r.hex}</td></tr>`});
   cltab.innerHTML=t+'</table><br>';}
  else{cltab.innerHTML='';document.getElementById('ptitle').textContent='Raw RTD buffer (1-based positions; blue = just changed)';grid.innerHTML=g;}
  log.textContent=s.logs.slice(-60).join('\n');log.scrollTop=1e9;
  document.getElementById('hex').textContent=s.recent_hex;
 }catch(e){document.getElementById('src').textContent='dashboard lost connection';}
}
setInterval(tick,250);tick();
</script></body></html>"""


class App:
    def __init__(self, cfg, saved: dict | None = None):
        """cfg = the running configuration (config file + command-line overrides).
        saved = the configuration as stored in scorereader_config.json. Only explicit changes from the dashboard
        are written back, so options like --demo or --no-mqtt never end up in the file."""
        self.cfg = cfg
        self.saved = saved if saved is not None else json.loads(json.dumps(cfg))
        self.stop = threading.Event()
        self.running = False
        self.gen = 0  # bumped on any settings change, so outputs refresh even if the board hasn't changed
        self.swap_lock = threading.Lock()  # held while the decoders are replaced or read
        self.settings_lock = threading.Lock()
        self.sports = SportMap(FIELDS_PATH)
        if cfg["sport"] not in self.sports.sports:
            log(f"Unknown sport '{cfg['sport']}', using football. Options: {', '.join(self.sports.names())}")
            cfg["sport"] = "football"
        self.decoder, self.cl = self._new_decoders()
        self.mqtt = None
        if cfg.get("mqtt", {}).get("enabled"):
            from sportzcast_mqtt import SportzcastMqttOutput

            self.mqtt = SportzcastMqttOutput(cfg, log=log)
        self.reader = self._new_reader()
        self.vmix = VmixPusher(cfg, threading.Event()) if cfg["vmix"].get("enabled") else None
        self.data: dict = {}
        self.data_lock = threading.Lock()

    # ---- components
    def _new_decoders(self):
        dec = DaktronicsRTD(self.cfg.get("strict_daktronics_header", True))
        cl = DaktronicsCurrentLoop()
        cl.sport_fallback = lambda: self.cfg["sport"]
        cl.custom_fields = lambda: self.cfg.get("custom_fields", {})
        self.vendor = None
        self.cl_other = None
        pid = self.protocol_id()
        if not pid:
            try:
                import scoreboards

                self.cl_other = scoreboards.create("Daktronics_Autodetect")
            except Exception:
                self.cl_other = None
        if pid:
            try:
                import scoreboards

                self.vendor = scoreboards.create(pid)
                log(f"Scoreboard: {self.protocol_label()}")
            except Exception as e:
                log(f"Scoreboard '{pid}' is not available ({e}); using the built-in Daktronics decoders")
        return dec, cl

    def protocol_id(self) -> str:
        return str(get_path(self.cfg, "scoreboard.protocol", "") or "")

    def protocol_label(self) -> str:
        pid = self.protocol_id()
        if not pid:
            return "Daktronics All Sport 5000 (built-in)"
        try:
            import scoreboards

            vs = scoreboards.vendor_sport(pid) or {}
            return vs.get("description") or pid
        except Exception:
            return pid

    def bot_plan(self) -> dict:
        """How to set up the ScoreBot for the chosen brand and wiring (built-in Daktronics: the config file's
        scorelink.config_commands at cfg["baud"], sent only when asked, exactly as before)."""
        pid = self.protocol_id()
        if not pid or self.vendor is None:
            # Built-in Daktronics: if another brand reconfigured the bot, put the Daktronics set-up back once.
            last = str(get_path(self.cfg, "scorelink.configured_for", "") or "")
            if last and last != BUILTIN_BOT_KEY:
                return {"label": "Daktronics All Sport 5000 (built-in)", "commands": None, "baud": None,
                        "configure": True, "on_configured": self._remember_bot(BUILTIN_BOT_KEY)}
            return {}
        try:
            import scoreboards
            from scoreboards import hardware

            vs = scoreboards.vendor_sport(pid) or {}
            configs = hardware.configs_for_vendor(vs.get("vendor", ""))
        except Exception as e:
            return {"note": f"No bot set-up known for {pid} ({e}); reading at {self.cfg['baud']} baud"}
        if not configs:
            return {"note": f"No wiring known for {pid}; reading at {self.cfg['baud']} baud"}
        idx = int(get_path(self.cfg, "scoreboard.connection", 0) or 0)
        vc = configs[idx] if 0 <= idx < len(configs) else configs[0]
        label = f"{self.protocol_label()} - {vc.get('connection', 'wired')}"
        try:
            plan = hardware.plan(vc)
        except Exception as e:
            return {"label": label, "note": f"Can't set up the bot for {label} automatically ({e})"}
        if plan.get("device") != "pic" or plan.get("dynamic"):
            return {"label": label, "baud": plan.get("data_baud") or None,
                    "note": f"{label}: this wiring ({plan.get('hardware')}) is configured outside the ScoreLinkII; "
                            "ScoreReader only reads the data"}
        key = f"{pid}#{vc.get('hardware')}"
        return {"label": label, "commands": plan["pic_commands"], "baud": plan["data_baud"],
                "configure": get_path(self.cfg, "scorelink.configured_for", "") != key,
                "on_configured": self._remember_bot(key)}

    def _remember_bot(self, key: str):
        def remember():
            set_path(self.saved, "scorelink.configured_for", key)
            set_path(self.cfg, "scorelink.configured_for", key)
            try:
                save_config(self.saved)
            except OSError:
                pass
        return remember

    def _new_reader(self):
        r = Reader(self.cfg, self.decoder, threading.Event(), self.cl, vendor=self.vendor, bot=self.bot_plan())
        r.cl_other = self.cl_other
        if self.mqtt:
            r.raw_hook = self.mqtt.raw
        return r

    def restart_reader(self):
        """Stop the data source, clear every decoded value, and start the source currently in cfg."""
        old = self.reader
        old.stop.set()
        if old.is_alive():
            old.join(timeout=5)
            if old.is_alive():
                log("The previous data source is still closing; the new one will retry until the port is free")
        with self.swap_lock:
            self.decoder, self.cl = self._new_decoders()
            STATUS.reset_counters()
            STATUS.set_source("starting", self.cfg["source"])
            self.reader = self._new_reader()
            self.gen += 1
        log(f"Data source: {self.cfg['source']}")
        if self.running:
            self.reader.start()

    def restart_vmix(self):
        if self.vmix:
            self.vmix.stop.set()
            self.vmix = None
        if self.cfg["vmix"].get("enabled"):
            self.vmix = VmixPusher(self.cfg, threading.Event())
            STATUS.vmix_state = "connecting"
            if self.running:
                self.vmix.start()
        else:
            STATUS.vmix_state = "disabled"

    # ---- settings
    def live_source(self) -> str:
        """The source to go back to after demo/replay: the saved one, or the ScoreBot."""
        s = self.saved.get("source", "scorelink")
        return "scorelink" if s in RUNTIME_ONLY_SOURCES else s

    def setting_choices(self) -> dict:
        try:
            import scoreboards

            protocols = sorted(scoreboards.protocols())
        except Exception:
            protocols = []
        return {"source": ["scorelink", "serial", "tcp", "demo", "replay"], "sport": self.sports.names(),
                "mqtt.mode": ["broker", "client"], "replay_file": list_captures(),
                "scoreboard.protocol": [""] + protocols}

    def scoreboards_json(self) -> list:
        """Brands with their implemented sports and wiring options, for the Settings pickers."""
        try:
            import scoreboards

            impl = scoreboards.protocols()
            cat = scoreboards.catalog()
        except Exception:
            return []
        out = []
        for v in cat.get("vendors", []):
            sports = [{"id": r["enum"], "description": r.get("description") or r["enum"], "event": r.get("event_type")}
                      for r in cat.get("vendor_sports", []) if r.get("vendor") == v["name"] and r.get("enum") in impl]
            if sports:
                out.append({"name": v["name"], "sports": sorted(sports, key=lambda x: x["description"]),
                            "connections": [c.get("connection", "") + (" - " + c["hardware"] if c.get("hardware") else "")
                                            for c in v.get("configs", [])]})
        return sorted(out, key=lambda v: v["name"].lower())

    def settings_json(self) -> dict:
        try:
            ports = [{"device": p.device, "description": p.description,
                      "scorelink": (p.vid, p.pid) == (SCORELINK_VID, SCORELINK_PID)} for p in list_serial_ports()]
        except Exception:
            ports = []
        return {
            "values": {p: get_path(self.cfg, p, "") for p in SETTINGS},
            "spec": [{"path": p, "group": g, "label": lbl, "type": t, "apply": a} for p, (g, lbl, t, a) in SETTINGS.items()],
            "choices": self.setting_choices(),
            "ports": ports,
            "runtime_only_sources": list(RUNTIME_ONLY_SOURCES),
            "scoreboards": self.scoreboards_json(),
            "live_source": self.live_source(),
            "config_path": CONFIG_PATH,
            "text_folder": os.path.join(DATA_DIR, get_path(self.cfg, "text_files.folder", "text_out")),
        }

    def apply_settings(self, changes: dict) -> dict:
        """Validate and apply dashboard settings. All-or-nothing: if any value is invalid, nothing changes."""
        if not isinstance(changes, dict):
            return {"ok": False, "errors": {"": "expected a JSON object"}}
        choices = self.setting_choices()
        clean, errors = {}, {}
        for path, value in changes.items():
            if path not in SETTINGS:
                errors[path] = "is not a setting that can be changed here"
                continue
            try:
                clean[path] = coerce_setting(path, value, choices)
            except ValueError as e:
                errors[path] = f"{SETTINGS[path][1]} {e}"
        if errors:
            return {"ok": False, "errors": errors}
        with self.settings_lock:
            changed = {p: v for p, v in clean.items() if get_path(self.cfg, p) != v}
            persist = False
            for path, value in changed.items():
                set_path(self.cfg, path, value)
                # demo/replay are never saved, so the next start is always live data
                runtime_only = path == "replay_file" or (path == "source" and value in RUNTIME_ONLY_SOURCES)
                if not runtime_only:
                    set_path(self.saved, path, value)
                    persist = True
                log(f"Setting {path} = {value!r}" + (" (this session only)" if runtime_only else ""))
            if persist:
                save_config(self.saved)
            kinds = {SETTINGS[p][3] for p in changed}
            if "reader" in kinds:
                self.restart_reader()
            if "vmix" in kinds:
                self.restart_vmix()
            self.gen += 1
        return {"ok": True, "changed": sorted(changed),
                "restart_needed": sorted(p for p in changed if SETTINGS[p][3] == "restart")}

    # ---- data
    def current(self) -> dict:
        """Every field (for the dashboard)."""
        with self.data_lock:
            d = self.data
            return d.copy() if isinstance(d, Data) else dict(d)

    def public(self, d: dict) -> dict:
        """The fields served to graphics: only those used in the sport, unless output_all_fields is on."""
        if self.cfg.get("output_all_fields") or not isinstance(d, Data):
            return dict(d)
        return d.public()

    def add_team_info(self, d: dict) -> None:
        """Team names/abbreviations/colors from Settings. A blank name falls back to what the console sent
        (RTD), then the legacy mqtt.home_team_name/guest_team_name, then HOME/GUEST."""
        t = self.cfg.get("teams", {}) or {}
        m = self.cfg.get("mqtt", {}) or {}
        for side in ("home", "guest"):
            d[f"{side}_name"] = (str(t.get(f"{side}_name") or "").strip() or str(d.get(f"{side}_name") or "").strip()
                                 or str(m.get(f"{side}_team_name") or "").strip() or side.upper())
            d[f"{side}_abbr"] = (str(t.get(f"{side}_abbr") or "").strip()
                                 or str(d.get(f"{side}_abbr") or "").strip())
            d[f"{side}_color"] = str(t.get(f"{side}_color") or "").strip()

    def vendor_contract(self):
        """(contract name, contract dict) when a ScoreConnect-style decoder supplies the data: the chosen brand,
        or, on the built-in Daktronics path, a current-loop console code the built-in decoder doesn't know
        (anything but football 6601 / soccer 7601). None = the built-in decoder."""
        v = self.vendor
        if v is None:
            o, cl = self.cl_other, self.cl
            if (o is None or not cl.packets or cl.console_code in cl.CODE_SPORT
                    or getattr(o.decoder, "selected", None) is None):
                return None
            v = o
        return v.contract_name, (v.full_contract() if hasattr(v, "full_contract") else v.snapshot())

    def mqtt_contract(self, d: dict):
        """Contract for the MQTT payloads; None = football/soccer via build_payloads (byte-compatible as before)."""
        vc = self.vendor_contract()
        if vc is not None or self.cl.packets:
            return vc
        return rtd_contract(self.cfg["sport"], d)

    def build_data(self) -> dict:
        with self.swap_lock:
            vc = self.vendor_contract()
            if vc is not None:
                d = contract_to_data(*vc)
                d["protocol"] = self.protocol_id() or (self.cl_other.decoder.selected if self.cl_other else "")
            elif self.cl.packets:
                d = self.cl.data()
            else:
                sport = self.cfg["sport"]
                d = Data(self.sports.extract(sport, self.decoder.snapshot()))
                friendly = set(self.sports.simple(sport, d))
                d.raw_keys = frozenset(f["name"] for f in self.sports.fields(sport)) - friendly
                d.setdefault("sport", sport)
        # single possession field for graphics: "H", "V" or "" (no possession lit on the board)
        if "home_poss" in d:
            d["possession"] = "H" if d.get("home_poss") else ("V" if d.get("guest_poss") else "")
        self.add_team_info(d)
        return d

    def update_loop(self):
        seen = None
        text_cache: dict = {}
        last_save = 0.0
        while not self.stop.is_set():
            v = (self.gen, self.decoder.version, self.cl.version, self.vendor.version if self.vendor else 0,
                 self.cl_other.version if self.cl_other else 0)
            if v != seen:
                seen = v
                d = self.build_data()
                with self.data_lock:
                    self.data = d
                vm = self.vmix
                if vm:
                    vm.submit(d)
                if self.mqtt:
                    self.mqtt.update(d, contract=self.mqtt_contract(d))
                tf = self.cfg.get("text_files", {})
                if tf.get("enabled"):
                    try:
                        write_text_files(os.path.join(DATA_DIR, tf.get("folder", "text_out")), self.public(d),
                                         text_cache)
                    except OSError as e:
                        log(f"text file write error: {e}")
                if self.cfg.get("save_state") and time.time() - last_save > 2:
                    last_save = time.time()
                    try:
                        self.decoder.save(STATE_PATH)
                    except OSError:
                        pass
            self.stop.wait(0.03)
        # app stopping: stop the threads we own
        self.reader.stop.set()
        if self.vmix:
            self.vmix.stop.set()

    def state_json(self) -> dict:
        with self.swap_lock:
            dec, cl = self.decoder, self.cl
        buf = dec.snapshot()
        now = time.time()
        with dec.lock:
            ch = [round(now - t, 1) if t else 9999 for t in dec.changed_at[: len(buf)]]
        lp = STATUS.last_packet_time
        return {
            "source": self.cfg["source"],
            "source_saved": self.cfg["source"] not in RUNTIME_ONLY_SOURCES,
            "live_source": self.live_source(),
            "replay_file": os.path.basename(str(self.cfg.get("replay_file") or "")),
            "source_state": STATUS.source_state,
            "source_detail": STATUS.source_detail,
            "bytes_in": STATUS.bytes_in,
            "packets": STATUS.packets,
            "bad_packets": STATUS.bad_packets,
            "unknown_headers": {} if cl.packets else dict(list(STATUS.unknown_headers.items())[:5]),
            "packet_age": (now - lp) if lp else None,
            "vmix_state": STATUS.vmix_state,
            "mqtt_state": self.mqtt.status if self.mqtt else "disabled",
            "pic_info": STATUS.pic_info,
            "sport": (self.current().get("sport") or self.cfg["sport"]) if self.vendor_contract() else
                     (cl.sport if cl.packets else self.cfg["sport"]),
            "vendor_mode": self.vendor is not None,
            "sports": self.sports.names(),
            "fields": [{"name": f["name"], "pos": f["pos"], "len": f["len"]} for f in self.sports.fields(self.cfg["sport"])],
            "data": self.current(),
            "raw": buf.decode("latin-1", "replace").replace("\x00", " "),
            "changed_ago": ch,
            "logs": STATUS.logs[-80:],
            "recent_hex": STATUS.recent_hex,
            "protocol": (self.protocol_label() if self.vendor is not None else
                         "Daktronics current loop (code " + (cl.console_code or "?") + ")" if cl.packets
                         else "Daktronics RTD"),
            "scoreboard": self.protocol_label(),
            "contract": self._contract_rows(),
            "cl_table": cl.address_table(),
            "cl_bad": cl.bad,
        }

    def _contract_rows(self) -> list:
        vc = self.vendor_contract()
        if vc is None:
            return []
        v = self.vendor or self.cl_other
        rows = [{"k": k, "v": str(val)} for k, val in sorted(vc[1].items()) if not isinstance(val, (dict, list))]
        return [{"k": "(contract)", "v": vc[0]}, {"k": "(packets / bad)", "v": f"{v.packets} / {v.bad}"}] + rows

    def make_handler(app):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                d = app.public(app.current())  # only the fields used in the sport (unless output_all_fields)
                flat = {k: (("1" if v else "0") if isinstance(v, bool) else v) for k, v in d.items()}
                if u.path in ("/", "/index.html"):
                    return self._send(200, DASHBOARD_HTML, "text/html; charset=utf-8")
                if u.path == "/data.json":
                    return self._send(200, json.dumps([flat], ensure_ascii=False), "application/json")
                if u.path == "/data.obj.json":
                    return self._send(200, json.dumps(flat, ensure_ascii=False), "application/json")
                if u.path == "/data.xml":
                    x = "".join(f"<{k}>{xml_escape(str(v))}</{k}>" for k, v in flat.items())
                    return self._send(200, f'<?xml version="1.0" encoding="utf-8"?><scoreboard><data>{x}</data></scoreboard>',
                                      "application/xml")
                if u.path == "/data.csv":
                    s = io.StringIO()
                    w = csv.writer(s)
                    w.writerow(flat.keys())
                    w.writerow(flat.values())
                    return self._send(200, s.getvalue(), "text/csv")
                if u.path in ("/favicon.svg", "/favicon.ico", "/icon.png"):
                    name, ctype = (("icon.png", "image/png") if u.path == "/icon.png"
                                   else ("icon.svg", "image/svg+xml"))
                    try:
                        with open(os.path.join(ASSETS_DIR, name), "rb") as f:
                            return self._send(200, f.read(), ctype)
                    except OSError:
                        return self._send(404, "not found", "text/plain")
                if u.path == "/api/state":
                    return self._send(200, json.dumps(app.state_json()), "application/json")
                if u.path == "/api/settings":
                    return self._send(200, json.dumps(app.settings_json(), ensure_ascii=False), "application/json")
                return self._send(404, "not found", "text/plain")

            def do_POST(self):
                u = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(u.query)
                # The custom header makes browsers send a CORS preflight for cross-site requests, which this
                # server never approves, so another web page open on this PC can't change settings.
                if self.headers.get("X-ScoreReader") != "1":
                    return self._send(403, "missing X-ScoreReader: 1 header", "text/plain")
                if u.path == "/api/settings":
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                        changes = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                    except (ValueError, UnicodeDecodeError):
                        return self._send(400, json.dumps({"ok": False, "errors": {"": "invalid JSON"}}),
                                          "application/json")
                    res = app.apply_settings(changes)
                    return self._send(200 if res["ok"] else 400, json.dumps(res), "application/json")
                if u.path == "/api/sport":
                    name = (qs.get("name") or [""])[0]
                    res = app.apply_settings({"sport": name})
                    if res["ok"]:
                        cl = app.cl
                        if cl.console_code in cl.CODE_SPORT:
                            log(f"Console code {cl.console_code} overrides the sport: {cl.sport}")
                        return self._send(200, "ok", "text/plain")
                    return self._send(400, "unknown sport", "text/plain")
                if u.path == "/api/reinit":
                    app.reader.reinit_request.set()
                    log("Re-init requested from dashboard")
                    return self._send(200, "ok", "text/plain")
                return self._send(404, "not found", "text/plain")

        return H

    def run(self):
        """Start everything and block until Ctrl+C."""
        self.start()
        try:
            while not self.stop.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            log("Stopping…")
        finally:
            self.shutdown()

    @property
    def dashboard_url(self) -> str:
        return f"http://localhost:{int(self.cfg['http_port'])}/"

    def start(self):
        """Start the source, outputs and web server in background threads, then return."""
        if self.cfg.get("save_state"):
            self.decoder.load(STATE_PATH)
        self.running = True
        self.reader.start()
        if self.vmix:
            STATUS.vmix_state = "connecting"
            self.vmix.start()
        if self.mqtt:
            self.mqtt.start()
        threading.Thread(target=self.update_loop, daemon=True).start()
        port = int(self.cfg["http_port"])
        srv = ThreadingHTTPServer(("0.0.0.0", port), self.make_handler())
        self._srv = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"Dashboard:        http://localhost:{port}/")
        log(f"vMix data source: http://localhost:{port}/data.json   (also /data.xml, /data.csv)")
        if self.mqtt:
            log(f"MQTT topics:      bot/{self.mqtt.bot}/json, bot/{self.mqtt.bot}/sbdata, bot/{self.mqtt.bot}/raw")

    def shutdown(self):
        if getattr(self, "_shut", False):
            return
        self._shut = True
        self.stop.set()
        self.reader.stop.set()
        srv = getattr(self, "_srv", None)
        if srv is not None:
            srv.shutdown()
        if self.cfg.get("save_state"):
            try:
                self.decoder.save(STATE_PATH)
            except OSError:
                pass


# --------------------------------------------------------------------------- CLI tools
def cmd_list_ports():
    ports = list_serial_ports()
    if not ports:
        print("No serial ports found.")
    for p in ports:
        tag = "  <-- ScoreLinkII / MCP2221" if (p.vid, p.pid) == (SCORELINK_VID, SCORELINK_PID) else ""
        vidpid = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "----:----"
        print(f"{p.device:28} {vidpid}  {p.description}{tag}")
    try:
        m = MCP2221()
        val, d = m.get_gp2()
        m.close()
        print(f"\nScoreLinkII USB control interface: OK (GP2={val}, {'DATA' if val == 1 else 'COMMAND' if val == 0 else 'not GPIO'} mode)")
    except ImportError:
        print("\n(hidapi not installed - can't check MCP2221 GPIO interface; only needed on Mac/Linux)")
    except Exception as e:
        print(f"\nScoreLinkII USB control interface: {e}")


def cmd_list_scoreboards():
    import scoreboards

    impl = scoreboards.protocols()
    rows = [r for r in scoreboards.catalog().get("vendor_sports", []) if r.get("enum") in impl]
    print("(blank)".ljust(44), "Daktronics All Sport 5000, built-in current loop + RTD (default)")
    for r in sorted(rows, key=lambda r: (r["vendor"].lower(), r["description"])):
        print(r["enum"].ljust(44), f'{r["vendor"]}: {r["description"]}')
    print(f"\n{len(rows)} scoreboard layouts. Use: scorereader.py --scoreboard ID   (or pick one in Settings)")
    for mod, err in scoreboards.load_errors().items():
        print(f"warning: scoreboards/{mod}.py failed to load: {err}")


def cmd_probe(cfg, configure: bool):
    import serial

    port = resolve_port(cfg)
    mcp = MCP2221()
    ser = serial.Serial(port, cfg["baud"], timeout=0.2)
    try:
        print(f"Port {port}")
        val, d = mcp.get_gp2()
        print(f"GP2 before: value={val} dir={d}  ({'DATA mode' if val == 1 else 'COMMAND mode' if val == 0 else 'not GPIO'})")
        info = scorelink_session(cfg, ser, mcp, send_config=configure, probe=True)
        val, d = mcp.get_gp2()
        print(f"GP2 after:  value={val} ({'DATA mode' if val == 1 else '?'})")
        if not info.get("R?"):
            print("\nNo reply from the PIC. Check: ScoreConnect III fully closed (incl. service), right port, bot powered.")
    finally:
        ser.close()
        mcp.close()


def cmd_sniff(cfg, seconds: float):
    """Raw hex dump of whatever the bot sends in data mode (no decoding)."""
    stop = threading.Event()
    dec = DaktronicsRTD(cfg.get("strict_daktronics_header", True))
    rd = Reader(cfg, dec, stop, DaktronicsCurrentLoop())
    rd.raw_sink = queue.Queue()
    rd.start()
    t_end = time.time() + seconds
    total = 0
    try:
        while time.time() < t_end:
            try:
                data = rd.raw_sink.get(timeout=0.5)
            except queue.Empty:
                continue
            total += len(data)
            for i in range(0, len(data), 24):
                ch = data[i : i + 24]
                asc = "".join(chr(b) if 32 <= b < 127 else "." for b in ch)
                print(f"{ch.hex(' '):<72} {asc}")
    except KeyboardInterrupt:
        pass
    stop.set()
    print(f"\n{total} bytes, {STATUS.packets} valid packets decoded (RTD + current loop).")
    if total and not STATUS.packets:
        print("Bytes but no RTD packets -> wrong baud? try --baud 9600 or 38400, or check scoreboard type.")
    if not total:
        print("No bytes. Is the console on and sending? Clock running? Try --probe to check the bot.")


def main():
    ap = argparse.ArgumentParser(description="ScoreReader - ScoreLinkII / Daktronics scoreboard data to vMix, MQTT and more")
    ap.add_argument("--version", action="version", version=f"ScoreReader {__version__}")
    ap.add_argument("--port", help="serial port (COM5, /dev/cu.usbmodem...) - default auto")
    ap.add_argument("--baud", type=int, help="scoreboard data baud (default 19200)")
    ap.add_argument("--sport", help="football, basketball, soccer, baseball, volleyball, hockey_lacrosse, ...")
    ap.add_argument("--source", choices=["scorelink", "serial", "tcp", "demo", "replay"],
                    help="scorelink = ScoreBot over USB; serial = plain USB-serial cable to the console")
    ap.add_argument("--demo", action="store_true", help="fake football game (test vMix without hardware)")
    ap.add_argument("--vmix", action="store_true", help="enable vMix TCP push (input name in config)")
    ap.add_argument("--vmix-input", help="vMix title input name/number")
    ap.add_argument("--http-port", type=int)
    ap.add_argument("--mqtt-bot", type=int, metavar="N", help="bot number for MQTT topics bot/N/... (default 0)")
    ap.add_argument("--no-mqtt", action="store_true", help="disable the Sportzcast-compatible MQTT output")
    ap.add_argument("--scoreboard", metavar="ID",
                    help="scoreboard brand+sport id (see --list-scoreboards); this session only")
    ap.add_argument("--list-scoreboards", action="store_true", help="list supported scoreboard brands/sports and exit")
    ap.add_argument("--replay", metavar="FILE", help="replay a raw capture from logs/raw_*.bin")
    ap.add_argument("--no-menubar", action="store_true", help="Mac: don't show the ScoreReader menu bar icon")
    ap.add_argument("--fresh", action="store_true", help="ignore the saved last-known scoreboard state")
    ap.add_argument("--list-ports", action="store_true", help="list serial ports and exit")
    ap.add_argument("--probe", action="store_true", help="talk to the ScoreLinkII PIC (version/config) and exit")
    ap.add_argument("--configure-bot", action="store_true",
                    help="re-send the ScoreConnect config commands (Daktronics football) to the bot and exit")
    ap.add_argument("--sniff", type=float, nargs="?", const=20, metavar="SECONDS",
                    help="hex-dump raw bytes from the bot (default 20s) and exit")
    # Old macOS versions pass a "-psn_…" process serial number to apps opened from Finder.
    a = ap.parse_args([x for x in sys.argv[1:] if not x.startswith("-psn_")])

    if hasattr(signal, "SIGTERM"):  # systemd / launchd stop = Ctrl+C: shut down cleanly
        def _on_term(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, _on_term)

    saved = load_config()                   # what's in scorereader_config.json
    cfg = json.loads(json.dumps(saved))     # running config = saved + command-line options (never written back)
    if a.port:
        cfg["port"] = a.port
    if a.baud:
        cfg["baud"] = a.baud
    if a.sport:
        cfg["sport"] = a.sport
    if a.source:
        cfg["source"] = a.source
    if a.demo:
        cfg["source"] = "demo"
    if a.replay:
        cfg["source"], cfg["replay_file"], cfg["record_raw"] = "replay", a.replay, False
    if a.mqtt_bot is not None:
        cfg["mqtt"]["bot_number"] = a.mqtt_bot
    if a.no_mqtt:
        cfg["mqtt"]["enabled"] = False
    if a.vmix:
        cfg["vmix"]["enabled"] = True
    if a.vmix_input:
        cfg["vmix"]["input"] = a.vmix_input
    if a.http_port:
        cfg["http_port"] = a.http_port

    if a.scoreboard is not None:
        cfg.setdefault("scoreboard", {})["protocol"] = a.scoreboard
    if a.list_ports:
        return cmd_list_ports()
    if a.list_scoreboards:
        return cmd_list_scoreboards()
    if a.probe or a.configure_bot:
        try:
            return cmd_probe(cfg, configure=a.configure_bot)
        except ImportError:
            print("hidapi is not installed (Mac/Linux only):  pip3 install hidapi")
        except Exception as e:
            print(f"Probe failed: {e}")
            if "denied" in str(e).lower():
                print("-> ScoreConnect III (or its service) still has the port. Run the stop-service .bat as admin.")
        return
    if a.sniff is not None:
        return cmd_sniff(cfg, a.sniff)
    if a.fresh and os.path.exists(STATE_PATH):
        os.remove(STATE_PATH)
    print(f"ScoreReader {__version__}  |  source={cfg['source']}  sport={cfg['sport']}  baud={cfg['baud']}  config={CONFIG_PATH}")
    if saved.get("source") in RUNTIME_ONLY_SOURCES:
        print(f"NOTE: scorereader_config.json has \"source\": \"{saved['source']}\" - that is not live scoreboard data. "
              "Pick the live source in Settings.")
    set_window_title(f"ScoreReader {__version__}")
    if MAC_APP:  # no Terminal window: keep the log in a file (menu bar > Open logs folder)
        detach_console(os.path.join(LOG_DIR, "scorereader.log"))
    app = App(cfg, saved=saved)
    if sys.platform == "darwin" and not a.no_menubar:
        try:
            import menubar

            if menubar.available():
                app.start()
                if MAC_APP:  # opened from Finder/Launchpad: show the dashboard so it's clear it started
                    import webbrowser

                    threading.Timer(1.5, webbrowser.open, args=(app.dashboard_url,)).start()
                return menubar.run(app)  # owns the main thread until Quit
        except Exception as e:
            log(f"Menu bar icon unavailable ({e}); running in this window only")
            if app.running:
                try:
                    while not app.stop.is_set():
                        time.sleep(1)
                except KeyboardInterrupt:
                    log("Stopping…")
                finally:
                    app.shutdown()
                return
    app.run()


if __name__ == "__main__":
    main()
