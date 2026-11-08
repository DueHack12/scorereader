"""Uno scoreboards (Basketball and Generic): ASCII packets F8 ... 0D."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A

START, END = 0xF8, 0x0D


class UnoProtocol(Protocol):
    """Packet = first F8 up to and including the first 0D. A 0D with no F8 before it is dropped."""

    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, END)
            if end < 0:
                return
            start = find(buf, START)
            pkt = bytes(buf[start:end + 1]) if 0 <= start < end else None
            del buf[:end + 1]
            if pkt is not None:
                yield pkt


class UnoBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 23:
            return
        c = self.c
        if p[19] == 49:  # '1': tenths display
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=A(p[4]),
                     ClockSecondOnes=A(p[5]), ClockTenthsSecond=A(p[6]))
        else:
            c.update(ClockMode=":", ClockMinutesTens=A(p[4]), ClockMinutesOnes=A(p[5]),
                     ClockSecondTens=A(p[6]), ClockSecondOnes=A(p[7]), ClockTenthsSecond="0")
        if p[22] == 49:
            if len(p) >= 25:
                c.update(ShotClockSecondTens=A(p[23]), ShotClockSecondOnes=A(p[24]))
        else:
            c.update(ShotClockSecondTens="0", ShotClockSecondOnes="0")
        c.update(Period=A(p[14]), HomeScoreHundreds=A(p[8]), HomeScoreTens=A(p[9]), HomeScoreOnes=A(p[10]),
                 GuestScoreHundreds=A(p[11]), GuestScoreTens=A(p[12]), GuestScoreOnes=A(p[13]),
                 HomeFoulTens=" ", HomeFoulOnes=A(p[15]),
                 # ScoreConnect stores the guest fouls digit in the *tens* slot and never sets the ones.
                 GuestFoulTens=A(p[16]),
                 HomeTimeouts=A(p[17]), GuestTimeouts=A(p[18]))


class UnoGeneric(Decoder):
    contract = "Generic"
    event = "Generic"

    def decode(self, p: bytes) -> None:
        if len(p) < 25:
            return
        c = self.c
        c.update(TOTimerMinutesOnes=A(p[1]), TOTimerSecondsTens=A(p[2]), TOTimerSecondsOnes=A(p[3]),
                 ClockDigit1=A(p[4]), ClockDigit2=A(p[5]), ClockDigit3=A(p[6]), ClockDigit4=A(p[7]),
                 HomeHundreds=A(p[8]), HomeTens=A(p[9]), HomeOnes=A(p[10]),
                 GuestHundreds=A(p[11]), GuestTens=A(p[12]), GuestOnes=A(p[13]),
                 Period=A(p[14]), HomeFouls=A(p[15]), GuestFouls=A(p[16]),
                 HomeNumberOfTO=A(p[17]), GuestNumberOfTO=A(p[18]),
                 ClockMode="." if p[19] == 49 else ":",
                 InternalClockStatus="R" if p[20] == 49 else "S",
                 PlayClockStatusInternal="R" if p[21] == 49 else "S",
                 PlayClockDisplay="1" if p[22] == 49 else "0",
                 PlayClock=A(p[23]) + A(p[24]))


PROTOCOLS = {
    "Uno_Basketball": lambda: UnoProtocol(UnoBasketball()),
    "Uno_Generic": lambda: UnoProtocol(UnoGeneric()),
}
