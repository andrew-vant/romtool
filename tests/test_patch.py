import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile
from io import BytesIO, StringIO

import romlib
from romlib import patch

class TestPatch(unittest.TestCase):
    def test_from_blocks(self):
        changes = {0x00: b"\x00\x00",
                   0x10: b"\x01\x02\x03"}
        p = patch.Patch.from_blocks(changes)
        self.assertEqual(p.changes[0], 0)
        self.assertEqual(p.changes[1], 0)
        self.assertEqual(p.changes[0x10], 1)
        self.assertEqual(p.changes[0x11], 2)
        self.assertEqual(p.changes[0x12], 3)

    def test_from_ips(self):
        ips = BytesIO(b'PATCH\x00\x00\x00\x00\x01\x03'
                      b'\x00\x00\x01\x00\x04\x01\x01\x01\xAAEOF')
        p = patch.Patch.from_ips(ips)
        self.assertEqual(p.changes[0], 3)
        self.assertEqual(p.changes[1], 1)
        self.assertEqual(p.changes[2], 1)
        self.assertEqual(p.changes[3], 1)
        self.assertEqual(p.changes[4], 0xAA)
        self.assertEqual(len(p.changes), 5)

    def test_from_ipst(self):
        ipst = StringIO("PATCH\n000000:0001:03\n000001:0004:010101AA\nEOF\n")
        p = patch.Patch.from_ipst(ipst)
        self.assertEqual(p.changes[0], 3)
        self.assertEqual(p.changes[1], 1)
        self.assertEqual(p.changes[2], 1)
        self.assertEqual(p.changes[3], 1)
        self.assertEqual(p.changes[4], 0xAA)
        self.assertEqual(len(p.changes), 5)

    def test_to_ips(self):
        changes = {0: 1,
                   5: 5,
                   6: 6,
                   10: 10}
        intended_output = b"".join([
            "PATCH".encode("ascii"),
            b'\x00\x00\x00\x00\x01\x01',
            b'\x00\x00\x05\x00\x02\x05\x06',
            b'\x00\x00\x0A\x00\x01\x0A',
            "EOF".encode("ascii")])
        p = patch.Patch(changes)

        with TemporaryFile("wb+") as f:
            p.to_ips(f)
            f.seek(0)
            self.assertEqual(f.read(), intended_output)

    def test_to_ipst(self):
        changes = {0: 1,
                   5: 5,
                   6: 6,
                   10: 10}
        lines = ["PATCH",
                 "000000:0001:01",
                 "000005:0002:0506",
                 "00000A:0001:0A",
                 "EOF\n"]
        intended_output = ("\n".join(lines))
        p = patch.Patch(changes)
        with TemporaryFile("wt+") as f:
            p.to_ipst(f)
            f.seek(0)
            self.assertEqual(f.read(), intended_output)

    def test_ips_bogoaddr_error(self):
        changes = {patch._ips_bogo_address: 0}
        p = patch.Patch(changes)
        with TemporaryFile("wb+") as f:
            self.assertRaises(patch.PatchValueError, p.to_ips, f)

    def test_ips_bogoaddr_supplied(self):
        changes = {patch._ips_bogo_address: 0}
        bogobyte = 0x10
        intended_output = b"".join([
            "PATCH".encode("ascii"),
            b'\x45\x4f\x45\x00\x02\x10\x00',
            "EOF".encode("ascii")])
        p = patch.Patch(changes)
        with TemporaryFile("wb+") as f:
            p.to_ips(f, bogobyte)
            f.seek(0)
            self.assertEqual(f.read(), intended_output)

    def test_ips_change_concatenation(self):
        changes = {0x00: b"\x00\x00",
                   0x02: b"\x01\x02\x03"}

        intended_output = b"".join([
            "PATCH".encode("ascii"),
            b'\x00\x00\x00\x00\x05\x00\x00\x01\x02\x03',
            "EOF".encode("ascii")])

        with TemporaryFile("wb+") as f:
            patch.IPSPatch(changes).write(f)
            f.seek(0)
            self.assertEqual(f.read(), intended_output)
