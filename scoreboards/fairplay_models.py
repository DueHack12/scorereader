"""Fair-Play scoreboards other than the "main" RS-485 family (see ``fairplay.py`` for that one).

* MP80 / MP70 wireless  - XBee link, 12-bit address + 4-bit nibble words, 16-bit additive checksum.
* Proline               - RS-232 ASCII messages framed by STX (02) ... ETX (03).
* MP69 via PIC 55 AA    - the ScoreLinkII decodes the console and forwards 7+ raw BCD bytes.
* MP70 via PIC 55 AA    - the PIC forwards a normal Fair-Play packet; the sport comes from its code byte.

Everything here yields *contract* dicts (see ``base.py``); wire details are in ``docs/vendors/fairplay_models.md``.
"""
from __future__ import annotations

import re

from .base import Decoder, Protocol, find
from .common import ascii_char, bcd
from .pic55aa import Pic55AAMp69, Pic55AAMp70

__all__ = ["PROTOCOLS", "FairplayAutodetect"]


# =========================================================================================== MP80 wireless
def _mp80_names(p: bytes) -> tuple[str | None, str | None]:
    """Team names from the 32-byte packet that starts 3F D0 (home at byte 6, then guest)."""
    home = guest = None
    try:
        i = 6
        s = ""
        while p[i] not in (0, 10):
            s += chr(p[i])
            i += 1
        home = s
        s = ""
        i += 1
        while p[i] not in (0, 13):
            if p[i] != 10:
                s += chr(p[i])
            i += 1
        guest = s
    except IndexError:
        pass  # a name that runs off the end of the packet is dropped (the home name may already be set)
    return home, guest


class _Mp80Decoder(Decoder):
    """Words of 2 bytes: address = (b0 << 4) | (b1 >> 4), value = low nibble of b1. The last word is the checksum."""

    plain: dict = {}      # address -> contract field holding the BCD nibble (nibbles A-F read as blank)
    flags: dict = {}      # address -> (field, character, test): "nz" = nibble != 0, "eq1" = nibble == 1
    blank_zero: dict = {}  # address -> field; like plain, but a "0" reads as blank (hundreds digits)
    clocked = True

    def decode(self, p: bytes) -> None:
        if len(p) == 32 and p[0] == 0x3F and p[1] == 0xD0:
            home, guest = _mp80_names(p)
            if home is not None:
                self.c["HomeTeamName"] = home
            if guest is not None:
                self.c["GuestTeamName"] = guest
        else:
            c = self.c
            for k in range(len(p) // 2 - 1):
                addr = ((p[2 * k] << 8) | (p[2 * k + 1] & 0xF0)) >> 4
                d = p[2 * k + 1] & 0x0F
                if self.clocked and 7 <= addr <= 10:
                    self._clock(addr, d)
                elif addr in self.plain:
                    c[self.plain[addr]] = bcd(d, 0)
                elif addr in self.flags:
                    field, ch, test = self.flags[addr]
                    on = d != 0 if test == "nz" else d == 1
                    c[field] = ch if on else " "
                elif addr in self.blank_zero:
                    c[self.blank_zero[addr]] = bcd(d, 0, blank="0")
                else:
                    self.extra(addr, d)
        self.after()

    def extra(self, addr: int, d: int) -> None:
        pass

    def after(self) -> None:
        pass

    def _clock(self, addr: int, d: int) -> None:
        c = self.c
        colon = c.get("ClockMode", " ") == ":"
        v = bcd(d, 0)
        if addr == 7:
            if colon:
                c["ClockMinutesTens"] = v
            else:
                c["ClockMinutesTens"] = "0"
                c["ClockSecondTens"] = v
        elif addr == 8:
            if colon:
                c["ClockMinutesOnes"] = v
            else:
                c["ClockMinutesOnes"] = "0"
                c["ClockSecondOnes"] = v
        elif addr == 9:
            if colon:
                c["ClockSecondTens"] = v
                c["ClockTenthsSecond"] = "0"
            else:
                c["ClockTenthsSecond"] = v
        else:  # 10: a blank nibble means "tenths mode"
            c["ClockMode"] = "." if v == " " else ":"
            if c["ClockMode"] == ":":
                c["ClockSecondOnes"] = v


_SCORES = {2: "HomeScoreTens", 1: "HomeScoreOnes", 5: "GuestScoreTens", 4: "GuestScoreOnes"}


class _Mp80Football(_Mp80Decoder):
    contract = event = "Football"
    plain = {**_SCORES, 19: "HomeTimeouts", 20: "GuestTimeouts", 210: "PlayClockTens", 209: "PlayClockOnes",
             36: "Quarter", 35: "Down", 17: "BallOnTens", 18: "BallOnOnes", 37: "ToGoTens", 38: "ToGoOnes"}
    flags = {259: ("GuestPossession", ">", "nz"), 260: ("HomePossession", "<", "nz")}


class _Mp80Basketball(_Mp80Decoder):
    contract = event = "Basketball"
    plain = {**_SCORES, 123: "HomeFoulTens", 121: "HomeFoulOnes", 19: "HomeTimeouts", 124: "GuestFoulTens",
             122: "GuestFoulOnes", 20: "GuestTimeouts", 210: "ShotClockSecondTens", 209: "ShotClockSecondOnes",
             36: "Period"}
    blank_zero = {3: "HomeScoreHundreds", 6: "GuestScoreHundreds"}
    flags = {260: ("HomePossession", "<", "nz"), 262: ("HomeBonus", "B", "eq1"),
             268: ("HomeDoubleBonus", "B", "eq1"), 259: ("GuestPossession", ">", "nz"),
             261: ("GuestBonus", "B", "eq1"), 267: ("GuestDoubleBonus", "B", "eq1"), 15: ("Horn", "H", "eq1")}


class _Mp80Hockey(_Mp80Decoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    plain = {**_SCORES, 36: "Period", 148: "HomeShotOnGoalOnes", 149: "HomeShotOnGoalTens",
             150: "GuestShotOnGoalOnes", 151: "GuestShotOnGoalTens"}
    flags = {15: ("Horn", "H", "eq1")}


class _Mp80Volleyball(_Mp80Decoder):
    contract = event = "Volleyball"
    plain = {**_SCORES, 121: "HomeGamesWon", 19: "HomeTimeout", 20: "GuestTimeout", 122: "GuestGamesWon",
             36: "Game"}


class _Mp80Soccer(_Mp80Decoder):
    contract = event = "Soccer"
    plain = {**_SCORES, 36: "Period", 37: "HomeShotTens", 38: "HomeShotOnes", 17: "GuestShotTens",
             18: "GuestShotOnes"}
    # two-character string fields built from two addresses: address -> (field, position)
    pairs = {282: ("HomeCornerKicks", 0), 306: ("HomeCornerKicks", 1), 255: ("GuestCornerKicks", 0),
             298: ("GuestCornerKicks", 1), 313: ("HomeSaves", 0), 314: ("HomeSaves", 1),
             303: ("GuestSaves", 0), 305: ("GuestSaves", 1)}

    def extra(self, addr: int, d: int) -> None:
        if addr in self.pairs:
            field, pos = self.pairs[addr]
            cur = self.c.get(field)
            ch = bcd(d, 0)
            if not cur or not cur.strip():  # first half to arrive: the other half stays blank
                self.c[field] = ch + " " if pos == 0 else " " + ch
            else:
                self.c[field] = ch + cur[1] if pos == 0 else cur[0] + ch


_INNINGS_G = {265: 1, 263: 2, 247: 3, 245: 4, 188: 5, 189: 6, 190: 7, 191: 8, 192: 9, 219: 10}
_INNINGS_H = {253: 1, 256: 2, 296: 3, 278: 4, 199: 5, 200: 6, 201: 7, 203: 8, 204: 9, 220: 10}


class _Mp80Baseball(_Mp80Decoder):
    contract = "BaseballSoftball"
    event = "Baseball"
    clocked = False
    plain = {41: "Balls", 42: "Strikes", 43: "Outs", 2: "HomeRunTens", 1: "HomeRunOnes", 5: "GuestRunTens",
             4: "GuestRunOnes", 47: "GuestHitsTens", 48: "GuestHitsOnes", 49: "HomeHitsTens",
             50: "HomeHitsOnes", 145: "GuestErrors", 146: "HomeErrors", 45: "AtBatTens", 46: "AtBatOnes",
             44: "InningTens", 36: "InningOnes",
             **{a: f"GuestInning{n}" for a, n in _INNINGS_G.items()},
             **{a: f"HomeInning{n}" for a, n in _INNINGS_H.items()}}

    def extra(self, addr: int, d: int) -> None:
        if addr == 260:  # nonzero-looking "1" means bottom of the inning
            if bcd(d, 0) == "1":
                self.c.update(TopBottomInning="B", TopOfInning=" ", BottomOfInning=".")
            else:
                self.c.update(TopBottomInning="T", TopOfInning=".", BottomOfInning=" ")


class _Mp70InlineBaseball(_Mp80Baseball):
    """MP70 "inline" baseball: no inning-number words; the inning is worked out from the line score."""

    plain = {a: f for a, f in _Mp80Baseball.plain.items() if f not in ("InningTens", "InningOnes")}

    def after(self) -> None:
        c = self.c
        num = 10
        for n in range(10, 0, -1):
            g = c.get(f"GuestInning{n}", " ")
            h = c.get(f"HomeInning{n}", " ")
            if g != " " and h != " ":
                num += 1  # both halves played: the next inning is up (num == n + 1)
                break
            if g != " ":
                break  # visitors batted, home has not: bottom of inning n
            if num > 1:
                num -= 1
        c["InningTens"], c["InningOnes"] = f"{num:02d}"


class _Mp80Protocol(Protocol):
    """No delimiters on the wire: ScoreConnect treats everything received as one packet, checks the
    16-bit sum of all bytes but the last two against those two (big endian), and discards the buffer.

    Here the buffer is kept until it validates, and a bad frame in front of a good one is dropped by
    looking for the longest tail of the buffer that validates (one frame per read is assumed)."""

    max_frame = 512
    min_resync = 6  # one data word + checksum

    def _valid(self, view) -> bool:
        return len(view) >= 4 and sum(view[:-2]) == (view[-2] << 8) | view[-1]

    def extract(self):
        buf = self.buf
        n = len(buf)
        if n < 4:
            return
        if self._valid(buf):
            pkt = bytes(buf)
            buf.clear()
            yield pkt
            return
        if n > self.max_frame:  # never going to validate
            self.reject()
            buf.clear()
            return
        total = sum(buf[:-2])
        run = total
        for s in range(0, n - self.min_resync + 1):
            if s:
                run -= buf[s - 1]
            if s and (n - s) % 2 == 0 and run == (buf[-2] << 8 | buf[-1]) and run:
                self.reject()  # garbage / a bad frame in front of the good one
                pkt = bytes(buf[s:])
                buf.clear()
                yield pkt
                return


# =========================================================================================== MP69 (PIC 55 AA)
def _mp69_clock(c: dict, p: bytes) -> None:
    if p[5] & 0x0F == 0x0F:  # tenths mode: seconds in byte 6, tenths in the high nibble of byte 5
        c.update(ClockMode=".", ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=bcd(p[6], 1),
                 ClockSecondOnes=bcd(p[6], 0), ClockTenthsSecond=bcd(p[5], 1))
    else:
        c.update(ClockMode=":", ClockMinutesTens=bcd(p[6], 1), ClockMinutesOnes=bcd(p[6], 0),
                 ClockSecondTens=bcd(p[5], 1), ClockSecondOnes=bcd(p[5], 0), ClockTenthsSecond=" ")


class _Mp69Football(Decoder):
    contract = event = "Football"

    def decode(self, p: bytes) -> None:
        if len(p) < 7:
            return
        c = self.c
        c["Quarter"] = bcd(p[2], 0)
        _mp69_clock(c, p)
        c.update(HomeScoreTens=bcd(p[4], 1), HomeScoreOnes=bcd(p[4], 0), GuestScoreTens=bcd(p[3], 1),
                 GuestScoreOnes=bcd(p[3], 0))
        c["Horn"] = "H" if p[0] & 0x60 == 0x60 else " "
        c["HomePossession"] = "<" if p[1] & 8 else " "
        c["GuestPossession"] = ">" if p[1] & 4 else " "


class _Mp69Basketball(Decoder):
    contract = event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 7:
            return
        c = self.c
        c["Period"] = bcd(p[2], 0)
        c["HomeScoreHundreds"] = "1" if p[1] & 0x80 else " "
        c["GuestScoreHundreds"] = "1" if p[1] & 0x40 else " "
        c.update(HomeScoreTens=bcd(p[4], 1), HomeScoreOnes=bcd(p[4], 0), GuestScoreTens=bcd(p[3], 1),
                 GuestScoreOnes=bcd(p[3], 0))
        _mp69_clock(c, p)
        c["Horn"] = "H" if p[0] & 0x60 == 0x60 else " "
        c["GuestBonus"] = "B" if p[1] & 0x10 else " "
        c["HomeBonus"] = "B" if p[1] & 0x20 else " "
        c["HomePossession"] = "<" if p[1] & 8 else " "
        c["GuestPossession"] = ">" if p[1] & 4 else " "


class _Mp69Baseball(Decoder):
    contract = "BaseballSoftball"
    event = "Baseball"

    def decode(self, p: bytes) -> None:
        if len(p) < 7:
            return
        c = self.c
        c.update(InningOnes=bcd(p[2], 0), Balls=bcd(p[6], 1), Strikes=bcd(p[6], 0), Outs=bcd(p[5], 0),
                 HomeRunTens=bcd(p[4], 1), HomeRunOnes=bcd(p[4], 0), GuestRunTens=bcd(p[3], 1),
                 GuestRunOnes=bcd(p[3], 0))
        c["TopOfInning"] = "T" if p[1] & 4 else " "
        c["BottomOfInning"] = "B" if p[1] & 8 else " "


# =========================================================================================== Proline (RS-232)
def _int(s: str) -> int:
    s = s.strip()
    return int(s) if re.fullmatch(r"[+-]?\d+", s) else 0


def _a(p: bytes, i: int, slz: bool = False) -> str:
    return ascii_char(p[i], slz)


def _str(p: bytes, i: int, n: int = 8) -> str:
    """n characters of ASCII from byte i, blank-padded when the packet is shorter."""
    return "".join(_a(p, k) if k < len(p) else " " for k in range(i, i + n))


class _ProlineDecoder(Decoder):
    """Messages are STX, a letter naming the message, ASCII fields, ETX. ``handlers`` maps the letter to
    (minimum length, method)."""

    handlers: dict = {}

    def decode(self, p: bytes) -> None:
        h = self.handlers.get(p[1]) if len(p) > 1 else None
        if h and len(p) >= h[0]:
            getattr(self, h[1])(p)

    def _clock(self, p: bytes, keep_tenths_blank: bool = False) -> None:
        """Game clock from bytes 2-6 (minutes, seconds, tenths). Football uses a variant that leaves the
        tenths (colon mode) and the minutes (tenths mode) untouched; every other sport zero-fills them."""
        c = self.c
        if _int(_a(p, 2) + _a(p, 3)) >= 1 or _a(p, 6) == " ":
            c.update(ClockMode=":", ClockMinutesTens=_a(p, 2), ClockMinutesOnes=_a(p, 3),
                     ClockSecondTens=_a(p, 4), ClockSecondOnes=_a(p, 5))
            if not keep_tenths_blank:
                c["ClockTenthsSecond"] = "0"
        else:
            c.update(ClockMode=".", ClockSecondTens=_a(p, 4), ClockSecondOnes=_a(p, 5),
                     ClockTenthsSecond=_a(p, 6))
            if not keep_tenths_blank:
                c.update(ClockMinutesTens="0", ClockMinutesOnes="0")

    def _name(self, p: bytes, off: int, home: bool) -> None:
        self.c["HomeTeamName" if home else "GuestTeamName"] = _str(p, off)

    def _fields(self, p: bytes, rows) -> None:
        for field, i, *slz in rows:
            self.c[field] = _a(p, i, bool(slz and slz[0]))


class _ProlineFootball(_ProlineDecoder):
    contract = event = "Football"
    handlers = {70: (34, "teams"), 67: (10, "clock")}

    def teams(self, p: bytes) -> None:
        c = self.c
        c["HomeTeamName"] = _str(p, 2)
        self._fields(p, [("HomeScoreTens", 12), ("HomeScoreOnes", 13), ("HomeTimeouts", 14)])
        c["GuestTeamName"] = _str(p, 15)
        self._fields(p, [("GuestScoreTens", 25), ("GuestScoreOnes", 26), ("GuestTimeouts", 27), ("Down", 28),
                         ("ToGoTens", 29), ("ToGoOnes", 30), ("BallOnTens", 31), ("BallOnOnes", 32)])
        c["HomePossession"] = "<" if _a(p, 33) == "H" else " "
        c["GuestPossession"] = ">" if _a(p, 33) == "V" else " "

    def clock(self, p: bytes) -> None:
        self._clock(p, keep_tenths_blank=True)
        self._fields(p, [("Quarter", 7), ("PlayClockTens", 8), ("PlayClockOnes", 9)])


class _ProlineSoccer(_ProlineDecoder):
    contract = event = "Soccer"
    handlers = {82: (38, "teams"), 67: (8, "clock")}

    def teams(self, p: bytes) -> None:
        c = self.c
        for side, base, name in (("Home", 12, 2), ("Guest", 30, 20)):
            self._name(p, name, side == "Home")
            self._fields(p, [(f"{side}ScoreTens", base, True), (f"{side}ScoreOnes", base + 1),
                             (f"{side}ShotTens", base + 2, True), (f"{side}ShotOnes", base + 3)])
            c[f"{side}Saves"] = _a(p, base + 4, True) + _a(p, base + 5)
            c[f"{side}CornerKicks"] = " " + _a(p, base + 7)

    def clock(self, p: bytes) -> None:
        self._clock(p)
        self.c["Period"] = _a(p, 7)


class _ProlineBasketball(_ProlineDecoder):
    contract = event = "Basketball"
    handlers = {66: (3, "side"), 67: (10, "clock")}

    def side(self, p: bytes) -> None:
        who = {72: "Home", 86: "Guest"}.get(p[2])
        if who is None or len(p) < 11:
            return
        c = self.c
        self._name(p, 3, who == "Home")
        # ScoreConnect shifts every index by +10 for packets shorter than 19 bytes, which always runs off the
        # end of the packet: only the team name survives in that case.
        if len(p) < 22:
            return
        c[f"{who}ScoreHundreds"] = _a(p, 13, True)
        if c[f"{who}ScoreHundreds"] == " ":
            c[f"{who}ScoreTens"] = _a(p, 14, True)  # note: with hundreds showing, the tens digit is never refreshed
        c[f"{who}ScoreOnes"] = _a(p, 15)
        c[f"{who}FoulTens"] = _a(p, 16, True)
        c[f"{who}FoulOnes"] = _a(p, 17)
        c[f"{who}Timeouts"] = _a(p, 18)
        c[f"{who}Possession"] = ("<" if who == "Home" else ">") if _a(p, 19) != "0" else " "
        c[f"{who}Bonus"] = "B" if _a(p, 20) != "0" else " "
        c[f"{who}DoubleBonus"] = "B" if _a(p, 21) != "0" else " "

    def clock(self, p: bytes) -> None:
        self._clock(p)
        self._fields(p, [("ShotClockSecondTens", 8), ("ShotClockSecondOnes", 9), ("Period", 7)])


_INNING_COLS = [19 + 2 * k for k in range(10)]  # one character every second byte, 19..37


class _ProlineBaseball(_ProlineDecoder):
    contract = "BaseballSoftball"
    event = "Baseball"
    handlers = {65: (15, "state"), 84: (38, "line")}

    def state(self, p: bytes) -> None:
        self._fields(p, [("InningTens", 2), ("InningOnes", 3), ("Balls", 4), ("Strikes", 5), ("Outs", 6)])
        self.c["TopBottomInning"] = "B" if _a(p, 7) == "H" else "T"
        self._fields(p, [("AtBatTens", 8), ("AtBatOnes", 9), ("ErrorFlag", 10)])
        self.c["PitchCount"] = _a(p, 12) + _a(p, 13) + _a(p, 14)

    def line(self, p: bytes) -> None:
        who = {72: "Home", 86: "Guest"}.get(p[2])
        if who is None:
            return
        self._fields(p, [(f"{who}RunTens", 13), (f"{who}RunOnes", 14), (f"{who}HitsTens", 15),
                         (f"{who}HitsOnes", 16), (f"{who}Errors", 17)]
                     + [(f"{who}Inning{n}", col) for n, col in enumerate(_INNING_COLS, 1)])


def _penalty_rows(side: str, base: int, players: int, key: str = "PenaltyPlayer") -> list:
    rows = []
    for n in range(1, players + 1):
        o = base + 6 * (n - 1)
        for k, suffix in enumerate(("Tens", "Ones", "ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens",
                                    "ClockSecondOnes")):
            rows.append((f"{side}{key}{n}{suffix}", o + k))
    return rows


class _ProlineHockey(_ProlineDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    handlers = {72: (54, "teams"), 67: (10, "clock")}

    def teams(self, p: bytes) -> None:
        self.c["HomeTeamName"] = _str(p, 2)
        self._fields(p, [("HomeScoreTens", 12), ("HomeScoreOnes", 13), ("HomeShotOnGoalTens", 14),
                         ("HomeShotOnGoalOnes", 15)] + _penalty_rows("Home", 16, 2))
        self.c["GuestTeamName"] = _str(p, 28)
        self._fields(p, [("GuestScoreTens", 38), ("GuestScoreOnes", 39), ("GuestShotOnGoalTens", 40),
                         ("GuestShotOnGoalOnes", 41)] + _penalty_rows("Guest", 42, 2))

    def clock(self, p: bytes) -> None:
        self._clock(p)
        self._fields(p, [("Period", 7), ("ShotClockTens", 8), ("ShotClockOnes", 9)])


class _ProlineLacrosse(_ProlineDecoder):
    contract = "HockeyLacrosse"
    event = "Lacrosse"
    handlers = {76: (73, "teams"), 67: (10, "clock")}

    def teams(self, p: bytes) -> None:
        c = self.c
        for side, name, base in (("Home", 2, 12), ("Guest", 37, 47)):
            self._name(p, name, side == "Home")
            self._fields(p, [(f"{side}ScoreTens", base), (f"{side}ScoreOnes", base + 1),
                             (f"{side}TimeOut", base + 2), (f"{side}ShotOnGoalTens", base + 3),
                             (f"{side}ShotOnGoalOnes", base + 4)])
            c[f"{side}Saves"] = _a(p, base + 5) + _a(p, base + 6)
            self._fields(p, _penalty_rows(side, base + 7, 3))
        c["HomePossession"] = "<" if _a(p, 72) == "H" else " "
        c["GuestPossession"] = ">" if _a(p, 72) == "V" else " "

    def clock(self, p: bytes) -> None:
        self._clock(p)
        self._fields(p, [("ShotClockTens", 8), ("ShotClockOnes", 9), ("Period", 7)])


class _ProlineVolleyball(_ProlineDecoder):
    contract = event = "Volleyball"
    handlers = {86: (19, "score"), 89: (39, "players"), 67: (7, "clock")}

    def score(self, p: bytes) -> None:
        who = {72: "Home", 86: "Guest"}.get(p[2])
        if who is None:
            return
        self._name(p, 3, who == "Home")
        self._fields(p, [(f"{who}ScoreTens", 13), (f"{who}ScoreOnes", 14), (f"{who}GamesWon", 15),
                         (f"{who}Timeout", 16), ("Game", 17)])
        self.c["HomeServe"] = "*" if _a(p, 18) == "1" else " "  # ScoreConnect writes HomeServe for both sides

    def players(self, p: bytes) -> None:
        who = {72: "Home", 86: "Guest"}.get(p[2])
        if who is None:
            return
        for n in range(1, 7):
            o = 3 + 6 * (n - 1)
            self.c[f"{who}Player{n}"] = _a(p, o) + _a(p, o + 1)
            self.c[f"{who}Player{n}Kills"] = _a(p, o + 3)
            self.c[f"{who}Player{n}Digs"] = _a(p, o + 4) + _a(p, o + 5)

    def clock(self, p: bytes) -> None:
        self._clock(p)


class _ProlineProtocol(Protocol):
    """STX (02) .. ETX (03). The first STX in the buffer starts the message ending at the first ETX; the
    second byte must be a capital letter (the message type)."""

    def extract(self):
        buf = self.buf
        while True:
            etx = find(buf, 3)
            if etx < 0:
                return
            stx = find(buf, 2)
            if 0 <= stx < etx:
                pkt = bytes(buf[stx : etx + 1])
                del buf[: etx + 1]
                if 65 <= pkt[1] <= 90:
                    yield pkt
                else:
                    self.reject()
            else:
                del buf[: etx + 1]  # ETX with no STX before it: stray bytes


# =========================================================================================== MP70 autodetect
_AUTODETECT_IDS = {
    0: "Fairplay_Basketball_Code0", 1: "Fairplay_Basketball_Code1", 2: "Fairplay_Basketball_Code2",
    4: "Fairplay_Basketball_Code4", 5: "Fairplay_Basketball_Code5", 6: "Fairplay_Basketball_Code6",
    9: "Fairplay_Basketball_Code9", 10: "Fairplay_Basketball_Code10", 11: "Fairplay_Basketball_Code11",
    12: "Fairplay_Basketball_Code12", 13: "Fairplay_Hockey_code13", 14: "Fairplay_Hockey_Code14",
    21: "Fairplay_Lacrosse", 22: "Fairplay_Soccer_Code22", 23: "Fairplay_Football_Code23",
    24: "Fairplay_Football_Code24", 25: "Fairplay_Football_Code25", 26: "Fairplay_Football_Code26",
    27: "Fairplay_Football_Code27", 30: "Fairplay_Baseball_Code30", 31: "Fairplay_Baseball_Code31",
    32: "Fairplay_Baseball_Code32", 33: "Fairplay_Baseball_Code33", 34: "Fairplay_BaseballSoftball_Code34",
    35: "Fairplay_BaseballSoftball_Code35", 36: "Fairplay_Soccer_Code36",
}


def _registry_decoder(protocol_id: str) -> Decoder:
    """A fresh decoder of a Fair-Play main-family id from the package registry (looked up lazily so this
    module doesn't depend on ``fairplay.py`` at import time)."""
    from . import create

    return create(protocol_id).decoder


class FairplayAutodetect(Decoder):
    """The first byte of every packet is a sport code; when it changes, switch to that sport's Fair-Play
    decoder (a fresh one, as ScoreConnect does). ``contract``, ``event`` and ``c`` follow the selection."""

    def __init__(self, factory=None):
        self._factory = factory or _registry_decoder
        self._sel: Decoder | None = None
        self._missing: set = set()
        self.code: int | None = None
        self.selected_id: str | None = None
        self._own = {"EventId": "Generic"}
        super().__init__()

    @property
    def contract(self) -> str:  # type: ignore[override]
        return self._sel.contract if self._sel else "Generic"

    @property
    def event(self) -> str:  # type: ignore[override]
        return self._sel.event if self._sel else "Generic"

    @property
    def c(self) -> dict:  # type: ignore[override]
        return self._sel.c if self._sel else self._own

    @c.setter
    def c(self, value: dict) -> None:
        if self._sel:
            self._sel.c = value
        else:
            self._own = value

    def reset(self) -> None:
        self._sel = None
        self.code = None
        self.selected_id = None
        self._own = {"EventId": "Generic"}

    def decode(self, p: bytes) -> None:
        if not p:
            return
        code = p[0]
        pid = _AUTODETECT_IDS.get(code)
        if pid and pid != self.selected_id and pid not in self._missing:
            try:
                self._sel = self._factory(pid)
                self.code, self.selected_id = code, pid
            except (KeyError, ImportError, AttributeError):
                self._missing.add(pid)  # that sport isn't available in this build
        if self._sel:
            self._sel.decode(p)


# =========================================================================================== registry
PROTOCOLS = {
    "FairplayMP80_Baseball": lambda: _Mp80Protocol(_Mp80Baseball()),
    "FairplayMP80_Football": lambda: _Mp80Protocol(_Mp80Football()),
    "FairplayMP80_Basketball": lambda: _Mp80Protocol(_Mp80Basketball()),
    "FairplayMP80_Soccer": lambda: _Mp80Protocol(_Mp80Soccer()),
    "FairplayMP80_Hockey": lambda: _Mp80Protocol(_Mp80Hockey()),
    "FairPlayMP80_Volleyball": lambda: _Mp80Protocol(_Mp80Volleyball()),
    "FairPlayMP70_BaseBallInLine": lambda: _Mp80Protocol(_Mp70InlineBaseball()),
    "FairplayProline_Football": lambda: _ProlineProtocol(_ProlineFootball()),
    "FairplayProline_Soccer": lambda: _ProlineProtocol(_ProlineSoccer()),
    "FairplayProline_Lacrosse": lambda: _ProlineProtocol(_ProlineLacrosse()),
    "FairplayProline_Hockey": lambda: _ProlineProtocol(_ProlineHockey()),
    "FairplayProline_Baseball": lambda: _ProlineProtocol(_ProlineBaseball()),
    "FairplayProline_Basketball": lambda: _ProlineProtocol(_ProlineBasketball()),
    "FairplayProline_Volleyball": lambda: _ProlineProtocol(_ProlineVolleyball()),
    "PIC55AA_FairplayMP69_Basketball_Code0": lambda: Pic55AAMp69(_Mp69Basketball()),
    "PIC55AA_FairplayMP69_Basketball_Code42": lambda: Pic55AAMp69(_Mp69Basketball()),
    "PIC55AA_FairplayMP69_Baseball": lambda: Pic55AAMp69(_Mp69Baseball()),
    "PIC55AA_FairplayMP69_Football": lambda: Pic55AAMp69(_Mp69Football()),
    "PIC55AA_FairplayMP70_AutoDetect": lambda: Pic55AAMp70(FairplayAutodetect()),
}
