"""Quince basketball scoreboard (RS-232, 19200 baud).

Wire format: ``SOH(01) 00 LEN <LEN-1 bytes> LAST CR(0D)``: after the ``01 00`` header, ``LEN`` counts itself and
every byte up to and including LAST (the final byte before the CR). No checksum is verified. The decoder
receives the ``LEN`` bytes starting at LEN: ``p[0]`` = LEN, ``p[1]`` and ``p[2]`` = source/command bytes,
``p[3]`` = field selector, ``p[4:]`` = BCD data. See docs/vendors/quince.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find_pair
from .common import ascii_char, bcd

SOH, CR = 0x01, 0x0D


class QuinceProtocol(Protocol):
    """Header ``01 00``, length byte, ``LEN`` bytes, then CR.

    ScoreConnect only releases a packet once it has seen the ``CR 01`` that starts the *next* one, so every
    update arrives one packet late. This version completes a packet as soon as its own CR has arrived, which
    produces the same packets (it only accepts what ScoreConnect would) without the added delay.
    """

    def extract(self):
        buf = self.buf
        while True:
            j = find_pair(buf, SOH, 0x00)  # index of the 00 that follows an 01
            if j < 0:
                if len(buf) > 1:
                    del buf[:-1]
                return
            if j - 1:
                del buf[: j - 1]  # junk before the header
            if len(buf) < 3:
                return
            size = buf[2]
            end = 2 + size  # index of the CR
            if size == 0:
                del buf[:2]
                self.reject()
                continue
            if len(buf) <= end:
                return
            if buf[end] != CR:
                del buf[:2]  # not a packet: resynchronise on the next header
                self.reject()
                continue
            pkt = bytes(buf[2:end])
            del buf[: end + 1]
            yield pkt


class QuinceBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        try:  # a short packet updates the fields it reaches, like ScoreConnect
            self._decode(p)
        except IndexError:
            pass

    def _decode(self, p: bytes) -> None:
        c = self.c
        if p[1] == 0xC5:  # clock run/stop
            c["InternalClockStatus"] = "R" if p[3] == 1 else "S"
            return
        if p[2] == 0x45:  # shot clock
            self._shot_clock(p)
            return
        kind = p[3]
        if kind == 0x02:
            self._main_clock(p)
        elif kind == 0x36:
            c.update(HomeScoreHundreds=bcd(p[4], 0), HomeScoreTens=bcd(p[5], 1), HomeScoreOnes=bcd(p[5], 0))
        elif kind == 0x46:
            c.update(GuestScoreHundreds=bcd(p[4], 0), GuestScoreTens=bcd(p[5], 1), GuestScoreOnes=bcd(p[5], 0))
        elif kind == 0x38:
            c.update(HomeFoulTens=bcd(p[4], 1), HomeFoulOnes=bcd(p[4], 0))
        elif kind == 0x48:
            c.update(GuestFoulTens=bcd(p[4], 1), GuestFoulOnes=bcd(p[4], 0))
        elif kind == 0x33:
            c["HomeTimeouts"] = bcd(p[4], 0)
        elif kind == 0x43:
            c["GuestTimeouts"] = bcd(p[4], 0)
        elif kind in (0x53, 0x63):  # player numbers: 'S' home, 'c' guest
            side = "Home" if kind == 0x53 else "Guest"
            for n in range(5):
                c[f"{side}Player{n + 1}"] = _pair(p[4 + n])
        elif kind in (0x51, 0x61):  # player points: 'Q' home, 'a' guest
            side = "Home" if kind == 0x51 else "Guest"
            for n in range(5):
                c[f"{side}Player{n + 1}Points"] = _pair(p[4 + n])
        elif kind in (0x54, 0x64):  # player fouls: 'T' home, 'd' guest; one BCD nibble per player
            side = "Home" if kind == 0x54 else "Guest"
            for n in range(5):
                c[f"{side}Player{n + 1}FoulNumber"] = bcd(p[4 + n // 2], 1 - n % 2)
        elif kind == 0x31:
            c["HomeTeamName"] = _team_name(p)
        elif kind == 0x41:
            c["GuestTeamName"] = _team_name(p)

    def _main_clock(self, p: bytes) -> None:
        c = self.c
        c.update(ClockMinutesTens=bcd(p[6], 1), ClockMinutesOnes=bcd(p[6], 0), ClockSecondTens=bcd(p[7], 1),
                 ClockSecondOnes=bcd(p[7], 0))
        if all(c[k] in (" ", "0") for k in ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens")):
            c["ClockTenthsSecond"] = bcd(p[8], 1)
            c["ClockMode"] = "."
        else:
            c["ClockTenthsSecond"] = "0"
            c["ClockMode"] = ":"

    def _shot_clock(self, p: bytes) -> None:
        if len(p) < 7 or p[0] != 7 or p[6] != 0x91:
            i = 5 if p[3] == 1 else 6
            self.c.update(ShotClockSecondTens=bcd(p[i], 1), ShotClockSecondOnes=bcd(p[i], 0),
                          ShotClockTenthsSecond=bcd(p[i + 1], 1))


def _pair(b: int) -> str:
    return bcd(b, 1) + bcd(b, 0)


def _team_name(p: bytes) -> str:
    return "".join(ascii_char(b) for b in p[5 : len(p) - 2])


PROTOCOLS = {"Quince_Basketball": lambda: QuinceProtocol(QuinceBasketball())}
