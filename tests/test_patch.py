import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile

import ureflib
from ureflib import patch

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

    @unittest.expectedFailure
    def test_ips_0x454f46(self):
        self.assertFalse(True)

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
