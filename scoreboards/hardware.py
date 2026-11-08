"""How ScoreConnect III configures the ScoreBot hardware for each wiring option ("hardware configuration").

Every wiring option in ``catalog.json`` names a hardware configuration such as
``PIC_CURRENTLOOP_NODECODE_19200_INVERTED``.  This module turns that name into

* ``HARDWARE``: the facts (device, interface, decode, baud, polarity);
* :func:`pic_commands`: the ASCII commands sent to the ScoreLinkII selector chip (PIC) in command mode;
* :func:`data_baud`: the serial baud to read data at once the bot is back in data mode;
* :func:`radio_setup`: the Laird / Digi XBee / Silicon Labs radio set-up conversation, as data;
* :data:`ETH_SERIAL` / :func:`eth_serial`: the network serial-server settings used by network bots.

Nothing here touches hardware; it is data and string building, so it is testable without a ScoreBot.
See ``docs/vendors/hardware.md`` for the wire details and the list of unverified points.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

# Source (wiring) letters used in the PIC ">I" and ">M" commands.
SOURCE_LETTER = {"rs232": "2", "rs485": "4", "nevco": "N", "current_loop": "C", "xbee": "X"}
# PIC on-board decoder letters (">D").
DECODE_LETTER = {None: "0", "nevco": "N", "mp69": "F", "mp70": "7", "dak4000": "D", "serial": "S"}

COMMAND_BAUD = 57600            # PIC command-mode baud (ScoreLinkII, ScoreLink Plus, ScoreLink I)
DEFAULT_PIC_VERSION = 1.14      # firmware reported by ">R?" on the ScoreLinkII that ScoreReader was tested with

# Timing and retry constants of ScoreConnect's PIC conversation (milliseconds unless noted).
PIC_TIMING = {
    "mode_switch_ms": 50,       # wait after driving the command-mode line either way
    "eeprom_ms": 300,           # wait after a write before reading it back
    "retry_wait_ms": 300,       # wait between failed attempts
    "settle_ms": 100,           # wait after each command is confirmed or given up on
    "reply_wait_ms": 200,       # wait before reading a reply
    "reply_timeout_ms": 500,    # read timeout for a reply
    "switch_tries": 10,         # ">M..." commands
    "comm_tries": 4,            # every other command
}

# (interface, source, decode, baud, inverted) per HardwareConfigurationType, in ScoreConnect's enum order.
# The interface is the module that talks to the bot: pic, laird, digi, digi_check_version, digi_24ghz,
# silabs, silabs_zigbee, receiver (wireless receiver without configuration), udp.
_TABLE = {
    "NO_HARDWARE_CONFIGURATION": (None, None, None, 9600, False),
    "PIC_CURRENTLOOP_NODECODE_19200_INVERTED": ("pic", "current_loop", None, 19200, True),
    "PIC_CURRENTLOOP_NODECODE_2400_INVERTED": ("pic", "current_loop", None, 2400, True),
    "PIC_CURRENTLOOP_DECODEDAK4000_57600_INVERTED": ("pic", "current_loop", "dak4000", 57600, True),
    "PIC_NEVCO_DECODENEVCO_57600_NORMAL": ("pic", "nevco", "nevco", 57600, False),
    "PIC_RS232_NODECODE_19200_NORMAL": ("pic", "rs232", None, 19200, False),
    "PIC_RS232_NODECODE_9600_NORMAL": ("pic", "rs232", None, 9600, False),
    "PIC_RS485_22_NODECODE_57600_NORMAL": ("pic", "rs485", None, 57600, False),
    "PIC_RS485_22_NODECODE_2400_NORMAL": ("pic", "rs485", None, 2400, False),
    "PIC_RS485_22_NODECODE_9600_NORMAL": ("pic", "rs485", None, 9600, False),
    "PIC_RS485_22_NODECODE_9600_INVERTED": ("pic", "rs485", None, 9600, True),
    "PIC_RS485_22_NODECODE_19200_NORMAL": ("pic", "rs485", None, 19200, False),
    "PIC_RS485_22_NODECODE_62100_NORMAL": ("pic", "rs485", None, 62100, False),
    "PIC_RS485_22_NODECODE_115200_NORMAL": ("pic", "rs485", None, 115200, False),
    "PIC_RS485_22_NODECODE_115200_INVERTED": ("pic", "rs485", None, 115200, True),
    "PIC_RS485_22_DECODEMP70_57600_NORMAL": ("pic", "rs485", "mp70", 57600, False),
    "PIC_RS485_422_DECODEMP69_57600_NORMAL": ("pic", "rs485", "mp69", 57600, False),
    "PIC_RS485_422_DECODEMP69_57600_INVERTED": ("pic", "rs485", "mp69", 57600, True),
    "LAIRD_RS232_NODECODE_9600_NORMAL": ("laird", "rs232", None, 9600, False),
    "LAIRD_RS232_NODECODE_57600_NORMAL": ("laird", "rs232", None, 57600, False),
    "DIGI_XBEE_NODECODE_57600_NORMAL": ("digi", "xbee", None, 57600, False),
    "LAIRD_XBEE_NODECODE_57600_NORMAL": ("laird", "xbee", None, 57600, False),
    "PIC_RS485_22_NODECODE_38400_NORMAL": ("pic", "rs485", None, 38400, False),
    "SILABS_NODECODE_115200_NORMAL": ("silabs", "xbee", None, 115200, False),
    "PIC_RS232_NODECODE_115200_NORMAL": ("pic", "rs232", None, 115200, False),
    "SILABS_ZIGBEE_NODECODE_115200_NORMAL": ("silabs_zigbee", "xbee", None, 115200, False),
    "PIC_RS485_22_DECODESERIAL_57600_NORMAL": ("pic", "rs485", "serial", 57600, False),
    "PIC_RS232_NODECODE_4800_NORMAL": ("pic", "rs232", None, 4800, False),
    "WIRELESS_NOCONFIG_NODECODE_9600_NORMAL": ("receiver", "xbee", None, 9600, False),
    "PIC_RS485_22_NODECODE_10000_NORMAL": ("pic", "rs485", None, 10000, False),
    "PIC_RS232_NODECODE_38400_NORMAL": ("pic", "rs232", None, 38400, False),
    "UDP": ("udp", "rs232", None, 9600, False),
    "DIGI_XBEE_VERSION_CHECK_NODECODE_57600_NORMAL": ("digi_check_version", "xbee", None, 57600, False),
    "PIC_RS232_NODECODE_57600_NORMAL": ("pic", "rs232", None, 57600, False),
    "DIGI_XBEE_24GHZ_NODECODE_115200_NORMAL": ("digi_24ghz", "xbee", None, 115200, False),
    # Added in the Windows build:
    "CUTOM_DYNAMYC_BUILD": ("pic", None, None, 9600, False),    # [sic]; fields are filled in by dynamic_config()
    "TCP_SERVER": ("tcp_server", "rs232", None, 9600, False),
}
_INTERFACE_NUMBER = {"pic": 1, "laird": 2, "digi": 3, "silabs": 4, "silabs_zigbee": 5, "receiver": 6, "udp": 7,
                     "digi_check_version": 8, "digi_24ghz": 9, "tcp_server": 10}
_DEVICE = {"pic": "pic", "laird": "laird", "digi": "digi_xbee", "digi_check_version": "digi_xbee",
           "digi_24ghz": "digi_xbee", "silabs": "silabs", "silabs_zigbee": "silabs", "receiver": "receiver",
           "udp": "udp", "tcp_server": "tcp", None: "none"}


def _entry(name: str, row: tuple) -> dict:
    interface, source, decode, baud, inverted = row
    return {
        "name": name,
        "device": _DEVICE[interface],          # pic | laird | digi_xbee | silabs | receiver | udp | none
        "interface": interface,                # finer than device (digi variants, zigbee)
        "interface_number": _INTERFACE_NUMBER.get(interface),   # ScoreConnect's InterfaceType value
        "source": source,                      # rs232 | rs485 | nevco | current_loop | xbee
        "source_letter": SOURCE_LETTER.get(source),
        "decode": decode,                      # None = pass-through; else PIC decoder name
        "decode_letter": DECODE_LETTER[decode] if interface else None,
        "baud": baud,                          # serial baud to read data at after configuration
        "inverted": inverted,
        "polarity": "I" if inverted else "N",
        "dynamic": name == "CUTOM_DYNAMYC_BUILD",
        "command_baud": COMMAND_BAUD if interface in ("pic", "laird", "digi", "digi_check_version", "digi_24ghz",
                                                      "silabs", "silabs_zigbee", "receiver") else None,
    }


def normalize(name: str) -> str:
    """Catalog spellings (``PIC_RS485/22_...``, ``NO HARDWARE CONFIGURATION``, ``MODED+F_...``) to table keys."""
    return str(name).strip().upper().replace("/", "_").replace(" ", "_").replace("+", "_")


HARDWARE: dict = {name: _entry(name, row) for name, row in _TABLE.items()}


def hardware_info(hardware) -> dict:
    """The HARDWARE entry for a catalog or enum spelling; KeyError if ScoreConnect has no such configuration.

    A dict (as returned by :func:`dynamic_config`) is passed through unchanged."""
    if isinstance(hardware, dict):
        return hardware
    try:
        return HARDWARE[normalize(hardware)]
    except KeyError:
        raise KeyError(f"Unknown hardware configuration '{hardware}'") from None


def dynamic_config(source: str, baud: int = 9600, inverted: bool = False, nonstandard_baud: Optional[int] = None) -> dict:
    """The "custom build" hardware configuration of the Windows build (catalog hardware ``CUTOM_DYNAMYC_BUILD``).

    The operator picks source (rs232 | rs485 | nevco | current_loop), baud and polarity; ScoreConnect derives the rest:
    Nevco forces the Nevco decoder at 57600; a custom baud (``nonstandard_baud`` 100..99999) forces the serial
    decoder at 57600 with ``NNNNN8N1``; polarity is only honoured for rs485 and current loop (others are normal).
    """
    if source not in ("rs232", "rs485", "nevco", "current_loop"):
        raise ValueError(f"unsupported dynamic source '{source}'")
    decode, out_baud, nonstd = None, baud, None
    if source == "nevco":
        decode, out_baud = "nevco", 57600
    elif nonstandard_baud is not None:
        if not 100 <= nonstandard_baud <= 99999:
            raise ValueError("nonstandard_baud must be 100..99999")
        decode, out_baud, nonstd = "serial", 57600, f"{nonstandard_baud:05d}8N1"
    inv = bool(inverted) and source in ("rs485", "current_loop")
    e = _entry("CUTOM_DYNAMYC_BUILD", ("pic", source, decode, out_baud, inv))
    e["nonstandard_serial"] = nonstd
    return e


# --------------------------------------------------------------------------- PIC (ScoreLinkII selector chip)
class PicStep(NamedTuple):
    cmd: str        # without the trailing CR, e.g. ">M8I1N"
    kind: str       # "switch" (">M...", verified up to 10 times) or "comm" (everything else, up to 4 times)
    query: str      # read-back query, e.g. ">M8?"


def readback_query(cmd: str, kind: Optional[str] = None) -> str:
    """The query ScoreConnect sends to confirm ``cmd`` was stored."""
    cmd = cmd.strip()
    if kind is None:
        kind = "switch" if cmd.startswith(">M") else "comm"
    if kind == "comm":
        return cmd[:2] + "?"
    if len(cmd) > 4 and cmd[2] == "0":
        # slot-clear style ">M0X0X": ask for the whole mux state (or the second slot if it is not 0)
        return ">M?" if cmd[4] == "0" else cmd[:2] + cmd[4] + "?"
    return cmd[:3] + "?"


def verify_reply(cmd: str, reply: str, kind: Optional[str] = None) -> bool:
    """ScoreConnect's acceptance test for a read-back reply.

    ``reply`` is the CR-terminated line the PIC sent, with or without the leading ``>`` echo.
    Only some characters are compared (``>M8I1N`` read back as ``>M8X1Y`` still passes), exactly like ScoreConnect.
    """
    cmd = cmd.strip()
    if kind is None:
        kind = "switch" if cmd.startswith(">M") else "comm"
    reply = "".join(ch for ch in reply if " " <= ch <= "~")
    if not reply.startswith(">"):
        reply = ">" + reply
    if kind == "comm":
        return len(reply) > 2 and len(cmd) > 2 and reply[0] == cmd[0] and reply[2] == cmd[2]
    reply = reply.split(",")[0]
    if len(cmd) > 4 and cmd[2] == "0":
        return len(reply) > 2 and reply[0] == cmd[0] and reply[2] == cmd[4]
    return len(reply) > 4 and len(cmd) > 4 and reply[0] == cmd[0] and reply[2] == cmd[2] and reply[4] == cmd[4]


def _is_version(version, wanted: float) -> bool:
    try:
        return round(float(version), 2) == wanted
    except (TypeError, ValueError):
        return False


def pic_steps(hardware: str, vendor_config: Optional[dict] = None, pic_version=DEFAULT_PIC_VERSION) -> list:
    """The ordered PIC conversation ScoreConnect has with a ScoreLinkII for this hardware configuration.

    ``vendor_config`` is a catalog wiring option; its ``nonstandard_serial`` (``"621009N2"``) matters only for the
    serial-decode configuration.  ``pic_version`` is the number after ``R`` in the ``>R?`` reply.
    Returns [] when ScoreConnect sends nothing (no hardware configuration, UDP).
    """
    hw = hardware_info(hardware)
    if hw["interface"] in (None, "udp", "tcp_server"):
        return []
    if hw["source_letter"] is None:
        raise ValueError("custom build: use dynamic_config(source, baud, ...) and pass its result")
    src, dec, pol = hw["source_letter"], hw["decode_letter"], hw["polarity"]
    cmds = [">M0X0X", ">T0"]
    # The decoder command: serial decode needs PIC firmware 1.14, otherwise ScoreConnect falls back to ">D0".
    cmds.append(">D0" if dec == "S" and not _is_version(pic_version, 1.14) else ">D" + dec)
    if src == "C":
        if dec == "0":
            cmds.append(f">M8{pol}1N")
        elif dec == "D":
            cmds += [">M8I6N", ">M5N1N"]        # polarity is fixed to inverted for the Daktronics 4000 decoder
    elif src == "2":
        cmds += [">I2", f">M4{pol}1N", f">M1{pol}4N"]
    elif src == "4":
        cmds.append(">I4")
        if dec == "0":
            cmds += [f">M4{pol}1N", f">M1{pol}4N"]
        elif dec in ("7", "F"):
            cmds += [f">M4{pol}6N", ">M5N1N"]
        elif dec == "S":
            if _is_version(pic_version, 1.14):
                cmds.append(f">M4{pol}6N")
                nonstd = ((vendor_config or {}).get("nonstandard_serial") or hw.get("nonstandard_serial") or "").strip()
                if nonstd:
                    cmds += [">M5N1N", ">S" + nonstd]
            else:
                cmds += [f">M4{pol}1N", ">M5N1N"]
    elif src == "X":
        cmds += [f">M1{pol}3N", f">M3{pol}1N"]
    elif src == "N":
        cmds += [f">M1{pol}5N", f">M5{pol}1N"]
    steps = []
    for c in cmds:
        kind = "switch" if c.startswith(">M") else "comm"
        steps.append(PicStep(c, kind, readback_query(c, kind)))
    return steps


def pic_commands(hardware: str, vendor_config: Optional[dict] = None, pic_version=DEFAULT_PIC_VERSION) -> list:
    """Command strings (no CR) in the order ScoreConnect sends them; append ``\\r`` when writing."""
    return [s.cmd for s in pic_steps(hardware, vendor_config, pic_version)]


def data_baud(hardware: str, vendor_config: Optional[dict] = None) -> int:
    """Serial baud to read scoreboard data at after configuration (0 = no hardware configuration, not applicable).

    The PIC only routes signals, so for pass-through configurations this is simply the scoreboard's baud.  With an
    on-board decoder (Daktronics 4000, Nevco, MP69/MP70, serial) the PIC re-emits the decoded data at 57600.
    """
    return int(hardware_info(hardware)["baud"])


def command_baud(hardware: str) -> Optional[int]:
    """Baud used for the command conversation (PIC or radio); None when ScoreConnect has none."""
    return hardware_info(hardware)["command_baud"]


# --------------------------------------------------------------------------- wireless radios
class RadioStep(NamedTuple):
    kind: str                   # enter | query | set | reset
    send: bytes
    expect: Optional[bytes]     # None = no check
    match: str                  # "equals" (whole reply must be exactly this) or "contains"
    delay_ms: int               # wait between writing and reading
    timeout_ms: int             # per-read timeout
    tries: int                  # attempts before giving up
    note: str = ""


_DIGI_GROUP_HP_DT = (
    (0,0), (0,16), (1,16), (2,16), (3,16), (4,32), (5,32), (6,32),
    (0,32), (1,48), (2,48), (3,48), (4,48), (5,64), (6,64), (0,64),
    (1,64), (2,80), (3,80), (4,80), (5,80), (6,96), (0,96), (1,96),
    (2,96), (3,112), (4,112), (5,112), (6,112), (0,128), (1,128), (2,128),
    (3,128), (4,128), (5,128), (6,128), (0,144), (1,144), (2,144), (3,144),
    (4,144), (5,144), (6,144), (0,5), (1,5), (2,5), (3,5), (4,5),
    (5,5), (6,21), (0,21), (1,21), (2,21), (3,21), (4,21), (5,37),
    (6,37), (0,37), (1,37), (2,37), (3,37), (4,53), (5,53), (6,53),
    (0,53), (1,53), (2,53), (3,69), (4,69), (5,69), (6,69), (0,69),
    (1,69), (6,5), (5,21), (4,37), (3,53), (2,69), (0,85), (1,85),
    (2,85), (3,85), (4,85), (5,85), (6,85), (0,101), (1,101), (2,101),
    (3,101), (4,101), (5,101), (6,101), (0,117), (1,117), (2,117), (3,117),
    (4,117), (5,117), (6,117), (0,133),
)

ETH_SERIAL = {
    "MODE16_17_DELAY2_STRTCHR16_STPCHR17_INT4C": ("16/17", 2, "16h", "17h", None, "4Ch"),
    "MODE55AA_DELAY2_STRTCHR02_STPCHR04_INT4D": ("55aa", 2, "02h", "04h", None, "4Dh"),
    "MODEDELAY_DELAY2_STRTCHR02_STPCHR03_INT4C": ("delay", 2, "02h", "03h", None, "4Ch"),
    "MODEDELAY_DELAY2_STRTCHR04_STPCHR05_INT4C": ("delay", 2, "04h", "05h", None, "4Ch"),
    "MODEDELAY_DELAY3_STRTCHR01_STPCHR1D_INT4D": ("delay", 3, "01h", "1dh", None, "4Dh"),
    "MODEDELAY_DELAY3_STRTCHR02_STPCHR04_INT4C": ("delay", 3, "02h", "04h", None, "4Ch"),
    "MODEDELAY_DELAY1_STRTCHR02_STPCHR04_INT4C": ("delay", 1, "02h", "04h", None, "4Ch"),
    "MODEDELAY_DELAY3_STRTCHR02_STPCHR04_INT4D": ("delay", 3, "02h", "04h", None, "4Dh"),
    "MODEDELAY_DELAY3_STRTCHRFC_STPCHR20_INT4C": ("delay", 3, "FCh", "20h", None, "4Ch"),
    "MODEDELAY_DELAY3_STRTCHRFC_STPCHR20_INT4D": ("delay", 3, "FCh", "20h", None, "4Dh"),
    "MODEDELAY_DELAY6_STRTCHR02_STPCHR04_INT4D": ("delay", 6, "02h", "04h", None, "4Dh"),
    "MODEDELAY_DELAY8_STRTCHR02_STPCHR04_INT4D": ("delay", 8, "02h", "04h", None, "4Dh"),
    "MODED_F_DELAY2_STRTCHR02_STPCHR03_INT4D": ("delay+framing", 2, "02h", "03h", None, "4Dh"),
    "MODED_F_DELAY2_STRTCHRAA_STPCHRAB_INT4D": ("delay+framing", 2, "aah", "abh", None, "4Dh"),
    "MODESTARTEND_DELAY2_STRTCHR0D_STPCHR0A_INT4C": ("start/end", 2, "0Dh", "0Ah", None, "4Ch"),
    "MODESTARTEND_DELAY4_STRTCHR02_STPCHR0D_INT4C": ("start/end", 4, "02h", "0Dh", None, "4Ch"),
    "MODESTARTLENGTH_DELAY2_STRTCHRFC_STPCHR20_INT4D": ("start/length", 2, "FCh", "20h", None, "4Dh"),
    "MODEDELAY_DELAY2_STRTCHR04_STPCHR05_INT4D": ("delay", 2, "04h", "05h", None, "4Dh"),
    "MODESTARTLENGTH_DELAY2_STRTCHRFF_LENGTH19_INT4D": ("start/length", 2, "FFh", None, "19", "4Dh"),
    "MODESTARTLENGTH_DELAY2_STRTCHRFC_LENGTH20_INT4D": ("start/length", 2, "FCh", None, "20", "4Dh"),
    "MODESTARTLENGTH_DELAY2_STRTCHRFC_LENGTH20_INT4C": ("start/length", 2, "FCh", None, "20", "4Ch"),
    "MODEDELAY_DELAY5_STRTCHR02_STPCHR03_INT4D": ("delay", 5, "02h", "03h", None, "4Dh"),
    "MODEDELAY_DELAY5_STRTCHR02_STPCHR03_INT4C": ("delay", 5, "02h", "03h", None, "4Ch"),
    "MODEDELAY_DELAY50_STRTCHR02_STPCHR03_INT4D": ("delay", 50, "02h", "03h", None, "4Dh"),
}

def _laird_channel(has_group: bool, group: int, channel: int) -> int:
    if not has_group:
        return channel & 0xFF
    g = group if 0 <= group <= 8 else 0
    c = channel if (0 <= channel <= 8 and g != 0) else 0
    return (g * 8 + c) & 0xFF if c else g & 0xFF


def _radio_laird(sys_id: int, channel: int, external: bool, antenna_reg: int = 0) -> list:
    antenna = (antenna_reg | 0x20) if external else (antenna_reg & 0xDF)
    note_ant = ("register value is read first (cc c0 c1 01 -> cc c1 01 vv) and OR-ed with 0x20 for the external "
                "antenna or AND-ed with 0xDF for the internal one; antenna_reg=0 is assumed here")
    return [
        RadioStep("enter", b"AT+++\r", b"\xccCOM", "equals", 100, 500, 4, "radio command mode"),
        RadioStep("set", bytes([0xCC, 0xC1, 0x76, 0x01, sys_id]), bytes([0x76, 0x01, sys_id]), "equals", 50, 100, 4,
                  "system id"),
        RadioStep("set", bytes([0xCC, 0xC1, 0x40, 0x01, channel]), bytes([0x40, 0x01, channel]), "equals", 50, 100, 4,
                  "channel"),
        RadioStep("query", bytes([0xCC, 0xC0, 0xC1, 0x01]), None, "equals", 50, 100, 4, note_ant),
        RadioStep("set", bytes([0xCC, 0xC1, 0xC1, 0x01, antenna]), bytes([0xC1, 0x01, antenna]), "equals", 100, 100, 4,
                  "antenna register"),
        RadioStep("reset", b"\xcc\xff", None, "equals", 100, 100, 1, "radio reset"),
    ]


def _digi_valid_firmware(interface: str, version: int) -> bool:
    if interface == "digi_check_version":
        return version >= 8074
    if interface == "digi_24ghz":
        return version <= 2012
    return 2012 < version <= 3014


def _radio_digi(interface: str, has_group: bool, group: int, channel: int) -> list:
    ok = b"OK\r"
    steps = [
        RadioStep("enter", b"+++", ok, "contains", 500, 500, 4, "AT command mode (guard time is the delay)"),
        RadioStep("query", b"ATVR\r", None, "equals", 50, 500, 1,
                  "firmware version as a decimal integer; valid: check_version >= 8074, 24ghz <= 2012, "
                  "plain 2013..3014"),
    ]
    if not has_group:
        if 0 <= channel < len(_DIGI_GROUP_HP_DT):
            hp, dt = _DIGI_GROUP_HP_DT[channel]
            cmds = [f"ATHP{hp:02X}\r", f"ATDT{dt:02X}\r", "ATWR\r"]
        else:
            cmds = []
    elif interface == "digi_check_version":
        mask = "FFFFFF8000000000" if channel == 1 else "FFFFFFFFFFF7FFFF"
        cmds = ["ATIDE55\r", f"ATHP{group:02X}\r", f"ATCM{mask}\r", "ATWR\r"]
    elif interface == "digi_24ghz":
        cmds = [f"ATID{group:04X}\r", f"ATCH{channel:02X}\r", "ATWR\r"]
    else:
        cmds = []
    for c in cmds:
        steps.append(RadioStep("set", c.encode("ascii"), ok, "contains", 50, 500, 1, "2 s window for the reply"))
    steps.append(RadioStep("reset", b"ATCN\r", None, "contains", 500, 200, 1, "leave command mode"))
    return steps


def _radio_silabs(zigbee: bool, channel: int) -> list:
    phy = "ZigBee" if zigbee else "Custom"
    return [
        RadioStep("enter", b"receive 0 \n", b"Received packets: OFF\n> ", "contains", 50, 100, 4, "stop reception"),
        RadioStep("set", b"set_phy_config 0\n", f"Success, now on: {phy}\n> ".encode(), "contains", 50, 100, 4,
                  "ScoreConnect sends phy id 0 for ZigBee too"),
        RadioStep("set", f"save_channel {channel} \n".encode(), b"Success\n>", "contains", 50, 100, 4,
                  "note the space before the newline"),
        RadioStep("set", b"receive 1 \n", b"Received packets: ON\n> ", "contains", 50, 100, 4, "resume reception"),
    ]


def radio_setup(hardware: str, vendor_config: Optional[dict] = None, *, sys_id: int = 0, channel: int = 0,
                group: Optional[int] = None, has_group: Optional[bool] = None, external_antenna: bool = True) -> list:
    """The radio set-up conversation ScoreConnect has after the PIC is back in data mode, as RadioStep data.

    The catalog does not carry radio parameters (they live in per-vendor wireless tables), so the caller supplies
    ``sys_id`` (Laird), ``channel`` and ``group``.  ``has_group`` defaults to ``group is not None``.
    Returns [] for hardware that ScoreConnect does not configure over the radio link: PIC wired configurations, the
    no-configuration receiver, UDP and "no hardware".
    """
    hw = hardware_info(hardware)
    iface = hw["interface"]
    if has_group is None:
        has_group = group is not None
    group = group or 0
    if iface == "laird":
        return _radio_laird(sys_id & 0xFF, _laird_channel(has_group, group, channel), external_antenna)
    if iface in ("digi", "digi_check_version", "digi_24ghz"):
        return _radio_digi(iface, has_group, group, channel)
    if iface in ("silabs", "silabs_zigbee"):
        return _radio_silabs(iface == "silabs_zigbee", channel)
    return []


_LAIRD_BAUD_ID = {115200: 9, 57600: 8, 38400: 7, 28000: 6, 19200: 5, 14400: 4, 9600: 3, 4800: 2, 2400: 1, 1200: 0}
_DIGI_BAUD_ID = {57600: 6, 38400: 5, 19200: 4, 9600: 3, 4800: 2, 2400: 1, 1200: 0}


def radio_baud_setup(hardware: str, baud: int) -> list:
    """Steps that change the radio's own serial baud (Windows build only; the Mac build has none).

    Laird and Digi XBee only; Silicon Labs radios cannot be changed (ScoreConnect returns false).  [] when the baud
    has no radio code or the hardware has no such radio.  Run it in radio command mode, before :func:`radio_setup`.
    """
    iface = hardware_info(hardware)["interface"]
    if iface == "laird" and baud in _LAIRD_BAUD_ID:
        b = _LAIRD_BAUD_ID[baud]
        return [
            RadioStep("set", bytes([0xCC, 0xC1, 0x42, 0x01, b]), bytes([0x42, 0x01, b]), "equals", 50, 100, 4, "baud"),
            RadioStep("query", bytes([0xCC, 0xC0, 0x42, 0x01]), bytes([0xCC, 0x42, 0x01, b]), "equals", 50, 100, 4,
                      "read back"),
            RadioStep("reset", b"\xcc\xff", None, "equals", 100, 100, 1, "radio reset, then wait 100 ms"),
        ]
    if iface in ("digi", "digi_check_version", "digi_24ghz") and baud in _DIGI_BAUD_ID:
        b = _DIGI_BAUD_ID[baud]
        ok = b"OK\r"
        return [
            RadioStep("set", f"ATBD{b}\r".encode(), ok, "contains", 50, 500, 1, "2 s window; 300 ms pause after"),
            RadioStep("query", b"ATBD\r", f"{b}\r".encode(), "contains", 50, 500, 1, "read back"),
            RadioStep("set", b"ATWR\r", ok, "contains", 50, 500, 1),
            RadioStep("reset", b"ATCN\r", None, "contains", 500, 200, 1),
        ]
    return []


# --------------------------------------------------------------------------- network serial server (eth_serial)
def eth_serial(name: str) -> dict:
    """Decode an ``eth_serial`` catalog string into the serial-server settings ScoreConnect pushes to network bots.

    ``mode`` strings are the ScoreLink (I) spellings (``16/17``, ``start/length``, ``start/end``,
    ``delay+framing``); ScoreConnect III uses them for every bot type.  ``stop_char`` is ScoreConnect's default
    ``04h`` for the ``LENGTH`` variants, which have no stop character; ``length`` is recorded but never sent.
    """
    row = ETH_SERIAL[normalize(name)]
    mode, delay, start, stop, length, int_mode = row
    return {"mode": mode, "delay": delay, "start_char": start, "stop_char": stop or "04h", "length": length,
            "interface_mode": int_mode}


# --------------------------------------------------------------------------- catalog helpers
def configs_for_vendor(vendor_name: str) -> list:
    """The wiring options (``connection``, ``hardware``, ``eth_serial`` ...) of a vendor, from catalog.json."""
    from . import catalog
    want = vendor_name.strip().lower()
    for v in catalog().get("vendors", []):
        if str(v.get("name", "")).strip().lower() == want:
            return [dict(c) for c in v.get("configs", [])]
    return []


def plan(vendor_config: dict, pic_version=DEFAULT_PIC_VERSION) -> dict:
    """Everything needed to bring up one catalog wiring option on a ScoreLinkII."""
    hw = hardware_info(vendor_config["hardware"])
    if hw["dynamic"]:
        return {"hardware": hw["name"], "device": "pic", "dynamic": True, "pic_commands": [],
                "command_baud": COMMAND_BAUD, "data_baud": None, "read_timeout_ms": None,
                "eth_serial": eth_serial(vendor_config["eth_serial"]) if vendor_config.get("eth_serial") else None}
    return {
        "hardware": hw["name"],
        "device": hw["device"],
        "pic_commands": pic_commands(hw["name"], vendor_config, pic_version),
        "command_baud": hw["command_baud"],
        "data_baud": hw["baud"],
        "read_timeout_ms": int(vendor_config["read_timeout"]) if vendor_config.get("read_timeout") else None,
        "eth_serial": eth_serial(vendor_config["eth_serial"]) if vendor_config.get("eth_serial") else None,
    }
