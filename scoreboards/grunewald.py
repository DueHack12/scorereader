"""Grunewald basketball: '#' (23) + 23 ASCII bytes + CR = 25 bytes."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A

START, END = 0x23, 0x0D


class GrunewaldProtocol(Protocol):
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
            if len(pkt) == 25:
                yield pkt
            else:
                self.reject()


class GrunewaldBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 24:
            return
        c = self.c
        c["Period"] = A(p[1])
        if p[2] == 67:
            c["InternalClockStatus"] = "R"
        elif p[2] == 99:
            c["InternalClockStatus"] = "S"
        if p[3] == 48 and p[4] == 48:
            c.update(ClockMode=".", ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=A(p[5]),
                     ClockSecondOnes=A(p[6]), ClockTenthsSecond=A(p[7]))
        else:
            c.update(ClockMode=":", ClockMinutesTens=A(p[3]), ClockMinutesOnes=A(p[4]), ClockSecondTens=A(p[5]),
                     ClockSecondOnes=A(p[6]), ClockTenthsSecond=" ")
        if p[17] == 65:
            c.update(ShotClockSecondTens=A(p[8]), ShotClockSecondOnes=A(p[9]), ShotClockTenthsSecond=A(p[10]))
        else:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=" ", ShotClockTenthsSecond=" ")
        c.update(HomeScoreHundreds=A(p[11]), HomeScoreTens=A(p[12]), HomeScoreOnes=A(p[13]),
                 GuestScoreHundreds=A(p[14]), GuestScoreTens=A(p[15]), GuestScoreOnes=A(p[16]),
                 HomeTimeouts=A(p[19]), GuestTimeouts=A(p[20]),
                 HomePossession="<" if A(p[21]) == "<" else " ", GuestPossession=">" if A(p[21]) == ">" else " ",
                 HomeFoulOnes=A(p[22]), GuestFoulOnes=A(p[23]))


PROTOCOLS = {"Grunewald_basketball": lambda: GrunewaldProtocol(GrunewaldBasketball())}
