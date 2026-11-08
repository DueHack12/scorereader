"""FarmTek timer: exactly 7 ASCII bytes then CR: HHH(secs) mode tenths hundredths millis."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A


class FarmTekProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, 0x0D)
            if end < 0:
                return
            pkt = bytes(buf[:end])
            del buf[:end + 1]
            if len(pkt) == 7:
                yield pkt
            else:
                self.reject()


class FarmTekTiming(Decoder):
    contract = "Timer"
    event = "Timer"
    parse_type = "OnlySecondsClock"  # ScoreConnect builds Timer(SbdataParseType.OnlySecondsClock)

    def decode(self, p: bytes) -> None:
        if len(p) < 7:
            return
        self.c.update(ClockSecondHundreds=A(p[0]), ClockSecondTens=A(p[1]), ClockSecondOnes=A(p[2]),
                      ClockMode=A(p[3]), ClockTenthsSecond=A(p[4]), ClockHundredths=A(p[5]),
                      ClockMilliseconds=A(p[6]))


PROTOCOLS = {"Farmtek_Timing": lambda: FarmTekProtocol(FarmTekTiming())}
