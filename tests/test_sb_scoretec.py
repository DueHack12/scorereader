from __future__ import annotations

from scoreboards import scoretec

SEG = {"0": 0x3F, "1": 0x06, "2": 0x5B, "3": 0x4F, "4": 0x66, "5": 0x6D, "6": 0x7D, "7": 0x07, "8": 0x7F, "9": 0x6F}


def payload(flags: int = 0b0100, p21: int = 0) -> bytes:
    """27 payload bytes, laid out so decoded packet[k] == payload[k-1] (the packet starts with '@')."""
    b = bytearray(27)

    def put(k, v):
        b[k - 1] = v

    for k, ch in ((25, "1"), (24, "2"), (23, "3"), (22, "4"), (20, "5"), (19, "6"), (18, "7"), (17, "8"),
                  (13, "0"), (12, "9"), (8, "1"), (7, "2"), (10, "3"), (9, "4"), (11, "5")):
        put(k, SEG[ch])
    put(14, 0x03)
    put(16, flags)
    put(21, p21)
    return bytes(b)


def mk():
    return scoretec.PROTOCOLS["ScoreTec_Basketball"]()


def stream(*payloads: bytes) -> bytes:
    return b"".join(x + b"@" for x in payloads)


def test_decode_second_frame():
    p = mk()
    assert p.feed(stream(payload(), payload(flags=0b1100, p21=0x20))) == 1
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "2", "3", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "5", "6")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "7", "8")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == ("0", "9", "1", "2")
    assert (c["FoulPlayerTens"], c["FoulPlayerOnes"], c["FoulPlayerNumberOfFouls"]) == ("3", "4", "5")
    assert c["Period"] == "3" and c["HomePossession"] == "<" and c["HomeBonus"] == "B" and c["GuestBonus"] == " "


def test_possession_guest_and_guest_hundreds():
    p = mk()
    p.feed(stream(payload(), payload(flags=0b0011, p21=0x16)))
    c = p.snapshot()
    assert c["GuestPossession"] == ">" and c["HomePossession"] == " " and c["GuestBonus"] == "B"
    assert c["GuestScoreHundreds"] == "1"


def test_split_garbage_and_misplaced_marker():
    p = mk()
    d = stream(payload(), payload())
    assert p.feed(d[:30]) == 0
    assert p.feed(d[30:]) == 1
    q = mk()
    assert q.feed(b"abc@") == 0 and q.bad == 1  # '@' not at index 27
