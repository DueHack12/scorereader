import io
import json
import socket
import sys
import urllib.request

import menubar
import scorereader as sr


def test_status_line_live_and_demo():
    state = {"source_state": "connected", "source_saved": True, "source": "scorelink",
             "data": {"period_ordinal": "2nd", "clock": "4:32", "home_score": "14", "guest_score": "21",
                      "home_abbr": "EAG", "guest_name": "TIGERS"}}
    assert menubar.status_line(state) == "Connected · 2nd 4:32 · EAG 14 – 21 TIGERS"
    state.update(source="demo", source_saved=False)
    assert menubar.status_line(state).startswith("DEMO · ")
    assert menubar.status_line({}) == "Starting"


def test_menubar_only_offered_on_mac():
    if sys.platform != "darwin":
        assert menubar.available() is False


def test_window_title_escape_on_terminals(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    if sys.platform == "win32":
        sr.set_window_title("ScoreReader test")  # must not raise
        return
    out = Tty()
    monkeypatch.setattr(sys, "stdout", out)
    sr.set_window_title("ScoreReader 2.0.0")
    assert out.getvalue() == "\x1b]0;ScoreReader 2.0.0\x07"


def test_logo_assets_exist():
    for name in ("icon.svg", "icon.png", "icon.ico", "icon.icns", "menubar.png", "menubar@2x.png"):
        assert (sr.os.path.exists(sr.os.path.join(sr.ASSETS_DIR, name))), name


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_start_serves_favicon_and_shutdown_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "CONFIG_PATH", str(tmp_path / "cfg.json"))
    monkeypatch.setattr(sr, "LOG_DIR", str(tmp_path / "logs"))
    port = _free_port()
    cfg = sr.deep_merge(sr.DEFAULT_CONFIG, {"source": "demo", "http_port": port, "record_raw": False,
                                            "mqtt": {"enabled": False}})
    app = sr.App(cfg, saved=json.loads(json.dumps(cfg)))
    app.start()
    try:
        assert app.dashboard_url == f"http://localhost:{port}/"
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/favicon.svg")
        assert r.headers["Content-Type"] == "image/svg+xml" and b"<svg" in r.read()
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read()
        assert b'rel="icon" href="/favicon.svg"' in page
    finally:
        app.shutdown()
        app.shutdown()  # second call is a no-op
    assert app.stop.is_set() and app.reader.stop.is_set()


def test_log_survives_a_closed_console_and_detach_writes_to_file(tmp_path, monkeypatch):
    class Closed:
        def write(self, *_):
            raise OSError(5, "Input/output error")

        def flush(self):
            raise OSError(5, "Input/output error")
    monkeypatch.setattr(sys, "stdout", Closed())
    sr.log("window gone")  # must not raise
    assert sr.STATUS.logs[-1].endswith("window gone")
    path = tmp_path / "logs" / "scorereader.log"
    monkeypatch.setattr(sys, "stderr", sys.stderr)  # restored after the test
    sr.detach_console(str(path))
    sr.log("still running")
    sys.stdout.flush()
    assert "still running" in path.read_text()
