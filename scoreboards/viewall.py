"""View All basketball scoreboard (RS-232).

Wire format: ``STX(02) f0;f1;…;f11;f12 ETX(03)``: ASCII text fields separated by ``;`` (exactly twelve of
them) with the last field ended by the ETX. Field 0 carries the STX and an unused value; fields 1 and 2 are
not decoded. No checksum. See docs/vendors/viewall.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char

STX, ETX, SEMI = 0x02, 0x03, 0x3B
SEPARATORS = 12


class ViewAllProtocol(Protocol):
    """First ETX ends a packet and the first STX before it starts one; it must hold exactly 12 semicolons."""

    def extract(self):
        buf = self.buf
        while True:
            etx = find(buf, ETX)
            if etx < 0:
                return
            stx = find(buf, STX)
            if 0 <= stx < etx:
                pkt = bytes(buf[stx : etx + 1])
                del buf[: etx + 1]
                if pkt.count(SEMI) == SEPARATORS:
                    yield pkt
                else:
                    self.reject()
            else:
                del buf[: etx + 1]


def _fields(p: bytes):
    """Split a packet into the byte lists between ';' / ETX delimiters (the text after the last delimiter is ignored)."""
    start = 0
    for i, b in enumerate(p):
        if b in (SEMI, ETX):
            yield p[start:i]
            start = i + 1


def _digits3(field: bytes, prefix: str) -> dict:
    """A score of 1 to 3 characters, right-aligned with '0' padding; other lengths leave the score alone."""
    n = len(field)
    if not 1 <= n <= 3:
        return {}
    d = "".join(ascii_char(b) for b in field).rjust(3, "0")
    return {f"{prefix}ScoreHundreds": d[0], f"{prefix}ScoreTens": d[1], f"{prefix}ScoreOnes": d[2]}


class ViewAllBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        c = self.c
        for num, f in enumerate(_fields(p)):
            a = lambda i: ascii_char(f[i])  # noqa: E731
            n = len(f)
            try:
                if num in (3, 4) and f:  # team names, first 8 characters
                    c["HomeTeamName" if num == 3 else "GuestTeamName"] = "".join(ascii_char(b) for b in f[:8])
                elif num == 5:
                    c.update(_digits3(f, "Home"))
                elif num == 6:
                    c.update(_digits3(f, "Guest"))
                elif num == 7:
                    c["Period"] = a(1) if n > 1 else a(0)
                elif num == 8:
                    c["InternalClockStatus"] = a(0)
                elif num == 9:
                    mode = a(2)
                    c["ClockMode"] = mode
                    if mode in (":", " "):
                        c.update(ClockMinutesTens=a(0), ClockMinutesOnes=a(1), ClockSecondTens=a(3),
                                 ClockSecondOnes=a(4), ClockTenthsSecond="0")
                    else:
                        c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=a(0),
                                 ClockSecondOnes=a(1), ClockTenthsSecond=a(3))
                elif num == 10:
                    if n == 0:
                        c.update(ShotClockSecondTens=" ", ShotClockSecondOnes="0")
                    elif n == 2:
                        c.update(ShotClockSecondTens=a(0), ShotClockSecondOnes=a(1))
                    else:
                        c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=a(0))
                elif num in (11, 12):
                    side = "Home" if num == 11 else "Guest"
                    c[f"{side}FoulTens"] = a(0) if n > 1 else " "
                    c[f"{side}FoulOnes"] = a(1) if n > 1 else a(0)
            except IndexError:
                pass  # empty or short field: leave the earlier value, like a field ScoreConnect cannot read


PROTOCOLS = {"ViewAll_Basketball": lambda: ViewAllProtocol(ViewAllBasketball())}
