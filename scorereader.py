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
import csv
import datetime as _dt
import io
import json
import os
import queue
import random
import socket
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape as xml_escape

__version__ = "1.0.0"

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)  # PyInstaller support
CONFIG_PATH = os.path.join(APP_DIR, "scorereader_config.json")
FIELDS_PATH = os.path.join(RES_DIR, "daktronics_fields.json")
STATE_PATH = os.path.join(APP_DIR, "scorereader_state.bin")
LOG_DIR = os.path.join(APP_DIR, "logs")

SCORELINK_VID, SCORELINK_PID = 0x04D8, 0x00DD

DEFAULT_CONFIG = {
    "source": "scorelink",          # scorelink | serial | tcp | demo
    "port": "auto",                 # auto | COM5 | /dev/cu.usbmodem1101 ...
    "baud": 19200,                  # scoreboard data baud (Daktronics All Sport 5000 = 19200)
    "sport": "football",
    "scorelink": {
        "use_gpio_mode_switch": True,   # drive MCP2221 GP2 (needs `hidapi`)
        "probe_on_start": True,         # ask the PIC its version/config at startup (log only)
        "send_config_on_start": False,  # re-send config_commands every start
        "command_baud": 57600,
        # exactly what ScoreConnect III sent for Daktronics football (current loop, inverted):
        "config_commands": [">M0X0X", ">T0", ">D0", ">M8I1N"],
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
        "home_team_name": "HOME",
        "guest_team_name": "GUEST",
        "publish_rate": 10,          # max messages/sec on json & sbdata
        "heartbeat_seconds": 1.0,    # re-publish even when nothing changed
        "publish_raw": True,
    },
    "text_files": {"enabled": False, "folder": "text_out"},
    "record_raw": True,
    "strict_daktronics_header": True,
}


# --------------------------------------------------------------------------- utils
_PRINT_LOCK = threading.Lock()


def log(msg: str) -> None:
    line = f"{_dt.datetime.now():%H:%M:%S} {msg}"
    with _PRINT_LOCK:
        print(line, flush=True)
    STATUS.add_log(line)


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "fields":
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return deep_merge(DEFAULT_CONFIG, json.load(f))


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


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
            s["down_distance"] = f"{down} & {togo}" if down and togo != "" else down
            s["ball_on"] = str(g("ball_on", ""))
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


def scorelink_session(cfg, ser, mcp, send_config: bool, probe: bool) -> dict:
    """Enter command mode, query/configure the PIC, return to data mode. Returns info dict."""
    sl = cfg["scorelink"]
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
            for c in sl["config_commands"]:
                pic_command(ser, c)
                time.sleep(0.3)  # PIC writes EEPROM
                chk = c[:3] + "?" if c.startswith(">M") else c[:2] + "?"
                r = pic_command(ser, chk)
                log(f"PIC set {c} -> readback {r or '(no reply)'}")
    finally:
        mcp.set_gp2(True)  # data mode
        time.sleep(0.05)
        ser.baudrate = cfg["baud"]
        time.sleep(0.05)
        ser.reset_input_buffer()
    STATUS.pic_info = info
    return info


class Reader(threading.Thread):
    def __init__(self, cfg, decoder: DaktronicsRTD, stop: threading.Event, cl=None):
        super().__init__(daemon=True)
        self.cfg, self.decoder, self.stop = cfg, decoder, stop
        self.cl = cl
        self.raw_file = None
        self.reinit_request = threading.Event()
        self.raw_sink: queue.Queue | None = None  # for --sniff
        self.raw_hook = None  # e.g. MQTT bot/N/raw

    def _feed(self, data: bytes):
        if self.raw_hook is not None:
            self.raw_hook(data)
        if self.cl is not None:
            self.cl.feed(data)
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
                msg = str(e)
                if "Access is denied" in msg or "PermissionError" in repr(e) or "busy" in msg.lower():
                    msg += "  -> The port is in use. Quit ScoreConnect III AND stop its Windows service " \
                           "(admin cmd: net stop ScoreConnectIII), then this will retry automatically."
                STATUS.set_source("error", msg)
                log(f"Source error: {msg}")
                if os.environ.get("SCOREREADER_DEBUG"):
                    traceback.print_exc()
            self.stop.wait(3)

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
        ser = serial.Serial(port, self.cfg["baud"], bytesize=8, parity="N", stopbits=1, timeout=0.2)
        try:
            log(f"Opened {port}")
            if scorelink and mcp is not None:
                sl = self.cfg["scorelink"]
                scorelink_session(self.cfg, ser, mcp, sl.get("send_config_on_start", False),
                                  sl.get("probe_on_start", True))
                log(f"ScoreLinkII in DATA mode, reading at {self.cfg['baud']} baud")
            STATUS.set_source("connected", f"{port} @ {self.cfg['baud']}")
            while not self.stop.is_set():
                if self.reinit_request.is_set():
                    self.reinit_request.clear()
                    if scorelink and mcp is not None:
                        scorelink_session(self.cfg, ser, mcp, True, True)
                data = ser.read(4096)
                if data:
                    self._record(data)
                    self._feed(data)
        finally:
            ser.close()
            if mcp:
                mcp.close()

    def run_replay(self):
        path = self.cfg["replay_file"]
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
            pk += put(48, 20, "FAIRFIELD PREP") + put(68, 20, "VISITORS")
            pk += put(88, 10, "PREP") + put(98, 10, "VIS")
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

    def run(self):
        latest = None
        while not self.stop.is_set():
            try:
                latest = self.q.get(timeout=0.5)
                while not self.q.empty():
                    latest = self.q.get_nowait()
            except queue.Empty:
                pass
            if latest is None:
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
                if self.sock:
                    try:
                        self.sock.close()
                    except OSError:
                        pass
                self.sock = None
                self.stop.wait(2)


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
</style></head><body>
<header><h1>ScoreReader</h1><span id="src" class="pill">…</span><span id="age" class="pill">…</span><span id="vmix" class="pill">vMix</span><span id="mqtt" class="pill">MQTT</span>
<span class="mut" id="stats"></span><span style="flex:1"></span>
<label class="mut">Sport <select id="sport"></select></label>
<button onclick="reinit()" title="Re-run ScoreLinkII probe + config">Re-init bot</button>
<a href="/data.json" target="_blank">data.json</a><a href="/data.xml" target="_blank">data.xml</a></header>
<main>
<div class="card bug">
 <div><div class="team" id="hn">HOME</div><div class="score" id="hs">0</div><div class="poss" id="hp"></div></div>
 <div class="mid"><div class="clock" id="clk">--:--</div><div class="sub" id="sub"></div></div>
 <div><div class="team" id="gn">GUEST</div><div class="score" id="gs">0</div><div class="poss" id="gp"></div></div>
</div>
<div class="cols">
 <div class="card"><b>Fields</b> <span class="mut">(names = keys in data.json)</span>
   <input id="flt" placeholder="filter…" style="float:right"><table id="ft"></table></div>
 <div class="card"><b id="ptitle">Raw data</b><div id="cltab"></div><div class="grid" id="grid"></div>
   <br><b>Log</b><pre id="log"></pre><br><b>Last bytes (hex)</b><pre id="hex"></pre></div>
</div></main>
<script>
let fieldsMeta=[];
async function reinit(){await fetch('/api/reinit',{method:'POST'});}
document.getElementById('sport').onchange=async e=>{await fetch('/api/sport?name='+e.target.value,{method:'POST'});fieldsMeta=[];};
async function tick(){
 try{
  const r=await fetch('/api/state');const s=await r.json();
  const sel=document.getElementById('sport');
  if(!sel.options.length){s.sports.forEach(n=>{const o=new Option(n,n);sel.add(o)});}
  sel.value=s.sport;
  const src=document.getElementById('src');src.textContent=s.source_state+' — '+s.source_detail;
  src.className='pill '+(s.source_state=='connected'?'ok':(s.source_state=='error'?'bad':'warn'));
  const age=document.getElementById('age');
  if(s.packet_age==null){age.textContent='no RTD packets yet';age.className='pill warn'}
  else{age.textContent='last packet '+s.packet_age.toFixed(1)+'s ago';age.className='pill '+(s.packet_age<5?'ok':'warn')}
  const vm=document.getElementById('vmix');vm.textContent='vMix: '+s.vmix_state;vm.className='pill '+(s.vmix_state.startsWith('connected')?'ok':(s.vmix_state=='disabled'?'':'bad'));
  const mq=document.getElementById('mqtt');mq.textContent='MQTT: '+s.mqtt_state;mq.className='pill '+(s.mqtt_state.startsWith('listening')||s.mqtt_state.startsWith('connected')?'ok':(s.mqtt_state=='disabled'?'':'bad'));
  document.getElementById('stats').textContent=`${s.bytes_in} bytes · ${s.packets} pkts · ${s.bad_packets} bad`+(Object.keys(s.unknown_headers).length?' · unknown hdrs: '+JSON.stringify(s.unknown_headers):'');
  const d=s.data;
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
  if(s.cl_table.length){grid.innerHTML='';document.getElementById('ptitle').textContent=s.protocol+' — addresses';
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
    def __init__(self, cfg):
        self.cfg = cfg
        self.stop = threading.Event()
        self.decoder = DaktronicsRTD(cfg.get("strict_daktronics_header", True))
        self.cl = DaktronicsCurrentLoop()
        self.cl.sport_fallback = lambda: self.cfg["sport"]
        self.cl.custom_fields = lambda: self.cfg.get("custom_fields", {})
        self.sports = SportMap(FIELDS_PATH)
        if cfg["sport"] not in self.sports.sports:
            log(f"Unknown sport '{cfg['sport']}', using football. Options: {', '.join(self.sports.names())}")
            cfg["sport"] = "football"
        self.reader = Reader(cfg, self.decoder, self.stop, self.cl)
        self.vmix = VmixPusher(cfg, self.stop) if cfg["vmix"].get("enabled") else None
        self.mqtt = None
        if cfg.get("mqtt", {}).get("enabled"):
            from sportzcast_mqtt import SportzcastMqttOutput

            self.mqtt = SportzcastMqttOutput(cfg, log=log)
            self.reader.raw_hook = self.mqtt.raw
        self.data: dict = {}
        self.data_lock = threading.Lock()

    def current(self) -> dict:
        with self.data_lock:
            return dict(self.data)

    def update_loop(self):
        seen = None
        text_cache: dict = {}
        last_save = 0.0
        while not self.stop.is_set():
            v = (self.decoder.version, self.cl.version)
            if v != seen:
                seen = v
                if self.cl.packets:
                    d = self.cl.data()
                else:
                    d = self.sports.extract(self.cfg["sport"], self.decoder.snapshot())
                # single possession field for graphics: "H", "V" or "" (no possession lit on the board)
                if "home_poss" in d:
                    d["possession"] = "H" if d.get("home_poss") else ("V" if d.get("guest_poss") else "")
                with self.data_lock:
                    self.data = d
                if self.vmix:
                    self.vmix.submit(d)
                if self.mqtt:
                    self.mqtt.update(d)
                tf = self.cfg.get("text_files", {})
                if tf.get("enabled"):
                    try:
                        write_text_files(os.path.join(APP_DIR, tf.get("folder", "text_out")), d, text_cache)
                    except OSError as e:
                        log(f"text file write error: {e}")
                if time.time() - last_save > 2:
                    last_save = time.time()
                    try:
                        self.decoder.save(STATE_PATH)
                    except OSError:
                        pass
            self.stop.wait(0.03)

    def state_json(self) -> dict:
        buf = self.decoder.snapshot()
        now = time.time()
        with self.decoder.lock:
            ch = [round(now - t, 1) if t else 9999 for t in self.decoder.changed_at[: len(buf)]]
        lp = STATUS.last_packet_time
        return {
            "source_state": STATUS.source_state,
            "source_detail": STATUS.source_detail,
            "bytes_in": STATUS.bytes_in,
            "packets": STATUS.packets,
            "bad_packets": STATUS.bad_packets,
            "unknown_headers": {} if self.cl.packets else dict(list(STATUS.unknown_headers.items())[:5]),
            "packet_age": (now - lp) if lp else None,
            "vmix_state": STATUS.vmix_state,
            "mqtt_state": self.mqtt.status if self.mqtt else "disabled",
            "pic_info": STATUS.pic_info,
            "sport": self.cl.sport if self.cl.packets else self.cfg["sport"],
            "sports": self.sports.names(),
            "fields": [{"name": f["name"], "pos": f["pos"], "len": f["len"]} for f in self.sports.fields(self.cfg["sport"])],
            "data": self.current(),
            "raw": buf.decode("latin-1", "replace").replace("\x00", " "),
            "changed_ago": ch,
            "logs": STATUS.logs[-80:],
            "recent_hex": STATUS.recent_hex,
            "protocol": "Daktronics current loop (code " + (self.cl.console_code or "?") + ")" if self.cl.packets
                        else "Daktronics RTD",
            "cl_table": self.cl.address_table(),
            "cl_bad": self.cl.bad,
        }

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
                d = app.current()
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
                if u.path == "/api/state":
                    return self._send(200, json.dumps(app.state_json()), "application/json")
                return self._send(404, "not found", "text/plain")

            def do_POST(self):
                u = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(u.query)
                if u.path == "/api/sport":
                    name = (qs.get("name") or [""])[0]
                    if name in app.sports.sports:
                        app.cfg["sport"] = name
                        save_config(app.cfg)
                        app.decoder.version += 1
                        app.cl.version += 1
                        log(f"Sport set to {name}" + (f" (console code {app.cl.console_code} overrides: {app.cl.sport})"
                                                      if app.cl.console_code in app.cl.CODE_SPORT else ""))
                        return self._send(200, "ok", "text/plain")
                    return self._send(400, "unknown sport", "text/plain")
                if u.path == "/api/reinit":
                    app.reader.reinit_request.set()
                    log("Re-init requested from dashboard")
                    return self._send(200, "ok", "text/plain")
                return self._send(404, "not found", "text/plain")

        return H

    def run(self):
        self.decoder.load(STATE_PATH)
        self.reader.start()
        if self.vmix:
            STATUS.vmix_state = "connecting"
            self.vmix.start()
        if self.mqtt:
            self.mqtt.start()
        threading.Thread(target=self.update_loop, daemon=True).start()
        port = int(self.cfg["http_port"])
        srv = ThreadingHTTPServer(("0.0.0.0", port), self.make_handler())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log(f"Dashboard:        http://localhost:{port}/")
        log(f"vMix data source: http://localhost:{port}/data.json   (also /data.xml, /data.csv)")
        if self.mqtt:
            log(f"MQTT topics:      bot/{self.mqtt.bot}/json, bot/{self.mqtt.bot}/sbdata, bot/{self.mqtt.bot}/raw")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log("Stopping…")
        finally:
            self.stop.set()
            srv.shutdown()
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
    ap.add_argument("--replay", metavar="FILE", help="replay a raw capture from logs/raw_*.bin")
    ap.add_argument("--fresh", action="store_true", help="ignore the saved last-known scoreboard state")
    ap.add_argument("--list-ports", action="store_true", help="list serial ports and exit")
    ap.add_argument("--probe", action="store_true", help="talk to the ScoreLinkII PIC (version/config) and exit")
    ap.add_argument("--configure-bot", action="store_true",
                    help="re-send the ScoreConnect config commands (Daktronics football) to the bot and exit")
    ap.add_argument("--sniff", type=float, nargs="?", const=20, metavar="SECONDS",
                    help="hex-dump raw bytes from the bot (default 20s) and exit")
    a = ap.parse_args()

    cfg = load_config()
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

    if a.list_ports:
        return cmd_list_ports()
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
    App(cfg).run()


if __name__ == "__main__":
    main()
