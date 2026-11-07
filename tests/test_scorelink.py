import sys
import types

import scorereader as sr


def test_mcp2221_sets_gp2_via_sram_and_gpio(monkeypatch):
    sent = []

    class Dev:
        gp2 = (0xEE, 0xEF)  # not configured as GPIO yet

        def open_path(self, p):
            pass

        def write(self, b):
            sent.append(b)
            self.buf = b

        def read(self, n, t):
            c = self.buf[1]
            r = [c, 0] + [0] * 62
            if c == 0x51:
                r[6], r[7] = Dev.gp2
            if c == 0x61:
                r[22:26] = [0x08, 0x08, 0x08, 0x08]
            if c == 0x60:
                Dev.gp2 = ((self.buf[1 + 10] >> 4) & 1, 0)
            return r

        def close(self):
            pass

    hid = types.ModuleType("hid")
    hid.device = Dev
    hid.enumerate = lambda v, p: [{"path": b"x"}]
    monkeypatch.setitem(sys.modules, "hid", hid)
    monkeypatch.setattr(sys, "platform", "linux")
    m = sr.MCP2221()
    m.set_gp2(True)
    cmds = [b[1] for b in sent]
    assert cmds == [0x51, 0x61, 0x60, 0x50]
    s60 = next(b for b in sent if b[1] == 0x60)
    assert s60[1 + 7] == 0x80 and s60[1 + 8:1 + 12] == [0x08, 0x08, 0x10, 0x08]
    s50 = next(b for b in sent if b[1] == 0x50)
    assert s50[1 + 10:1 + 14] == [0xFF, 1, 0xFF, 0]
    assert all(len(b) == 65 and b[0] == 0 for b in sent)


def test_pic_command_parsing():
    class FakeSer:
        out = b""

        def reset_input_buffer(self):
            pass

        def write(self, b):
            q = b.decode().strip()
            self.out = {">R?": b">R1.14\r", ">B?": b"B6\r", ">M8?": b"\r>M8I1N\r"}.get(q, b"\r")

        def flush(self):
            pass

        def read(self, n):
            c, self.out = self.out[:1], self.out[1:]
            return c

    f = FakeSer()
    assert sr.pic_command(f, ">R?") == "R1.14"
    assert sr.pic_command(f, "B?") == "B6"
    assert sr.pic_command(f, ">M8?") == "M8I1N"
