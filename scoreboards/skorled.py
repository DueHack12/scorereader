"""Skorled basketball scoreboard (RS-232, 115200 baud).

Wire format: ``STX(02) b1 LEN b3 b4 TYPE <data…> XOR`` where the packet is ``LEN + 4`` bytes from the STX and
the last byte is the XOR of all the bytes before it. ``TYPE`` (``B`` game, ``C``/``E`` home/guest player
points and fouls, ``D``/``F`` home/guest player numbers) is byte 5; data is ASCII. See docs/vendors/skorled.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char, xor8

STX = 0x02


class SkorledProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            start = find(buf, STX)
            if start < 0:
                buf.clear()  # nothing but garbage
                return
            del buf[:start]
            if len(buf) < 3:
                return
            size = buf[2] + 4
            if len(buf) < size:
                return
            pkt = bytes(buf[:size])
            if xor8(pkt, 0, size - 1) == pkt[-1]:
                del buf[:size]
                yield pkt
            else:
                # ScoreConnect swallows the whole claimed length (and only counts every tenth failure); dropping
                # just the STX lets a false STX in line noise resynchronise on the real packet behind it.
                del buf[:1]
                self.reject()


class SkorledBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        try:  # a short packet updates the fields it reaches, like ScoreConnect
            self._decode(p)
        except IndexError:
            pass

    def _decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        c["ClockMode"] = ":"
        kind = p[5]
        if kind == 0x42:  # 'B' game state
            if p[12] in (0x3A, 0x20):  # ':' or blank separator
                c.update(ClockMode=":", ClockMinutesTens=a(10), ClockMinutesOnes=a(11), ClockSecondTens=a(13),
                         ClockSecondOnes=a(14), ClockTenthsSecond="0")
            else:
                c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=a(10),
                         ClockSecondOnes=a(11), ClockTenthsSecond=a(13))
            if p[17] == 0x20:
                c.update(ShotClockSecondTens=a(15), ShotClockSecondOnes=a(16), ShotClockTenthsSecond=" ")
            elif p[17] == 0x2E:
                c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=a(15), ShotClockTenthsSecond=a(16))
            c["Period"] = a(24)
            c["Horn"] = "H" if p[8] == 0x38 else " "
            c.update(HomeScoreHundreds=a(25), HomeScoreTens=a(26), HomeScoreOnes=a(27), HomeFoulTens=a(28),
                     HomeFoulOnes=a(29))
            self._side_flags(p, "Home", 30)
            c.update(HomeTimeouts=a(31), GuestScoreHundreds=a(32), GuestScoreTens=a(33), GuestScoreOnes=a(34),
                     GuestFoulTens=a(35), GuestFoulOnes=a(36))
            self._side_flags(p, "Guest", 37)
            c["GuestTimeouts"] = a(38)
            sub = a(18)
            if sub in "GHgh":
                c.update(TimeoutClockSecondTens=a(22), TimeoutClockSecondOnes=a(23))
            elif sub == "T":
                c["InternalClockStatus"] = "R"
            elif sub == "t":
                c["InternalClockStatus"] = "S"
        elif kind in (0x43, 0x45):  # 'C' home / 'E' guest: foul number and points per player
            side = "Home" if kind == 0x43 else "Guest"
            for n in range(5):
                c[f"{side}Player{n + 1}FoulNumber"] = a(18 + 3 * n)
                c[f"{side}Player{n + 1}Points"] = a(19 + 3 * n) + a(20 + 3 * n)
        elif kind in (0x44, 0x46):  # 'D' home / 'F' guest: player numbers
            side = "Home" if kind == 0x44 else "Guest"
            for n in range(5):
                c[f"{side}Player{n + 1}"] = a(14 + 2 * n) + a(15 + 2 * n)

    def _side_flags(self, p: bytes, side: str, i: int) -> None:
        """Possession arrow and bonus lamps are packed in one character: '1'/'9' bonus, '2'/':' double bonus,
        '9' and above also carry possession. ScoreConnect points *both* teams' arrow at '<'."""
        ch = ascii_char(p[i])
        self.c[f"{side}Possession"] = "<" if ch > "8" else " "
        self.c[f"{side}Bonus"] = "B" if ch in ("1", "9") else " "
        self.c[f"{side}DoubleBonus"] = "B" if ch in ("2", ":") else " "


PROTOCOLS = {"Skorled_Basketball": lambda: SkorledProtocol(SkorledBasketball())}
