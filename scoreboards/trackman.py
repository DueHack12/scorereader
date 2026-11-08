"""Trackman baseball pitch speed (UDP): every datagram is JSON {"Time":..,"Pitch":{"Speed":"87.3"}}."""
from __future__ import annotations

import json

from .base import Decoder, Protocol
from .common import ascii_text


class TrackmanProtocol(Protocol):
    """No framing: each feed() chunk is one packet."""

    def extract(self):
        if self.buf:
            pkt = bytes(self.buf)
            self.buf.clear()
            yield pkt


class TrackmanBaseball(Decoder):
    contract = "BaseballSoftball"
    event = "Baseball"  # ScoreConnect leaves EventId unset; the catalog lists this board as Baseball
    MAX_PENDING = 65536

    def __init__(self):
        super().__init__()
        self._pending = ""

    @staticmethod
    def _parse(text: str):
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        return obj if isinstance(obj, dict) else None

    def decode(self, p: bytes) -> None:
        text = ascii_text(p)
        obj = self._parse(text)
        if obj is None:  # maybe a datagram split in two: try the accumulated text
            self._pending = (self._pending + text)[-self.MAX_PENDING:]
            obj = self._parse(self._pending)
        if obj is None:
            return
        self._pending = ""
        pitch = obj.get("Pitch")
        speed = pitch.get("Speed") if isinstance(pitch, dict) else None
        self.c["PitchSpeed"] = "" if speed is None else str(speed).split(".")[0]

    def reset(self) -> None:
        super().reset()
        self._pending = ""


PROTOCOLS = {"Trackman_BaseballPitchSpeed": lambda: TrackmanProtocol(TrackmanBaseball())}
