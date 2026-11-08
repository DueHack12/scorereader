"""Framing used when the ScoreLinkII PIC decodes the console itself (PIC decode modes such as
DECODENEVCO, DECODEDAK4000, DECODEMP69, DECODEMP70) and forwards the result in its own frames:

    55 AA code L b4 b5 01 b7 payload… (frame is L + 9 bytes from the 55; all bytes sum to 0 mod 256)

``code`` identifies the decode mode (Nevco 0xB7, Daktronics 4000 0xBD, Fair-Play MP69 0xBA, MP70 0xBF).
Each vendor slices a different part of the frame as the packet it hands to its decoder.
"""
from __future__ import annotations

from .base import Decoder, Protocol, find_pair

CODE_NEVCO = 0xB7       # 183
CODE_DAK4000 = 0xBD     # 189
CODE_MP69 = 0xBA        # 186
CODE_MP70 = 0xBF        # 191


class Pic55AAProtocol(Protocol):
    """Generic PIC 55 AA framing. Override :meth:`payload` for the vendor's slice of the frame."""

    code = 0

    def __init__(self, decoder: Decoder, code: int | None = None):
        super().__init__(decoder)
        if code is not None:
            self.code = code

    def payload(self, frame: bytes, length: int) -> bytes:
        return frame[8 : 8 + length]

    def extract(self):
        buf = self.buf
        while True:
            j = find_pair(buf, 0x55, 0xAA)  # index of the AA
            if j < 0:
                if len(buf) > 1:
                    del buf[:-1]
                return
            s = j - 1  # index of the 55
            if s:
                del buf[:s]
            if len(buf) <= 7:
                return  # need the header
            if buf[7] != 1 or buf[2] != self.code:
                del buf[:2]  # not a frame of ours: skip this 55 AA and keep looking
                self.reject()
                continue
            length = buf[3]
            total = length + 9
            if len(buf) < total:
                return
            frame = bytes(buf[:total])
            del buf[:total]
            if sum(frame) & 0xFF:
                self.reject()
                continue
            yield self.payload(frame, length)


class Pic55AANevco(Pic55AAProtocol):
    code = CODE_NEVCO

    def payload(self, frame: bytes, length: int) -> bytes:
        return frame[6 : 6 + length + 3]


class Pic55AADak4000(Pic55AAProtocol):
    code = CODE_DAK4000

    def payload(self, frame: bytes, length: int) -> bytes:
        return frame[8 : 8 + length] + bytes(9)  # decoder expects L + 9 bytes, zero padded


class Pic55AAMp69(Pic55AAProtocol):
    code = CODE_MP69


class Pic55AAMp70(Pic55AAProtocol):
    code = CODE_MP70

    def payload(self, frame: bytes, length: int) -> bytes:
        return frame[8 : 8 + length] + bytes(9)


def make_frame(code: int, payload: bytes, b4: int = 0, b5: int = 0, b6: int = 0) -> bytes:
    """Build a PIC 55 AA frame for tests: 55 AA code L b4 b5 b6 01 payload(L) checksum."""
    body = bytes([0x55, 0xAA, code, len(payload), b4, b5, b6, 1]) + bytes(payload)
    return body + bytes([(-sum(body)) & 0xFF])
