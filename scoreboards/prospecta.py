"""Prospecta basketball (ALGE "CKN" V1 framing): D1 LEN type data... sum8, total = LEN + 2."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import bcd_zero_blank, dec, sum8

START = 0xD1


class ProspectaProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            i = find(buf, START)
            if i < 0:
                buf.clear()
                return
            if len(buf) <= i + 3:
                del buf[:i]
                return
            if buf[i + 1] == START:  # doubled start byte: the second one is the real start
                i += 1
                if len(buf) <= i + 1:
                    del buf[:i]
                    return
            size = buf[i + 1] + 2
            if len(buf) - i < size:
                del buf[:i]
                return
            pkt = bytes(buf[i:i + size])
            del buf[:i + size]
            if sum8(pkt, 0, size - 1) == pkt[-1]:
                yield pkt
            else:
                self.reject()


def _d(b: int, i: int, digits: int = 2, left: bool = False) -> str:
    return dec(b, i, digits, left)


class ProspectaBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 3:
            return
        t = p[2]
        if t == 4 and len(p) >= 8:
            self._clocks(p)
            self._timeout_clock(p)
        elif t == 10 and len(p) >= 23:
            self.c["HomeTeamName"] = "".join(chr(b) for b in p[3:11])  # raw bytes, as ScoreConnect does
            self.c["GuestTeamName"] = "".join(chr(b) for b in p[15:23])
        elif t == 13 and len(p) >= 7:
            c = self.c
            c.update(HomeFoulTens=_d(p[3], 1, 2, True), HomeFoulOnes=_d(p[3], 0), GuestFoulTens=_d(p[4], 1, 2, True),
                     GuestFoulOnes=_d(p[4], 0), FoulPlayerTens=_d(p[5], 1, 2, True), FoulPlayerOnes=_d(p[5], 0),
                     FoulPlayerNumberOfFouls=_d(p[6], 0))
        elif t == 22 and len(p) >= 14:
            self._clocks(p)
            self._timeout_clock(p)
            c = self.c
            f = p[11]
            c.update(HomeScoreHundreds=_d(p[8], 2, 3, True), HomeScoreTens=_d(p[8], 1, 3), HomeScoreOnes=_d(p[8], 0, 3),
                     GuestScoreHundreds=_d(p[9], 2, 3, True), GuestScoreTens=_d(p[9], 1, 3),
                     GuestScoreOnes=_d(p[9], 0, 3), Period=_d(p[10], 0, 2, True),
                     HomePossession="<" if f & 0x80 else " ", GuestPossession=">" if f & 0x08 else " ",
                     HomeTimeouts=_d((f & 0x30) >> 4, 0, 2, True), GuestTimeouts=_d(f & 3, 0, 2, True),
                     HomeBonus="B" if f & 0x40 else " ", GuestBonus="B" if f & 0x04 else " ",
                     HomeFoulTens=_d(p[12], 1, 2, True), HomeFoulOnes=_d(p[12], 0),
                     GuestFoulTens=_d(p[13], 1, 2, True), GuestFoulOnes=_d(p[13], 0))

    def _timeout_clock(self, p):
        v = p[7] & 0x7F
        self.c.update(TimeoutClockSecondTens=_d(v, 1, 2, True), TimeoutClockSecondOnes=_d(v, 0, 2, True))

    def _clocks(self, p):
        c = self.c
        if p[3] > 0:
            c.update(ClockMode=":", ClockMinutesTens=_d(p[3], 1, 2, True), ClockMinutesOnes=_d(p[3], 0),
                     ClockSecondTens=_d(p[4], 1), ClockSecondOnes=_d(p[4], 0), ClockTenthsSecond="0")
        else:
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=_d(p[4], 1, 2, True),
                     ClockSecondOnes=_d(p[4], 0), ClockTenthsSecond=bcd_zero_blank(p[5], 1))
        if p[6] == 170:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=" ")
        else:
            c.update(ShotClockSecondTens=_d(p[6], 1, 2, True), ShotClockSecondOnes=_d(p[6], 0))


PROTOCOLS = {"Prospecta_Basketball": lambda: ProspectaProtocol(ProspectaBasketball())}
