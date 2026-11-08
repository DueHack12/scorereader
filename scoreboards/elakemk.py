"""Elak EMK basketball: D3 '4' '1' type ... 0D (ASCII)."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A

START, END = 0xD3, 0x0D


class ElakEmkProtocol(Protocol):
    """ScoreConnect's first pass per read looks for a 00 byte instead of 0D (probably a typo); here the frame
    always ends at 0D and stray 00 bytes between frames are ignored as garbage."""

    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, END)
            if end < 0:
                return
            start = find(buf, START)
            pkt = bytes(buf[start:end + 1]) if 0 <= start < end else None
            del buf[:end + 1]
            if pkt is None:
                continue
            if len(pkt) >= 4 and pkt[1] == 52 and pkt[2] == 49:
                yield pkt
            else:
                self.reject()


class ElakEmkBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        c = self.c
        n = len(p)
        t = p[3]
        if t == 84 and n > 4:  # 'T'
            if p[4] == 80 and n >= 13:  # 'P': game clock
                if p[6] == 32 and p[7] == 32:
                    c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockMode=".", ClockSecondTens=A(p[9]),
                             ClockSecondOnes=A(p[10]), ClockTenthsSecond=A(p[12]))
                else:
                    c.update(ClockMode=":", ClockMinutesTens=A(p[6]), ClockMinutesOnes=A(p[7]),
                             ClockSecondTens=A(p[9]), ClockSecondOnes=A(p[10]), ClockTenthsSecond="0")
            elif p[4] == 79 and n >= 11:  # 'O': timeouts
                if p[5] == 58:
                    c.update(HomeTimeouts=A(p[7]), GuestTimeouts=A(p[10]))
                elif p[5] == 84:
                    c.update(TimeoutClockSecondTens=A(p[7]), TimeoutClockSecondOnes=A(p[8]))
        elif t == 82 and n >= 14:  # 'R': scores
            c.update(HomeScoreHundreds=A(p[6]), HomeScoreTens=A(p[7]), HomeScoreOnes=A(p[8]),
                     GuestScoreHundreds=A(p[11]), GuestScoreTens=A(p[12]), GuestScoreOnes=A(p[13]))
        elif t == 65 and n >= 8 and p[4] == 84:  # 'A' 'T': shot clock
            c.update(ShotClockSecondTens=A(p[6]), ShotClockSecondOnes=A(p[7]))


PROTOCOLS = {"ElakEmk_Basketball": lambda: ElakEmkProtocol(ElakEmkBasketball())}
