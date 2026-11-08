from scoreboards import coloradotiming as ct


def make(pid):
    return ct.PROTOCOLS[pid]()


def waterpolo(start=0x02, head=b"CT"):
    p = bytearray(b" " * 70)
    p[0] = start
    p[1:3] = head
    p[11:13] = b"07"; p[14:16] = b"45"; p[17] = ord("3"); p[18] = ord("2")
    p[19:21] = b"24"; p[21] = ord("2"); p[22] = ord("1"); p[24:26] = b"30"
    p[26:28] = b"09"; p[28] = ord("2"); p[61:63] = b"12"; p[63] = ord("3")
    p[69] = 0x04
    return bytes(p)


def check_waterpolo(c):
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == tuple("0745")
    assert (c["ClockTenthsSecond"], c["ClockHundreths"], c["ClockMode"]) == ("3", "2", ":")
    assert (c["ShotClockTens"], c["ShotClockOnes"], c["Period"]) == ("2", "4", "2")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"], c["GuestTimeouts"]) == ("0", "9", "2")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["HomeTimeouts"]) == ("1", "2", "3")
    assert (c["TimeoutMinutesOnes"], c["TimeoutSecondsTens"], c["TimeoutSecondsOnes"]) == ("1", "3", "0")


def test_v1_waterpolo():
    p = make("ColoradoTiming_Waterpolo")
    assert p.feed(waterpolo()) == 1
    check_waterpolo(p.snapshot())
    assert p.contract_name == "WaterPolo" and p.decoder.event == "WaterPolo"


def test_v2_waterpolo_start_01_or_02():
    for start in (1, 2):
        p = make("ColoradoTimingV2_Waterpolo")
        assert p.feed(waterpolo(start, b"XY")) == 1
        check_waterpolo(p.snapshot())


def test_v1_garbage_split_and_reject():
    p = make("ColoradoTiming_Waterpolo")
    f = waterpolo()
    assert p.feed(b"\x55\xaa junk" + f[:30]) == 0
    assert p.feed(f[30:]) == 1
    # a V1 packet that does not start STX 'C' 'T' is rejected
    assert p.feed(waterpolo(head=b"XY")) == 0 and p.bad == 1
    # EOT with no start byte before it
    assert p.feed(b"abc\x04") == 0 and p.bad == 2


def test_v2_split_and_short_packet_ignored():
    p = make("ColoradoTimingV2_Waterpolo")
    f = waterpolo(1, b"zz")
    p.feed(b"noise" + f[:10])
    assert p.feed(f[10:]) == 1
    before = p.snapshot()
    p.feed(b"\x01short\x04")  # too short to hold a water polo frame: decoder ignores it
    assert p.snapshot() == before
    assert p.feed(b"no start byte\x04") == 0 and p.bad == 1


SWIM = {
    "SR": b"\x02SR01:23.4\x04",
    "ST": b"\x02ST03 212" + b"1:23" + b"." + b"456" + b"\x04",
    "FT": b"\x02FT03 2" + b"1:23" + b"." + b"456" + b"\x04",
}


def test_v2_swimming_running_split_finish_reset():
    p = make("ColoradoTimingV2_Swimming")
    assert p.contract_name == "SwimmingDetail" and p.decoder.event == "Swimming"
    p.feed(SWIM["SR"])
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"], c["ClockMode"]) == ("0", "1", "2", "3", "4", ":")
    p.feed(SWIM["ST"])
    c = p.snapshot()
    assert (c["Place3"], c["Split3"], c["Clock3"]) == ("2", "12", "1:23456")
    p.feed(SWIM["FT"])
    c = p.snapshot()
    assert (c["Place3"], c["Clock3"], c["FinishFlag3"]) == ("2", "1:23456", ".")
    p.feed(b"\x02RE\x04")
    c = p.snapshot()
    assert c["ClockSecondOnes"] == "0" and c["Clock3"] == "" and c["Place3"] == " " and c["FinishFlag3"] == " "
    # lane out of range is ignored
    p.feed(b"\x02ST09 212" + b"1:23" + b"." + b"456" + b"\x04")
    assert "Clock9" not in p.snapshot()


def test_v2_swimming_split_frame():
    p = make("ColoradoTimingV2_Swimming")
    f = SWIM["SR"]
    p.feed(b"\xff" + f[:4])
    assert p.feed(f[4:]) == 1
    assert p.snapshot()["ClockSecondOnes"] == "3"


def test_v1_swimming_accepts_only_ct_and_decodes_nothing():
    p = make("ColoradoTiming_Swimming")
    assert p.feed(SWIM["SR"]) == 0 and p.bad == 1  # not "CT": rejected
    assert p.feed(b"\x02CT01:23.4\x04") == 1  # accepted by framing; the swimming decoder has no "CT" type
    assert "ClockSecondOnes" not in p.snapshot()
