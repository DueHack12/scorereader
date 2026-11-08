"""Stramatel scoreboards (standard 54-byte ASCII frames, plus the BE04030 variant with 55-byte frames).

Ids: Stramatel_Basketball, _BasketballBE04030, _Hockey, _RinkHockey, _Hockey452, _IceHockey, _IceHockeyBE04030,
_Volleyball, _Tennis, _Futsal, _HandBall, _TableTennis, _Badminton.
See docs/vendors/stramatel.md for the wire formats and field tables.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find, find_pair
from .common import ascii_char, bcd

__all__ = ["PROTOCOLS"]

CR = 0x0D
CHANNELS = range(0xF8, 0xFE)  # channel bytes F8..FD start a standard frame


# --------------------------------------------------------------------------- framing
class StramatelProtocol(Protocol):
    """<channel F8..FD> <sport char> ... <CR>, exactly 54 bytes including both ends. No checksum."""

    frame_len = 54

    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, CR)
            if end < 0:
                return
            start = next((i for i, b in enumerate(buf) if b in CHANNELS), -1)
            pkt = bytes(buf[start : end + 1]) if 0 <= start < end else None
            del buf[: end + 1]
            if pkt is not None and len(pkt) == self.frame_len:
                yield pkt
            else:
                self.reject()


class BE04030Protocol(Protocol):
    """F8 F8 ... CR CR: the packet runs from the second F8 to the second CR and must be 55 bytes."""

    frame_len = 55

    def extract(self):
        buf = self.buf
        while True:
            end = find_pair(buf, CR, CR)
            if end < 0:
                return
            start = find_pair(buf, 0xF8, 0xF8)
            pkt = bytes(buf[start : end + 1]) if 0 <= start < end else None
            del buf[: end + 1]
            if pkt is not None and len(pkt) == self.frame_len:
                yield pkt
            else:
                self.reject()


# --------------------------------------------------------------------------- shared decode helpers
def _a(p: bytes, i: int, slz: bool = False) -> str:
    """ASCII character at p[i]; with slz a "0" reads as blank."""
    return ascii_char(p[i], slz)


def _pair(p: bytes, i: int, slz: bool = False) -> str:
    """Two ASCII characters at p[i], p[i + 1]; optional zero suppression on the first."""
    return _a(p, i, slz) + _a(p, i + 1)


class _StramatelDecoder(Decoder):
    min_len = 54

    def decode(self, p: bytes) -> None:
        if len(p) < max(self.min_len, 2):
            return
        fn = self.packets().get(p[1])
        if fn:
            fn(p)

    def packets(self) -> dict:
        raise NotImplementedError

    def _clock(self, p: bytes) -> None:
        c = self.c
        if _a(p, 6) != " " and _a(p, 7) != " ":
            c["ClockMode"] = ":"
            c["ClockMinutesTens"], c["ClockMinutesOnes"] = _a(p, 4, True), _a(p, 5)
            c["ClockSecondTens"], c["ClockSecondOnes"] = _a(p, 6), _a(p, 7)
            c["ClockTenthsSecond"] = "0"
        else:
            c["ClockMode"] = "."
            c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"], c["ClockSecondOnes"] = _a(p, 4, True), _a(p, 5)
            c["ClockTenthsSecond"] = _a(p, 6)

    def _status(self, p: bytes, code: int = 0x30) -> None:
        self.c["InternalClockStatus"] = "R" if p[20] == code else "S"

    def _horn(self, p: bytes) -> None:
        self.c["Horn"] = "H" if p[19] == 0x31 else " "

    def _name(self, key: str, p: bytes, off: int) -> None:
        """Team names are 4 UTF-16LE characters; ScoreConnect keeps the first non-blank name it sees."""
        if not str(self.c.get(key, "")).strip():
            self.c[key] = bytes(p[off : off + 8]).decode("utf-16-le", errors="replace")

    def _names(self, off: int = 6) -> dict:
        return {0x77: lambda p: self._name("HomeTeamName", p, off), 0x62: lambda p: self._name("GuestTeamName", p, off)}

    def _shot(self, p: bytes):
        """(tens, ones, tenths or None) of the shot clock. Bit 6 of p[49] means seconds + tenths."""
        if p[49] & 0x40:
            ones, tenths = _a(p, 48), bcd(p[49], 0)
            return "0", ("0" if ones == " " else ones), ("0" if tenths == " " else tenths)
        tens, ones = _a(p, 48), _a(p, 49)
        return ("0" if tens == " " else tens), ("0" if ones == " " else ones), None


# --------------------------------------------------------------------------- basketball
class Basketball(_StramatelDecoder):
    contract = "Basketball"
    event = "Basketball"

    def packets(self) -> dict:
        d = {0x33: self._main, 0x34: self._main, 0x38: lambda p: self._points(p, "Home"),
             0x37: lambda p: self._points(p, "Guest")}
        d.update(self._names())
        return d

    def _main(self, p: bytes) -> None:
        c = self.c
        c["HomePossession"] = "<" if p[3] == 0x31 else " "
        c["GuestPossession"] = ">" if p[3] == 0x32 else " "
        self._clock(p)
        for side, b in (("Home", 8), ("Guest", 11)):
            c[f"{side}ScoreHundreds"] = _a(p, b, True)
            c[f"{side}ScoreTens"] = _a(p, b + 1, c[f"{side}ScoreHundreds"] == " ")
            c[f"{side}ScoreOnes"] = _a(p, b + 2)
        c["Period"] = _a(p, 14)
        c["HomeFoulTens"] = c["GuestFoulTens"] = " "
        c["HomeFoulOnes"], c["GuestFoulOnes"] = _a(p, 15), _a(p, 16)
        c["HomeTimeouts"], c["GuestTimeouts"] = _a(p, 17), _a(p, 18)
        self._horn(p)
        self._status(p)
        c["TimeoutClockMinutesOnes"] = _a(p, 21)
        c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"] = _a(p, 46), _a(p, 47)
        tens, ones, tenths = self._shot(p)
        c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = tens, ones
        c["ShotClockTenthsSecond"] = " " if tenths is None else tenths
        for n in range(5):
            c[f"HomePlayer{n + 1}FoulNumber"] = _a(p, 22 + n)
            c[f"GuestPlayer{n + 1}FoulNumber"] = _a(p, 34 + n)
        c["PlayClockStatusInternal"] = "R" if p[51] == 0x30 else "S"

    def _points(self, p: bytes, side: str) -> None:
        for n in range(5):
            self.c[f"{side}Player{n + 1}Points"] = _pair(p, 22 + 2 * n, True)


# --------------------------------------------------------------------------- hockey family
class _Hockey(_StramatelDecoder):
    """Parameterised by byte positions. pens[side] = [(minutes tens or None, minutes ones, sec tens, sec ones)]."""

    contract = "HockeyLacrosse"
    event = "Hockey"
    main_id = 0x35
    scores = (9, 10, 12, 13)      # home tens/ones, guest tens/ones
    period = 14
    timeouts = (17, 18)           # None when the board has none
    status_code = 0x30
    name_off = 6
    shot_ids = (0x37, 0x38)
    pens: dict = {}

    def packets(self) -> dict:
        d = {self.main_id: self._main}
        d.update({i: self._shot_clock for i in self.shot_ids})
        d.update(self._names(self.name_off))
        return d

    def _shot_clock(self, p: bytes) -> None:
        tens, ones, tenths = self._shot(p)
        self.c["ShotClockTens"], self.c["ShotClockOnes"] = tens, ones
        if tenths is not None:
            self.c["ShotClockTenthsSecond"] = tenths

    def _main(self, p: bytes) -> None:
        c = self.c
        self._clock(p)
        ht, ho, gt, go = self.scores
        c["HomeScoreTens"], c["HomeScoreOnes"] = _a(p, ht), _a(p, ho)
        c["GuestScoreTens"], c["GuestScoreOnes"] = _a(p, gt), _a(p, go)
        c["Period"] = _a(p, self.period)
        if self.timeouts:
            c["HomeTimeOut"], c["GuestTimeOut"] = _a(p, self.timeouts[0]), _a(p, self.timeouts[1])
        self._horn(p)
        self._status(p, self.status_code)
        for side, rows in self.pens.items():
            for n, (mt, mo, st, so) in enumerate(rows, 1):
                k = f"{side}PenaltyPlayer{n}Clock"
                c[k + "MinutesTens"] = " " if mt is None else _a(p, mt)
                c[k + "MinutesOnes"], c[k + "SecondTens"], c[k + "SecondOnes"] = _a(p, mo), _a(p, st), _a(p, so)


class Hockey(_Hockey):
    pens = {
        "Home": [(None, 22, 23, 24), (None, 25, 26, 27), (None, 28, 29, 30)],
        "Guest": [(None, 35, 36, 37), (None, 38, 39, 40), (None, 41, 42, 43)],
    }


class Hockey452(_Hockey):
    pens = {
        "Home": [(None, 24, 25, 26), (None, 29, 30, 31), (None, 34, 35, 36)],
        "Guest": [(None, 39, 40, 41), (None, 44, 45, 46), (None, 49, 50, 51)],
    }


class IceHockey(_Hockey):
    main_id = 0x93
    scores = (8, 9, 10, 11)
    period = 12
    timeouts = None
    pens = {"Home": [(None, 16, 17, 18)]}


class IceHockeyBE04030(_Hockey):
    main_id = 0x93
    status_code = 0x31
    name_off = 7
    shot_ids = ()
    pens = {
        "Home": [(29, 22, 23, 24), (30, 26, 27, 28)],
        "Guest": [(43, 36, 37, 38), (44, 40, 41, 42)],
    }
    min_len = 55


# --------------------------------------------------------------------------- futsal / handball
class Futsal(_StramatelDecoder):
    contract = "FutsalHandball"

    def __init__(self, handball: bool = False):
        self.event = "Handball" if handball else "Futsal"
        super().__init__()

    def packets(self) -> dict:
        d = {53: self._main, 60: self._main, 37: self._clock, 38: self._clock}
        d.update(self._names())
        return d

    def _main(self, p: bytes) -> None:
        c = self.c
        self._clock(p)
        c["HomeFouls"] = _a(p, 8)
        c["HomeScoreTens"], c["HomeScoreOnes"] = _a(p, 9, True), _a(p, 10)
        c["GuestFouls"] = _a(p, 11)
        c["GuestScoreTens"], c["GuestScoreOnes"] = _a(p, 12, True), _a(p, 13)
        c["Period"] = _a(p, 14)
        c["HomeTimeOut"], c["GuestTimeOut"] = _a(p, 17), _a(p, 18)
        self._horn(p)
        self._status(p)
        # (side, player) -> (number tens, number ones, minutes ones, seconds tens, seconds ones)
        for side, n, t, o, m, s1, s2 in (("Home", 1, 31, 32, 22, 23, 24), ("Home", 2, 46, 47, 35, 36, 37),
                                         ("Guest", 1, 33, 34, 25, 26, 27), ("Guest", 2, 48, 49, 38, 39, 40)):
            k = f"{side}PenaltyPlayer{n}"
            c[k + "Tens"], c[k + "Ones"] = _a(p, t), _a(p, o)
            c[k + "ClockMinutesTens"] = " "
            c[k + "ClockMinutesOnes"], c[k + "ClockSecondTens"], c[k + "ClockSecondOnes"] = _a(p, m), _a(p, s1), _a(p, s2)


# --------------------------------------------------------------------------- racket sports
class _TimeOfDay(_StramatelDecoder):
    """Table tennis, badminton and tennis show a match-elapsed hh:mm in bytes 4-7."""

    def _hhmm(self, p: bytes) -> None:
        c = self.c
        c["ClockHourTens"], c["ClockHourOnes"] = _a(p, 4), _a(p, 5)
        c["ClockMinutesTens"], c["ClockMinutesOnes"] = _a(p, 6), _a(p, 7)


class TableTennisBadminton(_TimeOfDay):
    contract = "TableTennisBadminton"

    def __init__(self, badminton: bool = False):
        self.event = "Badminton" if badminton else "TableTennis"
        super().__init__()

    def packets(self) -> dict:
        d = {58: self._main, 108: self._main}
        d.update(self._names())
        return d

    def _main(self, p: bytes) -> None:
        c = self.c
        self._hhmm(p)
        c["Set"] = _a(p, 14)
        c["HomePoints"], c["GuestPoints"] = _pair(p, 9), _pair(p, 12)
        c["HomeSetsWon"], c["GuestSetsWon"] = _a(p, 15), _a(p, 16)
        c["HomeServe"] = "S" if p[50] in (0x31, 0x32) else " "
        c["GuestServe"] = "S" if p[50] in (0x33, 0x34) else " "
        for n in range(4):
            c[f"HomePointsSet{n + 1}"] = _pair(p, 24 + 4 * n)
            c[f"GuestPointsSet{n + 1}"] = _pair(p, 26 + 4 * n)


class Tennis(_TimeOfDay):
    contract = "Tennis"
    event = "Tennis"

    def packets(self) -> dict:
        d = {57: self._main}
        d.update(self._names())
        return d

    def _main(self, p: bytes) -> None:
        c = self.c
        self._hhmm(p)
        c["TopPoints"], c["BottomPoints"] = _pair(p, 9, True), _pair(p, 12, True)
        c["Set"] = _a(p, 14)
        # sets 1-2 suppress a leading zero, sets 3-4 (a different part of the frame) do not
        for n, (t, b, slz) in enumerate(((24, 26, True), (28, 30, True), (37, 39, False), (41, 43, False)), 1):
            c[f"TopSet{n}Tens"], c[f"TopSet{n}Ones"] = _a(p, t, slz), _a(p, t + 1)
            c[f"BottomSet{n}Tens"], c[f"BottomSet{n}Ones"] = _a(p, b, slz), _a(p, b + 1)
        # ScoreConnect only ever sets the top player's serve (its bottom-serve branch repeats the same test)
        if p[50] in (0x30, 0x31):
            c["TopServe"], c["BottomServe"] = "S", " "
        c["IsTieBreak"] = "1" if p[52] == 0x31 else " "
        self._status(p)


class Volleyball(_StramatelDecoder):
    contract = "Volleyball"
    event = "Volleyball"

    def packets(self) -> dict:
        d = {54: self._main}
        d.update(self._names())
        return d

    def _main(self, p: bytes) -> None:
        c = self.c
        self._clock(p)
        c["HomeScoreTens"], c["HomeScoreOnes"] = _a(p, 9, True), _a(p, 10)
        c["GuestScoreTens"], c["GuestScoreOnes"] = _a(p, 12, True), _a(p, 13)
        c["Set"] = _a(p, 14)
        c["HomeGamesWon"], c["GuestGamesWon"] = _a(p, 15), _a(p, 16)
        c["HomeTimeout"], c["GuestTimeout"] = _a(p, 17), _a(p, 18)
        self._status(p)
        for n in range(4):
            c[f"HomeScoreSet{n + 1}"] = _pair(p, 22 + 4 * n, True)
            c[f"GuestScoreSet{n + 1}"] = _pair(p, 24 + 4 * n, True)


def _std(decoder):
    return lambda: StramatelProtocol(decoder())


def _be(decoder):
    return lambda: BE04030Protocol(decoder())


PROTOCOLS = {
    "Stramatel_Basketball": _std(Basketball),
    "Stramatel_Hockey": _std(Hockey),
    "Stramatel_RinkHockey": _std(Hockey),
    "Stramatel_IceHockey": _std(IceHockey),
    "Stramatel_Hockey452": _std(Hockey452),
    "Stramatel_IceHockeyBE04030": _be(IceHockeyBE04030),
    "Stramatel_BasketballBE04030": _be(Basketball),
    "Stramatel_Volleyball": _std(Volleyball),
    "Stramatel_Tennis": _std(Tennis),
    "Stramatel_Futsal": _std(lambda: Futsal(False)),
    "Stramatel_HandBall": _std(lambda: Futsal(True)),
    "Stramatel_TableTennis": _std(lambda: TableTennisBadminton(False)),
    "Stramatel_Badminton": _std(lambda: TableTennisBadminton(True)),
}
