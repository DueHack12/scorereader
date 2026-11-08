"""Bertelle basketball: ':' (3A) delimited packets, last byte = XOR of the others."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_digit_or_blank as AD, xor8

MARK = 0x3A


class BertelleProtocol(Protocol):
    """A packet runs from one ':' to just before the next, so it is decoded when the next one starts."""

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
            if len(pkt) >= 2 and xor8(pkt, 0, len(pkt) - 1) == pkt[-1]:
                yield pkt
            else:
                self.reject()


class BertelleBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        c = self.c
        if len(p) < 4 or p[2] != 87:
            return
        if p[1] == 80 and p[3] == 16 and len(p) >= 20:
            if p[8] != 15:
                c.update(ClockMode=":", ClockMinutesTens=AD(p[11]), ClockMinutesOnes=AD(p[10]),
                         ClockSecondTens=AD(p[9]), ClockSecondOnes=AD(p[8]), ClockTenthsSecond="0")
            else:
                c.update(ClockMode=".", ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=AD(p[11]),
                         ClockSecondOnes=AD(p[10]), ClockTenthsSecond=AD(p[9]))
            c.update(HomeScoreHundreds=AD(p[7]), HomeScoreTens=AD(p[14]), HomeScoreOnes=AD(p[15]),
                     GuestScoreHundreds=AD(p[6]), GuestScoreTens=AD(p[12]), GuestScoreOnes=AD(p[13]),
                     HomeFoulTens=AD(p[17]), HomeFoulOnes=AD(p[16]), GuestFoulTens=AD(p[19]),
                     GuestFoulOnes=AD(p[18]))
            if p[5] % 2 == 0:  # odd values leave the previous period untouched
                c["Period"] = AD((p[5] & 0xF) // 2 | 0x30)
        elif p[1] == 84 and p[3] == 4 and len(p) >= 6:
            c.update(ShotClockSecondTens=AD(p[4]), ShotClockSecondOnes=AD(p[5]))


PROTOCOLS = {"Bertelle_Basketball": lambda: BertelleProtocol(BertelleBasketball())}
