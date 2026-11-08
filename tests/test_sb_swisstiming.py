from scoreboards import swisstiming as st
from scoreboards.common import xor8


def main_frame(kind: str, body: bytes) -> bytes:
    f = b"\x02" + kind.encode() + body + b"\x03"
    return f + bytes([xor8(f)])


def d_record(**kw) -> bytes:
    b = bytearray(b" " * 23)  # indexes 2..24 of the frame
    for i, v in kw.items():
        b[int(i[1:]) - 2] = ord(v) if isinstance(v, str) else v
    return bytes(b)


def feed_all(proto, data):
    return proto.feed(data)


def basketball_d():
    return main_frame("D", d_record(i2="1", i3="2", i4=":", i5="3", i6="4", i7="1", i8="0", i9="5", i10="0", i11="9",
                                    i12="9", i13="3", i14="4", i15="2", i16="1", i17="3", i18="2", i20="1",
                                    i23="1", i24="4"))


def test_basketball_data():
    p = st.PROTOCOLS["SwissTiming_Basketball"]()
    assert p.feed(b"\xff\x10" + basketball_d()) == 1
    c = p.snapshot()
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "2", "3", "4")
    assert c["ClockMode"] == ":"
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "9", "9")
    assert c["Period"] == "3" and c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "1"
    assert c["HomeFoulOnes"] == "3" and c["GuestFoulOnes"] == "4"
    assert c["Horn"] == "H" and c["HomePossession"] == " " and c["GuestPossession"] == ">"
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("1", "4")
    assert p.contract_name == "Basketball" and c["EventId"] == "Basketball"


def test_names_and_split_feed_and_checksum_reject():
    p = st.PROTOCOLS["SwissTiming_Basketball"]()
    # names: home at 2..9, guest at 14..21 -> body index 0 is frame index 2
    body = b"HOMETEAM" + b"    " + b"VISITORS"
    names = main_frame("N", body)
    for i in range(len(names)):  # one byte at a time
        p.feed(names[i : i + 1])
    c = p.snapshot()
    assert c["HomeTeamName"] == "HOMETEAM" and c["GuestTeamName"] == "VISITORS"
    bad = bytearray(basketball_d())
    bad[-1] ^= 0xFF
    n = p.packets
    p.feed(bytes(bad))
    assert p.packets == n and p.bad >= 1


def test_leftover_checksum_byte_then_next_frame():
    p = st.PROTOCOLS["SwissTiming_Basketball"]()
    f = basketball_d()
    assert p.feed(f + f + f) == 3


def test_hockey_data_and_penalties():
    p = st.PROTOCOLS["SwissTiming_Hockey"]()
    b = bytearray(b" " * 16)  # frame indexes 2..17
    for i, v in {8: "1", 9: "2", 11: "0", 12: "7", 15: "2", 16: "1", 17: "2", 2: "0", 3: "1", 4: ":", 5: "5", 6: "9"}.items():
        b[i - 2] = ord(v)
    assert p.feed(b"junk" + main_frame("D", bytes(b))) == 1
    c = p.snapshot()
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "2", "0", "7")
    assert c["Period"] == "2" and c["HomeFullTimeoutsRemaining"] == "2" and c["GuestFullTimeoutsRemaining"] == "1"
    assert p.contract_name == "HockeyLacrosse" and c["EventId"] == "Hockey"
    pen = bytearray(b" " * 42)  # frame indexes 2..43
    pen[0:7] = b"1202:30"          # home player 1
    pen[7:14] = b"0701:15"         # home player 2
    pen[21:28] = b"2200:45"        # guest player 1
    assert p.feed(main_frame("O", bytes(pen))) == 1
    c = p.snapshot()
    assert (c["HomePenaltyPlayer1Tens"], c["HomePenaltyPlayer1Ones"]) == ("1", "2")
    assert (c["HomePenaltyPlayer1ClockMinutesTens"], c["HomePenaltyPlayer1ClockMinutesOnes"]) == ("0", "2")
    assert (c["HomePenaltyPlayer1ClockSecondTens"], c["HomePenaltyPlayer1ClockSecondOnes"]) == ("3", "0")
    assert c["HomePenaltyPlayer2Ones"] == "7" and c["HomePenaltyPlayer2ClockSecondOnes"] == "5"
    assert c["GuestPenaltyPlayer1Tens"] == "2" and c["GuestPenaltyPlayer1ClockSecondTens"] == "4"
    assert c["HomeShotOnGoalTens"] == " " and "GuestShotOnGoalOnes" not in c


def test_waterpolo_and_timeout_quirk():
    p = st.PROTOCOLS["SwissTiming_WaterPolo"]()
    def rec(to):
        b = bytearray(b" " * 23)
        for i, v in {4: ".", 2: "2", 3: "5", 5: "3", 8: "0", 9: "4", 11: "0", 12: "2", 17: "4", 15: to, 16: "2", 23: "2", 24: "8"}.items():
            b[i - 2] = ord(v)
        return main_frame("D", bytes(b))
    p.feed(rec("3"))
    c = p.snapshot()
    assert c["ClockMode"] == "." and c["ClockSecondTens"] == "2" and c["ClockTenthsSecond"] == "3"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["Period"]) == ("0", "4", "4")
    assert (c["ShotClockTens"], c["ShotClockOnes"]) == ("2", "8")
    assert c["HomeTimeouts"] == "3"
    p.feed(rec("2"))  # a drop of exactly one is ignored
    assert p.snapshot()["HomeTimeouts"] == "3"
    p.feed(rec("1"))
    assert p.snapshot()["HomeTimeouts"] == "1"
    assert p.contract_name == "WaterPolo"


def tx(text: str) -> bytes:
    return b"\x01" + text.encode() + b"\x04"


def rec(rid, *vals):
    return tx("4|6|%d|0|" % rid + "|".join(vals))


def test_transmission_basketball():
    p = st.PROTOCOLS["SwissTimmingTransmission_Basketball"]()
    stream = b"\x07\x07" + rec(1, "87", "102", "", "") + rec(2, "5", "12", "1", "0", "", "")
    stream += rec(3, "2", "3", "") + rec(4, "3", "2", "", "") + rec(7, "1") + rec(30, "7:05", "", "", "", "", "0", "0")
    stream += rec(31, "12", "", "", "1")
    assert p.feed(stream[:30]) <= 1
    p.feed(stream[30:])
    c = p.snapshot()
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == (" ", "8", "7")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("1", "0", "2")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulTens"], c["GuestFoulOnes"]) == (" ", "5", "1", "2")
    assert c["HomeBonus"] == "B" and c["GuestBonus"] == " "
    assert c["HomeTimeouts"] == "2" and c["GuestTimeouts"] == "3" and c["Period"] == "2" and c["Horn"] == "H"
    assert c["ClockMode"] == ":" and (c["ClockMinutesTens"], c["ClockMinutesOnes"]) == (" ", "7")
    assert (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("0", "5")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("1", "2") and c["PlayClockStatusInternal"] == "R"
    p.feed(rec(4, "4", "x", "", ""))
    assert p.snapshot()["Period"] == "5"
    p.feed(rec(31, "9.4", "", "", "0"))
    c = p.snapshot()
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"], c["ShotClockTenthsSecond"]) == (" ", "9", "4")
    assert c["PlayClockStatusInternal"] == "S"
    p.feed(rec(30, "9.7", "", "", "", "", "0", "0"))
    c = p.snapshot()
    assert c["ClockMode"] == "." and c["ClockSecondOnes"] == "9" and c["ClockTenthsSecond"] == "7"


def test_transmission_rejects_garbage_without_soh():
    p = st.PROTOCOLS["SwissTimmingTransmission_Basketball"]()
    assert p.feed(b"abc\x04") == 0 and p.bad == 1
    assert p.feed(b"\x01nonsense\x04") == 1  # decoded but ignored
    assert p.snapshot() == {"EventId": "Basketball"}


def swim(sub: str, rec_: str, tail: str, cls: int = 19) -> bytes:
    return b"\x01" + bytes([cls]) + b"\x00\x00\x00\x00" + sub.encode() + rec_.encode() + tail.encode() + b"\x04"


def test_swimming():
    p = st.PROTOCOLS["SwissTimingTransmission_Swimming"]()
    p.feed(b"xx" + swim("00", "00", "200 FREE MEN"))
    c = p.snapshot()
    assert c["PacketType"] == "Event" and c["SwimmingEvent"]["EventName"] == "200 FREE MEN"
    p.feed(swim("00", "01", "REC 1:50.00"))
    assert p.snapshot()["SwimmingEvent"]["EventRecord"] == "REC 1:50.00"
    p.feed(swim("20", "01", "01:23.45"))
    c = p.snapshot()
    assert c["PacketType"] == "Rows"
    r = c["SwimmingRows"]
    assert (r["ClockMinutesTens"], r["ClockSecondOnes"], r["ClockTenthsSecond"], r["ClockHundreths"]) == ("0", "3", "4", "5")
    assert c["SwimmingEvent"]["ClockMinutesOnes"] == "1"
    lane = "05 " + "SMITH JOHN".ljust(16) + " " + "ABCD" + " " + "1:23.45".ljust(8) + " " + "02"
    p.feed(swim("00", "02", lane))
    r = p.snapshot()["SwimmingRows"]
    assert r["RowType"] == "Row4To6" and r["RowANumber"] == 4
    assert r["RowBLane"] == "05" and r["RowBSwimmerName"] == "SMITH JOHN      "
    assert r["RowBTeamName"] == "ABCD" and r["RowBClock"] == "1:23.45 " and r["RowBPlace"] == "02"
    p.feed(b"\x01\x02\x0c\x04")
    c = p.snapshot()
    assert c["SwimmingRows"] == {"EventId": "SwissTiming"} and c["PacketType"] == "Rows"
    assert p.contract_name == "SwimmingMixed"
