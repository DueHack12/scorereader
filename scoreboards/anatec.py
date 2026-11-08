"""Anatec (wired) and Anatec Wireless baseball and basketball scoreboards (RS-232, 9600 baud).

Wire format: ``CR(0D) <data…> LF(0A)``, all ASCII, no checksum. ScoreConnect accepts a packet only when
CR..LF (inclusive) is exactly 13 bytes (wired) or 23 bytes (wireless). See docs/vendors/anatec.md.
"""
from __future__ import annotations

import re

from .base import Decoder, Protocol, find
from .common import ascii_char

CR, LF = 0x0D, 0x0A
WIRED_SIZE = 13
WIRELESS_SIZE = 23


class AnatecProtocol(Protocol):
    """CR ... LF with a fixed packet size. Bytes up to the first LF are always consumed."""

    size = WIRED_SIZE

    def __init__(self, decoder: Decoder, size: int | None = None):
        super().__init__(decoder)
        if size is not None:
            self.size = size

    def extract(self):
        buf = self.buf
        while True:
            lf = find(buf, LF)
            if lf < 0:
                return
            cr = find(buf, CR)
            if 0 <= cr < lf:
                pkt = bytes(buf[cr : lf + 1])
                del buf[: lf + 1]
                if len(pkt) == self.size:
                    yield pkt
                else:
                    self.reject()
            else:
                del buf[: lf + 1]


class AnatecWirelessProtocol(AnatecProtocol):
    size = WIRELESS_SIZE


class _Base(Decoder):
    def decode(self, p: bytes) -> None:
        try:  # a short packet updates the fields it reaches, like ScoreConnect
            self._decode(p)
        except IndexError:
            pass

    def _decode(self, p: bytes) -> None:
        raise NotImplementedError


_INT = re.compile(r"\s*[+-]?[0-9]+\s*", re.ASCII)


def _int(text: str) -> int:
    """Integer value of a short string (surrounding blanks ok); 0 if it isn't a number."""
    return int(text) if _INT.fullmatch(text) else 0


class AnatecBaseball(_Base):
    contract = "BaseballSoftball"
    event = "Baseball"

    def _decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        c["ClockMode"] = ":"
        inning = _int(a(6) + a(7))
        outs = _int(a(5))
        # Top/bottom is inferred: a new inning means the visitors are batting; the same inning with fewer
        # outs than before means the halves flipped. Otherwise the previous value stands.
        previous = _int(c.get("InningTens", " ") + c.get("InningOnes", " "))
        if inning != previous or inning == 0:
            half = "T"
        elif outs < _int(c.get("Outs", " ")):
            half = "B"
        else:
            half = " "
        if half == "T":
            c.update(TopBottomInning="T", TopOfInning=".", BottomOfInning=" ")
        elif half == "B":
            c.update(TopBottomInning="B", TopOfInning=" ", BottomOfInning=".")
        c.update(Balls=a(3), Strikes=a(4), Outs=a(5), GuestRunTens=a(8), GuestRunOnes=a(9),
                 HomeRunTens=a(10), HomeRunOnes=a(11), AtBatTens=a(1), AtBatOnes=a(2),
                 InningTens=a(6), InningOnes=a(7))


_SHOT_TENTHS = {b: chr(ord("0") + b - 64) for b in range(64, 74)}  # 0x40..0x49 -> "0".."9"


class AnatecBasketball(_Base):
    contract = "Basketball"
    event = "Basketball"

    def _decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        if p[14] == 32:  # under a minute: seconds and tenths
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0",
                     ClockSecondTens=a(20), ClockSecondOnes=a(21), ClockTenthsSecond=a(15))
        else:
            c.update(ClockMode=":", ClockMinutesTens=a(20), ClockMinutesOnes=a(21),
                     ClockSecondTens=a(15), ClockSecondOnes=a(14), ClockTenthsSecond="0")
        c["Horn"] = "H" if p[16] == 7 else " "
        c.update(HomeScoreHundreds=a(17), HomeScoreTens=a(18), HomeScoreOnes=a(19),
                 GuestScoreHundreds=a(13), GuestScoreTens=a(12), GuestScoreOnes=a(11),
                 HomeTimeouts=a(10), GuestTimeouts=a(9), Period=a(7),
                 HomeFoulTens=a(3), HomeFoulOnes=a(4), GuestFoulTens=a(5), GuestFoulOnes=a(6))
        if "0" <= a(2) <= "9":  # whole seconds
            c.update(ShotClockSecondTens=a(1), ShotClockSecondOnes=a(2), ShotClockTenthsSecond=" ")
        else:  # single digit plus tenths, the tenths digit encoded as 0x40 + n
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes="0" if a(1) == " " else a(1),
                     ShotClockTenthsSecond=_SHOT_TENTHS.get(p[2], "0"))
        if p[8] == 84:  # 'T'
            c.update(HomePossession="<", GuestPossession=" ")
        elif p[8] == 71:  # 'G'
            c.update(HomePossession=" ", GuestPossession=">")
        else:
            c.update(HomePossession=" ", GuestPossession=" ")


PROTOCOLS = {
    "Anatec_Baseball": lambda: AnatecProtocol(AnatecBaseball()),
    # ScoreConnect wires the wired basketball decoder to a 13-byte packet although it reads byte 21, so as
    # registered upstream it can never decode. The 23-byte layout is the only one it can read; use that.
    "Anatec_Basketball": lambda: AnatecProtocol(AnatecBasketball(), WIRELESS_SIZE),
    "Anatec_Wireless_Baseball": lambda: AnatecWirelessProtocol(AnatecBaseball()),
    "Anatec_Wireless_Basketball": lambda: AnatecWirelessProtocol(AnatecBasketball()),
}
