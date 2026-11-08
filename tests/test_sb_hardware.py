import json
import os

import pytest

from scoreboards import hardware as hw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "scoreboards", "catalog.json"), encoding="utf-8") as _f:
    CATALOG = json.load(_f)
CONFIGS = [(v["name"], c) for v in CATALOG["vendors"] for c in v["configs"]]
USED = sorted({c["hardware"] for _, c in CONFIGS})


def test_daktronics_current_loop_exact():
    name = "PIC_CURRENTLOOP_NODECODE_19200_INVERTED"
    assert hw.pic_commands(name) == [">M0X0X", ">T0", ">D0", ">M8I1N"]
    assert hw.data_baud(name) == 19200
    assert hw.command_baud(name) == 57600
    assert hw.HARDWARE[name]["inverted"] is True and hw.HARDWARE[name]["device"] == "pic"


def test_every_catalog_hardware_resolves():
    for name in USED:
        info = hw.hardware_info(name)
        assert info["name"] in hw.HARDWARE
        assert isinstance(hw.data_baud(name), int)
        if info["interface"] == "pic" and not info["dynamic"]:
            cmds = hw.pic_commands(name, {"nonstandard_serial": "621009N2"})
            assert cmds[:2] == [">M0X0X", ">T0"] and len(cmds) >= 4
            assert all(c.startswith(">") and "\r" not in c for c in cmds)
        elif info["device"] in ("udp", "tcp", "none"):
            assert hw.pic_commands(name) == []


def test_every_catalog_config_has_known_eth_serial():
    for _, c in CONFIGS:
        e = hw.eth_serial(c["eth_serial"])
        assert e["start_char"] and e["stop_char"] and e["interface_mode"] in ("4Ch", "4Dh")


def test_catalog_plans():
    for _, c in CONFIGS:
        p = hw.plan(c)
        assert p["hardware"] in hw.HARDWARE


@pytest.mark.parametrize("name,expected,baud", [
    ("PIC_CURRENTLOOP_NODECODE_2400_INVERTED", [">M0X0X", ">T0", ">D0", ">M8I1N"], 2400),
    ("PIC_CURRENTLOOP_DECODEDAK4000_57600_INVERTED", [">M0X0X", ">T0", ">DD", ">M8I6N", ">M5N1N"], 57600),
    ("PIC_NEVCO_DECODENEVCO_57600_NORMAL", [">M0X0X", ">T0", ">DN", ">M1N5N", ">M5N1N"], 57600),
    ("PIC_RS232_NODECODE_9600_NORMAL", [">M0X0X", ">T0", ">D0", ">I2", ">M4N1N", ">M1N4N"], 9600),
    ("PIC_RS485/22_NODECODE_9600_INVERTED", [">M0X0X", ">T0", ">D0", ">I4", ">M4I1N", ">M1I4N"], 9600),
    ("PIC_RS485/22_DECODEMP70_57600_NORMAL", [">M0X0X", ">T0", ">D7", ">I4", ">M4N6N", ">M5N1N"], 57600),
    ("PIC_RS485/422_DECODEMP69_57600_INVERTED", [">M0X0X", ">T0", ">DF", ">I4", ">M4I6N", ">M5N1N"], 57600),
    ("LAIRD_XBEE_NODECODE_57600_NORMAL", [">M0X0X", ">T0", ">D0", ">M1N3N", ">M3N1N"], 57600),
    ("LAIRD_RS232_NODECODE_9600_NORMAL", [">M0X0X", ">T0", ">D0", ">I2", ">M4N1N", ">M1N4N"], 9600),
    ("SILABS_ZIGBEE_NODECODE_115200_NORMAL", [">M0X0X", ">T0", ">D0", ">M1N3N", ">M3N1N"], 115200),
    ("PIC_RS485/22_NODECODE_62100_NORMAL", [">M0X0X", ">T0", ">D0", ">I4", ">M4N1N", ">M1N4N"], 62100),
    ("NO HARDWARE CONFIGURATION", [], 9600),
    ("UDP", [], 9600),
    ("TCP_SERVER", [], 9600),
])
def test_pic_table(name, expected, baud):
    assert hw.pic_commands(name) == expected
    assert hw.data_baud(name) == baud


def test_serial_decode_nonstandard():
    name = "PIC_RS485/22_DECODESERIAL_57600_NORMAL"
    cfg = {"nonstandard_serial": "621009N2"}
    assert hw.pic_commands(name, cfg) == [">M0X0X", ">T0", ">DS", ">I4", ">M4N6N", ">M5N1N", ">S621009N2"]
    assert hw.pic_commands(name, {}) == [">M0X0X", ">T0", ">DS", ">I4", ">M4N6N"]
    # other PIC firmware: no serial decoding, pass-through routing
    assert hw.pic_commands(name, cfg, pic_version=1.2) == [">M0X0X", ">T0", ">D0", ">I4", ">M4N1N", ">M5N1N"]
    assert hw.data_baud(name, cfg) == 57600
    for _, c in CONFIGS:
        if c.get("nonstandard_serial"):
            assert hw.pic_commands(c["hardware"], c)[-1] == ">S" + c["nonstandard_serial"]


def test_pic_steps_and_verification():
    steps = hw.pic_steps("PIC_CURRENTLOOP_NODECODE_19200_INVERTED")
    assert [(s.kind, s.query) for s in steps] == [("switch", ">M?"), ("comm", ">T?"), ("comm", ">D?"),
                                                   ("switch", ">M8?")]
    assert hw.verify_reply(">M0X0X", ">M0X0X") and hw.verify_reply(">M0X0X", "M0X0X")
    assert hw.verify_reply(">M8I1N", "M8I1N") and not hw.verify_reply(">M8I1N", "M8I6N")
    assert hw.verify_reply(">T0", ">T0") and not hw.verify_reply(">T0", ">T1")
    assert not hw.verify_reply(">D0", "")


def test_dynamic_build():
    d = hw.dynamic_config("current_loop", 19200, inverted=True)
    assert hw.pic_commands(d) == [">M0X0X", ">T0", ">D0", ">M8I1N"] and hw.data_baud(d) == 19200
    assert hw.data_baud(hw.dynamic_config("nevco", 9600)) == 57600
    s = hw.dynamic_config("rs485", 9600, nonstandard_baud=19200)
    assert s["nonstandard_serial"] == "192008N1" and hw.pic_commands(s)[-1] == ">S192008N1"
    assert hw.dynamic_config("rs232", 9600, inverted=True)["inverted"] is False
    with pytest.raises(ValueError):
        hw.pic_commands("CUTOM_DYNAMYC_BUILD")


def test_unknown_hardware():
    with pytest.raises(KeyError):
        hw.pic_commands("NOPE")


def test_radios():
    laird = hw.radio_setup("LAIRD_XBEE_NODECODE_57600_NORMAL", sys_id=0x47, channel=5)
    assert laird[0].send == b"AT+++\r" and laird[0].expect == b"\xccCOM"
    assert laird[1].send == bytes([0xCC, 0xC1, 0x76, 0x01, 0x47]) and laird[1].expect == bytes([0x76, 0x01, 0x47])
    assert laird[2].send == bytes([0xCC, 0xC1, 0x40, 0x01, 5])
    assert laird[-1].send == b"\xcc\xff"
    grp = hw.radio_setup("LAIRD_XBEE_NODECODE_57600_NORMAL", group=2, channel=3)
    assert grp[2].send[-1] == 2 * 8 + 3
    d24 = hw.radio_setup("DIGI_XBEE_24GHZ_NODECODE_115200_NORMAL", group=0x1234, channel=11)
    assert [s.send for s in d24] == [b"+++", b"ATVR\r", b"ATID1234\r", b"ATCH0B\r", b"ATWR\r", b"ATCN\r"]
    chk = hw.radio_setup("DIGI_XBEE_VERSION_CHECK_NODECODE_57600_NORMAL", group=5, channel=1)
    assert [s.send for s in chk][2:5] == [b"ATIDE55\r", b"ATHP05\r", b"ATCMFFFFFF8000000000\r"]
    plain = hw.radio_setup("DIGI_XBEE_NODECODE_57600_NORMAL", channel=1)
    assert [s.send for s in plain][2:5] == [b"ATHP00\r", b"ATDT10\r", b"ATWR\r"]
    sl = hw.radio_setup("SILABS_NODECODE_115200_NORMAL", channel=7)
    assert [s.send for s in sl] == [b"receive 0 \n", b"set_phy_config 0\n", b"save_channel 7 \n", b"receive 1 \n"]
    assert b"ZigBee" in hw.radio_setup("SILABS_ZIGBEE_NODECODE_115200_NORMAL")[1].expect
    for name in ("PIC_RS232_NODECODE_9600_NORMAL", "UDP", "WIRELESS_NOCONFIG_NODECODE_9600_NORMAL",
                 "NO HARDWARE CONFIGURATION"):
        assert hw.radio_setup(name) == []


def test_radio_baud():
    assert hw.radio_baud_setup("LAIRD_XBEE_NODECODE_57600_NORMAL", 9600)[0].send == bytes([0xCC, 0xC1, 0x42, 0x01, 3])
    assert hw.radio_baud_setup("DIGI_XBEE_NODECODE_57600_NORMAL", 57600)[0].send == b"ATBD6\r"
    assert hw.radio_baud_setup("SILABS_NODECODE_115200_NORMAL", 9600) == []


def test_eth_serial():
    e = hw.eth_serial("MODEDELAY_DELAY3_STRTCHR02_STPCHR04_INT4C")
    assert e == {"mode": "delay", "delay": 3, "start_char": "02h", "stop_char": "04h", "length": None,
                 "interface_mode": "4Ch"}
    assert hw.eth_serial("MODE16/17_DELAY2_STRTCHR16_STPCHR17_INT4C")["mode"] == "16/17"
    assert hw.eth_serial("MODED+F_DELAY2_STRTCHRAA_STPCHRAB_INT4D")["mode"] == "delay+framing"


def test_configs_for_vendor():
    cfgs = hw.configs_for_vendor("daktronics")
    assert cfgs and any(c["hardware"] == "PIC_CURRENTLOOP_NODECODE_19200_INVERTED" for c in cfgs)
    assert hw.configs_for_vendor("no such vendor") == []
