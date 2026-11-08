from scoreboards import pannonescore as ps
from scoreboards.common import xor8


def frame(flag, code=0, **over):
    p = bytearray(70)
    p[0] = 0x82
    p[1] = flag
    p[61] = code
    for i, v in over.items():
        p[int(i[1:])] = v
    p[-1] = 0x83
    p[-2] = xor8(p, 1, len(p) - 2)
    return bytes(p)


def make():
    return ps.PROTOCOLS["PannoneScore_Autodetect"]()


def test_scores_clock_period_fouls_timeouts():
    p = make()
    assert p.contract_name == "Generic"
    f = frame(3, p2=0x12, p3=0x34, p4=0x25, p51=0x01, p52=0x23, p53=0x00, p54=0x45)
    assert p.feed(f) == 1
    c = p.snapshot()
    assert p.contract_name == "Basketball" and p.decoder.event == "Basketball"
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"],
            c["ClockSecondOnes"]) == (":", "1", "2", "3", "4")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "5")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "2", "3")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "4", "5")
    p.feed(frame(5, p60=0x02))
    assert p.snapshot()["Period"] == "2"
    p.feed(frame(1, p60=0x07))
    c = p.snapshot()
    assert (c["HomeFoulTens"], c["HomeFoulOnes"]) == ("0", "7")
    p.feed(frame(7, p60=0x1C))  # guest fouls; A-F nibbles are glyphs
    c = p.snapshot()
    assert (c["GuestFoulTens"], c["GuestFoulOnes"]) == ("1", "E")
    p.feed(frame(4, p36=0x00, p37=0x03, p38=0x02))
    p.feed(frame(4, p36=0x80, p37=0x03, p38=0x01))
    c = p.snapshot()
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("2", "1")


def test_seconds_mode_and_shot_clock_blank():
    p = make()
    p.feed(frame(1, p2=0x59, p3=0xA7, p4=0xFF))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockSecondOnes"],
            c["ClockTenthsSecond"]) == (".", "0", "5", "9", "7")
    assert c["ShotClockSecondTens"] == " "


def test_unknown_code_ignored_and_autodetect_follows_code():
    p = make()
    assert p.feed(frame(3, code=9, p2=0x12)) == 1
    assert "ClockMinutesOnes" not in p.snapshot() and p.decoder.code == -1
    p.feed(frame(3, code=0, p2=0x12))
    assert p.decoder.code == 0 and p.snapshot()["ClockMinutesOnes"] == "2"
    p.feed(frame(3, code=9, p2=0x34))  # unknown code keeps the layout; still decodes with it
    assert p.snapshot()["ClockMinutesTens"] == "3"


def test_garbage_split_checksum_and_short():
    p = make()
    f = frame(3, p2=0x12)
    assert p.feed(b"\x01\x02junk" + f[:20]) == 0
    assert p.feed(f[20:]) == 1
    bad = bytearray(f)
    bad[-2] ^= 0x01
    assert p.feed(bytes(bad)) == 0 and p.bad == 1
    assert p.feed(b"\x83") == 0 and p.bad == 2  # ETX with no STX
    short = bytearray(b"\x82\x03\x12")
    short += bytes([xor8(short, 1, len(short)), 0x83])
    assert p.feed(bytes(short)) == 1  # valid frame, too short to decode: ignored
    assert p.snapshot()["ClockMinutesOnes"] == "2"
