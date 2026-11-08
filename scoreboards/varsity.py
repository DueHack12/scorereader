"""Varsity Scoreboards (original RS-485 "Varsity" and "Varsity Gen2").

Two wire formats, both read through a ScoreLinkII in no-decode mode (RS-485):

* Varsity (Main): length-prefixed packets ``[n, type, data..., chk]`` with ``n`` = packet length (3-19) and the
  byte sum of the whole packet equal to 0xAA. Data bytes are consecutive registers starting at ``type``.
* Varsity Gen2: ``F6 len ... `` frames of ``len + 1`` bytes whose byte sum is 0xA0; the page is in byte 5.

The boards send the clocks as a start/stop message with a time value instead of every tick, so the
decoders run the clock themselves (a countdown that is re-anchored when it is started). Read the clock
fields live with ``Protocol.tick()`` / ``snapshot()``; ``Protocol.version`` ticks the clock as well, so
anything that polls ``version`` sees a running clock change.

See docs/vendors/varsity.md for the register tables.
"""
from __future__ import annotations

import threading
import time

from .base import Decoder, Protocol
from .common import ascii_char, bcd, dec

__all__ = ["PROTOCOLS", "MainProtocol", "Gen2Protocol"]

SUM_MAIN = 0xAA
SUM_GEN2 = 0xA0
SYNC_GEN2 = 0xF6


# --------------------------------------------------------------------------- small helpers
def _bz(ch: str) -> str:
    """Blank a zero digit."""
    return " " if ch == "0" else ch


def _s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _pair(tens: str, ones: str):
    """2-digit value with a blank-padded tens digit -> {tens, ones}."""
    return lambda b: {tens: dec(b, 1, 2, True), ones: dec(b, 0, 2, True)}


def _score3(*keys: str):
    """3-digit blank-left value -> keys (hundreds?, tens, ones)."""
    n = len(keys)
    return lambda b: {k: dec(b, n - 1 - i, 3, True) for i, k in enumerate(keys)}


def _digit(key: str):
    return lambda b: {key: dec(b, 0)}


def _flag(key: str, on: str):
    """Main protocol lamp: ones digit == 1."""
    return lambda b: {key: on if dec(b, 0) == "1" else " "}


def _possession(b: int) -> dict:
    if b & 1:
        return {"HomePossession": "<", "GuestPossession": " "}
    return {"HomePossession": " ", "GuestPossession": ">"}


# --------------------------------------------------------------------------- clocks
class _Countdown:
    """Countdown timer with a settable value. A value received while it is already running does not move the
    running timer (it only takes effect after a stop), as in ScoreConnect."""

    def __init__(self, now):
        self._now = now
        self.running = False
        self.value_ms = 0
        self._end = None

    def set(self, ms: int, running: bool) -> None:
        self.running = running
        self.value_ms = ms
        if not running:
            self._end = None
        elif self._end is None:
            self._end = self._now() * 1000.0 + ms

    def read_ms(self) -> int:
        if not self.running:
            return self.value_ms
        if self._end is None:
            self._end = self._now() * 1000.0 + self.value_ms
        return max(0, int(self._end - self._now() * 1000.0))


def _clock_text(ms: int) -> str:
    """MMSSt as a string: total minutes within the hour plus 60 per hour, seconds, tenths."""
    ms = max(0, int(ms))
    minutes = (ms // 3600000) * 60 + (ms // 60000) % 60
    return f"{minutes:02d}{(ms // 1000) % 60:02d}{(ms % 1000) // 100}"


def _round_main(ms: int) -> int:
    """Varsity (Main) display rounding: whole seconds (rounded up) at a minute or more, tenths below."""
    msp = ms % 1000
    sec = (ms // 1000) % 60
    if (ms // 60000) % 60 > 0:
        total = ((ms // 60000) % 60) * 60 + sec + (1 if msp // 100 > 0 else 0)
        return total * 1000
    tenths = msp // 100
    if msp % 100 >= 10:
        tenths += 1
    return sec * 1000 + tenths * 100


def _round_gen2(ms: int) -> int:
    """Varsity Gen2 rounding. Any non-zero fraction bumps the tenths digit by one (0.5 s shows 0.6)."""
    msp = ms % 1000
    sec = (ms // 1000) % 60
    if (ms // 60000) % 60 > 0:
        total = ((ms // 60000) % 60) * 60 + sec + (1 if msp > 0 else 0)
        return total * 1000
    tenths = msp // 100
    if msp - tenths > 0:
        tenths += 1
    return sec * 1000 + tenths * 100


class _ClockedDecoder(Decoder):
    """Decoder with a self-running main clock and an optional play/shot clock."""

    round_ms = staticmethod(lambda ms: ms)
    skip_unchanged = False   # Varsity Main only writes the main clock when its text changes
    play_keys: tuple | None = None   # contract keys for the seconds tens/ones of the play (shot) clock

    def __init__(self, now=None):
        super().__init__()
        self.now = now or time.monotonic
        self._init_clocks()

    def _init_clocks(self) -> None:
        self._main = _Countdown(lambda: self.now())
        self._play = _Countdown(lambda: self.now())
        self._old = "00000"

    def reset(self) -> None:
        super().reset()
        self._init_clocks()

    def set_main(self, ms: int, running: bool) -> None:
        self._main.set(ms, running)
        self.c["InternalClockStatus"] = "R" if running else "S"

    def set_play(self, ms: int, running: bool) -> None:
        self._play.set(ms, running)
        self.c["PlayClockStatusInternal"] = "R" if running else "S"

    def refresh(self) -> bool:
        """Recompute the clock fields from the current time. Returns True if the contract changed."""
        before = dict(self.c)
        c = self.c
        text = _clock_text(self.round_ms(self._main.read_ms()))
        if not (self.skip_unchanged and text[:5] == self._old):
            self._old = text[:5]
            if text[0] == "0" and text[1] == "0":
                c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0", ClockSecondTens=text[2],
                         ClockSecondOnes=text[3], ClockTenthsSecond=text[4])
            else:
                c.update(ClockMode=":", ClockMinutesTens=text[0], ClockMinutesOnes=text[1],
                         ClockSecondTens=text[2], ClockSecondOnes=text[3], ClockTenthsSecond="0")
        if self.play_keys:
            ptext = _clock_text(self._play.read_ms())
            c[self.play_keys[0]] = ptext[2]
            c[self.play_keys[1]] = ptext[3]
        return c != before


class _TickMixin:
    """Protocol mixin: refreshes the decoder's running clocks when the contract is read or polled."""

    def _setup_tick(self) -> None:
        self.lock = threading.RLock()  # version is read from inside feed()
        self._version = getattr(self, "_version", 0)

    @property
    def version(self) -> int:
        self.tick()
        return self._version

    @version.setter
    def version(self, value: int) -> None:
        self._version = value

    def tick(self) -> bool:
        refresh = getattr(self.decoder, "refresh", None)
        if refresh is None:
            return False
        with self.lock:
            changed = refresh()
            if changed:
                self._version += 1
            return changed

    def snapshot(self) -> dict:
        self.tick()
        return super().snapshot()


# --------------------------------------------------------------------------- Varsity (Main)
class MainProtocol(_TickMixin, Protocol):
    """``[n, type, data..., chk]``, n = 3..19 bytes in all, byte sum == 0xAA."""

    def __init__(self, decoder: Decoder):
        super().__init__(decoder)
        self._setup_tick()

    def extract(self):
        buf = self.buf
        while len(buf) >= 3:
            n = buf[0]
            if not 3 <= n <= 19:
                del buf[:1]
                continue
            if len(buf) < n:
                return
            pkt = bytes(buf[:n])
            if sum(pkt) & 0xFF == SUM_MAIN:
                del buf[:n]
                yield pkt
            else:
                del buf[:1]
                self.reject()


class _MainDecoder(_ClockedDecoder):
    """Consecutive-register decoder. Subclasses fill ``registers``: type -> fn(byte) -> {field: char}."""

    registers: dict = {}
    clock_types: tuple = ()          # subset of 73 (main run), 76 (main stop), 77 (play run), 78 (play stop)
    skip_unchanged = True
    round_ms = staticmethod(_round_main)

    def decode(self, p: bytes) -> None:
        if len(p) < 2:
            return
        typ = p[1]
        if typ in self.clock_types:
            if len(p) > 6:
                ms = _s32(_s32((p[3] << 24) | (p[4] << 16) | (p[5] << 8) | p[6]) * 10)
                ms = max(0, ms)
                if typ in (73, 76):
                    self.set_main(ms, typ == 73)
                else:
                    self.set_play(ms, typ == 77)
            return
        for i in range(2, min(p[0], len(p)) - 1):
            fn = self.registers.get(typ)
            if fn:
                self.c.update(fn(p[i]))
            typ = (typ + 1) & 0xFF


def _basketball_registers() -> dict:
    return {
        0: _score3("HomeScoreHundreds", "HomeScoreTens", "HomeScoreOnes"),
        1: _score3("GuestScoreHundreds", "GuestScoreTens", "GuestScoreOnes"),
        2: _pair("HomeFoulTens", "HomeFoulOnes"),
        3: _pair("GuestFoulTens", "GuestFoulOnes"),
        4: _possession,
        6: _digit("Period"),
        9: _flag("HomeBonus", "B"),
        10: _flag("GuestBonus", "B"),
        45: _digit("HomeTimeouts"),
        46: _digit("GuestTimeouts"),
        50: _flag("HomeDoubleBonus", "B"),
        51: _flag("GuestDoubleBonus", "B"),
    }


class VarsityBasketball(_MainDecoder):
    contract = "Basketball"
    event = "Basketball"
    clock_types = (73, 76, 77, 78)
    play_keys = ("ShotClockSecondTens", "ShotClockSecondOnes")
    registers = _basketball_registers()


def _soccer_penalties(key: str):
    return lambda b: {key: dec(b, 1, 2, True) + dec(b, 0, 2, True)}


class VarsitySoccer(_MainDecoder):
    contract = "Soccer"
    event = "Soccer"
    clock_types = (73, 76)
    registers = {
        0: _score3("HomeScoreTens", "HomeScoreOnes"),
        1: _score3("GuestScoreTens", "GuestScoreOnes"),
        2: _soccer_penalties("HomePenalties"),
        3: _soccer_penalties("GuestPenalties"),
        4: _possession,
        6: _digit("Period"),
        9: _pair("HomeShotTens", "HomeShotOnes"),
        10: _pair("GuestShotTens", "GuestShotOnes"),
        45: _digit("HomeTimeouts"),
        46: _digit("GuestTimeouts"),
    }


def _inning_registers() -> dict:
    regs = {}
    for k in range(10):
        regs[16 + k] = _digit(f"HomeInning{k + 1}")
        regs[26 + k] = _digit(f"GuestInning{k + 1}")
    return regs


def _error_flag(b: int) -> dict:
    return {"ErrorFlag": "H" if b == 12 else "E" if b == 13 else " "}


def _top_bottom(key: str, letter: str):
    def fn(b: int) -> dict:
        if b == 1:
            return {key: ".", "TopBottomInning": letter}
        return {key: " "}
    return fn


def _run_pair(tens: str, ones: str):
    return lambda b: {tens: _bz(dec(b, 1)), ones: dec(b, 0)}


class VarsityBaseball(_MainDecoder):
    """No clock on this layout."""
    contract = "BaseballSoftball"
    event = "Baseball"
    registers = {
        0: _run_pair("HomeRunTens", "HomeRunOnes"),
        1: _run_pair("GuestRunTens", "GuestRunOnes"),
        2: _run_pair("HomeHitsTens", "HomeHitsOnes"),
        3: _run_pair("GuestHitsTens", "GuestHitsOnes"),
        4: _digit("HomeErrors"),
        5: _digit("GuestErrors"),
        6: _run_pair("InningTens", "InningOnes"),
        9: _digit("Balls"),
        10: _digit("Strikes"),
        11: _digit("Outs"),
        14: lambda b: {"AtBatTens": bcd(b, 1, blank="A"), "AtBatOnes": bcd(b, 0, blank="A")},
        15: _error_flag,
        41: _top_bottom("BottomOfInning", "B"),
        42: _top_bottom("TopOfInning", "T"),
        **_inning_registers(),
    }


# --------------------------------------------------------------------------- Varsity Gen2
class Gen2Protocol(_TickMixin, Protocol):
    """``F6 len ...``: ``len + 1`` bytes in all, byte sum == 0xA0 (the F6 counts)."""

    def __init__(self, decoder: Decoder):
        super().__init__(decoder)
        self._setup_tick()

    def extract(self):
        buf = self.buf
        while True:
            i = buf.find(SYNC_GEN2)
            if i < 0:
                buf.clear()
                return
            if i:
                del buf[:i]
            if len(buf) < 2:
                return
            total = buf[1] + 1
            if len(buf) < total:
                return
            frame = bytes(buf[:total])
            if sum(frame) & 0xFF == SUM_GEN2:
                del buf[:total]
                yield frame
            else:
                del buf[:1]  # resync on the next F6 (ScoreConnect drops len-1 bytes instead)
                self.reject()


def _at(p: bytes, i: int):
    return p[i] if 0 <= i < len(p) else None


def _on(key: str, ch: str):
    return lambda b: {key: ch if b == 1 else " "}


def _gen2_score(tens: str, ones: str, hundreds: str | None = None):
    def fn(b: int) -> dict:
        out = {}
        h = " "
        if hundreds:
            h = _bz(dec(b, 2, 3))
            out[hundreds] = h
        t = dec(b, 1, 3)
        out[tens] = t if h != " " else _bz(t)
        out[ones] = dec(b, 0, 3)
        return out
    return fn


def _gen2_count(tens: str, ones: str, blank: bool):
    if blank:
        return lambda b: {tens: _bz(dec(b, 1)), ones: dec(b, 0)}
    return lambda b: {tens: dec(b, 1), ones: dec(b, 0)}


class _Gen2Decoder(_ClockedDecoder):
    """Page 0 = scoreboard state at fixed byte offsets, page 1 = clock message, page 6 = team names."""

    round_ms = staticmethod(_round_gen2)
    page0: list = []                  # (byte offset, fn(byte) -> {field: char})
    clock_subs: tuple = (0, 1, 4, 5)  # 0/1 main run/stop, 4/5 play run/stop

    def decode(self, p: bytes) -> None:
        page = _at(p, 5)
        if page == 0:
            for idx, fn in self.page0:
                b = _at(p, idx)
                if b is not None:
                    self.c.update(fn(b))
        elif page == 1:
            self._clock(p)
        elif page == 6 and self.has_names:
            self._names(p)

    has_names = True

    def _clock(self, p: bytes) -> None:
        sub = _at(p, 6)
        if sub not in self.clock_subs:
            return
        if sub in (0, 1):
            if len(p) <= 10:
                return
            ms = p[7] | (p[8] << 8) | (p[9] << 16) | (p[10] << 24)
            self.set_main(max(0, _s32(ms)), sub == 0)
        else:
            if len(p) <= 11:
                return
            ms = p[8] | (p[9] << 8) | (p[10] << 16) | (p[11] << 24)
            self.set_play(max(0, _s32(ms)), sub == 4)

    def _names(self, p: bytes) -> None:
        which = _at(p, 7)
        if which in (0, 1) and len(p) >= 16:
            name = "".join(ascii_char(b) for b in p[8:16])
            self.c["HomeTeamName" if which == 0 else "GuestTeamName"] = name


_POSS_HOME = (15, _on("HomePossession", "<"))
_POSS_GUEST = (16, _on("GuestPossession", ">"))


class Gen2Basketball(_Gen2Decoder):
    contract = "Basketball"
    event = "Basketball"
    play_keys = ("ShotClockSecondTens", "ShotClockSecondOnes")
    page0 = [
        (11, _gen2_score("HomeScoreTens", "HomeScoreOnes", "HomeScoreHundreds")),
        (12, _gen2_score("GuestScoreTens", "GuestScoreOnes", "GuestScoreHundreds")),
        (13, _gen2_count("HomeFoulTens", "HomeFoulOnes", True)),
        (14, _gen2_count("GuestFoulTens", "GuestFoulOnes", True)),
        _POSS_HOME, _POSS_GUEST,
        (17, _digit("Period")),
        (27, _on("HomeBonus", "B")),
        (28, _on("GuestBonus", "B")),
        (63, _digit("HomeTimeouts")),
        (64, _digit("GuestTimeouts")),
        (68, _on("HomeDoubleBonus", "B")),
        (69, _on("GuestDoubleBonus", "B")),
    ]


class Gen2Football(_Gen2Decoder):
    contract = "Football"
    event = "Football"
    play_keys = ("PlayClockTens", "PlayClockOnes")
    page0 = [
        (11, _gen2_score("HomeScoreTens", "HomeScoreOnes")),
        (12, _gen2_score("GuestScoreTens", "GuestScoreOnes")),
        _POSS_HOME, _POSS_GUEST,
        (17, _digit("Quarter")),
        (27, _digit("Down")),
        (28, _gen2_count("ToGoTens", "ToGoOnes", False)),
        (29, _gen2_count("BallOnTens", "BallOnOnes", False)),
        (30, _digit("HomeTimeouts")),
        (31, _digit("GuestTimeouts")),
    ]


class Gen2Hockey(_Gen2Decoder):
    contract = "HockeyLacrosse"
    event = "Hockey"
    play_keys = ("ShotClockTens", "ShotClockOnes")
    page0 = [
        (11, _gen2_score("HomeScoreTens", "HomeScoreOnes")),
        (12, _gen2_score("GuestScoreTens", "GuestScoreOnes")),
        (13, _gen2_count("HomeShotOnGoalTens", "HomeShotOnGoalOnes", False)),
        (14, _gen2_count("GuestShotOnGoalTens", "GuestShotOnGoalOnes", False)),
        _POSS_HOME, _POSS_GUEST,
        (17, _digit("Period")),
    ]


class Gen2Soccer(_Gen2Decoder):
    """Main clock only (no play clock)."""
    contract = "Soccer"
    event = "Soccer"
    clock_subs = (0, 1)
    page0 = [
        (11, _gen2_score("HomeScoreTens", "HomeScoreOnes")),
        (12, _gen2_score("GuestScoreTens", "GuestScoreOnes")),
        _POSS_HOME, _POSS_GUEST,
        (17, _digit("Period")),
    ]


class Gen2Baseball(Decoder):
    """Page 0 only, packets of 62 bytes or fewer. No clock, no team names."""
    contract = "BaseballSoftball"
    event = "Baseball"
    fields = [
        (11, _run_pair("HomeRunTens", "HomeRunOnes")),
        (12, _run_pair("GuestRunTens", "GuestRunOnes")),
        (17, _run_pair("InningTens", "InningOnes")),
        (27, _digit("Balls")),
        (28, _digit("Strikes")),
        (29, _digit("Outs")),
        (32, lambda b: {"AtBatTens": bcd(b, 1, blank="F"), "AtBatOnes": bcd(b, 0, blank="F")}),
        (33, lambda b: {"ErrorFlag": "H" if b == 172 else "E" if b == 173 else " "}),
    ]

    def decode(self, p: bytes) -> None:
        if len(p) > 62 or _at(p, 5) != 0:
            return
        for idx, fn in self.fields:
            b = _at(p, idx)
            if b is not None:
                self.c.update(fn(b))


class Gen2Volleyball(Decoder):
    """Page 0; each field is read only if the frame's length byte covers its offset."""
    contract = "Volleyball"
    event = "Volleyball"

    def decode(self, p: bytes) -> None:
        if _at(p, 5) != 0 or len(p) < 2:
            return
        n = p[1]
        c = self.c

        def get(i):
            return p[i] if n >= i and i < len(p) else None

        if (b := get(11)) is not None:
            c.update(HomeScoreTens=_bz(dec(b, 1)), HomeScoreOnes=dec(b, 0))
        if (b := get(12)) is not None:
            c.update(GuestScoreTens=_bz(dec(b, 1)), GuestScoreOnes=dec(b, 0))
        if (b := get(13)) is not None:
            c["HomeGamesWon"] = _bz(dec(b, 0))
        if (b := get(14)) is not None:
            c["GuestGamesWon"] = _bz(dec(b, 0))
        if (b := get(17)) is not None:
            c["Game"] = _bz(dec(b, 0))
        if (b := get(15)) is not None:
            c["HomeServe"] = "*" if b & 1 else " "
        if (b := get(16)) is not None:
            c["GuestServe"] = "*" if b & 1 else " "


PROTOCOLS = {
    "Varsity_Basketball": lambda: MainProtocol(VarsityBasketball()),
    "Varsity_Baseball": lambda: MainProtocol(VarsityBaseball()),
    "Varsity_Soccer": lambda: MainProtocol(VarsitySoccer()),
    "VarsityGen2_Basketball": lambda: Gen2Protocol(Gen2Basketball()),
    "VarsityGen2_Football": lambda: Gen2Protocol(Gen2Football()),
    "VarsityGen2_Hockey": lambda: Gen2Protocol(Gen2Hockey()),
    "VarsityGen2_Soccer": lambda: Gen2Protocol(Gen2Soccer()),
    "VarsityGen2_Baseball": lambda: Gen2Protocol(Gen2Baseball()),
    "VarsityGen2_Volleyball": lambda: Gen2Protocol(Gen2Volleyball()),
}
