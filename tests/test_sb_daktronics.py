from conftest import make_cl_frame
from scoreboards import create, daktronics as dk
from scoreboards.common import SEG7

INV = {v: k for k, v in SEG7.items() if v != " "}
INV[" "] = 0


def S(text):
    return [INV[ch] for ch in text]


def fr(addr, fields, size=None):
    """Frame with data bytes placed by packet index (p[5] is data[0]); `fields` maps index -> int or list."""
    flat = {}
    for i, v in fields.items():
        for k, b in enumerate(v if isinstance(v, (list, tuple)) else [v]):
            flat[i + k] = b
    top = max(flat) if flat else 5
    n = max(size or 0, top - 4)
    data = bytearray(n)
    for i, b in flat.items():
        data[i - 5] = b
    return make_cl_frame(addr, bytes(data))


def run(pid, *frames, chunk=None):
    p = create(pid)
    stream = b"".join(frames)
    if chunk:
        for i in range(0, len(stream), chunk):
            p.feed(stream[i:i + chunk])
    else:
        p.feed(stream)
    return p, p.snapshot()


def has(c, **kw):
    for k, v in kw.items():
        assert c.get(k) == v, (k, c.get(k), v)


def test_registry_has_all_ids():
    ids = {"3000_Baseball", "3000_Football", "Autodetect", "BaseBall_Pitch_Speed", "Baseball", "Baseball1600",
           "Baseball5601", "Baseball_Pitch_Clock", "Basketball", "Basketball5500", "Basketball9122", "Football",
           "Football1600", "FootballCode6103", "Hockey5000", "Hockey5000Code4103", "Hockey5000Code9405",
           "JvcPracticeFootball", "Lacrosse5000", "Lacrosse5000Code4103", "Rodeo2000", "Soccer", "Softball",
           "Swimming", "Timer8601", "Volleyball", "Volleyball5500", "Waterpolo2000", "Wrestling3000"}
    assert set(dk.PROTOCOLS) == {"Daktronics_" + i for i in ids}


# ---- framing
def test_framing_garbage_split_and_rejection():
    f = fr(1, {5: S("1200")}, size=7)
    p, c = run("Daktronics_Football", b"\x00junk\x55", f * 2, chunk=3)
    assert p.packets == 2 and c["ClockMinutesTens"] == "1"
    bad = bytearray(f)
    bad[-4] ^= 0xFF
    p, c = run("Daktronics_Football", bytes(bad))
    assert p.packets == 0 and p.bad == 1
    lenbad = bytearray(f)
    lenbad[3] += 1  # wrong length byte: frame waits for more bytes then fails its checksum
    p, _ = run("Daktronics_Football", bytes(lenbad))
    assert p.packets == 0  # waits for the (longer) frame to arrive
    p.feed(bytes(8))
    assert p.packets == 0 and p.bad == 1
    p, _ = run("Daktronics_Football", f[:-3])
    assert p.packets == 0 and p.bad == 0
    p.feed(f[-3:])
    assert p.packets == 1


def test_short_unguarded_packet_does_not_raise():
    p, _ = run("Daktronics_Rodeo2000", make_cl_frame(12, b"\x00"))
    assert p.packets == 1 and p.decoder.short == 1


# ---- football family
def test_football():
    f1 = fr(1, {5: S("1200"), 9: S("25"), 11: 0x40}, size=7)
    f15 = fr(15, {5: S("1200"), 11: S("0724"), 15: S("2"), 17: 7, 18: S("32")}, size=16)
    f16 = fr(16, {5: S("353 7")})
    p, c = run("Daktronics_Football", f1, f15, f16, chunk=5)
    has(c, ClockMode=":", ClockMinutesTens="1", ClockSecondOnes="0", ClockTenthsSecond="0", PlayClockTens="2",
        PlayClockOnes="5", InternalClockStatus="S", HomeScoreTens="0", HomeScoreOnes="7", GuestScoreTens="2",
        GuestScoreOnes="4", Quarter="2", HomePossession="<", GuestPossession=" ", HomeTimeouts="3",
        GuestTimeouts="2", BallOnTens="3", BallOnOnes="5", Down="3", ToGoTens=" ", ToGoOnes="7", EventId="Football")
    assert p.contract_name == "Football"


def test_football_tenths_mode():
    f1 = fr(1, {5: S("598"), 8: 0, 11: 0}, size=7)
    f15 = fr(15, {5: S("598")}, size=11)
    _, c = run("Daktronics_Football", f1, f15)
    has(c, ClockMode=".", ClockMinutesTens="0", ClockSecondTens="5", ClockSecondOnes="9", ClockTenthsSecond="8",
        InternalClockStatus="R")


def test_football6103():
    f12 = fr(12, {9: S("1403"), 17: S("12"), 19: S("2"), 20: S("4")}, size=17)
    f14 = fr(14, {7: S("3"), 13: S("2")}, size=10)
    f13 = fr(13, {13: S("3")}, size=10)
    f220 = fr(220, {14: 128}, size=11)
    f1 = fr(1, {5: S("0845"), 9: S("40"), 11: 0}, size=7)
    f15 = fr(15, {5: S("0845"), 11: S("1403"), 17: 56, 18: S("32")}, size=16)
    _, c = run("Daktronics_FootballCode6103", f12, f14, f13, f220, f1, f15)
    has(c, HomeScoreTens="1", HomeScoreOnes="4", GuestScoreTens="0", GuestScoreOnes="3", ToGoTens="1",
        ToGoOnes="2", Down="2", Quarter="3", HomeTimeouts="3", GuestTimeouts="2", PlayClockTens="4",
        ClockMinutesOnes="8", InternalClockStatus="R", GuestPossession=">", HomePossession=" ")


def test_football3000():
    f1 = fr(1, {5: S("1000"), 9: S("12")}, size=7)
    f12 = fr(12, {5: S("1000"), 9: S("2113"), 13: 56, 19: S("4")}, size=16)
    f23 = fr(23, {5: S("4 2 5")})
    _, c = run("Daktronics_3000_Football", f1, f12, f23)
    has(c, PlayClockOnes="2", HomeScoreTens="2", HomeScoreOnes="1", GuestScoreOnes="3", GuestPossession=">",
        Quarter="4", BallOnTens="4", Down="2", ToGoOnes="5", ClockMinutesTens="1")


def test_jvc_practice_football():
    f1 = fr(1, {5: S("1000"), 9: S("30"), 11: 0x40}, size=7)
    f15 = fr(15, {5: S("1000"), 13: S("17"), 15: S("1"), 17: 7, 18: S("21")}, size=16)
    _, c = run("Daktronics_JvcPracticeFootball", f1, f15)
    has(c, GuestScoreTens="1", GuestScoreOnes="7", Quarter="1", HomeTimeouts="2", GuestTimeouts="1",
        InternalClockStatus="S", HomePossession="<")
    assert "HomeScoreTens" not in c


def test_football1600():
    f = fr(11, {5: S("0930"), 15: S("0714"), 19: S("2")}, size=16)
    _, c = run("Daktronics_Football1600", f)
    has(c, ClockMode=":", ClockMinutesOnes="9", HomeScoreOnes="7", GuestScoreTens="1", GuestScoreOnes="4", Down="2")


# ---- soccer (with real captured bytes)
H = bytes.fromhex
SOCCER = {
    0xFE: b"76015000430",
    1: H("fd bf bf bf 00 00 40"),
    11: H("fd bf bf bf 00 00 00 00 0f 00 00 ed 00 fd 87 00"),
    12: H("fd bf bf bf 00 ed 00 fd 3f 00 00 86 00 db 00 00"),
    13: H("e6 ed bf bf 00 bf 00 bf 07 00 00 00 00 00 00 00"),
    16: H("00 db 00 00 86"),
    17: H("fd bf bf bf 00 ed 00 fd 00 00 00 86 00 db 00 87"),
    72: H("00 cf 00 00 86 00 00 00 00 00 00 e6 00 00 db 00"),
}


def test_soccer_real_capture_7601():
    stream = b"".join(make_cl_frame(a, d) for a, d in SOCCER.items()) * 2
    p, c = run("Daktronics_Soccer", stream, chunk=13)
    assert p.packets == 16 and p.bad == 0
    has(c, ClockMode=":", ClockMinutesTens="6", ClockMinutesOnes="0", ClockSecondTens="0", ClockSecondOnes="0",
        InternalClockStatus="S", HomeScoreTens=" ", HomeScoreOnes="5", GuestScoreTens=" ", GuestScoreOnes="6",
        Period="7", HomeShotTens=" ", HomeShotOnes="1", GuestShotTens=" ", GuestShotOnes="2", Horn=" ",
        HomeSaves="00", GuestSaves=" 1")
    # ScoreConnect reads corners from addr 13 p[15..18]; this board sends zeros there (blank), so the
    # known-good 3/4 only appears on the address 72 stats panel, which Daktronics_Soccer ignores.
    has(c, HomeCornerKicks="  ", GuestCornerKicks="  ")


def test_soccer_synthetic():
    f1 = fr(1, {5: S("0123"), 11: 0}, size=7)
    f11 = fr(11, {5: S("4530"), 15: S("0102"), 19: S("2")}, size=16)
    f12 = fr(12, {13: 0x80, 15: S("0304")}, size=14)
    f13 = fr(13, {15: S("0506")}, size=14)
    f17 = fr(17, {7: S("07"), 15: S("08")}, size=12)
    _, c = run("Daktronics_Soccer", f1, f11, f12, f13, f17)
    has(c, InternalClockStatus="R", ClockMinutesTens="4", HomeScoreOnes="1", GuestScoreOnes="2", Period="2",
        Horn="H", HomeShotOnes="3", GuestShotOnes="4", HomeCornerKicks="05", GuestCornerKicks="06",
        HomeSaves="07", GuestSaves="08")


# ---- basketball family
def test_basketball():
    f1 = fr(1, {5: S("0712"), 9: S("14"), 11: 0}, size=7)
    f12 = fr(12, {5: S("0712"), 9: S("2118"), 13: 0x04 | 0x20 | 0x80, 14: 0x01 | 0x10, 15: S("5"), 16: S("3"),
                  17: S("12"), 19: S("2"), 20: S("3")}, size=16)
    f17 = fr(17, {13: S("2"), 14: S("1")}, size=10)
    f220 = fr(220, {14: 4}, size=11)
    f23 = fr(23, {5: S("23") + S("1") + S("04") + S("45") + S("3") + S("12"), 20: S("3")}, size=16)
    f24 = fr(24, {5: S("77") + S("2") + S("10"), 17: S("5"), 20: S("2")}, size=16)
    f25 = fr(25, {5: S("11") + S("0") + S("02"), 20: S("1")}, size=16)
    f26 = fr(26, {5: S("33") + S("4") + S("19"), 17: S("2"), 20: S("4")}, size=16)
    p, c = run("Daktronics_Basketball", f1, f12, f17, f220, f23, f24, f25, f26)
    has(c, ShotClockSecondTens="1", ShotClockSecondOnes="4", ClockMinutesOnes="7", HomeScoreTens="2",
        HomeScoreOnes="1", GuestScoreTens="1", GuestScoreOnes="8", HomeScoreHundreds="1", GuestScoreHundreds=" ",
        HomePossession="<", GuestPossession=" ", GuestBonus="B", Horn="H", HomeFoulTens="1", HomeFoulOnes="5",
        GuestFoulTens=" ", GuestFoulOnes="3", FoulPlayerTens="1", FoulPlayerOnes="2",
        FoulPlayerNumberOfFouls="2", Period="3", HomeTimeouts="2", GuestTimeouts="1", HomeDoubleBonus="B")
    has(c, HomePlayer1="23", HomePlayer1FoulNumber="1", HomePlayer1Points="04", HomePlayer2="45",
        HomeFullTimeouts="3", HomePlayer4="77", HomePlayer4FoulNumber="2", HomePlayer4Points="10",
        HomeBottomCenter="5", HomePartialTimeouts="2", GuestPlayer1="11", GuestPlayer1Points="02",
        GuestFullTimeouts="1", GuestPlayer4="33", GuestPlayer4Points="19", InboundChannelNumber="2",
        GuestPartialTimeouts="4")


def test_basketball_shotclock_tenths():
    f1 = fr(1, {5: S("0059"), 13: S("5"), 14: 0, 15: S("3")}, size=11)
    _, c = run("Daktronics_Basketball", f1)
    has(c, ShotClockSecondTens=" ", ShotClockSecondOnes="5", ShotClockTenthsSecond="3")


def test_basketball_team_names_from_bitmaps():
    home = [255, 9, 9, 6, 0, 254, 9, 254, 0, 0]
    guest = [255, 137, 118, 0, 126, 129, 126, 0, 0, 0]
    data = bytes(home + guest)
    p, c = run("Daktronics_Basketball", make_cl_frame(221, data))
    assert (c["HomeTeamName"], c["GuestTeamName"]) == ("PA      ", "BO      ")


def test_basketball9122():
    f1 = fr(1, {5: S("0501"), 11: 0x50, 13: S("2"), 14: S("4")}, size=11)
    f13 = fr(13, {9: S("08") , 11: S("11"), 13: S("3"), 14: 0x40 | 0x01, 15: S("12"), 17: S("2"), 18: S("0"),
                  19: S("7"), 20: S("1")}, size=17)
    f14 = fr(14, {8: S("23"), 10: S("4"), 13: 0x80}, size=11)
    f23 = fr(23, {5: S("55"), 20: S("2")}, size=16)
    p, c = run("Daktronics_Basketball9122", f1, f13, f14, f23)
    has(c, InternalClockStatus="S", Horn="H", ShotClockSecondTens="2", ShotClockSecondOnes="4",
        HomeScoreOnes="8", GuestScoreOnes="1", Period="3", HomePossession="<", HomeBonus="B", HomeFoulTens="1",
        HomeFoulOnes="2", GuestFoulOnes="7", HomeTimeouts="2", GuestTimeouts="1", FoulPlayerTens="2",
        FoulPlayerOnes="3", FoulPlayerNumberOfFouls="4", HomePlayer1="55", HomeFullTimeouts="2")


def asc(s):
    return [ord(ch) for ch in s]


def f5500(group, item, body, size=None):
    # p[6]=group, p[7]=item, p[8]=?, payload from p[9]
    fields = {6: group, 7: item}
    for i, b in body.items():
        fields[i] = b
    return fr(0x01, fields, size=size or 12)


def test_basketball5500():
    clock = f5500(17, 1, {13: 67, 14: asc("07"), 17: asc("45"), 19: 32}, size=17)
    clock2 = f5500(17, 1, {13: 48, 17: asc("12"), 19: 46, 20: ord("3")}, size=17)
    score = f5500(33, 1, {9: 32, 10: asc(" 78")}, size=10)
    gscore = f5500(33, 2, {9: 155, 14: asc("102")}, size=14)
    tos = f5500(33, 6, {10: ord("3")}, size=7)
    per = f5500(33, 11, {10: ord("2")}, size=7)
    fouls = f5500(33, 12, {9: asc("07")}, size=7)
    name = f5500(81, 1, {13: asc("TIGERS")}, size=16)
    poss = f5500(49, 3, {9: ord("1")}, size=7)
    shot = f5500(17, 4, {10: asc("14")}, size=9)
    p, c = run("Daktronics_Basketball5500", clock, score, gscore, tos, per, fouls, name, poss, shot)
    has(c, InternalClockStatus="R", ClockMinutesTens="0", ClockMinutesOnes="7", ClockSecondTens="4",
        ClockSecondOnes="5", ClockMode=":", HomeScoreHundreds=" ", HomeScoreTens="7", HomeScoreOnes="8",
        GuestScoreHundreds="1", GuestScoreTens="0", GuestScoreOnes="2", HomeTimeouts="3", Period="2",
        HomeFoulTens="0", HomeFoulOnes="7", HomeTeamName="TIGERS  ", HomePossession="<",
        ShotClockSecondTens="1", ShotClockSecondOnes="4")
    _, c = run("Daktronics_Basketball5500", clock2)
    has(c, ClockMode=".", ClockSecondOnes="2", ClockTenthsSecond="3", InternalClockStatus="S")


# ---- volleyball
def test_volleyball():
    f1 = fr(1, {5: S("1000"), 11: 0x40}, size=7)
    f12 = fr(12, {5: S("1000"), 9: S("1523"), 13: 0x04, 15: S("12"), 19: S("3"), 20: S("2")}, size=17)
    f17 = fr(17, {13: S("1"), 14: S("2")}, size=10)
    f15 = fr(15, {5: S("2519") + S("2523")}, size=17)
    f23 = fr(23, {5: S("12") + S("3") + S("45")}, size=17)
    f26 = fr(26, {15: S("99") + S("1") + S("07")}, size=17)
    f221 = make_cl_frame(221, bytes([255, 0, 0, 0] + [255, 9, 9, 6, 0, 0, 0, 0]))
    p, c = run("Daktronics_Volleyball", f1, f12, f17, f15, f23, f26, f221)
    has(c, InternalClockStatus="S", HomeScoreTens="1", HomeScoreOnes="5", GuestScoreOnes="3", HomeServe="*",
        GuestServe=" ", HomeGamesWon="1", GuestGamesWon="2", Game="3", Set="2", HomeTimeout="1", GuestTimeout="2",
        HomeScoreSet1="25", GuestScoreSet1="19", HomeScoreSet2="25", GuestScoreSet2="23", HomePlayer1="12",
        HomePlayer1Kills="3", HomePlayer1Digs="45", GuestPlayer6="99", GuestPlayer6Kills="1",
        GuestPlayer6Digs="07")
    # volleyball names start at p[4] (the 0x22 byte) rather than p[5]; both are 8 characters
    assert len(c["HomeTeamName"]) == 8 and len(c["GuestTeamName"]) == 8


def test_volleyball5500():
    clock = f5500(17, 1, {13: 67, 14: asc("12"), 17: asc("30"), 19: 32}, size=17)
    sc = f5500(33, 1, {9: 32, 11: asc("15")}, size=12)
    gsc = f5500(33, 2, {9: 155, 15: asc("21")}, size=16)
    to = f5500(33, 6, {10: ord("2")}, size=12)
    gw = f5500(33, 12, {14: ord("1")}, size=15)
    nm = f5500(81, 2, {13: asc("LIONS")}, size=16)
    srv = f5500(49, 5, {9: ord("1")}, size=12)
    _, c = run("Daktronics_Volleyball5500", clock, sc, gsc, to, gw, nm, srv)
    has(c, InternalClockStatus="R", ClockMinutesTens="1", ClockSecondTens="3", ClockMode=":", HomeScoreTens="1",
        HomeScoreOnes="5", GuestScoreTens="2", GuestScoreOnes="1", HomeTimeout="2", HomeGamesWon="1",
        GuestServe="*")
    assert c["GuestTeamName"].startswith("LIONS")


# ---- hockey / lacrosse
def test_hockey5000_and_lacrosse():
    f1 = fr(1, {5: S("1500"), 9: S("30"), 11: 0}, size=9)
    f71 = fr(71, {5: S("1500"), 9: S("0302"), 13: 0x80, 20: S("2")}, size=17)
    f17 = fr(17, {13: S("1"), 14: S("2")}, size=10)
    pen = {5: S("12") + S("2") + S("30") + S("34") + S("1") + S("00"), 15: S("07")}
    f72 = fr(72, pen, size=14)
    f73 = fr(73, pen, size=14)
    for pid, ev in (("Daktronics_Hockey5000", "Hockey"), ("Daktronics_Lacrosse5000", "Lacrosse")):
        p, c = run(pid, f1, f71, f17, f72, f73)
        has(c, EventId=ev, ShotClockTens="3", HomeScoreOnes="3", GuestScoreOnes="2", Period="2", Horn="H",
            HomeTimeOut="1", GuestTimeOut="2", HomePenaltyPlayer1Tens="1", HomePenaltyPlayer1Ones="2",
            HomePenaltyPlayer1ClockMinutesOnes="2", HomePenaltyPlayer1ClockSecondTens="3",
            HomeShotOnGoalTens="0", HomeShotOnGoalOnes="7", GuestPenaltyPlayer2Ones="4",
            GuestPenaltyPlayer3Tens=" ", GuestShotOnGoalOnes="7", InternalClockStatus="R")
        assert p.contract_name == "HockeyLacrosse"
    # ScoreConnect quirk: home player 2 "ones" lands in the tens field, ones never set
    assert c["HomePenaltyPlayer2Tens"] == "4" and "HomePenaltyPlayer2Ones" not in c


def test_hockey4103_and_lacrosse4103():
    f1 = fr(1, {5: S("0800"), 11: 0x40}, size=9)
    f11 = fr(11, {5: S("0800"), 9: S("0405")}, size=13)
    f12 = fr(12, {20: S("3")}, size=16)
    f13 = fr(13, {15: S("12") + S("2") + S("34") + S("1")}, size=16)
    pen = {5: S("12") + S("2") + S("30") + S("34") + S("1") + S("00")}
    f23, f25 = fr(23, pen, size=11), fr(25, pen, size=11)
    for pid, ev in (("Daktronics_Hockey5000Code4103", "Hockey"), ("Daktronics_Lacrosse5000Code4103", "Lacrosse")):
        _, c = run(pid, f1, f11, f12, f13, f23, f25)
        has(c, EventId=ev, InternalClockStatus="S", HomeScoreOnes="4", GuestScoreOnes="5", Period="3",
            HomeShotOnGoalTens="1", HomeShotOnGoalOnes="2", HomeTimeOut="2", GuestShotOnGoalOnes="4",
            GuestTimeOut="1", HomePenaltyPlayer2ClockSecondTens="0", GuestPenaltyPlayer1Ones="2",
            HomePenaltyPlayer3ClockSecondTens=" ")
        assert "HomePenaltyPlayer3ClockSecondOnes" not in c


def test_hockey9405():
    f1 = fr(1, {5: S("1245"), 9: S("21"), 11: 0x40}, size=9)
    f12 = fr(12, {9: S("0 "), 11: S("1 ") , 20: S("2")}, size=17)
    f12b = fr(12, {9: S("07"), 11: S("12"), 20: S("2")}, size=17)
    f11 = fr(11, {5: S("12"), 9: S("34")}, size=7)
    _, c = run("Daktronics_Hockey5000Code9405", f1, f12, f11)
    has(c, ClockMode=":", ClockMinutesTens="1", ClockSecondOnes="5", InternalClockStatus="S", ShotClockTens="2",
        HomeScoreTens="0", HomeScoreOnes="0", Period="2", HomeShotOnGoalTens="1", HomeShotOnGoalOnes="2",
        GuestShotOnGoalTens="3", GuestShotOnGoalOnes="4")
    _, c = run("Daktronics_Hockey5000Code9405", f12b)
    has(c, HomeScoreTens="0", HomeScoreOnes="7", GuestScoreTens="1", GuestScoreOnes="2")


# ---- baseball / softball
def test_baseball_and_softball():
    f64 = fr(64, {7: S("213"), 10: 249, 11: S("0412") + S("1") + S("0310") + S("2")}, size=17)
    f65 = fr(65, {5: S("0 2"), 17: S("1")}, size=14)
    f66 = fr(66, {5: S("1")}, size=12)
    f61 = fr(61, {11: 2}, size=8)
    f12 = fr(12, {5: S("07"), 7: S("12")}, size=6)
    f11 = fr(11, {5: S("1234")}, size=6)
    for pid, ev in (("Daktronics_Baseball", "Baseball"), ("Daktronics_Softball", "Softball")):
        p, c = run(pid, f64, f65, f66, f61, f12, f11)
        has(c, EventId=ev, Balls="2", Strikes="1", Outs="3", ErrorFlag="E", GuestRunTens="0", GuestRunOnes="4",
            GuestHitsOnes="2", GuestErrors="1", HomeRunOnes="3", HomeHitsTens="1", GuestInning1="0",
            GuestInning3="2", GuestErrorNumber="1", HomeInning1="1", TopBottomInning="B", BottomOfInning=".",
            TopOfInning=" ", InningTens="0", InningOnes="7", AtBatOnes="2", ClockMinutesTens="1",
            ClockSecondOnes="4")
        assert p.contract_name == "BaseballSoftball"


def test_baseball_pitch_count():
    # pitch count only when the half-inning flag matches and the packet length is 12 or 14 (n == len + 5)
    f61 = fr(61, {11: 2}, size=8)
    f3 = fr(3, {9: [S("9")[0] | 0x80, S("7")[0]]}, size=6)
    _, c = run("Daktronics_Baseball", f61, f3)
    assert c["PitchCount"] == "197"


def test_baseball1600_always_top():
    f = fr(61, {5: S("0102"), 9: S("3"), 13: S("2") + S("1") + S("2")}, size=11)
    _, c = run("Daktronics_Baseball1600", f)
    has(c, Balls="2", Strikes="1", Outs="2", InningOnes="3", InningTens=" ", GuestRunOnes="1", HomeRunTens="0",
        HomeRunOnes="2", TopBottomInning="T", TopOfInning=".")


def test_baseball5601():
    f1 = fr(12, {9: S("0312"), 14: S("2"), 16: S("1"), 18: S("5") + S("1")}, size=16)
    f2 = fr(12, {9: S("0312"), 14: S("2"), 16: S("1"), 18: S("5") + S("0")}, size=16)
    _, c = run("Daktronics_Baseball5601", f1)
    has(c, HomeRunOnes="3", GuestRunTens="1", GuestRunOnes="2", Balls="2", Strikes="1", Outs="1", InningOnes="5",
        TopBottomInning="T")
    _, c = run("Daktronics_Baseball5601", f1, f2)  # same inning, outs fell -> bottom
    has(c, TopBottomInning="B", BottomOfInning=".", Outs="0")


def test_baseball3000():
    f63 = fr(63, {5: S("2") + S("1") + S("2") + S("4") + S("0310") + S("1") + S("0502")}, size=16)
    f11 = fr(11, {5: S("0930")}, size=6)
    _, c = run("Daktronics_3000_Baseball", f63, f11)
    has(c, EventId="Baseball", Balls="2", Strikes="1", Outs="2", InningOnes="4", GuestRunOnes="3",
        GuestHitsTens="1", GuestHitsOnes="0", HomeRunOnes="5", HomeHitsOnes="2", ClockMinutesOnes="9",
        TopBottomInning="T")


def test_pitch_clock_and_speed():
    _, c = run("Daktronics_Baseball_Pitch_Clock", fr(11, {5: S("0015")}, size=5))
    has(c, PitchClockMinutesTens="0", PitchClockSecondTens="1", PitchClockSecondOnes="5")
    _, c = run("Daktronics_BaseBall_Pitch_Speed", fr(1, {6: S("092")}, size=6))
    has(c, PitchSpeed="092")


# ---- other sports
def test_swimming():
    _, c = run("Daktronics_Swimming", fr(1, {5: S("0159")}, size=5))
    has(c, ClockMinutesOnes="1", ClockSecondTens="5", ClockSecondOnes="9", ClockTenthsSecond="0")


def test_timer8601():
    f1 = fr(1, {11: 0x40}, size=8)
    f12 = fr(12, {5: S("1234"), 20: S("5")}, size=17)
    f23 = fr(23, {10: S("6")}, size=8)
    _, c = run("Daktronics_Timer8601", f1, f12, f23)
    has(c, EventId="SingleTimer", InternalClockStatus="S", ClockMinutesTens="1", ClockSecondOnes="4",
        ClockTenthsSecond="5")
    assert "ClockHundredths" not in c  # ScoreConnect's ClockMode checks never match


def test_waterpolo():
    f1 = fr(1, {5: S("0345"), 9: S("30"), 11: 0}, size=8)
    f11 = fr(11, {9: S("0405"), 13: S("2")}, size=10)
    f16 = fr(16, {5: S("12") + S("45") + S("0"), 10: S("33") + S("21")}, size=12)
    f15 = fr(15, {5: S("07") + S("59") , 10: S("08") + S("10")}, size=12)
    p, c = run("Daktronics_Waterpolo2000", f1, f11, f16, f15)
    has(c, ClockMode=":", ClockMinutesOnes="3", ShotClockTens="3", InternalClockStatus="R", HomeScoreOnes="4",
        GuestScoreOnes="5", Period="2", GuestPenaltyPlayer1Ones="2", GuestPenaltyPlayer1ClockSecondTens="4",
        GuestPenaltyPlayer1ClockMinutesTens=" ", GuestPenaltyPlayer2Tens="3", GuestPenaltyPlayer2ClockSecondOnes="1",
        HomePenaltyPlayer1Tens="0", HomePenaltyPlayer2Ones="8", HomePenaltyPlayer2ClockSecondTens="1")
    assert p.contract_name == "WaterPolo"


def test_wrestling():
    f11 = fr(11, {5: S("0145"), 9: S("0306"), 13: 67}, size=11)
    f12 = fr(12, {13: 8}, size=9)
    f14 = fr(14, {5: S("07"), 14: S("12")}, size=13)
    f104 = fr(104, {5: S("123"), 17: S("145")}, size=17)
    p, c = run("Daktronics_Wrestling3000", f11, f12, f14, f104)
    has(c, ClockMode=":", ClockSecondOnes="5", HomeScoreOnes="3", GuestScoreOnes="6", Period="2",
        AdvantageHome=" ", AdvantageGuest="*", HomeMatchScoreOnes="7", GuestMatchScoreTens="1",
        HomeMatchHundreds="1", HomeMatchOnes="3", AdvantageTimeMinutesOnes="1", AdvantageTimeSecondOnes="5")


def test_rodeo():
    f12 = fr(12, {12: S("5")}, size=9)           # last hundredths digit present -> stopped
    f11a = fr(11, {5: S("0042"), 9: S("0000")}, size=9)
    f12r = fr(12, {12: 0}, size=9)                 # blank -> running
    f11b = fr(11, {5: S("0042"), 9: S("1234")}, size=9)
    f11c = fr(11, {5: S("0043"), 9: S("1234")}, size=9)
    p, c = run("Daktronics_Rodeo2000", f12, f11a, f12r, f11b)
    has(c, ClockMode=".", RiderNumber="0042", PrevRiderNumber="0042", InternalClockStatus="R", ClockSecondTens="1",
        ClockSecondOnes="2", ClockTenthsSecond="3", ClockHundreths="4", ClockMilliSeconds="0")
    _, c = run("Daktronics_Rodeo2000", f12, f11c)  # stopped and a new rider: the clock resets
    has(c, InternalClockStatus="S", ClockSecondTens="0", RiderNumber="0043")


# ---- autodetect
def test_autodetect_switches_and_resets():
    code = lambda s: make_cl_frame(0xFE, s.encode() + b"5000430")
    changes = []
    p = create("Daktronics_Autodetect")
    p.decoder.on_detect = changes.append
    p.feed(fr(11, {5: S("1234")}, size=6))  # nothing selected yet
    assert p.snapshot()["EventId"] == "AutoDetect" and "ClockMinutesTens" not in p.snapshot() and p.contract_name == "Generic"
    p.feed(code("6601") + fr(15, {5: S("1200"), 11: S("0724")}, size=16))
    c = p.snapshot()
    has(c, HomeScoreOnes="7", GuestScoreOnes="4", EventId="Football")
    assert p.contract_name == "Football" and changes == ["Daktronics_Football"]
    p.feed(code("6601"))  # same sport: state kept
    assert p.snapshot()["HomeScoreOnes"] == "7"
    p.feed(code("1101") + fr(12, {9: S("21")}, size=16))
    c = p.snapshot()
    assert p.contract_name == "Basketball" and "Quarter" not in c and c["HomeScoreOnes"] == "1"
    p.feed(code("7601"))  # the Rafferty board's soccer code is not in ScoreConnect's table
    assert p.decoder.selected == "Daktronics_Basketball"
    p.feed(code("7701"))
    assert p.contract_name == "Soccer" and changes[-1] == "Daktronics_Soccer"
