"""Major Display baseball (XBee): '!' (21) delimited packets of >= 51 bytes, custom 7-segment table."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A

MARK = 0x21
_SEG = {111: "0", 6: "1", 205: "2", 143: "3", 166: "4", 171: "5", 235: "6", 14: "7", 239: "8", 175: "9"}


def _digit_major_display(b: int) -> str:
    return _SEG.get(b, " ")


class MajorDisplayProtocol(Protocol):
    """A packet runs from one '!' to just before the next; shorter than 51 bytes is dropped silently.
    (ScoreConnect switches to ':' as the delimiter after the first packet in a read, which looks like a copy
    and paste slip; '!' is used throughout here.)"""

    def extract(self):
        buf = self.buf
        while True:
            a = find(buf, MARK)
            if a < 0:
                buf.clear()
                return
            b = find(buf, MARK, a + 1)
            if b < 0:
                del buf[:a]
                return
            pkt = bytes(buf[a:b])
            del buf[:b]
            if len(pkt) >= 51:
                yield pkt


_D = _digit_major_display
_SINGLE = {"AtBatTens": 7, "AtBatOnes": 6, "Balls": 8, "Strikes": 9, "Outs": 38, "GuestRunTens": 41,
           "GuestRunOnes": 40, "HomeRunTens": 46, "HomeRunOnes": 45}
_GUEST_INN = (10, 11, 12, 13, 22, 23, 24, 25, 26)
_HOME_INN = (14, 15, 16, 17, 28, 29, 30, 31, 32)


class MajorDisplayBaseball(Decoder):
    contract = "BaseballSoftball"
    event = "Baseball"

    def decode(self, p: bytes) -> None:
        if len(p) < 47:
            return
        c = self.c
        c["ClockMode"] = ":"
        for name, i in _SINGLE.items():
            c[name] = _D(p[i])
        for n, i in enumerate(_GUEST_INN, 1):
            c[f"GuestInning{n}"] = _D(p[i])
        for n, i in enumerate(_HOME_INN, 1):
            c[f"HomeInning{n}"] = _D(p[i])
        if len(p) > 51 and b"TNCHEAD" in p:
            self._name(p, "HomeTeamName", p.find(b"TNCHEAD:1:1:") + 12)
            self._name(p, "GuestTeamName", p.find(b"TNCENDTNCHEAD:2:1:") + 18)

    def _name(self, p: bytes, key: str, off: int) -> None:
        if off + 8 <= len(p):
            name = "".join(A(b) for b in p[off:off + 8])  # 8 characters, not trimmed
            if name:
                self.c[key] = name


PROTOCOLS = {"MajorDisplay_Baseball": lambda: MajorDisplayProtocol(MajorDisplayBaseball())}
