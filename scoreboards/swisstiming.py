"""Swiss Timing scoreboards.

Two unrelated wire formats live here:

* **Swiss Timing "Main"** (hockey, basketball, water polo; PIC RS-485 at 9600 baud)::

      02 type payload… 03 xor

  ``type`` is ``N`` (team names), ``D`` (clock, score, period …) or ``O`` (hockey penalty list). ``xor`` is the
  XOR of every byte from the STX through the ETX. The checksum byte is *not* consumed with the frame, it is left
  in the buffer and skipped when the next STX is located (a checksum of 0x02 directly followed by the real STX
  is handled as ScoreConnect does).

* **Swiss Timing Transmission** (swimming, and the "STBP" basketball variant)::

      01 … 04

  SOH-to-EOT with no checksum. Basketball packets are ASCII, ``|`` separated: ``\\x014|6|<id>|<n>|<values…>``.
  Swimming packets use raw byte 1 as the packet class and fixed ASCII columns.

Contracts: ``Basketball``, ``HockeyLacrosse``, ``WaterPolo`` (all single-level dicts) and ``SwimmingMixed``, whose
``SwimmingEvent`` and ``SwimmingRows`` parts are nested dicts. The nested dicts are replaced, never mutated in
place, so ``Protocol.feed`` notices changes.
"""
from __future__ import annotations

import re

from .base import Decoder, Protocol, find
from .common import ascii_char, ascii_text, xor8

__all__ = ["MainProtocol", "TransmissionProtocol", "PROTOCOLS"]

STX, ETX, SOH, EOT = 0x02, 0x03, 0x01, 0x04


# --------------------------------------------------------------------------- small helpers
def _to_int(s: str) -> int:
    """Lenient integer parse: surrounding whitespace allowed, anything else non-numeric reads as 0."""
    return int(s) if re.fullmatch(r"\s*[+-]?[0-9]+\s*", s) else 0


def _try_int(s: str):
    return int(s) if re.fullmatch(r"\s*[+-]?[0-9]+\s*", s) else None


def _ascii7(data) -> str:
    """Bytes -> str the way .NET's ASCII decoder does it: anything above 0x7F becomes "?"."""
    return "".join(chr(b) if b < 128 else "?" for b in data)


def _fit(s: str, n: int):
    """Right-align a 1..n character string into n single characters (None if it doesn't fit)."""
    if 1 <= len(s) <= n:
        return list(s.rjust(n))
    return None


# --------------------------------------------------------------------------- Main protocol
class MainProtocol(Protocol):
    """STX … ETX xor frames. Yields the frame including the checksum byte."""

    def extract(self):
        buf = self.buf
        while True:
            etx = find(buf, ETX)
            if etx < 0:
                return
            stx = find(buf, STX)
            if 0 <= stx < etx:
                if buf[stx + 1] == buf[stx]:  # doubled STX: the second one starts the frame
                    stx += 1
                if len(buf) < etx + 2:
                    return  # the checksum byte hasn't arrived yet
                frame = bytes(buf[stx : etx + 2])
                del buf[: etx + 1]  # the checksum byte stays behind (see module docstring)
                if xor8(frame, 0, len(frame) - 1) == frame[-1]:
                    yield frame
                else:
                    self.reject()
            else:
                del buf[: etx + 1]
                if etx:  # etx == 0 is just the checksum byte of the previous frame
                    self.reject()


def _set_clock(c: dict, p: bytes) -> None:
    mode = ascii_char(p[4])
    if mode == ":":
        c.update(ClockMinutesTens=ascii_char(p[2]), ClockMinutesOnes=ascii_char(p[3]),
                 ClockSecondTens=ascii_char(p[5]), ClockSecondOnes=ascii_char(p[6]),
                 ClockTenthsSecond="0", ClockMode=":")
    elif mode == ".":
        c.update(ClockMinutesTens="0", ClockMinutesOnes="0",
                 ClockSecondTens=ascii_char(p[2]), ClockSecondOnes=ascii_char(p[3]),
                 ClockTenthsSecond=ascii_char(p[5]), ClockMode=".")
    else:  # any other separator is reported as the clock mode as-is
        c.update(ClockMinutesTens=ascii_char(p[2]), ClockMinutesOnes=ascii_char(p[3]), ClockMode=mode,
                 ClockSecondTens=ascii_char(p[5]), ClockSecondOnes=ascii_char(p[6]), ClockTenthsSecond="0")


class _MainDecoder(Decoder):
    """Common part: 'N' names, 'D' data. Subclasses give the 'D' layout (``fields``) and a minimum length."""

    fields: tuple = ()      # (contract field, packet index) read as ASCII from a 'D' record
    data_len = 25           # bytes a 'D' record needs

    def decode(self, p: bytes) -> None:
        if len(p) < 2:
            return
        kind = p[1]
        if kind == 0x4E:  # 'N': home name at 2, guest name at 14, 8 characters each
            for key, off in (("HomeTeamName", 2), ("GuestTeamName", 14)):
                if len(p) >= off + 8 and ascii_char(p[off]) != " ":
                    self.c[key] = ascii_text(p[off : off + 8])
        elif kind == 0x44 and len(p) >= self.data_len:  # 'D'
            _set_clock(self.c, p)
            for key, i in self.fields:
                self.c[key] = ascii_char(p[i])
            self.extra(p)
        elif kind == 0x4F:  # 'O'
            self.penalties(p)

    def extra(self, p: bytes) -> None:
        pass

    def penalties(self, p: bytes) -> None:
        pass


class SwissBasketball(_MainDecoder):
    contract = "Basketball"
    event = "Basketball"
    fields = (("ShotClockSecondTens", 23), ("ShotClockSecondOnes", 24),
              ("HomeScoreHundreds", 7), ("HomeScoreTens", 8), ("HomeScoreOnes", 9),
              ("GuestScoreHundreds", 10), ("GuestScoreTens", 11), ("GuestScoreOnes", 12),
              ("Period", 17), ("HomeTimeouts", 15), ("GuestTimeouts", 16),
              ("HomeFoulOnes", 13), ("GuestFoulOnes", 14))
    _POSSESSION = {"0": (" ", " "), "1": ("<", " "), "2": (" ", ">"), "3": ("<", ">")}

    def extra(self, p: bytes) -> None:
        self.c["Horn"] = " " if ascii_char(p[20]) == "0" else "H"
        pos = self._POSSESSION.get(ascii_char(p[18]))
        if pos:  # other codes leave the possession arrows as they were
            self.c["HomePossession"], self.c["GuestPossession"] = pos


class SwissHockey(_MainDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    data_len = 18
    fields = (("HomeScoreTens", 8), ("HomeScoreOnes", 9), ("GuestScoreTens", 11), ("GuestScoreOnes", 12),
              ("Period", 17), ("HomeFullTimeoutsRemaining", 15), ("GuestFullTimeoutsRemaining", 16))

    # 'O' record: three penalty slots per team, 7 bytes each: player (2), minutes (2), ':' , seconds (2)
    _SLOTS = tuple((team, n, base) for team, bases in (("Home", (2, 9, 16)), ("Guest", (23, 30, 37)))
                   for n, base in enumerate(bases, 1))

    def penalties(self, p: bytes) -> None:
        if len(p) < 44:
            return
        for team, n, b in self._SLOTS:
            k = f"{team}PenaltyPlayer{n}"
            for suffix, off in (("Tens", 0), ("Ones", 1), ("ClockMinutesTens", 2), ("ClockMinutesOnes", 3),
                                ("ClockSecondTens", 5), ("ClockSecondOnes", 6)):
                self.c[k + suffix] = ascii_char(p[b + off])
        # ScoreConnect blanks the shots on goal here, and (a quirk) never touches GuestShotOnGoalOnes.
        self.c.update(HomeShotOnGoalTens=" ", HomeShotOnGoalOnes=" ", GuestShotOnGoalTens=" ")


class SwissWaterPolo(_MainDecoder):
    contract = "WaterPolo"
    event = "WaterPolo"
    fields = (("HomeScoreTens", 8), ("HomeScoreOnes", 9), ("GuestScoreTens", 11), ("GuestScoreOnes", 12),
              ("Period", 17), ("ShotClockTens", 23), ("ShotClockOnes", 24))

    def extra(self, p: bytes) -> None:
        # Timeout counts ignore a drop of exactly one (ScoreConnect keeps the previous value in that case).
        for key, i in (("HomeTimeouts", 15), ("GuestTimeouts", 16)):
            new, old = ascii_char(p[i]), self.c.get(key, " ")
            self.c[key] = old if ord(new) == ord(old) - 1 else new


# --------------------------------------------------------------------------- Transmission protocol
class TransmissionProtocol(Protocol):
    """SOH … EOT, no checksum. Yields the packet including both delimiters."""

    def extract(self):
        buf = self.buf
        while True:
            eot = find(buf, EOT)
            if eot < 0:
                return
            soh = find(buf, SOH)
            if 0 <= soh < eot:
                pkt = bytes(buf[soh : eot + 1])
                del buf[: eot + 1]
                yield pkt
            else:
                del buf[: eot + 1]
                self.reject()


class SwissTransmissionBasketball(Decoder):
    """Basketball over the Transmission protocol. Fields are ``|`` separated; ``f[2]`` is the record id."""

    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        f = _ascii7(p).split("|")
        if len(f) <= 3 or "4" not in f[0] or f[1] != "6":
            return
        rid = _try_int(f[2])
        handler = {1: self._scores, 2: self._fouls, 3: self._timeouts, 4: self._period, 7: self._horn,
                   30: self._game_time, 31: self._shot_clock}.get(rid)
        if handler:
            handler(f)

    def _scores(self, f):
        if len(f) > 6:
            for team, s in (("Home", f[4]), ("Guest", f[5])):
                d = _fit(s, 3)
                if d:
                    self.c[team + "ScoreHundreds"], self.c[team + "ScoreTens"], self.c[team + "ScoreOnes"] = d

    def _fouls(self, f):
        if len(f) > 8:
            for team, s in (("Home", f[4]), ("Guest", f[5])):
                d = _fit(s, 2)
                if d:
                    self.c[team + "FoulTens"], self.c[team + "FoulOnes"] = d
            # ScoreConnect compares these with a char instead of a string, which makes that code throw on every
            # fouls record; the bonus lamps are decoded here as intended ("1" = bonus).
            self.c["HomeBonus"] = "B" if f[6] == "1" else " "
            self.c["GuestBonus"] = "B" if f[7] == "1" else " "

    def _timeouts(self, f):
        if len(f) > 6 and f[4] and f[5]:
            self.c["HomeTimeouts"], self.c["GuestTimeouts"] = f[4][0], f[5][0]

    def _period(self, f):
        if len(f) > 7 and f[4]:
            if f[4][0] == "3" and f[5]:
                self.c["Period"] = f[5][0]
            elif f[4][0] == "4":  # overtime
                self.c["Period"] = "5"

    def _horn(self, f):
        if len(f) > 4 and f[4]:
            self.c["Horn"] = "H" if f[4][0] == "1" else " "

    def _game_time(self, f):
        if len(f) <= 9:
            return
        t = f[4]
        if ":" in t:
            self.c["ClockMode"], self.c["ClockTenthsSecond"] = ":", " "
            mins, secs = t.split(":")[:2]
            if len(mins) in (1, 2):
                self.c["ClockMinutesTens"], self.c["ClockMinutesOnes"] = mins.rjust(2)
            if len(secs) in (1, 2):
                self.c["ClockSecondTens"], self.c["ClockSecondOnes"] = secs.rjust(2)
        elif "." in t:
            self.c["ClockMode"] = "."
            secs, tenths = t.split(".")[:2]
            if len(secs) in (1, 2):
                self.c["ClockSecondTens"], self.c["ClockSecondOnes"] = secs.rjust(2)
            if tenths:
                self.c["ClockTenthsSecond"] = tenths[0]

    def _shot_clock(self, f):
        if len(f) <= 7 or not f[7]:
            return
        t = f[4]
        self.c["PlayClockStatusInternal"] = "R" if f[7][0] == "1" else "S"
        if t == "":
            # ScoreConnect clears ClockTenthsSecond (the game clock's) here, not the shot clock's.
            self.c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=" ", ClockTenthsSecond=" ")
        elif "." in t:
            secs, tenths = t.split(".")[:2]
            self.c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=secs[:1] or " ",
                          ShotClockTenthsSecond=tenths[:1] or " ")
        else:
            if len(t) == 2:
                self.c["ShotClockSecondTens"], self.c["ShotClockSecondOnes"] = t
            else:
                self.c["ShotClockSecondTens"], self.c["ShotClockSecondOnes"] = " ", t[0]
            self.c["ShotClockTenthsSecond"] = " "


class SwissTransmissionSwimming(Decoder):
    """Swimming results board. ``packet[1]`` is a raw class byte (19 = text record, 2 = control).

    Class 19 layout (ASCII columns): 6-7 sub-type, 8-9 record, 10-11 lane (rows) / start of text, 13-28 swimmer,
    30-33 team, 35-42 time, 44-45 place. Clock records (record 1, sub-type 20) carry ``MM:SS.hh`` at 10-17.
    """

    contract = "SwimmingMixed"
    event = "SwissTiming"

    def __init__(self):
        super().__init__()
        self._fresh()

    def _fresh(self):
        self.c.update(PacketType="", SwimmingEvent={"EventId": self.event}, SwimmingRows={"EventId": self.event})

    def reset(self) -> None:
        super().reset()
        self._fresh()

    def _patch(self, part: str, **fields) -> None:
        self.c[part] = {**self.c[part], **fields}  # replace, so Protocol.feed sees the change

    @staticmethod
    def _text(a: str, start: int, n: int) -> str:
        return "".join(a[i] if i < len(a) else " " for i in range(start, start + n))

    def decode(self, p: bytes) -> None:
        if len(p) < 3:
            return
        if p[1] == 19:
            self._record(p)
        elif p[1] == 2 and p[2] == 12:  # clear display
            self.c["PacketType"] = "Rows"
            self.c["SwimmingEvent"] = {"EventId": self.event}
            self.c["SwimmingRows"] = {"EventId": self.event}

    def _record(self, p: bytes) -> None:
        if len(p) < 12:
            return
        a = ascii_text(p)
        sub = _to_int(p[6:8].decode("utf-8", "replace"))
        rec = _to_int(p[8:10].decode("utf-8", "replace"))
        n = len(p) - 11
        if rec == 0:
            self.c["PacketType"] = "Event"
            self._patch("SwimmingEvent", EventName=self._text(a, 10, n))
        elif rec == 1:
            if sub == 0:
                self.c["PacketType"] = "Event"
                self._patch("SwimmingEvent", EventRecord=self._text(a, 10, n))
            elif sub == 20 and n == 8 and len(p) >= 18:
                self.c["PacketType"] = "Rows"
                clock = dict(ClockMinutesTens=a[10], ClockMinutesOnes=a[11], ClockSecondTens=a[13],
                             ClockSecondOnes=a[14], ClockTenthsSecond=a[16], ClockHundreths=a[17])
                self._patch("SwimmingRows", **clock)
                self._patch("SwimmingEvent", **clock)
        else:
            lane = _to_int(p[10:12].decode("utf-8", "replace"))
            if lane > 0:
                self.c["PacketType"] = "Rows"
                block = (lane - 1) // 3 if lane <= 9 else 0
                first = block * 3
                self._patch("SwimmingRows", RowType=("Row1To3", "Row4To6", "Row7To9")[block],
                            RowANumber=first + 1, RowBNumber=first + 2, RowCNumber=first + 3)
                if lane <= 9 and len(p) >= 46:
                    row = "ABC"[(lane - 1) % 3]
                    self._patch("SwimmingRows", **{
                        f"Row{row}Lane": a[10] + a[11], f"Row{row}SwimmerName": self._text(a, 13, 16),
                        f"Row{row}TeamName": self._text(a, 30, 4), f"Row{row}Clock": self._text(a, 35, 8),
                        f"Row{row}Place": a[44] + a[45]})


PROTOCOLS = {
    "SwissTiming_Basketball": lambda: MainProtocol(SwissBasketball()),
    "SwissTiming_Hockey": lambda: MainProtocol(SwissHockey()),
    "SwissTiming_WaterPolo": lambda: MainProtocol(SwissWaterPolo()),
    "SwissTimmingTransmission_Basketball": lambda: TransmissionProtocol(SwissTransmissionBasketball()),
    "SwissTimingTransmission_Swimming": lambda: TransmissionProtocol(SwissTransmissionSwimming()),
}
