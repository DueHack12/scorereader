"""Daktronics serial protocols other than the All Sport 5000 current loop.

Four families, all registered in ``PROTOCOLS``:

* ``DaktronicsPublic_*``      RTD-style text frames ``SYN … SOH … STX text EOT … ETB`` that patch a persistent
                              1 KB text image; the decoders read fixed columns of that image.
* ``DaktronicsAllSportsCG_*`` character-generator feed: ``SOH … EOT`` frames of fixed-column ASCII.
* ``Daktronics4000_*``        "4000 V2" 18-byte frames ``AA <16 bytes> AB`` with active-low 7-segment bytes.
* ``PIC55AA_Daktronics4000_*`` the same 16 data bytes, delivered through the ScoreLinkII PIC (55 AA / code 0xBD).

See docs/vendors/daktronics_serial.md for the layouts and the quirks reproduced from ScoreConnect III.
"""
from __future__ import annotations

import re

from .base import Decoder, Protocol, find
from .common import ascii_char
from .pic55aa import Pic55AADak4000

__all__ = ["PROTOCOLS"]


def _r(first: int, last: int) -> tuple:
    """Inclusive index range as a tuple (a multi-character field)."""
    return tuple(range(first, last + 1))


def _fill(c: dict, a, spec) -> None:
    """spec: (contract field, index) for one character, or (field, (i, j, …)) for a string."""
    for name, pos in spec:
        c[name] = "".join(a[i] for i in pos) if isinstance(pos, tuple) else a[pos]


# =================================================================================== Daktronics Public (RTD)
_IMAGE_SIZE = 1024
_INT_RE = re.compile(r"[+-]?\d+\Z")


class PublicProtocol(Protocol):
    """``SYN(16) … SOH(1) … STX(2) text EOT(4) … ETB(23)``.

    The three ASCII digits at frame offsets 17-19 give the zero-based position at which the text between
    STX and EOT is written into a persistent 1024-byte image (initially spaces). The decoder sees the whole
    image after every frame. There is no checksum check; the only framing test is SOH at offset 9.
    """

    def __init__(self, decoder: Decoder):
        super().__init__(decoder)
        self.image = bytearray(b" " * _IMAGE_SIZE)

    def extract(self):
        buf = self.buf
        while True:
            etb = find(buf, 23)
            if etb < 0:
                return
            syn = find(buf, 22)
            if 0 <= syn < etb:
                seg = bytes(buf[syn : etb + 1])
                if len(seg) > 9 and seg[9] != 1:  # garbage held an early SYN: retry from the last one
                    alt = buf.rfind(22, 0, etb)
                    if alt > syn:
                        seg = bytes(buf[alt : etb + 1])
                del buf[: etb + 1]
                if self._apply(seg):
                    yield bytes(self.image)
            else:
                del buf[: etb + 1]

    def _apply(self, seg: bytes) -> bool:
        if len(seg) < 20 or seg[9] != 1:
            self.reject()
            return False
        field = seg[17:20].decode("latin-1").strip()
        dest = int(field) if _INT_RE.match(field) else 0  # unparsable offset reads as 0
        stx = seg.find(2)
        if stx < 0:
            return False  # header-only frame, nothing to write
        eot = seg.find(4)
        n = eot - stx - 1
        if eot < 0 or n < 0 or dest < 0 or dest + n > _IMAGE_SIZE:
            self.reject()
            return False
        self.image[dest : dest + n] = seg[stx + 1 : eot]
        return True


_PUB_NAMES = (("HomeTeamName", _r(47, 54)), ("GuestTeamName", _r(67, 74)))


class _PublicDecoder(Decoder):
    spec: tuple = ()
    status = True      # InternalClockStatus from column 28 ("s" = stopped)
    names = True       # team names at 47 and 67

    def decode(self, packet: bytes) -> None:
        a = packet.decode("latin-1").ljust(_IMAGE_SIZE)
        c = self.c
        if self.names:
            _fill(c, a, _PUB_NAMES)
        if self.status:
            c["InternalClockStatus"] = "R" if a[27] == " " else "S"
        self.clock(c, a)
        _fill(c, a, self.spec)
        self.extra(c, a)

    @staticmethod
    def clock(c: dict, a: str) -> None:
        c["ClockMode"] = a[2]
        if a[2] == ".":
            c["ClockMinutesTens"] = "0"
            c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"] = a[0]
            c["ClockSecondOnes"] = a[1]
            c["ClockTenthsSecond"] = a[3]
        else:
            c["ClockMinutesTens"] = a[0]
            c["ClockMinutesOnes"] = a[1]
            c["ClockSecondTens"] = a[3]
            c["ClockSecondOnes"] = a[4]
            c["ClockTenthsSecond"] = "0"

    def extra(self, c: dict, a: str) -> None:
        pass


def _spec_innings(prefix: str, first: int) -> tuple:
    return tuple((f"{prefix}Inning{n + 1}", first + 2 * n) for n in range(10))


class _PubBaseball(_PublicDecoder):
    contract = "BaseballSoftball"
    event = "Baseball"  # ScoreConnect reports Baseball for the softball id too
    spec = (
        ("Balls", 221), ("Strikes", 222), ("Outs", 223), ("InningTens", 141), ("InningOnes", 142),
        ("GuestRunTens", 113), ("GuestRunOnes", 114), ("HomeRunTens", 109), ("HomeRunOnes", 110),
        ("GuestHitsTens", 208), ("GuestHitsOnes", 209), ("HomeHitsTens", 202), ("HomeHitsOnes", 203),
        ("GuestErrors", 211), ("HomeErrors", 205), ("AtBatTens", 214), ("AtBatOnes", 215), ("ErrorFlag", 226),
    ) + _spec_innings("Guest", 282) + _spec_innings("Home", 258)

    def extra(self, c, a):
        top = a[201] == ">"
        c["TopBottomInning"] = "T" if top else "B"
        c["TopOfInning"] = "." if top else " "
        c["BottomOfInning"] = "." if a[200] == "<" else " "


def _bb_players(prefix: str, base: int) -> tuple:
    out = []
    for n in range(5):
        b = base + 7 * n
        out += [(f"{prefix}Player{n + 1}", (b, b + 1)), (f"{prefix}Player{n + 1}FoulNumber", b + 3),
                (f"{prefix}Player{n + 1}Points", (b + 4, b + 5))]
    return tuple(out)


class _PubBasketball(_PublicDecoder):
    contract = "Basketball"
    event = "Basketball"
    spec = (
        ("ShotClockSecondTens", 203), ("ShotClockSecondOnes", 204),
        ("HomeScoreHundreds", 108), ("HomeScoreTens", 109), ("HomeScoreOnes", 110),
        ("GuestScoreHundreds", 112), ("GuestScoreTens", 113), ("GuestScoreOnes", 114),
        ("HomePossession", 209), ("GuestPossession", 215), ("HomeTimeouts", 122), ("GuestTimeouts", 130),
        ("Period", 142), ("HomeBonus", 223), ("GuestBonus", 230),
        ("HomeFoulTens", 235), ("HomeFoulOnes", 236), ("GuestFoulTens", 237), ("GuestFoulOnes", 238),
        ("FoulPlayerTens", 255), ("FoulPlayerOnes", 256), ("FoulPlayerNumberOfFouls", 257), ("Horn", 208),
        ("HomeFullTimeouts", 115), ("HomePartialTimeouts", 117), ("GuestFullTimeouts", 123),
        ("GuestPartialTimeouts", 125),
    ) + _bb_players("Home", 304) + _bb_players("Guest", 475)


class _PubFootball(_PublicDecoder):
    contract = "Football"
    event = "Football"
    # ScoreConnect assigns HomeScoreQuarter1-4 twice (columns 226-233, then 246-253); the later columns win,
    # and the visitor quarter scores are never filled.
    spec = (
        ("PlayClockTens", 203), ("PlayClockOnes", 204),
        ("HomeScoreTens", 109), ("HomeScoreOnes", 110), ("GuestScoreTens", 113), ("GuestScoreOnes", 114),
        ("HomePossession", 209), ("GuestPossession", 214), ("HomeTimeouts", 122), ("GuestTimeouts", 130),
        ("Quarter", 142), ("BallOnTens", 219), ("BallOnOnes", 220), ("Down", 221),
        ("ToGoTens", 224), ("ToGoOnes", 225),
        ("HomeScoreQuarter1", (246, 247)), ("HomeScoreQuarter2", (248, 249)),
        ("HomeScoreQuarter3", (250, 251)), ("HomeScoreQuarter4", (252, 253)),
        ("HomeYardsRushing", _r(266, 269)), ("HomeYardsPassing", _r(270, 273)), ("HomeTotalYards", _r(274, 277)),
        ("VisitorYardsRushing", _r(278, 281)), ("VisitorYardsPassing", _r(282, 285)),
        ("VisitorTotalYards", _r(286, 289)),
        ("HomeTotalFirstDowns", (290, 291)), ("VisitorTotalFirstDowns", (292, 293)), ("Flag", 310),
    )


def _penalties(prefix: str, bases: tuple) -> tuple:
    out = []
    for n, b in enumerate(bases, 1):
        p = f"{prefix}PenaltyPlayer{n}"
        out += [(p + "Tens", b), (p + "Ones", b + 1),
                (p + "ClockMinutesTens", b + 2), (p + "ClockMinutesOnes", b + 3),
                (p + "ClockSecondTens", b + 5), (p + "ClockSecondOnes", b + 6)]
    return tuple(out)


class _PubHockey(_PublicDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    spec = (
        ("ShotClockTens", 203), ("ShotClockOnes", 204),
        ("HomeScoreTens", 109), ("HomeScoreOnes", 110), ("GuestScoreTens", 113), ("GuestScoreOnes", 114),
        ("HomeTimeOut", 131), ("GuestTimeOut", 136),
        ("HomeFullTimeoutsRemaining", 116), ("GuestFullTimeoutsRemaining", 124),
        ("HomePartialTimeoutsRemaining", 118), ("GuestPartialTimeoutsRemaining", 126),
        ("HomeShotOnGoalTens", 422), ("HomeShotOnGoalOnes", 423),
        ("GuestShotOnGoalTens", 468), ("GuestShotOnGoalOnes", 469), ("Period", 142),
    ) + _penalties("Home", (225, 235, 245)) + _penalties("Guest", (285, 295, 305))

    def extra(self, c, a):
        c["HomePlayerPopUp"] = " "
        c["GuestPlayerPopUp"] = " "
        c["Horn"] = "H" if a[28] == "h" else " "


class _PubLacrosse(_PubHockey):
    event = "Lacrosse"


class _PubSoccer(_PublicDecoder):
    contract = "Soccer"
    event = "Soccer"
    status = False  # no clock status for soccer
    # GuestPenalties reads column 336 twice (the second digit is a copy of the first), as ScoreConnect does.
    spec = (
        ("HomeScoreTens", 109), ("HomeScoreOnes", 110), ("GuestScoreTens", 113), ("GuestScoreOnes", 114),
        ("Period", 142), ("HomeTimeouts", 122), ("GuestTimeouts", 130),
        ("HomePossession", 200), ("GuestPossession", 205),
        ("HomeShotTens", 259), ("HomeShotOnes", 260), ("HomeSaves", (270, 271)),
        ("HomeCornerKicks", (281, 282)), ("HomePenalties", (292, 293)),
        ("GuestShotTens", 303), ("GuestShotOnes", 304), ("GuestSaves", (314, 315)),
        ("GuestCornerKicks", (325, 326)), ("GuestPenalties", (336, 336)),
    )


def _vb_players(prefix: str, base: int) -> tuple:
    out = []
    for n in range(6):
        b = base + 7 * n
        out += [(f"{prefix}Player{n + 1}", (b, b + 1)), (f"{prefix}Player{n + 1}Kills", b + 3),
                (f"{prefix}Player{n + 1}Digs", (b + 4, b + 5))]
    return tuple(out)


class _PubVolleyball(_PublicDecoder):
    contract = "Volleyball"
    event = "Volleyball"
    # Only GuestScoreSet1 is filled (ScoreConnect overwrites it with columns 241, 243, 245 and finally 247-248).
    spec = (
        ("HomeGamesWon", 215), ("HomeScoreTens", 109), ("HomeScoreOnes", 110),
        ("GuestGamesWon", 217), ("GuestScoreTens", 113), ("GuestScoreOnes", 114),
        ("HomeServe", 200), ("GuestServe", 207), ("HomeTimeout", 122), ("GuestTimeout", 130),
        ("HomeScoreSet1", (221, 222)), ("HomeScoreSet2", (223, 224)),
        ("HomeScoreSet3", (225, 226)), ("HomeScoreSet4", (227, 228)),
        ("GuestScoreSet1", (247, 248)), ("Set", 220), ("Game", 142),
    ) + _vb_players("Home", 262) + _vb_players("Guest", 429)


class _PubSwimming(_PublicDecoder):
    contract = "SwimmingDetail"
    event = "Swimming"
    status = False
    names = False

    def clock(self, c, a):  # type: ignore[override]
        c["ClockMinutesTens"] = a[0]
        c["ClockMinutesOnes"] = a[1]
        c["ClockSecondTens"] = a[3]
        c["ClockSecondOnes"] = a[4]
        c["ClockTenthsSecond"] = a[6]


class _PubRodeo(_PublicDecoder):
    contract = "Rodeo"
    event = "Rodeo"
    names = False

    def clock(self, c, a):  # type: ignore[override]
        c["ClockMode"] = " "
        c["ClockMinutesTens"] = a[0]
        c["ClockMinutesOnes"] = a[1]
        c["ClockSecondTens"] = a[3]
        c["ClockSecondOnes"] = a[4]
        c["ClockTenthsSecond"] = a[6]
        c["ClockHundreths"] = a[7]
        c["ClockMilliSeconds"] = a[8]

    def extra(self, c, a):
        c["RiderNumber"] = a[30:34].strip()
        c["RiderScore"] = (a[17:19] + a[20:22] + a[23:26]).strip()
        # ScoreConnect only ever sets Penalty to "P"; it is never cleared again.
        if a[205] == "P":
            c["Penalty"] = "P"
        c["ReRide"] = "R" if a[204] == "F" else " "
        c["LeaderNumber"] = a[61:65].strip()
        c["LeaderScore"] = (a[52:54] + a[55:57] + a[58:61]).strip()
        c["PrevRiderNumber"] = a[84:88].strip()
        c["PrevRiderScore"] = (a[75:77] + a[78:80] + a[81:84]).strip()


# =================================================================================== AllSport CG (SOH … EOT)
class AllSportCGProtocol(Protocol):
    """``SOH(1) … EOT(4)``: everything up to the first EOT is one packet, including both control bytes.

    ScoreConnect drops a packet that does not start with SOH. Here, leading junk before an SOH is discarded
    (counted as one reject) and the frame itself is still decoded.
    """

    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, 4)
            if end < 0:
                return
            seg = bytes(buf[: end + 1])
            del buf[: end + 1]
            if seg[0] != 1:
                self.reject()
                i = seg.find(1)
                if i <= 0:
                    continue
                seg = seg[i:]
            if len(seg) < getattr(self.decoder, "min_len", 0):
                self.reject()
                continue
            yield seg


class _CGDecoder(Decoder):
    min_len = 1  # smallest packet ScoreConnect decodes without an index error

    def decode(self, packet: bytes) -> None:
        if len(packet) < self.min_len:
            return
        self.apply(self.c, [ascii_char(b) for b in packet])

    def apply(self, c: dict, a: list) -> None:
        raise NotImplementedError

    @staticmethod
    def clock(c: dict, a: list) -> None:
        if a[6] == ".":
            c["ClockMode"] = "."
            c["ClockMinutesTens"] = "0"
            c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"] = a[4]
            c["ClockSecondOnes"] = a[5]
            c["ClockTenthsSecond"] = a[7]
        else:
            c["ClockMode"] = ":"
            c["ClockMinutesTens"] = a[1]
            c["ClockMinutesOnes"] = a[2]
            c["ClockSecondTens"] = a[4]
            c["ClockSecondOnes"] = a[5]
            c["ClockTenthsSecond"] = "0"


def _text(a, first: int, n: int) -> str:
    return "".join(a[i] if i < len(a) else " " for i in range(first, first + n))


class _CGFootball(_CGDecoder):
    contract = "Football"
    event = "Football"
    min_len = 42

    def apply(self, c, a):
        c["HomeTeamName"] = _text(a, 6, 8)
        c["GuestTeamName"] = _text(a, 16, 8)
        c["ClockMode"] = ":"
        c["ClockMinutesTens"], c["ClockMinutesOnes"] = a[1], a[2]
        c["ClockSecondTens"], c["ClockSecondOnes"] = a[4], a[5]
        c["ClockTenthsSecond"] = "0"
        _fill(c, a, (
            ("PlayClockTens", 38), ("PlayClockOnes", 39),
            ("HomeScoreTens", 26), ("HomeScoreOnes", 27), ("GuestScoreTens", 28), ("GuestScoreOnes", 29),
            # ScoreConnect reads timeouts from 40/41 and then overwrites them with 25/28 (the latter is the
            # guest score tens digit). The final values are kept.
            ("HomeTimeouts", 25), ("GuestTimeouts", 28),
            ("Quarter", 30), ("BallOnTens", 31), ("BallOnOnes", 32), ("Down", 33),
            ("ToGoTens", 34), ("ToGoOnes", 35)))
        c["HomePossession"] = " " if a[36] == " " else "<"
        c["GuestPossession"] = " " if a[37] == " " else ">"


class _CGBasketball(_CGDecoder):
    contract = "Basketball"
    event = "Basketball"
    min_len = 30
    spec = (
        ("ShotClockSecondTens", 9), ("ShotClockSecondOnes", 10),
        ("HomeScoreHundreds", 13), ("HomeScoreTens", 14), ("HomeScoreOnes", 15),
        ("GuestScoreHundreds", 16), ("GuestScoreTens", 17), ("GuestScoreOnes", 18),
        ("HomeFoulTens", 19), ("HomeFoulOnes", 20), ("GuestFoulTens", 21), ("GuestFoulOnes", 22),
        ("HomeFullTimeouts", 23), ("HomePartialTimeouts", 24), ("HomeTimeouts", 25),
        ("GuestFullTimeouts", 26), ("GuestPartialTimeouts", 27), ("GuestTimeouts", 28), ("Period", 29),
    )

    def apply(self, c, a):
        self.clock(c, a)
        c["InternalClockStatus"] = a[8]
        _fill(c, a, self.spec)


class _CGBasketballUNCG(_CGBasketball):
    min_len = 28
    spec = (
        ("ShotClockSecondTens", 9), ("ShotClockSecondOnes", 10),
        ("HomeScoreHundreds", 11), ("HomeScoreTens", 12), ("HomeScoreOnes", 13),
        ("GuestScoreHundreds", 14), ("GuestScoreTens", 15), ("GuestScoreOnes", 16),
        ("HomeFoulTens", 17), ("HomeFoulOnes", 18), ("GuestFoulTens", 19), ("GuestFoulOnes", 20),
        ("HomeFullTimeouts", 21), ("HomePartialTimeouts", 22), ("GuestFullTimeouts", 23),
        ("GuestPartialTimeouts", 24), ("HomeTimeouts", 25), ("GuestTimeouts", 26), ("Period", 27),
    )


class _CGHockey(_CGDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    min_len = 49
    # HomeShotOnGoalTens is read from 15 and then overwritten from 17; GuestShotOnGoalOnes is never set.
    spec = (
        ("HomeScoreTens", 9), ("HomeScoreOnes", 10), ("GuestScoreTens", 11), ("GuestScoreOnes", 12),
        ("HomeTimeOut", 13), ("GuestTimeOut", 14), ("Period", 19),
        ("HomeShotOnGoalOnes", 16), ("HomeShotOnGoalTens", 17), ("GuestShotOnGoalTens", 18),
    ) + _penalties("Home", (21, 28)) + _penalties("Guest", (35, 42))

    def apply(self, c, a):
        self.clock(c, a)
        _fill(c, a, self.spec)


class _CGVolleyball(_CGDecoder):
    contract = "Volleyball"
    event = "Volleyball"
    min_len = 36
    spec = (
        ("HomeGamesWon", 17), ("HomeScoreTens", 9), ("HomeScoreOnes", 10),
        ("GuestGamesWon", 18), ("GuestScoreTens", 11), ("GuestScoreOnes", 12),
        ("HomeTimeout", 13), ("GuestTimeout", 14), ("Set", 20), ("Game", 19),
        ("HomeServe", 15), ("GuestServe", 16),
        ("HomeScoreSet1", (20, 21)), ("HomeScoreSet2", (22, 23)), ("HomeScoreSet3", (24, 25)),
        ("HomeScoreSet4", (26, 27)), ("GuestScoreSet1", (28, 29)), ("GuestScoreSet2", (30, 31)),
        ("GuestScoreSet3", (32, 33)), ("GuestScoreSet4", (34, 35)),
    )

    def apply(self, c, a):
        self.clock(c, a)
        c["InternalClockStatus"] = "S" if a[8] == "s" else "R"
        _fill(c, a, self.spec)


class _CGBaseball(_CGDecoder):
    contract = "BaseballSoftball"
    event = "Baseball"
    min_len = 160
    spec = (
        ("GuestRunTens", 7), ("GuestRunOnes", 8), ("HomeRunTens", 3), ("HomeRunOnes", 4),
        ("AtBatTens", 41), ("AtBatOnes", 42), ("InningTens", 9), ("InningOnes", 10),
        ("HomeHitsTens", 28), ("HomeHitsOnes", 29), ("HomeErrors", 31),
        ("GuestHitsTens", 34), ("GuestHitsOnes", 35), ("GuestErrors", 37),
        ("Balls", 48), ("Strikes", 49), ("Outs", 50),
    ) + tuple((f"HomeInning{n + 1}", 85 + 2 * n) for n in range(10)) \
        + tuple((f"GuestInning{n + 1}", 109 + 2 * n) for n in range(10))

    def decode(self, packet: bytes) -> None:
        # ScoreConnect returns the previous values for packets of 159 bytes or fewer
        if len(packet) <= 159:
            return
        super().decode(packet)

    def apply(self, c, a):
        _fill(c, a, self.spec)
        c["ErrorFlag"] = "E" if a[52] != " " else ("H" if a[51] != " " else " ")
        # "Top" test: with n = the inning number, half[n-1] is filled and half[n] is blank, where half lists
        # the line score as G1, H1, G2, H2, … (so it only really lines up for the first innings).
        half = []
        for n in range(1, 11):
            half += [c[f"GuestInning{n}"], c[f"HomeInning{n}"]]
        inning = (c["InningTens"] + c["InningOnes"]).strip()
        top = False
        if inning.isdigit() and 1 <= int(inning) < len(half):
            n = int(inning)
            top = half[n - 1] != " " and half[n] == " "
        c["TopBottomInning"] = "T" if top else "B"
        if len(a) >= 165:
            end = 165 if top else 148
            if end < len(a):
                c["PitchCount"] = a[end - 2] + a[end - 1] + a[end]


# =================================================================================== Daktronics 4000 (V2 and PIC)
class Dak4000V2Protocol(Protocol):
    """``AA <16 data bytes> AB`` (18 bytes, no checksum). Data bytes are active-low 7-segment patterns.

    ScoreConnect takes the first AB, then the first AA before it, and accepts the frame only if they are 18
    bytes apart. Here the AA is the byte 17 positions before the AB, so junk containing an AA ahead of the
    frame no longer costs a frame.
    """

    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, 0xAB)
            if end < 0:
                return
            start = end - 17
            if start >= 0 and buf[start] == 0xAA:
                frame = bytes(buf[start + 1 : end])
                del buf[: end + 1]
                yield frame
                continue
            if 0 <= find(buf, 0xAA) < end:
                self.reject()  # a header was seen but the frame is not 18 bytes long
            del buf[: end + 1]


_DIGIT_4000 = {64: "0", 121: "1", 36: "2", 48: "3", 25: "4", 18: "5", 2: "6", 120: "7", 0: "8", 24: "9", 255: " "}


def _d(b: int) -> str:
    """Daktronics 4000 digit: active-low 7-segment byte (a..g = bits 0..6), 0xFF blank, anything else blank."""
    return _DIGIT_4000.get(b, " ")


class _Dak4000Decoder(Decoder):
    spec: tuple = ()
    size = 16

    def decode(self, packet: bytes) -> None:
        if len(packet) < self.size:
            return
        p = packet
        c = self.c
        s = _d(p[3])
        if s == " ":  # no tens-of-seconds position: the clock is in SS.t
            c["ClockMode"] = "."
            c["ClockMinutesTens"] = "0"
            c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"] = _d(p[0]), _d(p[1]), _d(p[2])
        else:
            c["ClockMode"] = ":"
            c["ClockMinutesTens"], c["ClockMinutesOnes"] = _d(p[0]), _d(p[1])
            c["ClockSecondTens"], c["ClockSecondOnes"] = _d(p[2]), s
            c["ClockTenthsSecond"] = "0"
        for name, i in self.spec:
            c[name] = _d(p[i])
        self.extra(c, p)

    def extra(self, c: dict, p: bytes) -> None:
        pass


class _D4Football(_Dak4000Decoder):
    contract = "Football"
    event = "Football"
    spec = (("HomeScoreTens", 4), ("HomeScoreOnes", 5), ("GuestScoreTens", 6), ("GuestScoreOnes", 7),
            ("Down", 9), ("ToGoTens", 10), ("ToGoOnes", 11), ("BallOnTens", 12), ("BallOnOnes", 13),
            ("Quarter", 14))


class _D4FootballCode27(_Dak4000Decoder):
    contract = "Football"
    event = "Football"
    spec = (("HomeScoreTens", 6), ("HomeScoreOnes", 7), ("GuestScoreTens", 8), ("GuestScoreOnes", 9),
            ("Quarter", 10), ("HomeTimeouts", 13), ("GuestTimeouts", 14))

    def extra(self, c, p):
        c["HomePossession"] = "<" if p[12] == 248 else " "
        c["GuestPossession"] = ">" if p[12] == 199 else " "


class _D4Basketball(_Dak4000Decoder):
    contract = "Basketball"
    event = "Basketball"
    spec = (("HomeScoreTens", 4), ("HomeScoreOnes", 5), ("GuestScoreTens", 6), ("GuestScoreOnes", 7),
            ("HomeFoulOnes", 10), ("GuestFoulOnes", 11), ("FoulPlayerTens", 12), ("FoulPlayerOnes", 13),
            ("FoulPlayerNumberOfFouls", 14), ("Period", 15))

    def extra(self, c, p):
        # Bit clear = lamp on. Byte 9 carries the "1" hundreds / tens lamps, byte 8 possession and bonus.
        c["ShotClockSecondTens"] = c["ShotClockSecondOnes"] = " "
        c["HomeScoreHundreds"] = "1" if p[9] & 0x03 == 0 else " "
        c["GuestScoreHundreds"] = "1" if p[9] & 0x0C == 0 else " "
        c["HomeFoulTens"] = "1" if p[9] & 0x30 == 0 else " "
        c["GuestFoulTens"] = "1" if p[9] & 0xC0 == 0 else " "
        c["HomePossession"] = "<" if p[8] & 0x04 == 0 else " "
        c["GuestPossession"] = ">" if p[8] & 0x08 == 0 else " "
        c["HomeBonus"] = "B" if p[8] & 0x10 == 0 else " "
        c["GuestBonus"] = "B" if p[8] & 0x20 == 0 else " "
        for k in ("HomeFullTimeouts", "HomePartialTimeouts", "GuestFullTimeouts", "GuestPartialTimeouts",
                  "HomeTimeouts", "GuestTimeouts"):
            c[k] = " "


class _D4Hockey(_Dak4000Decoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    spec = (("HomeScoreTens", 4), ("HomeScoreOnes", 5), ("GuestScoreTens", 6), ("GuestScoreOnes", 7),
            ("HomeShotOnGoalTens", 10), ("HomeShotOnGoalOnes", 11),
            ("GuestShotOnGoalTens", 12), ("GuestShotOnGoalOnes", 13), ("Period", 15))


class _D4Baseball(_Dak4000Decoder):
    contract = "BaseballSoftball"
    event = "Baseball"
    spec = (("AtBatTens", 0), ("AtBatOnes", 1), ("Balls", 2), ("Strikes", 3), ("Outs", 4), ("ErrorFlag", 5),
            ("GuestRunTens", 6), ("GuestRunOnes", 7), ("GuestHitsTens", 8), ("GuestHitsOnes", 9),
            ("GuestErrors", 10), ("HomeRunTens", 11), ("HomeRunOnes", 12), ("HomeHitsTens", 13),
            ("HomeHitsOnes", 14), ("HomeErrors", 15))

    def decode(self, packet: bytes) -> None:
        if len(packet) < self.size:
            return
        # No clock on the baseball layout: only the lamps and counters.
        for name, i in self.spec:
            self.c[name] = _d(packet[i])


class _D4Volleyball(_Dak4000Decoder):
    contract = "Volleyball"
    event = "Volleyball"
    spec = (("HomeScoreTens", 4), ("HomeScoreOnes", 5), ("GuestScoreTens", 6), ("GuestScoreOnes", 7),
            ("HomeGamesWon", 10), ("GuestGamesWon", 11), ("Game", 14))

    def extra(self, c, p):
        c["HomeServe"] = "*" if p[9] & 2 else " "
        c["GuestServe"] = "*" if p[9] & 1 else " "


class _D4Soccer(_Dak4000Decoder):
    contract = "Soccer"
    event = "Soccer"
    spec = (("HomeScoreTens", 4), ("HomeScoreOnes", 5), ("GuestScoreTens", 6))
    # ScoreConnect blanks GuestScoreOnes here (almost certainly meant GuestShotOnes). Set to False to keep
    # the guest score's ones digit.
    blank_guest_score_ones = True

    def extra(self, c, p):
        c["GuestScoreOnes"] = " " if self.blank_guest_score_ones else _d(p[7])
        c["Period"] = {252: "1", 231: "2"}.get(p[8], " ")
        c["HomeShotTens"] = c["HomeShotOnes"] = c["GuestShotTens"] = " "
        c["HomeSaves"] = c["GuestSaves"] = ""
        c["HomeTimeouts"] = c["GuestTimeouts"] = " "
        c["HomeCornerKicks"] = " " + _d(p[11])
        c["GuestCornerKicks"] = " " + _d(p[13])


# =================================================================================== registrations
def _pub(decoder_cls):
    return lambda: PublicProtocol(decoder_cls())


def _cg(decoder_cls):
    return lambda: AllSportCGProtocol(decoder_cls())


def _v2(decoder_cls):
    return lambda: Dak4000V2Protocol(decoder_cls())


def _pic(decoder_cls):
    return lambda: Pic55AADak4000(decoder_cls())


PROTOCOLS = {
    "DaktronicsPublic_Baseball": _pub(_PubBaseball),
    "DaktronicsPublic_Softball": _pub(_PubBaseball),
    "DaktronicsPublic_Football": _pub(_PubFootball),
    "DaktronicsPublic_Basketball": _pub(_PubBasketball),
    "DaktronicsPublic_Hockey": _pub(_PubHockey),
    "DaktronicsPublic_Lacrosse": _pub(_PubLacrosse),
    "DaktronicsPublic_Volleyball": _pub(_PubVolleyball),
    "DaktronicsPublic_Soccer": _pub(_PubSoccer),
    "DaktronicsPublic_Swimming": _pub(_PubSwimming),
    "DaktronicsPublic_Rodeo": _pub(_PubRodeo),
    "DaktronicsAllSportsCG_Football": _cg(_CGFootball),
    "DaktronicsAllSportsCG_Basketball": _cg(_CGBasketball),
    "DaktronicsAllSportsCG_Hockey": _cg(_CGHockey),
    "DaktronicsAllSportsCG_Volleyball": _cg(_CGVolleyball),
    "DaktronicsAllSportsCG_BasketballUNCG": _cg(_CGBasketballUNCG),
    "DaktronicsAllSportsCG_Baseball": _cg(_CGBaseball),
    "Daktronics4000_Football": _v2(_D4Football),
    "Daktronics4000_Football_Code27": _v2(_D4FootballCode27),
    "Daktronics4000_Hockey": _v2(_D4Hockey),
    "Daktronics4000_BaseballSoftball": _v2(_D4Baseball),
    "Daktronics4000_Volleyball": _v2(_D4Volleyball),
    "Daktronics4000_Soccer": _v2(_D4Soccer),
    "Daktronics4000_Basketball_Code3": _v2(_D4Basketball),
    "Daktronics4000_Basketball_Code4": _v2(_D4Basketball),
    "PIC55AA_Daktronics4000_Hockey": _pic(_D4Hockey),
    "PIC55AA_Daktronics4000_BaseballSoftball": _pic(_D4Baseball),
    "PIC55AA_Daktronics4000_Football": _pic(_D4Football),
    "PIC55AA_Daktronics4000_Basketball": _pic(_D4Basketball),
    "PIC55AA_Daktronics4000_Volleyball": _pic(_D4Volleyball),
    "PIC55AA_Daktronics4000_Soccer": _pic(_D4Soccer),
    "PIC55AA_Daktronics4000_Football_Code27": _pic(_D4FootballCode27),
}
