import pytest

from scoreboards import sportzcast


def pkt(code, fields=None, text=None):
    """150-character sbdata packet: code in 0-1, then {offset: chars}."""
    b = bytearray(b" " * 150)
    b[0:2] = code.encode()
    for off, s in (fields or {}).items():
        b[off:off + len(s)] = s.encode()
    return bytes(b) + b"\n"


def run(pid, data):
    p = sportzcast.PROTOCOLS[pid]()
    p.feed(data)
    return p


def test_all_ids_registered():
    assert len(sportzcast.PROTOCOLS) == 18
    for f in sportzcast.PROTOCOLS.values():
        f()


def test_football():
    p = run("SportzcastSBData_Football", pkt("02", {2: "1234", 8: "25", 11: "21", 14: "07", 16: "<", 20: "3",
                                                  25: "2", 26: "HOMETEAM", 116: "R", 117: ":"}))
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockSecondOnes"], c["InternalClockStatus"]) == ("1", "4", "R")
    assert c["HomeScoreTens"] + c["HomeScoreOnes"] == "21" and c["GuestScoreOnes"] == "7"
    assert c["HomePossession"] == "<" and c["Down"] == "3" and c["HomeTeamName"] == "HOMETEAM"
    assert c["PlayClockTens"] == "2" and p.decoder.contract == "Football" and c["EventId"] == "Football"


def test_tenths_clock_mode():
    p = run("SportzcastSBData_Football", pkt("02", {2: "593", 117: "."}))
    c = p.snapshot()
    assert (c["ClockMode"], c["ClockMinutesTens"], c["ClockSecondTens"], c["ClockTenthsSecond"]) == (".", "0", "5", "3")


def test_soccer():
    p = run("SportzcastSBData_Soccer", pkt("08", {11: "03", 14: "11", 19: "4", 47: "1", 48: "2", 22: "5",
                                                 23: "09", 29: "2", 49: "01"}))
    c = p.snapshot()
    assert c["HomeScoreOnes"] == "3" and c["GuestScoreTens"] == "1" and c["HomeCornerKicks"] == "14"
    assert c["GuestCornerKicks"] == "25" and c["HomeSaves"] == "09" and c["Period"] == "2"
    assert c["HomePenalties"] == "01"


def test_basketball():
    p = run("SportzcastSBData_Basketball", pkt("03", {10: "112", 13: "098", 47: "23", 49: "4", 50: "17",
                                                    121: "99", 129: "05", 30: "H"}))
    c = p.snapshot()
    assert c["HomeScoreHundreds"] == "1" and c["GuestScoreOnes"] == "8" and c["HomePlayer1"] == "23"
    assert c["HomePlayer1Points"] == "17" and c["GuestPlayer4"] == "99" and c["GuestPlayer5Points"] == "05"


def test_baseball_and_softball():
    d = pkt("01", {6: "2", 7: "1", 8: "0", 9: " ", 10: "7", 15: "T", 30: "3", 31: "1", 50: "VISITORS",
                   66: "1", 69: "078"})
    c = run("SportzcastSBData_Baseball", d).snapshot()
    assert c["Balls"] == "2" and c["InningOnes"] == "7" and c["GuestInning1"] == "3" and c["HomeInning1"] == "1"
    assert c["GuestTeamName"] == "VISITORS" and c["OnFirst"] == "1" and c["PitchSpeed"] == "078"
    p = run("SportzcastSBData_Softball", d)
    assert p.decoder.event == "Softball" and p.decoder.contract == "BaseballSoftball"


def test_hockey_lacrosse():
    d = pkt("05", {11: "02", 14: "01", 29: "3", 47: "17", 49: "02", 51: "00", 65: "88", 119: "AB", 125: "CD"})
    p = run("SportzcastSBData_Hockey", d)
    c = p.snapshot()
    assert c["HomeScoreOnes"] == "2" and c["HomePenaltyPlayer1Ones"] == "7"
    assert c["HomePenaltyPlayer1ClockMinutesOnes"] == "2" and c["GuestPenaltyPlayer1Tens"] == "8"
    assert c["HomePlayer1PenaltyType1"] == "A" and c["GuestPlayer1PenaltyType2"] == "D"
    assert run("SportzcastSBData_Lacrosse", d).decoder.event == "Lacrosse"


def test_futsal_handball():
    d = pkt("29", {11: "05", 13: "04", 19: "2", 47: "09", 65: "10"})
    p = run("SportzcastSBData_Futsal", d)
    c = p.snapshot()
    assert c["HomeScoreOnes"] == "5" and c["GuestScoreOnes"] == "4" and c["Period"] == "2"
    assert c["HomePenaltyPlayer1Ones"] == "9" and c["GuestPenaltyPlayer1Tens"] == "1"
    assert p.decoder.contract == "FutsalHandball"
    assert run("SportzcastSBData_Handball", d).decoder.event == "Handball"


def test_volleyball():
    p = run("SportzcastSBData_Volleyball", pkt("06", {6: "2", 7: "2", 8: "5", 16: "25", 18: "20", 102: "15",
                                                     48: "07", 50: "3", 51: "12", 126: "44", 128: "1"}))
    c = p.snapshot()
    assert c["HomeGamesWon"] == "2" and c["HomeScoreOnes"] == "5" and c["HomeScoreSet1"] == "25"
    assert c["GuestScoreSet1"] == "20" and c["HomeScoreSet5"] == "15" and c["HomePlayer1Digs"] == "12"
    assert c["GuestPlayer6"] == "44" and c["GuestPlayer6Kills"] == "1"


def test_wrestling_swimming_tennis_waterpolo_tabletennis():
    c = run("SportzcastSBData_Wrestling", pkt("12", {2: "0145", 6: "0", 8: "123", 11: "04", 19: "152",
                                                    116: "R", 117: ":"})).snapshot()
    assert c["ClockMinutesOnes"] == "1" and c["HomeMatchHundreds"] == "1" and c["WeightClass"] == "152"
    assert c["InternalClockStatus"] == "R"
    c = run("SportzcastSBData_Swimming", pkt("13", {2: "01234", 7: "F", 10: "1", 11: "01:02.34", 84: "F",
                                                   87: "3"})).snapshot()
    assert c["FinishFlag1"] == "F" and c["Place1"] == "1" and c["Clock1"] == "01:02.3" and c["Place8"] == "3"
    c = run("SportzcastSBData_Tennis", pkt("16", {2: "1230", 6: "2", 7: "40", 9: "15", 11: "6", 86: "1",
                                                 31: "ALPHA"})).snapshot()
    assert c["ClockHourOnes"] == "2" and c["TopPoints"] == "40" and c["TopSet1Ones"] == "6"
    assert c["TopSet1Tens"] == "1" and c["TopPlayerName"].startswith("ALPHA")
    c = run("SportzcastSBData_Waterpolo", pkt("24", {2: "07", 5: "30", 8: "5", 12: "2", 17: "05", 20: "06",
                                                    39: "12", 116: "S", 117: ":"})).snapshot()
    assert c["ClockMinutesOnes"] == "7" and c["ClockSecondTens"] == "3" and c["GuestScoreOnes"] == "5"
    assert c["HomeScoreOnes"] == "6" and c["HomePenaltyPlayer1Ones"] == "2"
    c = run("SportzcastSBData_TableTennis", pkt("31", {6: "3", 7: "11", 9: "09", 15: "11", 17: "05"})).snapshot()
    assert c["HomePoints"] == "11" and c["GuestPoints"] == "09" and c["HomePointsSet1"] == "11"
    p = run("SportzcastSBData_Badminton", pkt("32", {7: "21"}))
    assert p.decoder.event == "Badminton" and p.snapshot()["HomePoints"] == "21 "[:2]


def test_autodetect_switches():
    p = run("SportzcastSBData_Autodetect", pkt("02", {11: "21"}))
    assert p.decoder.contract == "Football" and p.snapshot()["HomeScoreTens"] == "2"
    p.feed(pkt("08", {11: "03"}))
    assert p.decoder.contract == "Soccer" and p.snapshot()["HomeScoreOnes"] == "3"
    assert "PlayClockTens" not in p.snapshot()
    p.feed(pkt("99"))  # unknown code keeps the current layout
    assert p.decoder.contract == "Soccer"
    p.feed(pkt("28", {2: "1", 9: "123"}))
    assert p.decoder.contract == "Generic" and p.snapshot()["HomeHundreds"] == "1"


def test_autodetect_raw_codes():
    p = sportzcast.PROTOCOLS["SportzcastSBData_Autodetect"]()
    b = bytearray(pkt("02"))
    b[0], b[1] = 0, 2
    p.feed(bytes(b))
    assert p.decoder.contract == "Football"


def test_virtualbot_locks_on_first_packet():
    p = run("Sportzcast_VirtualBot", pkt("03", {12: "9"}))
    assert p.decoder.contract == "Basketball" and p.snapshot()["HomeScoreOnes"] == "9"
    p.feed(pkt("02", {11: "21"}))
    assert p.decoder.contract == "Basketball"
    q = run("Sportzcast_VirtualBot", pkt("31"))  # table tennis is not a virtual-bot sport
    assert q.packets == 0 and q.bad == 1


def test_garbage_split_and_length_rejection():
    pid = "SportzcastSBData_Football"
    good = pkt("02", {11: "21"})
    p = sportzcast.PROTOCOLS[pid]()
    p.feed(b"garbage\n" + good[:70])
    assert p.packets == 0 and p.bad == 1
    p.feed(good[70:])
    assert p.packets == 1 and p.snapshot()["HomeScoreTens"] == "2"
    p.feed(good[:-2] + b"\n")  # 149 characters
    assert p.packets == 1 and p.bad == 2
    p.feed(b"x" * 151 + b"\n")
    assert p.bad == 3


def test_clock_status_only_updates_for_r_or_s():
    p = run("SportzcastSBData_Football", pkt("02", {116: "r"}))
    assert p.snapshot()["InternalClockStatus"] == "R"
    p.feed(pkt("02", {116: "x"}))
    assert p.snapshot()["InternalClockStatus"] == "R"


@pytest.mark.parametrize("pid", sorted(sportzcast.PROTOCOLS))
def test_every_id_decodes_a_blank_packet(pid):
    code = {"Autodetect": "02", "Badminton": "32", "Baseball": "01", "Basketball": "03", "Football": "02",
            "Futsal": "29", "Handball": "30", "Hockey": "05", "Lacrosse": "07", "Soccer": "08",
            "Softball": "04", "Swimming": "13", "TableTennis": "31", "Tennis": "16", "Volleyball": "06",
            "Waterpolo": "24", "Wrestling": "12", "VirtualBot": "02"}[pid.split("_")[1]]
    p = run(pid, pkt(code))
    assert p.packets == 1 and p.snapshot()
