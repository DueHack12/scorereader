"""Eversan scoreboards (ScoreConnect namespaces Eversan.Main, Model9364, Model9775/Model9694).

Three framings, all over a serial stream of 7-bit ASCII digits plus a few flag bytes:

* **Legacy** (``Eversan_*``): a packet starts with 0x01 or 0x02 and its second byte is the total length.
  Byte 2 is a checksum: sum of bytes 6..L-1 for packets longer than 15 bytes, otherwise XOR of bytes 3..L-1.
* **V2** (``EversanV2_*``): a packet starts with the console's sport code (the catalog ``vendor_sport_code``,
  which ScoreConnect lets the operator override), the second byte is the total length, and the checksum is the
  XOR of bytes 4..L-1, stored at byte 3 (codes 70, 129) or byte 2 (codes 131, 135; 129 and 135 also accept the
  other position).
* **Model 9xxx** (``EversanModel*``): no length or checksum; a packet runs from one start byte (129 for the
  9364, 131 for the 9775/9694) to the next one.

See docs/vendors/eversan.md for the field tables.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char, ascii_digit_or_blank, sum8, xor8

__all__ = ["PROTOCOLS", "EversanLegacyProtocol", "EversanV2Protocol", "Eversan9xxxProtocol"]


# --------------------------------------------------------------------------- private helpers
def _ea(b: int) -> str:
    """Eversan character: low 7 bits as ASCII; ":" (the colon lamp) and non-printables read as blank."""
    c = ascii_char(b & 0x7F)
    return " " if c == ":" else c


def _period(b: int) -> str:
    """Period from the lamp bits in the low nibble of the flag byte (8, 12, 14, 15 -> 1..4)."""
    return {8: "1", 12: "2", 14: "3", 15: "4"}.get(b & 0x0F, " ")


class _Decoder(Decoder):
    """Eversan decoder base: ``layouts`` maps the first byte to ``(minimum length, method name)``.

    ``None`` as a key is the fallback for layouts that don't look at the first byte. Short packets are ignored.
    """

    layouts: dict = {}

    def decode(self, p: bytes) -> None:
        if not p:
            return
        entry = self.layouts.get(p[0], self.layouts.get(None))
        if entry is not None and len(p) >= entry[0]:
            getattr(self, entry[1])(p)

    def _put(self, p: bytes, fields: dict) -> None:
        for name, i in fields.items():
            self.c[name] = _ea(p[i])

    def _clock(self, p: bytes, i: int) -> None:
        """mm ss t starting at offset i. "00" minutes switches to seconds.tenths display."""
        c = self.c
        if _ea(p[i]) == "0" and _ea(p[i + 1]) == "0":
            c["ClockMode"] = "."
            c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"] = (_ea(p[i + 2]), _ea(p[i + 3]),
                                                                                  _ea(p[i + 4]))
        else:
            c["ClockMode"] = ":"
            c["ClockMinutesTens"], c["ClockMinutesOnes"] = _ea(p[i]), _ea(p[i + 1])
            c["ClockSecondTens"], c["ClockSecondOnes"] = _ea(p[i + 2]), _ea(p[i + 3])
            c["ClockTenthsSecond"] = "0"


# --------------------------------------------------------------------------- basketball
class _Basketball(_Decoder):
    contract = "Basketball"
    event = "Basketball"

    def _scores(self, p):
        c = self.c
        c["HomeScoreHundreds"] = ascii_digit_or_blank(ord(_ea(p[11])))
        c["GuestScoreHundreds"] = ascii_digit_or_blank(ord(_ea(p[14])))
        self._put(p, {"HomeScoreTens": 12, "HomeScoreOnes": 13, "GuestScoreTens": 15, "GuestScoreOnes": 16})

    def _fouls(self, p):
        self._put(p, {"HomeFoulTens": 17, "HomeFoulOnes": 18, "GuestFoulTens": 23, "GuestFoulOnes": 24,
                      "FoulPlayerTens": 19, "FoulPlayerOnes": 20, "FoulPlayerNumberOfFouls": 22})

    def _bonuses(self, p):
        self.c["HomeBonus"] = "B" if p[5] & 0x40 else " "
        self.c["GuestBonus"] = "B" if p[5] & 0x20 else " "

    def _period_possession(self, p):
        self.c["Period"] = _period(p[5])
        home = not p[5] & 0x10
        self.c["HomePossession"], self.c["GuestPossession"] = ("<", " ") if home else (" ", ">")

    def _main(self, p):
        self._clock(p, 6)
        self._scores(p)
        self._fouls(p)
        self._period_possession(p)
        self._bonuses(p)


class _Basketball25(_Basketball):
    layouts = {1: (25, "_main"), 18: (25, "_main"), 2: (13, "_shot")}

    def _shot(self, p):
        self._put(p, {"ShotClockSecondTens": 11, "ShotClockSecondOnes": 12})


class _Basketball106(_Basketball):
    """Code 29: scores/fouls at different offsets, and the possession bit is inverted."""

    layouts = {1: (29, "_main")}

    def _main(self, p):
        self._clock(p, 6)
        self._put(p, {"HomeScoreHundreds": 11, "HomeScoreTens": 12, "HomeScoreOnes": 13,
                      "GuestScoreHundreds": 15, "GuestScoreTens": 16, "GuestScoreOnes": 17,
                      "HomeFoulTens": 18, "HomeFoulOnes": 19, "HomeTimeouts": 20, "GuestTimeouts": 24,
                      "GuestFoulTens": 25, "GuestFoulOnes": 26, "FoulPlayerTens": 21, "FoulPlayerOnes": 22,
                      "FoulPlayerNumberOfFouls": 23, "Period": 14, "ShotClockSecondTens": 27,
                      "ShotClockSecondOnes": 28})
        home = bool(p[5] & 0x10)
        self.c["HomePossession"], self.c["GuestPossession"] = ("<", " ") if home else (" ", ">")
        self._bonuses(p)
        self.c["HomeDoubleBonus"] = "B" if p[5] & 0x08 else " "
        self.c["GuestDoubleBonus"] = "B" if p[5] & 0x04 else " "


class _Basketball555(_Basketball):
    layouts = {129: (27, "_main")}

    def _main(self, p):
        super()._main(p)
        self._put(p, {"ShotClockSecondTens": 25, "ShotClockSecondOnes": 26})


# --------------------------------------------------------------------------- football
class _Football(_Decoder):
    contract = "Football"
    event = "Football"
    layouts = {1: (24, "_main"), 129: (24, "_main")}
    togo, ballon = 16, 18  # offsets of the tens digits

    def _main(self, p):
        self._clock(p, 6)
        self._put(p, {"HomeScoreTens": 12, "HomeScoreOnes": 13, "GuestScoreTens": 14, "GuestScoreOnes": 15,
                      "ToGoTens": self.togo, "ToGoOnes": self.togo + 1,
                      "BallOnTens": self.ballon, "BallOnOnes": self.ballon + 1,
                      "Down": 20, "Quarter": 21, "HomeTimeouts": 22, "GuestTimeouts": 23})
        home = not p[4] & 0x40
        self.c["HomePossession"], self.c["GuestPossession"] = ("<", " ") if home else (" ", ">")


class _Football111(_Football):
    togo, ballon = 18, 16  # to-go and ball-on swapped


class _Football9364(_Football):
    """Model 9364: same fields, but no first-byte check (the framing already keyed on 129)."""

    layouts = {None: (24, "_main")}


# --------------------------------------------------------------------------- lacrosse / soccer
class _LacrosseSoccer(_Decoder):
    """Clock at 5; two layouts, selected by the first byte (1 = legacy, 135 = V2)."""

    layouts = {1: (15, "_legacy"), 135: (18, "_v2")}

    def _legacy(self, p):
        self._clock(p, 5)
        self._put(p, {"HomeScoreTens": 10, "HomeScoreOnes": 11, "GuestScoreTens": 12, "GuestScoreOnes": 13,
                      "Period": 14})

    def _v2(self, p):
        self._clock(p, 5)
        self._put(p, {"HomeScoreTens": 16, "HomeScoreOnes": 17, "GuestScoreTens": 11, "GuestScoreOnes": 12,
                      "Period": 10})


class _Lacrosse(_LacrosseSoccer):
    contract = "HockeyLacrosse"
    event = "Lacrosse"


class _Soccer(_LacrosseSoccer):
    contract = "Soccer"
    event = "Soccer"


class _Lacrosse9364(_Decoder):
    contract = "HockeyLacrosse"
    event = "Lacrosse"
    layouts = {None: (24, "_main")}

    def _main(self, p):
        self._clock(p, 6)
        self._put(p, {"HomeScoreTens": 12, "HomeScoreOnes": 13, "GuestScoreTens": 14, "GuestScoreOnes": 15,
                      "HomeShotOnGoalTens": 19, "HomeShotOnGoalOnes": 21, "HomeTimeOut": 22, "GuestTimeOut": 23})
        self.c["HomePlayerPopUp"] = _ea(p[20]) + _ea(p[16])
        self.c["GuestPlayerPopUp"] = _ea(p[17]) + _ea(p[18])


# --------------------------------------------------------------------------- baseball
def _inning_state(c: dict) -> tuple:
    """(inning number as 2 chars, "T" or "B") from which innings already have runs entered.

    Scans from inning 10 down to 1 for the latest inning with a guest entry: a home entry too means the
    inning is complete (reported as the next inning, top), no home entry means the home half is to come
    (bottom). With nothing entered it reports inning 01.
    """
    num, half = 10, "T"
    for n in range(10, 0, -1):
        guest, home = c.get(f"GuestInning{n}", " "), c.get(f"HomeInning{n}", " ")
        if guest != " " and home != " ":
            num, half = num + 1, "T"
            break
        if guest != " ":
            half = "B"
            break
        if num > 1:
            num -= 1
    return f"{num:02d}", half


class _Baseball(_Decoder):
    contract = "BaseballSoftball"
    event = "Baseball"
    layouts = {70: (42, "_main"), 135: (42, "_main")}

    def _main(self, p):
        f = {"Balls": 7, "Strikes": 8, "Outs": 9, "GuestRunTens": 12, "GuestRunOnes": 13, "GuestHitsTens": 14,
             "GuestHitsOnes": 15, "GuestErrors": 16, "HomeRunTens": 17, "HomeRunOnes": 18, "HomeHitsTens": 19,
             "HomeHitsOnes": 20, "HomeErrors": 21}
        for n in range(1, 11):
            f[f"GuestInning{n}"] = 21 + n
            f[f"HomeInning{n}"] = 31 + n
        self._put(p, f)
        inning, half = _inning_state(self.c)
        self.c["TopBottomInning"] = half
        self.c["TopOfInning"], self.c["BottomOfInning"] = (".", " ") if half == "T" else (" ", ".")
        self.c["InningTens"], self.c["InningOnes"] = inning[0], inning[1]


# --------------------------------------------------------------------------- hockey
class _Hockey(_Decoder):
    """Penalty boxes are 6 bytes per player: number tens/ones, minutes tens (not always sent), m, ss."""

    contract = "HockeyLacrosse"
    event = "Hockey"

    def _penalties(self, p, bases: dict, minutes_tens_from_stream: bool) -> None:
        for (side, n), b in bases.items():
            pre = f"{side}PenaltyPlayer{n}"
            self.c[pre + "Tens"], self.c[pre + "Ones"] = _ea(p[b]), _ea(p[b + 1])
            self.c[pre + "ClockMinutesTens"] = _ea(p[b + 2]) if minutes_tens_from_stream else " "
            self.c[pre + "ClockMinutesOnes"] = _ea(p[b + 3])
            self.c[pre + "ClockSecondTens"], self.c[pre + "ClockSecondOnes"] = _ea(p[b + 4]), _ea(p[b + 5])


class _Hockey131(_Hockey):
    """V2 code 131 / Model 9694 layout. ``minutes_tens`` is True for the 9694, which sends the tens digit."""

    layouts = {131: (50, "_main")}
    minutes_tens = False

    def _main(self, p):
        self._clock(p, 6)
        self._put(p, {"HomeScoreTens": 13, "HomeScoreOnes": 14, "GuestScoreTens": 17, "GuestScoreOnes": 18,
                      "Period": 15, "HomeShotOnGoalTens": 22, "HomeShotOnGoalOnes": 23,
                      "GuestShotOnGoalTens": 24, "GuestShotOnGoalOnes": 25})
        self._penalties(p, {("Home", 1): 26, ("Home", 2): 32, ("Guest", 1): 38, ("Guest", 2): 44},
                        self.minutes_tens)


class _Hockey9694(_Hockey131):
    minutes_tens = True


class _Hockey9775(_Hockey):
    layouts = {None: (44, "_main")}

    def _main(self, p):
        self._clock(p, 7)
        self._put(p, {"HomeScoreTens": 12, "HomeScoreOnes": 13, "GuestScoreTens": 14, "GuestScoreOnes": 15,
                      "HomeShotOnGoalOnes": 17, "GuestShotOnGoalOnes": 19})
        self._penalties(p, {("Home", 1): 20, ("Home", 2): 26, ("Guest", 1): 32, ("Guest", 2): 38}, False)


# --------------------------------------------------------------------------- protocols
class EversanLegacyProtocol(Protocol):
    """Start byte 0x01 or 0x02, length at byte 1, checksum at byte 2."""

    def extract(self):
        buf = self.buf
        while True:
            i = next((k for k, b in enumerate(buf) if b in (1, 2)), -1)
            if i < 0:
                buf.clear()
                return
            del buf[:i]
            if len(buf) < 2:
                return
            n = buf[1]
            if n < 3:
                del buf[:1]
                self.reject()
                continue
            if len(buf) < n:
                return
            pkt = bytes(buf[:n])
            del buf[:n]
            check = sum8(pkt, 6, n) if n > 15 else xor8(pkt, 2, n)
            if check == pkt[2]:
                yield pkt
            else:
                self.reject()


class EversanV2Protocol(Protocol):
    """Start byte = the console's sport code; length at byte 1; XOR of bytes 4.. at ``sum_at`` (or ``alt_at``).

    ScoreConnect finds the first byte >= 128 for 128+ codes and silently drops a frame that starts with another
    byte; this version looks for the configured code itself, which gives the same result on a clean stream and
    resynchronises faster after noise.
    """

    _CHECK = {129: (3, 2), 135: (2, 3), 131: (2, -1)}  # code -> (checksum byte, alternate checksum byte)

    def __init__(self, decoder: Decoder, code: int):
        super().__init__(decoder)
        self.code = code
        self.sum_at, self.alt_at = self._CHECK.get(code, (3, -1))

    def extract(self):
        buf = self.buf
        while True:
            i = find(buf, self.code)
            if i < 0:
                buf.clear()
                return
            del buf[:i]
            if len(buf) < 2:
                return
            n = buf[1]
            if n < 5:
                del buf[:1]
                self.reject()
                continue
            if len(buf) < n:
                return
            pkt = bytes(buf[:n])
            del buf[:n]
            x = xor8(pkt, 4)
            if x == pkt[self.sum_at] or (self.alt_at > 0 and x == pkt[self.alt_at]):
                yield pkt
            else:
                self.reject()


class Eversan9xxxProtocol(Protocol):
    """Packets run from one start byte to the next. A packet is released when the next start byte arrives."""

    def __init__(self, decoder: Decoder, code: int):
        super().__init__(decoder)
        self.code = code

    def extract(self):
        buf = self.buf
        while True:
            i = find(buf, self.code)
            if i < 0:
                buf.clear()
                return
            j = find(buf, self.code, i + 1)
            if j < 0:
                del buf[:i]
                return
            pkt = bytes(buf[i:j])
            del buf[:j]
            yield pkt


PROTOCOLS = {
    "Eversan_Basketball_Code25": lambda: EversanLegacyProtocol(_Basketball25()),
    "Eversan_Basketball_Code29": lambda: EversanLegacyProtocol(_Basketball106()),
    "Eversan_Football": lambda: EversanLegacyProtocol(_Football()),
    "Eversan_Lacrosse_Code15": lambda: EversanLegacyProtocol(_Lacrosse()),
    "Eversan_Soccer_Code15": lambda: EversanLegacyProtocol(_Soccer()),
    "EversanV2_Baseball_Code135": lambda: EversanV2Protocol(_Baseball(), 135),
    "EversanV2_Baseball_Code70": lambda: EversanV2Protocol(_Baseball(), 70),
    "EversanV2_Basketball": lambda: EversanV2Protocol(_Basketball555(), 129),
    "EversanV2_Football": lambda: EversanV2Protocol(_Football(), 129),
    "EversanV2_Football_Code111": lambda: EversanV2Protocol(_Football111(), 129),
    "EversanV2_Hockey_Code131": lambda: EversanV2Protocol(_Hockey131(), 131),
    "EversanV2_Lacrosse_Code135": lambda: EversanV2Protocol(_Lacrosse(), 135),
    "EversanV2_Soccer_Code135": lambda: EversanV2Protocol(_Soccer(), 135),
    "EversanModel9364_Football": lambda: Eversan9xxxProtocol(_Football9364(), 129),
    "EversanModel9364_Lacrosse": lambda: Eversan9xxxProtocol(_Lacrosse9364(), 129),
    "EversanModel9694_Hockey": lambda: Eversan9xxxProtocol(_Hockey9694(), 131),
    "EversanModel9775_Hockey": lambda: Eversan9xxxProtocol(_Hockey9775(), 131),
}
