
from scoreboards import eversan


def body(n, fields=None, p0=0):
    b = bytearray(b"0" * n)
    b[0] = p0
    for i, v in (fields or {}).items():
        b[i] = v if isinstance(v, int) else ord(v)
    return b


def put(b, i, s):
    b[i:i + len(s)] = s.encode()


def legacy(p0, n, fields=None, flags=None):
    b = body(n, fields, p0)
    b[1] = n
    for i, v in (flags or {}).items():
        b[i] = v
    if n > 15:
        b[2] = sum(b[6:n]) & 0xFF
    else:
        # ScoreConnect compares XOR(bytes 2..n-1) with byte 2, i.e. bytes 3..n-1 must XOR to zero
        b[3] = 0
        x = 0
        for v in b[4:n]:
            x ^= v
        b[3] = x
    return b


def v2(code, n, sum_at, fields=None, p0=None):
    b = body(n, fields, code if p0 is None else p0)
    b[1] = n
    b[sum_at] = 0
    x = 0
    for v in b[4:]:
        x ^= v
    b[sum_at] = x
    return b


def run(pid, *chunks):
    p = eversan.PROTOCOLS[pid]()
    for c in chunks:
        p.feed(bytes(c))
    return p


def test_registered_ids():
    assert len(eversan.PROTOCOLS) == 17
    for f in eversan.PROTOCOLS.values():
        f()


def clock(b, i, s):
    put(b, i, s)


# ---------------------------------------------------------------- legacy
def basketball25():
    b = legacy(1, 30)
    put(b, 6, "1234")
    put(b, 11, "123")      # home score
    put(b, 14, "045")
    put(b, 17, "0507")
    b[5] = 0x40 | 0x20 | 12  # both bonus, period 2, home possession (bit 4 clear)
    b[2] = sum(b[6:30]) & 0xFF
    return b


def test_basketball_code25():
    c = run("Eversan_Basketball_Code25", basketball25()).snapshot()
    assert c["ClockMode"] == ":" and c["ClockMinutesTens"] == "1" and c["ClockSecondOnes"] == "4"
    assert c["HomeScoreHundreds"] == "1" and c["HomeScoreOnes"] == "3" and c["GuestScoreHundreds"] == "0"
    assert c["Period"] == "2" and c["HomePossession"] == "<" and c["HomeBonus"] == "B" and c["GuestBonus"] == "B"
    assert c["HomeFoulOnes"] == "5"


def test_basketball_code25_shot_clock_packet():
    b = legacy(2, 14)
    put(b, 11, "24")
    b[3] = 0
    x = 0
    for v in b[4:14]:
        x ^= v
    b[3] = x
    c = run("Eversan_Basketball_Code25", basketball25(), b).snapshot()
    assert c["ShotClockSecondTens"] == "2" and c["ShotClockSecondOnes"] == "4" and c["HomeScoreOnes"] == "3"


def test_tenths_mode_and_colon_blank():
    b = legacy(1, 30)
    put(b, 6, "0042:")
    b[10] = ord("7")
    b[5] = 0
    b[2] = sum(b[6:30]) & 0xFF
    c = run("Eversan_Basketball_Code25", b).snapshot()
    assert c["ClockMode"] == "." and c["ClockSecondTens"] == "4" and c["ClockSecondOnes"] == "2"
    assert c["ClockTenthsSecond"] == "7"
    b[9] = ord(":")  # a colon lamp reads as blank
    b[2] = sum(b[6:30]) & 0xFF
    assert run("Eversan_Basketball_Code25", b).snapshot()["ClockSecondOnes"] == " "


def test_basketball_code29():
    b = legacy(1, 34, {14: "3"}, {5: 0x10 | 0x40 | 0x08})
    put(b, 6, "0830")
    put(b, 11, "105")
    put(b, 15, "099")
    put(b, 20, "2")
    put(b, 27, "14")
    b[2] = sum(b[6:34]) & 0xFF
    c = run("Eversan_Basketball_Code29", b).snapshot()
    assert c["HomeScoreHundreds"] == "1" and c["GuestScoreOnes"] == "9" and c["Period"] == "3"
    assert c["HomePossession"] == "<" and c["HomeBonus"] == "B" and c["HomeDoubleBonus"] == "B"
    assert c["GuestBonus"] == " " and c["HomeTimeouts"] == "2" and c["ShotClockSecondTens"] == "1"


def test_football_legacy():
    b = legacy(1, 30, {}, {4: 0x40})
    put(b, 6, "1200")
    put(b, 12, "1407")
    put(b, 16, "1025")
    put(b, 20, "3")
    put(b, 21, "2")
    b[2] = sum(b[6:30]) & 0xFF
    c = run("Eversan_Football", b).snapshot()
    assert c["HomeScoreTens"] == "1" and c["GuestScoreOnes"] == "7" and c["ToGoTens"] == "1"
    assert c["BallOnOnes"] == "5" and c["Down"] == "3" and c["Quarter"] == "2"
    assert c["GuestPossession"] == ">" and c["HomePossession"] == " "


def test_lacrosse_soccer_legacy():
    b = legacy(1, 20)
    put(b, 5, "2315")
    put(b, 10, "03144")
    b[2] = sum(b[6:20]) & 0xFF
    c = run("Eversan_Soccer_Code15", b).snapshot()
    assert c["ClockMinutesTens"] == "2" and c["HomeScoreOnes"] == "3" and c["GuestScoreTens"] == "1"
    assert c["Period"] == "4"
    p = run("Eversan_Lacrosse_Code15", b)
    assert p.decoder.contract == "HockeyLacrosse" and p.decoder.event == "Lacrosse"
    assert p.snapshot()["GuestScoreTens"] == "1"


def test_legacy_short_packet_uses_xor_checksum():
    b = legacy(1, 12)
    p = run("Eversan_Soccer_Code15", b)
    assert p.packets == 1 and p.bad == 0
    b[6] ^= 1
    p.feed(bytes(b))
    assert p.bad == 1


# ---------------------------------------------------------------- V2
def test_v2_football_both_checksum_positions():
    b = v2(129, 30, 3, {12: "2", 13: "4", 20: "1"})
    p = run("EversanV2_Football", b)
    assert p.snapshot()["HomeScoreOnes"] == "4" and p.snapshot()["Down"] == "1"
    b2 = v2(129, 30, 2, {12: "3", 13: "5"})
    b2[3] = 0x30
    # recompute with the checksum only at byte 2
    x = 0
    for v in b2[4:]:
        x ^= v
    b2[2] = x
    p.feed(bytes(b2))
    assert p.snapshot()["HomeScoreOnes"] == "5" and p.bad == 0


def test_v2_football111_swaps_togo_ballon():
    b = v2(129, 30, 3, {16: "3", 17: "5", 18: "1", 19: "0"})
    c = run("EversanV2_Football_Code111", b).snapshot()
    assert c["BallOnTens"] == "3" and c["BallOnOnes"] == "5" and c["ToGoTens"] == "1"


def test_v2_basketball():
    b = v2(129, 32, 3, {25: "2", 26: "4", 19: "0"})
    b[5] = 0x40 | 0x10 | 14
    b[3] = 0
    x = 0
    for v in b[4:]:
        x ^= v
    b[3] = x
    c = run("EversanV2_Basketball", b).snapshot()
    assert c["ShotClockSecondTens"] == "2" and c["Period"] == "3" and c["GuestPossession"] == ">"
    assert c["HomeBonus"] == "B"


def test_v2_lacrosse_soccer_135():
    b = v2(135, 20, 2, {10: "2", 11: "0", 12: "4", 16: "1", 17: "3"})
    c = run("EversanV2_Soccer_Code135", b).snapshot()
    assert c["Period"] == "2" and c["GuestScoreOnes"] == "4" and c["HomeScoreOnes"] == "3"
    assert run("EversanV2_Lacrosse_Code135", b).decoder.event == "Lacrosse"


def baseball_packet(code, guest, home):
    b = body(44, {}, code)
    for n, v in enumerate(guest):
        b[22 + n] = ord(v)
    for n, v in enumerate(home):
        b[32 + n] = ord(v)
    for n in range(len(guest), 10):
        b[22 + n] = 32
    for n in range(len(home), 10):
        b[32 + n] = 32
    b[7], b[8], b[9] = ord("2"), ord("1"), ord("0")
    b[12], b[13] = ord("0"), ord("3")
    b[1] = 44
    sum_at = 3 if code == 70 else 2
    b[sum_at] = 0
    x = 0
    for v in b[4:]:
        x ^= v
    b[sum_at] = x
    return b


def test_v2_baseball_135_and_70():
    c = run("EversanV2_Baseball_Code135", baseball_packet(135, "013", "02")).snapshot()
    assert c["Balls"] == "2" and c["GuestRunOnes"] == "3" and c["GuestInning3"] == "3"
    assert (c["InningTens"], c["InningOnes"], c["TopBottomInning"]) == ("0", "3", "B")
    assert c["BottomOfInning"] == "." and c["TopOfInning"] == " "
    c = run("EversanV2_Baseball_Code70", baseball_packet(70, "0130", "0201")).snapshot()
    assert (c["InningTens"], c["InningOnes"], c["TopBottomInning"]) == ("0", "5", "T")
    assert c["TopOfInning"] == "."


def test_v2_hockey_131():
    b = v2(131, 52, 2, {13: "0", 14: "3", 17: "0", 18: "1", 15: "2", 26: "1", 27: "4", 29: "1", 30: "4",
                        31: "5", 28: "9"})
    put(b, 6, "1503")
    b[2] = 0
    x = 0
    for v in b[4:]:
        x ^= v
    b[2] = x
    c = run("EversanV2_Hockey_Code131", b).snapshot()
    assert c["HomeScoreOnes"] == "3" and c["GuestScoreOnes"] == "1" and c["Period"] == "2"
    assert c["HomePenaltyPlayer1Tens"] == "1" and c["HomePenaltyPlayer1ClockMinutesOnes"] == "1"
    assert c["HomePenaltyPlayer1ClockMinutesTens"] == " " and c["HomePenaltyPlayer1ClockSecondOnes"] == "5"


# ---------------------------------------------------------------- Model 9xxx
def test_9364_football_and_lacrosse():
    b = body(24, {}, 129)
    put(b, 6, "0945")
    put(b, 12, "1407")
    put(b, 16, "1020")
    put(b, 20, "3")
    put(b, 22, "21")
    put(b, 16, "10")
    put(b, 17, "5")
    nxt = bytes([129])
    p = run("EversanModel9364_Football", b, nxt)
    c = p.snapshot()
    assert c["ClockMinutesOnes"] == "9" and c["HomeScoreTens"] == "1" and c["ToGoOnes"] == "5"
    assert c["Down"] == "3" and c["HomeTimeouts"] == "2"
    b = body(24, {}, 129)
    put(b, 12, "0502")
    put(b, 16, "7")
    put(b, 20, "8")
    put(b, 21, "9")
    put(b, 22, "3")
    p = run("EversanModel9364_Lacrosse", b, nxt)
    c = p.snapshot()
    assert c["HomeScoreOnes"] == "5" and c["HomePlayerPopUp"] == "87" and c["HomeShotOnGoalOnes"] == "9"
    assert c["HomeTimeOut"] == "3"


def hockey9xxx(n=50):
    return body(n, {}, 131)


def test_9694_hockey_minutes_tens_from_stream():
    b = hockey9xxx()
    put(b, 6, "1200")
    put(b, 13, "02")
    put(b, 26, "12")
    put(b, 28, "1")
    p = run("EversanModel9694_Hockey", b, bytes([131]))
    c = p.snapshot()
    assert c["HomeScoreOnes"] == "2" and c["HomePenaltyPlayer1ClockMinutesTens"] == "1"
    assert c["HomePenaltyPlayer1Ones"] == "2"


def test_9775_hockey():
    b = hockey9xxx(46)
    put(b, 7, "0059")
    put(b, 11, "9")
    put(b, 12, "0305")
    put(b, 17, "6")
    put(b, 20, "07")
    put(b, 23, "2")
    p = run("EversanModel9775_Hockey", b, bytes([131]))
    c = p.snapshot()
    assert c["ClockMode"] == "." and c["ClockSecondTens"] == "5" and c["ClockTenthsSecond"] == "9"
    assert c["HomeScoreOnes"] == "3" and c["GuestScoreOnes"] == "5" and c["HomeShotOnGoalOnes"] == "6"
    assert c["HomePenaltyPlayer1Ones"] == "7" and c["HomePenaltyPlayer1ClockMinutesTens"] == " "
    assert c["HomePenaltyPlayer1ClockMinutesOnes"] == "2"


def test_9xxx_waits_for_next_start_byte():
    b = hockey9xxx(46)
    p = run("EversanModel9775_Hockey", b)
    assert p.packets == 0
    p.feed(bytes([131]))
    assert p.packets == 1


# ---------------------------------------------------------------- framing
def test_garbage_and_split_v2():
    b = v2(129, 30, 3, {13: "9"})
    p = eversan.PROTOCOLS["EversanV2_Football"]()
    p.feed(b"\x05\x06\x07" + bytes(b[:10]))
    assert p.packets == 0
    p.feed(bytes(b[10:]))
    assert p.packets == 1 and p.snapshot()["HomeScoreOnes"] == "9"


def test_v2_checksum_and_length_rejection():
    b = v2(129, 30, 3, {13: "9"})
    b[10] ^= 0x01
    p = run("EversanV2_Football", b)
    assert p.packets == 0 and p.bad == 1
    p.feed(bytes([129, 2, 0, 0, 0]))  # impossible length
    assert p.bad == 2


def test_legacy_garbage_split_and_checksum():
    b = basketball25()
    p = eversan.PROTOCOLS["Eversan_Basketball_Code25"]()
    p.feed(b"\x7f\x7e" + bytes(b[:12]))
    assert p.packets == 0
    p.feed(bytes(b[12:]))
    assert p.packets == 1
    bad = bytearray(b)
    bad[8] ^= 0x04
    p.feed(bytes(bad))
    assert p.packets == 1 and p.bad == 1


def test_9xxx_garbage_before_frame():
    b = hockey9xxx(46)
    put(b, 12, "02")
    p = run("EversanModel9775_Hockey", b"junk" + bytes(b), bytes([131]))
    assert p.packets == 1 and p.snapshot()["HomeScoreOnes"] == "2"


def test_short_packet_ignored_not_raised():
    p = run("EversanModel9775_Hockey", bytes([131, 49, 50]), bytes([131]))
    assert p.bad == 0 and "HomeScoreOnes" not in p.snapshot()
