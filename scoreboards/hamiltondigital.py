"""Hamilton Digital hockey: packets end with LF (0A); first byte D4 (BCD nibbles) or 'T' (ASCII)."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A, bcd

CODE_BCD, CODE_ASCII = 0xD4, 0x54

_PENALTY = (("HomePenaltyPlayer1", 7), ("GuestPenaltyPlayer1", 13), ("HomePenaltyPlayer2", 19),
            ("GuestPenaltyPlayer2", 25))


class HamiltonDigitalProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, 0x0A)
            if end < 0:
                return
            pkt = bytes(buf[:end])
            del buf[:end + 1]
            if pkt and pkt[0] in (CODE_BCD, CODE_ASCII):
                yield pkt
            else:
                self.reject()


class HamiltonDigitalHockey(Decoder):
    contract = "HockeyLacrosse"
    event = "Hockey"

    def decode(self, p: bytes) -> None:
        if len(p) < 30:
            return
        f = (lambda b: bcd(b, 0)) if p[0] == CODE_BCD else A
        c = self.c
        mode = A(p[3])
        c["ClockMode"] = mode
        if mode == ":":
            c.update(ClockMinutesTens=f(p[1]), ClockMinutesOnes=f(p[2]), ClockSecondTens=f(p[4]),
                     ClockSecondOnes=f(p[5]), ClockTenthsSecond="0")
        else:
            c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=f(p[1]),
                     ClockSecondOnes=f(p[2]), ClockTenthsSecond=f(p[4]))
        for prefix, i in _PENALTY:
            c[prefix + "ClockMinutesTens"] = f(p[i])
            c[prefix + "ClockMinutesOnes"] = f(p[i + 1])
            c[prefix + "ClockSecondTens"] = f(p[i + 3])
            c[prefix + "ClockSecondOnes"] = f(p[i + 4])


PROTOCOLS = {"HamiltonDigital_Hockey": lambda: HamiltonDigitalProtocol(HamiltonDigitalHockey())}
