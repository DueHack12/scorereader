"""Anatec wired and wireless baseball/basketball: CR ... LF packets of 13 or 23 bytes."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def baseball(outs="0", inning="03"):
    return b"\r07" + b"2" + b"1" + outs.encode() + inning.encode() + b" 4" + b" 2" + b"\n"


def basket(**over):
    p = bytearray(b" " * 23)
    p[0], p[22] = 13, 10
    p[1:3] = b"24"
    p[3:7] = b"0305"
    p[7] = ord("2")
    p[8] = ord("T")
    p[9], p[10] = ord("1"), ord("3")
    p[11], p[12], p[13] = ord("7"), ord("5"), ord(" ")
    p[14], p[15] = ord("4"), ord("3")
    p[16] = 0
    p[17:20] = b"102"
    p[20:22] = b"12"
    for k, v in over.items():
        p[int(k[1:])] = v
    return bytes(p)


def test_baseball_both_wirings():
    for pid, extra in (("Anatec_Baseball", b""), ("Anatec_Wireless_Baseball", b" " * 10)):
        p = create(pid)
        pkt = baseball() if not extra else baseball()[:-1] + extra + b"\n"
        p.feed(pkt)
        c = p.snapshot()
        check(c, AtBatTens="0", AtBatOnes="7", Balls="2", Strikes="1", Outs="0", InningTens="0", InningOnes="3",
              GuestRunTens=" ", GuestRunOnes="4", HomeRunTens=" ", HomeRunOnes="2", ClockMode=":",
              TopBottomInning="T", TopOfInning=".", BottomOfInning=" ", EventId="Baseball")


def test_baseball_half_inning_detection():
    p = create("Anatec_Baseball")
    p.feed(baseball(outs="2"))
    check(p.snapshot(), TopBottomInning="T")
    p.feed(baseball(outs="1"))  # same inning, fewer outs: bottom
    check(p.snapshot(), TopBottomInning="B", TopOfInning=" ", BottomOfInning=".")
    p.feed(baseball(outs="1"))  # unchanged
    check(p.snapshot(), TopBottomInning="B")
    p.feed(baseball(outs="0", inning="04"))  # new inning: top
    check(p.snapshot(), TopBottomInning="T")


def test_basketball_wireless_and_wired_registration():
    for pid in ("Anatec_Wireless_Basketball", "Anatec_Basketball"):
        p = create(pid)
        p.feed(basket())
        c = p.snapshot()
        check(c, ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
              ClockSecondOnes="4", ClockTenthsSecond="0", HomeScoreHundreds="1", HomeScoreTens="0",
              HomeScoreOnes="2", GuestScoreHundreds=" ", GuestScoreTens="5", GuestScoreOnes="7",
              HomeTimeouts="3", GuestTimeouts="1", Period="2", HomeFoulTens="0", HomeFoulOnes="3",
              GuestFoulTens="0", GuestFoulOnes="5", ShotClockSecondTens="2", ShotClockSecondOnes="4",
              HomePossession="<", GuestPossession=" ", Horn=" ", EventId="Basketball")


def test_basketball_variants():
    p = create("Anatec_Wireless_Basketball")
    p.feed(basket(i14=32, i15=ord("7"), i16=7, i8=ord("G"), i1=ord("5"), i2=0x43))
    c = p.snapshot()
    check(c, ClockMode=".", ClockMinutesTens="0", ClockSecondTens="1", ClockSecondOnes="2", ClockTenthsSecond="7",
          Horn="H", GuestPossession=">", HomePossession=" ", ShotClockSecondTens=" ", ShotClockSecondOnes="5",
          ShotClockTenthsSecond="3")


def test_garbage_split_and_length_reject():
    data = b"zz\n" + baseball()
    p = create("Anatec_Baseball")
    p.feed(data[:6])
    p.feed(data[6:])
    assert p.packets == 1 and p.bad == 0
    p.feed(b"\r12345\n")  # wrong length
    assert p.bad == 1 and p.packets == 1
    w = create("Anatec_Wireless_Baseball")
    w.feed(baseball())  # 13 bytes is not a wireless packet
    assert w.packets == 0 and w.bad == 1
