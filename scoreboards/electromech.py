"""Electro-Mech (ElectroMech V2) scoreboards.

Wire format (2400 baud inverted current loop, or XBee at 57600): the console sends 2-byte "cells". The first
byte has bit 7 clear, the second has bit 7 set, so the second byte ends the cell::

    byte A: 0 d6 d5 d4 d3 d2 d1 d0
    byte B: 1 a4 a3 a2 a1 a0 flag d7        address = (B & 0x7C) >> 2, flag = B & 2

The cell value is ``d7 d6..d4 d3..d0`` = ``((B & 1) << 7) | (A & 0x70) | (A & 0x0F)``. There is no checksum;
the console re-sends cells continuously and only the cell address says what a value means.
Sport layouts are tables of ``address -> [(contract field, function(value, flag))]``.
"""
from __future__ import annotations

import re

from .base import Decoder, Protocol
from .common import bcd, blank_to_zero, blank_zero, digit

__all__ = ["ProtocolV2", "PROTOCOLS"]


# --------------------------------------------------------------------------- framing
class ProtocolV2(Protocol):
    """Yields ``(B, A)`` cells as 2-byte packets ``[B, A]`` (the byte with bit 7 set first)."""

    def extract(self):
        buf = self.buf
        while buf:
            end = next((i for i, b in enumerate(buf) if b & 0x80), -1)
            if end < 0:
                del buf[:-1]  # keep only the last byte: it may be the data half of a cell still arriving
                return
            if end == 0:  # a cell terminator with no data byte in front of it
                del buf[0]
                self.reject()
                continue
            pkt = bytes((buf[end], buf[end - 1]))
            del buf[: end + 1]
            yield pkt


# --------------------------------------------------------------------------- helpers
def _int(s: str) -> int:
    """Lenient integer parse: surrounding whitespace allowed, anything else non-numeric reads as 0."""
    return int(s) if re.fullmatch(r"\s*[+-]?[0-9]+\s*", s) else 0


def _hi(v, f):
    return bcd(v, 1)


def _lo(v, f):
    return bcd(v, 0)


def _hi_bz(v, f):  # high BCD digit with a leading zero blanked
    return blank_zero(bcd(v, 1), " ")


def _dg(v, f):
    return digit(v)


def _flag(ch):
    return lambda v, f: ch if f else " "


def _const(ch):
    return lambda v, f: ch


def _mod60(t: int, amount: int) -> int:
    t += amount
    return 0 if t < 0 or t > 59 else t


class _Clock:
    """Game clock built from separate minute and second cells.

    The console sends minutes and seconds in different cells, so at a rollover the board briefly shows an
    inconsistent time (for example 04:00 before the seconds cell says 59). While the clock is running this
    mirrors ScoreConnect: it compares with the previous reading and repairs the half-updated value before
    publishing it.
    """

    def __init__(self):
        self.ch = ["\0"] * 6  # [mode, min tens, min ones, sec tens, sec ones, tenths]
        self.prev_min = 0
        self.prev_sec = 0     # seconds*10 in ':' mode, whole seconds in '.' mode
        self.prev_tenth = 0
        self.running = False
        self.running_cnt = 0
        self.prev_text = " 00000"

    def set_mode(self, colon: bool) -> None:
        self.ch[0] = ":" if colon else "."

    def minutes(self, v: int, out: dict) -> None:
        ch = self.ch
        if ch[0] == ":":
            ch[1], ch[2] = bcd(v, 1), bcd(v, 0)
        elif ch[0] == ".":
            ch[1] = ch[2] = "0"
            ch[3], ch[4] = bcd(v, 1), bcd(v, 0)
        else:
            return
        self._correlate(out)

    def seconds(self, v: int, out: dict) -> None:
        ch = self.ch
        if ch[0] == ":":
            ch[3], ch[4], ch[5] = bcd(v, 1), bcd(v, 0), "0"
        elif ch[0] == ".":
            ch[5] = bcd(v, 1)
        else:
            return
        self._correlate(out)

    def _correlate(self, out: dict) -> None:
        ch = self.ch
        text = "".join(ch)
        if self.running:
            if ch[0] == ":":
                self._fix_minutes()
            elif ch[0] == ".":
                self._fix_tenths()
        diff = abs(_int(text[1:]) - _int(self.prev_text[1:]))
        if diff in (1, 10):
            self.running, self.running_cnt = True, 2
        elif self.running_cnt > 0:
            self.running_cnt -= 1
        else:
            self.running = False
        if text != self.prev_text:
            self._publish(out)
        self.prev_text = text

    def _fix_minutes(self) -> None:
        ch = self.ch
        sec = _int(ch[3] + ch[4] + "0")
        mins = _int(ch[1] + ch[2])
        fixed = False
        if self.prev_min - mins == 1 and self.prev_sec == sec:
            ch[3], ch[4], fixed = "5", "9", True
        if self.prev_min - mins == -1 and self.prev_sec == sec and not fixed:
            ch[3], ch[4], fixed = "0", "0", True
        if self.prev_sec == 0 and sec == 590 and not fixed and mins != self.prev_min - 1:
            ch[1], ch[2] = f"{max(mins - 1, 0):02d}"
            fixed = True
        if self.prev_sec == 590 and sec == 0 and not fixed and mins != self.prev_min + 1:
            ch[1], ch[2] = f"{min(mins + 1, 99):02d}"
            fixed = True
        if fixed:
            sec, mins = _int(ch[3] + ch[4] + "0"), _int(ch[1] + ch[2])
        self.prev_sec, self.prev_min, self.prev_tenth = sec, mins, 0

    def _fix_tenths(self) -> None:
        ch = self.ch
        ch[1] = ch[2] = "0"
        tenth = _int(ch[5])
        sec = _int(ch[3] + ch[4])
        fixed = False
        if self.prev_tenth == tenth == 0:
            sec = _mod60(self.prev_sec, -1)
            ch[3], ch[4] = f"{sec:02d}"
            ch[5] = "9"
            fixed = True
        else:
            if self.prev_tenth == 0 and tenth == 9 and sec != _mod60(self.prev_sec, -1):
                sec = _mod60(self.prev_sec, -1)
                ch[3], ch[4] = f"{sec:02d}"
                fixed = True
            if self.prev_tenth == 9 and tenth == 0 and sec != _mod60(self.prev_sec, 1):
                sec = _mod60(self.prev_sec, 1)
                ch[3], ch[4] = f"{sec:02d}"
                fixed = True
        if fixed:
            sec, tenth = _int(ch[3] + ch[4]), _int(ch[5])
        self.prev_sec, self.prev_tenth = sec, tenth

    def _publish(self, out: dict) -> None:
        ch = self.ch
        if ch[0] == ":":
            out.update(ClockMode=":", ClockMinutesTens=blank_zero(ch[1], " "), ClockMinutesOnes=ch[2],
                       ClockSecondTens=ch[3], ClockSecondOnes=ch[4], ClockTenthsSecond="0")
        else:
            out.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0",
                       ClockSecondTens=blank_zero(ch[3], " "), ClockSecondOnes=ch[4], ClockTenthsSecond=ch[5])


# --------------------------------------------------------------------------- decoder base
class _Cells(Decoder):
    """Decodes one cell. ``TABLE`` maps address -> list of (field, fn(value, flag)) or a handler(self, v, flag)."""

    TABLE: dict = {}

    def decode(self, packet: bytes) -> None:
        if len(packet) < 2:
            return
        addr = (packet[0] & 0x7C) >> 2
        flag = packet[0] & 2
        low = packet[1] & 0x0F
        v = ((packet[0] & 1) << 7) | (packet[1] & 0x70) | low
        entry = self.TABLE.get(addr)
        if entry is None:
            return
        if callable(entry):
            entry(self, v, flag)
        else:
            for field, fn in entry:
                self.c[field] = fn(v, flag)


class _ClockedCells(_Cells):
    """Sports whose clock goes through the correlating _Clock."""

    def __init__(self):
        super().__init__()
        self.clock = _Clock()

    def reset(self) -> None:
        super().reset()
        self.clock = _Clock()


def _period_cell(field):
    def handler(self, v, f):
        if field:
            self.c[field] = digit(v)
        self.clock.set_mode(bool(f))
    return handler


def _min_cell(self, v, f):
    self.clock.minutes(v, self.c)


def _sec_cell(self, v, f):
    self.clock.seconds(v, self.c)


def _lx_sec_cell(self, v, f):  # LX layout: the seconds cell also carries the mode in its low nibble
    self.clock.set_mode(bcd(v, 0) != " ")
    self.clock.seconds(v, self.c)


# --------------------------------------------------------------------------- football
def _fb_home_score(self, v, f):
    self.c["HomeScoreTens"], self.c["HomeScoreOnes"] = blank_zero(bcd(v, 1), " "), bcd(v, 0)
    self.c["HomePossession"] = "<" if f else " "
    if f:
        self.c["GuestPossession"] = " "


def _fb_guest_score(self, v, f):
    self.c["GuestScoreTens"], self.c["GuestScoreOnes"] = blank_zero(bcd(v, 1), " "), bcd(v, 0)
    self.c["GuestPossession"] = ">" if f else " "
    if f:
        self.c["HomePossession"] = " "


class FootballDecoder(_ClockedCells):
    contract = "Football"
    event = "Football"
    TABLE = {
        1: _min_cell, 0: _sec_cell, 2: _period_cell("Quarter"),
        8: _fb_home_score, 9: _fb_guest_score,
        16: [("GuestTimeouts", _hi), ("HomeTimeouts", _lo)],
        12: [("ToGoTens", _hi_bz), ("ToGoOnes", _lo)],
        13: [("BallOnTens", _hi_bz), ("BallOnOnes", _lo)],
        14: [("Down", _dg)],
    }


# --------------------------------------------------------------------------- basketball
def _basketball_table(swap: bool) -> dict:
    """Layout for the console's 'first' team (Home normally, Guest when swapped) and 'second' team."""
    a, b = ("Guest", "Home") if swap else ("Home", "Guest")
    arrow = {"Home": "<", "Guest": ">"}

    def score(team):
        def handler(self, v, f):
            hundreds = "1" if f else " "
            self.c[team + "ScoreHundreds"] = hundreds
            self.c[team + "ScoreTens"] = blank_zero(bcd(v, 1), hundreds)
            self.c[team + "ScoreOnes"] = bcd(v, 0)
        return handler

    def bits(self, v, f):
        d = v & 0x0F
        self.c[a + "Possession"] = arrow[a] if d & 1 else " "
        self.c[b + "Possession"] = arrow[b] if d & 2 else " "
        self.c[a + "Bonus"] = "B" if d & 4 else " "
        self.c[b + "Bonus"] = "B" if d & 8 else " "

    return {
        1: _min_cell, 0: _sec_cell, 2: _period_cell("Period"),
        4: [("ShotClockSecondTens", _hi), ("ShotClockSecondOnes", _lo)],
        8: score(a), 9: score(b),
        15: [(a + "Timeouts", _dg)], 11: [(b + "Timeouts", _dg)],
        10: bits,
        12: [(a + "FoulTens", _flag("1")), (a + "FoulOnes", _lo), (b + "FoulOnes", _hi)],
        13: [(b + "FoulTens", _flag("1")), ("FoulPlayerTens", _hi), ("FoulPlayerOnes", _lo)],
        14: [("FoulPlayerNumberOfFouls", _dg)],
    }


class BasketballDecoder(_ClockedCells):
    contract = "Basketball"
    event = "Basketball"
    TABLE = _basketball_table(False)


class BasketballDecoderSwappedTeams(_ClockedCells):
    """Same cells with the two teams exchanged *inside* the decoder (ScoreConnect has no generic swap here)."""

    contract = "Basketball"
    event = "Basketball"
    TABLE = _basketball_table(True)


# --------------------------------------------------------------------------- soccer
class SoccerDecoder(_ClockedCells):
    contract = "Soccer"
    event = "Soccer"
    TABLE = {
        1: _min_cell, 0: _sec_cell, 2: _period_cell("Period"),
        4: [("ClockSecondTens", _hi), ("ClockSecondOnes", _lo)],
        8: [("HomeScoreTens", _hi_bz), ("HomeScoreOnes", _lo)],
        9: [("GuestScoreTens", _hi_bz), ("GuestScoreOnes", _lo)],
        12: [("HomeShotTens", _hi_bz), ("HomeShotOnes", _lo)],
        13: [("GuestShotTens", _hi_bz), ("GuestShotOnes", _lo)],
    }


class LxSoccerDecoder(_ClockedCells):
    contract = "Soccer"
    event = "Soccer"
    TABLE = {
        20: _min_cell, 21: _lx_sec_cell,
        31: [("Period", _dg)],
        25: [("HomeScoreTens", _hi_bz), ("HomeScoreOnes", _lo)],
        24: [("GuestScoreTens", _hi_bz), ("GuestScoreOnes", _lo)],
    }


# --------------------------------------------------------------------------- direct (uncorrelated) clocks
def _direct_min(self, v, f):
    c = self.c
    if c.get("ClockMode") == ".":
        c["ClockMinutesTens"], c["ClockMinutesOnes"] = "0", "0"
        c["ClockSecondTens"], c["ClockSecondOnes"] = bcd(v, 1), bcd(v, 0)
    else:
        c["ClockMinutesTens"], c["ClockMinutesOnes"] = bcd(v, 1), bcd(v, 0)
        if self.zero_tenths_on_minutes:
            c["ClockTenthsSecond"] = "0"


def _direct_sec(self, v, f):
    c = self.c
    if c.get("ClockMode") == ".":
        c["ClockTenthsSecond"] = bcd(v, 1)
    else:
        c["ClockSecondTens"], c["ClockSecondOnes"] = bcd(v, 1), bcd(v, 0)
        if self.zero_tenths_on_seconds:
            c["ClockTenthsSecond"] = "0"


def _pen_cells(side, n, sec_goal=None, min_goal=None):
    """Hockey penalty slot: (seconds cell, minutes+player-ones cell), each optionally carrying a goal lamp."""
    p = f"{side}PenaltyPlayer{n}"

    def secs(self, v, f):
        self.c[p + "ClockSecondTens"], self.c[p + "ClockSecondOnes"] = bcd(v, 1), bcd(v, 0)
        if sec_goal:
            self.c[sec_goal] = "G" if f else " "

    def mins(self, v, f):
        self.c[p + "ClockMinutesTens"] = " "
        self.c[p + "ClockMinutesOnes"], self.c[p + "Ones"] = bcd(v, 0), bcd(v, 1)
        if min_goal:
            self.c[min_goal] = "G" if f else " "

    return secs, mins


class HockeyDecoder(_Cells):
    contract = "HockeyLacrosse"
    event = "Hockey"
    zero_tenths_on_minutes = False
    zero_tenths_on_seconds = True

    def _period(self, v, f):
        self.c["Period"] = digit(v)
        self.c["ClockMode"] = ":" if f else "."

    TABLE = {
        1: _direct_min, 0: _direct_sec, 2: _period,
        4: [("ShotClockTens", _hi), ("ShotClockOnes", _lo)],
        8: [("HomeScoreTens", _hi), ("HomeScoreOnes", _lo)],
        9: [("GuestScoreTens", _hi), ("GuestScoreOnes", _lo)],
        11: [("GuestShotOnGoalTens", _dg)], 10: [("GuestShotOnGoalOnes", _dg)],
        15: [("HomeShotOnGoalTens", _dg)], 3: [("HomeShotOnGoalOnes", _dg)],
        14: [("GuestPenaltyPlayer1Tens", _dg)],
        18: [("GuestPenaltyPlayer2Tens", _dg)],
        26: [("HomePenaltyPlayer1Tens", _dg)],
        30: [("HomePenaltyPlayer2Tens", _dg)],
    }
    TABLE[12], TABLE[13] = _pen_cells("Guest", 1)
    # Quirk kept from ScoreConnect: the goal lamps ride on the guest slot-2 cells (home lamp on 16, guest on 17).
    TABLE[16], TABLE[17] = _pen_cells("Guest", 2, "HomeGoal", "GuestGoal")
    TABLE[24], TABLE[25] = _pen_cells("Home", 1)
    TABLE[28], TABLE[29] = _pen_cells("Home", 2)


class VolleyballDecoder(_Cells):
    contract = "Volleyball"
    event = "Volleyball"
    zero_tenths_on_minutes = True
    zero_tenths_on_seconds = False

    def _mode(self, v, f):
        self.c["ClockMode"] = ":" if f else "."

    TABLE = {
        1: _direct_min, 0: _direct_sec, 2: _mode,
        8: [("HomeScoreTens", _hi_bz), ("HomeScoreOnes", _lo)],
        9: [("GuestScoreTens", _hi_bz), ("GuestScoreOnes", _lo)],
        15: [("HomeTimeout", _dg)], 11: [("GuestTimeout", _dg)],
        12: [("HomeGamesWon", _lo), ("GuestGamesWon", _hi)],
        13: [("Game", _lo)],
    }


def _lx_slot(side, n, player, sec, mins, minutes_blank=True):
    p = f"{side}PenaltyPlayer{n}"
    return {
        player: [(p + "Tens", _hi), (p + "Ones", _lo)],
        sec: [(p + "ClockSecondTens", _hi), (p + "ClockSecondOnes", _lo)],
        mins: ([(p + "ClockMinutesTens", _const(" ")), (p + "ClockMinutesOnes", _dg)] if minutes_blank
               else [(p + "ClockMinutesTens", _hi), (p + "ClockMinutesOnes", _lo)]),
    }


def _lx_clock_sec(self, v, f):
    c = self.c
    c["ClockMode"] = ":" if bcd(v, 0) != " " else "."
    if c["ClockMode"] == ".":
        c["ClockTenthsSecond"] = bcd(v, 1)
    else:
        c["ClockSecondTens"], c["ClockSecondOnes"] = bcd(v, 1), bcd(v, 0)
        c["ClockTenthsSecond"] = "0"


class LxHockeyLacrosseDecoder(_Cells):
    contract = "HockeyLacrosse"
    zero_tenths_on_minutes = False

    def __init__(self, event: str = "Hockey"):
        self.event = event
        super().__init__()

    TABLE = {
        26: [("HomePenaltyPlayer2Tens", _dg)],
        27: [("HomePenaltyPlayer2Ones", _dg)],
        3: [("HomePenaltyPlayer2ClockSecondTens", _dg)],
        11: [("HomePenaltyPlayer2ClockSecondOnes", _dg)],
        15: [("HomePenaltyPlayer2ClockMinutesTens", _const(" ")), ("HomePenaltyPlayer2ClockMinutesOnes", _dg)],
        16: [("HomeShotOnGoalTens", _hi), ("HomeShotOnGoalOnes", _lo), ("HomeGoal", _flag("G"))],
        17: [("GuestShotOnGoalTens", _hi), ("GuestShotOnGoalOnes", _lo), ("GuestGoal", _flag("G"))],
        4: [("ShotClockTens", _hi), ("ShotClockOnes", _lo)],
        20: _direct_min, 21: _lx_clock_sec,
        31: [("Period", _dg)],
        24: [("HomeScoreTens", _hi_bz), ("HomeScoreOnes", _lo)],
        25: [("GuestScoreTens", _hi_bz), ("GuestScoreOnes", _lo)],
    }
    TABLE.update(_lx_slot("Guest", 1, 0, 1, 2))
    TABLE.update(_lx_slot("Guest", 2, 12, 13, 14))
    TABLE.update(_lx_slot("Home", 1, 8, 9, 10, minutes_blank=False))


# --------------------------------------------------------------------------- baseball / softball
class _BaseballCells(_Cells):
    contract = "BaseballSoftball"

    def __init__(self, event: str = "Baseball"):
        self.event = event
        super().__init__()

    # helpers shared by several layouts
    def _balls_strikes(self, v, f):
        self.c["Balls"] = blank_to_zero(bcd(v, 0))
        self.c["Strikes"] = blank_to_zero(bcd(v, 1))

    def _home_runs(self, v, f):
        self.c["HomeRunTens"], self.c["HomeRunOnes"] = blank_zero(bcd(v, 1), " "), bcd(v, 0)
        self.c["InningTens"] = " "

    def _guest_runs(self, v, f):
        self.c["GuestRunTens"], self.c["GuestRunOnes"] = blank_zero(bcd(v, 1), " "), bcd(v, 0)
        self.c["ErrorFlag"] = "E" if f else " "

    def _inning_top(self, v, f):
        if self.c.get("InningOnes", " ") != digit(v):
            self.c["TopBottomInning"] = "T"
        self.c["InningOnes"] = digit(v)

    def _outs_bcd(self, v, f):
        # an out count that drops while the half-inning is 'T' means the inning flipped to the bottom
        if _int(bcd(v, 0)) < _int(self.c.get("Outs", " ")) and self.c.get("TopBottomInning") == "T":
            self.c["TopBottomInning"] = "B"
        self.c["Outs"] = blank_to_zero(bcd(v, 0))


class BaseballSoftballDecoder(_BaseballCells):
    TABLE = {
        4: _BaseballCells._home_runs, 5: _BaseballCells._guest_runs, 6: _BaseballCells._inning_top,
        12: _BaseballCells._balls_strikes, 13: _BaseballCells._outs_bcd,
    }


class LxBaseballSoftballDecoder(_BaseballCells):
    TABLE = {
        8: _BaseballCells._home_runs, 9: _BaseballCells._guest_runs, 10: _BaseballCells._inning_top,
        12: _BaseballCells._balls_strikes, 13: _BaseballCells._outs_bcd,
    }


def _x14_outs(self, v, f):
    if _int(digit(v)) < _int(self.c.get("Outs", " ")) and self.c.get("TopBottomInning") == "T":
        self.c.update(TopBottomInning="B", TopOfInning=" ", BottomOfInning=".")
    self.c["Outs"] = blank_to_zero(digit(v))


def _x14_inning(self, v, f):
    new = _int(bcd(v, 1) + bcd(v, 0))
    if new > _int(self.c.get("InningTens", " ") + self.c.get("InningOnes", " ")):
        self.c.update(TopBottomInning="T", TopOfInning=".", BottomOfInning=" ")
    self.c["InningTens"], self.c["InningOnes"] = bcd(v, 1), bcd(v, 0)


class BaseballSoftball14X15XDecoder(_BaseballCells):
    TABLE = {
        12: [("HomeRunTens", _hi_bz), ("HomeRunOnes", _lo)],
        13: [("HomeHitsTens", _hi_bz), ("HomeHitsOnes", _lo)],
        8: [("GuestRunTens", _hi_bz), ("GuestRunOnes", _lo)],
        9: [("GuestHitsTens", _hi_bz), ("GuestHitsOnes", _lo)],
        10: [("GuestErrors", _dg)], 14: [("HomeErrors", _dg)],
        5: _BaseballCells._balls_strikes, 6: _x14_outs, 16: _x14_inning,
        4: [("AtBatTens", _hi), ("AtBatOnes", _lo)],
    }


def _ls_inning(self, v, f):
    self.c["InningOnes"] = digit(v)
    self.c["InningTens"] = "1" if v & 0x80 else " "


def _ls_half(top: bool):
    def handler(self, v, f):
        if v & 0x80:
            if top:
                self.c.update(TopBottomInning="T", TopOfInning=".", BottomOfInning=" ")
            else:
                self.c.update(TopBottomInning="B", TopOfInning=" ", BottomOfInning=".")
    return handler


def _ls_line(side, first):
    """Two-inning-per-cell BCD line score cells: low nibble = first inning, high nibble = next."""
    def handler(self, v, f):
        self.c[f"{side}Inning{first}"] = bcd(v, 0)
        self.c[f"{side}Inning{first + 1}"] = bcd(v, 1)
    return handler


def _ls_single(side, n):
    return [(f"{side}Inning{n}", _dg)]


class LineScoreBaseballDecoder(_BaseballCells):
    def __init__(self):
        super().__init__("Baseball")

    TABLE = {
        0: [("HomeRunTens", _hi_bz), ("HomeRunOnes", _lo)],
        1: [("HomeHitsTens", _hi_bz), ("HomeHitsOnes", _lo)],
        2: _ls_inning,
        3: [("HomeErrors", _dg)],
        4: [("AtBatTens", _hi), ("AtBatOnes", _lo)],
        5: _BaseballCells._balls_strikes,
        6: [("Outs", lambda v, f: blank_to_zero(digit(v)))],
        7: [("GuestErrors", _dg)],
        14: _ls_half(True), 15: _ls_half(False),
        16: [("GuestRunTens", _hi), ("GuestRunOnes", _lo)],
        17: [("GuestHitsTens", _hi), ("GuestHitsOnes", _lo)],
        19: [("GuestErrors", _dg)],
    }
    for _side, _base in (("Home", 8), ("Guest", 24)):
        TABLE[_base] = _ls_line(_side, 1)
        TABLE[_base + 1] = _ls_line(_side, 3)
        TABLE[_base + 2] = _ls_single(_side, 5)
        TABLE[_base + 3] = _ls_single(_side, 6)
        TABLE[_base + 4] = _ls_line(_side, 7)
        TABLE[_base + 5] = _ls_line(_side, 9)
    del _side, _base


# --------------------------------------------------------------------------- registry
PROTOCOLS = {
    "Electromech_Football": lambda: ProtocolV2(FootballDecoder()),
    "Electromech_LineScoreBaseball": lambda: ProtocolV2(LineScoreBaseballDecoder()),
    "Electromech_Hockey": lambda: ProtocolV2(HockeyDecoder()),
    "Electromech_Volleyball": lambda: ProtocolV2(VolleyballDecoder()),
    "Electromech_Baseball": lambda: ProtocolV2(BaseballSoftballDecoder("Baseball")),
    "Electromech_Softball": lambda: ProtocolV2(BaseballSoftballDecoder("Softball")),
    "Electromech_LxBaseball": lambda: ProtocolV2(LxBaseballSoftballDecoder("Baseball")),
    "Electromech_BaseballSoftball14x15x": lambda: ProtocolV2(BaseballSoftball14X15XDecoder("Baseball")),
    "Electromech_Basketball": lambda: ProtocolV2(BasketballDecoder()),
    "Electromech_Basketball_SwappedTeams": lambda: ProtocolV2(BasketballDecoderSwappedTeams()),
    "Electromech_LxHockey": lambda: ProtocolV2(LxHockeyLacrosseDecoder("Hockey")),
    "Electromech_LxLacrosse": lambda: ProtocolV2(LxHockeyLacrosseDecoder("Lacrosse")),
    "Electromech_Soccer": lambda: ProtocolV2(SoccerDecoder()),
    "Electromech_LxSoccer": lambda: ProtocolV2(LxSoccerDecoder()),
}
