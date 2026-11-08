"""PannoneScore (basketball, autodetect on a sport code).

Frame: ``0x82 ... xor 0x83`` where xor = XOR of every byte after the 0x82 up to (not including) the checksum.
The packet byte at index 61 selects the sport (0 = basketball); byte 1 says which "pages" the packet carries.
See docs/vendors/pannonescore.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import bcd_raw, xor8

__all__ = ["PROTOCOLS"]

_STX, _ETX = 0x82, 0x83
_MIN_LEN = 62  # the sport code lives at index 61

_SPECIAL_NIBBLES = {"A": "-", "B": "_", "C": "E", "D": "C", "E": "°", "F": " "}


def _nib(b: int, i: int) -> str:
    """Nibble i (1 = high, 0 = low) of b; A-F are the board's special glyphs."""
    ch = bcd_raw(b, i)
    return _SPECIAL_NIBBLES.get(ch, ch)


class PannoneProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, _ETX)
            if end < 0:
                return
            start = find(buf, _STX)
            pkt = bytes(buf[start : end + 1]) if 0 <= start < end else b""
            del buf[: end + 1]
            if len(pkt) >= 3 and pkt[-2] == xor8(pkt, 1, len(pkt) - 2):
                yield pkt
            else:
                self.reject()


# byte 1 of the packet -> the three page letters it carries
_PAGES = {1: "ABD", 2: "ACE", 3: "ABF", 4: "ACG", 5: "ABH", 6: "ACD", 7: "ABE", 8: "ACF", 9: "ABG", 10: "ACI"}


class BasketballDecoder(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < _MIN_LEN:
            return
        for page in _PAGES.get(p[1], ""):
            getattr(self, "_page_" + page, self._nothing)(p)

    def _nothing(self, p: bytes) -> None:
        pass

    def _page_A(self, p: bytes) -> None:  # clocks (data at index 2..4)
        c = self.c
        if _nib(p[3], 1) == "-":  # high nibble of the 2nd clock byte is A: seconds.tenths
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=_nib(p[2], 1),
                     ClockSecondOnes=_nib(p[2], 0), ClockTenthsSecond=_nib(p[3], 0))
        else:
            c.update(ClockMode=":", ClockMinutesTens=_nib(p[2], 1), ClockMinutesOnes=_nib(p[2], 0),
                     ClockSecondTens=_nib(p[3], 1), ClockSecondOnes=_nib(p[3], 0), ClockTenthsSecond="0")
        c["ShotClockSecondTens"] = _nib(p[4], 1)
        c["ShotClockSecondOnes"] = _nib(p[4], 0)

    def _page_F(self, p: bytes) -> None:  # scores
        self.c.update(HomeScoreHundreds=_nib(p[51], 0), HomeScoreTens=_nib(p[52], 1), HomeScoreOnes=_nib(p[52], 0),
                      GuestScoreHundreds=_nib(p[53], 0), GuestScoreTens=_nib(p[54], 1),
                      GuestScoreOnes=_nib(p[54], 0))

    def _page_H(self, p: bytes) -> None:
        self.c["Period"] = _nib(p[60], 0)

    def _page_D(self, p: bytes) -> None:
        self.c.update(HomeFoulTens=_nib(p[60], 1), HomeFoulOnes=_nib(p[60], 0))

    def _page_E(self, p: bytes) -> None:
        self.c.update(GuestFoulTens=_nib(p[60], 1), GuestFoulOnes=_nib(p[60], 0))

    def _page_G(self, p: bytes) -> None:  # timeouts; bit 7 of byte 36 picks the team
        if p[37] & 0x1F == 3:
            self.c["GuestTimeouts" if p[36] & 0x80 else "HomeTimeouts"] = _nib(p[38], 0)


_SPORTS = {0: BasketballDecoder}


class Autodetect(Decoder):
    """Switches layout on the sport code in byte 61. Unknown codes leave the current layout in place;
    before the first known code nothing is decoded. A change of code starts a fresh contract."""

    def __init__(self):
        self._sel: Decoder | None = None
        self._code = -1
        self._idle = {"EventId": "Generic"}

    @property
    def contract(self) -> str:
        return self._sel.contract if self._sel else "Generic"

    @property
    def event(self) -> str:
        return self._sel.event if self._sel else "Generic"

    @property
    def c(self) -> dict:
        return self._sel.c if self._sel else self._idle

    @c.setter
    def c(self, value: dict) -> None:
        if self._sel:
            self._sel.c = value
        else:
            self._idle = value

    @property
    def code(self) -> int:
        return self._code

    def decode(self, p: bytes) -> None:
        if len(p) < _MIN_LEN:
            return
        code = p[61]
        if code != self._code and code in _SPORTS:
            self._code = code
            self._sel = _SPORTS[code]()
        if self._sel:
            self._sel.decode(p)

    def reset(self) -> None:
        if self._sel:
            self._sel.reset()
        else:
            self._idle = {"EventId": "Generic"}


PROTOCOLS = {"PannoneScore_Autodetect": lambda: PannoneProtocol(Autodetect())}
