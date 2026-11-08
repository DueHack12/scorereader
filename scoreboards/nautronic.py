"""Nautronic scoreboards: the "Main" (NG22 style) family and the NG 08 / NT-Pult basketball family.

Ids: Nautronic_Basketball, Nautronic_Hockey, NautronicNg08_Basketball, NautronicNTPult_Basketball.
See docs/vendors/nautronic.md for the wire formats and field tables.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find_pair
from .common import ascii_text, bcd, bcd_zero_blank, dec

__all__ = ["PROTOCOLS"]

# --------------------------------------------------------------------------- private Nautronic helpers
_BLANK_REF = "ABCDF"    # nibble characters that read as blank in the "optional" digit reader
_BLANK_PLAIN = "ABCEF"  # ... and in the "plain" digit reader (note: not the same set)


def _nibble(sub: bytes, high: int, off: int, blanks: str):
    """Hex nibble of sub[off + 2] (high nibble if `high`), blank for the given characters; None if out of range."""
    i = off + 2
    if i >= len(sub):
        return None
    ch = f"{sub[i]:02X}"[0 if high else 1]
    return " " if ch in blanks else ch


def _digit(sub: bytes, high: int, off: int):
    """Digit reader that reports a missing byte as None, so callers can leave the field untouched."""
    return _nibble(sub, high, off, _BLANK_REF)


def _digit_str(sub: bytes, high: int, off: int) -> str:
    """Digit reader that reports a missing byte as a blank."""
    ch = _nibble(sub, high, off, _BLANK_PLAIN)
    return " " if ch is None else ch


_PENALTY = {"4": ("5", " "), "1": ("2", " "), "3": ("2", "2"), "5": ("2", "5")}
_TIMEOUT = {0: "0", 1: "1", 5: "2", 21: "3"}
_FOUL = {0: "0", 1: "1", 3: "2", 7: "3", 15: "4", 31: "5"}


def _penalty(ch: str):
    return _PENALTY.get(ch, (" ", " "))


def _timeout(b: int) -> str:
    return _TIMEOUT.get(b, " ")


def _foul(b: int) -> str:
    return _FOUL.get(b, " ")


# --------------------------------------------------------------------------- "Main" family: FF 71 frames
class _MainProtocol(Protocol):
    """Frames start with FF 71 and run up to the next FF 71. Header: FF 71 L ?? 80 ??, then sub-packets."""

    def extract(self):
        buf = self.buf
        while True:
            n = find_pair(buf, 0xFF, 0x71)
            if n < 0:
                return
            n2 = find_pair(buf, 0xFF, 0x71, n + 1)
            if n2 < 0:
                if n > 1:
                    del buf[: n - 1]  # drop garbage ahead of the frame start
                return
            pkt = bytes(buf[n - 1 : n2 - 1])
            del buf[: n2 - 1]
            # ScoreConnect's check: at least 5 bytes, byte 4 == 0x80, and len - (L + 4) < 3 (an upper bound only)
            if len(pkt) >= 5 and pkt[4] == 0x80 and len(pkt) - (pkt[2] + 4) < 3:
                yield pkt
            else:
                self.reject()


class _SubPacketDecoder(Decoder):
    """Walks the sub-packets (length byte, then id hi, id lo, data...) and dispatches on the 16-bit id."""

    def __init__(self):
        super().__init__()
        self._handlers = self.handlers()

    def handlers(self) -> dict:
        raise NotImplementedError

    def decode(self, packet: bytes) -> None:
        i = 6
        while i < len(packet):
            n = packet[i]
            if i + n + 1 > len(packet) or n < 3:
                break
            sub = bytes(packet[i + 1 : i + 1 + n])
            fn = self._handlers.get((sub[0] << 8) | sub[1])
            if fn:
                fn(sub)
            i += n + 1

    # shared helpers
    def _put(self, sub: bytes, high: int, off: int, key: str) -> str | None:
        v = _digit(sub, high, off)
        if v is not None:
            self.c[key] = v
        return v

    def _names(self, sub: bytes, home_len: int) -> None:
        if sub[2] == 0 and len(sub) > 8:
            self.c["HomeTeamName"] = ascii_text(sub[8 : 8 + home_len]).lstrip()
        elif sub[2] == 128 and len(sub) > 8:
            self.c["GuestTeamName"] = ascii_text(sub[8:28]).lstrip()

    def _penalties(self, sub: bytes, side: str) -> None:
        for n in range(1, 4):
            b = 5 * (n - 1)
            p = f"{side}PenaltyPlayer{n}"
            self._put(sub, 0, b, p + "Tens")
            self._put(sub, 0, b + 1, p + "Ones")
            self.c[p + "ClockMinutesTens"] = " "
            self._put(sub, 0, b + 2, p + "ClockMinutesOnes")
            self._put(sub, 0, b + 3, p + "ClockSecondTens")
            self._put(sub, 0, b + 4, p + "ClockSecondOnes")

    def _penalty_types(self, sub: bytes, side: str) -> None:
        for n, off in ((1, 2), (2, 4), (3, 6)):
            v = _digit(sub, 0, off)
            if v is not None:
                t1, t2 = _penalty(v)
                self.c[f"{side}Player{n}PenaltyType1"] = t1
                self.c[f"{side}Player{n}PenaltyType2"] = t2


class NautronicBasketball(_SubPacketDecoder):
    contract = "Basketball"
    event = "Basketball"

    def __init__(self):
        super().__init__()
        self._empty_timeout = 0

    def reset(self) -> None:
        super().reset()
        self._empty_timeout = 0

    def handlers(self) -> dict:
        return {
            0xC0D3: lambda s: self._names(s, 10) if len(s) >= 18 or s[2] == 128 else None,
            0x400C: self._clock, 0x4000: self._home_score, 0x407C: self._guest_score, 0x4006: self._period,
            0x4013: self._timeout_clock, 0x4093: self._timeout_clock,
            0x4020: lambda s: self._players(s, "HomePlayer{}"), 0x40A0: lambda s: self._players(s, "GuestPlayer{}"),
            0x4050: lambda s: self._players(s, "HomePlayer{}Points"),
            0x40D0: lambda s: self._players(s, "GuestPlayer{}Points"),
            0x8005: self._possession,
            0x8007: lambda s: self._set_foul(s, "HomeFoulOnes", 3),
            0x8087: lambda s: self._set_foul(s, "GuestFoulOnes", 3),
            0x8080: lambda s: self._set_timeouts(s, "GuestTimeouts"),
            0x8000: lambda s: self._set_timeouts(s, "HomeTimeouts"),
            0x40CA: self._shot_clock,
        }

    def _clock(self, sub: bytes) -> None:
        last = _digit(sub, 0, 3)
        if last is None:
            return
        if last != " ":
            for off, key in enumerate(("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")):
                self._put(sub, 0, off, key)
            self.c["ClockMode"] = ":"
            self.c["ClockTenthsSecond"] = "0"
        else:
            self.c["ClockMinutesTens"] = self.c["ClockMinutesOnes"] = "0"
            self._put(sub, 0, 0, "ClockSecondTens")
            self._put(sub, 0, 1, "ClockSecondOnes")
            self._put(sub, 0, 2, "ClockTenthsSecond")
            self.c["ClockMode"] = "."
        v = _digit(sub, 1, 2)
        if v is not None:
            self.c["InternalClockStatus"] = "R" if v == "6" else "S"

    def _home_score(self, sub: bytes) -> None:
        v = _digit(sub, 1, 1)
        if v is not None:
            self.c["HomeScoreHundreds"] = "1" if v != "0" else " "  # any non-"0" nibble (even blank) shows a 1
        self._put(sub, 0, 0, "HomeScoreTens")
        self._put(sub, 0, 1, "HomeScoreOnes")

    def _guest_score(self, sub: bytes) -> None:
        v = _digit(sub, 1, 5)
        if v is not None:
            self.c["GuestScoreHundreds"] = "1" if v != "0" else " "
        self._put(sub, 0, 4, "GuestScoreTens")
        self._put(sub, 0, 5, "GuestScoreOnes")

    def _period(self, sub: bytes) -> None:
        self._put(sub, 0, 1, "Period")

    def _timeout_clock(self, sub: bytes) -> None:
        if len(sub) <= 4:
            return
        if (sub[3] & 0xF0) == 0x20:
            self._put(sub, 0, 0, "TimeoutClockMinutesOnes")
            self._put(sub, 0, 1, "TimeoutClockSecondTens")
            self._put(sub, 0, 2, "TimeoutClockSecondOnes")
            self._empty_timeout = 0
        elif sub[3] == 0x0F:
            self._empty_timeout += 1
            if self._empty_timeout > 10:  # blank only after more than 10 consecutive "empty" updates
                for k in ("TimeoutClockMinutesOnes", "TimeoutClockSecondTens", "TimeoutClockSecondOnes"):
                    self.c[k] = " "

    def _players(self, sub: bytes, fmt: str) -> None:
        if len(sub) > 14:
            for n in range(1, 6):
                self.c[fmt.format(n)] = _digit_str(sub, 0, 2 * n - 2) + _digit_str(sub, 0, 2 * n - 1)

    def _possession(self, sub: bytes) -> None:
        v = _digit(sub, 1, 0)
        if v is not None:
            self.c["HomePossession"] = "<" if v == "1" else " "
            self.c["GuestPossession"] = ">" if v == "0" else " "

    def _set_foul(self, sub: bytes, key: str, need: int) -> None:
        if len(sub) >= need:
            self.c[key] = _foul(sub[2])

    def _set_timeouts(self, sub: bytes, key: str) -> None:
        if len(sub) >= 4:
            self.c[key] = _timeout(sub[2])

    def _shot_clock(self, sub: bytes) -> None:
        if len(sub) != 5:
            return
        if sub[4] == 1:
            if sub[2] != 0 or sub[3] != 0:
                self.c["ShotClockSecondTens"] = " "
                self._put(sub, 0, 0, "ShotClockSecondOnes")
                self._put(sub, 0, 1, "ShotClockTenthsSecond")
        else:
            self.c["ShotClockTenthsSecond"] = " "
            self._put(sub, 0, 0, "ShotClockSecondTens")
            self._put(sub, 0, 1, "ShotClockSecondOnes")


class NautronicHockey(_SubPacketDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"

    def handlers(self) -> dict:
        return {
            0xC0D3: lambda s: self._names(s, 8),
            0x4000: self._home_score, 0x407C: self._guest_score, 0x400C: self._clock,
            0x4011: lambda s: self._penalties(s, "Home"), 0x4091: lambda s: self._penalties(s, "Guest"),
            # the two timeout/penalty-type packets are crossed over on the wire: 0x8000 carries the guest's timeouts
            # with the home's penalty types, 0x8080 the home's timeouts with the guest's penalty types
            0x8000: self._cross_a, 0x8080: self._cross_b,
        }

    def _home_score(self, sub: bytes) -> None:
        self._put(sub, 0, 0, "HomeScoreTens")
        self._put(sub, 0, 1, "HomeScoreOnes")
        self._put(sub, 0, 4, "HomeShotOnGoalTens")
        self._put(sub, 0, 5, "HomeShotOnGoalOnes")
        self._put(sub, 0, 7, "Period")

    def _guest_score(self, sub: bytes) -> None:
        self._put(sub, 0, 4, "GuestScoreTens")
        self._put(sub, 0, 5, "GuestScoreOnes")
        self._put(sub, 0, 8, "GuestShotOnGoalTens")
        self._put(sub, 0, 9, "GuestShotOnGoalOnes")

    def _clock(self, sub: bytes) -> None:
        for off, key in enumerate(("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes")):
            self._put(sub, 0, off, key)
        v = _digit(sub, 1, 2)
        if v is not None:
            self.c["InternalClockStatus"] = "R" if v == "6" else "S"
        self.c["ClockMode"] = ":"

    def _cross_a(self, sub: bytes) -> None:
        self.c["GuestFullTimeoutsRemaining"] = _timeout(sub[2])
        self.c["GuestPartialTimeoutsRemaining"] = " "
        self._penalty_types(sub, "Home")

    def _cross_b(self, sub: bytes) -> None:
        self.c["HomeFullTimeoutsRemaining"] = _timeout(sub[2])
        self.c["HomePartialTimeoutsRemaining"] = " "
        self._penalty_types(sub, "Guest")


# --------------------------------------------------------------------------- NG 08 family
class _Ng08Protocol(Protocol):
    """A packet ends at the first byte >= 0x80 and starts at the first byte in {3, 10, 40, 70} before it."""

    _STARTS = (10, 40, 70, 3)

    def extract(self):
        buf = self.buf
        while True:
            end = next((i for i, b in enumerate(buf) if b >= 0x80), -1)
            if end < 0:
                return
            start = next((i for i, b in enumerate(buf) if b in self._STARTS), -1)
            pkt = bytes(buf[start : end + 1]) if 0 <= start < end else None
            del buf[: end + 1]
            if pkt is None:
                self.reject()  # terminator with no start byte before it
            else:
                yield pkt


def _nb(b: int, i: int) -> str:
    """BCD nibble (0 = low, 1 = high); A-F read as blank."""
    return bcd(b, i)


class _Ng08Basketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 2:
            return
        a, k = p[0], p[1]
        c = self.c
        if k == 12 and a in (10, 40) and len(p) > 5:
            self._clock12(p)
        elif k == 13 and a in (10, 40) and len(p) > 4:
            self._clock13(p)
        elif k == 17 and a == 10 and len(p) > 4:
            self._shot(p, 2, 3)
        elif k == 0 and a == 40 and len(p) > 5:
            self._shot(p, 4, 2)
        elif k == 18 and a == 10 and len(p) > 3:
            self._partial_shot(p)
        elif k == 0 and a == 10 and len(p) > 6:
            c["Period"] = _nb(p[4], 0)
            c["HomeScoreHundreds"] = "1" if _nb(p[2], 1) == "2" else " "
            c["HomeScoreTens"] = _nb(p[2], 0)
            c["HomeScoreOnes"] = _nb(p[3], 0)
            c["GuestScoreHundreds"] = "1" if _nb(p[5], 1) == "2" else " "
            c["GuestScoreTens"] = _nb(p[5], 0)
            c["GuestScoreOnes"] = _nb(p[6], 0)
        elif a == 3 and k == 5 and len(p) > 13 and p[2] == 10 and p[3] == 5:
            self._score_foul(p)
        # (10, 48) carries a timeout on/off flag in p[2]; ScoreConnect tracks it but never uses it

    def _clock12(self, p: bytes) -> None:
        c = self.c
        c["InternalClockStatus"] = "S" if _nb(p[4], 1) == "2" else "R"
        if _nb(p[2], 1) != "2" and _nb(p[5], 1) != "2":
            last = _nb(p[5], 0)
            if last != " ":
                c["ClockMinutesTens"], c["ClockMinutesOnes"] = _nb(p[2], 0), _nb(p[3], 0)
                c["ClockSecondTens"], c["ClockSecondOnes"] = _nb(p[4], 0), last
                c["ClockTenthsSecond"], c["ClockMode"] = "0", ":"
            else:
                c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
                c["ClockSecondTens"], c["ClockSecondOnes"] = _nb(p[2], 0), _nb(p[3], 0)
                c["ClockTenthsSecond"], c["ClockMode"] = _nb(p[4], 0), "."

    def _clock13(self, p: bytes) -> None:
        c = self.c
        c["InternalClockStatus"] = "S" if _nb(p[3], 1) == "2" else "R"
        if c["InternalClockStatus"] != "S":
            last = _nb(p[4], 0)
            if last != " ":  # note: the tens of minutes is not touched in this layout
                c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"] = _nb(p[2], 0), _nb(p[3], 0), last
                c["ClockTenthsSecond"], c["ClockMode"] = "0", ":"
            else:
                c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
                c["ClockSecondOnes"], c["ClockTenthsSecond"] = _nb(p[2], 0), _nb(p[3], 0)
                c["ClockMode"] = "."

    def _shot(self, p: bytes, check: int, start: int) -> None:
        c = self.c
        if _nb(p[check], 0) == "1":
            c["ShotClockSecondTens"] = "0"
            c["ShotClockSecondOnes"] = _nb(p[start], 0)
            c["ShotClockTenthsSecond"] = _nb(p[start + 1], 0)
            self._lt5 = True
        else:
            c["ShotClockSecondTens"] = _nb(p[start], 0)
            c["ShotClockSecondOnes"] = _nb(p[start + 1], 0)
            self._lt5 = False

    _lt5 = False

    def _partial_shot(self, p: bytes) -> None:
        c = self.c
        first = _nb(p[2], 0)
        if self._lt5 or first > "2":
            c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"] = first, _nb(p[3], 0)
        else:
            c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = first, _nb(p[3], 0)

    def _score_foul(self, p: bytes) -> None:
        side = "Home" if p[4] == 0 else "Guest" if p[4] == 1 else None
        if side is None:
            return
        c = self.c
        h, t, o = dec(p[11], 2, 3), dec(p[11], 1, 3), dec(p[11], 0, 3)
        c[f"{side}ScoreHundreds"] = " " if h == "0" else h
        c[f"{side}ScoreTens"] = " " if h == "0" and t == "0" else t
        c[f"{side}ScoreOnes"] = o
        ft = dec(p[12], 1, 2)
        c[f"{side}FoulTens"] = " " if ft == "0" else ft
        c[f"{side}FoulOnes"] = dec(p[12], 0, 3)

    def reset(self) -> None:
        super().reset()
        self._lt5 = False


class _NtPultBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def decode(self, p: bytes) -> None:
        if len(p) < 2:
            return
        a, k, c = p[0], p[1], self.c
        if k == 12 and a in (10, 40) and len(p) > 5:
            c["InternalClockStatus"] = "S" if _nb(p[4], 1) == "2" else "R"
            last = _nb(p[5], 0)
            if last != " ":
                c["ClockMinutesTens"], c["ClockMinutesOnes"] = _nb(p[2], 0), _nb(p[3], 0)
                c["ClockSecondTens"], c["ClockSecondOnes"] = _nb(p[4], 0), last
                c["ClockTenthsSecond"], c["ClockMode"] = "0", ":"
            else:
                c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
                c["ClockSecondTens"], c["ClockSecondOnes"] = _nb(p[2], 0), _nb(p[3], 0)
                c["ClockTenthsSecond"], c["ClockMode"] = _nb(p[4], 0), "."
        elif k == 13 and a in (10, 40) and len(p) > 4:
            c["InternalClockStatus"] = "S" if _nb(p[3], 1) == "2" else "R"
            if c["InternalClockStatus"] != "S":
                last = _nb(p[4], 0)
                if last != " ":
                    c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"] = (
                        _nb(p[2], 0), _nb(p[3], 0), last)
                    c["ClockTenthsSecond"], c["ClockMode"] = "0", ":"
                else:
                    c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
                    c["ClockSecondOnes"], c["ClockTenthsSecond"] = _nb(p[2], 0), _nb(p[3], 0)
                    c["ClockMode"] = "."
        elif ((k == 0 and a == 40) or (k == 18 and a == 10)) and len(p) > 3:
            c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = _nb(p[2], 0), _nb(p[3], 0)
        elif k == 17 and a == 10 and len(p) > 4:
            c["ShotClockSecondTens"], c["ShotClockSecondOnes"] = _nb(p[3], 0), _nb(p[4], 0)
        elif a == 10 and 3 < len(p) <= 6 and k in (0, 3):
            side = "Home" if k == 0 else "Guest"
            hundreds = "1" if _nb(p[2], 1) == "2" else " "
            c[f"{side}ScoreHundreds"] = hundreds
            c[f"{side}ScoreTens"] = bcd_zero_blank(p[2], 0) if hundreds == " " else _nb(p[2], 0)
            c[f"{side}ScoreOnes"] = _nb(p[3], 0)
        elif a == 10 and k in (5, 8) and len(p) > 4:
            flag = _nb(p[4], 1) == "2"
            c["HomePossession"] = "<" if (k == 5 and flag) else " "
            c["GuestPossession"] = ">" if (k == 8 and flag) else " "
            if _nb(p[3], 0) != " " and _nb(p[4], 0) != " ":
                c["TimeoutClockMinutesOnes"] = _nb(p[2], 0)
                c["TimeoutClockSecondTens"] = _nb(p[3], 0)
                c["TimeoutClockSecondOnes"] = _nb(p[4], 0)
            if c.get("InternalClockStatus") == "R":  # timeout clock is only shown while the game clock is stopped
                c["TimeoutClockMinutesOnes"] = c["TimeoutClockSecondTens"] = c["TimeoutClockSecondOnes"] = " "


PROTOCOLS = {
    "Nautronic_Basketball": lambda: _MainProtocol(NautronicBasketball()),
    "Nautronic_Hockey": lambda: _MainProtocol(NautronicHockey()),
    "NautronicNg08_Basketball": lambda: _Ng08Protocol(_Ng08Basketball()),
    "NautronicNTPult_Basketball": lambda: _Ng08Protocol(_NtPultBasketball()),
}
