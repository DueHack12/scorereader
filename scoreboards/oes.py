"""OES scoreboards (wired RS-232/RS-422/RS-485 and XBee wireless).

Wire format (all OES sports): ``STX(02) 't'|'s' <data…> <checksum> CR(0D)``.
The checksum byte is ``sum(bytes from STX up to, not including, the checksum) & 0x7F``, plus 0x20 when the
result is below 0x20 (so it is always printable and never collides with STX/CR). Data bytes are 7-bit ASCII;
bit 7 carries flags on some fields (clock-stopped, hundreds digit, possession, ...).

Decoders are table driven: a step is ``(contract_field, spec)`` where ``spec`` is an int (one ASCII byte), a
tuple of ints (several bytes joined into a string) or a str (constant), or a callable ``f(packet, contract)``.
A packet shorter than a decoder expects updates the fields it can reach and then stops (never raises), which
matches how ScoreConnect leaves the remaining fields untouched.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char

STX = 0x02
CR = 0x0D


# --------------------------------------------------------------------------- framing
def oes_checksum(body) -> int:
    """Checksum byte for ``body`` (STX .. last data byte)."""
    chk = sum(body) & 0x7F
    return chk + 32 if chk < 32 else chk


def make_packet(body: bytes) -> bytes:
    """Wrap ``body`` (which must start with STX) with checksum and CR."""
    return bytes(body) + bytes([oes_checksum(body), CR])


class OesProtocol(Protocol):
    """STX ... checksum CR framing shared by every OES sport.

    ScoreConnect takes the first CR, then the first STX in the buffer; if the STX precedes the CR the span
    is a candidate packet, otherwise the bytes up to and including the CR are discarded. Everything through
    the CR is consumed either way, so a bad packet never blocks the stream. There is no length field.
    """

    def extract(self):
        buf = self.buf
        while True:
            cr = find(buf, CR)
            if cr < 0:
                return
            stx = find(buf, STX)
            if 0 <= stx < cr:
                pkt = bytes(buf[stx : cr + 1])
                del buf[: cr + 1]
                if pkt[-2] == oes_checksum(pkt[:-2]):
                    yield pkt
                else:
                    self.reject()
            else:
                del buf[: cr + 1]


# --------------------------------------------------------------------------- character helpers
def oes_ascii(b: int) -> str:
    """Low 7 bits as a printable character; ':' (the clock colon) and non-printables read as blank."""
    ch = ascii_char(b & 0x7F)
    return " " if ch == ":" else ch


def _chars(p: bytes, *idx: int) -> str:
    return "".join(oes_ascii(p[i]) for i in idx)


def _timeouts(b: int) -> str:
    """Partial timeouts: bits 2-3 -> '0'..'3'."""
    return str((b & 0x0C) >> 2)


def _set_clock(p: bytes, c: dict) -> None:
    """Game clock. A blank byte 5 means the clock is under a minute: SS.t at bytes 2-4; else MM:SS at 2-5."""
    if oes_ascii(p[5]) == " ":
        c["ClockMinutesTens"] = "0"
        c["ClockMinutesOnes"] = "0"
        c["ClockSecondTens"] = oes_ascii(p[2])
        c["ClockSecondOnes"] = oes_ascii(p[3])
        c["ClockTenthsSecond"] = oes_ascii(p[4])
        c["ClockMode"] = "."
    else:
        c["ClockMinutesTens"] = oes_ascii(p[2])
        c["ClockMinutesOnes"] = oes_ascii(p[3])
        c["ClockSecondTens"] = oes_ascii(p[4])
        c["ClockSecondOnes"] = oes_ascii(p[5])
        c["ClockTenthsSecond"] = "0"
        c["ClockMode"] = ":"


class _TableDecoder(Decoder):
    """Runs ``steps`` over a packet. ``kind`` (a byte) is the required value of byte 1, if any."""

    kind: int | None = None
    steps: list = []

    def decode(self, p: bytes) -> None:
        if self.kind is not None and (len(p) < 2 or p[1] != self.kind):
            return
        c = self.c
        try:
            for step in self.steps:
                if callable(step):
                    step(p, c)
                    continue
                field, spec = step
                if isinstance(spec, int):
                    c[field] = oes_ascii(p[spec])
                elif isinstance(spec, tuple):
                    c[field] = _chars(p, *spec)
                else:
                    c[field] = spec
        except IndexError:
            pass  # short packet: keep what was decoded so far


def _score(home: tuple, guest: tuple) -> list:
    return [("HomeScoreTens", home[0]), ("HomeScoreOnes", home[1]),
            ("GuestScoreTens", guest[0]), ("GuestScoreOnes", guest[1])]


# --------------------------------------------------------------------------- baseball
def _innings(home: list, guest: list) -> list:
    return ([(f"GuestInning{n}", i) for n, i in enumerate(guest, 1)]
            + [(f"HomeInning{n}", i) for n, i in enumerate(home, 1)])


def _top_bottom(c: dict, top: bool | None) -> None:
    if top is None:
        c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = " ", " ", " "
    elif top:
        c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "T", ".", " "
    else:
        c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"] = "B", " ", "."


def _inning_from_linescore(c: dict) -> tuple:
    """Current inning and half derived from the line score, as ScoreConnect does.

    Scan from the 10th inning down: the first inning where the guests have a mark decides. Both teams
    marked -> the next inning's top (inning + 1, 'T'); guests only -> that inning's bottom ('B'). With
    nothing marked the result is inning 01, 'T'.
    """
    num = 10
    half = "T"
    for n in range(10, 0, -1):
        g = c.get(f"GuestInning{n}", " ")
        h = c.get(f"HomeInning{n}", " ")
        if g != " " and h != " ":
            half = "T"
            num += 1
            break
        if g != " ":
            half = "B"
            break
        if num > 1:
            num -= 1
    s = f"{num:02d}"
    return s[0], s[1], half


def _flag_by_ascii(idx: int, table: dict):
    """ErrorFlag from the ASCII digit at ``idx`` (unlisted values leave the previous flag in place)."""
    def step(p, c):
        v = table.get(oes_ascii(p[idx]))
        if v is not None:
            c["ErrorFlag"] = v
    return step


def _flag_by_raw(idx: int, table: dict):
    """ErrorFlag from the raw byte at ``idx`` (unlisted values leave the previous flag in place)."""
    def step(p, c):
        v = table.get(p[idx])
        if v is not None:
            c["ErrorFlag"] = v
    return step


class _Baseball(_TableDecoder):
    contract = "BaseballSoftball"
    event = "Baseball"
    kind = 116

    def decode(self, p: bytes) -> None:
        self.c["ClockMode"] = ":"
        super().decode(p)


class BaseballStandard(_Baseball):
    steps = [
        ("Balls", 25), ("Strikes", 26), ("Outs", 27),
        # raw (unmasked) byte: 'G' -> E, 'I' -> H, ':' -> blank
        _flag_by_raw(28, {71: "E", 73: "H", 58: " "}),
        ("GuestRunTens", 30), ("GuestRunOnes", 31), ("GuestHitsTens", 32), ("GuestHitsOnes", 33),
        ("GuestErrors", 34),
        ("HomeRunTens", 35), ("HomeRunOnes", 36), ("HomeHitsTens", 37), ("HomeHitsOnes", 38),
        ("HomeErrors", 39),
        *_innings(list(range(50, 60)), list(range(40, 50))),
        lambda p, c: _top_bottom(c, {"1": True, "2": False}.get(oes_ascii(p[2]))),
        ("AtBatTens", 5), ("AtBatOnes", 6), ("InningTens", 3), ("InningOnes", 4),
        lambda p, c: c.__setitem__("PitchSpeed", _chars(p, 22, 23, 24)),
        lambda p, c: c.__setitem__("PitchCount", " " + _chars(p, 12, 13)),
    ]


class BaseballCode50(_Baseball):
    steps = [
        ("Balls", 4), ("Strikes", 17), ("Outs", 18),
        ("GuestRunTens", 35), ("GuestRunOnes", 36), ("GuestHitsTens", 39), ("GuestHitsOnes", 40),
        ("GuestErrors", 42),
        ("HomeRunTens", 33), ("HomeRunOnes", 34), ("HomeHitsTens", 37), ("HomeHitsOnes", 38),
        ("HomeErrors", 41),
        *_innings([6, 7, 8, 9, 10, 21, 22, 23, 24, 25], [11, 12, 13, 14, 15, 26, 27, 28, 29, 30]),
        lambda p, c: _top_bottom(c, oes_ascii(p[49]) == "1"),
        ("AtBatTens", 2), ("AtBatOnes", 3),
        lambda p, c: c.update(zip(("InningTens", "InningOnes"), _inning_from_linescore(c))),
    ]


class BaseballCode53(_Baseball):
    steps = [
        ("Balls", 10), ("Strikes", 11), ("Outs", 12),
        _flag_by_ascii(13, {"9": "E", "6": "H", "0": " "}),
        ("GuestRunTens", 17), ("GuestRunOnes", 18), ("GuestHitsTens", 19), ("GuestHitsOnes", 20),
        ("GuestErrors", 21),
        ("HomeRunTens", 22), ("HomeRunOnes", 23), ("HomeHitsTens", 24), ("HomeHitsOnes", 25),
        ("HomeErrors", 26),
        *_innings(list(range(37, 47)), list(range(27, 37))),
        lambda p, c: _top_bottom(c, oes_ascii(p[2]) == "1"),
        ("AtBatTens", 5), ("AtBatOnes", 6), ("InningTens", 3), ("InningOnes", 4),
        ("PitchSpeed", (47, 48, 49)), ("PitchCount", (50, 51, 52)),
    ]


class BaseballCode85(_Baseball):
    steps = [
        ("Balls", 12), ("Strikes", 29), ("Outs", 30),
        _flag_by_ascii(13, {"9": "E", "6": "H", "0": " "}),
        ("GuestRunTens", 33), ("GuestRunOnes", 34), ("GuestHitsTens", 35), ("GuestHitsOnes", 36),
        ("GuestErrors", 37),
        ("HomeRunTens", 38), ("HomeRunOnes", 39), ("HomeHitsTens", 40), ("HomeHitsOnes", 41),
        ("HomeErrors", 42),
        *_innings([6, 7, 8, 9, 23, 24, 25, 26, 27, 28], [2, 3, 4, 5, 17, 18, 19, 20, 21, 22]),
        ("AtBatTens", 10), ("AtBatOnes", 11),
    ]

    def decode(self, p: bytes) -> None:
        super().decode(p)
        # Unlike the other baseball layouts the inning and half are always derived, even when the packet
        # was not a 't' packet.
        i1, i2, half = _inning_from_linescore(self.c)
        self.c["InningTens"], self.c["InningOnes"], self.c["TopBottomInning"] = i1, i2, half


class BaseballISC85X(_Baseball):
    kind = None
    steps = [
        ("Balls", 4), ("Strikes", 5), ("Outs", 6),
        ("GuestRunTens", 44), ("GuestRunOnes", 45), ("GuestHitsOnes", 47), ("GuestErrors", 48),
        ("HomeRunTens", 36), ("HomeRunOnes", 37), ("HomeHitsOnes", 39), ("HomeErrors", 40),
        *_innings([17, 18, 19, 20, 21, 22, 23, 33, 34, 35], [25, 26, 27, 28, 29, 30, 31, 41, 42, 43]),
        ("AtBatTens", 2), ("AtBatOnes", 3),
    ]


class BaseballPro(_Baseball):
    """Two layouts selected by packet length: 72 (short, scores only) and 117 (long, with line score)."""

    kind = None
    short_steps = [
        ("Balls", 25), ("Strikes", 26), ("Outs", 27), ("ErrorFlag", 6),
        ("GuestRunTens", 30), ("GuestRunOnes", 31), ("HomeRunTens", 35), ("HomeRunOnes", 36),
        lambda p, c: _top_bottom(c, oes_ascii(p[2]) == "G"),
        ("InningTens", 3), ("InningOnes", 4),
    ]
    long_steps = [
        ("Balls", 30), ("Strikes", 31), ("Outs", 32), ("ErrorFlag", 33),
        ("GuestRunTens", 35), ("GuestRunOnes", 36), ("GuestHitsTens", 37), ("GuestHitsOnes", 38),
        ("GuestErrors", 39),
        ("HomeRunTens", 40), ("HomeRunOnes", 41), ("HomeHitsTens", 42), ("HomeHitsOnes", 43),
        ("HomeErrors", 44),
        *_innings(list(range(86, 106, 2)), list(range(66, 86, 2))),
        lambda p, c: _top_bottom(c, oes_ascii(p[2]) == "G"),
        ("AtBatTens", 7), ("AtBatOnes", 8), ("InningTens", 3), ("InningOnes", 4),
        ("PitchSpeed", (27, 28, 29)), ("PitchCount", (14, 15, 16)),
    ]

    def decode(self, p: bytes) -> None:
        self.c["ClockMode"] = ":"
        if len(p) < 2 or p[1] != 116:
            return
        if len(p) == 72:
            self.steps = self.short_steps
        elif len(p) == 117:
            self.steps = self.long_steps
        else:
            return
        _TableDecoder.decode(self, p)


# --------------------------------------------------------------------------- football
class Football(_TableDecoder):
    contract = "Football"
    event = "Football"
    steps = [
        _set_clock,
        ("PlayClockTens", 20), ("PlayClockOnes", 21),
        *_score((7, 8), (9, 10)),
        lambda p, c: c.__setitem__("HomePossession", "<" if p[13] == 184 else " "),
        lambda p, c: c.__setitem__("GuestPossession", ">" if p[14] == 184 else " "),
        ("HomeTimeouts", 11), ("GuestTimeouts", 12),
        ("Quarter", 6), ("BallOnTens", 18), ("BallOnOnes", 19),
        ("Down", 15), ("ToGoTens", 16), ("ToGoOnes", 17),
    ]


class FootballWireless(_TableDecoder):
    contract = "Football"
    event = "Football"
    steps = [
        _set_clock,
        *_score((7, 8), (11, 12)),
        ("ToGoTens", 17), ("ToGoOnes", 18), ("Quarter", 15),
    ]


# --------------------------------------------------------------------------- basketball
def _basketball_clock_status(p, c):
    c["InternalClockStatus"] = "R" if (p[2] & 0x80) == 0 else "S"


def _basketball_game(p: bytes, c: dict, clock_status: bool) -> None:
    _set_clock(p, c)
    if clock_status:
        _basketball_clock_status(p, c)
    c["Period"] = oes_ascii(p[6])
    c["HomeScoreHundreds"] = "1" if p[7] & 0x80 else " "
    c["HomeScoreTens"] = oes_ascii(p[7])
    c["HomeScoreOnes"] = oes_ascii(p[8])
    c["GuestScoreHundreds"] = "1" if p[9] & 0x80 else " "
    c["GuestScoreTens"] = oes_ascii(p[9])
    c["GuestScoreOnes"] = oes_ascii(p[10])
    c["HomePossession"] = "<" if p[16] & 1 else " "
    c["GuestPossession"] = ">" if p[17] & 1 else " "
    c["HomeBonus"] = "B" if p[16] & 2 else " "
    c["HomeDoubleBonus"] = "B" if p[16] & 4 else " "
    c["GuestBonus"] = "B" if p[17] & 2 else " "
    c["GuestDoubleBonus"] = "B" if p[17] & 4 else " "
    c["HomePartialTimeouts"] = _timeouts(p[16])
    c["GuestPartialTimeouts"] = _timeouts(p[17])
    c["HomeTimeouts"] = c["HomeFullTimeouts"] = oes_ascii(p[11])
    c["GuestTimeouts"] = c["GuestFullTimeouts"] = oes_ascii(p[12])
    c["HomeFoulTens"] = "1" if p[13] & 0x80 else " "
    c["HomeFoulOnes"] = oes_ascii(p[13])
    c["GuestFoulTens"] = "1" if p[14] & 0x80 else " "
    c["GuestFoulOnes"] = oes_ascii(p[14])
    # A shot clock of B0 B0 (both "0" with the high bit set) means the shot clock is not in use.
    if p[18] != 0xB0 or p[19] != 0xB0:
        if p[18] & 0x80 == 0:
            c["ShotClockSecondTens"] = oes_ascii(p[18])
            c["ShotClockSecondOnes"] = oes_ascii(p[19])
        else:
            c["ShotClockSecondTens"] = " "
            c["ShotClockSecondOnes"] = oes_ascii(p[18])


def _basketball_player(p: bytes, c: dict) -> None:
    side = {"H": "Home", "G": "Guest"}.get(oes_ascii(p[2]))
    n = oes_ascii(p[3])
    if side is None or n not in ("1", "2", "3", "4", "5"):
        return
    c[f"{side}Player{n}"] = _chars(p, 4, 5)
    c[f"{side}Player{n}FoulNumber"] = oes_ascii(p[6])
    c[f"{side}Player{n}Points"] = _chars(p, 7, 8)


class Basketball(Decoder):
    """'t' packets carry the game state, 's' packets carry one player's number, fouls and points."""

    contract = "Basketball"
    event = "Basketball"

    def __init__(self, clock_status: bool = True):
        super().__init__()
        self.clock_status = clock_status  # False for the Tissot adapter, which has no clock-stopped bit

    def decode(self, p: bytes) -> None:
        if len(p) < 2:
            return
        try:
            if p[1] == ord("t"):
                _basketball_game(p, self.c, self.clock_status)
            elif p[1] == ord("s"):
                _basketball_player(p, self.c)
        except IndexError:
            pass


# --------------------------------------------------------------------------- hockey / lacrosse
def _penalty_steps(start: int, players: bool, p3: bool, lacrosse: bool = False) -> list:
    """Penalty slots in packet order: home 1, home 2, guest 1, guest 2 (five bytes each, or three without
    player numbers). Slot 3 is never on the wire and is set blank, except for lacrosse."""
    steps: list = []
    pos = start
    for side in ("Home", "Guest"):
        for n in (1, 2):
            pre = f"{side}PenaltyPlayer{n}"
            if players:
                steps += [(pre + "Tens", pos), (pre + "Ones", pos + 1)]
                pos += 2
            else:
                steps += [(pre + "Tens", " "), (pre + "Ones", " ")]
            steps += [(pre + "ClockMinutesTens", " "), (pre + "ClockMinutesOnes", pos),
                      (pre + "ClockSecondTens", pos + 1), (pre + "ClockSecondOnes", pos + 2)]
            pos += 3
        if p3:
            pre = f"{side}PenaltyPlayer3"
            steps += [(pre + s, " ") for s in ("Tens", "Ones", "ClockMinutesTens", "ClockMinutesOnes",
                                               "ClockSecondTens", "ClockSecondOnes")]
    return steps


def _hockey_steps(shots: int, penalties: int, players: bool = True) -> list:
    return [
        _set_clock,
        *_score((7, 8), (9, 10)),
        ("HomeGoal", " "), ("GuestGoal", " "), ("HomeTimeOut", " "), ("GuestTimeOut", " "),
        ("HomeShotOnGoalTens", shots), ("HomeShotOnGoalOnes", shots + 1),
        ("GuestShotOnGoalTens", shots + 2), ("GuestShotOnGoalOnes", shots + 3),
        ("Period", 6), ("Horn", " "),
        *_penalty_steps(penalties, players, p3=True),
    ]


class HockeyStandard(_TableDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    kind = 116
    steps = _hockey_steps(11, 19)


class HockeyPro(_TableDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    kind = 116
    steps = _hockey_steps(18, 22)


class HockeyISC85X(_TableDecoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    kind = 116
    steps = _hockey_steps(11, 17)


class ShortHockeyStandard(_TableDecoder):
    """Short hockey packet: penalty clocks only (no player numbers), no byte-1 check."""

    contract = "HockeyLacrosse"
    event = "Hockey"
    steps = _hockey_steps(11, 19, players=False)


class Lacrosse(_TableDecoder):
    contract = "HockeyLacrosse"
    event = "Lacrosse"
    steps = [
        _set_clock,
        ("ShotClockTens", 42), ("ShotClockOnes", 43),
        *_score((7, 8), (9, 10)),
        ("Period", 6),
        ("HomeShotOnGoalTens", 18), ("HomeShotOnGoalOnes", 19),
        ("GuestShotOnGoalTens", 20), ("GuestShotOnGoalOnes", 21),
        *_penalty_steps(22, True, p3=False),
    ]


# --------------------------------------------------------------------------- soccer / volleyball / wrestling
class SoccerPro(_TableDecoder):
    contract = "Soccer"
    event = "Soccer"
    kind = 115  # 's'
    steps = [
        _set_clock,
        *_score((7, 8), (9, 10)),
        ("HomePossession", " "), ("GuestPossession", " "),
        ("HomeShotTens", 11), ("HomeShotOnes", 12), ("HomeSaves", (13, 14)),
        ("GuestShotTens", 19), ("GuestShotOnes", 20), ("GuestSaves", (21, 22)),
        ("HomeCornerKicks", (15, 16)), ("GuestCornerKicks", (23, 24)),
        ("HomeTimeouts", " "), ("GuestTimeouts", " "),
        ("Period", 6),
        ("HomePenalties", (17, 18)), ("GuestPenalties", (25, 26)),
    ]


class Volleyball(_TableDecoder):
    contract = "Volleyball"
    event = "Volleyball"
    kind = 116
    steps = [
        _set_clock,
        _basketball_clock_status,
        ("Set", 6),
        lambda p, c: c.__setitem__("IsSet3", "1" if c["Set"] == "3" else "0"),
        *_score((7, 8), (9, 10)),
        ("HomeTimeout", 11), ("GuestTimeout", 12),
        lambda p, c: c.__setitem__("HomeServe", "*" if p[17] == 49 else " "),
        lambda p, c: c.__setitem__("GuestServe", "*" if p[18] == 49 else " "),
        ("HomeGamesWon", 20), ("GuestGamesWon", 22),
    ]


class Wrestling(_TableDecoder):
    contract = "Wrestling"
    event = "Wrestling"
    steps = [
        _set_clock,
        ("Period", 6),
        *_score((7, 8), (9, 10)),
        ("HomeMatchScoreTens", 19), ("HomeMatchScoreOnes", 20),
        ("GuestMatchScoreTens", 21), ("GuestMatchScoreOnes", 22),
        ("HomeMatchTens", 25), ("HomeMatchOnes", 26),
    ]


# --------------------------------------------------------------------------- autodetect
# Packet length (STX..CR inclusive) -> (decoder factory, vendor-sport id)
AUTODETECT = {
    21: (FootballWireless, "OES_FootballWireless"),
    23: (Basketball, "OES_Basketball"),
    25: (Football, "OES_Football"),
    31: (Volleyball, "OES_Volleyball"),
    32: (SoccerPro, "OES_SoccerPro"),
    36: (ShortHockeyStandard, "OES_ShortHockeyStandard"),
    44: (HockeyStandard, "OES_HockeyStandard"),
    45: (HockeyPro, "OES_HockeyPro"),
    47: (Lacrosse, "OES_Lacrosse"),
    48: (BaseballCode85, "OES_Baseball_Code85"),
    52: (BaseballISC85X, "OES_BaseballISC85X"),
    75: (BaseballStandard, "OES_BaseballStandard"),
    72: (BaseballPro, "OES_BaseballPro"),
    117: (BaseballPro, "OES_BaseballPro"),
}


class Autodetect(Decoder):
    """Picks the sport from the packet length. ``contract``, ``event`` and ``c`` follow the selected decoder.

    A new decoder (with a clean contract) is created whenever a packet arrives whose length is in
    :data:`AUTODETECT` and differs from the length that selected the current decoder. Packets of any other
    length go to the current decoder; before one is selected they are ignored. ``detected`` holds the
    vendor-sport id of the current choice and ``on_detect`` (optional) is called with it on each switch.
    """

    def __init__(self, on_detect=None):
        self._sel: Decoder | None = None
        self._size = 0
        self._own: dict = {"EventId": "AutoDetect"}
        self.detected: str | None = None
        self.on_detect = on_detect

    @property
    def contract(self) -> str:  # type: ignore[override]
        return self._sel.contract if self._sel else "Generic"

    @property
    def event(self) -> str:  # type: ignore[override]
        return self._sel.event if self._sel else "AutoDetect"

    @property
    def c(self) -> dict:  # type: ignore[override]
        return self._sel.c if self._sel else self._own

    @c.setter
    def c(self, value: dict) -> None:
        if self._sel:
            self._sel.c = value
        else:
            self._own = value

    def decode(self, p: bytes) -> None:
        if p and self._size != len(p) and len(p) in AUTODETECT:
            factory, vs = AUTODETECT[len(p)]
            self._size = len(p)
            self._sel = factory()
            self.detected = vs
            if self.on_detect:
                self.on_detect(vs)
        if self._sel:
            self._sel.decode(p)

    def reset(self) -> None:
        if self._sel:
            self._sel.reset()
        else:
            self._own = {"EventId": "AutoDetect"}


# --------------------------------------------------------------------------- registry
def _p(decoder_factory):
    return lambda: OesProtocol(decoder_factory())


PROTOCOLS = {
    "OES_AutoDetect": _p(Autodetect),
    "OES_BaseballISC85X": _p(BaseballISC85X),
    "OES_BaseballPro": _p(BaseballPro),
    "OES_BaseballStandard": _p(BaseballStandard),
    "OES_Baseball_Code50": _p(BaseballCode50),
    "OES_Baseball_Code53": _p(BaseballCode53),
    "OES_Baseball_Code85": _p(BaseballCode85),
    "OES_Basketball": _p(Basketball),
    "OES_Basketball_Tissot_Adapter": _p(lambda: Basketball(clock_status=False)),
    "OES_Football": _p(Football),
    "OES_FootballWireless": _p(FootballWireless),
    "OES_HockeyPro": _p(HockeyPro),
    "OES_HockeyStandard": _p(HockeyStandard),
    "OES_Hockey_ISC85X": _p(HockeyISC85X),
    "OES_Lacrosse": _p(Lacrosse),
    "OES_ShortHockeyStandard": _p(ShortHockeyStandard),
    "OES_SoccerPro": _p(SoccerPro),
    "OES_Volleyball": _p(Volleyball),
    "OES_Wrestling": _p(Wrestling),
}
