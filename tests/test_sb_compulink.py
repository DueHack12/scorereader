"""Compulink drag racing: CR-terminated tag lines."""
from scoreboards import create


def check(c, **kw):
    for k, v in kw.items():
        assert c[k] == v, (k, c.get(k), v)


def test_pairing_and_times():
    p = create("Compulink_DragRacing")
    p.feed(b"C,Pro Stock,R3\r\nc1 123\r\nn1Bob Smith\r\nm1Team1\r\nq1 7\r\nb1PRO\r\n")
    p.feed(b"c2 456\r\nn2Jane Roe Jane Roe Jane Roe\r\nq2 12\r\nw-L\r\nm-.012\r\nfl1.1\r\n")
    check(p.snapshot(), CategoryName="Pro Stock", Round="R3", LeftCarNumber=" 123", LeftDriver="Bob Smith",
          LeftMember="Team1", LeftQualPos=" 7", LeftClass="PRO", RightCarNumber=" 456",
          RightDriver="Jane Roe Jane Roe Ja", RightQualPos=" 1", Win="L", Mov=".012", LeftFirst="1.1",
          ChannelNumber="0", IsDetailed=False, EventId="DragRacing")


def test_detail_times_and_clear():
    p = create("Compulink_DragRacingDetail")
    p.feed(b"S5xx9.50\rL0 0.012\rL1 1.234\rL2 3.456\rL3 5.678\rL4 123.4\rL5 7.890\rL6 8.123\rL7 150.0\r")
    p.feed(b"S6xx10.0\rR0 0.100\rR1 1.300\rR2 3.500\rR3 5.700\rR4 120.0\rR5 7.900\rR6 8.200\rR7 140.0\rfr2.2\r")
    check(p.snapshot(), ChannelNumber="1", IsDetailed=True, LeftDialIn="9.50", LeftReactionTime=" 0.012",
          Left60Feet=" 1.234", Left330Feet=" 3.456", Left660Feet=" 5.678", Left660FeetMPH=" 123.4",
          Left1000Feet=" 7.890", LeftQuarterMile=" 8.123", LeftQuarterMileMPH=" 150.0", RightDialIn="10.0",
          RightReactionTime=" 0.100", Right60Feet=" 1.300", RightQuarterMileMPH=" 140.0", RightFirst="2.2")
    p.feed(b"C,Next,R4\r")
    check(p.snapshot(), LeftDialIn="", Left60Feet="", RightFirst="", CategoryName="Next", Round="R4", Win=" ")


def test_garbage_split_and_short_line():
    p = create("Compulink_DragRacing")
    data = b"\x00\xffn1Bob\x01 Smith\r\n"
    p.feed(data[:5])
    p.feed(data[5:])
    assert p.packets == 1 and p.snapshot()["LeftDriver"] == "Bob Smith"
    p.feed(b"x\r")  # a single character is not a tag
    assert p.bad == 1 and p.packets == 1
    p.feed(b"\r")  # empty line ignored
    assert p.bad == 1
