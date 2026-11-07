import json
import os
import sys
import time
import urllib.request

import scorereader as sr


def test_demo_end_to_end(tmp_path, monkeypatch):
    """Demo source -> decoder -> HTTP data.json."""
    monkeypatch.setattr(sr, "STATE_PATH", str(tmp_path / "state.bin"))
    cfg = sr.deep_merge(sr.DEFAULT_CONFIG, {"source": "demo", "http_port": 18799, "record_raw": False,
                                            "mqtt": {"enabled": False}})
    app = sr.App(cfg)
    import threading
    threading.Thread(target=app.run, daemon=True).start()
    d = None
    for _ in range(40):
        time.sleep(0.25)
        try:
            d = json.load(urllib.request.urlopen("http://127.0.0.1:18799/data.json"))[0]
            if d.get("clock"):
                break
        except OSError:
            pass
    app.stop.set()
    assert d and d["clock"] and d["home_name"] == "FAIRFIELD PREP" and d["possession"] in ("H", "V")
