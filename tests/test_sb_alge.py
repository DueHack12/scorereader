from scoreboards import alge


def v1(words):
    """words = [type, w3, w4 ...] -> D1 n type ... chk."""
    body = bytes([0xD1, len(words) + 1]) + bytes(words)
    return body + bytes([sum(body) & 0xFF])


def v2(words):
    n = len(words) + 1  # index of the last word
    ws = [0xD1, n] + list(words)
    out = bytearray()
    for w in ws[:-1]:
        out += bytes([w, 0x00])
    out.append(ws[-1])
    out.append(sum(ws) & 0xFF)
    return bytes(out)


def check_main(c):
    assert c["ClockMode"] == ":" and (c["ClockMinutesTens"], c["ClockMinutesOnes"]) == (" ", "7")
    assert (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("4", "5")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    assert (c["TimeoutClockSecondTens"], c["TimeoutClockSecondOnes"]) == ("1", "1")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "2")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "8", "7")
    assert c["Period"] == "3"
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert c["HomeBonus"] == "B" and c["GuestBonus"] == "B"
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "1"
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == ("1", "2", " ", "9")


def test_v1_main_with_garbage_and_split():
    # words: [22, 7(min), 45(sec) ...] -> adjust: w3=min, w4=sec ... so list index 1 is w3
    words = [22, 7, 45, 0x00, 24, 11, 102, 87, 3, 0xE5, 12, 9]
    pkt = v1(words)
    p = alge.PROTOCOLS["AlgeTimingCKN_V1_Basketball"]()
    data = b"\x00\x11" + pkt
    assert p.feed(data[:7]) == 0
    assert p.feed(data[7:]) == 1
    c = p.snapshot()
    check_main(c)
    assert p.contract_name == "Basketball"


def test_v1_checksum_reject_and_two_packets():
    pkt = bytearray(v1([22, 7, 45, 0, 24, 11, 102, 87, 3, 0xE5, 12, 9]))
    pkt[-1] ^= 1
    p = alge.PROTOCOLS["AlgeTimingCKN_V1_Basketball"]()
    assert p.feed(bytes(pkt)) == 0 and p.bad == 1
    assert p.feed(v1([4, 0, 9, 0x50, 0xAA, 30]) + v1([13, 3, 14, 5, 2])) == 2
    c = p.snapshot()
    assert c["ClockMode"] == "." and c["ClockSecondOnes"] == "9" and c["ClockTenthsSecond"] == "5"
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == (" ", " ")
    assert c["TimeoutClockSecondTens"] == "3" and c["TimeoutClockSecondOnes"] == "0"
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "3", "1", "4")
    assert c["FoulPlayerOnes"] == "5" and c["FoulPlayerNumberOfFouls"] == "2"


def test_v1_names():
    # raw offsets 3..10 and 15..22; words[0] is packet index 2
    pkt = v1([10] + list(b"HOMETEAM") + [0] * 4 + list(b"AWAYTEAM"))
    p = alge.PROTOCOLS["AlgeTimingCKN_V1_Basketball"]()
    assert p.feed(pkt) == 1
    c = p.snapshot()
    assert c["HomeTeamName"] == "HOMETEAM" and c["GuestTeamName"] == "AWAYTEAM"


def test_v2_main_waits_for_next_start_and_rejects_bad_checksum():
    words = [22, 7, 45, 0x00, 24, 11, 102, 87, 3, 0xE5, 12, 9]
    a, b = v2(words), v2([4, 0, 9, 0x50, 0xAA, 30])
    p = alge.PROTOCOLS["AlgeTimingCKN_V2_Basketball"]()
    assert p.feed(b"\x00\x00" + a[:10]) == 0
    assert p.feed(a[10:]) == 0          # the packet is released when the next one starts
    assert p.feed(b) == 1
    check_main(p.snapshot())
    bad = bytearray(b)
    bad[-1] ^= 1
    n = p.packets
    p.feed(bytes(bad) + a)  # releases the pending good `b`, then drops the corrupted copy
    assert p.packets == n + 1 and p.bad == 1
    p.feed(b)
    assert p.packets == n + 2  # `a` is released by the next start
    check_main(p.snapshot())


def test_v2_names_short_ignored():
    p = alge.PROTOCOLS["AlgeTimingCKN_V2_Basketball"]()
    p.feed(v2([22, 1]) + v2([22, 1]))
    assert p.snapshot() == {"EventId": "Basketball"}


def lane_line(letter, ident, status, clock, n=21):
    s = letter + ident + status + " " * 7 + clock.ljust(9)
    return s.ljust(n).encode() + b"\r"


def test_alge_timing():
    p = alge.PROTOCOLS["Alge_Timing"]()
    data = b"junk\r" + lane_line("A", "001", " ", "  12.3456") + lane_line("C", "007", ".", "   1:02.5", 23)
    data += lane_line("D", "009", "C", "  59.9999")
    assert p.feed(data[:20]) == 0
    assert p.feed(data[20:]) == 3
    assert p.bad == 1
    c = p.snapshot()
    assert c["Lane1ClockStatus"] == "S" and c["Lane1Id"] == "001" and c["Lane1Clock"] == "  12.3456"
    assert c["Lane3ClockStatus"] == "R" and c["Lane3Id"] == "007" and c["Lane3Clock"] == "   1:02.5"
    assert c["Lane4ClockStatus"] == "F"
    assert p.contract_name == "Timer" and c["EventId"] == "Timing"
