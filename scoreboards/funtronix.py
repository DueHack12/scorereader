"""Funtronix autodetect (basketball, soccer, volleyball).

Frame: 16 bytes; byte 0 has bit 7 set and none of bytes 1-15 do. Bits 5-6 of byte 0 select the sport
(0x40 basketball, 0x00 soccer, 0x20 volleyball). All digits are BCD low nibbles. See docs/vendors/funtronix.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol
from .common import bcd

__all__ = ["PROTOCOLS"]

_LEN = 16


class FuntronixProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while len(buf) >= _LEN:
            start = next((i for i, b in enumerate(buf) if b & 0x80), -1)
            if start < 0:
                buf.clear()
                return
            if len(buf) - start < _LEN:
                del buf[:start]
                return
            pkt = bytes(buf[start : start + _LEN])
            if any(b & 0x80 for b in pkt[1:]):
                del buf[: start + 1]  # another header inside: resync one byte on
                self.reject()
                continue
            del buf[: start + _LEN]
            yield pkt


def _clock(c: dict, p: bytes) -> None:
    if p[8] & 0x10:
        c.update(ClockMode=":", ClockMinutesTens=bcd(p[8], 0), ClockMinutesOnes=bcd(p[9], 0),
                 ClockSecondTens=bcd(p[10], 0), ClockSecondOnes=bcd(p[11], 0), ClockTenthsSecond="0")
    else:
        c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=bcd(p[10], 0),
                 ClockSecondOnes=bcd(p[11], 0), ClockTenthsSecond=bcd(p[12], 0))


def _flag(p: bytes, mask: int, ch: str) -> str:
    return ch if p[0] & mask else " "


class BasketballDecoder(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        c = self.c
        c.update(HomePossession=_flag(p, 8, "<"), GuestPossession=_flag(p, 4, ">"), HomeBonus=_flag(p, 2, "B"),
                 GuestBonus=_flag(p, 1, "B"),
                 HomeScoreHundreds=bcd(p[3], 0), HomeScoreTens=bcd(p[2], 0), HomeScoreOnes=bcd(p[1], 0),
                 GuestScoreHundreds=bcd(p[6], 0), GuestScoreTens=bcd(p[5], 0), GuestScoreOnes=bcd(p[4], 0),
                 Period=bcd(p[7], 0), ShotClockSecondTens=bcd(p[14], 0), ShotClockSecondOnes=bcd(p[15], 0))
        _clock(c, p)


class SoccerDecoder(Decoder):
    contract = "Soccer"
    event = "Soccer"

    def decode(self, p: bytes) -> None:
        c = self.c
        c.update(HomePossession=_flag(p, 8, "<"), GuestPossession=_flag(p, 2, ">"),
                 HomeScoreTens=bcd(p[2], 0), HomeScoreOnes=bcd(p[1], 0),
                 GuestScoreTens=bcd(p[5], 0), GuestScoreOnes=bcd(p[4], 0), Period=bcd(p[7], 0),
                 HomePenalties=bcd(p[13], 0), GuestPenalties=bcd(p[15], 0))
        _clock(c, p)


class VolleyballDecoder(Decoder):
    contract = "Volleyball"
    event = "Volleyball"

    def decode(self, p: bytes) -> None:
        c = self.c
        c.update(HomeServe=_flag(p, 8, "*"), GuestServe=_flag(p, 4, "*"),
                 HomeScoreTens=bcd(p[2], 0), HomeScoreOnes=bcd(p[1], 0),
                 GuestScoreTens=bcd(p[5], 0), GuestScoreOnes=bcd(p[4], 0), Game=bcd(p[7], 0),
                 HomeGamesWon=bcd(p[13], 0), GuestGamesWon=bcd(p[15], 0))
        _clock(c, p)


_SPORTS = {0x40: BasketballDecoder, 0x00: SoccerDecoder, 0x20: VolleyballDecoder}


class Autodetect(Decoder):
    """Follows the sport code in byte 0 (bits 5-6). A code change starts a fresh contract; unknown code
    (0x60) is ignored."""

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
        code = p[0] & 0x60
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


PROTOCOLS = {"Funtronix_Autodetect": lambda: FuntronixProtocol(Autodetect())}
