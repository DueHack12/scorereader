"""Sportzcast "sbdata" input: decodes another bot's / controller's 150-character stream back into a contract.

Wire format (ScoreConnect namespace SportzCast)::

    150 ASCII characters, then LF (0x0A)

Characters 0-1 are the sport code ("02" = football, "08" = soccer, ...). Everything else is a fixed-width
layout that depends on the sport (see docs/vendors/sportzcast.md). There is no checksum: a frame is valid
when exactly 150 bytes precede the LF; anything else is rejected and skipped.

The Contracts.Ingress classes in ScoreConnect are a JSON/HTTP input path (numbers and booleans in, contract
out) and do not touch this byte stream, so they are not used here.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find

__all__ = ["PROTOCOLS", "SbDataProtocol", "SbDataDecoder", "AutodetectDecoder", "VirtualBotDecoder"]

PACKET_LEN = 150

# A field spec is an int (one character at that offset) or a tuple of offsets (characters joined in order).


def _span(start: int, n: int) -> tuple:
    return tuple(range(start, start + n))


def _pair(a: int) -> tuple:
    return (a, a + 1)


# --------------------------------------------------------------------------- layouts (field -> spec)
def _penalties(home_first: int, guest_first: int, players: int) -> dict:
    """Penalty boxes: per player 6 characters (number tens/ones, then mm:ss tens/ones)."""
    out = {}
    for side, first in (("Home", home_first), ("Guest", guest_first)):
        for n in range(1, players + 1):
            b = first + 6 * (n - 1)
            for k, name in enumerate(("Tens", "Ones", "ClockMinutesTens", "ClockMinutesOnes",
                                      "ClockSecondTens", "ClockSecondOnes")):
                out[f"{side}PenaltyPlayer{n}{name}"] = b + k
    return out


def _football() -> dict:
    t = {"PlayClockTens": 8, "PlayClockOnes": 9, "Flag": 10, "HomeScoreTens": 11, "HomeScoreOnes": 12,
         "Horn": 13, "GuestScoreTens": 14, "GuestScoreOnes": 15, "HomePossession": 16, "GuestPossession": 17,
         "HomeTimeouts": 18, "GuestTimeouts": 19, "Down": 20, "ToGoTens": 21, "ToGoOnes": 22,
         "BallOnTens": 23, "BallOnOnes": 24, "Quarter": 25,
         "HomeTeamName": _span(26, 8), "GuestTeamName": _span(34, 8),
         "HomeYardsRushing": _span(42, 4), "HomeYardsPassing": _span(46, 4), "HomeTotalYards": _span(50, 4),
         "VisitorYardsRushing": _span(54, 4), "VisitorYardsPassing": _span(58, 4),
         "VisitorTotalYards": _span(62, 4),
         "HomeTotalFirstDowns": _pair(66), "VisitorTotalFirstDowns": _pair(68)}
    for n in range(1, 5):
        t[f"HomeScoreQuarter{n}"] = _pair(70 + 2 * (n - 1))
        t[f"VisitorScoreQuarter{n}"] = _pair(78 + 2 * (n - 1))
    return t


def _soccer() -> dict:
    return {"HomeScoreTens": 11, "HomeScoreOnes": 12, "HomePossession": 13, "GuestScoreTens": 14,
            "GuestScoreOnes": 15, "GuestPossession": 16, "HomeShotTens": 17, "HomeShotOnes": 18,
            "HomeCornerKicks": (47, 19), "GuestShotTens": 20, "GuestShotOnes": 21,
            "GuestCornerKicks": (48, 22), "HomeSaves": _pair(23), "GuestSaves": _pair(25),
            "HomeTimeouts": 27, "GuestTimeouts": 28, "Period": 29,
            "HomeTeamName": _span(31, 8), "GuestTeamName": _span(39, 8),
            "HomePenalties": _pair(49), "GuestPenalties": _pair(51)}


def _basketball() -> dict:
    t = {"HomeDoubleBonus": 6, "GuestDoubleBonus": 7, "ShotClockSecondTens": 8, "ShotClockSecondOnes": 9,
         "HomeScoreHundreds": 10, "HomeScoreTens": 11, "HomeScoreOnes": 12, "GuestScoreHundreds": 13,
         "GuestScoreTens": 14, "GuestScoreOnes": 15, "HomePossession": 16, "GuestPossession": 17,
         "HomeTimeouts": 18, "GuestTimeouts": 19, "HomeBonus": 20, "GuestBonus": 21, "HomeFoulTens": 22,
         "HomeFoulOnes": 23, "GuestFoulTens": 24, "GuestFoulOnes": 25, "FoulPlayerTens": 26,
         "FoulPlayerOnes": 27, "FoulPlayerNumberOfFouls": 28, "Period": 29, "Horn": 30,
         "HomeTeamName": _span(31, 8), "GuestTeamName": _span(39, 8),
         "HomeFullTimeouts": 60, "HomePartialTimeouts": 62, "GuestFullTimeouts": 64,
         "GuestPartialTimeouts": 66, "HomeBottomCenter": 82,
         "TimeoutClockMinutesOnes": 112, "TimeoutClockSecondTens": 114, "TimeoutClockSecondOnes": 115}
    # (side, player, name offset, foul offset, points offset)
    rows = [("Home", 1, 47, 49, 50), ("Home", 2, 52, 54, 55), ("Home", 3, 67, 69, 70),
            ("Home", 4, 72, 74, 75), ("Home", 5, 77, 79, 80),
            ("Guest", 1, 83, 85, 86), ("Guest", 2, 88, 90, 91), ("Guest", 3, 93, 95, 96),
            ("Guest", 4, 121, 123, 124), ("Guest", 5, 126, 128, 129)]
    for side, n, name, foul, pts in rows:
        t[f"{side}Player{n}"] = _pair(name)
        t[f"{side}Player{n}FoulNumber"] = foul
        t[f"{side}Player{n}Points"] = _pair(pts)
    return t


def _baseball() -> dict:
    t = {"Balls": 6, "Strikes": 7, "Outs": 8, "InningTens": 9, "InningOnes": 10, "GuestRunTens": 11,
         "GuestRunOnes": 12, "HomeRunTens": 13, "HomeRunOnes": 14, "TopBottomInning": 15,
         "GuestHitsTens": 16, "GuestHitsOnes": 17, "HomeHitsTens": 18, "HomeHitsOnes": 19,
         "GuestErrors": 20, "HomeErrors": 21, "AtBatTens": 22, "AtBatOnes": 23, "ErrorFlag": 24,
         "GuestErrorNumber": 25, "TopOfInning": 26, "BottomOfInning": 27,
         "GuestTeamName": _span(50, 8), "HomeTeamName": _span(58, 8), "OnFirst": 66, "OnSecond": 67,
         "OnThird": 68, "PitchSpeed": _span(69, 3), "PitchCount": _span(72, 3)}
    for n in range(1, 11):
        t[f"GuestInning{n}"] = 28 + 2 * n
        t[f"HomeInning{n}"] = 29 + 2 * n
    return t


def _hockey_lacrosse() -> dict:
    t = {"ShotClockTens": 8, "ShotClockOnes": 9, "HomeScoreTens": 11, "HomeScoreOnes": 12, "HomeGoal": 13,
         "GuestScoreTens": 14, "GuestScoreOnes": 15, "GuestGoal": 16, "HomeTimeOut": 18, "GuestTimeOut": 19,
         "HomePlayerPopUp": _pair(20), "GuestPlayerPopUp": _pair(22), "HomeShotOnGoalTens": 24,
         "HomeShotOnGoalOnes": 25, "GuestShotOnGoalTens": 26, "GuestShotOnGoalOnes": 27, "Period": 29,
         "Horn": 30, "HomeTeamName": _span(31, 8), "GuestTeamName": _span(39, 8),
         "HomeFullTimeoutsRemaining": 83, "GuestFullTimeoutsRemaining": 84,
         "HomePartialTimeoutsRemaining": 85, "GuestPartialTimeoutsRemaining": 86,
         "HomeSaves": _pair(87), "GuestSaves": _pair(89), "HomePossession": 91, "GuestPossession": 92}
    t.update(_penalties(47, 65, 3))
    for side, first in (("Home", 119), ("Guest", 125)):
        for n in range(1, 4):
            t[f"{side}Player{n}PenaltyType1"] = first + 2 * (n - 1)
            t[f"{side}Player{n}PenaltyType2"] = first + 2 * (n - 1) + 1
    return t


def _futsal_handball() -> dict:
    t = {"HomeScoreTens": 11, "HomeScoreOnes": 12, "GuestScoreTens": 13, "GuestScoreOnes": 14,
         "HomeTimeOut": 15, "GuestTimeOut": 16, "HomeFouls": 17, "GuestFouls": 18, "Period": 19, "Horn": 20,
         "HomeTeamName": _span(21, 8), "GuestTeamName": _span(29, 8)}
    t.update(_penalties(47, 65, 3))
    return t


def _swimming() -> dict:
    t = {"InternalClockStatus": 116, "ClockMode": 117, "PlayClockStatusInternal": 118,
         "ClockMinutesTens": 2, "ClockMinutesOnes": 3, "ClockSecondTens": 4, "ClockSecondOnes": 5,
         "ClockTenthsSecond": 6}
    for n in range(1, 9):
        b = 7 + 11 * (n - 1)
        t[f"FinishFlag{n}"] = b
        t[f"Split{n}"] = _pair(b + 1)
        t[f"Place{n}"] = b + 3
        t[f"Clock{n}"] = _span(b + 4, 7)
    return t


def _table_tennis() -> dict:
    t = {"Set": 6, "HomePoints": _pair(7), "GuestPoints": _pair(9), "HomeSetsWon": 11, "GuestSetsWon": 12,
         "HomeServe": 13, "GuestServe": 14, "HomeTeamName": _span(31, 8), "GuestTeamName": _span(39, 8)}
    for n in range(1, 5):
        t[f"HomePointsSet{n}"] = _pair(15 + 4 * (n - 1))
        t[f"GuestPointsSet{n}"] = _pair(17 + 4 * (n - 1))
    return t


def _tennis() -> dict:
    t = {"ClockHourTens": 2, "ClockHourOnes": 3, "ClockMinutesTens": 4, "ClockMinutesOnes": 5, "Set": 6,
         "TopPoints": _span(7, 2), "BottomPoints": _span(9, 2), "TopServe": 16, "BottomServe": 17,
         "Court": 23, "GameNumberOnes": 24, "TopTeamScore": _span(25, 2), "BottomTeamScore": _span(27, 2),
         "IsDeuce": 29, "Advantage": 30, "TopPlayerName": _span(31, 8), "BottomPlayerName": _span(39, 8),
         "TopTeamName": _span(47, 8), "BottomTeamName": _span(55, 8), "IsTieBreak": 63, "IsSet3": 84,
         "GameNumberTens": 85, "PacketTwittle": 97}
    for n in range(1, 6):
        t[f"TopSet{n}Ones"] = 11 + (n - 1)
        t[f"BottomSet{n}Ones"] = 18 + (n - 1)
        t[f"TopSet{n}Tens"] = 86 + (n - 1)
        t[f"BottomSet{n}Tens"] = 91 + (n - 1)
        t[f"Set{n}TopTieBreak"] = _span(64 + 4 * (n - 1), 2)
        t[f"Set{n}BottomTieBreak"] = _span(66 + 4 * (n - 1), 2)
    return t


def _volleyball() -> dict:
    t = {"HomeGamesWon": 6, "HomeScoreTens": 7, "HomeScoreOnes": 8, "GuestGamesWon": 9, "GuestScoreTens": 10,
         "GuestScoreOnes": 11, "HomeServe": 12, "GuestServe": 13, "HomeTimeout": 14, "GuestTimeout": 15,
         "HomeTeamName": _span(32, 8), "GuestTeamName": _span(40, 8),
         "HomeScoreSet5": _pair(102), "GuestScoreSet5": _pair(104), "IsSet3": 106, "Set": 119, "Game": 120}
    for n in range(1, 5):
        t[f"HomeScoreSet{n}"] = _pair(16 + 4 * (n - 1))
        t[f"GuestScoreSet{n}"] = _pair(18 + 4 * (n - 1))
    firsts = [("Home", n, 48 + 5 * (n - 1)) for n in range(1, 7)]
    firsts += [("Guest", n, 78 + 5 * (n - 1)) for n in range(1, 5)] + [("Guest", 5, 121), ("Guest", 6, 126)]
    for side, n, b in firsts:
        t[f"{side}Player{n}"] = _pair(b)
        t[f"{side}Player{n}Kills"] = b + 2
        t[f"{side}Player{n}Digs"] = _pair(b + 3)
    return t


def _water_polo() -> dict:
    t = {"ClockMinutesTens": 2, "ClockMinutesOnes": 3, "ClockSecondTens": 5, "ClockSecondOnes": 6,
         "ClockTenthsSecond": 8, "ClockHundreths": 9, "ShotClockTens": 10, "ShotClockOnes": 11, "Period": 12,
         "TimeoutMinutesOnes": 13, "TimeoutSecondsTens": 15, "TimeoutSecondsOnes": 16, "GuestScoreTens": 17,
         "GuestScoreOnes": 18, "GuestTimeouts": 19, "HomeScoreTens": 20, "HomeScoreOnes": 21,
         "HomeTimeouts": 22, "HomeTeamName": _span(23, 8), "GuestTeamName": _span(31, 8),
         "InternalClockStatus": 116, "ClockMode": 117}
    t.update(_penalties(39, 51, 2))
    return t


def _wrestling() -> dict:
    return {"InternalClockStatus": 116, "ClockMode": 117, "PlayClockStatusInternal": 118,
            "ClockMinutesTens": 2, "ClockMinutesOnes": 3, "ClockSecondTens": 4, "ClockSecondOnes": 5,
            "ClockTenthsSecond": 6, "HomeMatchHundreds": 8, "HomeMatchTens": 9, "HomeMatchOnes": 10,
            "HomeScoreTens": 11, "HomeScoreOnes": 12, "HomeMatchScoreTens": 13, "HomeMatchScoreOnes": 14,
            "GuestScoreTens": 15, "GuestScoreOnes": 16, "GuestMatchScoreTens": 17, "GuestMatchScoreOnes": 18,
            "WeightClass": _span(19, 3), "AdvantageTimeMinutesOnes": 22, "AdvantageTimeSecondTens": 23,
            "AdvantageTimeSecondOnes": 24, "AdvantageHome": 25, "AdvantageGuest": 26, "Period": 29,
            "Horn": 30, "HomeTeamName": _span(31, 8), "GuestTeamName": _span(39, 8)}


def _generic() -> dict:
    return {"TOTimerMinutesOnes": 2, "TOTimerSecondsTens": 3, "TOTimerSecondsOnes": 4, "ClockDigit1": 5,
            "ClockDigit2": 6, "ClockDigit3": 7, "ClockDigit4": 8, "HomeHundreds": 9, "HomeTens": 10,
            "HomeOnes": 11, "GuestHundreds": 12, "GuestTens": 13, "GuestOnes": 14, "Period": 15,
            "HomeFouls": 16, "GuestFouls": 17, "HomeNumberOfTO": 18, "GuestNumberOfTO": 19, "ClockMode": 20,
            "InternalClockStatus": 21, "PlayClockStatusInternal": 22, "PlayClockDisplay": 23,
            "PlayClock": _pair(24)}


# --------------------------------------------------------------------------- decoder
class SbDataDecoder(Decoder):
    """One sbdata layout. ``std_clock`` marks layouts that carry the usual clock at offsets 2-5 / 116-118."""

    def __init__(self, contract: str, event: str, table: dict, std_clock: bool = True):
        self.contract = contract
        self.event = event
        self.table = table
        self.std_clock = std_clock
        super().__init__()

    def _set_clock(self, s: str) -> None:
        c = self.c
        status, mode1, mode2 = s[116].upper(), s[117], s[118].upper()
        if status in ("R", "S"):
            c["InternalClockStatus"] = status
        if mode1 in (":", "."):
            c["ClockMode"] = mode1
        if mode2 in (":", "."):
            c["ClockMode"] = mode2
        if c.get("ClockMode", " ") in (":", " "):
            c["ClockMinutesTens"], c["ClockMinutesOnes"] = s[2], s[3]
            c["ClockSecondTens"], c["ClockSecondOnes"] = s[4], s[5]
            c["ClockTenthsSecond"] = "0"
        else:  # tenths-of-a-second display: seconds.tenths
            c["ClockMinutesTens"] = c["ClockMinutesOnes"] = "0"
            c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"] = s[2], s[3], s[4]

    def decode(self, packet: bytes) -> None:
        s = packet.decode("latin-1").ljust(PACKET_LEN)
        if self.std_clock:
            self._set_clock(s)
        c = self.c
        for field, spec in self.table.items():
            c[field] = s[spec] if isinstance(spec, int) else "".join(s[i] for i in spec)


def _make(contract: str, event: str, table_fn, std_clock: bool = True):
    return lambda: SbDataDecoder(contract, event, table_fn(), std_clock)


# event name -> factory; shared by the plain ids, Autodetect and VirtualBot
_BASEBALL = _make("BaseballSoftball", "Baseball", _baseball)
_SOFTBALL = _make("BaseballSoftball", "Softball", _baseball)
_FOOTBALL = _make("Football", "Football", _football)
_BASKETBALL = _make("Basketball", "Basketball", _basketball)
_HOCKEY = _make("HockeyLacrosse", "Hockey", _hockey_lacrosse)
_LACROSSE = _make("HockeyLacrosse", "Lacrosse", _hockey_lacrosse)
_SOCCER = _make("Soccer", "Soccer", _soccer)
_VOLLEYBALL = _make("Volleyball", "Volleyball", _volleyball)
_WRESTLING = _make("Wrestling", "Wrestling", _wrestling, False)
_SWIMMING = _make("SwimmingDetail", "Swimming", _swimming, False)
_TENNIS = _make("Tennis", "Tennis", _tennis, False)
_WATERPOLO = _make("WaterPolo", "WaterPolo", _water_polo, False)
_GENERIC = _make("Generic", "Generic", _generic, False)
_FUTSAL = _make("FutsalHandball", "Futsal", _futsal_handball)
_HANDBALL = _make("FutsalHandball", "Handball", _futsal_handball)
_TABLETENNIS = _make("TableTennisBadminton", "TableTennis", _table_tennis)
_BADMINTON = _make("TableTennisBadminton", "Badminton", _table_tennis)

# sport code (first two characters of the packet) -> decoder factory
_BY_CODE = {1: _BASEBALL, 2: _FOOTBALL, 3: _BASKETBALL, 4: _SOFTBALL, 5: _HOCKEY, 6: _VOLLEYBALL,
            7: _LACROSSE, 8: _SOCCER, 12: _WRESTLING, 13: _SWIMMING, 16: _TENNIS, 24: _WATERPOLO,
            28: _GENERIC, 29: _FUTSAL, 30: _HANDBALL, 31: _TABLETENNIS, 32: _BADMINTON}

# codes the Virtual Bot can start with (no futsal/handball/table tennis/badminton/generic)
_VBOT_CODES = (1, 2, 3, 4, 5, 6, 7, 8, 12, 13, 16, 24)


def _sport_code(packet: bytes) -> int:
    """The sport code from the first two characters ("02" -> 2), or -1."""
    if len(packet) >= 2 and 0x30 <= packet[0] <= 0x39 and 0x30 <= packet[1] <= 0x39:
        return (packet[0] - 0x30) * 10 + (packet[1] - 0x30)
    return -1


class _SelectingDecoder(Decoder):
    """Picks a layout from the packet's sport code; contract / event / c follow the selected layout."""

    _codes: tuple = ()
    _switch = True  # Autodetect re-selects when the code changes; the Virtual Bot locks on the first packet

    def __init__(self):
        self._sel: SbDataDecoder | None = None
        self._code = -1

    @property
    def contract(self) -> str:
        return self._sel.contract if self._sel else "Generic"

    @property
    def event(self) -> str:
        return self._sel.event if self._sel else "AutoDetect"

    @property
    def c(self) -> dict:
        return self._sel.c if self._sel else {}

    @c.setter
    def c(self, value: dict) -> None:
        if self._sel:
            self._sel.c = value

    @property
    def code(self) -> int:
        return self._code

    def reset(self) -> None:
        self._sel = None
        self._code = -1

    def _select(self, code: int) -> None:
        if code in self._codes and (code != self._code) and (self._switch or self._sel is None):
            self._sel = _BY_CODE[code]()
            self._code = code

    def decode(self, packet: bytes) -> None:
        self._select(_sport_code(packet))
        if self._sel is not None:
            self._sel.decode(packet)


class AutodetectDecoder(_SelectingDecoder):
    """Sportzcast_SBData_Autodetect: follows the sport code in every packet (a change starts a fresh contract).

    ScoreConnect's own version builds the code from the raw byte values (``"{b0}{b1}"``), which only matches
    when the stream carries binary 0x00 0x02 style codes. We accept the ASCII form that real sbdata uses and
    also that raw form (single-digit bytes 0-9 followed by a second byte, e.g. 0x01 0x02 -> "12").
    """

    _codes = tuple(_BY_CODE)

    def decode(self, packet: bytes) -> None:
        code = _sport_code(packet)
        if code < 0 and len(packet) >= 2:
            raw = int(f"{packet[0]}{packet[1]}")  # decimal concatenation of the two byte values
            code = raw if raw in _BY_CODE else -1
        self._select(code)
        if self._sel is not None:
            self._sel.decode(packet)


class VirtualBotDecoder(_SelectingDecoder):
    """Sportzcast_VirtualBot: the first packet's sport code fixes the layout for the rest of the session."""

    _codes = _VBOT_CODES
    _switch = False

    def decode(self, packet: bytes) -> None:
        if self._sel is None and _sport_code(packet) not in self._codes:
            raise NotImplementedError(f"sport code {packet[:2]!r} is not supported by the virtual bot")
        super().decode(packet)


# --------------------------------------------------------------------------- protocol
class SbDataProtocol(Protocol):
    """150 characters terminated by LF; anything else between line feeds is counted as an error."""

    def extract(self):
        buf = self.buf
        while True:
            i = find(buf, 0x0A)
            if i < 0:
                return
            pkt = bytes(buf[:i])
            del buf[: i + 1]
            if len(pkt) == PACKET_LEN:
                yield pkt
            else:
                self.reject()


PROTOCOLS = {
    "SportzcastSBData_Autodetect": lambda: SbDataProtocol(AutodetectDecoder()),
    "SportzcastSBData_Badminton": lambda: SbDataProtocol(_BADMINTON()),
    "SportzcastSBData_Baseball": lambda: SbDataProtocol(_BASEBALL()),
    "SportzcastSBData_Basketball": lambda: SbDataProtocol(_BASKETBALL()),
    "SportzcastSBData_Football": lambda: SbDataProtocol(_FOOTBALL()),
    "SportzcastSBData_Futsal": lambda: SbDataProtocol(_FUTSAL()),
    "SportzcastSBData_Handball": lambda: SbDataProtocol(_HANDBALL()),
    "SportzcastSBData_Hockey": lambda: SbDataProtocol(_HOCKEY()),
    "SportzcastSBData_Lacrosse": lambda: SbDataProtocol(_LACROSSE()),
    "SportzcastSBData_Soccer": lambda: SbDataProtocol(_SOCCER()),
    "SportzcastSBData_Softball": lambda: SbDataProtocol(_SOFTBALL()),
    "SportzcastSBData_Swimming": lambda: SbDataProtocol(_SWIMMING()),
    "SportzcastSBData_TableTennis": lambda: SbDataProtocol(_TABLETENNIS()),
    "SportzcastSBData_Tennis": lambda: SbDataProtocol(_TENNIS()),
    "SportzcastSBData_Volleyball": lambda: SbDataProtocol(_VOLLEYBALL()),
    "SportzcastSBData_Waterpolo": lambda: SbDataProtocol(_WATERPOLO()),
    "SportzcastSBData_Wrestling": lambda: SbDataProtocol(_WRESTLING()),
    "Sportzcast_VirtualBot": lambda: SbDataProtocol(VirtualBotDecoder()),
}
