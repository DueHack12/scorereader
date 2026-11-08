"""Bodet basketball and volleyball scoreboards (RS-232, 9600 baud).

Wire format: ``SOH(01) <addr> STX(02) <message…> ETX(03)``. There is no checksum and no length byte. The
message handed to the decoder is everything after the STX *including* the ETX, so ``p[0]`` is an unknown
byte, ``p[1:3]`` are two ASCII digits naming the message type and ``p[3]`` is a flag byte, followed by
ASCII data. See docs/vendors/bodet.md.
"""
from __future__ import annotations

import re

from .base import Decoder, Protocol, find
from .common import ascii_char

SOH, STX, ETX = 0x01, 0x02, 0x03

_INT = re.compile(r"\s*[+-]?[0-9]+\s*", re.ASCII)


def _to_int(chars: str) -> int:
    """Integer value of a string the way Convert.ToInt32 reads it (surrounding blanks ok); 0 if invalid."""
    return int(chars) if _INT.fullmatch(chars) else 0


def _slice_int(p: bytes, first: int, last: int) -> int:
    """Integer in raw bytes p[first..last] (inclusive); 0 when the packet is too short or not a number."""
    if last >= len(p):
        return 0
    return _to_int("".join(chr(b) for b in p[first : last + 1]))


def _three(value: int) -> str:
    """Score as three right-aligned characters; zero is blank (ScoreConnect formats with '###')."""
    return ("" if value == 0 else str(value)).rjust(3)[:3]


def _name(p: bytes, offset: int) -> str:
    return "".join(ascii_char(p[offset + i]) for i in range(8) if len(p) > i)


class BodetProtocol(Protocol):
    """First ETX ends a message; the first SOH before it starts one (and must be followed by <addr> STX)."""

    def extract(self):
        buf = self.buf
        while True:
            etx = find(buf, ETX)
            if etx < 0:
                return
            soh = find(buf, SOH)
            if 0 <= soh < etx:
                frame = bytes(buf[soh : etx + 1])
                if len(frame) > 2 and frame[2] == STX:
                    del buf[: etx + 1]
                    yield frame[3:]
                    continue
                self.reject()
            del buf[: etx + 1]


class _Base(Decoder):
    def decode(self, p: bytes) -> None:
        try:  # a short message updates the fields it reaches, like ScoreConnect
            self._decode(p)
        except IndexError:
            pass

    def _decode(self, p: bytes) -> None:
        raise NotImplementedError

    @staticmethod
    def _stopped(p: bytes) -> str:
        return "S" if p[3] & 2 else "R"


class BodetBasketball(_Base):
    contract = "Basketball"
    event = "Basketball"

    def _decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        kind = _slice_int(p, 1, 2)
        if kind == 18:  # clock, timeouts, period
            if a(7) != "D":
                c.update(ClockMode=":", ClockMinutesTens=a(5), ClockMinutesOnes=a(6),
                         ClockSecondTens=a(7), ClockSecondOnes=a(8), ClockTenthsSecond="0")
            c["InternalClockStatus"] = self._stopped(p)
            c["Horn"] = "H" if p[3] & 4 else " "
            c["Period"] = a(13)
            c["HomeTimeouts"] = c["HomeFullTimeouts"] = a(9)
            c["GuestTimeouts"] = c["GuestFullTimeouts"] = a(10)
        elif kind == 50:  # shot clock
            if p[3] & 0x90 == 0x90:  # under 10 seconds: tenths shown
                c.update(ShotClockSecondTens="0", ShotClockSecondOnes=a(4), ShotClockTenthsSecond=a(5))
            else:
                c.update(ShotClockSecondTens=a(4), ShotClockSecondOnes=a(5), ShotClockTenthsSecond=" ")
            c["PlayClockStatusInternal"] = self._stopped(p)
        elif kind == 30:  # scores, 3 ASCII digits each
            home, guest = _three(_slice_int(p, 4, 6)), _three(_slice_int(p, 7, 9))
            c.update(HomeScoreHundreds=home[0], HomeScoreTens=home[1], HomeScoreOnes=home[2],
                     GuestScoreHundreds=guest[0], GuestScoreTens=guest[1], GuestScoreOnes=guest[2])
        elif kind == 31:  # team fouls and the player-foul display
            c.update(HomeFoulOnes=a(5), GuestFoulOnes=a(7), FoulPlayerTens=a(8), FoulPlayerOnes=a(9),
                     FoulPlayerNumberOfFouls=a(10))
        elif kind == 36:  # final-minute clock (seconds and tenths)
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0",
                     ClockSecondTens=a(3), ClockSecondOnes=a(4), ClockTenthsSecond=a(5))
        elif kind == 98:
            c["HomeTeamName"] = _name(p, 3)
        elif kind == 99:
            c["GuestTeamName"] = _name(p, 3)
        elif kind not in (19, 32, 33, 34):  # unknown message: possession arrows are cleared
            c.update(GuestPossession=" ", HomePossession=" ")


class BodetVolleyball(_Base):
    contract = "Volleyball"
    event = "Volleyball"

    def _serve(self, p: bytes) -> None:
        """Common header: clock status from bit 1, serving side from bit 2 (set = home)."""
        home = bool(p[3] & 4)
        self.c.update(InternalClockStatus=self._stopped(p),
                      GuestServe=" " if home else "*", HomeServe="*" if home else " ")

    def _decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        kind = _slice_int(p, 1, 2)
        if kind == 6:  # live score
            self._serve(p)
            c.update(Set=a(5), HomeGamesWon=a(7),  # ScoreConnect assigns HomeGamesWon twice (p[6] then p[7])
                     HomeScoreTens=a(8), HomeScoreOnes=a(9), GuestScoreTens=a(10), GuestScoreOnes=a(11),
                     HomeTimeout=a(12), GuestTimeout=a(13), TimeoutClockSecondTens=a(14),
                     TimeoutClockSecondOnes=a(15))
        elif kind == 7:  # clock
            self._serve(p)
            c.update(ClockMode=":", ClockMinutesTens=a(5), ClockMinutesOnes=a(6), ClockSecondTens=a(7),
                     ClockSecondOnes=a(8))
        elif kind == 8:  # set scores 1..3
            self._serve(p)
            for n in range(3):
                c[f"HomeScoreSet{n + 1}"] = a(5 + 4 * n) + a(6 + 4 * n)
                c[f"GuestScoreSet{n + 1}"] = a(7 + 4 * n) + a(8 + 4 * n)


PROTOCOLS = {
    "Bodet_Basketball": lambda: BodetProtocol(BodetBasketball()),
    "Bodet_Volleyball": lambda: BodetProtocol(BodetVolleyball()),
}
