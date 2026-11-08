from scoreboards import westerstrand as w
from scoreboards.common import xor8


def frame250(**put):
    b = bytearray(b" " * 90)
    b[0], b[88] = 2, 3
    for k, v in put.items():
        b[int(k[1:])] = ord(v)
    b[89] = xor8(b, 1, 89)
    return bytes(b)


def test_250_colon_clock_scores():
    p = w.PROTOCOLS["Westerstrand_Basketball"]()
    f = frame250(i5="1", i6="2", i7="B", i8="3", i9="4", i13="2", i14="4", i31="1", i32="0", i33="5",
                 i34=" ", i35="9", i36="8", i74="3")
    data = b"\x99\x99" + f
    assert p.feed(data[:40]) == 0
    assert p.feed(data[40:]) == 1
    c = p.snapshot()
    assert c["ClockMode"] == ":" and (c["ClockMinutesTens"], c["ClockMinutesOnes"]) == ("1", "2")
    assert (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("3", "4")
    assert c["InternalClockStatus"] == "R"
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == ("2", "4", " ")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "9", "8")
    assert c["Period"] == "3" and p.contract_name == "Basketball"


def test_250_tenths_two_digit_home_and_period_blank():
    p = w.PROTOCOLS["Westerstrand_Basketball"]()
    p.feed(frame250(i5="0", i6="9", i8="7", i13="5", i14=".", i15="3", i31="4", i32="2"))
    c = p.snapshot()
    assert c["ClockMode"] == "." and c["ClockSecondOnes"] == "9" and c["ClockTenthsSecond"] == "7"
    assert "InternalClockStatus" not in c
    assert c["HomeScoreHundreds"] == " " and (c["HomeScoreTens"], c["HomeScoreOnes"]) == ("4", "2")
    assert "Period" not in c


def test_250_rejects_bad_checksum_and_length():
    p = w.PROTOCOLS["Westerstrand_Basketball"]()
    bad = bytearray(frame250())
    bad[89] ^= 0x55
    assert p.feed(bytes(bad)) == 0 and p.bad == 1
    short = b"\x02" + b" " * 20 + b"\x03" + b"\x00"
    assert p.feed(short) == 0 and p.bad == 2
    assert p.feed(frame250(i74="2")) == 1


def frame200(*body: int) -> bytes:
    f = bytes([0x3F]) + bytes(body) + b"\x03"
    x = xor8(f)
    return f + bytes([0x20 if x in (2, 3) else x])


def rec200(kind, rest=""):
    return frame200(0x20, 0x20, 0x20, ord(kind), *rest.encode())


def test_200_stream():
    p = w.PROTOCOLS["Westerstrand200_basketball"]()
    stream = b"\x00\x01" + rec200("!", " 1234")
    stream += rec200("$", " 2 4")             # shot clock: tens p6, ones p8
    stream += rec200("&", "!105") + rec200("&", ")987")
    stream += rec200("%", '"8 ') + rec200("%", "x1")
    stream += rec200("#", "07") + rec200("#", "$12")
    assert p.feed(stream[:9]) == 0
    p.feed(stream[9:])
    c = p.snapshot()
    assert p.bad == 0, p.last_error
    assert c["ClockMode"] == ":" and (c["ClockMinutesTens"], c["ClockMinutesOnes"]) == ("1", "2")
    assert (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("3", "4")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("9", "8", "7")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert c["Period"] == "1"
    assert (c["HomeFoulTens"], c["HomeFoulOnes"]) == ("0", "7")
    assert (c["GuestFoulTens"], c["GuestFoulOnes"]) == ("1", "2")


def test_200_sub_minute_clock_timeout_and_checksum_escape():
    p = w.PROTOCOLS["Westerstrand200_basketball"]()
    p.feed(rec200("!", " 597 "))
    c = p.snapshot()
    assert c["ClockMode"] == "." and c["ClockSecondOnes"] == "9" and c["ClockTenthsSecond"] == "7"
    # find a body whose XOR is 2 or 3 so the checksum byte is sent as 0x20
    for ch in range(0x30, 0x7F):
        f = bytes([0x3F, 0x20, 0x20, 0x20, ord("$"), ord("$"), 0x31, 0x32, 0x20, 0x20, 0x20, ch, 0x03])
        if xor8(f) in (2, 3):
            frame = f + b"\x20"
            break
    else:  # pragma: no cover
        raise AssertionError("no escape case")
    n = p.packets
    p.feed(frame)
    assert p.packets == n + 1


def test_200_bad_checksum_and_garbage():
    p = w.PROTOCOLS["Westerstrand200_basketball"]()
    bad = bytearray(rec200("&", "!105"))
    bad[-1] ^= 0x40
    assert p.feed(b"\x55\x55" + bytes(bad)) == 0 and p.bad == 1
    assert p.feed(rec200("&", "!105")) == 1
