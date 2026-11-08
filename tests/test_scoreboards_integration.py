"""ScoreReader + the multi-vendor scoreboards package."""
import json
import random

import pytest

import scoreboards
import scorereader as sr
import sportzcast_mqtt as sm
from scoreboards import hardware
from scoreboards.pic55aa import CODE_NEVCO, make_frame


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "CONFIG_PATH", str(tmp_path / "scorereader_config.json"))
    monkeypatch.setattr(sr, "STATE_PATH", str(tmp_path / "state.bin"))
    monkeypatch.setattr(sr, "LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def make_app(protocol="", **over):
    saved = sr.deep_merge(sr.DEFAULT_CONFIG, {"mqtt": {"enabled": False}, "scoreboard": {"protocol": protocol}, **over})
    return sr.App(json.loads(json.dumps(saved)), saved=saved)


def test_every_catalog_layout_with_a_scoreconnect_decoder_is_implemented():
    impl = scoreboards.protocols()
    assert not scoreboards.load_errors()
    missing = {r["enum"] for r in scoreboards.catalog()["vendor_sports"]} - set(impl)
    assert missing <= {"SportzcastSBData_Generic"}  # a database row ScoreConnect has no decoder for either


def test_every_protocol_survives_random_bytes_and_maps_to_output():
    rnd = random.Random(7)
    for pid in sorted(scoreboards.protocols()):
        p = scoreboards.create(pid)
        for _ in range(20):
            p.feed(bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 120))))
        d = sr.contract_to_data(p.contract_name, p.snapshot())
        assert isinstance(d, dict), pid


def test_builtin_path_is_unchanged_when_no_brand_is_chosen(paths):
    app = make_app()
    assert app.vendor is None and app.bot_plan() == {}
    assert app.reader.vendor is None


def test_brand_decoder_feeds_outputs(paths):
    app = make_app("PIC55AA_Nevco_Basketball", teams={"home_name": "PREP"})
    assert app.vendor is not None and app.reader.vendor is app.vendor
    app.reader._feed(b"\x00garbage" + make_frame(CODE_NEVCO, bytes(40)))
    d = app.build_data()
    assert d["protocol"] == "PIC55AA_Nevco_Basketball" and d["home_name"] == "PREP"
    assert app.state_json()["contract"][0]["v"] == app.vendor.contract_name


def test_bot_plan_for_daktronics_matches_the_known_working_setup(paths):
    app = make_app("Daktronics_Football")
    plan = app.bot_plan()
    assert plan["commands"] == [">M0X0X", ">T0", ">D0", ">M8I1N"] and plan["baud"] == 19200
    assert plan["configure"] is True
    plan["on_configured"]()
    assert make_app("Daktronics_Football", scorelink=app.saved["scorelink"]).bot_plan()["configure"] is False


def test_bot_plan_follows_the_wiring_choice(paths):
    configs = hardware.configs_for_vendor("Daktronics")
    assert len(configs) >= 2
    app = make_app("Daktronics_Football", scoreboard={"protocol": "Daktronics_Football", "connection": 1})
    assert configs[1]["connection"] in app.bot_plan()["label"]


def test_scoreboard_setting_validated_and_restarts_source(paths):
    app = make_app()
    assert not app.apply_settings({"scoreboard.protocol": "Nope_Basketball"})["ok"]
    assert app.apply_settings({"scoreboard.protocol": "OES_Basketball"})["ok"]
    assert app.vendor is not None and app.reader.vendor is app.vendor
    assert app.apply_settings({"scoreboard.protocol": ""})["ok"] and app.vendor is None


def test_settings_json_lists_brands(paths):
    s = make_app().settings_json()
    names = {b["name"] for b in s["scoreboards"]}
    assert {"Daktronics", "Nevco", "Fairplay", "OES"} <= names
    nevco = next(b for b in s["scoreboards"] if b["name"] == "Nevco")
    assert any(x["id"] == "PIC55AA_Nevco_Basketball" for x in nevco["sports"])


def test_scorelink_session_sends_brand_commands_with_retries():
    sent = []

    class Ser:
        baudrate = 0

        def __init__(self):
            self.out = b""

        def reset_input_buffer(self):
            pass

        def write(self, b):
            q = b.decode().strip()
            sent.append(q)
            if q == ">T?" and sent.count(">T?") == 2:  # 1st is the probe
                self.out = b"\r"  # first read-back of >T0 fails -> must retry
            elif q.endswith("?"):
                self.out = ({">M?": ">M0X0X", ">M8?": ">M8I1N"}.get(q, q[:2] + "0")).encode() + b"\r"
            else:
                self.out = b"\r"

        def flush(self):
            pass

        def read(self, n):
            c, self.out = self.out[:1], self.out[1:]
            return c

    class Mcp:
        def set_gp2(self, v):
            pass

    cfg = sr.deep_merge(sr.DEFAULT_CONFIG, {})
    ser = Ser()
    info = sr.scorelink_session(cfg, ser, Mcp(), True, False, commands=[">M0X0X", ">T0", ">D0", ">M8I1N"], data_baud=19200)
    writes = [c for c in sent if not c.endswith("?")]
    assert writes == [">M0X0X", ">T0", ">T0", ">D0", ">M8I1N"]
    assert info["configured"] is True and ser.baudrate == 19200


def test_mqtt_uses_contract_payloads_for_brand_decoders(paths):
    app = make_app("PIC55AA_Nevco_Basketball")
    app.reader._feed(make_frame(CODE_NEVCO, bytes(40)))
    out = sm.SportzcastMqttOutput(sr.deep_merge(sr.DEFAULT_CONFIG, {"mqtt": {"bot_number": 3}}))
    js, sb = out._payloads(app.build_data(), app.vendor_contract())
    assert len(sb) == 150 and json.loads(js)["BotNumber"] == 3
