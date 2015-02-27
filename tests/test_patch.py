import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile

import romlib
from romlib import patch

class TestIPSPatch(unittest.TestCase):
    def test_ips_basic(self):

        changes = {0x00: b"\x00\x00",
                   0x10: b"\x01\x02\x03"}

        intended_output = b"".join([
            "PATCH".encode("ascii"),
            b'\x00\x00\x00\x00\x02\x00\x00',
            b'\x00\x00\x10\x00\x03\x01\x02\x03',
            "EOF".encode("ascii")])

        with TemporaryFile("wb+") as f:
            patch.IPSPatch(changes).write(f)
            f.seek(0)
            self.assertEqual(f.read(), intended_output)

    def test_ips_bogoaddr_error(self):
        changes = {patch.IPSPatch.bogoaddr: b"\x00\x00"}
        self.assertRaises(ValueError, patch.IPSPatch, changes)

    def test_ips_bogoaddr_workaround(self):
        changes = {patch.IPSPatch.bogoaddr: b"\x00\x00"}
        bogobyte = 0x10

        intended_output = b"".join([
            "PATCH".encode("ascii"),
            b'\x45\x4f\x45\x00\x03\x10\x00\x00',
            "EOF".encode("ascii")])

        with TemporaryFile("wb+") as f:
            patch.IPSPatch(changes, bogobyte).write(f)
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
