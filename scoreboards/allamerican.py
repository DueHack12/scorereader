"""All American Scoreboards: Model 8000 ("Main"), Model 3000 and Model 9000.

Wire formats (all raw serial, ``NODECODE`` PIC mode, frames start with 0xFC):

* Model 8000: 32-byte frames, 16-bit little-endian sum of bytes 3..29 in bytes 30-31 (a computed byte of 0xFC
  is sent as 0x69). Byte 9 says which sub-packet this is (0x11 = main data, 0x22 = second page) and each
  sub-packet only updates its own fields. Values are BCD nibbles.
* Model 3000: 20-byte frames, no checksum, one BCD digit per byte (low nibble).
* Model 9000: 34-byte frames, CRC-16/CCITT (init FFFF) of bytes 0..31 big-endian in bytes 32-33, values are
  decimal bytes.

See docs/vendors/allamerican.md for the byte tables.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import bcd, crc16_ccitt, dec

__all__ = ["PROTOCOLS"]

SYNC = 0xFC


# --------------------------------------------------------------------------- framing
class _FcProtocol(Protocol):
    """Frames of ``size`` bytes starting at the first 0xFC. Subclasses validate with :meth:`valid`."""

    size = 0

    def valid(self, frame: bytes) -> bool:
        return True

    def extract(self):
        buf = self.buf
        while True:
            i = find(buf, SYNC)
            if i < 0:
                buf.clear()
                return
            if len(buf) - i < self.size:
                if i:
                    del buf[:i]
                return
            frame = bytes(buf[i : i + self.size])
            del buf[: i + self.size]
            if self.valid(frame):
                yield frame
            else:
                self.reject()


class Model8000Protocol(_FcProtocol):
    size = 32

    def valid(self, frame: bytes) -> bool:
        total = sum(frame[3:30])
        lo, hi = total & 0xFF, (total >> 8) & 0xFF
        lo = 0x69 if lo == SYNC else lo
        hi = 0x69 if hi == SYNC else hi
        return frame[30] == lo and frame[31] == hi


class Model3000Protocol(_FcProtocol):
    size = 20


class Model9000Protocol(_FcProtocol):
    size = 34

    def valid(self, frame: bytes) -> bool:
        crc = crc16_ccitt(frame, 0, 32)
        return frame[32] == crc >> 8 and frame[33] == crc & 0xFF


# --------------------------------------------------------------------------- shared decode helpers
def _int(ch: str) -> int:
    return int(ch) if ch.isdigit() else 0  # a blank nibble counts as 0


def _bcd_pair(c: dict, p: bytes, idx: int, tens: str, ones: str) -> None:
    c[tens] = bcd(p[idx], 1)
    c[ones] = bcd(p[idx], 0)


def _bcd_text(p: bytes, idx: int) -> str:
    return bcd(p[idx], 1) + bcd(p[idx], 0)


def _dec_pair(c: dict, p: bytes, idx: int, tens: str, ones: str) -> None:
    c[tens] = dec(p[idx], 1, 2, True)
    c[ones] = dec(p[idx], 0, 2, True)


def _clock(c: dict, minutes, seconds, tenths) -> None:
    """Under a minute the board puts the tenths in a separate byte; the clock then reads 00.SS.t."""
    if _int(minutes(1)) == 0 and _int(minutes(0)) == 0:
        c["ClockMode"] = "."
        c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
        c["ClockSecondTens"], c["ClockSecondOnes"] = seconds(1), seconds(0)
        c["ClockTenthsSecond"] = tenths()
    else:
        c["ClockMode"] = ":"
        c["ClockMinutesTens"], c["ClockMinutesOnes"] = minutes(1), minutes(0)
        c["ClockSecondTens"], c["ClockSecondOnes"] = seconds(1), seconds(0)
        c["ClockTenthsSecond"] = "0"


def _clock_bcd(c: dict, p: bytes) -> None:
    _clock(c, lambda i: bcd(p[4], i), lambda i: bcd(p[5], i), lambda: bcd(p[6], 0))


def _clock_dec(c: dict, p: bytes) -> None:
    _clock(c, lambda i: dec(p[4], i), lambda i: dec(p[5], i), lambda: dec(p[6], 0))


# --------------------------------------------------------------------------- Model 8000
class _Main8000(Decoder):
    """Common part: clock in every packet, the rest depends on the sub-packet type in byte 9."""

    def decode(self, p: bytes) -> None:
        if len(p) < 32:
            return
        _clock_bcd(self.c, p)
        self.head(p)
        if p[9] == 0x11:
            self.page1(p)
        elif p[9] == 0x22:
            self.page2(p)

    def head(self, p: bytes) -> None:  # fields taken from the common header (byte 7)
        pass

    def page1(self, p: bytes) -> None:
        pass

    def page2(self, p: bytes) -> None:
        pass


def _possession(c: dict, p: bytes) -> None:
    """Possession lamps in bit 0 of bytes 11 (home) and 13 (guest); nothing set means "unchanged"."""
    if p[11] & 1:
        c["HomePossession"], c["GuestPossession"] = "<", " "
    if p[13] & 1:
        c["HomePossession"], c["GuestPossession"] = " ", ">"


def _horn(c: dict, p: bytes) -> None:
    c["Horn"] = "H" if p[3] & 0x80 else " "


class Main8000Football(_Main8000):
    contract = "Football"
    event = "Football"

    def head(self, p):
        _bcd_pair(self.c, p, 7, "PlayClockTens", "PlayClockOnes")

    def page1(self, p):
        c = self.c
        _possession(c, p)
        c["Quarter"] = bcd(p[14], 0)
        _bcd_pair(c, p, 10, "HomeScoreTens", "HomeScoreOnes")
        _bcd_pair(c, p, 12, "GuestScoreTens", "GuestScoreOnes")
        c["HomeTimeouts"], c["GuestTimeouts"] = bcd(p[19], 1), bcd(p[19], 0)
        _bcd_pair(c, p, 17, "ToGoTens", "ToGoOnes")
        c["Down"] = bcd(p[18], 0)
        _bcd_pair(c, p, 20, "BallOnTens", "BallOnOnes")
        _horn(c, p)


class Main8000Basketball(_Main8000):
    contract = "Basketball"
    event = "Basketball"

    def head(self, p):
        _bcd_pair(self.c, p, 7, "ShotClockSecondTens", "ShotClockSecondOnes")

    def page1(self, p):
        c = self.c
        _possession(c, p)
        c["HomeBonus"] = "B" if p[11] & 8 else " "
        c["GuestBonus"] = "B" if p[13] & 8 else " "
        # ScoreConnect reads HomeDoubleBonus twice (byte 11 then byte 13); the byte 13 value wins and
        # GuestDoubleBonus is never written. Reproduced as is.
        c["HomeDoubleBonus"] = "B" if p[13] & 0x10 else " "
        c["Period"] = bcd(p[14], 0)
        c["HomeScoreHundreds"] = "1" if p[11] & 0x86 else "0"
        _bcd_pair(c, p, 10, "HomeScoreTens", "HomeScoreOnes")
        c["GuestScoreHundreds"] = "1" if p[13] & 0x86 else "0"
        _bcd_pair(c, p, 12, "GuestScoreTens", "GuestScoreOnes")
        _bcd_pair(c, p, 15, "HomeFoulTens", "HomeFoulOnes")
        _bcd_pair(c, p, 16, "GuestFoulTens", "GuestFoulOnes")
        _bcd_pair(c, p, 17, "FoulPlayerTens", "FoulPlayerOnes")
        c["FoulPlayerNumberOfFouls"] = bcd(p[18], 0)
        c["HomeTimeouts"], c["GuestTimeouts"] = bcd(p[19], 1), bcd(p[19], 0)
        _horn(c, p)


class Main8000Hockey(_Main8000):
    contract = "HockeyLacrosse"
    event = "Hockey"

    _PENALTY_SLOTS = (  # (contract prefix, player byte, minutes byte, seconds byte)
        ("HomePenaltyPlayer1", 12, 10, 11), ("HomePenaltyPlayer2", 15, 13, 14),
        ("GuestPenaltyPlayer1", 18, 16, 17), ("GuestPenaltyPlayer2", 21, 19, 20),
    )

    def head(self, p):
        _bcd_pair(self.c, p, 7, "ShotClockTens", "ShotClockOnes")

    def page1(self, p):
        c = self.c
        c["Period"] = bcd(p[14], 0)
        _horn(c, p)
        _bcd_pair(c, p, 10, "HomeScoreTens", "HomeScoreOnes")
        _bcd_pair(c, p, 12, "GuestScoreTens", "GuestScoreOnes")
        c["HomeTimeOut"], c["GuestTimeOut"] = bcd(p[19], 1), bcd(p[19], 0)
        c["HomeSaves"], c["GuestSaves"] = _bcd_text(p, 20), _bcd_text(p, 21)
        _bcd_pair(c, p, 15, "HomeShotOnGoalTens", "HomeShotOnGoalOnes")
        _bcd_pair(c, p, 16, "GuestShotOnGoalTens", "GuestShotOnGoalOnes")

    def page2(self, p):
        c = self.c
        for prefix, player, mins, secs in self._PENALTY_SLOTS:
            _bcd_pair(c, p, player, prefix + "Tens", prefix + "Ones")
            _bcd_pair(c, p, mins, prefix + "ClockMinutesTens", prefix + "ClockMinutesOnes")
            _bcd_pair(c, p, secs, prefix + "ClockSecondTens", prefix + "ClockSecondOnes")
        for side in ("Home", "Guest"):  # the console has no third penalty slot
            for part in ("Tens", "Ones", "ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens",
                         "ClockSecondOnes"):
                c[f"{side}PenaltyPlayer3{part}"] = " "


class Main8000Soccer(_Main8000):
    contract = "Soccer"
    event = "Soccer"

    def page1(self, p):
        c = self.c
        c["Period"] = bcd(p[14], 0)
        _bcd_pair(c, p, 10, "HomeScoreTens", "HomeScoreOnes")
        _bcd_pair(c, p, 12, "GuestScoreTens", "GuestScoreOnes")
        c["HomeTimeouts"], c["GuestTimeouts"] = bcd(p[19], 1), bcd(p[19], 0)
        c["HomeCornerKicks"], c["GuestCornerKicks"] = _bcd_text(p, 20), _bcd_text(p, 21)
        _bcd_pair(c, p, 15, "HomeShotTens", "HomeShotOnes")
        _bcd_pair(c, p, 16, "GuestShotTens", "GuestShotOnes")
        _horn(c, p)


class Main8000Volleyball(_Main8000):
    contract = "Volleyball"
    event = "Volleyball"

    def page1(self, p):
        c = self.c
        c["HomeGamesWon"], c["GuestGamesWon"] = bcd(p[15], 0), bcd(p[16], 0)
        _bcd_pair(c, p, 10, "HomeScoreTens", "HomeScoreOnes")
        _bcd_pair(c, p, 12, "GuestScoreTens", "GuestScoreOnes")
        c["HomeServe"] = "*" if p[11] & 1 else " "
        c["GuestServe"] = "*" if p[13] & 1 else " "
        c["Set"] = " "
        c["Game"] = bcd(p[14], 0)
        c["HomeTimeout"], c["GuestTimeout"] = bcd(p[19], 1), bcd(p[19], 0)
        for n, idx in enumerate((20, 22, 24, 26), start=1):  # home byte, guest byte right after it
            c[f"HomeScoreSet{n}"] = _bcd_text(p, idx)
            c[f"GuestScoreSet{n}"] = _bcd_text(p, idx + 1)


class Main8000Baseball(_Main8000):
    contract = "BaseballSoftball"
    event = "Baseball"

    def head(self, p):
        pass

    def decode(self, p):
        # Baseball boards send no clock, so only the sub-packets matter.
        if len(p) < 32:
            return
        if p[9] == 0x11:
            self.page1(p)
        elif p[9] == 0x22:
            self.page2(p)

    def page1(self, p):
        c = self.c
        c["Balls"] = bcd(p[18], 0)
        c["Strikes"], c["Outs"] = bcd(p[17], 1), bcd(p[17], 0)
        _bcd_pair(c, p, 14, "InningTens", "InningOnes")
        c["GuestErrorNumber"] = bcd(p[27], 0)
        _bcd_pair(c, p, 12, "GuestRunTens", "GuestRunOnes")
        _bcd_pair(c, p, 10, "HomeRunTens", "HomeRunOnes")
        _bcd_pair(c, p, 22, "GuestHitsTens", "GuestHitsOnes")
        _bcd_pair(c, p, 21, "HomeHitsTens", "HomeHitsOnes")
        c["GuestErrors"], c["HomeErrors"] = bcd(p[16], 0), bcd(p[16], 1)
        if p[13] & 1:
            c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "T", ".", " "
        else:
            c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "B", " ", "."
        _bcd_pair(c, p, 20, "AtBatTens", "AtBatOnes")

    def page2(self, p):
        c = self.c
        for n in range(1, 11):  # guest innings in bytes 10-19, home innings in bytes 20-29
            c[f"GuestInning{n}"] = bcd(p[9 + n], 0)
            c[f"HomeInning{n}"] = bcd(p[19 + n], 0)


# --------------------------------------------------------------------------- Model 3000
class Model3000Football(Decoder):
    contract = "Football"
    event = "Football"

    def decode(self, p: bytes) -> None:
        if len(p) < 20:
            return
        c = self.c
        c["ClockMode"] = ":"
        c["ClockMinutesTens"], c["ClockMinutesOnes"] = bcd(p[18], 0), bcd(p[17], 0)
        c["ClockSecondTens"], c["ClockSecondOnes"] = bcd(p[16], 0), bcd(p[15], 0)
        c["ClockTenthsSecond"] = "0"
        if p[1] & 1:
            c["HomePossession"], c["GuestPossession"] = "<", " "
        if p[1] & 2:
            c["HomePossession"], c["GuestPossession"] = " ", ">"
        c["Quarter"] = bcd(p[13], 0)
        c["HomeScoreTens"], c["HomeScoreOnes"] = bcd(p[3], 0), bcd(p[2], 0)
        c["GuestScoreTens"], c["GuestScoreOnes"] = bcd(p[6], 0), bcd(p[5], 0)
        c["ToGoTens"], c["ToGoOnes"] = bcd(p[9], 0), bcd(p[8], 0)
        c["Down"] = bcd(p[12], 0)
        c["BallOnTens"], c["BallOnOnes"] = bcd(p[11], 0), bcd(p[10], 0)


# --------------------------------------------------------------------------- Model 9000
def _possession_bits(c: dict, p: bytes) -> None:
    if p[14] & 0x10:
        c["HomePossession"], c["GuestPossession"] = "<", " "
    if p[14] & 0x20:
        c["GuestPossession"], c["HomePossession"] = ">", " "


class _Dec9000(Decoder):
    def decode(self, p: bytes) -> None:
        if len(p) < 34:
            return
        _clock_dec(self.c, p)
        self.body(p)

    def body(self, p: bytes) -> None:
        raise NotImplementedError


class Model9000Football(_Dec9000):
    contract = "Football"
    event = "Football"

    def body(self, p):
        c = self.c
        _possession_bits(c, p)
        c["PlayClockTens"], c["PlayClockOnes"] = dec(p[12], 1), dec(p[12], 0)
        c["Quarter"] = dec(p[17], 0)
        _dec_pair(c, p, 15, "HomeScoreTens", "HomeScoreOnes")
        _dec_pair(c, p, 16, "GuestScoreTens", "GuestScoreOnes")
        _dec_pair(c, p, 20, "ToGoTens", "ToGoOnes")
        c["Down"] = dec(p[18], 0)
        _dec_pair(c, p, 19, "BallOnTens", "BallOnOnes")
        c["HomeTimeouts"], c["GuestTimeouts"] = dec(p[21], 0), dec(p[22], 0)


class Model9000Basketball(_Dec9000):
    contract = "Basketball"
    event = "Basketball"

    def body(self, p):
        c = self.c
        c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = dec(p[9], 1), dec(p[9], 0)
        _possession_bits(c, p)
        c["HomeBonus"] = "B" if p[22] & 1 else " "
        c["GuestBonus"] = "B" if p[22] & 2 else " "
        c["HomeDoubleBonus"] = "B" if p[22] & 4 else " "
        c["GuestDoubleBonus"] = "B" if p[22] & 8 else " "
        c["Period"] = dec(p[17], 0)
        for side, idx in (("Home", 15), ("Guest", 16)):
            c[f"{side}ScoreHundreds"] = dec(p[idx], 2, 3, True)
            c[f"{side}ScoreTens"] = dec(p[idx], 1, 3, True)
            c[f"{side}ScoreOnes"] = dec(p[idx], 0, 3, True)
        _dec_pair(c, p, 18, "HomeFoulTens", "HomeFoulOnes")
        _dec_pair(c, p, 19, "GuestFoulTens", "GuestFoulOnes")
        _bcd_pair(c, p, 20, "FoulPlayerTens", "FoulPlayerOnes")
        c["FoulPlayerNumberOfFouls"] = dec(p[21], 0)
        c["HomeTimeouts"], c["GuestTimeouts"] = dec(p[23], 0), dec(p[24], 0)
        c["Horn"] = "H" if p[14] & 1 else " "


class Model9000Hockey(_Dec9000):
    contract = "HockeyLacrosse"
    event = "Hockey"

    def body(self, p):
        c = self.c
        c["Period"] = dec(p[17], 0)
        _dec_pair(c, p, 15, "HomeScoreTens", "HomeScoreOnes")
        _dec_pair(c, p, 16, "GuestScoreTens", "GuestScoreOnes")
        _dec_pair(c, p, 18, "HomeShotOnGoalTens", "HomeShotOnGoalOnes")
        _dec_pair(c, p, 19, "GuestShotOnGoalTens", "GuestShotOnGoalOnes")
        c["HomeTimeOut"] = dec(p[20], 0, 2, True)
        c["GuestTimeOut"] = dec(p[21], 0, 2, True)
        c["HomeSaves"] = dec(p[22], 1, 2, True) + dec(p[22], 0, 2, True)
        # ScoreConnect assigns byte 23 to HomeSaves a second time and never fills GuestSaves. Reproduced.
        c["HomeSaves"] = dec(p[23], 1, 2, True) + dec(p[23], 0, 2, True)


PROTOCOLS = {
    "AllAmerican_Baseball": lambda: Model8000Protocol(Main8000Baseball()),
    "AllAmerican_Football": lambda: Model8000Protocol(Main8000Football()),
    "AllAmerican_Basketeball": lambda: Model8000Protocol(Main8000Basketball()),
    "AllAmerican_Volleyball": lambda: Model8000Protocol(Main8000Volleyball()),
    "AllAmerican_Hockey": lambda: Model8000Protocol(Main8000Hockey()),
    "AllAmerican_Soccer": lambda: Model8000Protocol(Main8000Soccer()),
    "AllAmerican3000_Football": lambda: Model3000Protocol(Model3000Football()),
    "AllAmerican9000_Football": lambda: Model9000Protocol(Model9000Football()),
    "AllAmerican9000_Baskteball": lambda: Model9000Protocol(Model9000Basketball()),
    "AllAmerican9000_Hockey": lambda: Model9000Protocol(Model9000Hockey()),
}
