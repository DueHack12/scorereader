"""Westerstrand basketball scoreboards.

**Westerstrand Basic 250** (115200 baud RS-485): fixed 90-byte frames::

    02 … 03 chk          chk (byte 89) = XOR of bytes 1..88 (everything after the STX, ETX included)

All fields are ASCII at fixed offsets (clock 5-9, status 7, shot clock 13-15, home score 31-33, guest score 34-36,
period 74).

**Westerstrand Basic 200** (19200 baud RS-485): short variable-length records::

    3F … 03 chk          chk = XOR of every byte from the 0x3F ('?') through the ETX; a result of 2 or 3 is sent as 0x20

``packet[4]`` is the record type: ``!`` clock, ``$`` shot clock / timeout clock, ``&`` score, ``%`` period and
possession, ``#`` team fouls. Both formats leave the checksum byte consumed together with the frame.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char, xor8

__all__ = ["Westerstrand250Protocol", "Westerstrand200Protocol", "PROTOCOLS"]

FRAME_250 = 90


def _a(p: bytes, i: int) -> str:
    return ascii_char(p[i])


class _Base(Protocol):
    """Shared STX/ETX scanning: finds an ETX, the start byte before it, and consumes through the checksum."""

    start = 0x02

    def frame_ok(self, frame: bytes) -> bool:
        raise NotImplementedError

    def extract(self):
        buf = self.buf
        while True:
            etx = find(buf, 3)
            if etx < 0 or len(buf) < etx + 2:
                return
            s = find(buf, self.start)
            if 0 <= s < etx:
                frame = bytes(buf[s : etx + 2])
                del buf[: etx + 2]
                if self.frame_ok(frame):
                    yield frame
                else:
                    self.reject()
            else:
                del buf[: etx + 2]


class Westerstrand250Protocol(_Base):
    def frame_ok(self, frame: bytes) -> bool:
        return len(frame) == FRAME_250 and xor8(frame, 1, 89) == frame[89]


class Westerstrand200Protocol(_Base):
    start = 0x3F

    def frame_ok(self, frame: bytes) -> bool:
        x = xor8(frame, 0, len(frame) - 1)
        return (0x20 if x in (2, 3) else x) == frame[-1]


# --------------------------------------------------------------------------- decoders
class Westerstrand250Basketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 75:
            return
        c = self.c
        if p[9] == 32:  # under a minute: SS.T
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=_a(p, 5),
                     ClockSecondOnes=_a(p, 6), ClockTenthsSecond=_a(p, 8))
        else:
            c.update(ClockMode=":", ClockMinutesTens=_a(p, 5), ClockMinutesOnes=_a(p, 6), ClockSecondTens=_a(p, 8),
                     ClockSecondOnes=_a(p, 9), ClockTenthsSecond="0")
        if p[7] == 65:      # 'A'
            c["InternalClockStatus"] = "S"
        elif p[7] == 66:    # 'B'
            c["InternalClockStatus"] = "R"
        if _a(p, 15) == ".":
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=_a(p, 13), ShotClockTenthsSecond=_a(p, 14))
        else:
            c.update(ShotClockSecondTens=_a(p, 13), ShotClockSecondOnes=_a(p, 14), ShotClockTenthsSecond=" ")
        if p[33] == 32:
            c.update(HomeScoreHundreds=" ", HomeScoreTens=_a(p, 31), HomeScoreOnes=_a(p, 32))
        else:
            c.update(HomeScoreHundreds=_a(p, 31), HomeScoreTens=_a(p, 32), HomeScoreOnes=_a(p, 33))
        c.update(GuestScoreHundreds=_a(p, 34), GuestScoreTens=_a(p, 35), GuestScoreOnes=_a(p, 36))
        if p[74] != 32:
            c["Period"] = _a(p, 74)


class Westerstrand200Basketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def _clock(self, p: bytes) -> None:
        if p[9] == 32:
            self.c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=_a(p, 6),
                          ClockSecondOnes=_a(p, 7), ClockTenthsSecond=_a(p, 8))
        else:
            self.c.update(ClockMode=":", ClockMinutesTens=_a(p, 6), ClockMinutesOnes=_a(p, 7),
                          ClockSecondTens=_a(p, 8), ClockSecondOnes=_a(p, 9), ClockTenthsSecond="0")

    def decode(self, p: bytes) -> None:
        if len(p) < 5:
            return
        p = p.ljust(11, b" ")  # short records read as blank columns instead of failing
        c = self.c
        kind = p[4]
        if kind == 33:  # '!' game clock
            self._clock(p)
        elif kind == 36:  # '$'
            if p[5] == 32:  # shot clock
                if p[7] == 46:
                    c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=_a(p, 6), ShotClockTenthsSecond=_a(p, 8))
                elif p[8] != 32:
                    c.update(ShotClockSecondTens=_a(p, 6), ShotClockSecondOnes=_a(p, 8), ShotClockTenthsSecond=" ")
                else:
                    c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=_a(p, 6), ShotClockTenthsSecond=" ")
            elif p[5] == 36 and p[10] == 67:  # 'C': game clock again
                self._clock(p)
            elif p[5] == 36 and p[10] == 32:  # timeout clock
                c.update(TimeoutClockSecondTens=_a(p, 6), TimeoutClockSecondOnes=_a(p, 7))
        elif kind == 38:  # '&' score
            if p[5] == 33:
                if p[8] == 32:
                    c.update(HomeScoreHundreds=" ", HomeScoreTens=_a(p, 6), HomeScoreOnes=_a(p, 7))
                else:
                    c.update(HomeScoreHundreds=_a(p, 6), HomeScoreTens=_a(p, 7), HomeScoreOnes=_a(p, 8))
            elif p[5] == 41:
                if p[8] == 32:  # a two-digit guest score reads as its second digit (ScoreConnect quirk)
                    c.update(GuestScoreHundreds=" ", GuestScoreTens=" ", GuestScoreOnes=_a(p, 7))
                else:
                    c.update(GuestScoreHundreds=_a(p, 6), GuestScoreTens=_a(p, 7), GuestScoreOnes=_a(p, 8))
        elif kind == 37:  # '%'
            if p[5] == 34:
                if p[6] == 32 and p[7] == 56:
                    c.update(HomePossession=" ", GuestPossession=">")
                elif p[6] == 56 and p[7] == 32:
                    c.update(HomePossession="<", GuestPossession=" ")
            elif p[5] != 37:
                c["Period"] = _a(p, 6)
        elif kind == 35:  # '#'
            if p[5] == 36:
                c.update(GuestFoulTens=_a(p, 6), GuestFoulOnes=_a(p, 7))
            else:
                c.update(HomeFoulTens=_a(p, 5), HomeFoulOnes=_a(p, 6))


PROTOCOLS = {
    "Westerstrand_Basketball": lambda: Westerstrand250Protocol(Westerstrand250Basketball()),
    "Westerstrand200_basketball": lambda: Westerstrand200Protocol(Westerstrand200Basketball()),
}
