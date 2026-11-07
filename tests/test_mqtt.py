import json
import socket
import struct
import time

import pytest

import sportzcast_mqtt as sm

CFG = {"mqtt": {"bot_number": 175, "home_team_name": "PREP", "guest_team_name": "VISITORS"}}


def test_football_payloads():
    d = {"sport": "football", "clock": "4:32", "clock_running": True, "play_clock": "25", "home_score": "14",
         "guest_score": "7", "period": "2", "period_ordinal": "2nd", "home_poss": True, "guest_poss": False,
         "possession": "H", "home_timeouts": "3", "guest_timeouts": "2", "down": "3rd", "to_go": "7", "ball_on": "35"}
    js, sb = sm.build_payloads(d, CFG, now=1_780_000_000.0)
    j = json.loads(js)
    assert j["EventId"] == 2 and j["Clock"] == "4:32" and j["ClockStatus"] == "R"
    assert (j["HomeScore"], j["GuestScore"], j["Quarter"], j["QuarterOrdinal"]) == ("14", "7", "2", "2nd")
    assert (j["HomePossession"], j["Possession"], j["Down"], j["ToGo"], j["BallOn"]) == ("<", "H", "3", " 7", "35")
    assert j["BotNumber"] == 175 and j["BotNumberHex"] == "0000AF" and len(j["TimeStamp"]) == 12
    assert len(sb) == 150
    assert sb[0:2] == "02" and sb[2:6] == " 432" and sb[8:10] == "25"
    assert sb[11:13] == "14" and sb[14:16] == " 7" and sb[16] == "<" and sb[20] == "3" and sb[25] == "2"
    assert sb[26:34] == "PREP    " and sb[116:118] == "R:" and sb[132:138] == "0000AF"


def test_soccer_payloads():
    d = {"sport": "soccer", "clock": "60:00", "clock_running": False, "home_score": "5", "guest_score": "6",
         "period": "1", "period_ordinal": "1st", "home_shots": "1", "guest_shots": "12",
         "home_corners": "3", "guest_corners": "14", "horn": False}
    js, sb = sm.build_payloads(d, CFG)
    j = json.loads(js)
    assert j["EventId"] == 8 and j["Period"] == "1" and j["PeriodOrdinal"] == "1st"
    assert (j["HomeCornerKicks"], j["GuestCornerKicks"], j["GuestShots"]) == ("3", "14", "12")
    assert "Down" not in j
    assert sb[0:2] == "08" and sb[11:13] == " 5" and sb[17:19] == " 1" and sb[19] == "3"
    assert sb[22] == "4" and sb[48] == "1" and sb[29] == "1" and sb[31:39] == "PREP    "


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _mqtt_str(t):
    b = t.encode()
    return struct.pack("!H", len(b)) + b


def test_broker_tcp_subscribe_and_receive():
    port = _free_port()
    b = sm.MiniBroker("127.0.0.1", port, 0, log=lambda *_: None)
    b.start()
    for _ in range(50):
        if b.status.startswith("listening"):
            break
        time.sleep(0.05)
    b.publish("bot/0/json", '{"Clock":"1:00"}')  # retained -> delivered on subscribe
    c = socket.create_connection(("127.0.0.1", port), timeout=3)
    vh = _mqtt_str("MQTT") + b"\x04\x02\x00\x3c"
    pl = _mqtt_str("pytest")
    c.sendall(b"\x10" + bytes([len(vh) + len(pl)]) + vh + pl)
    assert c.recv(4) == b"\x20\x02\x00\x00"
    sub = b"\x00\x01" + _mqtt_str("bot/+/json") + b"\x00"
    c.sendall(b"\x82" + bytes([len(sub)]) + sub)
    assert c.recv(5) == b"\x90\x03\x00\x01\x00"
    data = c.recv(256)
    assert data[0] & 0xF0 == 0x30 and b"bot/0/json" in data and b'"Clock":"1:00"' in data
    b.publish("bot/0/json", '{"Clock":"0:59"}')
    assert b'"Clock":"0:59"' in c.recv(256)
    c.close()


def test_broker_websocket_with_paho():
    mqtt = pytest.importorskip("paho.mqtt.client")
    tcp, ws = _free_port(), _free_port()
    b = sm.MiniBroker("127.0.0.1", tcp, ws, log=lambda *_: None)
    b.start()
    time.sleep(0.3)
    got = []
    cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets", client_id="ws-pytest")
    cl.ws_set_options(path="/mqtt")
    cl.on_message = lambda c, u, m: got.append((m.topic, m.payload))
    cl.connect("127.0.0.1", ws, 30)
    cl.subscribe("bot/#")
    cl.loop_start()
    time.sleep(0.5)
    b.publish("bot/7/sbdata", "02" + " " * 148)
    for _ in range(40):
        if got:
            break
        time.sleep(0.05)
    cl.loop_stop()
    assert got and got[0][0] == "bot/7/sbdata"


@pytest.mark.parametrize("filt,topic,ok", [
    ("bot/+/json", "bot/12/json", True), ("bot/#", "bot/1/raw", True), ("bot/1/json", "bot/2/json", False),
    ("#", "$SYS/x", False), ("bot/+", "bot/1/json", False)])
def test_topic_match(filt, topic, ok):
    assert sm._topic_match(filt, topic) is ok
