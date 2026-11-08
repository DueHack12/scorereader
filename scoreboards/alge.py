"""ALGE-Timing: CKN basketball scoreboards (versions 1 and 2) and the ASCII "Timing" lane feed.

**CKN V1** (RS-232/RS-485 9600, or ZigBee at 115200)::

    D1 n type w3 w4 … wn chk        packet = n + 2 bytes, chk = sum of all preceding bytes mod 256

**CKN V2** is the same packet with every word followed by one extra byte, only the even-indexed bytes carry data::

    D1 x n x type x w3 x … wn chk   packet = 2n + 2 bytes, chk = sum of the even-indexed bytes mod 256

A V2 start byte is a 0xD1 that is not followed by 0xD1 or 0x2E. V2 frames are delimited by the *next* start byte,
so the newest frame is decoded when the one after it starts to arrive. The decoders read word ``k`` at
``packet[mode * k]`` (mode 1 or 2) and switch on the type word: 4 = clocks, 10 = team names, 13 = fouls,
22 = clocks + score + period + flags + team fouls.

**Alge_Timing**: ASCII lane lines ending in CR, exactly 21 or 23 characters: ``A``-``H`` (lane 1-8), id at 1-3,
status character at 4 (space = stopped, ``.`` = running, ``C`` = finished), clock text at 12-20.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char, bcd_zero_blank, dec

__all__ = ["ProtocolV1", "ProtocolV2", "TimingProtocol", "PROTOCOLS"]

START = 0xD1


# --------------------------------------------------------------------------- CKN framing
class ProtocolV1(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            n = find(buf, START)
            if n < 0:
                buf.clear()
                return
            if n:
                del buf[:n]
            if len(buf) <= 3:
                return
            if buf[1] == START:  # doubled start byte: the second one starts the packet
                del buf[0]
            size = buf[1] + 2
            if len(buf) < size:
                return
            pkt = bytes(buf[:size])
            del buf[:size]  # a bad packet is dropped whole, like a good one
            if sum(pkt[:-1]) & 0xFF == pkt[-1]:
                yield pkt
            else:
                self.reject()


def _v2_start(buf, index: int) -> int:
    """Index of the next real V2 start byte at or after ``index``, or -1."""
    while True:
        n = find(buf, START, index)
        if n < 0 or len(buf) <= n + 1:
            return -1
        if buf[n + 1] in (START, 0x2E):
            index = n + 2
            continue
        return n


class ProtocolV2(Protocol):
    def extract(self):
        buf = self.buf
        while True:
            s = _v2_start(buf, 0)
            if s < 0:
                return
            nxt = _v2_start(buf, s + 1)
            if nxt < 0:
                if s:
                    del buf[:s]
                return
            size = buf[s + 2] * 2 + 2
            if s + size > len(buf):
                if s:
                    del buf[:s]
                return
            pkt = bytes(buf[s : s + size])
            del buf[:nxt]
            if sum(pkt[0:size - 1:2]) & 0xFF == pkt[-1]:
                yield pkt
            else:
                self.reject()


# --------------------------------------------------------------------------- CKN basketball
class CknBasketball(Decoder):
    contract = "Basketball"
    event = "Basketball"

    def __init__(self, mode: int):
        super().__init__()
        self.mode = mode  # 1 = V1, 2 = V2

    def decode(self, p: bytes) -> None:
        m = self.mode
        if len(p) <= 2 * m:
            return
        kind = p[2 * m]
        if kind == 4 and len(p) > 7 * m:
            self._clocks(p)
        elif kind == 10 and len(p) >= 23:
            # raw byte offsets, independent of mode (so garbled on V2, as in ScoreConnect)
            self.c["HomeTeamName"] = "".join(map(chr, p[3:11]))
            self.c["GuestTeamName"] = "".join(map(chr, p[15:23]))
        elif kind == 13 and len(p) > 6 * m:
            self._fouls(p)
        elif kind == 22 and len(p) > 13 * m:
            self._main(p)

    def _w(self, p: bytes, k: int) -> int:
        return p[self.mode * k]

    def _timeout_clock(self, p: bytes) -> None:
        v = self._w(p, 7) & 0x7F
        self.c["TimeoutClockSecondTens"] = dec(v, 1, 2, True)
        self.c["TimeoutClockSecondOnes"] = dec(v, 0, 2, True)

    def _clocks(self, p: bytes) -> None:
        w = self._w
        c = self.c
        if w(p, 3) > 0:
            c.update(ClockMode=":", ClockMinutesTens=dec(w(p, 3), 1, 2, True), ClockMinutesOnes=dec(w(p, 3), 0, 2),
                     ClockSecondTens=dec(w(p, 4), 1, 2), ClockSecondOnes=dec(w(p, 4), 0, 2), ClockTenthsSecond="0")
        else:  # under a minute: seconds and tenths (high nibble of word 5)
            c.update(ClockMode=".", ClockMinutesTens="0", ClockMinutesOnes="0",
                     ClockSecondTens=dec(w(p, 4), 1, 2, True), ClockSecondOnes=dec(w(p, 4), 0, 2),
                     ClockTenthsSecond=bcd_zero_blank(w(p, 5), 1))
        if w(p, 6) == 0xAA:
            c.update(ShotClockSecondTens=" ", ShotClockSecondOnes=" ")
        else:
            c.update(ShotClockSecondTens=dec(w(p, 6), 1, 2, True), ShotClockSecondOnes=dec(w(p, 6), 0, 2))
        self._timeout_clock(p)

    def _fouls(self, p: bytes) -> None:
        w = self._w
        self.c.update(HomeFoulTens=dec(w(p, 3), 1, 2, True), HomeFoulOnes=dec(w(p, 3), 0, 2),
                      GuestFoulTens=dec(w(p, 4), 1, 2, True), GuestFoulOnes=dec(w(p, 4), 0, 2),
                      FoulPlayerTens=dec(w(p, 5), 1, 2, True), FoulPlayerOnes=dec(w(p, 5), 0, 2),
                      FoulPlayerNumberOfFouls=dec(w(p, 6), 0, 2))

    def _main(self, p: bytes) -> None:
        w = self._w
        self._clocks(p)
        flags = w(p, 11)
        self.c.update(
            HomeScoreHundreds=dec(w(p, 8), 2, 3, True), HomeScoreTens=dec(w(p, 8), 1, 3), HomeScoreOnes=dec(w(p, 8), 0, 3),
            GuestScoreHundreds=dec(w(p, 9), 2, 3, True), GuestScoreTens=dec(w(p, 9), 1, 3), GuestScoreOnes=dec(w(p, 9), 0, 3),
            Period=dec(w(p, 10), 0, 2, True),
            HomePossession="<" if flags & 0x80 else " ", GuestPossession=">" if flags & 0x08 else " ",
            HomeTimeouts=str((flags & 0x30) >> 4), GuestTimeouts=str(flags & 0x03),
            HomeBonus="B" if flags & 0x40 else " ", GuestBonus="B" if flags & 0x04 else " ",
            HomeFoulTens=dec(w(p, 12), 1, 2, True), HomeFoulOnes=dec(w(p, 12), 0, 2),
            GuestFoulTens=dec(w(p, 13), 1, 2, True), GuestFoulOnes=dec(w(p, 13), 0, 2))


# --------------------------------------------------------------------------- ASCII lane timing
class TimingProtocol(Protocol):
    """CR-terminated lines; only lines of exactly 21 or 23 characters are packets."""

    def extract(self):
        buf = self.buf
        while True:
            cr = find(buf, 13)
            if cr < 0:
                return
            line = bytes(buf[:cr])
            del buf[: cr + 1]
            if len(line) in (21, 23):
                yield line
            else:
                self.reject()


class AlgeTiming(Decoder):
    contract = "Timer"
    event = "Timing"
    _STATUS = {32: "S", 46: "R", 67: "F"}

    def decode(self, p: bytes) -> None:
        lane = p[0] - 64 if len(p) >= 21 else 0  # 'A' (65) .. 'H' (72) -> lane 1..8
        if 1 <= lane <= 8:
            k = f"Lane{lane}"
            self.c[k + "ClockStatus"] = self._STATUS.get(p[4], "S")
            self.c[k + "Id"] = "".join(ascii_char(b) for b in p[1:4])
            self.c[k + "Clock"] = "".join(ascii_char(b) for b in p[12:21])


PROTOCOLS = {
    "AlgeTimingCKN_V1_Basketball": lambda: ProtocolV1(CknBasketball(1)),
    "AlgeTimingCKN_V2_Basketball": lambda: ProtocolV2(CknBasketball(2)),
    "Alge_Timing": lambda: TimingProtocol(AlgeTiming()),
}
