"""iCast basketball: a text stream of ';'-separated fields.

A packet is the buffer up to 4 bytes past the first 'T' (when "Game Time" is in the buffer) or the first
'H' (when "Intermission Half" is), and must split into exactly 14 fields. NUL bytes are dropped first.
See docs/vendors/icast.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find

__all__ = ["PROTOCOLS"]

_FIELDS = 14


def _ascii(data) -> str:
    """One character per byte (bytes above 0x7F become '?')."""
    return "".join(chr(b) if b < 128 else "?" for b in data)


class ICastProtocol(Protocol):
    def extract(self):
        buf = self.buf
        if 0 in buf:
            buf[:] = bytes(b for b in buf if b)
        while True:
            text = _ascii(buf)
            if "Game Time" in text:
                end = find(buf, ord("T"))
            elif "Intermission Half" in text:
                end = find(buf, ord("H"))
            else:
                return
            pkt = bytes(buf[: end + 4])
            del buf[: end + 4]
            if len(_ascii(pkt).split(";")) == _FIELDS:
                yield pkt
            else:
                self.reject()


def _pair(text: str, sep: str):
    a, b = text.split(sep)[:2]
    return a, b


def _score(text: str):
    """Right-justified 1-3 characters -> (hundreds, tens, ones), or None for other lengths."""
    return {1: (" ", " ", text), 2: (" ", text[:1], text[1:]), 3: tuple(text)}.get(len(text))


def _mmss(m: str):
    return (m[0] if len(m) == 2 else " "), (m[1] if len(m) == 2 else m[0])


class BasketballDecoder(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def __init__(self):
        super().__init__()
        self._timeout_running = False

    def decode(self, p: bytes) -> None:
        for n, text in enumerate(_ascii(p).split(";")):
            handler = self._HANDLERS.get(n)
            if handler is None:
                continue
            try:
                handler(self, text)
            except IndexError:  # malformed field: skip it, keep the rest
                pass

    def _clock(self, text: str) -> None:
        c = self.c
        if ":" in text:
            m, s = _pair(text, ":")
            mt, mo = _mmss(m)
            c.update(ClockMode=":", ClockMinutesTens=mt, ClockMinutesOnes=mo, ClockSecondTens=s[0],
                     ClockSecondOnes=s[1], ClockTenthsSecond=" ")
        elif "." in text:
            s, t = _pair(text, ".")
            st, so = _mmss(s)
            c.update(ClockMode=".", ClockMinutesTens=" ", ClockMinutesOnes=" ", ClockSecondTens=st,
                     ClockSecondOnes=so, ClockTenthsSecond=t[0])

    def _home(self, text: str) -> None:
        v = _score(text)
        if v:
            self.c.update(zip(("HomeScoreHundreds", "HomeScoreTens", "HomeScoreOnes"), v))

    def _guest(self, text: str) -> None:
        v = _score(text)
        if v:
            self.c.update(zip(("GuestScoreHundreds", "GuestScoreTens", "GuestScoreOnes"), v))

    def _single(self, key: str, text: str) -> None:
        if len(text) == 1:
            self.c[key] = text

    def _period(self, text: str) -> None:
        self._single("Period", text)

    def _home_to(self, text: str) -> None:
        self._single("HomeTimeouts", text)

    def _guest_to(self, text: str) -> None:
        self._single("GuestTimeouts", text)

    def _fouls(self, side: str, text: str) -> None:
        if len(text) == 1:
            self.c.update({side + "FoulTens": " ", side + "FoulOnes": text})
        elif len(text) == 2:
            self.c.update({side + "FoulTens": text[0], side + "FoulOnes": text[1]})

    def _home_fouls(self, text: str) -> None:
        self._fouls("Home", text)

    def _guest_fouls(self, text: str) -> None:
        self._fouls("Guest", text)

    def _possession(self, text: str) -> None:
        arrows = {"0": (" ", " "), "1": ("<", " "), "2": (" ", ">")}.get(text)
        if arrows:
            self.c.update(HomePossession=arrows[0], GuestPossession=arrows[1])

    def _shot(self, text: str) -> None:
        c = self.c
        if "." in text:
            s, t = _pair(text, ".")
            st, so = _mmss(s)
            c.update(ShotClockSecondTens=st, ShotClockSecondOnes=so, ShotClockTenthsSecond=t[0])
        elif len(text) == 2:
            c.update(ShotClockSecondTens=text[0], ShotClockSecondOnes=text[1], ShotClockTenthsSecond=" ")
        elif len(text) == 1:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=text, ShotClockTenthsSecond=" ")

    def _timeout_flag(self, text: str) -> None:
        self._timeout_running = text != "0"
        if not self._timeout_running:
            self.c.update(TimeoutClockMinutesOnes=" ", TimeoutClockSecondTens=" ", TimeoutClockSecondOnes=" ")

    def _timeout_clock(self, text: str) -> None:
        if not self._timeout_running:
            return
        c = self.c
        if ":" in text:
            m, s = _pair(text, ":")
            c.update(TimeoutClockMinutesOnes=m[0], TimeoutClockSecondTens=s[0], TimeoutClockSecondOnes=s[1])
            return
        c["TimeoutClockMinutesOnes"] = " "
        if len(text) == 2:
            c.update(TimeoutClockSecondTens=text[0], TimeoutClockSecondOnes=text[1])
        elif len(text) == 1:
            c.update(TimeoutClockSecondTens=" ", TimeoutClockSecondOnes=text)

    _HANDLERS = {0: _clock, 1: _home, 2: _guest, 3: _period, 4: _home_to, 5: _guest_to, 6: _home_fouls,
                 7: _guest_fouls, 8: _possession, 9: _shot, 10: _timeout_flag, 11: _timeout_clock}


PROTOCOLS = {"ICast_Basketball": lambda: ICastProtocol(BasketballDecoder())}
