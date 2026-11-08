from scoreboards import funtronix as fx


def make():
    return fx.PROTOCOLS["Funtronix_Autodetect"]()


def frame(p0, **over):
    p = bytearray(16)
    p[0] = p0
    p[8] = 0x10  # clock in mm:ss mode
    for i, v in over.items():
        p[int(i[1:])] = v
    return bytes(p)


def test_basketball():
    p = make()
    f = frame(0x80 | 0x40 | 0x08 | 0x02, p1=5, p2=2, p3=1, p4=3, p5=4, p6=0, p7=2, p8=0x11, p9=2, p10=3, p11=4,
              p14=2, p15=5)
    assert p.feed(f) == 1
    c = p.snapshot()
    assert p.contract_name == "Basketball" and p.decoder.event == "Basketball"
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "2", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "4", "3")
    assert c["Period"] == "2" and c["ClockMode"] == ":"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("1234")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "5")
    assert (c["HomePossession"], c["GuestPossession"], c["HomeBonus"], c["GuestBonus"]) == ("<", " ", "B", " ")


def test_basketball_seconds_mode_guest_flags():
    p = make()
    p.feed(frame(0x80 | 0x40 | 0x04 | 0x01, p8=0, p10=5, p11=9, p12=7))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "5", "9", "7")
    assert (c["GuestPossession"], c["GuestBonus"], c["HomePossession"]) == (">", "B", " ")


def test_soccer_and_switch_resets_contract():
    p = make()
    p.feed(frame(0x80 | 0x40, p14=2))
    assert "ShotClockSecondTens" in p.snapshot()
    p.feed(frame(0x80 | 0x08 | 0x02, p1=3, p2=1, p4=0, p5=2, p7=1, p13=4, p15=6))
    c = p.snapshot()
    assert p.contract_name == "Soccer" and p.decoder.event == "Soccer"
    assert "ShotClockSecondTens" not in c
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "3", "2", "0")
    assert (c["HomePenalties"], c["GuestPenalties"], c["Period"]) == ("4", "6", "1")
    assert (c["HomePossession"], c["GuestPossession"]) == ("<", ">")


def test_volleyball():
    p = make()
    p.feed(frame(0x80 | 0x20 | 0x04, p1=1, p2=0, p4=2, p5=1, p7=3, p13=1, p15=2))
    c = p.snapshot()
    assert p.contract_name == "Volleyball"
    assert (c["HomeServe"], c["GuestServe"], c["Game"], c["HomeGamesWon"], c["GuestGamesWon"]) == (" ", "*", "3", "1", "2")
    assert (c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "1", "2")


def test_unknown_code_before_any_known_is_ignored():
    p = make()
    assert p.feed(frame(0x80 | 0x60, p1=5)) == 1
    assert p.contract_name == "Generic" and "ClockMinutesOnes" not in p.snapshot()


def test_garbage_split_and_rejects():
    p = make()
    f = frame(0x80 | 0x40, p1=7)
    assert p.feed(b"\x01\x02\x03" + f[:7]) == 0
    assert p.feed(f[7:]) == 1
    assert p.snapshot()["HomeScoreOnes"] == "7"
    bad = bytearray(f)
    bad[9] |= 0x80  # a second header byte inside the frame
    p.feed(bytes(bad) + f)
    assert p.bad >= 1 and p.packets == 2
