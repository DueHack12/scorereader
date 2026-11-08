from scoreboards import atlasservis as at

INV = {v: k for k, v in at._ATLAS_DIGITS.items()}
INV_STD = {v: k for k, v in at._STD_DIGITS.items()}


def packet(size, digits=(), flags=(), std=False):
    """digits: {index: char}; flags: indices that get bit 7 set. Ends in B5 so it works as a 'B5 FF' packet."""
    p = bytearray(size)
    p[0:2] = b"\xb5e"
    table = INV_STD if std else INV
    for i, ch in dict(digits).items():
        p[i] = table[ch]
    for i in flags:
        p[i] |= 0x80
    p[-1] = 0xB5
    return bytes(p)


def run(size, **kw):
    p = at.PROTOCOLS["AtlasServisCZ_Basketball"]()
    assert p.feed(packet(size, **kw) + b"\xff") == 1
    return p.snapshot()


# size -> (clock, home score, guest score, period, home foul, guest foul, shot)
LAYOUTS = {232: (8, 5, 16, 14, 15, 4, 185), 228: (7, 12, 16, 15, 11, 6, 213), 164: (7, 4, 14, 12, 11, 13, 149),
           198: (7, 12, 16, 15, 11, 6, 151), 200: (7, 12, 16, 15, 11, 6, 151)}


def test_all_atlas_layouts():
    for size, (k, h, g, per, fh, fg, s) in LAYOUTS.items():
        d = {k: "1", k + 1: "2", k + 2: "3", k + 3: "4", h + 1: "2", h + 2: "5", g + 1: "3", g + 2: "0",
             per: "3", fh: "2", fg: "1", s: "2", s + 1: "4"}
        if size == 164:  # timeout lamp bytes overlap the score digits
            d.pop(h + 1), d.pop(h + 2), d.pop(g + 1), d.pop(g + 2)
            d.update({h + 1: "2", h + 2: "5", g + 1: "3", g + 2: "0"})
        c = run(size, digits=d, flags=[k + 1])
        assert (c["ClockMode"] if "ClockMode" in c else None) is None
        assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("1234"), size
        assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == tuple("2530"), size
        assert (c["Period"], c["HomeFoulOnes"], c["GuestFoulOnes"]) == ("3", "2", "1"), size
        assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4"), size


def test_232_details():
    c = run(232, digits={8: "1", 9: "2", 10: "3", 11: "4", 185: "2", 186: "4"}, flags=[9])
    assert c["ClockTenthsSecond"] == "0" and c["GuestPossession"] == ">" and c["HomePossession"] == " "
    assert c["ShotClockTenthsSecond"] == " "
    # seconds.tenths clock, shot clock under 10 s, home possession (bit 7 of byte 8)
    c = run(232, digits={8: "5", 9: "9", 10: "7", 185: "8", 186: "3"}, flags=[8, 186])
    assert (c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == ("0", "5", "9", "7")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("0", "8", "3")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "


def test_228_blank_tens_become_zero():
    c = run(228, digits={8: "5", 9: "9", 10: "9", 214: "7"}, flags=[8])
    assert c["ClockMinutesTens"] == "0" and c["ClockMinutesOnes"] == "5"
    assert c["ShotClockSecondTens"] == "0" and c["ShotClockTenthsSecond"] == "0"


def test_164_timeouts_and_clock():
    p = at.PROTOCOLS["AtlasServisCZ_Basketball"]()
    p.feed(packet(164, digits={2: "3", 3: "5"}, flags=[5]) + b"\xff")
    c = p.snapshot()
    assert (c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("3", "5")
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "0"
    # one lamp fewer than shown is treated as flicker and the shown value is kept
    p.feed(packet(164, flags=[4]) + b"\xff")
    assert p.snapshot()["HomeTimeouts"] == "2"
    p.feed(packet(164, flags=[4, 5, 6]) + b"\xff")
    assert p.snapshot()["HomeTimeouts"] == "3"


def test_198_guest_timeouts_use_home_value():
    p = at.PROTOCOLS["AtlasServisCZ_Basketball"]()
    p.feed(packet(198, digits={4: "2", 5: "0"}, flags=[12, 13, 14, 16]) + b"\xff")
    c = p.snapshot()
    assert c["HomeTimeouts"] == "3" and c["GuestTimeouts"] == "1"
    assert (c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("2", "0")


def test_159_std_digits():
    d = {3: "2", 4: "5", 5: "3", 6: "3", 7: "0", 9: "1", 10: "2", 11: "3", 12: "4", 144: " ", 145: "7"}
    c = run(159, digits=d, std=True, flags=[10])
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == tuple("2530")
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("1234")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["Period"]) == ("0", "7", "3")


def test_cr_delimited_followers_garbage_split_and_rejects():
    p = at.PROTOCOLS["AtlasServisCZ_Basketball"]()
    a, b = packet(228, digits={13: "1"}), packet(228, digits={13: "2"})
    stream = a + b"\xff" + b[:-1] + b"\x10" + b"\r"  # second packet ends at CR (its own last byte is free)
    assert p.feed(stream[:100]) == 0
    assert p.feed(stream[100:]) == 2
    assert p.snapshot()["HomeScoreTens"] == "2"
    # garbage in front makes the first packet fail the B5 65 header
    assert p.feed(b"junk" + a + b"\xff") == 0 and p.bad == 1
    # unknown size is rejected, as is a header-less CR packet
    assert p.feed(packet(100) + b"\xff") == 0 and p.bad == 2
    assert p.feed(b"\xb5\xff") == 0  # empty packet: rejected
    assert p.bad == 3
