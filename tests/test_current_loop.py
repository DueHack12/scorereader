import scorereader as sr
from conftest import make_cl_frame as frame

INV = {v: k for k, v in sr.SEG7.items() if v != " "}
INV[" "] = 0


def S(text):
    return [INV[c] for c in text]


def feed_bytewise(cl, stream):
    for i in range(len(stream)):
        cl.feed(stream[i:i + 1])


def test_football_6601():
    cl = sr.DaktronicsCurrentLoop()
    f_code = frame(0xFE, b"66015000430")
    f1 = frame(1, S("1200") + S("25") + [0x40])                       # clock 12:00, play 25, stopped
    f15 = frame(15, S("1200") + [0, 0] + S(" 1 22") + [0, 7] + S("32") + [0])
    f16 = frame(16, S("353 7") + [0])
    feed_bytewise(cl, b"\x00junk\x55\xaa\x99" + (f_code + f1 + f15 + f16) * 3)
    d = cl.data()
    assert cl.console_code == "6601" and d["sport"] == "football"
    assert d["clock"] == "12:00" and d["clock_running"] is False
    assert d["play_clock"] == "25"
    assert (d["home_score"], d["guest_score"], d["period_ordinal"]) == ("1", "2", "2nd")
    assert d["home_poss"] is True and d["guest_poss"] is False
    assert (d["home_timeouts"], d["guest_timeouts"]) == ("3", "2")
    assert d["down_distance"] == "3rd & 7" and d["ball_on"] == "35"


def test_tenths_clock_mode():
    cl = sr.DaktronicsCurrentLoop()
    cl.feed(frame(1, S("598") + [0] + S("25") + [0x00]))
    assert cl.data()["clock"] == "59.8"
    assert cl.data()["clock_running"] is True


def test_bad_checksum_rejected():
    cl = sr.DaktronicsCurrentLoop()
    f = bytearray(frame(1, S("1200") + S("25") + [0]))
    f[-1] ^= 0xFF
    cl.feed(bytes(f))
    assert cl.packets == 0 and cl.bad == 1


# Bytes captured from a real All Sport 5000 in soccer (code 7601):
# board showed 60:00, JESUITS 5 / FALCONS 6, HALF 7, CKICKS 3/4, SOG 1/2
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


def test_soccer_7601_real_capture():
    cl = sr.DaktronicsCurrentLoop()
    stream = b"".join(frame(a, d) for a, d in SOCCER.items()) * 2
    for i in range(0, len(stream), 13):
        cl.feed(stream[i:i + 13])
    d = cl.data()
    assert d["sport"] == "soccer"
    assert d["clock"] == "60:00" and d["clock_running"] is False
    assert (d["home_score"], d["guest_score"], d["period"]) == ("5", "6", "7")
    assert (d["home_shots"], d["guest_shots"]) == ("1", "2")
    assert (d["home_corners"], d["guest_corners"]) == ("3", "4")
    assert "down" not in d and "ball_on" not in d


def test_soccer_corners_addr13_zeros_do_not_override_stats_panel():
    cl = sr.DaktronicsCurrentLoop()
    zeros13 = frame(13, H("e6 ed bf bf 00 bf 00 bf 07 00 00 bf 00 bf 00 00"))

    def f72(h, g):
        return frame(72, bytes([0, h, 0, 0, 0x86, 0, 0, 0, 0, 0, 0, g, 0, 0, 0xDB, 0]))

    cl.feed(frame(0xFE, b"76015000430") + f72(0xCF, 0xE6) + zeros13)
    assert (cl.data()["home_corners"], cl.data()["guest_corners"]) == ("3", "4")
    cl.feed(f72(0x6D, 0x7D) + zeros13)
    assert (cl.data()["home_corners"], cl.data()["guest_corners"]) == ("5", "6")


def test_custom_fields_override():
    cl = sr.DaktronicsCurrentLoop()
    cl.feed(b"".join(frame(a, d) for a, d in SOCCER.items()))
    cl.custom_fields = lambda: {"home_corners": {"addr": 72, "bytes": [3, 4]}, "new_thing": {"addr": 12, "bytes": [11]}}
    d = cl.data()
    assert d["home_corners"] == "1" and d["new_thing"] == "1"


def test_unknown_code_uses_configured_sport():
    cl = sr.DaktronicsCurrentLoop()
    cl.sport_fallback = lambda: "soccer"
    cl.feed(frame(0xFE, b"99995000430"))
    assert cl.sport == "soccer"
