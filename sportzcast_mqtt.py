"""
Sportzcast-compatible MQTT output for ScoreReader.

Mimics ScoreConnect III's *local* MQTT broker so existing consumers (OSE, Flowics-style
clients, custom graphics) keep working:

    MQTT       tcp://<this-pc>:1883
    WebSocket  ws://<this-pc>:8083/mqtt
    Topics     bot/{botNumber}/json    Sportzcast JSON contract (Sport base + Football)
               bot/{botNumber}/sbdata  150-char Sportzcast SBDATA string
               bot/{botNumber}/raw     raw controller bytes

Contains a tiny MQTT 3.1 / 3.1.1 / 5.0 broker (QoS 0 delivery, wildcard subscriptions,
WebSocket transport) with no third-party dependencies, plus an optional client mode for
publishing into an existing broker (e.g. Mosquitto).
"""
from __future__ import annotations

import asyncio
import base64
import datetime as _dt
import hashlib
import json
import socket
import struct
import threading
import time

# --------------------------------------------------------------------------- payload builders
_NET_EPOCH_TICKS = 621355968000000000  # .NET ticks at 1970-01-01


def _ch(s: str, i: int = 0) -> str:
    s = str(s or "")
    return s[i] if len(s) > i else " "


def _norm_score(s: str) -> str:
    s = str(s or "").strip()
    return str(int(s)) if s.isdigit() else (s or "0")


def _clock_parts(clock: str):
    """Return (mode, mt, mo, st, so, tenths) from '12:34', '4:32', '59.8', ''."""
    c = str(clock or "").strip()
    if "." in c and ":" not in c:
        sec, t = c.split(".", 1)
        sec = sec.rjust(2)[-2:]
        return ".", "0", "0", sec[0], sec[1], (t[:1] or "0")
    if ":" in c:
        m, s = c.split(":", 1)
        m = m.rjust(2)[-2:]
        s = s.rjust(2, "0")[:2]
        return ":", m[0], m[1], s[0], s[1], "0"
    return ":", " ", " ", " ", " ", " "


def _timestamps(now: float):
    ticks = int(now * 10_000_000) + _NET_EPOCH_TICKS
    ts = format(ticks, "X")[:12]
    full = _dt.datetime.fromtimestamp(now, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{int((now % 1) * 1000):03d}Z"
    return ts, full, str(int(now))


def build_payloads(d: dict, cfg: dict, now: float | None = None):
    """Return (json_str, sbdata_str) for a ScoreReader data dict (football)."""
    now = time.time() if now is None else now
    m = cfg.get("mqtt", {})
    bot = int(m.get("bot_number", 0))
    # ScoreReader puts the team names (Settings > Teams, or the console's) into the data; the legacy
    # mqtt.home_team_name / guest_team_name keys are the fallback for older configs and direct callers.
    home_name = d.get("home_name") or m.get("home_team_name", "HOME")
    guest_name = d.get("guest_name") or m.get("guest_team_name", "GUEST")

    mode, mt, mo, st, so, tenths = _clock_parts(d.get("clock", ""))
    running = bool(d.get("clock_running"))
    clock_status = "R" if running else "S"
    if mode == ".":
        clock = f"{st}{so}.{tenths}".strip()
    else:
        clock = f"{mt}{mo}:{st}{so}".strip() if (mt + mo + st + so).strip() else ""
    full_clock = f"{mt}{mo}:{st}{so}.{tenths}"

    hs = str(d.get("home_score", "")).strip().rjust(2)[-2:]
    gs = str(d.get("guest_score", "")).strip().rjust(2)[-2:]
    pc = str(d.get("play_clock", "")).strip().rjust(2)[-2:]
    togo = str(d.get("to_go", "")).strip().rjust(2)[-2:]
    ball = str(d.get("ball_on", "")).strip().rjust(2)[-2:]
    down = _ch(str(d.get("down", "")).strip())
    quarter = _ch(str(d.get("period", "")).strip())
    hto = _ch(str(d.get("home_timeouts", "")).strip())
    gto = _ch(str(d.get("guest_timeouts", "")).strip())
    hposs = "<" if d.get("home_poss") else " "
    gposs = ">" if d.get("guest_poss") else " "
    ts, ts_full, ts_epoch = _timestamps(now)
    bot_hex = f"{bot:06X}"
    q_ord = d.get("period_ordinal", "") if quarter.strip() else ""

    soccer = d.get("sport") == "soccer"
    period = _ch(str(d.get("period", "")).strip())
    p_ord = d.get("period_ordinal", "") if period.strip() else ""
    base = {
        "OriginTypeId": 1, "OriginType": "Local",
        "ClockMinutesTens": mt, "ClockMinutesOnes": mo, "ClockSecondTens": st, "ClockSecondOnes": so,
        "ClockTenthsSecond": tenths, "ClockMode": mode, "Clock": clock, "FullClock": full_clock,
        "VendorSportId": int(m.get("vendor_sport_id", 0)), "EventId": 8 if soccer else 2,
        "InboundChannelNumber": "1", "ClockStatus": clock_status, "PlayClockStatus": " ",
        "BotNumberHex": bot_hex, "BotNumber": bot,
        "TimeStamp": ts, "TimeStampFull": ts_full, "TimeStampEpoch": ts_epoch,
        "GuestTeamName": guest_name, "HomeTeamName": home_name,
        "WeightedCoverage": 1.0, "PublishRate": float(m.get("publish_rate", 10)),
        "VenueName": m.get("venue_name", ""), "VenueId": 0, "VenueGeniusId": 0,
    }
    if soccer:
        hsh = str(d.get("home_shots", "")).strip().rjust(2)[-2:]
        gsh = str(d.get("guest_shots", "")).strip().rjust(2)[-2:]
        hck = str(d.get("home_corners", "")).strip()
        gck = str(d.get("guest_corners", "")).strip()
        horn = "H" if d.get("horn") else " "
        contract = dict(base, **{
            "HomeScoreTens": hs[0], "HomeScoreOnes": hs[1], "GuestScoreTens": gs[0], "GuestScoreOnes": gs[1],
            "HomeShotTens": hsh[0], "HomeShotOnes": hsh[1], "GuestShotTens": gsh[0], "GuestShotOnes": gsh[1],
            "HomeScore": _norm_score(hs), "HomePossession": " ", "GuestScore": _norm_score(gs),
            "GuestPossession": " ", "HomeShots": hsh, "HomeCornerKicks": hck, "GuestShots": gsh,
            "GuestCornerKicks": gck, "HomeSaves": "", "GuestSaves": "", "HomeTimeouts": " ", "GuestTimeouts": " ",
            "Period": period, "PeriodOrdinal": p_ord, "HomePenalties": "", "GuestPenalties": "", "Horn": horn,
        })
    else:
        contract = dict(base, **{
            "PlayClockTens": pc[0], "PlayClockOnes": pc[1],
            "HomeScoreTens": hs[0], "HomeScoreOnes": hs[1], "GuestScoreTens": gs[0], "GuestScoreOnes": gs[1],
            "ToGoTens": togo[0], "ToGoOnes": togo[1], "BallOnTens": ball[0], "BallOnOnes": ball[1],
            "PlayClock": pc, "HomeScore": _norm_score(hs), "GuestScore": _norm_score(gs),
            "ToGo": togo, "BallOn": ball, "Flag": " ", "Horn": " ",
            "HomePossession": hposs, "GuestPossession": gposs, "Possession": d.get("possession", ""),
            "HomeTimeouts": hto, "GuestTimeouts": gto, "Down": down,
            "Quarter": quarter, "QuarterOrdinal": q_ord,
            "HomeYardsRushing": "", "HomeYardsPassing": "", "HomeTotalYards": "",
            "VisitorYardsRushing": "", "VisitorYardsPassing": "", "VisitorTotalYards": "",
            "HomeTotalFirstDowns": "", "VisitorTotalFirstDowns": "",
            "HomeScoreQuarter1": "", "HomeScoreQuarter2": "", "HomeScoreQuarter3": "", "HomeScoreQuarter4": "",
            "VisitorScoreQuarter1": "", "VisitorScoreQuarter2": "", "VisitorScoreQuarter3": "",
            "VisitorScoreQuarter4": "",
        })

    sb = [" "] * 150

    def put(s, a, b, right=False):
        width = b - a + 1
        s = str(s or "")
        s = s.rjust(width)[-width:] if right else s.ljust(width)[:width]
        sb[a : b + 1] = list(s)

    put("08" if soccer else "02", 0, 1)
    if mode == ".":
        sb[2], sb[3], sb[4], sb[5] = st, so, tenths, " "
    else:
        sb[2], sb[3], sb[4], sb[5] = mt, mo, st, so
    if soccer:
        sb[11], sb[12], sb[13], sb[14], sb[15], sb[16] = hs[0], hs[1], " ", gs[0], gs[1], " "
        put(hsh.strip(), 17, 18, right=True)
        put(hck, 19, 19, right=True)
        put(gsh.strip(), 20, 21, right=True)
        put(gck, 22, 22, right=True)
        sb[29], sb[30] = period, horn
        put(home_name, 31, 38)
        put(guest_name, 39, 46)
        sb[47] = hck[-2] if len(hck) > 1 else " "
        sb[48] = gck[-2] if len(gck) > 1 else " "
    else:
        put(pc.strip(), 8, 9, right=True)
        sb[11], sb[12] = hs[0], hs[1]
        sb[14], sb[15] = gs[0], gs[1]
        sb[16], sb[17], sb[18], sb[19], sb[20] = hposs, gposs, hto, gto, down
        put(togo.strip(), 21, 22, right=True)
        put(ball.strip(), 23, 24, right=True)
        sb[25] = quarter
        put(home_name, 26, 33)
        put(guest_name, 34, 41)
    sb[116], sb[117], sb[118] = clock_status, mode, " "
    sb[131] = "1"
    put(bot_hex, 132, 137)
    put(ts, 138, 149)
    return json.dumps(contract, ensure_ascii=False, separators=(",", ":")), "".join(sb)


# --------------------------------------------------------------------------- MQTT wire helpers
def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _mqtt_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _topic_match(filt: str, topic: str) -> bool:
    if filt == topic:
        return True
    fp, tp = filt.split("/"), topic.split("/")
    for i, f in enumerate(fp):
        if f == "#":
            return not (i == 0 and topic.startswith("$"))
        if i >= len(tp):
            return False
        if f == "+":
            if i == 0 and tp[0].startswith("$"):
                return False
            continue
        if f != tp[i]:
            return False
    return len(fp) == len(tp)


class _Stream:
    """Byte stream over plain TCP or WebSocket, with readexactly/write."""

    def __init__(self, reader, writer, websocket=False):
        self.r, self.w, self.ws = reader, writer, websocket
        self.buf = bytearray()

    async def readexactly(self, n: int) -> bytes:
        if not self.ws:
            return await self.r.readexactly(n)
        while len(self.buf) < n:
            await self._ws_frame()
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    async def _ws_frame(self):
        h = await self.r.readexactly(2)
        op, ln, masked = h[0] & 0x0F, h[1] & 0x7F, h[1] & 0x80
        if ln == 126:
            ln = struct.unpack("!H", await self.r.readexactly(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", await self.r.readexactly(8))[0]
        mask = await self.r.readexactly(4) if masked else b"\0\0\0\0"
        data = bytearray(await self.r.readexactly(ln))
        if masked:
            for i in range(ln):
                data[i] ^= mask[i % 4]
        if op in (0, 1, 2):
            self.buf += data
        elif op == 8:
            raise ConnectionError("websocket closed")
        elif op == 9:
            self._raw_ws(0xA, bytes(data))

    def _raw_ws(self, op, data: bytes):
        ln = len(data)
        if ln < 126:
            hdr = bytes([0x80 | op, ln])
        elif ln < 65536:
            hdr = bytes([0x80 | op, 126]) + struct.pack("!H", ln)
        else:
            hdr = bytes([0x80 | op, 127]) + struct.pack("!Q", ln)
        self.w.write(hdr + data)

    def write(self, data: bytes):
        if self.ws:
            self._raw_ws(0x2, data)
        else:
            self.w.write(data)

    def close(self):
        try:
            self.w.close()
        except Exception:
            pass


class _Client:
    def __init__(self, stream: _Stream, peer):
        self.s, self.peer = stream, peer
        self.level = 4
        self.subs: dict[str, int] = {}
        self.client_id = ""

    def send(self, data: bytes):
        try:
            self.s.write(data)
        except Exception:
            pass

    def publish(self, topic: str, payload: bytes, retain=False):
        vh = _mqtt_str(topic) + (b"\x00" if self.level >= 5 else b"")
        self.send(bytes([0x30 | (1 if retain else 0)]) + _varint(len(vh) + len(payload)) + vh + payload)


class MiniBroker:
    def __init__(self, host="0.0.0.0", tcp_port=1883, ws_port=8083, log=print):
        self.host, self.tcp_port, self.ws_port, self.log = host, tcp_port, ws_port, log
        self.clients: set[_Client] = set()
        self.retained: dict[str, bytes] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self.status = "starting"

    # ---- public (thread-safe)
    def start(self):
        threading.Thread(target=self._thread, daemon=True, name="mqtt-broker").start()

    def publish(self, topic: str, payload: bytes | str, retain=True):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        if self.loop:
            self.loop.call_soon_threadsafe(self._publish, topic, payload, retain)

    @property
    def client_count(self):
        return len(self.clients)

    # ---- internals
    def _thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())
        self.loop.run_forever()

    async def _serve(self):
        ok = []
        try:
            await asyncio.start_server(self._on_tcp, self.host, self.tcp_port)
            ok.append(f"mqtt://:{self.tcp_port}")
        except OSError as e:
            self.log(f"MQTT: can't listen on {self.tcp_port}: {e} (is ScoreConnect/Mosquitto still running?)")
        if self.ws_port:
            try:
                await asyncio.start_server(self._on_ws, self.host, self.ws_port)
                ok.append(f"ws://:{self.ws_port}/mqtt")
            except OSError as e:
                self.log(f"MQTT: can't listen on {self.ws_port}: {e}")
        self.status = ("listening " + " + ".join(ok)) if ok else "error: ports in use"
        if ok:
            self.log("MQTT broker listening on " + " and ".join(ok))

    def _publish(self, topic, payload, retain):
        if retain:
            self.retained[topic] = payload
        for c in list(self.clients):
            if any(_topic_match(f, topic) for f in c.subs):
                c.publish(topic, payload)

    async def _on_tcp(self, r, w):
        await self._session(_Stream(r, w), w.get_extra_info("peername"))

    async def _on_ws(self, r, w):
        try:
            req = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 10)
        except Exception:
            w.close()
            return
        headers = {}
        for line in req.decode("latin-1").split("\r\n")[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        key = headers.get("sec-websocket-key")
        if not key:
            w.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            w.close()
            return
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        protos = [p.strip() for p in headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
        proto = next((p for p in protos if p in ("mqtt", "mqttv3.1")), protos[0] if protos else "")
        resp = ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n" + (f"Sec-WebSocket-Protocol: {proto}\r\n" if proto else "") + "\r\n")
        w.write(resp.encode())
        await self._session(_Stream(r, w, websocket=True), w.get_extra_info("peername"))

    async def _read_packet(self, s: _Stream):
        h = (await s.readexactly(1))[0]
        mult, ln = 1, 0
        for _ in range(4):
            b = (await s.readexactly(1))[0]
            ln += (b & 0x7F) * mult
            mult *= 128
            if not b & 0x80:
                break
        body = await s.readexactly(ln) if ln else b""
        return h, body

    @staticmethod
    def _skip_props(body: bytes, i: int) -> int:
        mult, ln = 1, 0
        while True:
            b = body[i]
            i += 1
            ln += (b & 0x7F) * mult
            mult *= 128
            if not b & 0x80:
                break
        return i + ln

    async def _session(self, s: _Stream, peer):
        c = _Client(s, peer)
        try:
            h, body = await asyncio.wait_for(self._read_packet(s), 15)
            if h >> 4 != 1:
                raise ConnectionError("expected CONNECT")
            pl = struct.unpack("!H", body[:2])[0]
            c.level = body[2 + pl]
            i = 2 + pl + 1 + 1 + 2
            if c.level >= 5:
                i = self._skip_props(body, i)
            cl = struct.unpack("!H", body[i : i + 2])[0]
            c.client_id = body[i + 2 : i + 2 + cl].decode("utf-8", "replace")
            s.write(b"\x20\x03\x00\x00\x00" if c.level >= 5 else b"\x20\x02\x00\x00")
            self.clients.add(c)
            self.log(f"MQTT client connected: {c.client_id or '?'} from {peer[0] if peer else '?'}")
            while True:
                h, body = await self._read_packet(s)
                t = h >> 4
                if t == 8:  # SUBSCRIBE
                    pid = body[:2]
                    i = 2
                    if c.level >= 5:
                        i = self._skip_props(body, i)
                    codes, new = bytearray(), []
                    while i < len(body):
                        tl = struct.unpack("!H", body[i : i + 2])[0]
                        topic = body[i + 2 : i + 2 + tl].decode("utf-8", "replace")
                        i += 2 + tl + 1
                        c.subs[topic] = 0
                        codes.append(0)
                        new.append(topic)
                    vh = pid + (b"\x00" if c.level >= 5 else b"") + bytes(codes)
                    s.write(b"\x90" + _varint(len(vh)) + vh)
                    for f in new:
                        for topic, payload in self.retained.items():
                            if _topic_match(f, topic):
                                c.publish(topic, payload, retain=True)
                elif t == 10:  # UNSUBSCRIBE
                    pid = body[:2]
                    i = 2
                    if c.level >= 5:
                        i = self._skip_props(body, i)
                    n = 0
                    while i < len(body):
                        tl = struct.unpack("!H", body[i : i + 2])[0]
                        c.subs.pop(body[i + 2 : i + 2 + tl].decode("utf-8", "replace"), None)
                        i += 2 + tl
                        n += 1
                    vh = pid + ((b"\x00" + b"\x00" * n) if c.level >= 5 else b"")
                    s.write(b"\xB0" + _varint(len(vh)) + vh)
                elif t == 12:  # PINGREQ
                    s.write(b"\xD0\x00")
                elif t == 14:  # DISCONNECT
                    break
                elif t == 3:  # PUBLISH from a client: forward it
                    qos = (h >> 1) & 3
                    tl = struct.unpack("!H", body[:2])[0]
                    topic = body[2 : 2 + tl].decode("utf-8", "replace")
                    i = 2 + tl
                    pid = b""
                    if qos:
                        pid = body[i : i + 2]
                        i += 2
                    if c.level >= 5:
                        i = self._skip_props(body, i)
                    self._publish(topic, body[i:], bool(h & 1))
                    if qos == 1:
                        s.write(b"\x40\x02" + pid)
                    elif qos == 2:
                        s.write(b"\x50\x02" + pid)
                elif t == 6:  # PUBREL
                    s.write(b"\x70\x02" + body[:2])
        except (asyncio.IncompleteReadError, ConnectionError, OSError, asyncio.TimeoutError, IndexError, struct.error):
            pass
        finally:
            if c in self.clients:
                self.clients.discard(c)
                self.log(f"MQTT client disconnected: {c.client_id or '?'}")
            s.close()


class MqttPublisherClient:
    """Publish into an existing broker instead of hosting one (MQTT 3.1.1, QoS 0)."""

    def __init__(self, host, port=1883, client_id="ScoreReader", log=print):
        self.host, self.port, self.client_id, self.log = host, port, client_id, log
        self.sock = None
        self.lock = threading.Lock()
        self.status = "connecting"
        self.client_count = 0
        threading.Thread(target=self._pinger, daemon=True).start()

    def start(self):
        pass

    def _connect(self):
        s = socket.create_connection((self.host, self.port), timeout=5)
        vh = _mqtt_str("MQTT") + b"\x04\x02" + struct.pack("!H", 30)
        pl = _mqtt_str(self.client_id)
        s.sendall(b"\x10" + _varint(len(vh) + len(pl)) + vh + pl)
        ack = s.recv(4)
        if len(ack) < 4 or ack[0] != 0x20 or ack[3] != 0:
            raise ConnectionError(f"broker refused connection {ack!r}")
        s.settimeout(None)
        threading.Thread(target=self._drain, args=(s,), daemon=True).start()
        self.sock = s
        self.status = f"connected to {self.host}:{self.port}"
        self.log(f"MQTT: publishing to broker {self.host}:{self.port}")

    @staticmethod
    def _drain(s):
        try:
            while s.recv(1024):
                pass
        except OSError:
            pass

    def _pinger(self):
        while True:
            time.sleep(15)
            with self.lock:
                if self.sock:
                    try:
                        self.sock.sendall(b"\xC0\x00")
                    except OSError:
                        self.sock = None

    def publish(self, topic, payload, retain=False):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        vh = _mqtt_str(topic)
        pkt = bytes([0x30 | (1 if retain else 0)]) + _varint(len(vh) + len(payload)) + vh + payload
        with self.lock:
            try:
                if self.sock is None:
                    self._connect()
                self.sock.sendall(pkt)
            except OSError as e:
                self.status = f"error: {e}"
                self.sock = None


class SportzcastMqttOutput:
    """Glue: builds payloads from ScoreReader data and publishes on Sportzcast topics."""

    def __init__(self, cfg: dict, log=print):
        self.cfg = cfg
        m = cfg.get("mqtt", {})
        self.min_interval = 1.0 / max(1.0, float(m.get("publish_rate", 10)))
        self.heartbeat = float(m.get("heartbeat_seconds", 1.0))
        self.publish_raw = bool(m.get("publish_raw", True))
        if m.get("mode", "broker") == "client":
            self.out = MqttPublisherClient(m.get("broker_host", "127.0.0.1"), int(m.get("broker_port", 1883)), log=log)
        else:
            self.out = MiniBroker(m.get("bind", "0.0.0.0"), int(m.get("tcp_port", 1883)), int(m.get("ws_port", 8083)), log=log)
        self.latest: dict | None = None
        self.last_sent = 0.0
        self.last_json = ""
        self.lock = threading.Lock()
        self.event = threading.Event()

    @property
    def bot(self) -> int:
        """Read live from the config, so a new bot number from Settings applies immediately."""
        try:
            return int(self.cfg.get("mqtt", {}).get("bot_number", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def status(self):
        n = self.out.client_count
        return f"{self.out.status} · {n} client{'s' if n != 1 else ''} · bot/{self.bot}/json|sbdata|raw"

    def start(self):
        self.out.start()
        threading.Thread(target=self._loop, daemon=True, name="mqtt-publisher").start()

    def update(self, data: dict):
        with self.lock:
            self.latest = dict(data)
        self.event.set()

    def raw(self, chunk: bytes):
        if self.publish_raw:
            self.out.publish(f"bot/{self.bot}/raw", chunk, retain=False)

    def _loop(self):
        while True:
            self.event.wait(self.heartbeat)
            self.event.clear()
            with self.lock:
                d = self.latest
            if d is None:
                continue
            wait = self.min_interval - (time.time() - self.last_sent)
            if wait > 0:
                time.sleep(wait)
                with self.lock:
                    d = self.latest
            try:
                js, sb = build_payloads(d, self.cfg)
            except Exception as e:  # never kill the publisher
                print(f"MQTT payload error: {e}")
                continue
            self.out.publish(f"bot/{self.bot}/json", js)
            self.out.publish(f"bot/{self.bot}/sbdata", sb)
            self.last_sent = time.time()
            self.last_json = js
