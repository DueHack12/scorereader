"""Spectrum scoreboards: V2 (text line), V2W, V2E and MS250 (baseball).

All are raw serial (``NODECODE``, 9600 baud) and have no checksum:

* V2 basketball: ASCII line ``>MM:SS.t,home,guest,period<`` ended by LF.
* V2W: 35, 41 or 44 bytes of 7-bit ASCII ended by LF.
* V2E: 35 or 43 bytes of 7-bit ASCII + LF, then a NUL (so the frame is "...LF NUL"; the LF counts toward
  the 36 / 44 length ScoreConnect checks).
* MS250 baseball: 13 bytes starting with 00 0F.

See docs/vendors/spectrum.md for the byte tables.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find, find_pair
from .common import ascii_char, bcd

__all__ = ["PROTOCOLS"]


# --------------------------------------------------------------------------- framing
class _LineProtocol(Protocol):
    """Packets are the bytes before each LF; ``accept`` decides whether the packet is valid."""

    def accept(self, pkt: bytes) -> bool:
        return True

    def extract(self):
        buf = self.buf
        while True:
            j = find(buf, 0x0A)
            if j < 0:
                return
            pkt = bytes(buf[:j])
            del buf[: j + 1]
            if self.accept(pkt):
                yield pkt
            else:
                self.reject()


class SpectrumV2Protocol(_LineProtocol):
    def accept(self, pkt):
        return len(pkt) > 0 and pkt[0] == 0x3E  # ">"


class SpectrumV2WProtocol(_LineProtocol):
    def accept(self, pkt):
        return len(pkt) in (35, 41, 44)


class SpectrumV2EProtocol(Protocol):
    """Frames end with LF NUL; the packet keeps its LF (length 36 or 44)."""

    def extract(self):
        buf = self.buf
        while True:
            j = find_pair(buf, 0x0A, 0x00)
            if j < 0:
                return
            pkt = bytes(buf[:j])
            del buf[: j + 1]
            if len(pkt) in (36, 44):
                yield pkt
            else:
                self.reject()


class SpectrumMS250Protocol(Protocol):
    size = 13

    def extract(self):
        buf = self.buf
        while True:
            j = find_pair(buf, 0x00, 0x0F)
            if j < 0:
                if len(buf) > 1:
                    del buf[:-1]  # keep a trailing 00 that may start the next frame
                return
            s = j - 1
            if len(buf) < s + self.size:
                if s:
                    del buf[:s]
                return
            pkt = bytes(buf[s : s + self.size])
            del buf[: s + self.size]
            yield pkt


# --------------------------------------------------------------------------- character helpers
def _sa(b: int) -> str:
    """7-bit ASCII; ":" reads as blank."""
    ch = ascii_char(b & 0x7F)
    return " " if ch == ":" else ch


def _sa2(b: int) -> str:
    """Like _sa, and "F" reads as blank too (V2E and V2 baseball)."""
    ch = _sa(b)
    return " " if ch == "F" else ch


def _flag(value: int, mask: int, on: str) -> str:
    return on if value & mask else " "


def _put(c: dict, p: bytes, table, conv) -> None:
    for idx, name in table:
        c[name] = conv(p[idx])


# --------------------------------------------------------------------------- V2W / V2E shared layouts
_FOOTBALL = (
    (5, "HomeScoreTens"), (6, "HomeScoreOnes"), (7, "GuestScoreTens"), (8, "GuestScoreOnes"),
    (15, "BallOnTens"), (16, "BallOnOnes"), (9, "ToGoTens"), (10, "ToGoOnes"), (21, "Down"),
    (22, "HomeTimeouts"), (23, "Quarter"), (24, "GuestTimeouts"), (25, "PlayClockTens"), (26, "PlayClockOnes"),
)
_SOCCER = (
    (5, "HomeScoreTens"), (6, "HomeScoreOnes"), (9, "HomeShotTens"), (10, "HomeShotOnes"),
    (7, "GuestScoreTens"), (8, "GuestScoreOnes"), (15, "GuestShotTens"), (16, "GuestShotOnes"), (12, "Period"),
)


def _clock4(c: dict, p: bytes, conv) -> None:
    c["ClockMode"] = ":"
    c["ClockMinutesTens"], c["ClockMinutesOnes"] = conv(p[1]), conv(p[2])
    c["ClockSecondTens"], c["ClockSecondOnes"] = conv(p[3]), conv(p[4])
    c["ClockTenthsSecond"] = "0"


def _soccer(c: dict, p: bytes, conv) -> None:
    _clock4(c, p, conv)
    _put(c, p, _SOCCER, conv)
    c["HomePenalties"] = conv(p[22]) + conv(p[21])  # ones digit is sent first
    c["GuestPenalties"] = conv(p[24]) + conv(p[23])


class _Spectrum32(Decoder):
    """Decoders that read up to byte 31 of the packet."""

    def decode(self, p: bytes) -> None:
        if len(p) >= 32:
            self.body(p)

    def body(self, p: bytes) -> None:
        raise NotImplementedError


class V2WFootball(_Spectrum32):
    contract = "Football"
    event = "Football"

    def body(self, p):
        c = self.c
        # ScoreConnect tests (p[12] & 8) == 1, which can never be true: the clock is always mm:ss.
        _clock4(c, p, _sa)
        c["HomePossession"] = _flag(p[12], 1, "<")
        c["GuestPossession"] = _flag(p[12], 2, ">")
        _put(c, p, _FOOTBALL, _sa)


class V2EFootball(_Spectrum32):
    contract = "Football"
    event = "Football"

    def body(self, p):
        c = self.c
        _clock4(c, p, _sa2)
        c["HomePossession"] = "<" if p[12] == 53 else " "   # "5"
        c["GuestPossession"] = ">" if p[12] == 65 else " "  # "A"
        _put(c, p, _FOOTBALL, _sa2)


class V2WSoccer(_Spectrum32):
    contract = "Soccer"
    event = "Soccer"

    def body(self, p):
        _soccer(self.c, p, _sa)


class V2ESoccer(_Spectrum32):
    contract = "Soccer"
    event = "Soccer"

    def body(self, p):
        _soccer(self.c, p, _sa2)


class V2WVolleyball(_Spectrum32):
    contract = "Volleyball"
    event = "Volleyball"

    def body(self, p):
        _put(self.c, p, ((5, "HomeScoreTens"), (6, "HomeScoreOnes"), (7, "GuestScoreTens"), (8, "GuestScoreOnes"),
                         (22, "HomeGamesWon"), (24, "GuestGamesWon"), (23, "Set")), _sa)


_BASKETBALL = (
    (5, "HomeScoreTens"), (6, "HomeScoreOnes"), (7, "GuestScoreTens"), (8, "GuestScoreOnes"),
    (25, "ShotClockSecondTens"), (26, "ShotClockSecondOnes"),
    (21, "HomeFoulTens"), (22, "HomeFoulOnes"), (16, "GuestFoulTens"), (24, "GuestFoulOnes"),
    (30, "HomeTimeouts"), (31, "GuestTimeouts"), (23, "Period"),
)


def _basketball(c: dict, p: bytes, conv, clock_flags: int, poss_flags: int, score_flags: int, dbl_flags: int) -> None:
    """Shared V2W/V2E basketball layout. The four flag bytes are the status bytes (differing by model)."""
    if clock_flags & 8:
        _clock4(c, p, conv)
    else:  # under a minute: SS.t
        c["ClockMode"] = "."
        c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
        c["ClockSecondTens"], c["ClockSecondOnes"] = conv(p[1]), conv(p[2])
        c["ClockTenthsSecond"] = conv(p[3])
    c["HomePossession"] = _flag(poss_flags, 1, "<")
    c["GuestPossession"] = _flag(poss_flags, 2, ">")
    _put(c, p, _BASKETBALL, conv)
    c["HomeScoreHundreds"] = _flag(score_flags, 1, "1")
    c["GuestScoreHundreds"] = _flag(score_flags, 2, "1")
    c["HomeFullTimeouts"] = c["HomePartialTimeouts"] = c["GuestFullTimeouts"] = c["GuestPartialTimeouts"] = " "
    c["HomeBonus"] = _flag(score_flags, 4, "B")
    c["GuestBonus"] = _flag(score_flags, 8, "B")
    c["HomeDoubleBonus"] = _flag(dbl_flags, 8, "B")
    c["GuestDoubleBonus"] = _flag(dbl_flags, 4, "B")


class V2WBasketball(_Spectrum32):
    contract = "Basketball"
    event = "Basketball"

    def body(self, p):
        # status bytes: 12 = clock/possession, 14 = hundreds/bonus, 11 = double bonus
        _basketball(self.c, p, _sa, p[12], p[12], p[14], p[11])


class V2EBasketball(_Spectrum32):
    contract = "Basketball"
    event = "Basketball"

    @staticmethod
    def _status(b: int) -> int:
        return b - 7 if b >= 64 else b  # letters "A".. stand for 10.. in the flag bytes

    def body(self, p):
        s = self._status
        _basketball(self.c, p, _sa2, s(p[12]), s(p[12]), s(p[14]), s(p[11]))


class V2EHockeyMSX(_Spectrum32):
    contract = "HockeyLacrosse"
    event = "Hockey"

    # (contract prefix, player tens byte, minutes-ones byte, seconds-tens byte); player ones follows the tens
    # byte and seconds ones follows the seconds tens byte. Only sent in 44-byte frames.
    _PENALTIES = (("HomePenaltyPlayer1", 20, 22, 24), ("HomePenaltyPlayer2", 31, 33, 34),
                  ("GuestPenaltyPlayer1", 26, 28, 29), ("GuestPenaltyPlayer2", 36, 38, 39))

    def body(self, p):
        c = self.c
        status = p[12] - 7 if p[12] >= 64 else p[12]
        if status & 8:
            _clock4(c, p, _sa2)
        else:
            c["ClockMode"] = "."
            c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"] = _sa2(p[1]), _sa2(p[2]), _sa2(p[3])
        c["HomePossession"] = "<" if p[12] == 53 else " "
        c["GuestPossession"] = ">" if p[12] == 65 else " "
        _put(c, p, ((5, "HomeScoreTens"), (6, "HomeScoreOnes"), (7, "GuestScoreTens"), (8, "GuestScoreOnes"),
                    (23, "Period")), _sa2)
        if len(p) >= 41:
            for pre, pl, mins, sec in self._PENALTIES:
                c[pre + "Tens"], c[pre + "Ones"] = _sa2(p[pl]), _sa2(p[pl + 1])
                c[pre + "ClockMinutesTens"] = " "
                c[pre + "ClockMinutesOnes"] = _sa2(p[mins])
                c[pre + "ClockSecondTens"], c[pre + "ClockSecondOnes"] = _sa2(p[sec]), _sa2(p[sec + 1])


# --------------------------------------------------------------------------- V2 text-line basketball
class V2Basketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        # drop the leading ">" and the last character, then split on commas
        parts = p[1:-1].decode("latin-1").split(",")
        if len(parts) < 4 or len(parts[0]) < 5:
            return
        clk, c = parts[0], self.c
        if clk[0] == "0" and clk[1] == "0":
            if len(clk) < 7:
                return
            c["ClockMode"] = "."
            c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"] = clk[3], clk[4], clk[6]
        else:
            c["ClockMode"] = ":"
            c["ClockMinutesTens"], c["ClockMinutesOnes"] = clk[0], clk[1]
            c["ClockSecondTens"], c["ClockSecondOnes"] = clk[3], clk[4]
            c["ClockTenthsSecond"] = "0"
        for side, text in (("Home", parts[1]), ("Guest", parts[2])):
            if 1 <= len(text) <= 3:
                t = text.rjust(3)
                c[f"{side}ScoreHundreds"], c[f"{side}ScoreTens"], c[f"{side}ScoreOnes"] = t[0], t[1], t[2]
        c["Period"] = parts[3][0] if parts[3] else " "


# --------------------------------------------------------------------------- baseball
_BALL_INNING = [(21 + 2 * i, f"GuestInning{i + 1}") for i in range(10)] + \
               [(22 + 2 * i, f"HomeInning{i + 1}") for i in range(10)]
_BASEBALL = (
    (1, "Balls"), (2, "Strikes"), (3, "Outs"), (5, "HomeRunTens"), (6, "HomeRunOnes"),
    (7, "GuestRunTens"), (8, "GuestRunOnes"), (9, "AtBatTens"), (10, "AtBatOnes"),
    (15, "HomeHitsTens"), (16, "HomeHitsOnes"), (17, "GuestHitsTens"), (18, "GuestHitsOnes"),
    (19, "HomeErrors"), (20, "GuestErrors"),
) + tuple(_BALL_INNING)


def _inning_and_half(c: dict) -> tuple:
    """Current inning and half derived from the line score: the last non-blank column wins."""
    inning = 10
    for n in range(10, 0, -1):
        if c.get(f"HomeInning{n}", " ") != " ":
            return f"{inning:02d}", "B"
        if c.get(f"GuestInning{n}", " ") != " ":
            return f"{inning:02d}", "T"
        inning = max(inning - 1, 1)
    return f"{inning:02d}", "T"


class SpectrumBaseball(Decoder):
    """Shared by V2W and V2E baseball (ASCII, packet up to byte 40). Short packets fill what they reach."""

    contract = "BaseballSoftball"
    event = "Baseball"

    def decode(self, p: bytes) -> None:
        c = self.c
        for idx, name in _BASEBALL:
            if idx < len(p):
                c[name] = _sa2(p[idx])
        inning, half = _inning_and_half(c)
        if half == "T":
            c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "T", ".", " "
        else:
            c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "B", " ", "."
        c["InningTens"], c["InningOnes"] = inning[0], inning[1]


class MS250Baseball(Decoder):
    contract = "BaseballSoftball"
    event = "Baseball"

    def decode(self, p: bytes) -> None:
        if len(p) < 13:
            return
        c = self.c
        c["InningOnes"] = bcd(p[2], 0)
        c["HomeRunTens"], c["HomeRunOnes"] = bcd(p[3], 0), bcd(p[4], 0)
        c["GuestRunTens"], c["GuestRunOnes"] = bcd(p[5], 0), bcd(p[6], 0)
        # lamp patterns: unlisted patterns leave the previous value alone
        balls = {0: "0", 1: "1", 3: "2", 7: "3"}.get(p[10] & 7)
        if balls:
            c["Balls"] = balls
        strikes = {0: "0", 1: "1", 3: "2"}.get(p[11] & 3)
        if strikes:
            c["Strikes"] = strikes
        c["TopBottomInning"] = "T" if p[11] & 4 == 0 else "B"
        outs = {0: "0", 1: "1", 3: "2"}.get(p[12] & 3)
        if outs:
            c["Outs"] = outs


PROTOCOLS = {
    "SpectrumV2_Basketball": lambda: SpectrumV2Protocol(V2Basketball()),
    "SpectrumV2W_Basketball": lambda: SpectrumV2WProtocol(V2WBasketball()),
    "SpectrumV2W_Football": lambda: SpectrumV2WProtocol(V2WFootball()),
    "SpectrumV2W_Soccer": lambda: SpectrumV2WProtocol(V2WSoccer()),
    "SpectrumV2W_Volleyball": lambda: SpectrumV2WProtocol(V2WVolleyball()),
    "SpectrumV2W_Baseball": lambda: SpectrumV2WProtocol(SpectrumBaseball()),
    "SpectrumV2E_Football": lambda: SpectrumV2EProtocol(V2EFootball()),
    "SpectrumV2E_Soccer": lambda: SpectrumV2EProtocol(V2ESoccer()),
    "SpectrumV2E_Basketball": lambda: SpectrumV2EProtocol(V2EBasketball()),
    "SpectrumV2E_Baseball": lambda: SpectrumV2EProtocol(SpectrumBaseball()),
    "SpectrumMSX_Hockey": lambda: SpectrumV2EProtocol(V2EHockeyMSX()),
    "SpectrumMS250_Baseball": lambda: SpectrumMS250Protocol(MS250Baseball()),
}
