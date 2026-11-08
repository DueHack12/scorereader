"""Tests for scoreboards.daktronics_serial: Daktronics Public (RTD), AllSport CG, 4000 V2 and PIC 55 AA 4000."""
from __future__ import annotations

import pytest

from scoreboards import create, daktronics_serial as ds
from scoreboards.pic55aa import make_frame

ENC = {"0": 64, "1": 121, "2": 36, "3": 48, "4": 25, "5": 18, "6": 2, "7": 120, "8": 0, "9": 24, " ": 255}


def e(text: str) -> bytes:
    return bytes(ENC[ch] for ch in text)


def run(pid, data, chunk=0):
    p = ds.PROTOCOLS[pid]()
    if chunk:
        for i in range(0, len(data), chunk):
            p.feed(data[i : i + chunk])
    else:
        p.feed(data)
    return p, p.decoder.c


def check(c, **want):
    for k, v in want.items():
        assert c.get(k) == v, f"{k}: {c.get(k)!r} != {v!r}"


# ------------------------------------------------------------------ Daktronics Public
def pub_frame(dest: int, text: str) -> bytes:
    return (b"\x16" + b"01000100" + b"\x01" + b"004210" + f"{dest:04d}".encode() + b"\x02" + text.encode()
            + b"\x04" + b"00" + b"\x17")


def pub(updates: dict) -> bytes:
    return b"".join(pub_frame(i, t) for i, t in sorted(updates.items()))


BASE = {0: "12:34", 27: "s", 47: "HOMETEAM", 67: "GUESTTEA"}
BASE_CHECK = dict(ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3",
                  ClockSecondOnes="4", ClockTenthsSecond="0", InternalClockStatus="S",
                  HomeTeamName="HOMETEAM", GuestTeamName="GUESTTEA")


def test_public_football():
    p, c = run("DaktronicsPublic_Football", pub({**BASE, 109: "21", 113: "14", 141: " 3", 203: "25", 209: "<",
                                                 219: "35", 221: "2", 224: " 7", 246: "0714", 266: "0123",
                                                 290: "12", 310: "F"}))
    check(c, **BASE_CHECK, HomeScoreTens="2", HomeScoreOnes="1", GuestScoreTens="1", GuestScoreOnes="4",
          Quarter="3", PlayClockTens="2", PlayClockOnes="5", HomePossession="<", BallOnTens="3", Down="2",
          ToGoTens=" ", ToGoOnes="7", HomeScoreQuarter1="07", HomeScoreQuarter2="14", HomeYardsRushing="0123",
          HomeTotalFirstDowns="12", Flag="F", EventId="Football")
    assert p.contract_name == "Football" and p.packets == 16


def test_public_basketball():
    upd = {**BASE, 108: "1", 109: "0", 110: "5", 112: " ", 113: "9", 114: "9", 142: "2", 203: "14", 209: "<",
           223: "B", 235: " 4", 304: "23", 307: "2", 308: "11", 475: "07"}
    p, c = run("DaktronicsPublic_Basketball", pub(upd))
    check(c, **BASE_CHECK, HomeScoreHundreds="1", HomeScoreOnes="5", GuestScoreTens="9", Period="2",
          ShotClockSecondTens="1", ShotClockSecondOnes="4", HomePossession="<", HomeBonus="B",
          HomeFoulTens=" ", HomeFoulOnes="4", HomePlayer1="23", HomePlayer1FoulNumber="2",
          HomePlayer1Points="11", GuestPlayer1="07")


def test_public_hockey_and_lacrosse():
    upd = {**BASE, 109: " 3", 113: " 1", 142: "2", 225: "17", 227: "02", 230: "00", 422: " 9", 28: "h"}
    # clock flag at 27 and horn at 28 are separate columns; rewrite 27-28 as one chunk
    upd = {k: v for k, v in upd.items() if k not in (27, 28)}
    upd[27] = "sh"
    for pid, ev in (("DaktronicsPublic_Hockey", "Hockey"), ("DaktronicsPublic_Lacrosse", "Lacrosse")):
        p, c = run(pid, pub(upd))
        check(c, **BASE_CHECK, EventId=ev, HomeScoreTens=" ", HomeScoreOnes="3", GuestScoreOnes="1", Period="2",
              HomePenaltyPlayer1Tens="1", HomePenaltyPlayer1Ones="7", HomePenaltyPlayer1ClockMinutesOnes="2",
              HomePenaltyPlayer1ClockSecondTens="0", HomeShotOnGoalTens=" ", HomeShotOnGoalOnes="9",
              Horn="H", HomePlayerPopUp=" ")
        assert p.contract_name == "HockeyLacrosse"


def test_public_baseball_and_softball():
    upd = {**BASE, 109: " 3", 113: " 2", 141: " 5", 200: "<", 202: "07", 205: "1", 208: " 6", 211: "0",
           214: "12", 221: "2", 222: "1", 223: "2", 226: "E", 258: "0", 260: "1", 282: "3"}
    for pid in ("DaktronicsPublic_Baseball", "DaktronicsPublic_Softball"):
        p, c = run(pid, pub(upd))
        check(c, **BASE_CHECK, EventId="Baseball", HomeRunOnes="3", GuestRunOnes="2", InningTens=" ",
              InningOnes="5", Balls="2", Strikes="1", Outs="2", TopBottomInning="B", TopOfInning=" ",
              BottomOfInning=".", HomeHitsTens="0", HomeHitsOnes="7", HomeErrors="1", GuestHitsOnes="6",
              AtBatTens="1", AtBatOnes="2", ErrorFlag="E", HomeInning1="0", HomeInning2="1", GuestInning1="3")
    _, c = run("DaktronicsPublic_Baseball", pub({201: ">"}))
    check(c, TopBottomInning="T", TopOfInning=".")


def test_public_soccer():
    upd = {0: "45:00", 47: "HOMETEAM", 109: " 2", 113: " 1", 141: " 2", 200: "<", 259: " 8", 281: " 5",
           336: "4"}
    p, c = run("DaktronicsPublic_Soccer", pub(upd))
    check(c, HomeScoreOnes="2", GuestScoreOnes="1", Period="2", HomePossession="<", HomeShotOnes="8",
          HomeCornerKicks=" 5", ClockMinutesTens="4")
    assert "InternalClockStatus" not in c
    _, c = run("DaktronicsPublic_Soccer", pub({336: "41"}))
    check(c, GuestPenalties="44")  # quirk: column 336 read twice


def test_public_volleyball():
    upd = {**BASE, 109: "15", 113: "13", 200: "*", 214: " 2", 216: " 1", 220: "3", 221: "2521", 247: "1613",
           262: "07", 265: "5", 266: "12", 429: "09"}
    p, c = run("DaktronicsPublic_Volleyball", pub(upd))
    check(c, **BASE_CHECK, HomeScoreTens="1", HomeScoreOnes="5", HomeServe="*", HomeGamesWon="2", Set="3",
          HomeScoreSet1="25", HomeScoreSet2="21", GuestScoreSet1="16", HomePlayer1="07", HomePlayer1Kills="5",
          HomePlayer1Digs="12", GuestPlayer1="09")


def test_public_swimming():
    p, c = run("DaktronicsPublic_Swimming", pub({0: "01:23.4"}))
    check(c, ClockMinutesTens="0", ClockMinutesOnes="1", ClockSecondTens="2", ClockSecondOnes="3",
          ClockTenthsSecond="4", EventId="Swimming")
    assert p.contract_name == "SwimmingDetail"


def test_public_rodeo():
    upd = {0: "00:08.123", 17: "08 76 543", 27: "s", 30: "  42", 52: "07 65 432", 61: " 17 ", 204: "F",
           205: "P"}
    p, c = run("DaktronicsPublic_Rodeo", pub(upd))
    check(c, ClockSecondOnes="8", ClockTenthsSecond="1", ClockHundreths="2", ClockMilliSeconds="3",
          InternalClockStatus="S", RiderNumber="42", RiderScore="08" + "76" + "543", LeaderNumber="17",
          LeaderScore="07" + "65" + "432", ReRide="R", Penalty="P")
    p.feed(pub({204: " ", 205: " "}))
    check(p.decoder.c, ReRide=" ", Penalty="P")  # penalty is sticky in ScoreConnect


def test_public_clock_tenths_mode():
    _, c = run("DaktronicsPublic_Football", pub({0: "5 .9"}))
    check(c, ClockMode=".", ClockMinutesTens="0", ClockSecondTens="5", ClockSecondOnes=" ", ClockTenthsSecond="9")


def test_public_framing():
    data = pub({**BASE, 109: "21"})
    # garbage before, frame split into 3-byte pieces
    p, c = run("DaktronicsPublic_Football", b"junk\x04\x02" + data, chunk=3)
    check(c, HomeScoreTens="2", HomeScoreOnes="1")
    assert p.packets == 5
    # offset persists between frames (patch only the ones digit)
    p.feed(pub_frame(110, "7"))
    check(p.decoder.c, HomeScoreTens="2", HomeScoreOnes="7")


def test_public_rejects():
    p = ds.PROTOCOLS["DaktronicsPublic_Football"]()
    bad = bytearray(pub_frame(109, "21"))
    bad[9] = 0  # SOH missing
    p.feed(bytes(bad))
    assert p.bad == 1 and p.packets == 0
    p.feed(b"\x16short\x17")
    assert p.bad == 2
    p.feed(pub_frame(999, "x" * 30))  # runs past the 1 KB image
    assert p.bad == 3 and p.packets == 0
    p.feed(pub_frame(109, "21"))
    assert p.packets == 1


# ------------------------------------------------------------------ AllSport CG
def cg(n: int, put: dict) -> bytes:
    b = bytearray(b" " * n)
    for i, t in put.items():
        b[i : i + len(t)] = t.encode()
    b[0], b[-1] = 1, 4
    return bytes(b)


CGCLK = {1: "12:34"}


def test_cg_football():
    pk = cg(44, {**CGCLK, 6: "HOME", 16: "GUEST", 26: "2114", 30: "3", 31: "35", 33: "2", 34: " 7", 36: "<",
                 38: "25"})
    p, c = run("DaktronicsAllSportsCG_Football", pk)
    check(c, HomeTeamName="HOME    ", GuestTeamName="GUEST   ", ClockMode=":", ClockMinutesTens="1",
          ClockSecondOnes="4", HomeScoreTens="2", HomeScoreOnes="1", GuestScoreTens="1", GuestScoreOnes="4",
          Quarter="3", BallOnTens="3", BallOnOnes="5", Down="2", ToGoOnes="7", HomePossession="<",
          GuestPossession=" ", PlayClockTens="2", PlayClockOnes="5", HomeTimeouts=" ", GuestTimeouts="1")
    assert p.contract_name == "Football"


@pytest.mark.parametrize("pid,off", [("DaktronicsAllSportsCG_Basketball", 0), ("DaktronicsAllSportsCG_BasketballUNCG", 2)])
def test_cg_basketball(pid, off):
    pk = cg(32, {**CGCLK, 8: "S", 9: "24", 13 - off: "105", 16 - off: " 98", 19 - off: "0407", 29 - off: "3"})
    p, c = run(pid, pk)
    check(c, ClockMode=":", InternalClockStatus="S", ShotClockSecondTens="2", ShotClockSecondOnes="4",
          HomeScoreHundreds="1", HomeScoreTens="0", HomeScoreOnes="5", GuestScoreHundreds=" ",
          GuestScoreTens="9", GuestScoreOnes="8", HomeFoulTens="0", HomeFoulOnes="4", GuestFoulOnes="7",
          Period="3", EventId="Basketball")


def test_cg_basketball_tenths():
    _, c = run("DaktronicsAllSportsCG_Basketball", cg(32, {4: "09", 6: ".", 7: "7"}))
    check(c, ClockMode=".", ClockMinutesTens="0", ClockSecondTens="0", ClockSecondOnes="9", ClockTenthsSecond="7")


def test_cg_hockey():
    pk = cg(50, {**CGCLK, 9: " 3", 11: " 1", 13: "1", 19: "2", 16: "5", 17: "6", 18: "7", 21: "17", 23: "0200",
                 35: "09", 37: "05 30"})
    p, c = run("DaktronicsAllSportsCG_Hockey", pk)
    check(c, HomeScoreOnes="3", GuestScoreOnes="1", HomeTimeOut="1", Period="2", HomeShotOnGoalOnes="5",
          HomeShotOnGoalTens="6", GuestShotOnGoalTens="7", HomePenaltyPlayer1Ones="7",
          HomePenaltyPlayer1ClockMinutesOnes="2", GuestPenaltyPlayer1Ones="9", GuestPenaltyPlayer1ClockSecondTens="3",
          EventId="Hockey")


def test_cg_volleyball():
    pk = cg(37, {**CGCLK, 8: "s", 9: "1513", 15: "*", 17: "21", 19: "2", 20: "3", 21: "25", 22: "21", 28: "1620"})
    p, c = run("DaktronicsAllSportsCG_Volleyball", pk)
    check(c, InternalClockStatus="S", HomeScoreTens="1", GuestScoreOnes="3", HomeServe="*", HomeGamesWon="2",
          GuestGamesWon="1", Game="2", Set="3", HomeScoreSet1="32", HomeScoreSet2="21", GuestScoreSet1="16")
    _, c = run("DaktronicsAllSportsCG_Volleyball", cg(37, {}))
    check(c, InternalClockStatus="R")


def test_cg_baseball():
    pk = cg(170, {3: " 4", 7: " 2", 9: " 1", 28: " 7", 31: "1", 34: " 5", 37: "0", 41: " 9", 48: "212",
                  109: "3", 163: "087", 51: "H"})
    p, c = run("DaktronicsAllSportsCG_Baseball", pk)
    check(c, HomeRunOnes="4", GuestRunOnes="2", InningOnes="1", HomeHitsOnes="7", HomeErrors="1",
          GuestHitsOnes="5", AtBatOnes="9", Balls="2", Strikes="1", Outs="2", ErrorFlag="H", GuestInning1="3", TopBottomInning="T", EventId="Baseball")
    # inning 1, guest has batted and home has not: "top"; pitch count comes from 163-165
    check(c, PitchCount="087")
    pk2 = cg(170, {9: " 1", 109: "3", 85: "0", 146: "123"})
    _, c2 = run("DaktronicsAllSportsCG_Baseball", pk2)
    check(c2, TopBottomInning="B", PitchCount="123")
    short = ds.PROTOCOLS["DaktronicsAllSportsCG_Baseball"]()
    short.feed(cg(120, {}))
    assert short.bad == 1 and short.packets == 0


def test_cg_wrestling():
    pk = cg(30, {**CGCLK, 8: "s", 9: "0702", 15: "03", 17: "2", 22: "1", 24: "30", 26: "x"})
    p, c = run("DaktronicsAllSportsCG_Wrestling", pk)
    check(c, ClockMode=":", InternalClockStatus="S", HomeScoreTens="0", HomeScoreOnes="7", GuestScoreOnes="2",
          GuestMatchScoreTens="0", GuestMatchScoreOnes="3", Period="2", AdvantageTimeMinutesOnes="1",
          AdvantageTimeSecondTens="3", AdvantageTimeSecondOnes="0", AdvantageHome="*", AdvantageGuest=" ",
          EventId="Wrestling")
    assert p.contract_name == "Wrestling"
    _, c = run("DaktronicsAllSportsCG_Wrestling", cg(30, {3: ".", 4: "45", 7: "6"}))
    check(c, ClockMode=".", ClockSecondTens="4", ClockTenthsSecond="6")


def test_cg_framing():
    pk = cg(32, {**CGCLK, 8: "S", 13: "105", 29: "3"})
    p, c = run("DaktronicsAllSportsCG_Basketball", b"xx" + pk + pk, chunk=5)
    check(c, HomeScoreHundreds="1", Period="3")
    assert p.packets == 2 and p.bad == 1  # the junk prefix is dropped (and counted), the frames decode
    p2 = ds.PROTOCOLS["DaktronicsAllSportsCG_Basketball"]()
    p2.feed(b"abc\x04")  # EOT without SOH
    assert p2.bad == 1 and p2.packets == 0
    p2.feed(b"\x01ab\x04")  # too short for the layout
    assert p2.bad == 2 and p2.packets == 0


# ------------------------------------------------------------------ Daktronics 4000 (V2 and PIC)
def clk(m="12", s="34"):
    return e(m + s[0]) + e(s[1])  # bytes 0-3: MM S then ones in byte 3


def payload(clock: str, rest: dict, n=16) -> bytes:
    """clock 'MMSS' (minutes shown) or 'SST ' (tenths mode); rest = {index: byte or str of digits}."""
    b = bytearray([255] * n)
    b[0:4] = e(clock)
    for i, v in rest.items():
        if isinstance(v, str):
            b[i : i + len(v)] = e(v)
        else:
            b[i] = v
    return bytes(b)


def v2(p16: bytes) -> bytes:
    return b"\xaa" + p16 + b"\xab"


def pic(p16: bytes) -> bytes:
    return make_frame(0xBD, p16)


PAIRS = [("Daktronics4000_%s", v2), ("PIC55AA_Daktronics4000_%s", pic)]


@pytest.mark.parametrize("tmpl,wrap", PAIRS)
def test_4000_football(tmpl, wrap):
    p, c = run(tmpl % "Football", wrap(payload("1234", {4: "21", 6: "14", 9: "2", 10: " 7", 12: "35", 14: "3"})))
    check(c, ClockMode=":", ClockMinutesTens="1", ClockMinutesOnes="2", ClockSecondTens="3", ClockSecondOnes="4",
          ClockTenthsSecond="0", HomeScoreTens="2", HomeScoreOnes="1", GuestScoreOnes="4", Down="2",
          ToGoTens=" ", ToGoOnes="7", BallOnTens="3", BallOnOnes="5", Quarter="3", EventId="Football")
    assert p.contract_name == "Football"


@pytest.mark.parametrize("tmpl,wrap", PAIRS)
def test_4000_football_code27(tmpl, wrap):
    _, c = run(tmpl % "Football_Code27", wrap(payload("1234", {6: "07", 8: "03", 10: "2", 12: 248, 13: "2", 14: "1"})))
    check(c, HomeScoreOnes="7", GuestScoreOnes="3", Quarter="2", HomePossession="<", GuestPossession=" ",
          HomeTimeouts="2", GuestTimeouts="1")
    _, c = run(tmpl % "Football_Code27", wrap(payload("1234", {12: 199})))
    check(c, HomePossession=" ", GuestPossession=">")


@pytest.mark.parametrize("tmpl,wrap", PAIRS)
def test_4000_hockey(tmpl, wrap):
    # tenths mode: the 4th clock byte is blank, so bytes 0-2 are SS.t
    p, c = run(tmpl % "Hockey", wrap(payload("59 7"[:2] + "7 ", {4: " 3", 6: " 1", 10: " 9", 12: "12", 15: "2"})))
    check(c, ClockMode=".", ClockMinutesTens="0", ClockSecondTens="5", ClockSecondOnes="9",
          ClockTenthsSecond="7", HomeScoreOnes="3", GuestScoreOnes="1", HomeShotOnGoalOnes="9",
          GuestShotOnGoalTens="1", Period="2", EventId="Hockey")
    assert p.contract_name == "HockeyLacrosse"


@pytest.mark.parametrize("tmpl,wrap,pid", [("Daktronics4000_%s", v2, "BaseballSoftball"),
                                           ("PIC55AA_Daktronics4000_%s", pic, "BaseballSoftball")])
def test_4000_baseball(tmpl, wrap, pid):
    b = bytearray([255] * 16)
    b[0:2] = e("12")
    b[2:5] = e("321")
    b[6:8] = e(" 5")
    b[10] = e("2")[0]
    b[11:13] = e("10")
    b[15] = e("1")[0]
    _, c = run(tmpl % pid, wrap(bytes(b)))
    check(c, AtBatTens="1", AtBatOnes="2", Balls="3", Strikes="2", Outs="1", GuestRunOnes="5", GuestErrors="2",
          HomeRunTens="1", HomeRunOnes="0", HomeErrors="1", EventId="Baseball")
    assert "ClockMode" not in c


@pytest.mark.parametrize("tmpl,wrap,pid", [("Daktronics4000_%s", v2, "Basketball_Code3"),
                                           ("Daktronics4000_%s", v2, "Basketball_Code4"),
                                           ("PIC55AA_Daktronics4000_%s", pic, "Basketball")])
def test_4000_basketball(tmpl, wrap, pid):
    # byte 9 bits clear = "1" lamps: 0xFC leaves only the home hundreds lamp lit
    p, c = run(tmpl % pid, wrap(payload("1234", {4: "05", 6: "99", 8: 0xC3, 9: 0xFC, 10: "4", 15: "2"})))
    check(c, HomeScoreHundreds="1", HomeScoreTens="0", HomeScoreOnes="5", GuestScoreHundreds=" ",
          GuestScoreTens="9", HomeFoulTens=" ", HomeFoulOnes="4", HomePossession="<", GuestPossession=">",
          HomeBonus="B", GuestBonus="B", Period="2", ShotClockSecondTens=" ", HomeTimeouts=" ")
    assert p.contract_name == "Basketball"


@pytest.mark.parametrize("tmpl,wrap", PAIRS)
def test_4000_volleyball(tmpl, wrap):
    _, c = run(tmpl % "Volleyball", wrap(payload("1234", {4: "15", 6: "13", 9: 0x01, 10: "2", 11: "1", 14: "3"})))
    check(c, HomeScoreTens="1", GuestScoreOnes="3", HomeServe=" ", GuestServe="*", HomeGamesWon="2",
          GuestGamesWon="1", Game="3", EventId="Volleyball")


@pytest.mark.parametrize("tmpl,wrap", PAIRS)
def test_4000_soccer(tmpl, wrap):
    p, c = run(tmpl % "Soccer", wrap(payload("1234", {4: "02", 6: "01", 8: 231, 11: "4", 13: "2"})))
    check(c, HomeScoreOnes="2", GuestScoreTens="0", GuestScoreOnes=" ", Period="2", HomeCornerKicks=" 4",
          GuestCornerKicks=" 2", HomeSaves="", EventId="Soccer")
    d = ds.PROTOCOLS["Daktronics4000_Soccer"]()
    d.decoder.blank_guest_score_ones = False
    d.feed(v2(payload("1234", {6: "01", 7: "7"})))
    check(d.decoder.c, GuestScoreOnes="7")


def test_4000_v2_framing():
    f = v2(payload("1234", {4: "21"}))
    p, c = run("Daktronics4000_Football", b"\x00\xaa\x05" + f + f, chunk=4)
    check(c, HomeScoreTens="2")
    assert p.packets == 2 and p.bad == 0 or p.packets == 2  # garbage with an AA header before the frame
    q = ds.PROTOCOLS["Daktronics4000_Football"]()
    q.feed(b"\xaa" + bytes(10) + b"\xab")  # wrong length
    assert q.bad == 1 and q.packets == 0
    q.feed(f[:9])
    assert q.packets == 0
    q.feed(f[9:])
    assert q.packets == 1


def test_4000_v2_data_byte_aa():
    f = v2(payload("1234", {9: 0xAA}))
    p, c = run("Daktronics4000_Basketball_Code3", f)
    assert p.packets == 1  # an 0xAA inside the data does not break the frame


def test_pic_framing_and_checksum():
    f = pic(payload("1234", {4: "21"}))
    p, c = run("PIC55AA_Daktronics4000_Football", b"\x00\x01" + f[:7], chunk=0)
    p.feed(f[7:])
    check(p.decoder.c, HomeScoreTens="2")
    bad = bytearray(f)
    bad[-1] ^= 0xFF
    q = ds.PROTOCOLS["PIC55AA_Daktronics4000_Football"]()
    q.feed(bytes(bad))
    assert q.bad == 1 and q.packets == 0
    q.feed(make_frame(0xB7, bytes(16)))  # a different PIC decode mode is not ours
    assert q.packets == 0


def test_short_4000_payload_is_ignored():
    p = ds.PROTOCOLS["PIC55AA_Daktronics4000_Football"]()
    p.feed(make_frame(0xBD, b"\x00\x01"))
    assert p.decoder.c == {"EventId": "Football"}


def test_all_ids_registered():
    ids = [k for k in ds.PROTOCOLS]
    assert len(ids) == 32
    for pid in ids:
        assert create(pid) is not None
