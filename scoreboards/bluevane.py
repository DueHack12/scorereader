"""Blue Vane basketball scoreboards, normal and swapped-teams layouts (RS-232, 4800 baud).

Wire format: ``STX(02) <16 data bytes> ETX(03)``, ASCII data, no checksum and no length byte. Byte 15 of the
data is a flag byte. See docs/vendors/bluevane.md for how the swapped layout and ScoreConnect's own
team-swap setting relate.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char, blank_to_zero

STX, ETX = 0x02, 0x03
MIN_LEN = 16


class BlueVaneProtocol(Protocol):
    """Everything between the first STX and the first ETX is the packet."""

    def extract(self):
        buf = self.buf
        while True:
            etx = find(buf, ETX)
            if etx < 0:
                return
            stx = find(buf, STX)
            body = bytes(buf[stx + 1 : etx]) if 0 <= stx < etx else b""
            del buf[: etx + 1]
            if not body:
                continue
            if len(body) >= MIN_LEN:
                yield body
            else:
                self.reject()


class _BlueVaneBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"
    swapped = False  # True: the board's "home" fields carry the visitors and vice versa

    def decode(self, p: bytes) -> None:
        c = self.c
        a = lambda i: ascii_char(p[i])  # noqa: E731
        flags = p[15]
        if flags & 4 and a(2) == " ":  # under a minute: seconds.tenths
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0",
                     ClockSecondTens=blank_to_zero(a(0)), ClockSecondOnes=blank_to_zero(a(1)),
                     ClockTenthsSecond=blank_to_zero(a(3)))
        else:
            c.update(ClockMode=":", ClockMinutesTens=blank_to_zero(a(0)), ClockMinutesOnes=blank_to_zero(a(1)),
                     ClockSecondTens=blank_to_zero(a(2)), ClockSecondOnes=blank_to_zero(a(3)),
                     ClockTenthsSecond="0")
        if flags & 0x40:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=a(10), ShotClockTenthsSecond=a(11))
        else:
            c.update(ShotClockSecondTens=a(10), ShotClockSecondOnes=a(11),
                     ShotClockTenthsSecond="0" if self.swapped else " ")
        first, second = ("Guest", "Home") if self.swapped else ("Home", "Guest")
        # bytes 4..9 and 12..13 belong to `first` (the left-hand team on the wire) then `second`
        c[f"{first}FoulOnes"] = a(4)
        c[f"{second}FoulOnes"] = a(5)
        for side, tens, ones, hundred_flag in ((first, 6, 7, 0x20), (second, 8, 9, 0x10)):
            c[f"{side}ScoreTens"], c[f"{side}ScoreOnes"] = a(tens), a(ones)
            c[f"{side}ScoreHundreds"] = "1" if flags & hundred_flag and a(tens) != "9" and a(ones) != "9" else " "
        c[f"{first}Timeouts"] = a(12)
        c[f"{second}Timeouts"] = a(13)
        c["Period"] = a(14)
        c["Horn"] = "H" if flags & 2 else " "


class BlueVaneBasketball(_BlueVaneBasketball):
    pass


class BlueVaneBasketballSwapped(_BlueVaneBasketball):
    """Same packet, already mapped to the real home/guest: the board sends visitors first."""

    swapped = True


PROTOCOLS = {
    "BlueVane_Basketball": lambda: BlueVaneProtocol(BlueVaneBasketball()),
    "BlueVane_Basketball_SwappedTeamsInfo": lambda: BlueVaneProtocol(BlueVaneBasketballSwapped()),
}
