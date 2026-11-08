"""Baybor basketball: fixed-size packets that begin with a byte >= 0x80 (12 bytes, 14 for team names)."""
from __future__ import annotations

from .base import Decoder, Protocol
from .common import ascii_char as A

_LONG = {146, 147, 150, 160, 190}


class BayborProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            i = next((k for k, b in enumerate(buf) if b >= 0x80), -1)
            if i < 0:
                buf.clear()  # nothing here can start a packet
                return
            size = 14 if buf[i] in _LONG else 12
            if len(buf) - i < size:
                del buf[:i]
                return
            pkt = bytes(buf[i:i + size])
            del buf[:i + size]
            yield pkt


def _timeouts(b: int) -> str:
    if b == 64:
        return " "
    return {"B": "2", "A": "1"}.get(A(b), "3")


class BayborBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        c = self.c
        t = p[0]
        if t == 0x80:
            if p[4] == 58:
                c.update(ClockMode=":", ClockMinutesTens=A(p[2]), ClockMinutesOnes=A(p[3]),
                         ClockSecondTens=A(p[5]), ClockSecondOnes=A(p[6]), ClockTenthsSecond="0")
            elif p[4] == 32:
                c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0",
                         ClockSecondTens=A(p[2]), ClockSecondOnes=A(p[3]), ClockTenthsSecond=A(p[5]))
            if p[7] == 112:
                c.update(HomePossession="<", GuestPossession=" ")
            elif p[9] == 112:
                c.update(HomePossession=" ", GuestPossession=">")
            else:
                c.update(HomePossession=" ", GuestPossession=" ")
            c["HomeTimeouts"] = _timeouts(p[8])
            c["GuestTimeouts"] = _timeouts(p[10])
        elif t == 0x81:
            if p[1] in (32, 49):
                c.update(ShotClockSecondTens=A(p[2]), ShotClockSecondOnes=A(p[3]), ShotClockTenthsSecond=" ")
            elif p[1] in (50, 51):
                c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=A(p[2]), ShotClockTenthsSecond=A(p[3]))
            c["PlayClockStatusInternal"] = "R" if p[9] == 49 else "S"
        elif t == 0x82:
            c.update(HomeScoreHundreds=A(p[1]), HomeScoreTens=A(p[2]), HomeScoreOnes=A(p[3]),
                     GuestScoreHundreds=A(p[4]), GuestScoreTens=A(p[5]), GuestScoreOnes=A(p[6]),
                     HomeBonus="B" if p[7] == 66 else " ", GuestBonus="B" if p[9] == 66 else " ",
                     Period=A(p[8]))
        elif t == 0x83:
            c.update(HomeFoulTens=A(p[7]), HomeFoulOnes=A(p[8]), GuestFoulTens=A(p[9]), GuestFoulOnes=A(p[10]),
                     FoulPlayerTens=A(p[2]), FoulPlayerOnes=A(p[3]), FoulPlayerNumberOfFouls=A(p[6]))
        elif t in (146, 147):
            name = "".join(A(b) for b in p[1:])
            c["HomeTeamName" if t == 146 else "GuestTeamName"] = name
        elif t == 148:
            c["Horn"] = "H" if (p[1] == 49 or p[4] == 49) else " "


PROTOCOLS = {"Baybor_Basketball": lambda: BayborProtocol(BayborBasketball())}
