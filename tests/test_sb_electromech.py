import scoreboards
from scoreboards import electromech
from scoreboards.common import SEG7

SEG = {ch: b for b, ch in SEG7.items() if ch != "9" or b == 0x6F}
SEG[" "] = 0x00


def cell(addr, value, flag=0):
    """One Electro-Mech cell: data byte (bit7 clear) then address byte (bit7 set)."""
    a = (value & 0x70) | (value & 0x0F)
    b = 0x80 | (addr << 2) | (2 if flag else 0) | ((value >> 7) & 1)
    return bytes([a, b])


def bcdv(hi, lo):
    return (hi << 4) | lo


def run(pid, *cells):
    p = electromech.PROTOCOLS[pid]()
    p.feed(b"".join(cells))
    return p, p.snapshot()


def test_all_ids_registered_and_discoverable():
    ids = {"Electromech_" + n for n in (
        "Baseball", "BaseballSoftball14x15x", "Basketball", "Basketball_SwappedTeams", "Football", "Hockey",
        "LineScoreBaseball", "LxBaseball", "LxHockey", "LxLacrosse", "LxSoccer", "Soccer", "Softball", "Volleyball")}
    assert set(electromech.PROTOCOLS) == ids
    assert ids <= set(scoreboards.protocols())


# ---------------------------------------------------------------- framing
def test_cell_decoding_with_garbage_split_and_orphan():
    p = electromech.PROTOCOLS["Electromech_Football"]()
    c = cell(8, bcdv(2, 1))
    p.feed(b"\x12\x05\x7f" + c[:1])      # data bytes of garbage, then half a cell
    assert p.packets == 0
    p.feed(c[1:])                         # terminator arrives in the next chunk
    assert p.packets == 1 and p.snapshot()["HomeScoreOnes"] == "1"
    p.feed(b"\x85")                       # terminator with no data byte before it
    assert p.bad == 1 and p.packets == 1
    p.feed(cell(9, bcdv(0, 7)))
    assert p.snapshot()["GuestScoreTens"] == " " and p.snapshot()["GuestScoreOnes"] == "7"


def test_unknown_address_and_event_fields():
    p, c = run("Electromech_Football", cell(31, 0x12))
    assert c == {"EventId": "Football"}
    assert p.contract_name == "Football"


# ---------------------------------------------------------------- football
def test_football():
    p, c = run("Electromech_Football",
               cell(2, SEG["2"], flag=1),               # quarter 2, mm:ss clock
               cell(1, bcdv(1, 2)), cell(0, bcdv(3, 4)),
               cell(8, bcdv(1, 4), flag=1),            # home 14 with possession
               cell(9, bcdv(0, 7)),
               cell(16, bcdv(2, 3)),
               cell(12, bcdv(0, 8)), cell(13, bcdv(3, 5)), cell(14, SEG["3"]))
    assert c["Quarter"] == "2" and c["ClockMode"] == ":"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "2", "3", "4")
    assert c["ClockTenthsSecond"] == "0"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["HomePossession"]) == ("1", "4", "<")
    assert (c["GuestScoreTens"], c["GuestScoreOnes"], c["GuestPossession"]) == (" ", "7", " ")
    assert (c["GuestTimeouts"], c["HomeTimeouts"]) == ("2", "3")
    assert (c["ToGoTens"], c["ToGoOnes"], c["BallOnTens"], c["BallOnOnes"], c["Down"]) == (" ", "8", "3", "5", "3")
    # guest possession arrow takes it back
    c = run("Electromech_Football", cell(8, 0x00, flag=1), cell(9, 0x00, flag=1))[1]
    assert (c["HomePossession"], c["GuestPossession"]) == (" ", ">")


def test_football_tenths_mode_and_bcd_blank():
    _, c = run("Electromech_Football", cell(2, SEG["1"], flag=0), cell(1, bcdv(0, 5)), cell(0, bcdv(7, 0)))
    assert c["ClockMode"] == "." and c["ClockMinutesOnes"] == "0"
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == (" ", "5", "7")
    _, c = run("Electromech_Football", cell(8, bcdv(0xF, 3)))
    assert c["HomeScoreTens"] == " " and c["HomeScoreOnes"] == "3"


def test_clock_rollover_correction():
    p = electromech.PROTOCOLS["Electromech_Football"]()
    feed = lambda *cs: p.feed(b"".join(cs))
    feed(cell(2, SEG["1"], 1), cell(1, bcdv(0, 5)))
    for sec in (3, 2, 1, 0):                       # a few ticks so the clock counts as running
        feed(cell(0, bcdv(0, sec)))
    feed(cell(1, bcdv(0, 4)))                      # minutes cell lands before the seconds cell: 04:00 -> 04:59
    c = p.snapshot()
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("4", "5", "9")
    feed(cell(0, bcdv(5, 9)))
    c = p.snapshot()
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("4", "5", "9")


# ---------------------------------------------------------------- basketball
def basketball_cells():
    return [cell(2, SEG["3"], flag=1), cell(1, bcdv(0, 6)), cell(0, bcdv(1, 5)),
            cell(4, bcdv(2, 4)),
            cell(8, bcdv(0, 5), flag=1),   # first team 105
            cell(9, bcdv(7, 2)),           # second team 72
            cell(15, SEG["2"]), cell(11, SEG["4"]),
            cell(10, 0b0101),              # bit0 = first-slot possession, bit2 = first-slot bonus
            cell(12, bcdv(3, 6), flag=1),
            cell(13, bcdv(2, 3)), cell(14, SEG["4"])]


def test_basketball():
    p, c = run("Electromech_Basketball", *basketball_cells())
    assert (c["Period"], c["ClockMode"]) == ("3", ":")
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == (" ", "6", "1", "5")
    assert (c["ShotClockSecondTens"], c["ShotClockSecondOnes"]) == ("2", "4")
    assert (c["HomeScoreHundreds"], c["HomeScoreTens"], c["HomeScoreOnes"]) == ("1", "0", "5")
    assert (c["GuestScoreHundreds"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "7", "2")
    assert (c["HomeTimeouts"], c["GuestTimeouts"]) == ("2", "4")
    assert (c["HomePossession"], c["GuestPossession"], c["HomeBonus"], c["GuestBonus"]) == ("<", " ", "B", " ")
    assert (c["HomeFoulTens"], c["HomeFoulOnes"], c["GuestFoulOnes"], c["GuestFoulTens"]) == ("1", "6", "3", " ")
    assert (c["FoulPlayerTens"], c["FoulPlayerOnes"], c["FoulPlayerNumberOfFouls"]) == ("2", "3", "4")
    assert p.contract_name == "Basketball" and c["EventId"] == "Basketball"


def test_basketball_swapped_teams_is_mirror_image():
    _, normal = run("Electromech_Basketball", *basketball_cells())
    p, swapped = run("Electromech_Basketball_SwappedTeams", *basketball_cells())
    mirror = {"Home": "Guest", "Guest": "Home"}
    for k, v in normal.items():
        team = k[:4] if k[:4] == "Home" else k[:5] if k[:5] == "Guest" else ""
        if not team:
            assert swapped[k] == v, k
            continue
        other = mirror[team] + k[len(team):]
        if k.endswith("Possession"):  # the arrow follows the team it points at
            v = {"<": ">", ">": "<"}.get(v, v)
        assert swapped[other] == v, k
    assert (swapped["GuestScoreHundreds"], swapped["HomeScoreTens"], swapped["HomeTimeouts"]) == ("1", "7", "4")
    assert (swapped["GuestPossession"], swapped["HomePossession"], swapped["GuestBonus"], swapped["HomeBonus"]) == (">", " ", "B", " ")
    assert p.contract_name == "Basketball"


# ---------------------------------------------------------------- soccer
def test_soccer():
    p, c = run("Electromech_Soccer",
               cell(2, SEG["2"], flag=1), cell(1, bcdv(3, 7)), cell(0, bcdv(1, 2)),
               cell(8, bcdv(0, 3)), cell(9, bcdv(1, 0)), cell(12, bcdv(0, 9)), cell(13, bcdv(1, 2)),
               cell(4, bcdv(4, 5)))
    assert c["Period"] == "2"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"]) == ("3", "7")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "3", "1", "0")
    assert (c["HomeShotTens"], c["HomeShotOnes"], c["GuestShotTens"], c["GuestShotOnes"]) == (" ", "9", "1", "2")
    assert (c["ClockSecondTens"], c["ClockSecondOnes"]) == ("4", "5")  # address 4 overwrites seconds (quirk)
    assert p.contract_name == "Soccer"


def test_lx_soccer():
    _, c = run("Electromech_LxSoccer", cell(31, SEG["1"]), cell(21, bcdv(3, 0)), cell(20, bcdv(4, 5)),
               cell(25, bcdv(0, 2)), cell(24, bcdv(0, 1)))
    assert c["Period"] == "1" and c["ClockMode"] == ":"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("4", "5", "3", "0")
    assert (c["HomeScoreOnes"], c["GuestScoreOnes"]) == ("2", "1")
    # low nibble blank (A-F) selects seconds.tenths mode
    _, c = run("Electromech_LxSoccer", cell(31, SEG["1"]), cell(21, bcdv(5, 0xF)), cell(20, bcdv(1, 2)))
    assert c["ClockMode"] == "." and c["ClockTenthsSecond"] == "5"


# ---------------------------------------------------------------- hockey / lacrosse
def test_hockey():
    p, c = run("Electromech_Hockey",
               cell(2, SEG["2"], flag=1), cell(1, bcdv(1, 4)), cell(0, bcdv(5, 9)),
               cell(4, bcdv(2, 5)), cell(8, bcdv(0, 3)), cell(9, bcdv(1, 1)),
               cell(11, SEG["1"]), cell(10, SEG["2"]), cell(15, SEG["3"]), cell(3, SEG["4"]),
               cell(12, bcdv(3, 0)), cell(13, bcdv(1, 8)), cell(14, SEG["1"]),
               cell(16, bcdv(4, 5), flag=1), cell(17, bcdv(2, 9), flag=1), cell(18, SEG["2"]),
               cell(24, bcdv(1, 5)), cell(25, bcdv(2, 7)), cell(26, SEG["7"]),
               cell(28, bcdv(0, 1)), cell(29, bcdv(3, 4)), cell(30, SEG["8"]))
    assert (c["Period"], c["ClockMode"]) == ("2", ":")
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == ("1", "4", "5", "9", "0")
    assert (c["ShotClockTens"], c["ShotClockOnes"]) == ("2", "5")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("0", "3", "1", "1")
    assert (c["GuestShotOnGoalTens"], c["GuestShotOnGoalOnes"], c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"]) == ("1", "2", "3", "4")
    assert (c["GuestPenaltyPlayer1ClockSecondTens"], c["GuestPenaltyPlayer1ClockSecondOnes"]) == ("3", "0")
    assert (c["GuestPenaltyPlayer1ClockMinutesTens"], c["GuestPenaltyPlayer1ClockMinutesOnes"], c["GuestPenaltyPlayer1Ones"], c["GuestPenaltyPlayer1Tens"]) == (" ", "8", "1", "1")
    assert (c["GuestPenaltyPlayer2ClockSecondTens"], c["GuestPenaltyPlayer2ClockSecondOnes"], c["HomeGoal"]) == ("4", "5", "G")
    assert (c["GuestPenaltyPlayer2ClockMinutesOnes"], c["GuestPenaltyPlayer2Ones"], c["GuestGoal"], c["GuestPenaltyPlayer2Tens"]) == ("9", "2", "G", "2")
    assert (c["HomePenaltyPlayer1ClockSecondTens"], c["HomePenaltyPlayer1ClockSecondOnes"], c["HomePenaltyPlayer1ClockMinutesOnes"], c["HomePenaltyPlayer1Ones"], c["HomePenaltyPlayer1Tens"]) == ("1", "5", "7", "2", "7")
    assert (c["HomePenaltyPlayer2ClockSecondOnes"], c["HomePenaltyPlayer2ClockMinutesOnes"], c["HomePenaltyPlayer2Ones"], c["HomePenaltyPlayer2Tens"]) == ("1", "4", "3", "8")
    assert p.contract_name == "HockeyLacrosse" and c["EventId"] == "Hockey"


def test_hockey_tenths_mode():
    _, c = run("Electromech_Hockey", cell(2, SEG["3"], flag=0), cell(1, bcdv(4, 2)), cell(0, bcdv(7, 0)))
    assert c["ClockMode"] == "." and (c["ClockMinutesTens"], c["ClockMinutesOnes"]) == ("0", "0")
    assert (c["ClockSecondTens"], c["ClockSecondOnes"], c["ClockTenthsSecond"]) == ("4", "2", "7")


def lx_hockey_cells():
    return [cell(31, SEG["3"]), cell(20, bcdv(1, 2)), cell(21, bcdv(3, 4)),
            cell(24, bcdv(0, 2)), cell(25, bcdv(1, 0)), cell(4, bcdv(3, 0)),
            cell(16, bcdv(1, 8), flag=1), cell(17, bcdv(2, 4)),
            cell(0, bcdv(1, 7)), cell(1, bcdv(4, 5)), cell(2, SEG["2"]),
            cell(12, bcdv(0, 9)), cell(13, bcdv(2, 1)), cell(14, SEG["1"]),
            cell(8, bcdv(2, 3)), cell(9, bcdv(5, 9)), cell(10, bcdv(0, 1)),
            cell(26, SEG["4"]), cell(27, SEG["5"]), cell(3, SEG["6"]), cell(11, SEG["7"]), cell(15, SEG["1"])]


def check_lx_hockey(c, event):
    assert c["EventId"] == event and c["Period"] == "3" and c["ClockMode"] == ":"
    assert (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "2", "3", "4")
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == (" ", "2", "1", "0")
    assert (c["ShotClockTens"], c["ShotClockOnes"]) == ("3", "0")
    assert (c["HomeShotOnGoalTens"], c["HomeShotOnGoalOnes"], c["HomeGoal"], c["GuestGoal"]) == ("1", "8", "G", " ")
    assert (c["GuestShotOnGoalTens"], c["GuestShotOnGoalOnes"]) == ("2", "4")
    assert (c["GuestPenaltyPlayer1Tens"], c["GuestPenaltyPlayer1Ones"], c["GuestPenaltyPlayer1ClockSecondTens"],
            c["GuestPenaltyPlayer1ClockSecondOnes"], c["GuestPenaltyPlayer1ClockMinutesOnes"]) == ("1", "7", "4", "5", "2")
    assert (c["GuestPenaltyPlayer2Tens"], c["GuestPenaltyPlayer2Ones"], c["GuestPenaltyPlayer2ClockSecondTens"],
            c["GuestPenaltyPlayer2ClockSecondOnes"], c["GuestPenaltyPlayer2ClockMinutesOnes"]) == ("0", "9", "2", "1", "1")
    assert (c["HomePenaltyPlayer1Tens"], c["HomePenaltyPlayer1Ones"], c["HomePenaltyPlayer1ClockSecondTens"],
            c["HomePenaltyPlayer1ClockSecondOnes"], c["HomePenaltyPlayer1ClockMinutesTens"], c["HomePenaltyPlayer1ClockMinutesOnes"]) == ("2", "3", "5", "9", "0", "1")
    assert (c["HomePenaltyPlayer2Tens"], c["HomePenaltyPlayer2Ones"], c["HomePenaltyPlayer2ClockSecondTens"],
            c["HomePenaltyPlayer2ClockSecondOnes"], c["HomePenaltyPlayer2ClockMinutesOnes"]) == ("4", "5", "6", "7", "1")


def test_lx_hockey_and_lacrosse():
    p, c = run("Electromech_LxHockey", *lx_hockey_cells())
    check_lx_hockey(c, "Hockey")
    assert p.contract_name == "HockeyLacrosse"
    _, c = run("Electromech_LxLacrosse", *lx_hockey_cells())
    check_lx_hockey(c, "Lacrosse")


def test_lx_hockey_tenths_mode():
    _, c = run("Electromech_LxHockey", cell(21, bcdv(5, 0xF)), cell(20, bcdv(4, 2)))
    assert c["ClockMode"] == "." and c["ClockTenthsSecond"] == "5"
    assert (c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("0", "4", "2")


# ---------------------------------------------------------------- volleyball
def test_volleyball():
    p, c = run("Electromech_Volleyball",
               cell(2, 0, flag=1), cell(1, bcdv(1, 0)), cell(0, bcdv(3, 0)),
               cell(8, bcdv(2, 1)), cell(9, bcdv(0, 9)), cell(15, SEG["1"]), cell(11, SEG["2"]),
               cell(12, bcdv(1, 2)), cell(13, bcdv(0xA, 3)))
    assert c["ClockMode"] == ":" and (c["ClockMinutesTens"], c["ClockMinutesOnes"], c["ClockSecondTens"], c["ClockSecondOnes"]) == ("1", "0", "3", "0")
    assert c["ClockTenthsSecond"] == "0"
    assert (c["HomeScoreTens"], c["HomeScoreOnes"], c["GuestScoreTens"], c["GuestScoreOnes"]) == ("2", "1", " ", "9")
    assert (c["HomeTimeout"], c["GuestTimeout"]) == ("1", "2")
    assert (c["HomeGamesWon"], c["GuestGamesWon"], c["Game"]) == ("2", "1", "3")
    assert p.contract_name == "Volleyball"


# ---------------------------------------------------------------- baseball / softball
def check_diamond(pid, home_runs, guest_runs, inn, bs, outs, event):
    p, c = run(pid, cell(*home_runs), cell(*guest_runs), cell(*inn), cell(*bs), cell(*outs))
    assert p.contract_name == "BaseballSoftball" and c["EventId"] == event
    return c


def test_baseball_and_softball():
    for pid, event in (("Electromech_Baseball", "Baseball"), ("Electromech_Softball", "Softball")):
        c = check_diamond(pid, (4, bcdv(1, 2)), (5, bcdv(0, 3), 1), (6, SEG["4"]), (12, bcdv(2, 1)), (13, bcdv(0, 1)), event)
        assert (c["HomeRunTens"], c["HomeRunOnes"], c["InningTens"]) == ("1", "2", " ")
        assert (c["GuestRunTens"], c["GuestRunOnes"], c["ErrorFlag"]) == (" ", "3", "E")
        assert (c["InningOnes"], c["TopBottomInning"]) == ("4", "T")
        assert (c["Balls"], c["Strikes"], c["Outs"]) == ("1", "2", "1")


def test_baseball_flips_to_bottom_when_outs_reset():
    p = electromech.PROTOCOLS["Electromech_Baseball"]()
    p.feed(cell(6, SEG["2"]) + cell(13, bcdv(0, 2)))
    assert p.snapshot()["TopBottomInning"] == "T" and p.snapshot()["Outs"] == "2"
    p.feed(cell(13, bcdv(0, 0)))
    assert p.snapshot()["TopBottomInning"] == "B" and p.snapshot()["Outs"] == "0"
    p.feed(cell(6, SEG["3"]))
    assert p.snapshot()["TopBottomInning"] == "T"


def test_lx_baseball():
    c = check_diamond("Electromech_LxBaseball", (8, bcdv(0, 7)), (9, bcdv(1, 0)), (10, SEG["9"]), (12, bcdv(3, 2)), (13, bcdv(0, 2)), "Baseball")
    assert (c["HomeRunTens"], c["HomeRunOnes"], c["GuestRunTens"], c["GuestRunOnes"]) == (" ", "7", "1", "0")
    assert (c["InningOnes"], c["Balls"], c["Strikes"], c["Outs"], c["ErrorFlag"]) == ("9", "2", "3", "2", " ")


def test_baseball_14x15x():
    p, c = run("Electromech_BaseballSoftball14x15x",
               cell(12, bcdv(0, 5)), cell(13, bcdv(1, 1)), cell(8, bcdv(1, 0)), cell(9, bcdv(0, 8)),
               cell(10, SEG["1"]), cell(14, SEG["2"]), cell(5, bcdv(1, 3)), cell(4, bcdv(1, 2)),
               cell(16, bcdv(0, 3)), cell(6, SEG["2"]))
    assert p.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert (c["HomeRunTens"], c["HomeRunOnes"], c["HomeHitsTens"], c["HomeHitsOnes"]) == (" ", "5", "1", "1")
    assert (c["GuestRunTens"], c["GuestRunOnes"], c["GuestHitsTens"], c["GuestHitsOnes"]) == ("1", "0", " ", "8")
    assert (c["GuestErrors"], c["HomeErrors"], c["Balls"], c["Strikes"], c["Outs"]) == ("1", "2", "3", "1", "2")
    assert (c["AtBatTens"], c["AtBatOnes"], c["InningTens"], c["InningOnes"]) == ("1", "2", "0", "3")
    assert (c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"]) == ("T", ".", " ")
    p.feed(cell(6, SEG["0"]))  # outs drop while top -> bottom
    c = p.snapshot()
    assert (c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"]) == ("B", " ", ".")


def test_line_score_baseball():
    p, c = run("Electromech_LineScoreBaseball",
               cell(0, bcdv(1, 2)), cell(1, bcdv(0, 9)), cell(2, SEG["1"] | 0x80), cell(3, SEG["1"]),
               cell(4, bcdv(0, 7)), cell(5, bcdv(3, 2)), cell(6, SEG["1"]), cell(7, SEG["2"]),
               cell(14, 0x80),
               cell(16, bcdv(0, 4)), cell(17, bcdv(0, 6)), cell(19, SEG["3"]),
               cell(8, bcdv(2, 1)), cell(9, bcdv(4, 3)), cell(10, SEG["5"]), cell(11, SEG["6"]),
               cell(12, bcdv(8, 7)), cell(13, bcdv(0, 9)),
               cell(24, bcdv(0, 1)), cell(25, bcdv(0, 0)), cell(26, SEG["0"]), cell(27, SEG["2"]),
               cell(28, bcdv(0, 0)), cell(29, bcdv(1, 3)))
    assert p.contract_name == "BaseballSoftball" and c["EventId"] == "Baseball"
    assert (c["HomeRunTens"], c["HomeRunOnes"], c["HomeHitsTens"], c["HomeHitsOnes"]) == ("1", "2", " ", "9")
    assert (c["InningTens"], c["InningOnes"], c["HomeErrors"], c["AtBatTens"], c["AtBatOnes"]) == ("1", "1", "1", "0", "7")
    assert (c["Balls"], c["Strikes"], c["Outs"], c["GuestErrors"]) == ("2", "3", "1", "3")  # addr 19 wins over 7 (quirk)
    assert (c["TopBottomInning"], c["TopOfInning"], c["BottomOfInning"]) == ("T", ".", " ")
    assert (c["GuestRunTens"], c["GuestRunOnes"], c["GuestHitsOnes"]) == ("0", "4", "6")
    assert [c[f"HomeInning{i}"] for i in range(1, 11)] == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
    assert [c[f"GuestInning{i}"] for i in range(1, 11)] == ["1", "0", "0", "0", "0", "2", "0", "0", "3", "1"]
    p.feed(cell(15, 0x80))
    assert p.snapshot()["TopBottomInning"] == "B" and p.snapshot()["BottomOfInning"] == "."
    p.feed(cell(14, 0x00))  # flag bit clear: ignored
    assert p.snapshot()["TopBottomInning"] == "B"


def test_never_raises_on_noise():
    import random
    rnd = random.Random(7)
    noise = bytes(rnd.randrange(256) for _ in range(4000))
    for pid, factory in electromech.PROTOCOLS.items():
        p = factory()
        for i in range(0, len(noise), 37):
            p.feed(noise[i:i + 37])
        assert p.last_error == "", pid
