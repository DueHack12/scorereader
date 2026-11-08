"""LGR basketball: 02 'type' data... 03 (ASCII)."""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char as A

STX, ETX = 0x02, 0x03
_TO = {"0": "0", "1": "1", "3": "2", "7": "3"}


class LGRProtocol(Protocol):
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
            if len(pkt) > 3:
                yield pkt
            else:
                self.reject()


class LGRBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        c = self.c
        t = p[1]
        if t == 105 and len(p) >= 11:  # 'i': clocks
            # Quirk: minutes mode needs the minutes-ones digit > '0', so exactly 10:00 reads as 00:00.x
            if p[2] >= 48 and p[3] > 48:
                c.update(ClockMinutesTens=A(p[2]), ClockMinutesOnes=A(p[3]), ClockSecondTens=A(p[4]),
                         ClockSecondOnes=A(p[5]), ClockMode=":", ClockTenthsSecond="0")
            else:
                c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=A(p[4]),
                         ClockSecondOnes=A(p[5]), ClockTenthsSecond=A(p[6]), ClockMode=".")
            if p[10] == 84:  # 'T': the second display shows a timeout clock
                c.update(TimeoutClockSecondTens=A(p[7]), TimeoutClockSecondOnes=A(p[8]))
            else:
                c.update(InternalClockStatus=A(p[10]), ShotClockSecondTens=A(p[7]), ShotClockSecondOnes=A(p[8]))
        elif t == 50 and len(p) >= 8:  # '2': scores
            c.update(HomeScoreHundreds=A(p[2]), HomeScoreTens=A(p[3]), HomeScoreOnes=A(p[4]),
                     GuestScoreHundreds=A(p[5]), GuestScoreTens=A(p[6]), GuestScoreOnes=A(p[7]))
        elif t == 51 and len(p) >= 9:  # '3': fouls, timeouts, period
            c.update(HomeFoulTens=A(p[2]), HomeFoulOnes=A(p[3]), HomeTimeouts=_TO.get(A(p[4]), " "),
                     Period=A(p[5]), GuestTimeouts=_TO.get(A(p[6]), " "),
                     GuestFoulTens=A(p[7]), GuestFoulOnes=A(p[8]))
        elif t == 42 and len(p) >= 4:  # '*': possession
            if p[3] == 48:
                c.update(HomePossession=" ", GuestPossession=" ")
            elif p[3] == 49:
                c.update(HomePossession="<", GuestPossession=" ")
            elif p[2] == 50:  # checks byte 2 (not 3) for the guest arrow, as ScoreConnect does
                c.update(HomePossession=" ", GuestPossession=">")


PROTOCOLS = {"LGR_Basketball": lambda: LGRProtocol(LGRBasketball())}
