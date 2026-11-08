"""Mondo / Cuma basketball: 02 type(0-6) fields... 03, fields introduced by control bytes."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_digit_or_blank as AD, blank_zero

STX, ETX = 0x02, 0x03

K_CLOCK, K_LASTMIN, K_SHOT, K_PERIOD, K_HOME, K_GUEST, K_HFOUL, K_GFOUL = 17, 18, 19, 21, 23, 31, 14, 15
_KEYS = {K_CLOCK, K_LASTMIN, K_SHOT, K_PERIOD, K_HOME, K_GUEST, K_HFOUL, K_GFOUL}


class MondoProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, ETX)
            if end < 0:
                return
            start = find(buf, STX)
            pkt = bytes(buf[start:end + 1]) if 0 <= start < end else None
            del buf[:end + 1]
            if pkt is None:
                continue
            if len(pkt) > 1 and pkt[1] <= 6:
                yield pkt
            else:
                self.reject()


class MondoBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        # Each field marker is looked up (first occurrence) in this fixed order.
        for key, need, fn in ((K_CLOCK, 5, self._clock), (K_LASTMIN, 7, self._last_minute),
                              (K_SHOT, 2, self._shot), (K_PERIOD, 1, self._period),
                              (K_HOME, 3, self._home), (K_GUEST, 3, self._guest),
                              (K_HFOUL, 2, self._hfoul), (K_GFOUL, 2, self._gfoul)):
            i = p.find(key)
            if i > 0 and i + need < len(p):
                fn(i, p)

    def _clock(self, i, p):
        self.c.update(ClockMinutesTens=AD(p[i + 1]), ClockMinutesOnes=AD(p[i + 2]), ClockSecondTens=AD(p[i + 4]),
                      ClockSecondOnes=AD(p[i + 5]), ClockTenthsSecond="0", ClockMode=":")

    def _last_minute(self, i, p):
        self.c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=AD(p[i + 4]),
                      ClockSecondOnes=AD(p[i + 5]), ClockTenthsSecond=AD(p[i + 7]), ClockMode=".")

    def _shot(self, i, p):
        self.c.update(ShotClockSecondTens=AD(p[i + 1]), ShotClockSecondOnes=AD(p[i + 2]))

    def _period(self, i, p):
        self.c["Period"] = AD(p[i + 1])

    def _score(self, side, i, p):
        if p[i + 3] in _KEYS:  # next field follows after two digits
            h, t, o = " ", AD(p[i + 1]), AD(p[i + 2])
        elif p[i + 2] in _KEYS:  # one digit
            h, t, o = " ", " ", AD(p[i + 1])
        else:
            h, t, o = blank_zero(AD(p[i + 1]), " "), AD(p[i + 2]), AD(p[i + 3])
        self.c.update({f"{side}ScoreHundreds": h, f"{side}ScoreTens": t, f"{side}ScoreOnes": o})

    def _home(self, i, p):
        self._score("Home", i, p)

    def _guest(self, i, p):
        self._score("Guest", i, p)

    def _foul(self, side, i, p):
        self.c.update({f"{side}FoulTens": blank_zero(AD(p[i + 1]), " "), f"{side}FoulOnes": AD(p[i + 2])})

    def _hfoul(self, i, p):
        self._foul("Home", i, p)

    def _gfoul(self, i, p):
        self._foul("Guest", i, p)


PROTOCOLS = {
    "Mondo_Basketball": lambda: MondoProtocol(MondoBasketball()),
    "Cuma_Basketball": lambda: MondoProtocol(MondoBasketball()),
}
