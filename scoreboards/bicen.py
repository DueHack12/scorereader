"""Bicen basketball: FA 44 ... 160-byte frames, 16-bit big-endian sum in the last two bytes, BCD nibbles."""
from __future__ import annotations

from .base import Decoder, Protocol, find_pair
from .common import bcd

FRAME = 160


class BicenProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            j = find_pair(buf, 0xFA, 0x44)
            if j < 0:
                del buf[:max(0, len(buf) - 1)]
                return
            s = j - 1
            if s:
                del buf[:s]
            if len(buf) < FRAME:
                return
            pkt = bytes(buf[:FRAME])
            del buf[:FRAME]
            total = sum(pkt[:FRAME - 2]) & 0xFFFF  # bytes 0..157
            if pkt[158] == total >> 8 and pkt[159] == total & 0xFF:
                yield pkt
            else:
                self.reject()


class BicenBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 64:
            return
        c = self.c
        if bcd(p[58], 0) == " ":
            c.update(ClockMode=".", ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=bcd(p[56], 0),
                     ClockSecondOnes=bcd(p[57], 1), ClockTenthsSecond=bcd(p[58], 1))
        else:
            c.update(ClockMode=":", ClockMinutesTens=bcd(p[56], 0), ClockMinutesOnes=bcd(p[57], 1),
                     ClockSecondTens=bcd(p[58], 1), ClockSecondOnes=bcd(p[58], 0), ClockTenthsSecond=" ")
        if p[63] & 2:
            c.update(ShotClockSecondTens=bcd(p[55], 1), ShotClockSecondOnes=bcd(p[55], 0), ShotClockTenthsSecond=" ")
        else:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=bcd(p[55], 1), ShotClockTenthsSecond=bcd(p[55], 0))
        c["Period"] = bcd(p[61], 0)
        h_to = bcd(p[60], 1) != " "
        g_to = bcd(p[62], 0) != " "
        if not h_to:
            c["HomeFoulOnes"] = bcd(p[60], 0)
        else:
            c.update(TimeoutClockSecondTens=bcd(p[60], 1), TimeoutClockSecondOnes=bcd(p[60], 0))
        if not g_to:
            c["GuestFoulOnes"] = bcd(p[63], 1)
        else:
            c.update(TimeoutClockSecondTens=bcd(p[62], 0), TimeoutClockSecondOnes=bcd(p[63], 1))
        if not h_to and not g_to:
            c.update(TimeoutClockSecondTens=" ", TimeoutClockSecondOnes=" ")
        c.update(HomeScoreHundreds=bcd(p[52], 1), HomeScoreTens=bcd(p[52], 0), HomeScoreOnes=bcd(p[53], 1),
                 GuestScoreHundreds=bcd(p[53], 0), GuestScoreTens=bcd(p[54], 1), GuestScoreOnes=bcd(p[54], 0))


PROTOCOLS = {"Bicen_Basketball": lambda: BicenProtocol(BicenBasketball())}
