"""MacFinish basketball clock: 'D' mmss ss(shot) ... CR."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A


class MacFinishProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, 0x0D)
            if end < 0:
                return
            pkt = bytes(buf[:end])
            del buf[:end + 1]
            if pkt[:1] == b"D":
                yield pkt
            else:
                self.reject()


class MacFinishBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 7 or p[0] != 68:
            return
        self.c.update(ClockMode=":", ClockMinutesTens=A(p[1]), ClockMinutesOnes=A(p[2]), ClockSecondTens=A(p[3]),
                      ClockSecondOnes=A(p[4]), ShotClockSecondTens=A(p[5]), ShotClockSecondOnes=A(p[6]))


PROTOCOLS = {"MacFinish_Basketball": lambda: MacFinishProtocol(MacFinishBasketball())}
