"""Colorado Timing (V1 and V2) water polo and swimming.

Framing: an ASCII packet that ends with 0x04 (EOT) and starts at the first start byte found in the buffer.
V1 starts at 0x02 (STX) and the packet must begin ``STX 'C' 'T'``; V2 starts at the first 0x01 or 0x02.
No checksum. See docs/vendors/coloradotiming.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find
from .common import ascii_char

__all__ = ["PROTOCOLS"]

_EOT = 0x04
_LANES = range(1, 9)


def _first_of(buf, values) -> int:
    hits = [i for i in (find(buf, v) for v in values) if i >= 0]
    return min(hits) if hits else -1


class _EotProtocol(Protocol):
    """Packet = first start byte .. first EOT. Subclasses say which start bytes count and what is valid."""

    start_bytes = (0x02,)

    def valid(self, pkt: bytes) -> bool:
        return True

    def extract(self):
        buf = self.buf
        while True:
            end = find(buf, _EOT)
            if end < 0:
                return
            start = _first_of(buf, self.start_bytes)
            pkt = bytes(buf[start : end + 1]) if 0 <= start < end else b""
            del buf[: end + 1]
            if pkt and self.valid(pkt):
                yield pkt
            else:
                self.reject()


class ColoradoTimingV1(_EotProtocol):
    def valid(self, pkt: bytes) -> bool:
        return pkt[1:3] == b"CT"


class ColoradoTimingV2(_EotProtocol):
    start_bytes = (0x01, 0x02)


# --------------------------------------------------------------------------- water polo
# contract field -> packet index (all plain ASCII)
_WATERPOLO = {
    "ClockMinutesTens": 11, "ClockMinutesOnes": 12, "ClockSecondTens": 14, "ClockSecondOnes": 15,
    "ClockTenthsSecond": 17, "ClockHundreths": 18, "ShotClockTens": 19, "ShotClockOnes": 20, "Period": 21,
    "TimeoutMinutesOnes": 22, "TimeoutSecondsTens": 24, "TimeoutSecondsOnes": 25,
    "GuestScoreTens": 26, "GuestScoreOnes": 27, "GuestTimeouts": 28,
    "HomeScoreTens": 61, "HomeScoreOnes": 62, "HomeTimeouts": 63,
}


class WaterpoloDecoder(Decoder):
    contract = "WaterPolo"
    event = "WaterPolo"

    def decode(self, p: bytes) -> None:
        if len(p) <= max(_WATERPOLO.values()):
            return
        self.c["ClockMode"] = ":"
        for field, i in _WATERPOLO.items():
            self.c[field] = ascii_char(p[i])


# --------------------------------------------------------------------------- swimming
def _txt(p: bytes, *idx: int) -> str:
    return "".join(ascii_char(p[i]) for i in idx)


def _lane(p: bytes) -> int:
    try:
        return int(p[3:5].decode("latin-1"))
    except ValueError:
        return 0


class SwimmingDecoder(Decoder):
    """Packets are ``<STX>`` + 2-letter type: RE reset, SR running clock, ST split, FT finish."""

    contract = "SwimmingDetail"
    event = "Swimming"

    def _lane_set(self, lane: int, **vals) -> None:
        for name, v in vals.items():
            self.c[f"{name}{lane}"] = v

    def decode(self, p: bytes) -> None:
        kind = p[1:3]
        if kind == b"RE":
            for k in ("ClockMinutesTens", "ClockMinutesOnes", "ClockSecondTens", "ClockSecondOnes",
                      "ClockTenthsSecond"):
                self.c[k] = "0"
            for lane in _LANES:
                self._lane_set(lane, Split="", Place=" ", Clock="", FinishFlag=" ")
        elif kind == b"SR" and len(p) > 9:
            self.c["ClockMode"] = ":"
            for field, i in (("ClockMinutesTens", 3), ("ClockMinutesOnes", 4), ("ClockSecondTens", 6),
                             ("ClockSecondOnes", 7), ("ClockTenthsSecond", 9)):
                self.c[field] = ascii_char(p[i])
        elif kind == b"ST" and len(p) > 16:
            lane = _lane(p)
            if 0 < lane < 9:
                self._lane_set(lane, Split=_txt(p, 7, 8), Place=ascii_char(p[6]),
                               Clock=_txt(p, 9, 10, 11, 12, 14, 15, 16))
        elif kind == b"FT" and len(p) > 14:
            lane = _lane(p)
            if 0 < lane < 9:
                self._lane_set(lane, Place=ascii_char(p[6]), Clock=_txt(p, 7, 8, 9, 10, 12, 13, 14),
                               FinishFlag=".")


PROTOCOLS = {
    "ColoradoTiming_Waterpolo": lambda: ColoradoTimingV1(WaterpoloDecoder()),
    "ColoradoTiming_Swimming": lambda: ColoradoTimingV1(SwimmingDecoder()),
    "ColoradoTimingV2_Waterpolo": lambda: ColoradoTimingV2(WaterpoloDecoder()),
    "ColoradoTimingV2_Swimming": lambda: ColoradoTimingV2(SwimmingDecoder()),
}
