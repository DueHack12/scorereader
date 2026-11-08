"""Daktronics All Sport current-loop decoders (ScoreConnect's "Daktronics Main" family).

Wire format (``ProtocolV3``): the PIC forwards the console's current loop as

    55 AA | addr | len | x | x | 22 | data[len-1] | checksum

``(sum(addr..checksum) + 0x55 + 0xAA) & 0xFF == 0``. Each packet is handed to the decoder as
``addr len x x 22 data… checksum 55 AA`` (so ``p[0]`` is the address and ``p[5]`` the first data byte).
Decoders keep their contract between packets: the console only sends what changed.

Most sports use 7-segment data bytes; the "5500" family sends ASCII; addresses 0xDC/0xDD carry
LED-matrix bitmaps (team names, decoded by :func:`_dak_text`).
"""
from __future__ import annotations

from .base import Decoder, Protocol, find_pair
from .common import ascii_char, digit, digit_nb

__all__ = ["ProtocolV3", "PROTOCOLS", "Autodetect"]

HOME_NAME = "HomeTeamName"
GUEST_NAME = "GuestTeamName"


# --------------------------------------------------------------------------- protocol
class ProtocolV3(Protocol):
    """Finds ``55 AA`` frames, verifies the checksum and yields ``p`` (see module docstring)."""

    def extract(self):
        buf = self.buf
        while True:
            j = find_pair(buf, 0x55, 0xAA)  # index of the AA
            if j < 0:
                last = buf[-1] if buf else -1
                del buf[: len(buf) - 1 if last == 0x55 else len(buf)]
                return
            if j > 1:
                del buf[: j - 1]  # garbage before the 55
                j = 1
            if len(buf) < 4:
                return
            length = buf[3]
            total = length + 7  # 55 AA + (length + 5) bytes
            if len(buf) < total:
                return
            frame = bytes(buf[:total])
            del buf[:total]
            if sum(frame) & 0xFF:
                self.reject()  # ScoreConnect drops the whole frame too
                continue
            yield frame[2:] + b"\x55\xaa"


# --------------------------------------------------------------------------- helpers
# Dot-matrix glyphs (column bytes, zero = gap) used for team names on addresses 0xDC/0xDD.
_GLYPH_FORMS = {
    "A": ([254, 9, 254], [254, 9, 9, 254]),
    "B": ([255, 137, 118], [255, 137, 137, 118]),
    "C": ([126, 129, 66], [126, 129, 129, 66]),
    "D": ([255, 129, 126], [255, 129, 129, 126]),
    "E": ([255, 137, 129], [255, 137, 137, 129]),
    "F": ([255, 9, 1], [255, 9, 9, 1]),
    "G": ([126, 129, 137, 122],),
    "H": ([255, 8, 255], [255, 8, 8, 255]),
    "I": ([255], [129, 255, 129]),
    "J": ([96, 128, 127], [96, 128, 128, 127]),
    "K": ([255, 24, 36, 195],),
    "L": ([255, 128, 128], [255, 128, 128, 128]),
    "M": ([255, 2, 12, 2, 255],),
    "N": ([255, 12, 48, 255],),
    "O": ([126, 129, 126], [126, 129, 129, 126]),
    "P": ([255, 9, 6], [255, 9, 9, 6]),
    "Q": ([126, 129, 161, 126, 128],),
    "R": ([255, 17, 238], [255, 25, 41, 198]),
    "S": ([70, 137, 114], [70, 137, 137, 114]),
    "T": ([1, 255, 1], [1, 1, 255, 1, 1]),
    "U": ([127, 128, 127], [127, 128, 128, 127]),
    "V": ([63, 64, 128, 64, 63],),
    "W": ([127, 128, 112, 128, 127],),
    "X": ([227, 20, 8, 20, 227],),
    "Y": ([7, 8, 240, 8, 7],),
    "Z": ([225, 145, 137, 135],),
    ".": ([128],),
    ",": ([128, 96],),
}
_GLYPHS = {tuple(form): ch for ch, forms in _GLYPH_FORMS.items() for form in forms}


def _dak_text(p: bytes, start: int, end: int) -> str:
    """Letters drawn as pixel columns in p[start..end] -> 8-character name (space padded)."""
    out: list[str] = []
    cols: list[int] = []
    try:
        for i in range(start, end + 1):
            b = p[i]
            flush = False
            if b > 0 and len(cols) < 6:
                cols.append(b)
            else:
                flush = True
            if i == end:
                flush = True
            if flush:
                ch = _GLYPHS.get(tuple(cols))
                if ch:
                    out.append(ch)
                cols = []
    except IndexError:
        pass  # ScoreConnect stops quietly at the end of the packet
    return ("".join(out) + " " * 8)[:8]


def _to_int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        return 0


def _tb3(c: dict, inning: int, outs: int) -> str:
    """Top/bottom guess: 'T' when the inning changed (or is 0), 'B' when the out count dropped, else ' '."""
    cur = _to_int(c.get("InningTens", " ") + c.get("InningOnes", " "))
    if inning != cur or inning == 0:
        return "T"
    if outs < _to_int(c.get("Outs", " ")):
        return "B"
    return " "


def _set_tb(c: dict, which: str) -> None:
    if which == "T":
        c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "T", ".", " "
    elif which == "B":
        c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "B", " ", "."


def _dak3000_period(b: int) -> str:
    return {1: "1", 67: "2", 7: "3", 15: "4"}.get(b, " ")


# Rows: (guard, field, getter) assigns when n > guard (n = len byte + 5); callables take (c, p, n).
def _at(idx, field, fn=digit, guard=None):
    g = idx + 1 if guard is None else guard
    return [(g, field, lambda p, i=idx: fn(p[i]))]


def _seq(start, *fields, fn=digit):
    rows = []
    for k, f in enumerate(fields):
        rows += _at(start + k, f, fn)
    return rows


def _pair(idx, field, guard=None):
    g = idx + 2 if guard is None else guard
    return [(g, field, lambda p, i=idx: digit(p[i]) + digit(p[i + 1]))]


def _flag(idx, mask, field, on, off=" ", guard=None):
    g = idx + 1 if guard is None else guard
    return [(g, field, lambda p, i=idx, m=mask: on if p[i] & m else off)]


def _const(value, *fields):
    return [(-1, f, lambda p, v=value: v) for f in fields]


def _mode(c, p, n):  # ClockMode from the colon byte
    if n > 9:
        c["ClockMode"] = "." if p[8] == 0 else ":"


def _status(c, p, n):
    if n > 12:
        c["InternalClockStatus"] = "R" if p[11] & 0x40 == 0 else "S"


def _clock_by_mode(c, p, n):
    if c.get("ClockMode", " ") == ".":
        c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
        if n > 6:
            c["ClockSecondTens"] = digit(p[5])
        if n > 7:
            c["ClockSecondOnes"] = digit(p[6])
        if n > 8:
            c["ClockTenthsSecond"] = digit(p[7])
    else:
        if n > 6:
            c["ClockMinutesTens"] = digit(p[5])
        if n > 7:
            c["ClockMinutesOnes"] = digit(p[6])
        if n > 8:
            c["ClockSecondTens"] = digit(p[7])
        if n > 9:
            c["ClockSecondOnes"] = digit(p[8])
        c["ClockTenthsSecond"] = "0"


def _mode_and_clock(c, p, n):
    if n > 9:
        c["ClockMode"] = "." if p[8] == 0 else ":"
        _clock_by_mode(c, p, n)


_MMSS = _seq(5, "ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")


def _names(start):
    def run(c, p, n):
        half = max((p[1] - 1) // 2, 0)
        c[HOME_NAME] = _dak_text(p, start, start + half - 1)
        c[GUEST_NAME] = _dak_text(p, start + half, start + 2 * half - 1)
    return run


def _run(c, rows, p, n):
    for r in rows:
        if callable(r):
            r(c, p, n)
        elif n > r[0]:
            v = r[2](p)
            if v is not None:  # a getter returns None for "leave unchanged"
                c[r[1]] = v


def _score(first):
    return _seq(first, "HomeScoreTens", "HomeScoreOnes", "GuestScoreTens", "GuestScoreOnes")


# --------------------------------------------------------------------------- decoders
class _Table(Decoder):
    """Decoder driven by ``table: {address: [rows]}``. Out-of-range reads abort the packet (counted in ``short``)."""

    table: dict = {}

    def __init__(self, event: str | None = None):
        if event:
            self.event = event
        super().__init__()
        self.short = 0

    def decode(self, p: bytes) -> None:
        rows = self.table.get(p[0])
        if rows:
            try:
                _run(self.c, rows, p, p[1] + 5)
            except IndexError:
                self.short += 1


def _football_common():
    return {
        16: _seq(5, "BallOnTens", "BallOnOnes", "Down", "ToGoTens", "ToGoOnes"),
    }


_POSS_07_56 = (
    lambda i: _flag_eq(i, 7, "HomePossession", "<") + _flag_eq(i, 56, "GuestPossession", ">")
)


def _flag_eq(idx, value, field, on, off=" "):
    return [(idx + 1, field, lambda p, i=idx, v=value: on if p[i] == v else off)]


class Football(_Table):
    contract = event = "Football"
    table = {
        1: _at(9, "PlayClockTens") + _at(10, "PlayClockOnes") + [_mode_and_clock, _status],
        15: [_clock_by_mode] + _score(11) + _POSS_07_56(17) + _at(18, "HomeTimeouts") + _at(19, "GuestTimeouts")
        + _at(15, "Quarter"),
        **_football_common(),
    }


class Football6103(_Table):
    contract = event = "Football"
    table = {
        1: Football.table[1],
        220: [(15, "HomePossession", lambda p: "<" if p[14] == 64 else " "),
              (15, "GuestPossession", lambda p: ">" if p[14] == 128 else " ")],
        15: [_clock_by_mode] + _score(11) + _POSS_07_56(17) + _at(18, "HomeTimeouts") + _at(19, "GuestTimeouts"),
        12: _score(9) + _seq(17, "ToGoTens", "ToGoOnes", "Down", "Quarter"),
        14: _at(7, "HomeTimeouts") + _at(13, "GuestTimeouts"),
        13: _at(13, "Quarter"),
        **_football_common(),
    }


class Football3000(_Table):
    contract = event = "Football"
    table = {
        1: _at(9, "PlayClockTens") + _at(10, "PlayClockOnes") + [_mode],
        12: [_clock_by_mode] + _score(9) + _flag_eq(13, 7, "HomePossession", "<") + _flag_eq(13, 56, "GuestPossession", ">")
        + _at(19, "Quarter"),
        23: _seq(5, "BallOnTens", "BallOnOnes", "Down", "ToGoTens", "ToGoOnes"),
    }

class JvcPracticeFootball(_Table):
    contract = event = "Football"
    table = {
        1: _at(9, "PlayClockTens") + _at(10, "PlayClockOnes") + [_mode, _status],
        **_football_common(),
    }
    table[15] = ([_clock_by_mode] + _seq(13, "GuestScoreTens", "GuestScoreOnes") + _POSS_07_56(17)
                 + _at(18, "HomeTimeouts") + _at(19, "GuestTimeouts") + _at(15, "Quarter"))


class Football1600(_Table):
    contract = event = "Football"
    table = {
        11: list(_MMSS) + _score(15) + _at(19, "Down"),
    }

    def decode(self, p: bytes) -> None:
        self.c["ClockMode"] = ":"  # every packet, whatever the address
        super().decode(p)


class Soccer(_Table):
    contract = event = "Soccer"
    table = {
        1: [_mode, _status],
        11: [_clock_by_mode] + _score(15) + _at(19, "Period"),
        12: _flag(13, 0x80, "Horn", "H", guard=14) + _seq(15, "HomeShotTens", "HomeShotOnes", "GuestShotTens",
                                                           "GuestShotOnes"),
        13: _pair(15, "HomeCornerKicks") + _pair(17, "GuestCornerKicks"),
        17: _pair(7, "HomeSaves") + _pair(15, "GuestSaves"),
    }


def _hockey_penalties(side, first, shots, p3_ones_bug):
    """Two penalty slots (player, minutes, seconds) from `first`, optional shots, then slot 3 blanked."""
    s = side
    rows = _seq(first, f"{s}PenaltyPlayer1Tens", f"{s}PenaltyPlayer1Ones")
    rows += _const(" ", f"{s}PenaltyPlayer1ClockMinutesTens")
    rows += _seq(first + 2, f"{s}PenaltyPlayer1ClockMinutesOnes", f"{s}PenaltyPlayer1ClockSecondTens",
                 f"{s}PenaltyPlayer1ClockSecondOnes")
    rows += _seq(first + 5, f"{s}PenaltyPlayer2Tens", f"{s}PenaltyPlayer2Ones")
    rows += _const(" ", f"{s}PenaltyPlayer2ClockMinutesTens")
    rows += _seq(first + 7, f"{s}PenaltyPlayer2ClockMinutesOnes", f"{s}PenaltyPlayer2ClockSecondTens",
                 f"{s}PenaltyPlayer2ClockSecondOnes")
    if shots:
        rows += _seq(first + 10, f"{s}ShotOnGoalTens", f"{s}ShotOnGoalOnes")
    blank = [f"{s}PenaltyPlayer3{k}" for k in ("Tens", "Ones", "ClockMinutesTens", "ClockMinutesOnes",
                                                "ClockSecondTens")]
    if not p3_ones_bug:
        blank.append(f"{s}PenaltyPlayer3ClockSecondOnes")
    rows += _const(" ", *blank)
    return rows


class Hockey5000(_Table):
    contract = "HockeyLacrosse"
    event = "Hockey"
    table = {
        1: _at(9, "ShotClockTens") + _at(10, "ShotClockOnes") + [_mode, _status],
        17: _at(13, "HomeTimeOut") + _at(14, "GuestTimeOut"),
        71: [_clock_by_mode] + _score(9) + _at(20, "Period", guard=21) + _flag(13, 0x80, "Horn", "H", guard=14),
        72: _hockey_penalties("Home", 5, True, False),
        73: _hockey_penalties("Guest", 5, True, False),
    }
    # ScoreConnect quirk (addr 72 only): the second home penalty player's tens field is written twice, from
    # p[10] and then p[11], so HomePenaltyPlayer2Ones is never set.
    table[72] = [(g, "HomePenaltyPlayer2Tens" if f == "HomePenaltyPlayer2Ones" else f, fn) for g, f, fn in table[72]]


class Hockey4103(_Table):
    contract = "HockeyLacrosse"
    event = "Hockey"
    table = {
        1: [_mode, _status],
        11: [_clock_by_mode] + _score(9),
        12: _at(20, "Period", guard=21),
        13: _seq(15, "HomeShotOnGoalTens", "HomeShotOnGoalOnes", "HomeTimeOut", "GuestShotOnGoalTens",
                 "GuestShotOnGoalOnes", "GuestTimeOut"),
        23: _hockey_penalties("Home", 5, False, True),
        25: _hockey_penalties("Guest", 5, False, True),
    }


class Hockey9405(_Table):
    contract = "HockeyLacrosse"
    event = "Hockey"

    def decode(self, p: bytes) -> None:
        try:
            self._decode(p)
        except IndexError:
            self.short += 1

    def _decode(self, p: bytes) -> None:
        c = self.c
        a, n = p[0], p[1] + 7  # this decoder's guards count the trailing 55 AA
        if a == 1 and n >= 9:
            c["ClockMode"] = ":" if p[8] != 0 else "."
            if c["ClockMode"] == ":":
                c["ClockMinutesTens"], c["ClockMinutesOnes"] = digit_nb(p[5]), digit(p[6])
                c["ClockSecondTens"], c["ClockSecondOnes"] = digit(p[7]), digit(p[8])
                c["ClockTenthsSecond"] = " "
            else:
                c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
                c["ClockSecondTens"], c["ClockSecondOnes"] = digit_nb(p[5]), digit(p[6])
                c["ClockTenthsSecond"] = digit(p[7])
            if n > 11:
                c["InternalClockStatus"] = "R" if p[11] & 0x40 == 0 else "S"
            if n > 9:
                c["ShotClockTens"] = digit(p[9])
            if n > 10:
                c["ShotClockOnes"] = digit(p[10])
        elif a == 12 and p[1] >= 7:
            if n > 10:
                ones = digit(p[10])
                blank = ones == " "
                c["HomeScoreTens"] = "0" if blank else digit_nb(p[9])
                c["HomeScoreOnes"] = "0" if blank else ones
            if n > 12:
                ones = digit(p[12])
                blank = ones == " "
                c["GuestScoreTens"] = "0" if blank else digit_nb(p[11])
                c["GuestScoreOnes"] = "0" if blank else ones
            if n > 21:
                c["Period"] = digit(p[20])
        elif a == 11:
            rows = (_at(5, "HomeShotOnGoalTens", guard=5) + _at(6, "HomeShotOnGoalOnes", guard=6)
                    + _at(9, "GuestShotOnGoalTens", guard=9) + _at(10, "GuestShotOnGoalOnes", guard=10))
            _run(c, rows, p, n)


def _players(prefix, slots, kind, first_extra=None):
    """Player slots at p[5..]: number(2), kills/fouls(1), points/digs(2), 5 bytes each."""
    rows = []
    for k, slot in enumerate(slots):
        b = 5 + 5 * k
        rows += _pair(b, f"{prefix}Player{slot}", guard=-1)
        if kind == "bb":
            rows += [(-1, f"{prefix}Player{slot}FoulNumber", lambda p, i=b + 2: digit(p[i]))]
            rows += _pair(b + 3, f"{prefix}Player{slot}Points", guard=-1)
        else:
            rows += [(-1, f"{prefix}Player{slot}Kills", lambda p, i=b + 2: digit(p[i]))]
            rows += _pair(b + 3, f"{prefix}Player{slot}Digs", guard=-1)
    return [(21, f, g) for _, f, g in rows]  # whole block only when n > 21


def _bb_players():
    t = {}
    t[23] = _players("Home", (1, 2, 3), "bb") + [(21, "HomeFullTimeouts", lambda p: digit(p[20]))]
    t[24] = _players("Home", (4, 5), "bb") + [(21, "HomePartialTimeouts", lambda p: digit(p[20])),
                                                (21, "HomeBottomCenter", lambda p: digit(p[17]))]
    t[25] = _players("Guest", (1, 2, 3), "bb") + [(21, "GuestFullTimeouts", lambda p: digit(p[20]))]
    t[26] = _players("Guest", (4, 5), "bb") + [(21, "GuestPartialTimeouts", lambda p: digit(p[20])),
                                                 (21, "InboundChannelNumber", lambda p: digit(p[17]))]
    return t


class Basketball(_Table):
    contract = event = "Basketball"

    @staticmethod
    def _shot_clock(c, p, n):
        if 11 < n <= 15:
            c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = digit(p[9]), digit(p[10])
        if n > 15:
            if p[14] == 0:
                c["ShotClockSecondTens"] = " "
                c["ShotClockSecondOnes"] = digit(p[13])
                c["ShotClockTenthsSecond"] = digit(p[15])
            else:
                c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = digit(p[13]), digit(p[14])
                c["ShotClockTenthsSecond"] = " "

    table = {
        221: [_names(5)],
        1: [_shot_clock.__func__, _mode_and_clock, _status],
        17: _at(13, "HomeTimeouts", guard=14) + _at(14, "GuestTimeouts", guard=15),
        220: _flag(14, 4, "HomeDoubleBonus", "B", guard=15) + _flag(14, 8, "GuestDoubleBonus", "B", guard=15),
        12: [_clock_by_mode]
        + _flag(14, 3, "HomeScoreHundreds", "1", guard=15) + _seq(9, "HomeScoreTens", "HomeScoreOnes")
        + _flag(14, 0xC, "GuestScoreHundreds", "1", guard=15) + _seq(11, "GuestScoreTens", "GuestScoreOnes")
        + _flag(13, 4, "HomePossession", "<", guard=14) + _flag(13, 8, "GuestPossession", ">", guard=14)
        + _flag(13, 0x10, "HomeBonus", "B", guard=14) + _flag(13, 0x20, "GuestBonus", "B", guard=14)
        + _flag(14, 0x30, "HomeFoulTens", "1", guard=15) + _at(15, "HomeFoulOnes")
        + _flag(14, 0xC0, "GuestFoulTens", "1", guard=15) + _at(16, "GuestFoulOnes")
        + _seq(17, "FoulPlayerTens", "FoulPlayerOnes", "FoulPlayerNumberOfFouls", "Period")[:3]
        + _at(20, "Period") + _flag(13, 0x80, "Horn", "H", guard=14),
        **_bb_players(),
    }


class Basketball9122(_Table):
    contract = event = "Basketball"

    @staticmethod
    def _clock1(c, p, n):
        if n > 10:
            c["ShotClockSecondTens"] = digit(p[13])  # guard says n > 10 but reads p[13]
        if n > 11:
            c["ShotClockSecondOnes"] = digit(p[14])
        _mode(c, p, n)
        _clock_by_mode(c, p, n)
        if n > 12:
            c["InternalClockStatus"] = "R" if p[11] & 0x40 == 0 else "S"
            c["Horn"] = "H" if p[11] & 0x10 else " "

    table = {
        221: [_names(5)],
        1: [_clock1.__func__],
        13: _at(17, "HomeTimeouts", guard=18) + _at(20, "GuestTimeouts", guard=21)
        + _flag(14, 4, "HomeDoubleBonus", "B", guard=15) + _flag(14, 8, "GuestDoubleBonus", "B", guard=15)
        + _flag(14, 0x80, "GuestPossession", ">", guard=15) + _flag(14, 0x40, "HomePossession", "<", guard=15)
        + _flag(14, 1, "HomeBonus", "B", guard=15) + _flag(14, 2, "GuestBonus", "B", guard=15)
        + _at(15, "HomeFoulTens") + _at(16, "HomeFoulOnes") + _at(18, "GuestFoulTens") + _at(19, "GuestFoulOnes")
        + _at(13, "Period")
        + _flag(9, 0x80, "HomeScoreHundreds", "1", guard=10) + _seq(9, "HomeScoreTens", "HomeScoreOnes")
        + _flag(11, 0x80, "GuestScoreHundreds", "1", guard=12) + _seq(11, "GuestScoreTens", "GuestScoreOnes"),
        14: _seq(8, "FoulPlayerTens", "FoulPlayerOnes", "FoulPlayerNumberOfFouls")
        + _flag(13, 0x80, "Horn", "H", guard=14),
        **_bb_players(),
    }


class _Ascii5500(Decoder):
    """Shared framing logic for the ASCII "5500" consoles: dispatch on p[6] (group) and p[7] (item)."""

    pad_names = True

    def __init__(self):
        super().__init__()
        self.short = 0

    def decode(self, p: bytes) -> None:
        try:
            self._decode(p, p[1] + 5)
        except IndexError:
            self.short += 1

    def _clock(self, p, n):
        c = self.c
        st = {67: "R", 48: "S"}.get(p[13])
        if st:
            c["InternalClockStatus"] = st

    def _name(self, key, p):
        chars, ok = [], True
        for j in range(8):
            if ok and 13 + j < len(p) and p[13 + j] < 128:
                chars.append(ascii_char(p[13 + j]))
            else:
                ok = False
                if self.pad_names:
                    chars.append(" ")
        self.c[key] = "".join(chars)

    def _ascii_clock(self, p, n, guarded):
        c = self.c
        a = ascii_char
        if p[19] == 32:
            if not guarded or n > 15:
                c["ClockMinutesTens"] = a(p[14])
            if not guarded or n > 16:
                c["ClockMinutesOnes"] = a(p[15])
            if not guarded or n > 17:
                c["ClockMode"] = ":"
            if not guarded or n > 18:
                c["ClockSecondTens"] = a(p[17])
            if not guarded or n > 19:
                c["ClockSecondOnes"] = a(p[18])
            c["ClockTenthsSecond"] = "0"
        elif p[19] == 46:
            c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
            if not guarded or n > 18:
                c["ClockSecondTens"] = a(p[17])
            if not guarded or n > 19:
                c["ClockSecondOnes"] = a(p[18])
            if not guarded or n > 17:
                c["ClockMode"] = "."
            if not guarded or n > 19:
                c["ClockTenthsSecond"] = a(p[20])



class Basketball5500(_Ascii5500):
    contract = event = "Basketball"

    def _decode(self, p, n):
        c, a = self.c, ascii_char
        g, item = p[6], p[7]
        if g == 17:
            if item == 4:
                if n > 11:
                    c["ShotClockSecondTens"] = a(p[10])
                if n > 13:
                    c["ShotClockSecondOnes"] = a(p[11])
            elif item == 1:
                self._clock(p, n)
                if n > 20:
                    self._ascii_clock(p, n, True)
        elif g == 33:
            if item in (1, 2):
                side = "Home" if item == 1 else "Guest"
                if p[9] == 32:
                    base, g0 = 10, 11
                elif p[9] == 155:
                    base, g0 = 14, 15
                else:
                    return
                for k, f in enumerate(("ScoreHundreds", "ScoreTens", "ScoreOnes")):
                    if n > g0 + k:
                        c[side + f] = a(p[base + k])
            elif item == 6 and n > 11:
                c["HomeTimeouts"] = a(p[10])
            elif item == 10 and n > 11:
                c["GuestTimeouts"] = a(p[10])
            elif item == 11 and n > 11:
                c["Period"] = a(p[10])
            elif item in (12, 13):
                side = "Home" if item == 12 else "Guest"
                if n > 10:
                    c[side + "FoulTens"] = a(p[9])
                if n > 11:
                    c[side + "FoulOnes"] = a(p[10])
            elif item == 14:
                if n > 10:
                    c["FoulPlayerTens"] = a(p[9])
                if n > 11:
                    c["FoulPlayerOnes"] = a(p[10])
                if n > 12:
                    c["FoulPlayerNumberOfFouls"] = a(p[11])
        elif g == 81:
            if item == 1:
                self._name(HOME_NAME, p)
            elif item == 2:
                self._name(GUEST_NAME, p)
        elif g == 49 and n > 10:
            on = p[9] == 49
            if item == 3:
                c["HomePossession"] = "<" if on else " "
            elif item == 5:
                c["GuestPossession"] = ">" if on else " "
            elif item == 7:
                c["HomeBonus"] = "B" if on else " "
            elif item == 9:
                c["GuestBonus"] = "B" if on else " "


class Volleyball5500(_Ascii5500):
    contract = event = "Volleyball"
    pad_names = False  # unlike the basketball 5500 decoder, names are not padded to 8

    def _decode(self, p, n):
        c, a = self.c, ascii_char
        g, item = p[6], p[7]
        if g == 17:
            if item == 1:
                self._clock(p, n)
                if n > 20:
                    self._ascii_clock(p, n, False)
        elif g == 33:
            if item in (1, 2):
                side = "Home" if item == 1 else "Guest"
                if p[9] == 32:
                    base, g0 = 11, 12
                elif p[9] == 155:
                    base, g0 = 15, 16
                else:
                    return
                for k, f in enumerate(("ScoreTens", "ScoreOnes")):
                    if n > g0 + k:
                        c[side + f] = a(p[base + k])
            elif n > 11:
                if item == 6:
                    c["HomeTimeout"] = a(p[10])
                elif item == 10:
                    c["GuestTimeout"] = a(p[10])
                elif item == 11:
                    c["Game"] = a(p[10])
                elif item == 12:
                    c["HomeGamesWon"] = a(p[14])  # ScoreConnect reads p[14] here (not p[10]); kept as is
                elif item == 13:
                    c["GuestGamesWon"] = a(p[10])
        elif g == 81:
            if item == 1:
                self._name(HOME_NAME, p)
            elif item == 2:
                self._name(GUEST_NAME, p)
        elif g == 49 and n > 10:
            if item == 3:
                c["HomeServe"] = "*" if p[9] == 49 else " "
            elif item == 5:
                c["GuestServe"] = "*" if p[9] == 49 else " "


class Volleyball(_Table):
    contract = event = "Volleyball"
    table = {
        221: [_names(4)],
        1: [_mode, _status],
        17: _at(13, "HomeTimeout") + _at(14, "GuestTimeout"),
        12: [_clock_by_mode] + _score(9) + _flag(13, 4, "HomeServe", "*", guard=14)
        + _flag(13, 8, "GuestServe", "*", guard=14) + _at(15, "HomeGamesWon") + _at(16, "GuestGamesWon")
        + _at(20, "Set", guard=21) + _at(19, "Game", guard=20),
    }
    table[15] = []
    for _k, _s in enumerate((1, 2, 3, 4)):
        _b = 5 + 4 * _k
        table[15] += [(21, f"HomeScoreSet{_s}", lambda p, i=_b: digit(p[i]) + digit(p[i + 1])),
                      (21, f"GuestScoreSet{_s}", lambda p, i=_b + 2: digit(p[i]) + digit(p[i + 1]))]
    for _a, _side, _slots in ((23, "Home", (1, 2, 3)), (24, "Home", (4, 5, 6)), (25, "Guest", (1, 2, 3)),
                              (26, "Guest", (4, 5, 6))):
        table[_a] = _players(_side, _slots, "vb")


class Baseball(_Table):
    contract = "BaseballSoftball"
    event = "Baseball"
    table = {
        64: _seq(7, "Balls", "Strikes", "Outs") + [
            (11, "ErrorFlag", lambda p: {246: "H", 249: "E", 0: " "}.get(p[10], None))
        ] + _seq(11, "GuestRunTens", "GuestRunOnes", "GuestHitsTens", "GuestHitsOnes", "GuestErrors",
                 "HomeRunTens", "HomeRunOnes", "HomeHitsTens", "HomeHitsOnes", "HomeErrors"),
        65: _seq(5, *[f"GuestInning{i}" for i in range(1, 11)]) + _at(17, "GuestErrorNumber", guard=18),
        66: _seq(5, *[f"HomeInning{i}" for i in range(1, 11)]),
        12: _at(7, "AtBatTens") + _at(8, "AtBatOnes") + _at(5, "InningTens") + _at(6, "InningOnes"),
        11: list(_MMSS),
    }

    def _tb61(self, p, n):
        if n > 12:
            v = p[11] & 0xF
            _set_tb(self.c, {1: "T", 2: "B"}.get(v, ""))

    def _pitch_count(self, p, n):
        c = self.c
        if n == 12 and c.get("TopBottomInning") == "B":
            c["PitchCount"] = ("1" if p[9] & 0x80 else " ") + digit(p[9]) + digit(p[10])
        elif n == 14 and c.get("TopBottomInning") == "T":
            c["PitchCount"] = ("1" if p[11] & 0x80 else " ") + digit(p[11]) + digit(p[12])

    def decode(self, p: bytes) -> None:
        a, n = p[0], p[1] + 5
        try:
            if a == 61:
                self._tb61(p, n)
            elif a == 3:
                self._pitch_count(p, n)
            else:
                super().decode(p)
        except IndexError:
            self.short += 1


class Baseball1600(_Table):
    contract = "BaseballSoftball"
    event = "Baseball"

    def decode(self, p: bytes) -> None:
        if p[0] != 61:
            return
        c, n = self.c, p[1] + 5
        try:
            outs = inn = " "
            if n > 14:
                c["Balls"] = digit_nb(p[13])
            if n > 15:
                c["Strikes"] = digit_nb(p[14])
            if n > 16:
                outs = digit_nb(p[15])
            c["InningTens"] = " "
            if n > 10:
                inn = digit(p[9])
            for f, i, k in (("GuestRunTens", 5, 6), ("GuestRunOnes", 6, 7), ("HomeRunTens", 7, 8),
                            ("HomeRunOnes", 8, 9)):
                if n > k:
                    c[f] = digit(p[i])
            # ScoreConnect passes the *characters* as ints (code points), so the inning never matches: always 'T'.
            _set_tb(c, _tb3(c, ord(inn), ord(outs)))
            c["Outs"] = outs
            c["InningOnes"] = inn
        except IndexError:
            self.short += 1


class Baseball5601(_Table):
    contract = "BaseballSoftball"
    event = "Baseball"

    def decode(self, p: bytes) -> None:
        if p[0] != 12:
            return
        c = self.c
        try:
            c["GuestRunTens"], c["GuestRunOnes"] = digit(p[11]), digit(p[12])
            c["HomeRunTens"], c["HomeRunOnes"] = digit(p[9]), digit(p[10])
            c["InningTens"] = " "
            _set_tb(c, _tb3(c, _to_int(digit(p[18])), _to_int(digit(p[19]))))
            c["InningOnes"] = digit(p[18])
            c["Balls"], c["Strikes"], c["Outs"] = digit(p[14]), digit(p[16]), digit(p[19])
        except IndexError:
            self.short += 1


class Baseball3000(_Table):
    contract = "BaseballSoftball"
    event = "Baseball"

    def decode(self, p: bytes) -> None:
        c, n = self.c, p[1] + 5
        try:
            if p[0] == 63:
                c["Balls"], c["Strikes"], c["Outs"] = digit(p[5]), digit(p[6]), digit(p[7])
                c["InningOnes"] = digit(p[8])
                _set_tb(c, _tb3(c, ord(c["InningOnes"]), ord(c["Outs"])))  # code points again: always 'T'
                _run(c, _seq(9, "GuestRunTens", "GuestRunOnes", "GuestHitsTens", "GuestHitsOnes")
                     + _seq(14, "HomeRunTens", "HomeRunOnes", "HomeHitsTens", "HomeHitsOnes"), p, 99)
            elif p[0] == 11:
                _run(c, _MMSS, p, n)
        except IndexError:
            self.short += 1


class PitchClock(_Table):
    contract = "BaseballSoftball"
    event = "Baseball"
    table = {11: _seq(5, "PitchClockMinutesTens", "PitchClockMinutesOnes", "PitchClockSecondTens",
                      "PitchClockSecondOnes")}


class PitchSpeed(_Table):
    contract = "BaseballSoftball"
    event = "Baseball"
    table = {1: [(-1, "PitchSpeed", lambda p: digit(p[6]) + digit(p[7]) + digit(p[8]))]}


class Swimming(_Table):
    contract = "SwimmingDetail"
    event = "Swimming"
    table = {1: _seq(5, "ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")
             + [(-1, "ClockTenthsSecond", lambda p: "0")]}


class Timer8601(_Table):
    """ScoreConnect checks ClockMode 'R'/'S' on a contract whose ClockMode is never set, so the hundredths
    branches never fire; reproduced as is."""

    contract = "Timer"
    event = "SingleTimer"

    def decode(self, p: bytes) -> None:
        c, n, a = self.c, p[1] + 5, p[0]
        try:
            if a == 1:
                _status(c, p, n)
            elif a == 12:
                _run(c, _MMSS + _at(20, "ClockTenthsSecond", guard=21), p, n)
                if c.get("ClockMode", " ") == "R":
                    c["ClockHundredths"] = " "
            elif a == 23:
                if c.get("ClockMode", " ") == "S" and n > 11:
                    c["ClockHundredths"] = digit(p[10])
        except IndexError:
            self.short += 1


class Waterpolo2000(_Table):
    contract = event = "WaterPolo"
    table = {
        1: _seq(5, "ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")
        + [(9, "ClockMode", lambda p: "." if p[8] == 0 else ":")]
        + _at(9, "ShotClockTens") + _at(10, "ShotClockOnes") + [_status],
        11: _score(9) + _at(13, "Period"),
    }
    for _a, _s in ((16, "Guest"), (15, "Home")):
        _rows = _seq(5, f"{_s}PenaltyPlayer1Tens", f"{_s}PenaltyPlayer1Ones")
        _rows += _const(" ", f"{_s}PenaltyPlayer1ClockMinutesTens", f"{_s}PenaltyPlayer1ClockMinutesOnes")
        _rows += _seq(7, f"{_s}PenaltyPlayer1ClockSecondTens", f"{_s}PenaltyPlayer1ClockSecondOnes")
        _rows += _const(" ", f"{_s}PenaltyPlayer2ClockMinutesTens", f"{_s}PenaltyPlayer2ClockMinutesOnes")
        _rows += _seq(10, f"{_s}PenaltyPlayer2Tens", f"{_s}PenaltyPlayer2Ones")
        _rows += _seq(12, f"{_s}PenaltyPlayer2ClockSecondTens", f"{_s}PenaltyPlayer2ClockSecondOnes")
        table[_a] = _rows


class Wrestling3000(_Table):
    contract = event = "Wrestling"
    table = {
        104: _at(17, "AdvantageTimeMinutesOnes") + _at(18, "AdvantageTimeSecondTens")
        + _at(19, "AdvantageTimeSecondOnes") + _at(5, "HomeMatchHundreds", guard=18)
        + _at(6, "HomeMatchTens", guard=19) + _at(7, "HomeMatchOnes", guard=20),
        14: _at(5, "HomeMatchScoreTens", guard=16) + _at(6, "HomeMatchScoreOnes", guard=16)
        + _at(14, "GuestMatchScoreTens", guard=17) + _at(15, "GuestMatchScoreOnes", guard=17),
        11: list(_MMSS) + _score(9) + [(14, "Period", lambda p: _dak3000_period(p[13]))],
        12: _flag(13, 4, "AdvantageHome", "*", guard=14) + _flag(13, 8, "AdvantageGuest", "*", guard=14),
    }

    def decode(self, p: bytes) -> None:
        self.c["ClockMode"] = ":"
        super().decode(p)


class Rodeo2000(Decoder):
    contract = event = "Rodeo"

    def __init__(self):
        super().__init__()
        self.short = 0

    def decode(self, p: bytes) -> None:
        c = self.c
        c["ClockMode"] = "."
        try:
            if p[0] == 11:
                rider = "".join(digit(p[i]) for i in range(5, 9))
                prev = c.get("PrevRiderNumber")
                c["RiderNumber"] = rider
                status = c.get("InternalClockStatus", " ")
                if status == "S" and rider != prev:
                    for f in ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes",
                              "ClockTenthsSecond", "ClockHundreths", "ClockMilliSeconds"):
                        c[f] = "0"
                if status == "R" and rider == prev:
                    c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
                    c["ClockSecondTens"], c["ClockSecondOnes"] = digit(p[9]), digit(p[10])
                    c["ClockTenthsSecond"], c["ClockHundreths"] = digit(p[11]), digit(p[12])
                    c["ClockMilliSeconds"] = "0"
            elif p[0] == 12:
                last = digit(p[12])
                c["InternalClockStatus"] = "R" if last == " " else "S"
                if c.get("ClockHundreths", " ") != " ":
                    c["ClockMilliSeconds"] = "0" if last == " " else last
                else:
                    c["ClockMilliSeconds"] = "0"
        except IndexError:
            self.short += 1
        if "RiderNumber" in c:
            c["PrevRiderNumber"] = c["RiderNumber"]


# --------------------------------------------------------------------------- registry
_DECODERS = {
    "Daktronics_Baseball": lambda: Baseball("Baseball"),
    "Daktronics_Softball": lambda: Baseball("Softball"),
    "Daktronics_Football": Football,
    "Daktronics_FootballCode6103": Football6103,
    "Daktronics_Basketball5500": Basketball5500,
    "Daktronics_BaseBall_Pitch_Speed": PitchSpeed,
    "Daktronics_Baseball_Pitch_Clock": PitchClock,
    "Daktronics_Basketball": Basketball,
    "Daktronics_Swimming": Swimming,
    "Daktronics_Hockey5000": lambda: Hockey5000("Hockey"),
    "Daktronics_Lacrosse5000": lambda: Hockey5000("Lacrosse"),
    "Daktronics_Wrestling3000": Wrestling3000,
    "Daktronics_Soccer": Soccer,
    "Daktronics_Volleyball": Volleyball,
    "Daktronics_Baseball1600": Baseball1600,
    "Daktronics_Rodeo2000": Rodeo2000,
    "Daktronics_Volleyball5500": Volleyball5500,
    "Daktronics_3000_Football": Football3000,
    "Daktronics_3000_Baseball": Baseball3000,
    "Daktronics_JvcPracticeFootball": JvcPracticeFootball,
    "Daktronics_Football1600": Football1600,
    "Daktronics_Basketball9122": Basketball9122,
    "Daktronics_Baseball5601": Baseball5601,
    "Daktronics_Timer8601": Timer8601,
    "Daktronics_Hockey5000Code4103": lambda: Hockey4103("Hockey"),
    "Daktronics_Lacrosse5000Code4103": lambda: Hockey4103("Lacrosse"),
    "Daktronics_Waterpolo2000": Waterpolo2000,
    "Daktronics_Hockey5000Code9405": Hockey9405,
}

# Sub-decoders autodetect may select (no 6103, 3000 baseball, pitch clock, water polo or 9405).
_AUTO_IDS = [k for k in _DECODERS if k not in (
    "Daktronics_FootballCode6103", "Daktronics_3000_Baseball", "Daktronics_Baseball_Pitch_Clock",
    "Daktronics_Waterpolo2000", "Daktronics_Hockey5000Code9405")]

# Console code (ASCII at address 0xFE, p[5..8]) -> vendor-sport id. ScoreConnect 1.3.0.21 lists soccer as
# 7701; the reference board in tests/test_current_loop.py sends 7601, which is not in the table, so it is never auto-detected.
DAK_CODES = {
    "1101": "Daktronics_Basketball", "1103": "Daktronics_Basketball", "6601": "Daktronics_Football",
    "4401": "Daktronics_Hockey5000", "4402": "Daktronics_Hockey5000", "2101": "Daktronics_Volleyball",
    "5501": "Daktronics_Baseball", "7701": "Daktronics_Soccer", "0003": "Daktronics_Baseball1600",
    "3101": "Daktronics_Wrestling3000", "3102": "Daktronics_Wrestling3000",
}


class Autodetect(Decoder):
    """Switches layout when the console code packet (address 0xFE) names a known sport.

    ``contract``, ``event`` and ``c`` follow the selected sub-decoder; a switch starts from a fresh contract.
    ``selected`` is the current vendor-sport id (or None) and ``on_detect`` an optional callback.
    """

    def __init__(self, on_detect=None):
        self._idle = {"EventId": "AutoDetect"}
        self._dec = None
        self.selected = None
        self.on_detect = on_detect
        self.short = 0

    @property
    def contract(self):
        return self._dec.contract if self._dec else "Generic"

    @property
    def event(self):
        return self._dec.event if self._dec else "AutoDetect"

    @property
    def c(self):
        return self._dec.c if self._dec else self._idle

    @c.setter
    def c(self, value):
        if self._dec:
            self._dec.c = value
        else:
            self._idle = value

    def reset(self) -> None:
        self._dec, self.selected, self._idle = None, None, {"EventId": "AutoDetect"}

    def decode(self, p: bytes) -> None:
        if p[0] == 0xFE:
            code = "".join(chr(b) for b in p[5:9])
            vid = DAK_CODES.get(code)
            if vid and vid != self.selected and vid in _AUTO_IDS:
                self.selected = vid
                self._dec = _DECODERS[vid]()
                if self.on_detect:
                    self.on_detect(vid)
        if self._dec:
            self._dec.decode(p)


def _make(factory):
    return lambda: ProtocolV3(factory())


PROTOCOLS = {pid: _make(f) for pid, f in _DECODERS.items()}
PROTOCOLS["Daktronics_Autodetect"] = lambda: ProtocolV3(Autodetect())
