"""Fujitsu basketball scoreboard (RS-232, 57600 baud).

Wire format: ``STX(02) <type> <data…> CR(0D)``, 100 bytes from STX to CR inclusive, ASCII, no checksum.
``type`` is ``'1'`` (game), ``'2'`` (home players) or ``'3'`` (guest players). See docs/vendors/fujitsu.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char

STX, CR = 0x02, 0x0D
PACKET_SIZE = 100


class FujitsuProtocol(Protocol):
    """First CR ends a packet and the first STX before it starts one; it must span exactly 100 bytes."""

    def extract(self):
        buf = self.buf
        while True:
            cr = find(buf, CR)
            if cr < 0:
                return
            stx = find(buf, STX)
            pkt = bytes(buf[stx : cr + 1]) if 0 <= stx < cr else b""
            # ScoreConnect leaves the buffer untouched when the STX is missing or after the CR, which wedges
            # the stream on a stray CR; here the bytes through the CR are dropped so the next packet is found.
            del buf[: cr + 1]
            if not pkt:
                continue
            if len(pkt) == PACKET_SIZE:
                yield pkt
            else:
                self.reject()


class FujitsuBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        try:  # a short packet updates the fields it reaches, like ScoreConnect
            self._decode(p)
        except IndexError:
            pass

    def _clocks(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        if p[4] == 0x2E:  # '.': seconds.tenths
            c.update(ClockMode=".", ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=a(2),
                     ClockSecondOnes=a(3), ClockTenthsSecond=a(5))
        else:
            c.update(ClockMode=":", ClockMinutesTens=a(2), ClockMinutesOnes=a(3), ClockSecondTens=a(5),
                     ClockSecondOnes=a(6), ClockTenthsSecond=" ")
        if p[9] == 0x2E:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=a(8), ShotClockTenthsSecond=a(10))
        else:
            c.update(ShotClockSecondTens=a(9), ShotClockSecondOnes=a(10), ShotClockTenthsSecond=" ")

    def _decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        kind = p[1]
        if kind == 0x31:  # '1' game state
            self._clocks(p)
            c["HomeTeamName"] = a(13) + a(14) + a(15)
            c["GuestTeamName"] = a(16) + a(17) + a(18)
            c["Period"] = a(19)
            if a(20) == "2":
                c.update(GuestPossession=">", HomePossession=" ")
            else:  # anything else, including no arrow, reads as home
                c.update(GuestPossession=" ", HomePossession="<")
            c.update(HomeScoreHundreds=a(21), HomeScoreTens=a(22), HomeScoreOnes=a(23),
                     GuestScoreHundreds=a(24), GuestScoreTens=a(25), GuestScoreOnes=a(26),
                     HomeFoulOnes=a(27), GuestFoulOnes=a(28), HomeTimeouts=a(29), GuestTimeouts=a(30))
        elif kind in (0x32, 0x33):  # '2' home / '3' guest players
            self._clocks(p)
            side = "Home" if kind == 0x32 else "Guest"
            for n in range(5):
                c[f"{side}Player{n + 1}"] = a(13 + 2 * n) + a(14 + 2 * n)
                c[f"{side}Player{n + 1}Points"] = a(45 + 2 * n) + a(46 + 2 * n)
                c[f"{side}Player{n + 1}FoulNumber"] = a(77 + n)


PROTOCOLS = {"Fujitsu_Basketball": lambda: FujitsuProtocol(FujitsuBasketball())}
