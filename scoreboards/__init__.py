"""Scoreboard protocols for every brand ScoreConnect III supports.

Each vendor module defines ``PROTOCOLS = {"<id>": factory}``, where ``<id>`` is the vendor-sport name used in
``catalog.json`` (for example ``Nevco_Basketball``) and ``factory()`` returns a fresh ``base.Protocol``.

Modules are imported lazily and independently: a broken vendor module is reported by :func:`load_errors`
and never stops the others (or the Daktronics current-loop path in scorereader.py) from working.
"""
from __future__ import annotations

import importlib
import json
import os
import threading

VENDOR_MODULES = [
    "daktronics", "daktronics_serial", "fairplay", "fairplay_models", "nevco", "electromech", "varsity", "oes",
    "sportzcast", "eversan", "nautronic", "stramatel", "allamerican", "spectrum", "swisstiming", "alge",
    "tissot", "westerstrand", "coloradotiming", "harristime", "atlasservis", "pannonescore", "icast",
    "nisasport", "funtronix", "bodet", "anatec", "fujitsu", "bluevane", "skorled", "quince", "compulink",
    "viewall", "favero", "uno", "baybor", "ultrascore", "mondo", "lgr", "esk", "colosseo", "bertelle",
    "elakemk", "scoretec", "trackman", "majordisplay", "hamiltondigital", "macfinish", "farmtek", "prospecta",
    "bicen", "grunewald",
]

_lock = threading.Lock()
_protocols: dict | None = None
_errors: dict[str, str] = {}
_catalog: dict | None = None

CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog.json")


def protocols() -> dict:
    """All implemented protocol factories, keyed by vendor-sport id."""
    global _protocols
    with _lock:
        if _protocols is None:
            found: dict = {}
            for name in VENDOR_MODULES:
                try:
                    mod = importlib.import_module(f"{__name__}.{name}")
                except ModuleNotFoundError as e:
                    if e.name != f"{__name__}.{name}":
                        _errors[name] = f"{type(e).__name__}: {e}"
                    continue
                except Exception as e:
                    _errors[name] = f"{type(e).__name__}: {e}"
                    continue
                for pid, factory in getattr(mod, "PROTOCOLS", {}).items():
                    found[pid] = (name, factory)
            _protocols = found
        return {k: v[1] for k, v in _protocols.items()}


def module_of(protocol_id: str) -> str | None:
    protocols()
    return _protocols.get(protocol_id, (None,))[0] if _protocols else None


def load_errors() -> dict:
    protocols()
    return dict(_errors)


def create(protocol_id: str):
    """A fresh Protocol for the vendor-sport id, or KeyError if it isn't implemented."""
    factory = protocols().get(protocol_id)
    if factory is None:
        raise KeyError(f"Scoreboard protocol '{protocol_id}' is not available")
    return factory()


def catalog() -> dict:
    """Vendors, their wiring options and their sports (from ScoreConnect's configuration database)."""
    global _catalog
    if _catalog is None:
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                _catalog = json.load(f)
        except OSError:
            _catalog = {"vendors": [], "vendor_sports": []}
    return _catalog


def vendor_sport(protocol_id: str) -> dict | None:
    return next((r for r in catalog().get("vendor_sports", []) if r.get("enum") == protocol_id), None)
