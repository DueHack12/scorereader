from __future__ import annotations

from scoreboards import majordisplay

SEG = {"0": 111, "1": 6, "2": 205, "3": 143, "4": 166, "5": 171, "6": 235, "7": 14, "8": 239, "9": 175}


def packet(names: bool = False, size: int = 80) -> bytes:
    b = bytearray(b"\x00" * size)
    b[0] = 0x21

    def put(i, ch):
        b[i] = SEG[ch]

    put(7, "1"); put(6, "2")           # at bat 12
    put(8, "3"); put(9, "2")           # balls, strikes
    put(38, "1")                       # outs
    put(41, "1"); put(40, "5")         # guest runs 15
    put(46, "0"); put(45, "7")         # home runs 07
    put(10, "1"); put(22, "2"); put(26, "9")
    put(14, "3"); put(28, "4"); put(32, "5")
    if names:
        b[48:48 + 12 + 8] = b"TNCHEAD:1:1:EAGLES  "
        b[60 + 8:60 + 8 + 26] = b"TNCENDTNCHEAD:2:1:LIONS   "[:26]
    return bytes(b)


def mk():
    return majordisplay.PROTOCOLS["MajorDisplay_Baseball"]()


def test_scores_and_innings():
    p = mk()
    d = packet()
    assert p.feed(d + d[:1]) == 1  # the next '!' closes the packet
    c = p.snapshot()
    assert (c["AtBatTens"], c["AtBatOnes"], c["Balls"], c["Strikes"], c["Outs"]) == ("1", "2", "3", "2", "1")
    assert (c["GuestRunTens"], c["GuestRunOnes"], c["HomeRunTens"], c["HomeRunOnes"]) == ("1", "5", "0", "7")
    assert (c["GuestInning1"], c["GuestInning5"], c["GuestInning9"]) == ("1", "2", "9")
    assert (c["HomeInning1"], c["HomeInning5"], c["HomeInning9"]) == ("3", "4", "5")
    assert c["GuestInning2"] == " " and c["ClockMode"] == ":" and c["EventId"] == "Baseball"


def test_team_names():
    p = mk()
    d = packet(names=True)
    p.feed(d + b"!")
    c = p.snapshot()
    assert c["HomeTeamName"] == "EAGLES  " and c["GuestTeamName"] == "LIONS   "


def test_garbage_split_and_short():
    p = mk()
    d = packet()
    assert p.feed(b"junk" + d[:20]) == 0
    assert p.feed(d[20:] + b"!") == 1
    assert p.feed(b"!short!") == 0
    assert p.feed(b"x" * 3) == 0
