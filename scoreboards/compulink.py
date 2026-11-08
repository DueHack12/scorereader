"""Compulink drag-racing timing (plain text lines, RS-232).

Wire format: ASCII lines ending in CR(0D). Each line is a two-character tag followed by a value, for
example ``n1Bob Smith`` (left driver) or ``L1 1.234`` (left 60-foot time); a ``C,<category>,<round>`` line
starts a new pairing and clears every field. Non-printable bytes (such as the LF after the CR) are dropped
before the line is read. See docs/vendors/compulink.md.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find

CR = 0x0D

# tag -> (contract field, maximum length). The value is the rest of the line after the tag.
_FIELDS = {
    "c1": ("LeftCarNumber", 4), "b1": ("LeftClass", 6), "n1": ("LeftDriver", 20), "m1": ("LeftMember", 6),
    "c2": ("RightCarNumber", 4), "b2": ("RightClass", 6), "n2": ("RightDriver", 20), "m2": ("RightMember", 6),
    "L0": ("LeftReactionTime", 6), "R0": ("RightReactionTime", 6),
    "L1": ("Left60Feet", 6), "R1": ("Right60Feet", 6),
    "L2": ("Left330Feet", 6), "R2": ("Right330Feet", 6),
    "L3": ("Left660Feet", 6), "R3": ("Right660Feet", 6),
    "L4": ("Left660FeetMPH", 6), "R4": ("Right660FeetMPH", 6),
    "L5": ("Left1000Feet", 6), "R5": ("Right1000Feet", 6),
    "L6": ("LeftQuarterMile", 6), "R6": ("RightQuarterMile", 6),
    "L7": ("LeftQuarterMileMPH", 6), "R7": ("RightQuarterMileMPH", 6),
    "fl": ("LeftFirst", 6), "fr": ("RightFirst", 6), "m-": ("Mov", 6),
}
_QUAL = {"q1": "LeftQualPos", "q2": "RightQualPos"}       # first two characters of the value
_DIAL = {"S5": "LeftDialIn", "S6": "RightDialIn"}         # value after skipping two characters, max 5

_CLEARED = (
    "LeftDialIn LeftReactionTime Left60Feet Left330Feet Left660Feet Left660FeetMPH Left1000Feet LeftQuarterMile "
    "LeftQuarterMileMPH RightDialIn RightReactionTime Right60Feet Right330Feet Right660Feet Right660FeetMPH "
    "Right1000Feet RightQuarterMile RightQuarterMileMPH LeftFirst Mov RightFirst CategoryName Round "
    "LeftCarNumber LeftDriver LeftMember LeftQualPos LeftClass RightCarNumber RightDriver RightMember "
    "RightQualPos RightClass"
).split()


class CompulinkProtocol(Protocol):
    """Every CR ends a line; printable characters only are kept."""

    def extract(self):
        buf = self.buf
        while True:
            cr = find(buf, CR)
            if cr < 0:
                return
            line = bytes(b for b in buf[:cr] if 0x20 <= b <= 0x7E)
            del buf[: cr + 1]
            if len(line) >= 2:
                yield line
            elif line:
                self.reject()


class CompulinkDragRacing(Decoder):
    contract = "DragRacing"
    event = "DragRacing"

    def __init__(self, detailed: bool = False):
        self.detailed = detailed
        super().__init__()
        self.c.update(ChannelNumber="1" if detailed else "0", IsDetailed=detailed)

    def reset(self) -> None:
        super().reset()
        self.c.update(ChannelNumber="1" if self.detailed else "0", IsDetailed=self.detailed)

    def decode(self, packet: bytes) -> None:
        c = self.c
        line = packet.decode("latin-1")
        c["ChannelNumber"] = "1" if self.detailed else "0"
        tag, value = line[:2], line[2:]
        if line[0] == "C" and len(line.split(",")) == 3:
            tag = "C"
        if tag == "C":
            # ScoreConnect also sleeps two seconds here; that is deliberately not reproduced.
            c.update({name: "" for name in _CLEARED})
            c["Win"] = " "
            parts = line.split(",")
            c["CategoryName"] = parts[1][:25]
            c["Round"] = parts[2][:2]
        elif tag in _FIELDS:
            name, limit = _FIELDS[tag]
            c[name] = value[:limit]
        elif tag in _QUAL and len(value) >= 2:
            c[_QUAL[tag]] = value[:2]
        elif tag in _DIAL and len(value) >= 2:
            c[_DIAL[tag]] = value[2:][:5]
        elif tag == "w-" and value:
            c["Win"] = value[0]


PROTOCOLS = {
    "Compulink_DragRacing": lambda: CompulinkProtocol(CompulinkDragRacing(False)),
    "Compulink_DragRacingDetail": lambda: CompulinkProtocol(CompulinkDragRacing(True)),
}
