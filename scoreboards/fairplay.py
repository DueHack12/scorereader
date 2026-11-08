"""Fair-Play scoreboards on the plain RS-485 "no decode" wiring (ScoreConnect namespace Fairplay.Main).

Wire format (one packet)::

    code  type  ??  L  data[L]  sum_lo  sum_hi        (L + 6 bytes)

``code`` is the console's sport code (the catalog's ``vendor_sport_code``; every id here searches the
stream for its own code byte), ``type`` selects the sub-packet (0x81 main scoreboard, 0xC1 shot/play clock,
0xB1 home players, 0xB4 guest players), ``L`` is the number of data bytes, and the trailer is the 16-bit
little-endian sum of every byte before it. Data bytes start at packet offset 4 and are mostly packed BCD.
See docs/vendors/fairplay.md for the field tables.
"""
from __future__ import annotations

from .base import Decoder, Protocol
from .common import bcd, digit

__all__ = ["PROTOCOLS", "FairplayProtocol"]

T_MAIN, T_CLOCK2, T_HOME_PLAYERS, T_GUEST_PLAYERS = 0x81, 0xC1, 0xB1, 0xB4


# --------------------------------------------------------------------------- private helpers
def _fairplay_abc(b: int, pos: int) -> str:
    """Ball/strike/out lamp: hex character at position pos (0 = high nibble) of the byte; A, B, C -> 1, 2, 3."""
    return {"A": "1", "B": "2", "C": "3"}.get(f"{b:02X}"[pos], " ")


def _fairplay_outs(b: int) -> str:
    """Outs lamp pattern used by code 35: 0xBF = 0, 0x86 = 1, 0xDB = 2."""
    return {0xBF: "0", 0x86: "1", 0xDB: "2"}.get(b, " ")


def _hi(i):
    return lambda p: bcd(p[i], 1)


def _lo(i):
    return lambda p: bcd(p[i], 0)


def _two(i):
    return lambda p: bcd(p[i], 1) + bcd(p[i], 0)


def _flag(i, mask, ch, *, exact=False, off=" "):
    if exact:
        return lambda p: ch if (p[i] & mask) == mask else off
    return lambda p: ch if p[i] & mask else off


def _abc(i, pos):
    return lambda p: _fairplay_abc(p[i], pos)


def _set(field, getter):
    def rule(c, p):
        c[field] = getter(p)

    return rule


def _rules(*pairs):
    return [_set(f, g) for f, g in pairs]


def _digits(prefix, i, *, tens="Tens", ones="Ones"):
    return _rules((prefix + tens, _hi(i)), (prefix + ones, _lo(i)))


def _clock(c, p):
    """Game clock: minutes:seconds, or seconds.tenths when the low nibble of byte 5 is blank."""
    s = bcd(p[5], 0)
    if s != " ":
        c["ClockMode"] = ":"
        c["ClockMinutesTens"], c["ClockMinutesOnes"] = bcd(p[4], 1), bcd(p[4], 0)
        c["ClockSecondTens"], c["ClockSecondOnes"] = bcd(p[5], 1), s
        c["ClockTenthsSecond"] = "0"
    else:
        c["ClockMode"] = "."
        c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
        c["ClockSecondTens"], c["ClockSecondOnes"] = bcd(p[4], 1), bcd(p[4], 0)
        c["ClockTenthsSecond"] = bcd(p[5], 1)


def _top_bottom(c, which):
    top = which == "T"
    c["TopBottomInning"] = which
    c["TopOfInning"] = "." if top else " "
    c["BottomOfInning"] = " " if top else "."


# --------------------------------------------------------------------------- decoder base
class _FairplayDecoder(Decoder):
    layouts: dict = {}   # packet type -> [rule(c, p)]
    always: list = []    # rules run for every packet, whatever its type

    def decode(self, p: bytes) -> None:
        if len(p) < 2:
            return
        for rule in (*self.always, *self.layouts.get(p[1], ())):
            try:
                rule(self.c, p)
            except IndexError:  # short packet: keep what was decoded before the missing byte
                break


# --------------------------------------------------------------------------- football
class FairplayFootball(_FairplayDecoder):
    contract = event = "Football"
    layouts = {
        T_CLOCK2: _rules(("PlayClockTens", _hi(7)), ("PlayClockOnes", _lo(7))),
        T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7) + _rules(
            ("HomePossession", _flag(10, 8, "<")), ("GuestPossession", _flag(10, 4, ">")),
            ("Horn", _flag(11, 0x30, "H")),
        ) + _digits("BallOn", 12) + _rules(
            ("Down", _hi(8)), ("Quarter", _lo(8)),
            ("HomeTimeouts", _hi(13)), ("GuestTimeouts", _lo(13)),
        ) + _digits("ToGo", 9),
    }


# --------------------------------------------------------------------------- basketball
def _players(side, base_player, base_points, base_fouls):
    out = []
    for n in range(5):
        out += _rules((f"{side}Player{n + 1}", _two(base_player + n)),
                      (f"{side}Player{n + 1}FoulNumber", _lo(base_fouls + n)),
                      (f"{side}Player{n + 1}Points", _two(base_points + n)))
    return out


_SHOT = _rules(("ShotClockSecondTens", _hi(7)), ("ShotClockSecondOnes", _lo(7)))
_BB_SCORES = (_rules(("HomeScoreHundreds", _flag(10, 0x30, "1"))) + _digits("HomeScore", 6)
              + _rules(("GuestScoreHundreds", _flag(10, 0xC0, "1"))) + _digits("GuestScore", 7))
_BB_LAMPS = _rules(("HomePossession", _flag(10, 2, "<")), ("GuestPossession", _flag(10, 1, ">")),
                   ("HomeBonus", _flag(10, 8, "B")), ("GuestBonus", _flag(10, 4, "B")))
_BB_DOUBLE = _rules(("HomeDoubleBonus", _flag(11, 2, "B")), ("GuestDoubleBonus", _flag(11, 1, "B")))
_BB_FOULS = (_digits("HomeFoul", 12) + _digits("GuestFoul", 13) + _digits("FoulPlayer", 14)
             + _rules(("FoulPlayerNumberOfFouls", _lo(15)), ("Period", _lo(8))))
_HORN_ALL = ("Horn", _flag(11, 0x30, "H", exact=True))


class _Basketball(_FairplayDecoder):
    contract = event = "Basketball"


class FairplayBasketball(_Basketball):
    """Codes 1, 2, 9, 10, 11, 12."""
    layouts = {
        T_CLOCK2: _SHOT,
        T_HOME_PLAYERS: _players("Home", 4, 12, 20),
        T_GUEST_PLAYERS: _players("Guest", 4, 12, 20),
        T_MAIN: [_clock] + _BB_SCORES + _rules(("HomeTimeouts", _hi(16)), ("GuestTimeouts", _lo(16)), _HORN_ALL)
        + _BB_LAMPS + _BB_DOUBLE + _BB_FOULS,
    }


class FairplayBasketball56(_Basketball):
    """Codes 5 and 6: as the generic layout without the double-bonus lamps."""
    layouts = {
        T_CLOCK2: _SHOT,
        T_HOME_PLAYERS: _players("Home", 4, 12, 20),
        T_GUEST_PLAYERS: _players("Guest", 4, 12, 20),
        T_MAIN: [_clock] + _BB_SCORES + _rules(("HomeTimeouts", _hi(16)), ("GuestTimeouts", _lo(16)), _HORN_ALL)
        + _BB_LAMPS + _BB_FOULS,
    }


class FairplayBasketball0(_Basketball):
    """Code 0: score, lamps and period only; horn is any of the two horn bits."""
    layouts = {
        T_MAIN: [_clock] + _BB_SCORES + _rules(
            ("HomePossession", _flag(10, 2, "<")), ("GuestPossession", _flag(10, 1, ">")),
            ("HomeBonus", _flag(10, 8, "B")), ("HomeDoubleBonus", _flag(11, 2, "B")),
            ("GuestBonus", _flag(10, 4, "B")), ("GuestDoubleBonus", _flag(11, 1, "B")),
            ("Period", _lo(8)), ("Horn", _flag(11, 0x30, "H")),
        ),
    }


class FairplayBasketball4(_Basketball):
    """Code 4: timeouts live in the high nibbles of bytes 8 and 15; no double bonus, no player pages."""
    layouts = {
        T_CLOCK2: _SHOT,
        T_MAIN: [_clock] + _BB_SCORES + _rules(
            ("HomeTimeouts", _hi(8)), ("GuestTimeouts", _hi(15)), _HORN_ALL) + _BB_LAMPS + _BB_FOULS,
    }


# --------------------------------------------------------------------------- volleyball
class _Volleyball(_FairplayDecoder):
    contract = event = "Volleyball"


class FairplayVolleyball(_Volleyball):
    layouts = {T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7) + _rules(("Game", _lo(8)))}


class FairplayVolleyball4(_Volleyball):
    """Code 4. The old decoder writes the set 3 score twice (bytes 28/29, then 30/31); the last write wins."""
    layouts = {
        T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7) + _rules(
            ("Game", _hi(16)), ("Set", _lo(8)), ("HomeGamesWon", _lo(12)), ("GuestGamesWon", _lo(13)),
            ("HomeScoreSet1", _two(20)), ("GuestScoreSet1", _two(21)),
            ("HomeScoreSet2", _two(22)), ("GuestScoreSet2", _two(23)),
            ("HomeScoreSet3", _two(28)), ("GuestScoreSet3", _two(29)),
            ("HomeScoreSet3", _two(30)), ("GuestScoreSet3", _two(31)),
            ("HomeTimeout", _hi(8)), ("GuestTimeout", _hi(15)),
            ("HomeServe", lambda p: "*" if p[10] & 0xF == 2 else " "),
            ("GuestServe", lambda p: "*" if p[10] & 0xF == 1 else " "),
        ),
    }


# --------------------------------------------------------------------------- hockey / lacrosse
def _penalties(side, player_base, clock_base):
    """Two penalty slots per side: player number, minutes (high/low nibble of the first byte) and seconds."""
    out = []
    for n in (1, 2):
        pre = f"{side}PenaltyPlayer{n}"
        out += _digits(pre, player_base + n - 1)
        out += _rules((pre + "ClockMinutesTens", lambda p: " "),
                      (pre + "ClockMinutesOnes", (_hi if n == 1 else _lo)(clock_base)))
        out += _digits(pre + "ClockSecond", clock_base + n)
    return out


_SHOT2 = _rules(("ShotClockTens", _hi(7)), ("ShotClockOnes", _lo(7)))


class FairplayHockey13(_FairplayDecoder):
    contract, event = "HockeyLacrosse", "Hockey"
    layouts = {
        T_CLOCK2: _SHOT2,
        T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7)
        + _penalties("Home", 15, 12) + _penalties("Guest", 23, 20) + _rules(("Period", _lo(8))),
    }


class FairplayHockey14(_FairplayDecoder):
    contract, event = "HockeyLacrosse", "Hockey"
    layouts = {
        T_CLOCK2: _SHOT2,
        T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7)
        + _digits("HomeShotOnGoal", 12) + _digits("GuestShotOnGoal", 13)
        + _penalties("Home", 23, 20) + _penalties("Guest", 31, 28) + _rules(("Period", _lo(8))),
    }


class FairplayLacrosse(_FairplayDecoder):
    contract, event = "HockeyLacrosse", "Lacrosse"
    layouts = {
        T_CLOCK2: _SHOT2,
        T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7) + _rules(("Period", _lo(8))),
    }


# --------------------------------------------------------------------------- soccer
class FairplaySoccer22(_FairplayDecoder):
    contract = event = "Soccer"
    layouts = {
        T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7)
        + _digits("HomeShot", 12) + _digits("GuestShot", 15) + _rules(
            ("HomePossession", _flag(11, 2, "<")), ("GuestPossession", _flag(11, 1, ">")),
            ("HomeSaves", _two(13)), ("HomeCornerKicks", _lo(14)),
            ("GuestSaves", _two(16)), ("GuestCornerKicks", _lo(17)), ("Period", _lo(8))),
    }


class FairplaySoccer36(_FairplayDecoder):
    """Code 36: shots in bytes 8/9 and the period as a 7-segment digit in byte 10."""
    contract = event = "Soccer"
    layouts = {
        T_MAIN: [_clock] + _digits("HomeScore", 6) + _digits("GuestScore", 7)
        + _digits("HomeShot", 8) + _digits("GuestShot", 9) + _rules(("Period", lambda p: digit(p[10]))),
    }


# --------------------------------------------------------------------------- baseball / softball
class _Baseball(_FairplayDecoder):
    contract, event = "BaseballSoftball", "Baseball"
    always = [lambda c, p: c.update(InternalClockStatus=" ", ClockMode=":")]


def _error_flag_bits(c, p):
    c["ErrorFlag"] = " "
    if p[10] & 0x20:
        c["ErrorFlag"] = "H"
    if p[10] & 0x10:
        c["ErrorFlag"] = "E"


def _top_bottom_bits_4_8(c, p):
    c["TopBottomInning"] = " "
    if p[10] & 4:
        _top_bottom(c, "T")
    if p[10] & 8:
        _top_bottom(c, "B")


_RUNS_67 = _digits("HomeRun", 6) + _digits("GuestRun", 7)


def _baseball30_state(c, p):
    low, high = bcd(p[10], 0), bcd(p[10], 1)
    c["TopBottomInning"] = c["TopOfInning"] = c["BottomOfInning"] = " "
    if low in ("0", "4"):
        _top_bottom(c, "T")
        c["PitchCount"] = "0" + bcd(p[13], 1) + bcd(p[13], 0)
    elif low == "8":
        _top_bottom(c, "B")
        c["PitchCount"] = "0" + bcd(p[12], 1) + bcd(p[12], 0)
    if high in ("5", "7"):
        c["ErrorFlag"] = "E"
    elif high == "6":
        c["ErrorFlag"] = "H"
    elif high == "4":
        c["ErrorFlag"] = " "


class FairplayBaseball30(_Baseball):
    """Code 30: lamp counts as hex letters; top/bottom, pitch count and error flag from byte 10."""
    layouts = {
        T_MAIN: _rules(("Balls", _abc(8, 0)), ("Strikes", _abc(9, 1)), ("Outs", _abc(9, 0)))
        + _digits("Inning", 8) + _RUNS_67 + [_baseball30_state],
    }


class FairplayBaseball31(_Baseball):
    """Codes 31 (baseball and softball): balls/strikes/outs as BCD nibbles, flags in byte 10."""
    layouts = {
        T_MAIN: _rules(("Balls", _hi(8)), ("Strikes", _lo(9)), ("Outs", _hi(9)), ("InningOnes", _lo(8)))
        + _RUNS_67 + [_error_flag_bits, _top_bottom_bits_4_8] + _digits("AtBat", 5),
    }


class FairplayBaseball32(_Baseball):
    layouts = {
        T_MAIN: _rules(("Balls", _abc(8, 0)), ("Strikes", _abc(9, 1)), ("Outs", _abc(9, 0)),
                       ("InningOnes", _lo(8))) + _RUNS_67 + [_error_flag_bits, _top_bottom_bits_4_8],
    }


def _top_bottom_bits_40_80(c, p):
    if p[10] & 0x40:
        _top_bottom(c, "T")
    if p[10] & 0x80:
        _top_bottom(c, "B")


class FairplayBaseball33(_Baseball):
    layouts = {
        T_MAIN: _rules(("Balls", _hi(6)), ("Strikes", _lo(6)), ("Outs", _lo(9)),
                       ("GuestErrors", _hi(5)), ("HomeErrors", _hi(8))) + _digits("AtBat", 12) + _rules(
            ("InningTens", _flag(10, 0x30, "1")), ("InningOnes", _hi(9))) + _digits("HomeRun", 7)
        + _digits("GuestRun", 4) + _rules(
            ("GuestHitsTens", _flag(10, 0x0C, "1")), ("GuestHitsOnes", _lo(5)),
            ("HomeHitsTens", _flag(10, 0x03, "1")), ("HomeHitsOnes", _lo(8))) + [_top_bottom_bits_40_80],
    }


def _innings(side, first_byte, count):
    out = []
    for n in range(count):
        out.append((f"{side}Inning{n + 1}", (_lo if n % 2 == 0 else _hi)(first_byte + n // 2)))
    return _rules(*out)


def _inning_from_linescore(c, p):
    """Current inning and half: the last line-score column with a number in it (10 columns scanned)."""
    num, half = 10, "T"
    for i in range(10, 0, -1):
        if c.get(f"HomeInning{i}", "\0") != " ":
            half = "B"
            break
        if c.get(f"GuestInning{i}", "\0") != " ":
            half = "T"
            break
        if num > 1:
            num -= 1
    c["InningTens"], c["InningOnes"] = f"{num:02d}"
    _top_bottom(c, half)


class FairplayBaseball34(_Baseball):
    layouts = {
        T_MAIN: _rules(("Balls", _hi(9)), ("Strikes", _lo(8)), ("Outs", _hi(8)))
        + _innings("Guest", 12, 10) + _innings("Home", 20, 10)
        + _digits("GuestRun", 17) + _digits("GuestHits", 5) + _rules(("GuestErrors", _lo(6)))
        + _digits("HomeRun", 25) + _digits("HomeHits", 7) + _rules(("HomeErrors", _hi(6)))
        + _digits("AtBat", 4) + [_inning_from_linescore],
    }


class FairplayBaseball35(_Baseball):
    layouts = {
        T_MAIN: _rules(("Balls", _hi(8)), ("Strikes", _hi(16)), ("Outs", lambda p: _fairplay_outs(p[18])))
        + _innings("Guest", 4, 9) + _innings("Home", 12, 9)
        + _digits("GuestRun", 9) + _digits("HomeRun", 17) + _digits("AtBat", 20),
    }


# --------------------------------------------------------------------------- protocol
class FairplayProtocol(Protocol):
    """Finds ``code`` in the stream and checks the 16-bit sum trailer."""

    def __init__(self, decoder: Decoder, code: int):
        super().__init__(decoder)
        self.code = code

    def extract(self):
        buf = self.buf
        while True:
            i = buf.find(self.code)
            if i < 0:
                buf.clear()
                return
            if i:
                del buf[:i]
            if len(buf) < 4:
                return
            total = buf[3] + 6
            if len(buf) < total:
                return
            frame = bytes(buf[:total])
            if sum(frame[:-2]) == frame[-1] * 256 + frame[-2]:
                del buf[:total]
                yield frame
            else:
                del buf[:1]  # false start: look for the code again one byte later
                self.reject()


def _factory(decoder_cls, code):
    return lambda: FairplayProtocol(decoder_cls(), code)


_TABLE = {
    "Fairplay_Basketball_Code0": (FairplayBasketball0, 0),
    "Fairplay_Basketball_Code1": (FairplayBasketball, 1),
    "Fairplay_Basketball_Code2": (FairplayBasketball, 2),
    "Fairplay_Basketball_Code4": (FairplayBasketball4, 4),
    "Fairplay_Basketball_Code6": (FairplayBasketball56, 6),
    "Fairplay_Basketball_Code9": (FairplayBasketball, 9),
    "Fairplay_Basketball_Code10": (FairplayBasketball, 10),
    "Fairplay_Basketball_Code11": (FairplayBasketball, 11),
    "Fairplay_Basketball_Code12": (FairplayBasketball, 12),
    "Fairplay_Volleyball_Code0": (FairplayVolleyball, 0),
    "Fairplay_Volleyball_Code4": (FairplayVolleyball4, 4),
    "Fairplay_Hockey_code13": (FairplayHockey13, 13),
    "Fairplay_Hockey_Code14": (FairplayHockey14, 14),
    "Fairplay_Lacrosse": (FairplayLacrosse, 21),
    "Fairplay_Soccer_Code22": (FairplaySoccer22, 22),
    "Fairplay_Soccer_Code36": (FairplaySoccer36, 36),
    "Fairplay_Football_Code23": (FairplayFootball, 23),
    "Fairplay_Football_Code24": (FairplayFootball, 24),
    "Fairplay_Football_Code25": (FairplayFootball, 25),
    "Fairplay_Football_Code26": (FairplayFootball, 26),
    "Fairplay_Football_Code27": (FairplayFootball, 27),
    "Fairplay_Baseball_Code30": (FairplayBaseball30, 30),
    "Fairplay_Baseball_Code31": (FairplayBaseball31, 31),
    "Fairplay_Softball_Code31": (FairplayBaseball31, 31),
    "Fairplay_Baseball_Code32": (FairplayBaseball32, 32),
    "Fairplay_Baseball_Code33": (FairplayBaseball33, 33),
    "Fairplay_BaseballSoftball_Code34": (FairplayBaseball34, 34),
    "Fairplay_BaseballSoftball_Code35": (FairplayBaseball35, 35),
}
# Fairplay_Basketball_Code5 (FairplayBasketball56) and Fairplay_Football_Code24 are registered here too;
# they are in ScoreConnect's Fairplay.Main table but outside this assignment's id list.
_TABLE["Fairplay_Basketball_Code5"] = (FairplayBasketball56, 5)

PROTOCOLS = {pid: _factory(cls, code) for pid, (cls, code) in _TABLE.items()}
