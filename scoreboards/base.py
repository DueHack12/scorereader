"""Framework shared by every vendor decoder in this package.

A *protocol* (one per wire format) pulls complete packets out of the raw byte stream and hands each one
to a *decoder* (one per vendor + sport layout). The decoder writes what it finds into a *contract*: a plain
dict keyed by the Sportzcast contract field names (``HomeScoreTens``, ``ClockMode``, ``InternalClockStatus``
…), with one-character strings for single characters. ``scoreboards.contracts`` turns a contract into the
ScoreReader output fields, the Sportzcast JSON and the 150-character sbdata string.

Typical vendor module::

    class FootballDecoder(Decoder):
        contract = "Football"
        event = "Football"

        def decode(self, p: bytes) -> None:
            self.c["HomeScoreTens"] = digit(p[11])

    class MyProtocol(Protocol):
        def extract(self):
            ...  # yield complete packets, deleting what was consumed from self.buf

    PROTOCOLS = {"Vendor_Football": lambda: MyProtocol(FootballDecoder())}
"""
from __future__ import annotations

import threading
import time

__all__ = ["Decoder", "Protocol", "find", "find_pair"]


class Decoder:
    """Decodes one packet into ``self.c``. Subclass once per vendor + sport layout."""

    contract = "Generic"  # Sportzcast contract class: Football, Soccer, Basketball, BaseballSoftball, …
    event = "Generic"     # Sportzcast EventType name: Football, Baseball, Softball, Hockey, Lacrosse, …

    def __init__(self):
        self.c: dict = {"EventId": self.event}

    def decode(self, packet: bytes) -> None:
        raise NotImplementedError

    def reset(self) -> None:
        self.c = {"EventId": self.event}


class Protocol:
    """Finds packets in the byte stream and feeds them to a decoder.

    Subclasses implement :meth:`extract`, which yields complete packets from ``self.buf`` and deletes the
    bytes it consumed (including garbage before a packet). A packet that makes the decoder raise is
    counted in ``bad`` and skipped, so one malformed packet never stops the stream.
    """

    max_buffer = 8192  # bytes kept while waiting for the end of a packet (garbage / wrong baud protection)

    def __init__(self, decoder: Decoder):
        self.decoder = decoder
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.packets = 0      # packets decoded
        self.bad = 0          # packets rejected (checksum, length, decoder error)
        self.version = 0      # bumps whenever the contract changes
        self.last_time = 0.0  # time of the last decoded packet
        self.last_error = ""
        self.emulated: dict = {}  # EmulatedClockStatus etc. (kept out of the decoder's own contract)
        self._emulator = None
        try:
            from .contracts import ClockStatusEmulator  # optional until contracts.py exists

            self._emulator = ClockStatusEmulator()
        except Exception:
            self._emulator = None

    # ---- what a vendor protocol overrides
    def extract(self):
        """Yield complete packets (bytes) from self.buf, deleting consumed bytes."""
        raise NotImplementedError

    # ---- public API used by ScoreReader
    @property
    def contract_name(self) -> str:
        return self.decoder.contract

    def snapshot(self) -> dict:
        """A copy of the decoded contract."""
        with self.lock:
            return dict(self.decoder.c)

    def full_contract(self) -> dict:
        """The contract plus the emulated clock statuses (EmulatedClockStatus …), as the output layer expects."""
        with self.lock:
            return {**self.decoder.c, **self.emulated}

    def feed(self, data: bytes) -> int:
        """Add raw bytes; returns the number of packets decoded."""
        n = 0
        with self.lock:
            self.buf += data
            for pkt in self.extract():
                before = (dict(self.decoder.c), dict(self.emulated))
                try:
                    self.decoder.decode(bytes(pkt))
                except Exception as e:  # never let one packet kill the stream
                    self.bad += 1
                    self.last_error = f"{type(e).__name__}: {e}"
                    continue
                if self._emulator is not None:
                    try:
                        tmp = dict(self.decoder.c)
                        self._emulator.apply(tmp)
                        self.emulated = {k: v for k, v in tmp.items() if k.startswith("Emulated")}
                    except Exception:
                        pass
                n += 1
                self.packets += 1
                self.last_time = time.time()
                if (self.decoder.c, self.emulated) != before:
                    self.version += 1
            if len(self.buf) > self.max_buffer:
                del self.buf[: len(self.buf) - self.max_buffer // 2]
        return n

    def reject(self) -> None:
        """Count a packet that failed framing/checksum (call from extract)."""
        self.bad += 1


# --------------------------------------------------------------------------- buffer search helpers
def find(buf, value: int, start: int = 0) -> int:
    """Index of the first byte == value at or after start, or -1."""
    try:
        return buf.index(value, start)
    except ValueError:
        return -1


def find_pair(buf, first: int, second: int, start: int = 0) -> int:
    """Index of the *second* byte of the first `first, second` pair at or after start, or -1."""
    i = start
    while True:
        j = find(buf, second, i)
        if j < 0:
            return -1
        if j > 0 and buf[j - 1] == first:
            return j
        i = j + 1
