"""Favero basketball scoreboard (RS-485; ScoreConnect lists the non-standard serial setting "192009N1").

Wire format: no start/end markers. Every packet starts with a byte of 0x80 or more (the command) followed by
ASCII/flag bytes below 0x80: 12 bytes long, or 14 bytes for the team-name commands (a fixed list of command
bytes). No checksum. See docs/vendors/favero.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol
from .common import ascii_char

PACKET_SIZE = 12
LONG_PACKET_SIZE = 14
LONG_COMMANDS = frozenset(
    [0x92, 0x93, 0x96] + list(range(0xA0, 0xAF)) + list(range(0xB0, 0xBF))  # 146 147 150, 160-174, 176-190
)


class FaveroProtocol(Protocol):
    """The first byte >= 0x80 starts a packet whose size depends on that byte; earlier bytes are dropped."""

    def extract(self):
        buf = self.buf
        while True:
            start = next((i for i, b in enumerate(buf) if b >= 0x80), -1)
            if start < 0:
                buf.clear()
                return
            size = LONG_PACKET_SIZE if buf[start] in LONG_COMMANDS else PACKET_SIZE
            if len(buf) - start < size:
                del buf[:start]
                return
            pkt = bytes(buf[start : start + size])
            del buf[: start + size]
            yield pkt


def _timeouts(flag: int) -> str:
    if flag == 0x40:
        return " "
    return {"B": "2", "A": "1"}.get(ascii_char(flag), "3")


class FaveroBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        try:
            self._decode(p)
        except IndexError:
            pass

    def _decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        cmd = p[0]
        if cmd == 0x80:  # clock, possession arrows, timeouts
            if p[4] == 0x3A:  # ':'
                c.update(ClockMode=":", ClockMinutesTens=a(2), ClockMinutesOnes=a(3), ClockSecondTens=a(5),
                         ClockSecondOnes=a(6), ClockTenthsSecond="0")
            elif p[4] == 0x2E:  # '.'
                c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=a(2),
                         ClockSecondOnes=a(3), ClockTenthsSecond=a(5))
            if p[7] == 0x70:  # 'p'
                c.update(HomePossession="<", GuestPossession=" ")
            elif p[9] == 0x70:
                c.update(HomePossession=" ", GuestPossession=">")
            else:
                c.update(HomePossession=" ", GuestPossession=" ")
            c["HomeTimeouts"] = _timeouts(p[8])
            c["GuestTimeouts"] = _timeouts(p[10])
        elif cmd == 0x81:  # shot clock
            if p[1] in (0x20, 0x31):
                c.update(ShotClockSecondTens=a(2), ShotClockSecondOnes=a(3), ShotClockTenthsSecond=" ")
            elif p[1] in (0x32, 0x33):
                c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=a(2), ShotClockTenthsSecond=a(3))
            c["PlayClockStatusInternal"] = "R" if p[9] == 0x31 else "S"
        elif cmd == 0x82:  # scores, bonus, period
            c.update(HomeScoreHundreds=a(1), HomeScoreTens=a(2), HomeScoreOnes=a(3),
                     GuestScoreHundreds=a(4), GuestScoreTens=a(5), GuestScoreOnes=a(6),
                     HomeBonus="B" if p[7] == 0x42 else " ", GuestBonus="B" if p[9] == 0x42 else " ",
                     Period=a(8))
        elif cmd == 0x83:  # fouls
            c.update(HomeFoulTens=a(7), HomeFoulOnes=a(8), GuestFoulTens=a(9), GuestFoulOnes=a(10),
                     FoulPlayerTens=a(2), FoulPlayerOnes=a(3), FoulPlayerNumberOfFouls=a(6))
        elif cmd == 0x92:
            c["HomeTeamName"] = "".join(ascii_char(b) for b in p[1:])
        elif cmd == 0x93:
            c["GuestTeamName"] = "".join(ascii_char(b) for b in p[1:])
        elif cmd == 0x94:
            c["Horn"] = "H" if p[1] == 0x31 or p[4] == 0x31 else " "


PROTOCOLS = {"Favero_Basketball": lambda: FaveroProtocol(FaveroBasketball())}
