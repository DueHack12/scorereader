import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def make_cl_frame(addr: int, data: bytes) -> bytes:
    """Build a Daktronics current-loop frame: 55 AA addr len x x 22 data.. checksum."""
    body = bytes([addr, len(data) + 1, 0, 0, 0x22]) + bytes(data)
    return b"\x55\xaa" + body + bytes([(-(sum(body) + 0x55 + 0xAA)) & 0xFF])
