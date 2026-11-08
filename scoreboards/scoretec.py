"""Scoretec basketball: 7-segment bytes, frames delimited by '@' (40)."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import bcd, digit

MARK = 0x40


class ScoretecProtocol(Protocol):
    """ScoreConnect quirk reproduced: when the first '@' is at buffer index 27 the packet handed to the decoder
    is that '@' plus the 26 bytes after it (the start of the *next* frame, which needs 54 bytes in the buffer);
    an '@' anywhere else is a framing error. Consumed through the '@'."""

    def extract(self):
        buf = self.buf
        while True:
            i = find(buf, MARK)
            if i < 0:
                return
            if i == 27:
                if len(buf) < 54:
                    return
                pkt = bytes(buf[27:54])
                del buf[:28]
                yield pkt
            else:
                del buf[:i + 1]
                self.reject()


class ScoretecBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 26:
            return
        c = self.c
        c.update(ClockMode=":", ClockMinutesTens=digit(p[25]), ClockMinutesOnes=digit(p[24]),
                 ClockSecondTens=digit(p[23]), ClockSecondOnes=digit(p[22]))
        if p[16] & 4:
            c.update(HomePossession="<", GuestPossession=" ")
        if p[16] & 1:
            c.update(HomePossession=" ", GuestPossession=">")
        c["HomeBonus"] = "B" if p[16] & 8 else " "
        c["GuestBonus"] = "B" if p[16] & 2 else " "
        c["Period"] = bcd(p[14], 0)
        c.update(HomeScoreHundreds="1" if p[21] & 0x32 else " ", HomeScoreTens=digit(p[20]),
                 HomeScoreOnes=digit(p[19]),
                 GuestScoreHundreds="1" if p[21] & 0x16 else " ", GuestScoreTens=digit(p[18]),
                 GuestScoreOnes=digit(p[17]),
                 HomeFoulTens=digit(p[13]), HomeFoulOnes=digit(p[12]),
                 GuestFoulTens=digit(p[8]), GuestFoulOnes=digit(p[7]),
                 FoulPlayerTens=digit(p[10]), FoulPlayerOnes=digit(p[9]), FoulPlayerNumberOfFouls=digit(p[11]))


PROTOCOLS = {"ScoreTec_Basketball": lambda: ScoretecProtocol(ScoretecBasketball())}
