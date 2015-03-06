import unittest
from collections import OrderedDict
from tempfile import TemporaryFile, NamedTemporaryFile
from io import BytesIO, StringIO

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

    def test_ips_textualize(self):
        p = BytesIO(b'PATCH\x00\x00\x00\x00\x01\x03'
                    b'\x00\x00\x01\x00\x04\x01\x01\x01\xAAEOF')
        text = "PATCH\n0x000000:1:03\n0x000001:4:010101AA\nEOF\n"
        result = StringIO("")
        patch.IPSPatch.textualize(p, result)
        self.assertEqual(result.getvalue(), text)

    def test_ips_textualize_rle(self):
        p = BytesIO(b'PATCH\x00\x00\x00\x00\x00\x00\x02\xFFEOF')
        text = "PATCH\n0x000000:!2:FF\nEOF\n"
        result = StringIO("")
        patch.IPSPatch.textualize(p, result)
        self.assertEqual(result.getvalue(), text)

    def test_ips_compile(self):
        p = bytes(b'PATCH\x00\x00\x00\x00\x01\x03'
                  b'\x00\x00\x01\x00\x04\x01\x01\x01\xAAEOF')
        text = StringIO("PATCH\n0x000000:1:03\n0x000001:4:010101AA\nEOF\n")
        result = BytesIO()
        patch.IPSPatch.compile(text, result)
        self.assertEqual(result.getvalue(), p)

    def test_ips_compile_rle(self):
        p = bytes(b'PATCH\x00\x00\x00\x00\x00\x00\x02\xFFEOF')
        text = StringIO("PATCH\n0x000000:!2:FF\nEOF\n")
        result = BytesIO()
        patch.IPSPatch.compile(text, result)
        self.assertEqual(result.getvalue(), p)

    def test_ips_compile_line_skip(self):
        p = bytes(b'PATCH\x00\x00\x00\x00\x00\x00\x02\xFFEOF')
        text = StringIO("PATCH\n#\n\n0x000000:!2:FF\nEOF\n")
        result = BytesIO()
        patch.IPSPatch.compile(text, result)
        self.assertEqual(result.getvalue(), p)