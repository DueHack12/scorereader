"""Nisasport basketball (scoreboard feed) and Nisasport TV basketball (ASCII feed).

Main:  ``FF`` + 18 data bytes; the next ``FF`` opens the next packet. Data bytes carry a high-nibble tag and
       a BCD low nibble; byte 1 is 0x80 (main page) or 0xA0 (period page).
TV:    37 bytes ``01 13 'T' ... 04`` (ASCII digits).
See docs/vendors/nisasport.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char, bcd

__all__ = ["PROTOCOLS"]

_MAIN_LEN = 19      # 18 data bytes + the closing 0xFF
_TV_LEN = 37


class NisasportProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            a = find(buf, 0xFF)
            if a < 0:
                buf.clear()  # nothing but junk
                return
            b = find(buf, 0xFF, a + 1)
            if b < 0:
                del buf[:a]
                return
            pkt = bytes(buf[a + 1 : b + 1])  # data + closing FF
            del buf[:b]                      # the closing FF opens the next packet
            if len(pkt) == _MAIN_LEN:
                yield pkt
            else:
                self.reject()


class NisasportTvProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, 0x04)
            if end < 0:
                return
            start = end - (_TV_LEN - 1)
            pkt = bytes(buf[start : end + 1]) if start >= 0 else b""
            del buf[: end + 1]
            if pkt[:3] == b"\x01\x13T":
                yield pkt
            else:
                self.reject()


def _hi(p: bytes, i: int) -> str:
    return bcd(p[i], 1)


class BasketballDecoder(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 18:
            return
        c = self.c
        c["InternalClockStatus"] = "R" if p[0] & 0x20 else "S"
        c["Horn"] = "H" if p[0] & 0x02 else " "
        if p[1] == 0x80:
            if self._plausible(p):
                self._main_page(p)
        elif p[1] == 0xA0:
            c["Period"] = bcd(p[5], 0) if _hi(p, 5) == "2" else c.get("Period", " ")

    @staticmethod
    def _plausible(p: bytes) -> bool:
        """Each digit byte has a fixed high-nibble tag; packets whose tags don't fit are torn."""
        return (_hi(p, 6) == "1" and _hi(p, 7) == "0"
                and (p[5] == 127 or _hi(p, 5) == "0")
                and (p[8] == 127 or _hi(p, 8) == "1")
                and (p[12] == 31 or _hi(p, 12) == "0")
                and p[13] & 0xF0 == 0
                and _hi(p, 2) == _hi(p, 3) == _hi(p, 4) == "0"
                and _hi(p, 9) == _hi(p, 10) == _hi(p, 11) == "0")

    def _main_page(self, p: bytes) -> None:
        c = self.c
        if bcd(p[8], 0) == " ":  # no 4th clock digit: seconds.tenths
            c.update(ClockMode=".", ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=bcd(p[5], 0),
                     ClockSecondOnes=bcd(p[6], 0), ClockTenthsSecond=bcd(p[7], 0))
        else:
            c.update(ClockMode=":", ClockMinutesTens=bcd(p[5], 0), ClockMinutesOnes=bcd(p[6], 0),
                     ClockSecondTens=bcd(p[7], 0), ClockSecondOnes=bcd(p[8], 0))
        c["ShotClockSecondTens"] = bcd(p[12], 0)
        c["ShotClockSecondOnes"] = bcd(p[13], 0)
        h2, h3, h4 = bcd(p[2], 0), bcd(p[3], 0), bcd(p[4], 0)
        if h4 == " ":
            c["HomeScoreHundreds"] = " "
            c["HomeScoreTens"] = " " if h3 == " " else h2
            c["HomeScoreOnes"] = h2 if h3 == " " else h3
        else:
            c.update(HomeScoreHundreds=h2, HomeScoreTens=h3, HomeScoreOnes=h4)
        c["GuestScoreHundreds"] = bcd(p[9], 0)
        c["GuestScoreTens"] = bcd(p[10], 0)
        if _hi(p, 11) == "0":  # otherwise keep the last good digit
            c["GuestScoreOnes"] = bcd(p[11], 0)
        c["HomeFoulTens"] = c["GuestFoulTens"] = " "
        if _hi(p, 14) == "1":
            c["HomeFoulOnes"] = bcd(p[14], 0)
        if _hi(p, 17) == "1":
            c["GuestFoulOnes"] = bcd(p[17], 0)
        # ScoreConnect tests (byte & 7) != 15, always true, so timeouts always come out blank
        c["HomeTimeouts"] = c["GuestTimeouts"] = " "


class TvBasketballDecoder(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 19:
            return
        c = self.c
        a = [ascii_char(p[i]) for i in (3, 4, 5)]
        if a[2] != " ":
            v = a
        elif a[1] != " ":
            v = [" ", a[0], a[1]]
        elif a[0] != " ":
            v = [" ", " ", a[0]]
        else:
            v = None  # blank score: keep the last one
        if v:
            c.update(zip(("HomeScoreHundreds", "HomeScoreTens", "HomeScoreOnes"), v))
        if p[9] == 32:
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=ascii_char(p[6]),
                     ClockSecondOnes=ascii_char(p[7]), ClockTenthsSecond=ascii_char(p[8]))
        else:
            c.update(ClockMode=":", ClockMinutesTens=ascii_char(p[6]), ClockMinutesOnes=ascii_char(p[7]),
                     ClockSecondTens=ascii_char(p[8]), ClockSecondOnes=ascii_char(p[9]), ClockTenthsSecond="0")
        c.update(GuestScoreHundreds=ascii_char(p[10]), GuestScoreTens=ascii_char(p[11]),
                 GuestScoreOnes=ascii_char(p[12]), ShotClockSecondTens=ascii_char(p[13]),
                 ShotClockSecondOnes=ascii_char(p[14]), HomeFoulOnes=ascii_char(p[15]),
                 GuestFoulOnes=ascii_char(p[18]))


PROTOCOLS = {
    "Nisasport_Basketball": lambda: NisasportProtocol(BasketballDecoder()),
    "NisasportTv_Basketball": lambda: NisasportTvProtocol(TvBasketballDecoder()),
}
