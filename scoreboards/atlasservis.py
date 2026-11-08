"""Atlas Servis CZ basketball.

Packets start ``B5 65`` and the layout depends on the packet length (159, 164, 198, 200, 228, 232).
Digits are 7-segment bytes in a board-specific bit order (bit 7 flags a decimal point / possession / lamp).
See docs/vendors/atlasservis.md for the odd framing ScoreConnect uses.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find, find_pair

__all__ = ["PROTOCOLS"]

_HDR = b"\xb5e"
_CR = 0x0D

_ATLAS_DIGITS = {119: "0", 17: "1", 62: "2", 59: "3", 89: "4", 107: "5", 111: "6", 49: "7", 127: "8",
                 123: "9", 0: " "}
_STD_DIGITS = {63: "0", 6: "1", 91: "2", 79: "3", 102: "4", 109: "5", 125: "6", 7: "7", 127: "8",
               111: "9", 0: " "}


def _atlas_digit(b: int) -> str:
    return _ATLAS_DIGITS.get(b & 0x7F, " ")


def _std_digit(b: int) -> str:
    return _STD_DIGITS.get(b & 0x7F, " ")


class AtlasServisProtocol(Protocol):
    """First packet of a chunk ends where ``B5 FF`` is found (the B5 stays in the packet); every packet after
    that in the same buffer ends at the next CR. Packets must start ``B5 65`` and have a known length."""

    def extract(self):
        buf = self.buf
        end = find_pair(buf, 0xB5, 0xFF)  # index of the FF; the packet is everything before it
        if end < 0:
            return
        while end >= 0:
            pkt = bytes(buf[:end])
            del buf[: end + 1]
            if pkt[:2] == _HDR and len(pkt) in _SIZES:
                yield pkt
            else:
                self.reject()
            end = find(buf, _CR)


# --------------------------------------------------------------------------- basketball layouts
def _timeout_lamps(b1: int, b2: int, b3: int, current: str) -> str:
    """Timeouts left shown as lit lamps (bit 7 of three bytes). A count that is exactly one below the
    displayed value keeps the displayed value (filters lamp flicker); anything else replaces it."""
    n = 3 if b3 & 0x80 else 2 if b2 & 0x80 else 1 if b1 & 0x80 else 0
    if current in tuple("0123456789") and n == int(current) - 1:
        return current
    return str(n)


class _Layout:
    """Byte indices of the fields in one packet size. Clock, shot clock and possession rules are shared:
    the clock starts at ``clock`` (bit 7 of the 2nd byte = decimal point = mm:ss), the shot clock at ``shot``."""

    def __init__(self, *, foul_h, foul_g, clock, shot, home, period, guest, shot_tenths_blank=False,
                 timeout_clock=None, timeouts=None):
        self.foul_h, self.foul_g, self.clock, self.shot = foul_h, foul_g, clock, shot
        self.home, self.period, self.guest = home, period, guest
        self.shot_tenths_blank = shot_tenths_blank
        self.timeout_clock, self.timeouts = timeout_clock, timeouts


_L232 = _Layout(foul_h=15, foul_g=4, clock=8, shot=185, home=5, period=14, guest=16, shot_tenths_blank=True)
_L228 = _Layout(foul_h=11, foul_g=6, clock=7, shot=213, home=12, period=15, guest=16)
_L164 = _Layout(foul_h=11, foul_g=13, clock=7, shot=149, home=4, period=12, guest=14, timeout_clock=2,
                timeouts=(4, 14))
_L198 = _Layout(foul_h=11, foul_g=6, clock=7, shot=151, home=12, period=15, guest=16, timeout_clock=4,
                timeouts=(12, 16))
_BY_SIZE = {232: _L232, 228: _L228, 164: _L164, 198: _L198, 200: _L198}
_SIZES = frozenset(_BY_SIZE) | {159}


class BasketballDecoder(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) == 159:
            self._decode159(p)
            return
        lay = _BY_SIZE.get(len(p))
        if lay is None:
            return
        c, d = self.c, _atlas_digit
        k = lay.clock
        c["HomeFoulOnes"] = d(p[lay.foul_h])
        c["GuestFoulOnes"] = d(p[lay.foul_g])
        if p[k + 1] & 0x80:  # decimal point lit on the 2nd byte -> mm:ss
            c.update(ClockMinutesTens=d(p[k]) if d(p[k]) != " " else "0", ClockMinutesOnes=d(p[k + 1]),
                     ClockSecondTens=d(p[k + 2]), ClockSecondOnes=d(p[k + 3]), ClockTenthsSecond="0")
        else:
            c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=d(p[k]),
                     ClockSecondOnes=d(p[k + 1]), ClockTenthsSecond=d(p[k + 2]))
        if lay.timeout_clock is not None:
            t = lay.timeout_clock
            c["TimeoutClockSecondTens"] = d(p[t])
            c["TimeoutClockSecondOnes"] = d(p[t + 1])
        if lay.timeouts:
            (h0, g0) = lay.timeouts
            c["HomeTimeouts"] = _timeout_lamps(p[h0], p[h0 + 1], p[h0 + 2], c.get("HomeTimeouts", " "))
            # ScoreConnect's 198/200 layout feeds the *home* value into the guest filter; 164 uses guest's own
            guest_cur = c.get("HomeTimeouts" if len(p) in (198, 200) else "GuestTimeouts", " ")
            c["GuestTimeouts"] = _timeout_lamps(p[g0], p[g0 + 1], p[g0 + 2], guest_cur)
        h = lay.home
        c.update(HomeScoreHundreds=d(p[h]), HomeScoreTens=d(p[h + 1]), HomeScoreOnes=d(p[h + 2]),
                 Period=d(p[lay.period]))
        g = lay.guest
        c.update(GuestScoreHundreds=d(p[g]), GuestScoreTens=d(p[g + 1]), GuestScoreOnes=d(p[g + 2]))
        s = lay.shot
        if p[s + 1] & 0x80:  # shot clock under 10 s: s.t
            c.update(ShotClockSecondTens="0", ShotClockSecondOnes=d(p[s]), ShotClockTenthsSecond=d(p[s + 1]))
        else:
            c.update(ShotClockSecondTens=d(p[s]) if d(p[s]) != " " else "0", ShotClockSecondOnes=d(p[s + 1]),
                     ShotClockTenthsSecond=" " if lay.shot_tenths_blank else "0")
        if p[lay.clock] & 0x80:  # possession flag = bit 7 of the clock's first byte
            c.update(HomePossession="<", GuestPossession=" ")
        else:
            c.update(HomePossession=" ", GuestPossession=">")

    def _decode159(self, p: bytes) -> None:
        c, d = self.c, _std_digit
        c["HomeFoulOnes"] = d(p[5])
        c["GuestFoulOnes"] = d(p[13])
        if p[10] & 0x80:
            c.update(ClockMinutesTens=d(p[9]) if d(p[9]) != " " else "0", ClockMinutesOnes=d(p[10]),
                     ClockSecondTens=d(p[11]), ClockSecondOnes=d(p[12]), ClockTenthsSecond="0")
        else:
            c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=d(p[9]),
                     ClockSecondOnes=d(p[10]), ClockTenthsSecond=d(p[11]))
        c["ShotClockSecondTens"] = d(p[144]) if d(p[144]) != " " else "0"
        c["ShotClockSecondOnes"] = d(p[145])
        c.update(HomeScoreTens=d(p[3]), HomeScoreOnes=d(p[4]), Period=d(p[5]), GuestScoreTens=d(p[6]),
                 GuestScoreOnes=d(p[7]))


PROTOCOLS = {"AtlasServisCZ_Basketball": lambda: AtlasServisProtocol(BasketballDecoder())}
