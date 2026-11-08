"""Tissot basketball scoreboards (115200 baud RS-485).

Wire format: ASCII records between SOH and EOT, no checksum::

    01 "4|6|<id>|<n>|<value>|…" 04

Only packets that start with ``01 34 7C 36`` (``\\x014|6``) are accepted. Splitting the text between SOH and EOT on
``|`` gives ``f[2]`` = record id and the values from ``f[4]``:

======  =====================================================================================
id      content
======  =====================================================================================
1       ``f[4]`` home score, ``f[5]`` guest score
2       ``f[4]``/``f[5]`` team fouls, ``f[6]``/``f[7]`` bonus state (1 = bonus, 2 = double bonus)
4       ``f[5]`` period
5       ``f[4]`` possession 1 = home, 2 = guest, 3 = both, else none
17      ``f[4]``/``f[5]`` home/guest team name
30      ``f[4]`` game clock (``MM:SS`` or ``SS.t``), ``f[6]`` timeout clock, ``f[9]`` clock stopped flag
31      ``f[4]`` shot clock
32      ``f[7]``/``f[8]`` home/guest timeouts
======  =====================================================================================
"""
from __future__ import annotations

import re

from .base import Decoder, Protocol, find

__all__ = ["TissotProtocol", "TissotBasketball", "PROTOCOLS"]

HEADER = b"\x014|6"


def _to_int(s: str) -> int:
    return int(s) if re.fullmatch(r"\s*[+-]?[0-9]+\s*", s) else 0


def _right(s: str, n: int) -> str:
    """Last n characters of s, padded on the left with spaces."""
    return (" " * n + s)[-n:]


class TissotProtocol(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            eot = find(buf, 4)
            if eot < 0:
                return
            soh = find(buf, 1)
            if 0 <= soh < eot:
                pkt = bytes(buf[soh : eot + 1])
                del buf[: eot + 1]
                if pkt.startswith(HEADER):
                    yield pkt
                else:
                    self.reject()
            else:
                del buf[: eot + 1]
                self.reject()


class TissotBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        f = p[1:-1].decode("utf-8", "replace").split("|")
        if len(f) < 3:
            return
        handler = {1: self._scores, 2: self._fouls, 4: self._period, 5: self._possession, 17: self._names,
                   30: self._game_clock, 31: self._shot_clock, 32: self._timeouts}.get(_to_int(f[2]))
        if handler:
            handler(f)

    # ---- helpers that reproduce System.TimeSpan("c") character positions
    @staticmethod
    def _mmss(minutes: int, seconds: int) -> str:
        total = max(0, minutes * 60 + seconds)
        return f"{(total // 60) % 60:02d}{total % 60:02d}"

    def _set_clock(self, s: str) -> None:
        """Game clock text (Windows build): "MM:SS" or "SS.t"; values are kept to their last two digits."""
        c = self.c
        if "." not in s:
            m, _, rest = s.partition(":")
            sec = rest.partition(":")[0]
            mm, ss = abs(_to_int(m)) % 100, abs(_to_int(sec)) % 100
            c.update(ClockMinutesTens=str(mm // 10), ClockMinutesOnes=str(mm % 10), ClockMode=":",
                     ClockSecondTens=str(ss // 10), ClockSecondOnes=str(ss % 10), ClockTenthsSecond="0")
        else:
            whole, _, rest = s.partition(".")
            frac = rest.partition(".")[0]
            ms = max(0, _to_int(whole) * 1000 + _to_int(frac) * 100 + 1)
            sec = (ms // 1000) % 60  # as System.TimeSpan "c" prints it
            c.update(ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=str(sec // 10),
                     ClockSecondOnes=str(sec % 10), ClockMode=".", ClockTenthsSecond=str((ms % 1000) // 100))

    def _game_clock(self, f):
        if len(f) < 7:
            return
        self._set_clock(f[4])
        if f[6] == "":
            self.c.update(TimeoutClockMinutesOnes="0", TimeoutClockSecondTens="0", TimeoutClockSecondOnes="0")
        elif ":" in f[6]:
            m, sec = f[6].split(":")[:2]
            t = self._mmss(_to_int(m), _to_int(sec))
            self.c.update(TimeoutClockMinutesOnes=t[1], TimeoutClockSecondTens=t[2], TimeoutClockSecondOnes=t[3])
        if len(f) > 9:
            self.c["InternalClockStatus"] = "S" if f[9] == "1" else "R"

    def _shot_clock(self, f):
        if len(f) < 5:
            return
        if "." in f[4]:
            ch = _right(f[4], 4)
            self.c.update(ShotClockSecondTens=ch[0], ShotClockSecondOnes="0" if ch[1] == " " else ch[1],
                          ShotClockTenthsSecond=ch[3])
        else:
            ch = _right(f[4], 2)
            self.c.update(ShotClockSecondTens=ch[0], ShotClockSecondOnes="0" if ch[1] == " " else ch[1],
                          ShotClockTenthsSecond=" ")

    def _names(self, f):
        if len(f) > 5:
            self.c["HomeTeamName"], self.c["GuestTeamName"] = f[4], f[5]

    def _scores(self, f):
        if len(f) > 5:
            for team, s in (("Home", f[4]), ("Guest", f[5])):
                h, t, o = _right(str(_to_int(s)), 3)
                self.c.update({team + "ScoreHundreds": h, team + "ScoreTens": t, team + "ScoreOnes": o})

    def _fouls(self, f):
        if len(f) < 8:
            return
        for team, s, bonus in (("Home", f[4], f[6]), ("Guest", f[5], f[7])):
            t, o = _right(str(_to_int(s)), 2)
            self.c.update({team + "FoulTens": t, team + "FoulOnes": o,
                           team + "Bonus": "B" if bonus == "1" else " ",
                           team + "DoubleBonus": "B" if bonus == "2" else " "})

    def _period(self, f):
        if len(f) > 5 and f[5]:
            self.c["Period"] = f[5][0]

    def _possession(self, f):
        if len(f) > 4:
            home, guest = {"1": ("<", " "), "2": (" ", ">"), "3": ("<", ">")}.get(f[4], (" ", " "))
            self.c["HomePossession"], self.c["GuestPossession"] = home, guest

    def _timeouts(self, f):
        if len(f) > 8 and f[7] and f[8]:
            self.c["HomeTimeouts"], self.c["GuestTimeouts"] = f[7][0], f[8][0]


PROTOCOLS = {"Tissot_Basketball": lambda: TissotProtocol(TissotBasketball())}
