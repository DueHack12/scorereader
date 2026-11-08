from scoreboards import nisasport as ns


def data(**over):
    p = bytearray(18)
    p[1] = 0x80
    p[5], p[6], p[7], p[8] = 0x01, 0x12, 0x03, 0x14
    p[2], p[3], p[4] = 0x02, 0x05, 0x0F
    p[9], p[10], p[11] = 0x00, 0x02, 0x05
    p[12], p[13] = 0x02, 0x04
    p[14], p[17] = 0x13, 0x12
    p[0] = 0x22
    for i, v in over.items():
        p[int(i[1:])] = v
    return bytes(p)


def make():
    return ns.PROTOCOLS["Nisasport_Basketball"]()


def test_main_page():
    p = make()
    assert p.feed(b"\xff" + data() + b"\xff") == 1
    c = p.snapshot()
    assert (c["InternalClockStatus"], c["Horn"]) == ("R", "H")
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "2", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "2", "5")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    assert (c["HomeFoulOnes"], c["GuestFoulOnes"]) == ("3", "2")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == (" ", " ")
    assert p.contract_name == "Basketball"


def test_seconds_mode_stopped_clock_and_three_digit_home():
    p = make()
    p.feed(b"\xff" + data(p0=0x00, p5=0x05, p6=0x19, p7=0x07, p8=0x1F, p2=0x01, p3=0x02, p4=0x03) + b"\xff")
    c = p.snapshot()
    assert c["InternalClockStatus"] == "S" and c["Horn"] == " "
    assert (c["ClockMode"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (".", "5", "9", "7")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "2", "3")


def test_period_page_and_torn_packet():
    p = make()
    p.feed(b"\xff" + data() + b"\xff")
    p.feed(b"\xff" + data(p1=0xA0, p5=0x23) + b"\xff")
    assert p.snapshot()["Period"] == "3"
    p.feed(b"\xff" + data(p1=0xA0, p5=0x13) + b"\xff")  # wrong tag: period kept
    assert p.snapshot()["Period"] == "3"
    p.feed(b"\xff" + data(p6=0x22, p2=0x09) + b"\xff")  # bad tag: main page ignored
    assert p.snapshot()["HomeScoreTens"] == "2"


def test_framing_garbage_split_and_length():
    p = make()
    f = b"\xff" + data() + b"\xff" + data(p3=0x06) + b"\xff"
    assert p.feed(b"\x01\x02" + f[:12]) == 0
    assert p.feed(f[12:]) == 2
    assert p.snapshot()["HomeScoreOnes"] == "6"
    assert p.feed(b"\xff\x01\x02\x03\xff") == 0 and p.bad >= 1


# ---------------------------------------------------------------- TV
def tv_frame(**over):
    p = bytearray(b" " * 37)
    p[0:3] = b"\x01\x13T"
    p[3:6] = b" 25"
    p[6:10] = b"1234"
    p[10:13] = b"030"
    p[13:15] = b"24"
    p[15] = ord("3")
    p[18] = ord("4")
    p[36] = 0x04
    for k, v in over.items():
        s = int(k[1:])
        b = v if isinstance(v, bytes) else bytes([v])
        p[s : s + len(b)] = b
    return bytes(p)


def test_tv_basketball():
    p = ns.PROTOCOLS["NisasportTv_Basketball"]()
    assert p.feed(tv_frame()) == 1
    c = p.snapshot()
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "2", "5")
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (":", "1", "2", "3", "4", "0")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "3", "0")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["HomeFoulOnes"], c["GuestFoulOnes"]) == ("2", "4", "3", "4")
    p.feed(tv_frame(p3=b"  7", p6=b"095 "))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "0", "9", "5")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "7")
    p.feed(tv_frame(p3=b"   "))  # blank home score: previous value kept
    assert p.snapshot()["HomeScoreOnes"] == "7"


def test_tv_garbage_split_and_rejects():
    p = ns.PROTOCOLS["NisasportTv_Basketball"]()
    f = tv_frame()
    assert p.feed(b"\x7f\x7f" + f[:20]) == 0
    assert p.feed(f[20:]) == 1  # leading junk is outside the 37 bytes before the EOT
    p2 = ns.PROTOCOLS["NisasportTv_Basketball"]()
    assert p2.feed(b"ab\x04") == 0 and p2.bad == 1        # EOT too early
    bad = bytearray(tv_frame())
    bad[1] = 0x14
    assert p2.feed(bytes(bad)) == 0 and p2.bad == 2        # wrong header
    p2.feed(b"junk")
    assert p2.feed(f[:10]) == 0 and p2.feed(f[10:]) == 1   # split frame
