"""ESK basketball: F8 ... 0D, long ASCII packets (type in byte 1)."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A

START, END = 0xF8, 0x0D


class ESKProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, END)
            if end < 0:
                return
            start = find(buf, START)
            pkt = bytes(buf[start:end + 1]) if 0 <= start < end else None
            del buf[:end + 1]
            if pkt is not None:
                yield pkt
            else:
                self.reject()


class ESKBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 53 or p[1] not in (51, 55, 56):
            return
        c = self.c
        self._clock(p)
        if p[1] == 51:
            c.update(HomePossession="<" if p[3] == 49 else " ", GuestPossession=">" if p[3] == 50 else " ",
                     HomeScoreHundreds=A(p[8]), HomeScoreTens=A(p[9]), HomeScoreOnes=A(p[10]),
                     GuestScoreHundreds=A(p[11]), GuestScoreTens=A(p[12]), GuestScoreOnes=A(p[13]),
                     Period=A(p[14]), HomeFoulOnes=A(p[15]), GuestFoulOnes=A(p[16]),
                     HomeTimeouts=A(p[17]), GuestTimeouts=A(p[18]), TimeoutClockMinutesOnes=A(p[21]),
                     TimeoutClockSecondTens=A(p[46]), TimeoutClockSecondOnes=A(p[47]))

    def _clock(self, p: bytes) -> None:
        c = self.c
        secs = (A(p[6]) + A(p[7])).strip()
        mins = (A(p[4]) + A(p[5])).strip()
        if len(mins) == 2 and len(secs) == 1:
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=mins[0],
                     ClockSecondOnes=mins[1], ClockTenthsSecond=secs[0])
        elif mins and len(secs) == 2:  # ScoreConnect would throw on anything else; leave the clock alone
            c.update(ClockMode=":", ClockMinutesTens=mins[0] if len(mins) == 2 else "0",
                     ClockMinutesOnes=mins[1] if len(mins) == 2 else mins[0],
                     ClockSecondTens=secs[0], ClockSecondOnes=secs[1], ClockTenthsSecond="0")
        c["Horn"] = "H" if p[19] == 49 else " "
        if p[52] == 49:
            c.update(ShotClockSecondTens=A(p[48]), ShotClockSecondOnes=A(p[49]), ShotClockTenthsSecond=" ")
        elif p[52] == 46:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=A(p[48]), ShotClockTenthsSecond=A(p[49]))


PROTOCOLS = {"ESK_Basketball": lambda: ESKProtocol(ESKBasketball())}
