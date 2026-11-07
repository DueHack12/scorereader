import scorereader as sr


def test_rtd_decoder_handles_noise_and_fragmentation():
    d = sr.DaktronicsRTD()
    stream = (b"\xff\x00garbage" + sr.encode_rtd_packet(107, "  14  21")
              + b"\x16\x010042110000\x02XXXX\x04AB\x17"      # unknown header -> ignored
              + b"\x16\x010042100500\x04AB\x17"              # header-only packet
              + sr.encode_rtd_packet(0, " 4:32") + b"\x16\x16")
    for i in range(len(stream)):
        d.feed(stream[i:i + 1])
    out = sr.SportMap(sr.FIELDS_PATH).extract("football", d.snapshot())
    assert (out["home_score"], out["guest_score"], out["clock"]) == ("14", "21", "4:32")


def test_football_derived_fields():
    d = sr.DaktronicsRTD()

    def put(pos, length, text, right=False):
        t = str(text)
        t = t.rjust(length) if right else t.ljust(length)
        d.feed(sr.encode_rtd_packet(pos - 1, t))

    put(142, 2, 2, right=True)
    put(220, 2, 35, right=True)
    put(222, 3, "3rd")
    put(225, 2, 7, right=True)
    put(210, 1, "<")
    out = sr.SportMap(sr.FIELDS_PATH).extract("football", d.snapshot())
    assert out["period_ordinal"] == "2nd"
    assert out["down_distance"] == "3rd & 7"
    assert out["ball_on"] == "35"
    assert out["home_poss"] is True and out["guest_poss"] is False


def test_all_sports_load():
    m = sr.SportMap(sr.FIELDS_PATH)
    assert {"football", "basketball", "soccer", "baseball", "volleyball"} <= set(m.names())
    for sport in m.names():
        m.extract(sport, b" " * 1024)
