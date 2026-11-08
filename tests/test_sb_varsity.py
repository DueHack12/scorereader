from __future__ import annotations

import pytest

from scoreboards import varsity


# --------------------------------------------------------------------------- frame builders
def main_frame(typ: int, data: bytes) -> bytes:
    body = bytes([len(data) + 3, typ]) + bytes(data)
    return body + bytes([(0xAA - sum(body)) & 0xFF])


def gen2_frame(page: int, fields: dict | None = None, size: int = 40, sub: int | None = None,
               raw: dict | None = None) -> bytes:
    """F6 len b2 b3 b4 page ... chk; ``fields`` maps byte offset -> value; total length ``size``."""
    b = bytearray(size)
    b[0] = 0xF6
    b[1] = size - 1
    b[5] = page
    if sub is not None:
        b[6] = sub
    for k, v in (fields or {}).items():
        b[k] = v
    b[-1] = 0
    b[-1] = (0xA0 - sum(b)) & 0xFF
    return bytes(b)


def clock_gen2(sub: int, ms: int) -> bytes:
    if sub in (0, 1):
        f = {7 + i: (ms >> (8 * i)) & 0xFF for i in range(4)}
    else:
        f = {8 + i: (ms >> (8 * i)) & 0xFF for i in range(4)}
    return gen2_frame(1, f, size=16, sub=sub)


def clock_main(typ: int, cs: int) -> bytes:
    return main_frame(typ, bytes([0]) + cs.to_bytes(4, "big"))


class FakeTime:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def feed(p, data):
    p.feed(data)
    return p.snapshot()


# --------------------------------------------------------------------------- registry
def test_ids_registered():
    assert set(varsity.PROTOCOLS) == {
        "Varsity_Basketball", "Varsity_Baseball", "Varsity_Soccer", "VarsityGen2_Baseball",
        "VarsityGen2_Basketball", "VarsityGen2_Football", "VarsityGen2_Hockey", "VarsityGen2_Soccer",
        "VarsityGen2_Volleyball"}
    for f in varsity.PROTOCOLS.values():
        assert f().contract_name


# --------------------------------------------------------------------------- Varsity (Main) framing
@pytest.fixture(params=["Varsity_Basketball", "Varsity_Baseball", "Varsity_Soccer"])
def main_proto(request):
    return varsity.PROTOCOLS[request.param]()


def test_main_garbage_split_and_checksum(main_proto):
    good = main_frame(0, bytes([12, 7]))
    # garbage before the frame (bytes outside 3..19 are skipped)
    assert main_proto.feed(b"\xff\x00\x01" + good) == 1
    # split across feed() calls
    assert main_proto.feed(good[:2]) == 0
    assert main_proto.feed(good[2:]) == 1
    # bad checksum rejected and counted
    bad = bytearray(good)
    bad[-1] ^= 0x01
    before = main_proto.bad
    assert main_proto.feed(bytes(bad)) == 0
    assert main_proto.bad > before
    # still recovers (the leftover bytes of the bad packet may swallow the next one or two)
    assert main_proto.feed(good * 4) >= 1


def test_main_basketball():
    p = varsity.PROTOCOLS["Varsity_Basketball"]()
    c = feed(p, main_frame(0, bytes([105, 7, 3, 12])))  # scores, home fouls 3 (reg 2)
    assert c["HomeScoreHundreds"] == "1" and c["HomeScoreTens"] == "0" and c["HomeScoreOnes"] == "5"
    assert c["GuestScoreHundreds"] == " " and c["GuestScoreTens"] == " " and c["GuestScoreOnes"] == "7"
    assert c["HomeFoulTens"] == " " and c["HomeFoulOnes"] == "3"
    assert c["EventId"] == "Basketball" and p.contract_name == "Basketball"
    c = feed(p, main_frame(3, bytes([12, 1, 0, 2])))    # guest fouls, possession(4), reg 5 ignored, period(6)
    assert c["GuestFoulTens"] == "1" and c["GuestFoulOnes"] == "2"
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert c["Period"] == "2"
    c = feed(p, main_frame(4, bytes([0])))
    assert c["HomePossession"] == " " and c["GuestPossession"] == ">"
    c = feed(p, main_frame(9, bytes([1, 0])))
    assert c["HomeBonus"] == "B" and c["GuestBonus"] == " "
    c = feed(p, main_frame(45, bytes([2, 3])))
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "3"
    c = feed(p, main_frame(50, bytes([1, 1])))
    assert c["HomeDoubleBonus"] == "B" and c["GuestDoubleBonus"] == "B"


def test_main_soccer():
    p = varsity.PROTOCOLS["Varsity_Soccer"]()
    c = feed(p, main_frame(0, bytes([3, 12, 5, 0, 1])))
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "3")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "2")
    assert c["HomePenalties"] == " 5" and c["GuestPenalties"] == " 0"
    assert c["HomePossession"] == "<"
    c = feed(p, main_frame(9, bytes([14, 7])))
    assert (c["HomeShotTens"], c["HomeShotOnes"]) == ("1", "4")
    assert (c["GuestShotTens"], c["GuestShotOnes"]) == (" ", "7")
    c = feed(p, main_frame(6, bytes([2])))
    assert c["Period"] == "2"
    c = feed(p, main_frame(45, bytes([1, 2])))
    assert c["HomeTimeouts"] == "1" and c["GuestTimeouts"] == "2"
    assert p.contract_name == "Soccer" and c["EventId"] == "Soccer"


def test_main_baseball():
    p = varsity.PROTOCOLS["Varsity_Baseball"]()
    c = feed(p, main_frame(0, bytes([12, 3, 9, 0, 1, 2, 7])))
    assert (c["HomeRunTens"], c["HomeRunOnes"]) == ("1", "2")
    assert (c["GuestRunTens"], c["GuestRunOnes"]) == (" ", "3")
    assert (c["HomeHitsTens"], c["HomeHitsOnes"]) == (" ", "9")
    assert (c["GuestHitsTens"], c["GuestHitsOnes"]) == (" ", "0")
    assert c["HomeErrors"] == "1" and c["GuestErrors"] == "2"
    assert (c["InningTens"], c["InningOnes"]) == (" ", "7")
    c = feed(p, main_frame(9, bytes([2, 1, 2])))
    assert (c["Balls"], c["Strikes"], c["Outs"]) == ("2", "1", "2")
    c = feed(p, main_frame(14, bytes([0x1A, 13])))
    assert (c["AtBatTens"], c["AtBatOnes"]) == ("1", " ")
    assert c["ErrorFlag"] == "E"
    c = feed(p, main_frame(16, bytes([1, 0, 2])))
    assert (c["HomeInning1"], c["HomeInning2"], c["HomeInning3"]) == ("1", "0", "2")
    c = feed(p, main_frame(26, bytes([4, 5])))
    assert (c["GuestInning1"], c["GuestInning2"]) == ("4", "5")
    c = feed(p, main_frame(41, bytes([1, 0])))
    assert c["BottomOfInning"] == "." and c["TopOfInning"] == " " and c["TopBottomInning"] == "B"
    c = feed(p, main_frame(41, bytes([0, 1])))
    assert c["TopOfInning"] == "." and c["TopBottomInning"] == "T"
    assert p.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"


def test_main_clock_and_shot_clock():
    p = varsity.PROTOCOLS["Varsity_Basketball"]()
    t = FakeTime()
    p.decoder.now = t
    # stopped at 7:30.0 (45000 centiseconds)
    c = feed(p, clock_main(76, 45000))
    assert c["InternalClockStatus"] == "S" and c["ClockMode"] == ":"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == \
        ("0", "7", "3", "0")
    # run: counts down in real time
    c = feed(p, clock_main(73, 45000))
    assert c["InternalClockStatus"] == "R"
    t.t += 10.0
    c = p.snapshot()
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("7", "2", "0")
    # a second start packet while running does not re-anchor the clock
    feed(p, clock_main(73, 45000))
    t.t += 10.0
    c = p.snapshot()
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("7", "1", "0")
    # under a minute: tenths, rounded up from the second hundredth
    feed(p, clock_main(76, 5430))  # 54.3 s
    c = p.snapshot()
    assert c["ClockMode"] == "." and (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == \
        ("5", "4", "3")
    # shot clock (play clock): seconds only
    c = feed(p, clock_main(77, 2400))
    assert c["PlayClockStatusInternal"] == "R"
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    t.t += 5.0
    c = p.snapshot()
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("1", "9")


def test_main_clock_version_ticks_when_running():
    p = varsity.PROTOCOLS["Varsity_Basketball"]()
    t = FakeTime()
    p.decoder.now = t
    p.feed(clock_main(73, 12000))
    v = p.version
    t.t += 3.0
    assert p.version > v


def test_main_soccer_ignores_play_clock_messages():
    p = varsity.PROTOCOLS["Varsity_Soccer"]()
    p.decoder.now = FakeTime()
    c = feed(p, clock_main(77, 2400))
    assert "PlayClockStatusInternal" not in c
    c = feed(p, clock_main(76, 4500))  # 45.00 s -> under a minute
    assert c["InternalClockStatus"] == "S" and c["ClockMode"] == "."
    assert (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("4", "5")


# --------------------------------------------------------------------------- Gen2 framing
@pytest.fixture(params=sorted(i for i in varsity.PROTOCOLS if i.startswith("VarsityGen2")))
def gen2_proto(request):
    return varsity.PROTOCOLS[request.param]()


def test_gen2_garbage_split_and_checksum(gen2_proto):
    good = gen2_frame(0, {11: 21}, size=71)
    assert gen2_proto.feed(b"\x01\x02\x03" + good) == 1
    assert gen2_proto.feed(good[:10]) == 0
    assert gen2_proto.feed(good[10:]) == 1
    bad = bytearray(good)
    bad[11] ^= 0x04
    before = gen2_proto.bad
    assert gen2_proto.feed(bytes(bad)) == 0
    assert gen2_proto.bad == before + 1
    assert gen2_proto.feed(good) == 1
    assert gen2_proto.feed(good + good) == 2


def test_gen2_basketball():
    p = varsity.PROTOCOLS["VarsityGen2_Basketball"]()
    f = {11: 105, 12: 7, 13: 3, 14: 12, 15: 1, 16: 0, 17: 2, 27: 1, 28: 0, 63: 4, 64: 5, 68: 0, 69: 1}
    c = feed(p, gen2_frame(0, f, size=71))
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", " ", "7")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"]) == (" ", "3")
    assert (c["GuestFoulTens"], c["GuestFoulOnes"]) == ("1", "2")
    assert c["HomePossession"] == "<" and c["GuestPossession"] == " "
    assert c["Period"] == "2"
    assert c["HomeBonus"] == "B" and c["GuestBonus"] == " "
    assert c["HomeTimeouts"] == "4" and c["GuestTimeouts"] == "5"
    assert c["HomeDoubleBonus"] == " " and c["GuestDoubleBonus"] == "B"
    assert p.contract_name == "Basketball"


def test_gen2_basketball_short_frame_does_not_raise():
    p = varsity.PROTOCOLS["VarsityGen2_Basketball"]()
    c = feed(p, gen2_frame(0, {11: 12, 12: 3}, size=20))
    assert c["HomeScoreOnes"] == "2" and "HomeTimeouts" not in c
    assert p.bad == 0


def test_gen2_football():
    p = varsity.PROTOCOLS["VarsityGen2_Football"]()
    f = {11: 14, 12: 7, 15: 0, 16: 1, 17: 3, 27: 2, 28: 10, 29: 35, 30: 2, 31: 1}
    c = feed(p, gen2_frame(0, f))
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "4")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "7")
    assert c["HomePossession"] == " " and c["GuestPossession"] == ">"
    assert (c["Quarter"], c["Down"]) == ("3", "2")
    assert (c["ToGoTens"], c["ToGoOnes"]) == ("1", "0")
    assert (c["BallOnTens"], c["BallOnOnes"]) == ("3", "5")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("2", "1")
    assert p.contract_name == "Football" and c["EventId"] == "Football"


def test_gen2_hockey():
    p = varsity.PROTOCOLS["VarsityGen2_Hockey"]()
    c = feed(p, gen2_frame(0, {11: 3, 12: 10, 13: 9, 14: 21, 15: 1, 17: 2}))
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "3")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "0")
    assert (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"]) == ("0", "9")
    assert (c["GuestShotOnGoalTens"], c["GuestShotOnGoalOnes"]) == ("2", "1")
    assert c["Period"] == "2" and c["HomePossession"] == "<"
    assert p.contract_name == "HockeyLacrosse" and c["EventId"] == "Hockey"


def test_gen2_soccer():
    p = varsity.PROTOCOLS["VarsityGen2_Soccer"]()
    c = feed(p, gen2_frame(0, {11: 2, 12: 11, 16: 1, 17: 1}))
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "2")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "1")
    assert c["GuestPossession"] == ">" and c["Period"] == "1"
    assert p.contract_name == "Soccer"


def test_gen2_baseball():
    p = varsity.PROTOCOLS["VarsityGen2_Baseball"]()
    f = {11: 5, 12: 12, 17: 9, 27: 3, 28: 2, 29: 1, 32: 0x1F, 33: 172}
    c = feed(p, gen2_frame(0, f))
    assert (c["HomeRunTens"], c["HomeRunOnes"]) == (" ", "5")
    assert (c["GuestRunTens"], c["GuestRunOnes"]) == ("1", "2")
    assert (c["InningTens"], c["InningOnes"]) == (" ", "9")
    assert (c["Balls"], c["Strikes"], c["Outs"]) == ("3", "2", "1")
    assert (c["AtBatTens"], c["AtBatOnes"]) == ("1", " ")
    assert c["ErrorFlag"] == "H"
    c = feed(p, gen2_frame(0, {**f, 33: 173}))
    assert c["ErrorFlag"] == "E"
    # frames longer than 62 bytes are ignored
    c = feed(p, gen2_frame(0, {11: 40}, size=70))
    assert c["HomeRunOnes"] == "5"
    assert p.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"


def test_gen2_volleyball():
    p = varsity.PROTOCOLS["VarsityGen2_Volleyball"]()
    f = {11: 25, 12: 3, 13: 2, 14: 0, 15: 1, 16: 0, 17: 3}
    c = feed(p, gen2_frame(0, f))
    assert (c["HomeScoreTens"], c["HomeScoreOnes"]) == ("2", "5")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "3")
    assert c["HomeGamesWon"] == "2" and c["GuestGamesWon"] == " "
    assert c["HomeServe"] == "*" and c["GuestServe"] == " "
    assert c["Game"] == "3"
    assert p.contract_name == "Volleyball" and c["EventId"] == "Volleyball"
    # the length byte limits which fields are read: a frame of 13 bytes covers offsets up to 12
    c = feed(p, gen2_frame(0, {11: 30, 12: 31}, size=14))
    assert c["HomeScoreTens"] == "3" and c["GuestScoreOnes"] == "1"


def test_gen2_clock_run_stop_and_rounding():
    p = varsity.PROTOCOLS["VarsityGen2_Football"]()
    t = FakeTime()
    p.decoder.now = t
    c = feed(p, clock_gen2(1, 12 * 60 * 1000))  # stopped 12:00.000
    assert c["InternalClockStatus"] == "S" and c["ClockMode"] == ":"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == \
        ("1", "2", "0", "0")
    feed(p, clock_gen2(0, 90_500))  # run 1:30.5 -> 1:31 displayed (rounded up)
    c = p.snapshot()
    assert c["InternalClockStatus"] == "R"
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "3", "1")
    t.t += 40.0   # 50.5 s left -> tenths shown, bumped by one (Gen2 rounding oddity)
    c = p.snapshot()
    assert c["ClockMode"] == "." and (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == \
        ("5", "0", "6")
    t.t += 100.0  # runs out
    c = p.snapshot()
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == ("0", "0", "0")


def test_gen2_play_clock_and_team_names():
    p = varsity.PROTOCOLS["VarsityGen2_Football"]()
    t = FakeTime()
    p.decoder.now = t
    c = feed(p, clock_gen2(4, 25_000))
    assert c["PlayClockStatusInternal"] == "R"
    assert (c["PlayClockTens"], c["PlayClockOnes"]) == ("2", "5")
    t.t += 5.0
    c = p.snapshot()
    assert (c["PlayClockTens"], c["PlayClockOnes"]) == ("2", "0")
    c = feed(p, clock_gen2(5, 40_000))
    assert c["PlayClockStatusInternal"] == "S" and (c["PlayClockTens"], c["PlayClockOnes"]) == ("4", "0")
    names = gen2_frame(6, {7: 0, **{8 + i: ord(ch) for i, ch in enumerate("EAGLES  ")}}, size=20)
    names2 = gen2_frame(6, {7: 1, **{8 + i: ord(ch) for i, ch in enumerate("TIGERS\x01 ")}}, size=20)
    c = feed(p, names + names2)
    assert c["HomeTeamName"] == "EAGLES  " and c["GuestTeamName"] == "TIGERS  "


def test_gen2_shot_clock_basketball_hockey_and_soccer_noop():
    for pid, keys in (("VarsityGen2_Basketball", ("ShotClockSecondTens", "ShotClockSecondOnes")),
                      ("VarsityGen2_Hockey", ("ShotClockTens", "ShotClockOnes"))):
        p = varsity.PROTOCOLS[pid]()
        p.decoder.now = FakeTime()
        c = feed(p, clock_gen2(5, 24_000))
        assert (c[keys[0]], c[keys[1]]) == ("2", "4")
    p = varsity.PROTOCOLS["VarsityGen2_Soccer"]()
    p.decoder.now = FakeTime()
    c = feed(p, clock_gen2(5, 24_000))
    assert "PlayClockStatusInternal" not in c
    c = feed(p, clock_gen2(1, 45 * 60 * 1000))
    assert c["ClockMinutesTens"] == "4" and c["ClockMinutesOnes"] == "5"
