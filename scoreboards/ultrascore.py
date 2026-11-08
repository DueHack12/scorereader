"""UltraScore basketball (UDP): FE FF type ? len ... ; total packet = len + 6, no checksum."""
from __future__ import annotations

from .base import Decoder, Protocol, find_pair
from .common import bcd, dec


class UltraScoreProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            j = find_pair(buf, 0xFE, 0xFF)
            if j < 0:
                del buf[:max(0, len(buf) - 1)]  # keep a trailing FE
                return
            s = j - 1
            if s:
                del buf[:s]
            if len(buf) < 5:
                return
            total = buf[4] + 6
            if len(buf) < total:
                return
            pkt = bytes(buf[:total])
            del buf[:total]
            yield pkt


def _two(b: int) -> str:
    return dec(b, 1) + dec(b, 0)


class UltraScoreBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 3:
            return
        if p[2] == 1:
            self._general(p)
        elif p[2] in (2, 3):
            self._team(p, "Home" if p[2] == 2 else "Guest")

    def _team(self, p: bytes, side: str) -> None:
        if len(p) < 25:
            return
        # Player slots at 7,10,13,16,19,22. ScoreConnect writes the 4th and 5th triples both into
        # player 4 (so the 16-18 triple is overwritten) and the 6th into player 5; reproduced here.
        for n, base in zip((1, 2, 3, 4, 4, 5), (7, 10, 13, 16, 19, 22)):
            self.c[f"{side}Player{n}"] = _two(p[base])
            self.c[f"{side}Player{n}Points"] = _two(p[base + 1])
            self.c[f"{side}Player{n}FoulNumber"] = dec(p[base + 2], 0)

    def _general(self, p: bytes) -> None:
        if len(p) < 24:
            return
        c = self.c
        c["Period"] = bcd(p[6], 0)
        if p[7] == 17:
            c["InternalClockStatus"] = "R"
        elif p[7] == 18:
            c["InternalClockStatus"] = "S"
        if 255 not in (p[8], p[9], p[10]):
            c.update(ClockMinutesTens=dec(p[8], 1), ClockMinutesOnes=dec(p[8], 0), ClockSecondTens=dec(p[9], 1),
                     ClockSecondOnes=dec(p[9], 0), ClockTenthsSecond=dec(p[10], 0))
        else:
            c.update(ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=" ", ClockSecondOnes=" ",
                     ClockTenthsSecond=" ")
        if p[11] != 255 and p[12] != 255:
            c.update(ShotClockSecondTens=dec(p[11], 1), ShotClockSecondOnes=dec(p[11], 0),
                     ShotClockTenthsSecond=dec(p[12], 0))
        else:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=" ", ShotClockTenthsSecond=" ")
        if p[13] != 255:
            c.update(TimeoutClockSecondTens=dec(p[13], 1), TimeoutClockSecondOnes=dec(p[13], 0))
        else:
            c.update(TimeoutClockSecondTens=" ", TimeoutClockSecondOnes=" ")
        c.update(HomeScoreHundreds=" ", HomeScoreTens=dec(p[16], 1), HomeScoreOnes=dec(p[16], 0),
                 GuestScoreHundreds=" ", GuestScoreTens=dec(p[17], 1), GuestScoreOnes=dec(p[17], 0),
                 HomeFoulTens=dec(p[18], 1), HomeFoulOnes=dec(p[18], 0),
                 GuestFoulTens=dec(p[19], 1), GuestFoulOnes=dec(p[19], 0),
                 HomeTimeouts=dec(p[20], 0), GuestTimeouts=dec(p[21], 0),
                 HomePossession="<" if p[22] == 1 else " ", GuestPossession=">" if p[23] == 1 else " ")


PROTOCOLS = {"UltraScore": lambda: UltraScoreProtocol(UltraScoreBasketball())}
