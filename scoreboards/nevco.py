"""Nevco scoreboards, read through the ScoreLinkII/ScoreBot PIC in its Nevco decode mode.

The PIC decodes the console and forwards ``55 AA B7 L ... 01 payload checksum`` frames (see
:class:`scoreboards.pic55aa.Pic55AANevco`). The decoder receives ``L + 3`` bytes starting at frame byte 6, so
``packet[0]`` is frame byte 6, ``packet[1]`` is the constant ``01`` and ``packet[2 + k]`` is payload byte k.
Digits live in the odd (and some even) packet bytes, one nibble per display digit. Nibbles use plain BCD, or the
Nevco segment-code digit table (see :func:`_nevco_digit`) for periods.

Every decoder is table driven: ``rows`` maps contract fields to ``(field, packet index, function, *args)``.
Decoders keep their state between packets (like ScoreConnect), so fields a packet does not carry stay as they were.
Packets shorter than the highest index a decoder reads are ignored.
"""
from __future__ import annotations

from .base import Decoder
from .common import bcd, bcd_zero_blank, bit_count, mask_one_zero
from .pic55aa import Pic55AANevco

# --------------------------------------------------------------------------- private helpers
_NEVCO_DIGITS = {"0": "0", "1": "1", "2": "2", "4": "3", "8": "4", "9": "5", "A": "6", "C": "7", "D": "8", "E": "9"}


def _nevco_digit(b: int, i: int) -> str:
    """Nevco digit code in nibble i (0 = low, 1 = high): 0,1,2,4,8,9,A,C,D,E = 0-9; anything else blank."""
    return _NEVCO_DIGITS.get(f"{b & 0xFF:02X}"[1 - i], " ")


def _nevco_shotclock(b: int, i: int = 0) -> str:
    """Shot clock tens: only the low three bits of the byte are used; 7 means blank."""
    ch = f"{b & 7:02X}"[1 - i]
    return " " if ch in "7F" else ch


def _flag(b: int, mask: int, ch: str) -> str:
    return ch if b & mask else " "


def _bcd0(b: int, i: int) -> str:
    """BCD nibble where only "0" reads as blank (A-F stay as letters)."""
    return bcd(b, i, blank="0")


def _bcd_no_lead0(b: int, i: int) -> str:
    """BCD nibble (A-F blank) with a "0" also blanked."""
    ch = bcd(b, i)
    return " " if ch == "0" else ch


def _bcdm(b: int, i: int, mask: int) -> str:
    """BCD nibble of the masked byte (only "F" blank)."""
    return bcd(b, i, mask=mask)


def _play_clock_tens(b: int, mask: int = 0xFF) -> str:
    """Play clock tens: 7-9 (and A-F) never occur on a real play clock, so they read blank."""
    ch = bcd(b & mask, 0)
    return " " if ch >= "7" else ch


def _int(s: str) -> int:
    s = s.strip()
    return int(s) if s.isdigit() else 0


def _run_clock(c: dict, gate: str, mt: str, mo: str, st: str, so: str, tenths: str) -> None:
    """Minutes shown -> ``mm:ss`` with tenths 0; otherwise ``ss.t`` (minutes forced to 0)."""
    if _int(gate + mo) > 0:
        c.update(ClockMode=":", ClockMinutesTens=mt, ClockMinutesOnes=mo, ClockSecondTens=st, ClockSecondOnes=so,
                 ClockTenthsSecond="0")
    else:
        c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=st, ClockSecondOnes=so,
                 ClockTenthsSecond=tenths)


def _mpc_clock(c: dict, p: bytes) -> None:
    """MPC7/MPCX clock: seconds in byte 24, minutes in byte 26; blank high nibble of 24 = ``ss.t`` mode."""
    if bcd(p[24], 1) != " ":
        c.update(ClockMode=":", ClockMinutesTens=bcd(p[26], 0), ClockMinutesOnes=bcd(p[26], 1),
                 ClockSecondTens=bcd(p[24], 0), ClockSecondOnes=bcd(p[24], 1), ClockTenthsSecond="0")
    else:
        c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=bcd(p[26], 0),
                 ClockSecondOnes=bcd(p[26], 1), ClockTenthsSecond=bcd(p[24], 0))


def _innings(first: int, last: int) -> tuple:
    """Line-score rows for innings first..last: the guest runs are the high nibble and the home runs the low
    nibble of packet byte ``35 - 2 * inning``."""
    rows = []
    for n in range(first, last + 1):
        rows.append((f"GuestInning{n}", 35 - 2 * n, bcd, 1))
        rows.append((f"HomeInning{n}", 35 - 2 * n, bcd, 0))
    return tuple(rows)


# --------------------------------------------------------------------------- decoder base
class _NevcoDecoder(Decoder):
    rows: tuple = ()          # (field, packet index, function(byte, *args), *args)
    const: dict = {}          # fields set to a constant on every packet
    marker: tuple | None = None   # (index, value): packets whose byte differs are ignored
    reach = 0                 # highest packet index read by extra()

    def __init__(self):
        super().__init__()
        idx = [r[1] for r in self.rows] + [self.reach]
        if self.marker:
            idx.append(self.marker[0])
        self.need = max(idx) + 1  # shortest packet that can be decoded

    def decode(self, p: bytes) -> None:
        if len(p) < self.need:
            return
        if self.marker and p[self.marker[0]] != self.marker[1]:
            return
        c = self.c
        c.update(self.const)
        for field, n, fn, *args in self.rows:
            c[field] = fn(p[n], *args)
        self.extra(p)

    def extra(self, p: bytes) -> None:  # per-sport logic that does not fit the table
        pass


# --------------------------------------------------------------------------- football
_FOOTBALL_ROWS = (
    ("HomeScoreTens", 15, bcd, 0), ("HomeScoreOnes", 13, bcd_zero_blank, 0),
    ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd_zero_blank, 0),
    ("HomePossession", 29, _flag, 3, "<"), ("GuestPossession", 29, _flag, 0xC, ">"),
    ("BallOnTens", 5, bcd, 0), ("BallOnOnes", 3, bcd, 0),
    ("PlayClockTens", 4, _play_clock_tens), ("PlayClockOnes", 6, bcd, 0),
    ("Down", 7, bcd, 0), ("ToGoTens", 11, bcd, 0), ("ToGoOnes", 9, bcd, 0),
    ("Quarter", 27, bcd, 0), ("HomeTimeouts", 31, bcd, 1), ("GuestTimeouts", 33, bcd, 1),
)


class NevcoFootball(_NevcoDecoder):
    contract = "Football"
    event = "Football"
    rows = _FOOTBALL_ROWS
    reach = 32

    def extra(self, p):
        _run_clock(self.c, bcd(p[17], 0), bcd(p[17], 0), bcd(p[19], 0), bcd(p[21], 0), bcd(p[23], 0), bcd(p[32], 0))


class NevcoFootball827(_NevcoDecoder):
    contract = "Football"
    event = "Football"
    reach = 32
    rows = (
        ("HomeScoreTens", 15, bcd, 1), ("HomeScoreOnes", 13, bcd_zero_blank, 1),
        ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd_zero_blank, 0),
        ("HomePossession", 11, _flag, 2, "<"), ("GuestPossession", 11, _flag, 4, ">"),
        ("BallOnTens", 19, bcd, 1), ("BallOnOnes", 17, bcd, 1),
        ("PlayClockTens", 4, _play_clock_tens, 0xF7), ("PlayClockOnes", 6, bcd, 0),
        ("Down", 27, bcd, 1), ("ToGoTens", 33, bcd, 1), ("ToGoOnes", 31, bcd, 1),
        ("Quarter", 7, bcd, 0), ("HomeTimeouts", 25, bcd, 1), ("GuestTimeouts", 21, bcd, 1),
    )

    def extra(self, p):
        _run_clock(self.c, bcd(p[17], 0), bcd(p[17], 0), bcd(p[19], 0), bcd(p[21], 0), bcd(p[23], 0), bcd(p[32], 0))
        if p[11] & 0xF == 15:  # all lamps lit = no console data: no guest possession
            self.c["GuestPossession"] = " "


class _FootballMPC7(_NevcoDecoder):
    contract = "Football"
    event = "Football"
    reach = 26

    def extra(self, p):
        _mpc_clock(self.c, p)


_FOOTBALL_MPC7_COMMON = (
    ("HomeScoreTens", 8, bcd, 0), ("HomeScoreOnes", 8, bcd_zero_blank, 1),
    ("GuestScoreTens", 6, bcd, 0), ("GuestScoreOnes", 6, bcd_zero_blank, 1),
    ("HomePossession", 14, _flag, 4, "<"), ("GuestPossession", 14, _flag, 8, ">"), ("Flag", 14, _flag, 0x10, "F"),
    ("PlayClockTens", 16, bcd, 0), ("PlayClockOnes", 16, bcd, 1),
    ("Quarter", 33, bcd, 1), ("HomeTimeouts", 11, bcd, 0), ("GuestTimeouts", 11, bcd, 1),
)


class NevcoFootballMPC7(_FootballMPC7):
    rows = _FOOTBALL_MPC7_COMMON + (
        ("BallOnTens", 29, bcd, 0), ("BallOnOnes", 29, bcd, 1), ("Down", 4, bcd, 1),
        ("ToGoTens", 31, bcd, 0), ("ToGoOnes", 31, bcd, 1),
    )


class NevcoFootballMPC7Code1(_FootballMPC7):
    rows = _FOOTBALL_MPC7_COMMON + (
        ("BallOnTens", 4, bcd, 0), ("BallOnOnes", 4, bcd, 1), ("Down", 31, bcd, 0),
        ("ToGoTens", 29, bcd, 0), ("ToGoOnes", 29, bcd, 1),
    )


# --------------------------------------------------------------------------- basketball
class _NevcoBasketball(_NevcoDecoder):
    contract = "Basketball"
    event = "Basketball"
    reach = 33
    marker_value = None      # MPC7 variants only decode packets with this byte at index 34
    blank_zero_minutes = False
    gated_shot_clock = True
    bcd_score_ones = False   # Code 1 shows a leading zero in the score ones digit
    rows = ()
    _COMMON = (
        ("HomePossession", 25, _flag, 4, "<"), ("GuestPossession", 25, _flag, 8, ">"), ("Horn", 21, _flag, 8, "H"),
        ("HomeScoreHundreds", 29, _flag, 4, "1"), ("GuestScoreHundreds", 29, _flag, 8, "1"),
        ("HomeScoreTens", 15, bcd, 0), ("GuestScoreTens", 33, bcd, 0),
        ("HomeBonus", 17, _flag, 4, "B"), ("GuestBonus", 17, _flag, 8, "B"),
        ("Period", 27, _nevco_digit, 0),
    )

    def __init__(self):
        if self.marker_value is not None:
            self.marker = (34, self.marker_value)
        super().__init__()

    def decode(self, p):
        if len(p) < self.need or (self.marker and p[34] != self.marker[1]):
            return
        c = self.c
        ones = bcd if self.bcd_score_ones else bcd_zero_blank
        for field, n, fn, *args in self._COMMON + self.rows:
            c[field] = fn(p[n], *args)
        c["HomeScoreOnes"] = ones(p[13], 0)
        c["GuestScoreOnes"] = ones(p[31], 0)
        # minutes digit 1 is split over two bytes: bits 2-3 of byte 30 and bits 0-1 of byte 17
        d = (p[30] & 0xC) | (p[17] & 3)
        mt = _bcd0(d, 0) if self.blank_zero_minutes else bcd(d, 0)
        _run_clock(c, bcd(d, 0), mt, bcd(p[19], 0), _bcdm(p[21], 0, 7), bcd(p[23], 0), bcd(p[32], 0))
        if not self.gated_shot_clock or bcd(p[6], 0) != " ":
            c["ShotClockSecondTens"] = _nevco_shotclock(p[4])
            c["ShotClockSecondOnes"] = bcd(p[6], 0)
        else:
            c["ShotClockSecondTens"] = c["ShotClockSecondOnes"] = " "
        self.variant(p)

    def variant(self, p):
        pass


class NevcoBasketball(_NevcoBasketball):
    rows = (
        ("FoulPlayerTens", 5, bcd, 0), ("FoulPlayerOnes", 7, bcd, 0), ("FoulPlayerNumberOfFouls", 3, bcd, 0),
        ("HomeFoulTens", 29, _flag, 1, "1"), ("HomeFoulOnes", 11, bcd, 0),
        ("GuestFoulTens", 29, _flag, 2, "1"), ("GuestFoulOnes", 9, bcd, 0),
        ("GuestTimeouts", 26, bcd, 0), ("HomeTimeouts", 28, bcd, 0),
    )


class NevcoBasketball2745(_NevcoBasketball):
    rows = (
        ("FoulPlayerTens", 5, bcd, 0), ("FoulPlayerOnes", 7, bcd, 0), ("FoulPlayerNumberOfFouls", 3, bcd, 0),
        ("HomeFoulOnes", 11, bcd, 1), ("GuestFoulOnes", 31, bcd, 1),
        ("HomeTimeouts", 29, bcd, 1), ("GuestTimeouts", 23, bcd, 1),
    )


class NevcoBasketballMPC7(_NevcoBasketball):
    marker_value = 244
    blank_zero_minutes = True
    rows = (
        ("HomeDoubleBonus", 20, _flag, 4, "B"), ("GuestDoubleBonus", 20, _flag, 8, "B"),
        ("HomeFoulTens", 29, _flag, 1, "1"), ("HomeFoulOnes", 11, bcd, 0),
        ("GuestFoulTens", 29, _flag, 2, "1"), ("GuestFoulOnes", 9, bcd, 0),
        # byte 1 is the constant 01 of the PIC frame, so the number of fouls always reads "1" (as in ScoreConnect)
        ("FoulPlayerTens", 3, bcd, 0), ("FoulPlayerOnes", 5, bcd, 0), ("FoulPlayerNumberOfFouls", 1, bcd, 0),
        ("GuestTimeouts", 26, bcd, 0), ("HomeTimeouts", 28, bcd, 0),
    )


class NevcoBasketballMPC7Code1(_NevcoBasketball):
    marker_value = 244
    blank_zero_minutes = True
    gated_shot_clock = False
    bcd_score_ones = True
    rows = (
        ("HomeDoubleBonus", 20, _flag, 4, "B"), ("GuestDoubleBonus", 20, _flag, 8, "B"),
        ("HomeFoulTens", 29, _flag, 1, "1"), ("HomeFoulOnes", 11, bcd, 0),
        ("GuestFoulTens", 22, bcd, 0), ("GuestFoulOnes", 9, bcd, 0),
        ("FoulPlayerTens", 5, bcd, 0), ("FoulPlayerOnes", 7, bcd, 0), ("FoulPlayerNumberOfFouls", 3, bcd, 0),
        ("GuestTimeouts", 26, bcd, 0), ("HomeTimeouts", 28, bcd, 0),
    )


# --------------------------------------------------------------------------- hockey / lacrosse
class NevcoHockey(_NevcoDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    reach = 32
    const = {"HomeTimeOut": " ", "GuestTimeOut": " ", "HomePlayerPopUp": "  ", "GuestPlayerPopUp": "  "}
    rows = (
        ("ShotClockTens", 4, bcd, 0), ("ShotClockOnes", 6, bcd, 0),
        ("HomeScoreTens", 15, bcd, 0), ("HomeScoreOnes", 13, bcd_zero_blank, 0), ("HomeGoal", 17, _flag, 4, "*"),
        ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd_zero_blank, 0),
        ("HomeShotOnGoalTens", 16, bcd, 1), ("HomeShotOnGoalOnes", 14, bcd, 1),
        ("GuestShotOnGoalTens", 12, bcd, 1), ("GuestShotOnGoalOnes", 10, bcd, 1),
        ("Period", 27, bcd, 0), ("Horn", 21, _flag, 8, "H"),
        ("HomePenaltyPlayer1Tens", 9, bcd, 0), ("HomePenaltyPlayer1Ones", 7, bcd, 0),
        ("HomePenaltyPlayer1ClockMinutesTens", 11, mask_one_zero, 1), ("HomePenaltyPlayer1ClockMinutesOnes", 3, bcd, 1),
        ("HomePenaltyPlayer1ClockSecondTens", 5, bcd, 1), ("HomePenaltyPlayer1ClockSecondOnes", 7, bcd, 1),
        ("HomePenaltyPlayer2Tens", 29, bcd, 1), ("HomePenaltyPlayer2Ones", 27, bcd, 1),
        ("HomePenaltyPlayer2ClockMinutesTens", 11, mask_one_zero, 2), ("HomePenaltyPlayer2ClockMinutesOnes", 9, bcd, 1),
        ("HomePenaltyPlayer2ClockSecondTens", 11, bcd, 1), ("HomePenaltyPlayer2ClockSecondOnes", 13, bcd, 1),
        ("GuestPenaltyPlayer1Tens", 5, bcd, 0), ("GuestPenaltyPlayer1Ones", 3, bcd, 0),
        ("GuestPenaltyPlayer1ClockMinutesTens", 11, mask_one_zero, 4), ("GuestPenaltyPlayer1ClockMinutesOnes", 15, bcd, 1),
        ("GuestPenaltyPlayer1ClockSecondTens", 17, bcd, 1), ("GuestPenaltyPlayer1ClockSecondOnes", 19, bcd, 1),
        ("GuestPenaltyPlayer2Tens", 33, bcd, 1), ("GuestPenaltyPlayer2Ones", 31, bcd, 1),
        ("GuestPenaltyPlayer2ClockMinutesTens", 11, mask_one_zero, 8), ("GuestPenaltyPlayer2ClockMinutesOnes", 21, bcd, 1),
        ("GuestPenaltyPlayer2ClockSecondTens", 23, bcd, 1), ("GuestPenaltyPlayer2ClockSecondOnes", 25, bcd, 1),
    )

    def extra(self, p):
        c = self.c
        c.update(ClockMinutesTens=_bcdm(p[17], 0, 3), ClockMinutesOnes=bcd(p[19], 0), ClockSecondTens=_bcdm(p[21], 0, 7),
                 ClockSecondOnes=bcd(p[23], 0), ClockTenthsSecond=bcd(p[32], 0))
        c["ClockMode"] = "." if c["ClockMinutesTens"] == "0" and c["ClockMinutesOnes"] == "0" else ":"
        # the guest "goal" lamp shows the guest score ones digit (ScoreConnect behaviour)
        c["GuestGoal"] = bcd(p[31], 0) if p[17] & 8 else " "


class NevcoLacrosseMPC7(_NevcoDecoder):
    contract = "HockeyLacrosse"
    event = "Lacrosse"
    marker = (34, 112)
    reach = 26
    const = {f"{t}PenaltyPlayer3{f}": " " for t in ("Home", "Guest")
             for f in ("Tens", "Ones", "ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")}
    const.update({"HomePenaltyPlayer1ClockMinutesTens": " ", "HomePenaltyPlayer2ClockMinutesTens": " ",
                  "GuestPenaltyPlayer1ClockMinutesTens": " ", "GuestPenaltyPlayer2ClockMinutesTens": " "})
    rows = (
        ("HomePenaltyPlayer1Tens", 7, bcd, 0), ("HomePenaltyPlayer1Ones", 7, bcd, 1),
        ("HomePenaltyPlayer1ClockMinutesOnes", 15, bcd, 0),
        ("HomePenaltyPlayer1ClockSecondTens", 27, bcd, 0), ("HomePenaltyPlayer1ClockSecondOnes", 27, bcd, 1),
        ("HomePenaltyPlayer2Tens", 19, bcd, 0), ("HomePenaltyPlayer2Ones", 19, bcd, 1),
        ("HomePenaltyPlayer2ClockMinutesOnes", 15, bcd, 1),
        ("HomePenaltyPlayer2ClockSecondTens", 23, bcd, 0), ("HomePenaltyPlayer2ClockSecondOnes", 23, bcd, 1),
        ("GuestPenaltyPlayer1Tens", 5, bcd, 0), ("GuestPenaltyPlayer1Ones", 5, bcd, 1),
        ("GuestPenaltyPlayer1ClockMinutesOnes", 13, bcd, 0),
        ("GuestPenaltyPlayer1ClockSecondTens", 25, bcd, 0), ("GuestPenaltyPlayer1ClockSecondOnes", 25, bcd, 1),
        ("GuestPenaltyPlayer2Tens", 17, bcd, 0), ("GuestPenaltyPlayer2Ones", 17, bcd, 1),
        ("GuestPenaltyPlayer2ClockMinutesOnes", 13, bcd, 1),
        ("GuestPenaltyPlayer2ClockSecondTens", 21, bcd, 0), ("GuestPenaltyPlayer2ClockSecondOnes", 21, bcd, 1),
        ("Period", 10, bcd, 1), ("ShotClockTens", 16, bcd, 0), ("ShotClockOnes", 16, bcd, 1),
        ("HomeScoreTens", 8, bcd, 0), ("HomeScoreOnes", 8, bcd, 1),
        ("GuestScoreTens", 6, bcd, 0), ("GuestScoreOnes", 6, bcd, 1),
    )

    def extra(self, p):
        _mpc_clock(self.c, p)


# --------------------------------------------------------------------------- soccer
class NevcoSoccer(_NevcoDecoder):
    contract = "Soccer"
    event = "Soccer"
    const = {"ClockMode": ":", "ClockTenthsSecond": "0"}
    rows = (
        ("ClockMinutesTens", 17, bcd, 0), ("ClockMinutesOnes", 19, bcd, 0),
        ("ClockSecondTens", 21, bcd, 0), ("ClockSecondOnes", 23, bcd, 0),
        ("HomeScoreTens", 15, bcd, 0), ("HomeScoreOnes", 13, bcd_zero_blank, 0),
        ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd_zero_blank, 0),
        ("HomeShotTens", 5, bcd, 0), ("HomeShotOnes", 3, bcd_zero_blank, 0),
        ("GuestShotTens", 11, bcd, 0), ("GuestShotOnes", 9, bcd_zero_blank, 0),
        ("Period", 27, bcd, 0),
    )


class NevcoSoccer761(_NevcoDecoder):
    contract = "Soccer"
    event = "Soccer"
    const = {"ClockMode": ":", "ClockTenthsSecond": "0"}
    rows = (
        ("ClockMinutesTens", 17, bcd, 0), ("ClockMinutesOnes", 19, bcd, 0),
        ("ClockSecondTens", 21, bcd, 0), ("ClockSecondOnes", 23, bcd, 0),
        ("HomeScoreTens", 15, bcd, 1), ("HomeScoreOnes", 13, bcd_zero_blank, 1),
        ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd_zero_blank, 0),
        ("HomeShotTens", 33, bcd, 1), ("HomeShotOnes", 31, bcd_zero_blank, 1),
        ("GuestShotTens", 19, bcd, 1), ("GuestShotOnes", 17, bcd_zero_blank, 1),
        ("Period", 7, bcd, 0),
    )


class NevcoSoccerMPCX(_NevcoDecoder):
    contract = "Soccer"
    event = "Soccer"
    const = {"ClockMode": ":", "ClockTenthsSecond": "0"}
    rows = (
        ("ClockMinutesTens", 26, bcd, 0), ("ClockMinutesOnes", 26, bcd, 1),
        ("ClockSecondTens", 24, bcd, 0), ("ClockSecondOnes", 24, bcd, 1),
        ("HomeScoreTens", 8, bcd, 0), ("HomeScoreOnes", 8, bcd_zero_blank, 1),
        ("GuestScoreTens", 6, bcd, 0), ("GuestScoreOnes", 6, bcd_zero_blank, 1),
        ("HomeShotTens", 4, bcd, 0), ("HomeShotOnes", 4, bcd_zero_blank, 1),
        ("GuestShotTens", 33, bcd, 0), ("GuestShotOnes", 33, bcd_zero_blank, 1),
        ("Period", 10, bcd, 1),
    )


# --------------------------------------------------------------------------- volleyball
class NevcoVolleyball(_NevcoDecoder):
    contract = "Volleyball"
    event = "Volleyball"
    const = {"ClockMode": ":"}
    rows = (
        ("Game", 5, bcd, 0), ("HomeGamesWon", 11, bcd, 0), ("GuestGamesWon", 9, bcd_zero_blank, 0),
        ("HomeScoreTens", 15, bcd, 0), ("HomeScoreOnes", 13, bcd_zero_blank, 0),
        ("ClockMinutesOnes", 19, bcd, 0), ("ClockSecondTens", 21, _bcdm, 0, 7), ("ClockSecondOnes", 23, bcd, 0),
        ("HomeServe", 25, _flag, 4, "*"), ("GuestServe", 25, _flag, 8, "*"),
        ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd_zero_blank, 0),
    )

    def extra(self, p):
        t = _bcdm(p[17], 0, 3)
        self.c["ClockMinutesTens"] = " " if t == "0" else t


class NevcoVolleyballMPC7(_NevcoDecoder):
    contract = "Volleyball"
    event = "Volleyball"
    marker = (34, 4)
    reach = 32
    rows = (
        ("Set", 5, bcd, 0), ("Game", 5, bcd, 0),
        ("HomeScoreTens", 15, bcd, 0), ("HomeScoreOnes", 13, bcd, 0), ("HomeGamesWon", 11, bcd, 0),
        ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd, 0), ("GuestGamesWon", 9, bcd, 0),
        ("HomeTimeout", 28, bcd, 0), ("GuestTimeout", 26, bcd, 0),
        ("HomeServe", 25, _flag, 4, "*"), ("GuestServe", 25, _flag, 8, "*"),
    )

    def extra(self, p):
        _run_clock(self.c, bcd(p[17], 0), bcd(p[17], 0), bcd(p[19], 0), bcd(p[21], 0), bcd(p[23], 0), bcd(p[32], 0))


# --------------------------------------------------------------------------- wrestling
class NevcoWrestling(_NevcoDecoder):
    contract = "Wrestling"
    event = "Wrestling"
    const = {"ClockMode": ":", "ClockTenthsSecond": " "}
    rows = (
        ("ClockMinutesTens", 17, _bcd0, 0), ("ClockMinutesOnes", 19, bcd, 0),
        ("ClockSecondTens", 21, bcd, 0), ("ClockSecondOnes", 23, bcd, 0),
        ("HomeScoreTens", 15, bcd, 0), ("HomeScoreOnes", 13, bcd_zero_blank, 0),
        ("HomeMatchScoreTens", 29, mask_one_zero, 1), ("HomeMatchScoreOnes", 11, bcd_zero_blank, 0),
        ("GuestScoreTens", 33, bcd, 0), ("GuestScoreOnes", 31, bcd_zero_blank, 0),
        ("GuestMatchScoreTens", 29, mask_one_zero, 2), ("GuestMatchScoreOnes", 9, bcd_zero_blank, 0),
        ("Period", 27, _nevco_digit, 0),
    )
    reach = 25

    def extra(self, p):
        c = self.c
        if p[25] == 12:  # weight-class display
            c["WeightClass"] = bcd(p[3], 0) + bcd(p[5], 0) + bcd(p[7], 0)
        else:
            c.update(AdvantageTimeMinutesOnes=bcd(p[3], 0), AdvantageTimeSecondTens=bcd(p[5], 0),
                     AdvantageTimeSecondOnes=bcd(p[7], 0))
        if p[25] == 4:
            c.update(AdvantageHome="*", AdvantageGuest=" ")
        if p[25] == 8:
            c.update(AdvantageHome=" ", AdvantageGuest="*")


# --------------------------------------------------------------------------- baseball / softball
class _NevcoBaseball(_NevcoDecoder):
    contract = "BaseballSoftball"
    event = "Baseball"


def _set_half(c: dict, half: str) -> None:
    c["TopBottomInning"] = half
    c["TopOfInning"] = "." if half == "T" else " "
    c["BottomOfInning"] = "." if half == "B" else " "


class NevcoBaseball(_NevcoBaseball):
    const = {"GuestErrorNumber": " "}
    rows = (
        ("Balls", 28, bcd_zero_blank, 0), ("Strikes", 26, bcd_zero_blank, 0), ("Outs", 24, bcd_zero_blank, 0),
        ("InningTens", 18, bcd, 0), ("InningOnes", 16, bcd, 0),
        ("GuestRunTens", 13, _bcd_no_lead0, 1), ("GuestRunOnes", 11, bcd_zero_blank, 1),
        ("HomeRunTens", 13, _bcd_no_lead0, 0), ("HomeRunOnes", 11, bcd_zero_blank, 0),
        ("GuestHitsTens", 9, bcd, 1), ("GuestHitsOnes", 7, bcd, 1),
        ("HomeHitsTens", 9, bcd, 0), ("HomeHitsOnes", 7, bcd, 0),
        ("GuestErrors", 5, bcd, 0), ("HomeErrors", 5, bcd, 1),
        ("AtBatTens", 32, bcd, 0), ("AtBatOnes", 30, bcd, 0),
    ) + _innings(1, 10)
    reach = 22

    def extra(self, p):
        c = self.c
        c["ErrorFlag"] = {12: "E", 3: "H"}.get(p[22], " ")
        # bottom of the inning once the home line score for the current inning has a value
        inning = _int(c["InningTens"] + c["InningOnes"])
        half = "T"
        if 0 < inning < 11 and c.get(f"HomeInning{inning}", " ") != " ":
            half = "B"
        _set_half(c, half)


class NevcoBaseball252(_NevcoBaseball):
    const = {"InningTens": " "}
    rows = (
        ("Balls", 27, bit_count, "B"), ("Strikes", 29, bit_count, "S"), ("Outs", 25, bit_count, "O"),
        ("InningOnes", 19, bcd, 0),
        ("GuestRunTens", 33, bcd, 0), ("GuestRunOnes", 31, bcd, 0),
        ("HomeRunTens", 23, bcd, 0), ("HomeRunOnes", 21, bcd, 0),
    )


class NevcoBaseballMPCX706(_NevcoBaseball):
    marker = (4, 247)
    reach = 29
    const = {"TopBottomInning": " ", "TopOfInning": " ", "BottomOfInning": " ", "InningTens": " "}
    rows = (
        ("Balls", 7, bcd_zero_blank, 0), ("Strikes", 9, bcd_zero_blank, 0), ("Outs", 27, bcd_zero_blank, 0),
        ("InningOnes", 19, bcd, 0),
        ("GuestRunTens", 33, bcd, 0), ("GuestRunOnes", 31, bcd_zero_blank, 0),
        ("HomeRunTens", 15, bcd, 0), ("HomeRunOnes", 13, bcd_zero_blank, 0),
        ("AtBatTens", 5, bcd, 0), ("AtBatOnes", 3, bcd, 0),
    )

    def extra(self, p):
        self.c["ErrorFlag"] = {252: "E", 243: "H", 255: "H"}.get(p[29], " ")


class NevcoSimpleBaseball925(_NevcoBaseball):
    rows = (
        ("Balls", 25, bcd_zero_blank, 0), ("Strikes", 23, bcd_zero_blank, 0), ("Outs", 21, bcd_zero_blank, 0),
        ("InningTens", 19, bcd, 0), ("InningOnes", 17, bcd, 0),
        ("GuestRunTens", 33, bcd, 0), ("GuestRunOnes", 31, bcd_zero_blank, 0),
        ("HomeRunTens", 15, bcd, 0), ("HomeRunOnes", 13, bcd_zero_blank, 0),
        ("AtBatTens", 29, bcd, 0), ("AtBatOnes", 27, bcd, 0),
    )


class NevcoSimpleBaseball673(_NevcoBaseball):
    const = {"InningTens": " "}
    reach = 29
    rows = (
        ("Balls", 27, bit_count, "B"), ("Strikes", 29, bit_count, "S"),
        ("GuestRunTens", 33, bcd, 0), ("GuestRunOnes", 31, bcd, 0),
        ("HomeRunTens", 15, bcd, 0), ("HomeRunOnes", 13, bcd, 0),
    )

    def extra(self, p):
        # No half-inning lamp on this board: the half is inferred. Outs dropping while in the top means the
        # side changed (bottom); a new inning number means a new top.
        c = self.c
        outs = bit_count(p[25], "O")
        if _int(outs) < _int(c.get("Outs", " ")) and c.get("TopBottomInning") == "T":
            _set_half(c, "B")
        c["Outs"] = outs
        inning = bcd(p[11], 0)
        if c.get("InningOnes", " ") != inning:
            _set_half(c, "T")
        c["InningOnes"] = inning


class NevcoHandheldBaseball673(_NevcoBaseball):
    const = {"Balls": " ", "Strikes": " ", "TopBottomInning": " ", "TopOfInning": " ", "BottomOfInning": " ",
             "Outs": " ", "InningTens": " "}
    rows = (
        ("InningOnes", 27, bcd, 0),
        ("GuestRunTens", 33, bcd, 0), ("GuestRunOnes", 31, bcd, 0),
        ("HomeRunTens", 15, bcd, 0), ("HomeRunOnes", 13, bcd, 0),
    )


class NevcoSimpleBaseballMPC7(_NevcoBaseball):
    """Two alternating packet types, told apart by byte 34: 112 = main data, 120 = innings 7-10."""
    reach = 34

    _MAIN = (
        ("Balls", 31, bcd_zero_blank, 1), ("Strikes", 29, bcd_zero_blank, 1), ("Outs", 33, bcd_zero_blank, 1),
        ("InningTens", 14, _flag, 0x80, "1"), ("InningOnes", 10, bcd, 1),
        ("GuestRunTens", 6, bcd, 0), ("GuestRunOnes", 6, bcd_zero_blank, 1),
        ("HomeRunTens", 8, bcd, 0), ("HomeRunOnes", 8, bcd_zero_blank, 1),
        ("GuestHitsTens", 21, bcd, 0), ("GuestHitsOnes", 21, bcd, 1),
        ("HomeHitsTens", 23, bcd, 0), ("HomeHitsOnes", 23, bcd, 1),
        ("AtBatTens", 4, bcd, 0), ("AtBatOnes", 4, bcd, 1),
        ("HomeInning5", 5, bcd, 0), ("GuestInning6", 5, bcd, 1), ("HomeInning6", 7, bcd, 1),
        ("GuestInning4", 9, bcd, 1), ("HomeInning4", 9, bcd, 0), ("GuestInning5", 10, bcd, 0),
        ("GuestInning2", 13, bcd, 0), ("GuestInning3", 13, bcd, 1),
        ("HomeInning2", 15, bcd, 0), ("HomeInning3", 15, bcd, 1),
        ("GuestInning1", 17, bcd, 0), ("GuestErrors", 17, bcd, 1),
        ("HomeInning1", 19, bcd, 0), ("HomeErrors", 19, bcd, 1),
    )
    _LATE = (
        ("GuestInning9", 17, bcd, 0), ("GuestInning10", 17, bcd, 1), ("HomeInning9", 19, bcd, 0),
        ("HomeInning10", 19, bcd, 1), ("GuestInning7", 21, bcd, 0), ("GuestInning8", 21, bcd, 1),
        ("HomeInning7", 23, bcd, 0), ("HomeInning8", 23, bcd, 1),
    )

    def decode(self, p):
        if len(p) < self.need:
            return
        c = self.c
        if p[34] == 112:
            for field, n, fn, *args in self._MAIN:
                c[field] = fn(p[n], *args)
            # inning half from the lamp pattern in byte 18
            _set_half(c, {31: "T", 241: "B"}.get(p[18], " "))
        elif p[34] == 120:
            for field, n, fn, *args in self._LATE:
                c[field] = fn(p[n], *args)


# --------------------------------------------------------------------------- registry
_CLASSES = {
    "Baseball": NevcoBaseball,
    "Baseball_MPCX_Code706": NevcoBaseballMPCX706,
    "Baseball_MPCX_code_252": NevcoBaseball252,
    "Basketball": NevcoBasketball,
    "BasketballMPC7": NevcoBasketballMPC7,
    "BasketballMPC7_Code1": NevcoBasketballMPC7Code1,
    "Basketball_2745": NevcoBasketball2745,
    "Football": NevcoFootball,
    "FootballMPC7": NevcoFootballMPC7,
    "FootballMPC7_Code1": NevcoFootballMPC7Code1,
    "Football_Code827": NevcoFootball827,
    "HandheldBaseball_Code673": NevcoHandheldBaseball673,
    "Hockey": NevcoHockey,
    "HockeyMPC7": NevcoHockey,   # ScoreConnect registers the plain hockey decoder for MPC7 too
    "LacrosseMPC7": NevcoLacrosseMPC7,
    "SimpleBaseballMPC7": NevcoSimpleBaseballMPC7,
    "SimpleBaseball_Code673": NevcoSimpleBaseball673,
    "SimpleBaseball_Code925": NevcoSimpleBaseball925,
    "Soccer": NevcoSoccer,
    "SoccerMPCX": NevcoSoccerMPCX,
    "Soccer_Code761": NevcoSoccer761,
    "Volleyball": NevcoVolleyball,
    "VolleyballMPC7": NevcoVolleyballMPC7,
    "Wrestling": NevcoWrestling,
}


def _factory(cls):
    return lambda: Pic55AANevco(cls())


PROTOCOLS = {f"PIC55AA_Nevco_{name}": _factory(cls) for name, cls in _CLASSES.items()}
