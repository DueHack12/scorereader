import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import scorereader as sr
import sportzcast_mqtt as sm
from conftest import make_cl_frame as frame


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "CONFIG_PATH", str(tmp_path / "scorereader_config.json"))
    monkeypatch.setattr(sr, "STATE_PATH", str(tmp_path / "state.bin"))
    monkeypatch.setattr(sr, "LOG_DIR", str(tmp_path / "logs"))
    return tmp_path


def make_app(saved_over=None, cli_over=None):
    saved = sr.deep_merge(sr.DEFAULT_CONFIG, {"mqtt": {"enabled": False}, **(saved_over or {})})
    cfg = sr.deep_merge(json.loads(json.dumps(saved)), cli_over or {})
    return sr.App(cfg, saved=saved)


def on_disk():
    with open(sr.CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_command_line_overrides_are_never_saved(paths):
    app = make_app(cli_over={"source": "demo", "record_raw": False, "vmix": {"enabled": True}})
    assert app.apply_settings({"sport": "soccer"})["ok"]
    saved = on_disk()
    assert saved["sport"] == "soccer"
    assert saved["source"] == "scorelink" and saved["record_raw"] is True and saved["vmix"]["enabled"] is False
    assert app.cfg["source"] == "demo"  # the running session keeps its options


def test_demo_and_replay_are_session_only(paths):
    app = make_app()
    assert app.apply_settings({"source": "demo"})["ok"]
    assert app.cfg["source"] == "demo" and app.live_source() == "scorelink"
    assert app.apply_settings({"teams.home_name": "PREP"})["ok"]
    assert on_disk()["source"] == "scorelink"
    assert app.apply_settings({"source": "serial"})["ok"]
    assert on_disk()["source"] == "serial"


def test_config_file_left_in_demo_by_old_version_goes_back_to_scorebot(paths):
    app = make_app(saved_over={"source": "demo"})
    assert app.live_source() == "scorelink"


def test_invalid_settings_change_nothing(paths):
    app = make_app()
    res = app.apply_settings({"teams.home_name": "PREP", "vmix.port": "99999", "nope": 1, "teams.home_color": "blue"})
    assert not res["ok"] and set(res["errors"]) == {"vmix.port", "nope", "teams.home_color"}
    assert app.cfg["teams"]["home_name"] == "" and not (paths / "scorereader_config.json").exists()
    assert not app.apply_settings({"replay_file": "../../etc/passwd"})["ok"]


def test_setting_types_and_restart_flags(paths):
    app = make_app()
    res = app.apply_settings({"mqtt.bot_number": "175", "teams.home_color": "#1e3a8a", "record_raw": "false",
                              "http_port": 9000})
    assert res["ok"] and res["restart_needed"] == ["http_port"]
    assert app.cfg["mqtt"]["bot_number"] == 175 and app.cfg["teams"]["home_color"] == "#1E3A8A"
    assert app.cfg["record_raw"] is False


def test_source_change_clears_old_values(paths):
    app = make_app()
    app.cl.feed(frame(0xFE, b"66015000430") + frame(15, bytes(20)))
    assert app.cl.packets
    old = app.cl
    assert app.apply_settings({"source": "serial"})["ok"]
    assert app.cl is not old and app.cl.packets == 0 and app.build_data()["home_score"] == "0"


def test_team_names_in_current_loop_output(paths):
    app = make_app(saved_over={"teams": {"home_name": "FAIRFIELD PREP", "guest_abbr": "VIS", "home_color": "#AA0000"}})
    app.cl.feed(frame(0xFE, b"66015000430"))
    d = app.build_data()
    assert d["home_name"] == "FAIRFIELD PREP" and d["guest_name"] == "GUEST"
    assert d["guest_abbr"] == "VIS" and d["home_color"] == "#AA0000"
    js, sb = sm.build_payloads(d, app.cfg)
    assert json.loads(js)["HomeTeamName"] == "FAIRFIELD PREP" and sb[26:34] == "FAIRFIEL"


def test_team_name_fallbacks(paths):
    legacy = make_app(saved_over={"mqtt": {"enabled": False, "home_team_name": "JESUITS"}})
    assert legacy.build_data()["home_name"] == "JESUITS"
    rtd = make_app()
    rtd.decoder.feed(sr.encode_rtd_packet(47, "CONSOLE NAME".ljust(20)))  # RTD football home name (pos 48)
    assert rtd.build_data()["home_name"] == "CONSOLE NAME"
    rtd.apply_settings({"teams.home_name": "OVERRIDE"})
    assert rtd.build_data()["home_name"] == "OVERRIDE"


def test_state_not_saved_by_default(paths):
    assert sr.DEFAULT_CONFIG["save_state"] is False
    app = make_app()
    t = threading.Thread(target=app.update_loop, daemon=True)
    t.start()
    app.decoder.feed(sr.encode_rtd_packet(0, " 4:32"))
    time.sleep(0.3)
    app.stop.set()
    t.join(2)
    assert not (paths / "state.bin").exists()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_settings_http_api(paths):
    app = make_app()
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), app.make_handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    try:
        s = json.load(urllib.request.urlopen(base + "/api/settings"))
        assert s["values"]["source"] == "scorelink" and "demo" in s["choices"]["source"]

        def post(body, header=True):
            req = urllib.request.Request(base + "/api/settings", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", **({"X-ScoreReader": "1"} if header else {})})
            return urllib.request.urlopen(req)

        with pytest.raises(urllib.error.HTTPError) as e:
            post({"teams.home_name": "X"}, header=False)
        assert e.value.code == 403 and app.cfg["teams"]["home_name"] == ""
        assert json.load(post({"teams.home_name": "PREP"}))["ok"] and on_disk()["teams"]["home_name"] == "PREP"
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"baud": "fast"})
        assert e.value.code == 400
    finally:
        srv.shutdown()
