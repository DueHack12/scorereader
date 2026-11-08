"""Colosseo basketball: 01 LEN type data... xor|80 03, frames back to back (LEN+5 bytes each)."""
from __future__ import annotations

from .base import Decoder, Protocol
from .common import ascii_char as A, xor8


class ColosseoProtocol(Protocol):
    """ScoreConnect only decodes a frame once the next ``03 01`` boundary shows up; this version decodes as soon
    as the frame (length, trailing 03 and checksum) is complete, which yields the same packets sooner."""

    def extract(self):
        buf = self.buf
        i = 0
        while i < len(buf):
            if buf[i] != 1 or (i > 0 and buf[i - 1] != 3):
                i += 1
                continue
            if i + 1 >= len(buf):
                break
            total = buf[i + 1] + 5
            if i + total > len(buf):
                nxt = next((k for k in range(i + 1, len(buf)) if buf[k] == 1 and buf[k - 1] == 3), -1)
                if nxt < 0:
                    break
                self.reject()
                i = nxt
                continue
            pkt = bytes(buf[i:i + total])
            if pkt[-1] == 3 and (xor8(pkt, 0, total - 2) | 0x80) == pkt[-2]:
                del buf[:i + total]
                i = 0
                yield pkt
            else:
                self.reject()
                i += 1
        else:
            i = len(buf)
        if i:
            del buf[:i]


class ColosseoBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        c = self.c
        t = p[2] if len(p) > 2 else -1
        n = len(p)
        if t == 1 and n >= 11:
            # byte 3 ('R'/'S') is stored in ClockMode by ScoreConnect but immediately overwritten below.
            if p[5] == 80:
                c["Period"] = A(p[4])
            if A(p[8]) == ":":
                c.update(ClockMinutesTens=A(p[6]), ClockMinutesOnes=A(p[7]), ClockSecondTens=A(p[9]),
                         ClockSecondOnes=A(p[10]), ClockTenthsSecond=" ", ClockMode=":")
            else:
                c.update(ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=A(p[6]),
                         ClockSecondOnes=A(p[7]), ClockTenthsSecond=A(p[9]), ClockMode=".")
        elif t == 2 and n >= 20:
            home = A(p[19]) == "1"
            c.update(HomeScoreHundreds=A(p[3]), HomeScoreTens=A(p[4]), HomeScoreOnes=A(p[5]),
                     GuestScoreHundreds=A(p[6]), GuestScoreTens=A(p[7]), GuestScoreOnes=A(p[8]),
                     HomeTimeouts=A(p[15]), GuestTimeouts=A(p[16]), HomeFoulOnes=A(p[17]),
                     GuestFoulOnes=A(p[18]), HomePossession="<" if home else " ",
                     GuestPossession=" " if home else ">")
        elif t == 17 and n >= 6:
            if A(p[3]) == " ":
                c.update(ShotClockSecondTens=A(p[4]), ShotClockSecondOnes=A(p[5]), ShotClockTenthsSecond=" ")
            else:
                c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=A(p[3]), ShotClockTenthsSecond=A(p[5]))
        elif t == 7 and n >= 6:
            c.update(TimeoutClockSecondTens=A(p[4]), TimeoutClockSecondOnes=A(p[5]))


PROTOCOLS = {"Colosseo_basketball": lambda: ColosseoProtocol(ColosseoBasketball())}
