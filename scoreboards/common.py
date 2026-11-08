"""Generic decode helpers shared by vendor decoders.

All character helpers return a one-character string and fall back to " " (blank) when the byte can't be
decoded. Vendor-specific digit tables (Nevco, Eversan, Nautronic, …) live in the vendor's own module.
"""
from __future__ import annotations

# Standard 7-segment patterns (bit 7 = decimal point/colon, ignored). 0x6F and 0x67 are both "9".
SEG7 = {0x3F: "0", 0x06: "1", 0x5B: "2", 0x4F: "3", 0x66: "4", 0x6D: "5", 0x7D: "6", 0x07: "7", 0x7F: "8",
        0x67: "9", 0x6F: "9", 0x00: " "}


def digit(b: int) -> str:
    """7-segment byte -> digit; blank segments -> " "; unknown pattern -> " "."""
    return SEG7.get(b & 0x7F, " ")


def digit_nb(b: int) -> str:
    """Like digit() but a blank (or unknown) pattern reads as "0" ("no blank")."""
    ch = SEG7.get(b & 0x7F, "0")
    return "0" if ch == " " else ch


def ascii_char(b: int, suppress_leading_zero: bool = False) -> str:
    """Printable ASCII byte -> character; anything else -> " ". Optionally turn "0" into " "."""
    ch = chr(b) if 32 <= b < 127 else " "
    return " " if suppress_leading_zero and ch == "0" else ch


def ascii_text(data) -> str:
    return "".join(ascii_char(b) for b in data)


def ascii_digit_or_blank(b: int) -> str:
    ch = ascii_char(b)
    return ch if "0" <= ch <= "9" else " "


def dec(b: int, i: int, digits: int = 2, blank_left: bool = False) -> str:
    """Decimal digit i of byte value b, counting from the right (i=0 ones, 1 tens, 2 hundreds).

    With blank_left, leading zeros (except the last digit) become blanks, so dec(5, 1, 2, True) == " ".
    """
    s = list(f"{b:0{digits}d}")
    if blank_left:
        for k in range(digits - 1):
            if s[k] != "0":
                break
            s[k] = " "
    idx = digits - 1 - i
    return s[idx] if 0 <= idx < len(s) else " "


def bcd_raw(b: int, i: int) -> str:
    """Hex nibble i of b as a character (i=0 low nibble, 1 high nibble)."""
    return f"{b & 0xFF:02X}"[1 - i]


def bcd(b: int, i: int, blank: str | None = None, mask: int | None = None) -> str:
    """BCD nibble i (0 = low, 1 = high) as a digit.

    Default: nibbles A-F read as blank. blank="X": only that hex character reads as blank.
    mask=0x..: the byte is masked first and only "F" reads as blank.
    """
    if mask is not None:
        ch = f"{b & mask & 0xFF:02X}"[1 - i]
        return " " if ch == "F" else ch
    ch = f"{b & 0xFF:02X}"[1 - i]
    if blank is not None:
        return " " if ch == blank else ch
    return " " if ch in "ABCDEF" else ch


def bcd_zero_blank(b: int, i: int) -> str:
    """BCD nibble i; nibbles above 9 read as "0"."""
    ch = f"{b & 0xFF:02X}"[1 - i]
    return "0" if ch > "9" else ch


def mask_one_zero(b: int, mask: int) -> str:
    return "1" if b & mask else "0"


def blank_to_zero(ch: str) -> str:
    return "0" if ch == " " else ch


def blank_zero(ch: str, hundreds: str) -> str:
    """Blank a leading zero: keep ch if a higher digit is shown or ch isn't "0"."""
    if hundreds != " ":
        return ch
    return ch if ch != "0" else " "


def bit_count(b: int, kind: str) -> str:
    """Ball/strike/out lamps packed as bits. kind "B" (balls, bits 0-2), "S" (strikes, bits 2-3), "O" (outs, bits 0-1)."""
    if kind == "B":
        return {0: "0", 1: "1", 3: "2", 7: "3"}.get(b & 0x07, " ")
    if kind == "S":
        return {0: "0", 4: "1", 12: "2"}.get(b & 0x0C, " ")
    if kind == "O":
        return {0: "0", 1: "1", 3: "2"}.get(b & 0x03, " ")
    return " "


# --------------------------------------------------------------------------- checksums
def sum8(data, start: int = 0, end: int | None = None) -> int:
    """Sum of data[start:end] modulo 256."""
    return sum(data[start:end]) & 0xFF


def sum16(data, start: int = 0, end: int | None = None) -> int:
    return sum(data[start:end]) & 0xFFFF


def xor8(data, start: int = 0, end: int | None = None) -> int:
    x = 0
    for b in data[start:end]:
        x ^= b
    return x


def crc16_ccitt(data, start: int = 0, end: int | None = None, poly: int = 0x1021, init: int = 0xFFFF) -> int:
    crc = init
    for b in data[start:end]:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def text(c: dict, *keys: str) -> str:
    """Join contract characters, e.g. text(c, "HomeScoreTens", "HomeScoreOnes")."""
    return "".join(str(c.get(k, " ")) for k in keys)
