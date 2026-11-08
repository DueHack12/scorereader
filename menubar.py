"""ScoreReader's Mac menu bar icon.

Shows the live status and score, and offers Open dashboard, Re-init bot, Demo mode, Open logs folder and Quit.
ScoreReader also shows its log in the Terminal window; closing that window leaves ScoreReader running in the menu
bar (the log continues in logs/scorereader.log). Quit from the menu, or Ctrl+C in the Terminal, stops it. Needs ``rumps`` (installed on macOS by
requirements.txt and bundled in the Mac download); without it ScoreReader runs exactly as before.
"""
from __future__ import annotations

import os
import sys
import webbrowser


def available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import importlib.util

        return importlib.util.find_spec("rumps") is not None
    except Exception:
        return False


def status_line(state: dict) -> str:
    """One short line for the top of the menu, e.g. "Connected · 2nd 4:32 · HOME 14 – 21 GUEST"."""
    src = str(state.get("source_state", "")).capitalize() or "Starting"
    if not state.get("source_saved", True):
        src = "DEMO" if state.get("source") == "demo" else "REPLAY"
    d = state.get("data") or {}
    parts = [src]
    clock = " ".join(x for x in (str(d.get("period_ordinal") or ""), str(d.get("clock") or "")) if x).strip()
    if clock:
        parts.append(clock)
    if "home_score" in d:
        parts.append(f"{d.get('home_abbr') or d.get('home_name') or 'HOME'} {d.get('home_score', '0')} – "
                     f"{d.get('guest_score', '0')} {d.get('guest_abbr') or d.get('guest_name') or 'GUEST'}")
    return " · ".join(parts)


def run(app) -> None:
    """Run the menu bar icon on the main thread until Quit (app must already be started)."""
    import rumps

    import scorereader as sr

    icon = os.path.join(sr.ASSETS_DIR, "menubar.png")

    class MenuBar(rumps.App):
        def __init__(self):
            super().__init__("ScoreReader", icon=icon if os.path.exists(icon) else None, template=True,
                             quit_button=None)
            self.status = rumps.MenuItem("Starting…")
            self.demo = rumps.MenuItem("Demo mode", callback=self.toggle_demo)
            self.menu = [self.status, None, rumps.MenuItem("Open dashboard", callback=self.open_dashboard),
                         rumps.MenuItem("Re-init bot", callback=self.reinit), self.demo, None,
                         rumps.MenuItem("Open logs folder", callback=self.open_logs),
                         rumps.MenuItem("Quit ScoreReader", callback=self.quit)]
            self._set_dock_icon()
            self._timer = rumps.Timer(self.refresh, 1)  # refresh the status line once a second
            self._timer.start()

        @staticmethod
        def _set_dock_icon():
            """Show the ScoreReader logo (not Python's) in the Dock and app switcher while it runs."""
            try:
                from AppKit import NSApplication, NSImage

                png = os.path.join(sr.ASSETS_DIR, "icon.png")
                img = NSImage.alloc().initWithContentsOfFile_(png)
                if img is not None:
                    NSApplication.sharedApplication().setApplicationIconImage_(img)
            except Exception:
                pass

        def refresh(self, _):
            try:
                state = app.state_json()
                self.status.title = status_line(state)
                self.demo.state = 1 if state.get("source") == "demo" else 0
            except Exception:
                pass
            if app.stop.is_set():
                rumps.quit_application()

        def open_dashboard(self, _):
            webbrowser.open(app.dashboard_url)

        def open_logs(self, _):
            os.makedirs(sr.LOG_DIR, exist_ok=True)
            os.system(f'open "{sr.LOG_DIR}"')

        def reinit(self, _):
            app.reader.reinit_request.set()
            sr.log("Re-init requested from the menu bar")

        def toggle_demo(self, _):
            app.apply_settings({"source": app.live_source() if app.cfg["source"] == "demo" else "demo"})

        def quit(self, _):
            sr.log("Stopping…")
            app.shutdown()
            rumps.quit_application()

    import signal

    def _stop(*_):  # Ctrl+C / system shutdown: the 1-second timer sees this and quits
        app.stop.set()

    def _window_closed(*_):  # Terminal window closed: keep running in the menu bar, log to a file instead
        sr.detach_console(LOG_FILE)
        sr.log(f"Terminal window closed; ScoreReader keeps running in the menu bar (log: {LOG_FILE})")

    LOG_FILE = os.path.join(sr.LOG_DIR, "scorereader.log")
    for sig, handler in (("SIGINT", _stop), ("SIGTERM", _stop), ("SIGHUP", _window_closed)):
        if hasattr(signal, sig):
            signal.signal(getattr(signal, sig), handler)
    _rename_process("ScoreReader")
    try:
        MenuBar().run()
    finally:
        app.shutdown()


def _rename_process(name: str) -> None:
    """When run from source the process is Python, so the Dock/app menu would say "Python". Renaming the bundle
    name before the app starts fixes that where macOS allows it; a packaged ScoreReader.app is named properly anyway."""
    try:
        from Foundation import NSBundle, NSProcessInfo

        bundle = NSBundle.mainBundle()
        for info in (bundle.localizedInfoDictionary(), bundle.infoDictionary()):
            if info is not None and info.get("CFBundleName") != name:
                info["CFBundleName"] = name
        NSProcessInfo.processInfo().setProcessName_(name)
    except Exception:
        pass
