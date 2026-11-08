"""Harris Time CTL2K (basketball, hockey) and Harris Time V2 (hockey).

Main: ``':' ... LF`` ASCII frame (>= 74 bytes), decoded only when bytes 1-4 are "4321".
V2:   ``'@@' ... '##'`` frame of exactly 62 bytes starting at the first '@'.
See docs/vendors/harristime.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find, find_pair
from .common import ascii_char

__all__ = ["PROTOCOLS"]

_MAIN_MIN_LEN = 74
_V2_LEN = 62


def _harris_ascii(d: int) -> str:
    """Characters are sent as '0'-'9' plus an offset of 11 per status flag (60-69, 71-80, ... 126-135)."""
    if 32 <= d < 58:
        return chr(d)
    for k in range(1, 8):
        lo = 49 + 11 * k  # 60, 71, 82, 93, 104, 115, 126
        if lo <= d < lo + 10:
            return chr(d - 12 - 11 * (k - 1))
    return " "


def _fields(c: dict, p: bytes, table: dict, conv) -> None:
    for field, i in table.items():
        c[field] = conv(p[i])


class HarrisTimeProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, 0x0A)
            if end < 0:
                return
            start = find(buf, 0x3A)
            if not 0 <= start < end:
                del buf[: end + 1]  # LF with no ':' before it: junk
                continue
            pkt = bytes(buf[start : end + 1])
            del buf[: end + 1]
            if len(pkt) < _MAIN_MIN_LEN:
                self.reject()
                continue
            yield pkt


class HarrisTimeV2Protocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            end = find_pair(buf, 0x23, 0x23)
            if end < 0:
                return
            at = find_pair(buf, 0x40, 0x40) - 1
            if not 0 <= at < end:
                del buf[: end + 1]  # "##" with no "@@" before it: junk
                continue
            pkt = bytes(buf[at : end + 1])
            del buf[: end + 1]
            if len(pkt) != _V2_LEN:
                self.reject()
                continue
            yield pkt


# --------------------------------------------------------------------------- CTL2K basketball
_BB_FIELDS = {
    "HomeScoreTens": 9, "HomeScoreOnes": 10, "GuestScoreTens": 15, "GuestScoreOnes": 16, "Period": 17,
    "HomeFoulOnes": 18, "GuestFoulOnes": 19, "HomeTimeouts": 20, "GuestTimeouts": 21,
    "FoulPlayerOnes": 22, "FoulPlayerTens": 23, "FoulPlayerNumberOfFouls": 24,
    "ShotClockSecondTens": 25, "ShotClockSecondOnes": 26,
}


def _is_ctl2k(p: bytes) -> bool:
    return p[1:5] == b"4321"


class BasketballDecoder(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < _MAIN_MIN_LEN or not _is_ctl2k(p):
            return
        c = self.c
        h = _harris_ascii
        if h(p[14]) == " ":  # seconds.tenths
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=h(p[11]),
                     ClockSecondOnes=h(p[12]), ClockTenthsSecond=h(p[13]))
        else:
            c.update(ClockMode=":", ClockMinutesTens=h(p[11]), ClockMinutesOnes=h(p[12]),
                     ClockSecondTens=h(p[13]), ClockSecondOnes=h(p[14]), ClockTenthsSecond="0")
        _fields(c, p, _BB_FIELDS, h)
        # 100s of points and bonus lamps ride on the offset-coded digit bytes (">" tests as ScoreConnect does)
        c["HomeScoreHundreds"] = "1" if p[9] > 57 else " "
        c["GuestScoreHundreds"] = "1" if p[15] > 57 else " "
        c["HomeBonus"] = "B" if p[10] > 60 else " "
        c["HomeDoubleBonus"] = "B" if p[10] > 71 else " "
        c["GuestBonus"] = "B" if p[16] > 60 else " "
        c["GuestDoubleBonus"] = "B" if p[16] > 71 else " "
        c["Horn"] = " " if p[58] == 48 else "H"
        if 104 <= p[12] <= 114:  # possession arrow rides on the minutes-ones byte; otherwise left as it was
            c.update(HomePossession="<", GuestPossession=" ")
        elif 60 <= p[12] <= 70:
            c.update(HomePossession=" ", GuestPossession=">")


# --------------------------------------------------------------------------- CTL2K hockey
def _hockey_main_table() -> dict:
    t = {"ClockMinutesTens": 11, "ClockMinutesOnes": 12, "ClockSecondTens": 13, "ClockSecondOnes": 14,
         "HomeScoreTens": 9, "HomeScoreOnes": 10, "GuestScoreTens": 15, "GuestScoreOnes": 16, "Period": 17,
         "HomeShotOnGoalTens": 18, "HomeShotOnGoalOnes": 19, "GuestShotOnGoalTens": 20,
         "GuestShotOnGoalOnes": 21}
    i = 22
    for side in ("Home", "Guest"):
        for n in (1, 2):
            pre = f"{side}PenaltyPlayer{n}"
            for suffix in ("Tens", "Ones", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes"):
                t[pre + suffix] = i
                i += 1
    return t


_HOCKEY_MAIN = _hockey_main_table()


class HockeyDecoder(Decoder):
    contract = "HockeyLacrosse"
    event = "Hockey"

    def decode(self, p: bytes) -> None:
        if len(p) < _MAIN_MIN_LEN or not _is_ctl2k(p):
            return
        self.c["ClockMode"] = ":"
        _fields(self.c, p, _HOCKEY_MAIN, _harris_ascii)


# --------------------------------------------------------------------------- V2 hockey
_HOCKEY_V2 = {
    "ClockSecondOnes": 15, "ClockSecondTens": 16, "ClockMinutesOnes": 17, "ClockMinutesTens": 18,
    "HomeScoreOnes": 20, "HomeScoreTens": 21, "GuestScoreOnes": 23, "GuestScoreTens": 24, "Period": 26,
    "HomeShotOnGoalOnes": 28, "HomeShotOnGoalTens": 29, "GuestShotOnGoalOnes": 31, "GuestShotOnGoalTens": 32,
}
def _add_v2_penalties(table: dict) -> None:
    for side, n, base in (("Home", 1, 34), ("Home", 2, 40), ("Guest", 1, 46), ("Guest", 2, 52)):
        pre = f"{side}PenaltyPlayer{n}"
        table.update({pre + "ClockSecondOnes": base, pre + "ClockSecondTens": base + 1,
                      pre + "ClockMinutesOnes": base + 2, pre + "Ones": base + 3, pre + "Tens": base + 4})


_add_v2_penalties(_HOCKEY_V2)


class HockeyV2Decoder(Decoder):
    contract = "HockeyLacrosse"
    event = "Hockey"

    def decode(self, p: bytes) -> None:
        if len(p) < _V2_LEN:
            return
        self.c["ClockMode"] = ":"
        _fields(self.c, p, _HOCKEY_V2, ascii_char)  # digits are plain ASCII, least significant first


PROTOCOLS = {
    "HarrisTime_Basketball": lambda: HarrisTimeProtocol(BasketballDecoder()),
    "HarrisTime_Hockey": lambda: HarrisTimeProtocol(HockeyDecoder()),
    "HarrisTimeV2_Hockey": lambda: HarrisTimeV2Protocol(HockeyV2Decoder()),
}
