import unittest
from types import SimpleNamespace

import yaml
from addict import Dict

from romlib.io import Stream

class TestStream(unittest.TestCase):
    def setUp(self):
        self.stream = Stream(b'\x01\x02\x03\x04')

    def test_read_int(self):
        self.stream.pos = 0
        self.assertEqual(1, self.stream.read_int('uint', 8, 0, ''))

    def test_write_int(self):
        self.stream.pos = 0
        self.stream.write_int(10, 'uint', 8, 0, '')
        self.assertEqual(self.stream.bytes[0], 10)

    def test_read_str(self):
        stream = Stream(b'thingy')
        stream.pos = 0
        s = stream.read_str('str', len(stream), None, 'ascii')
        self.assertEqual(s, 'thingy')

    def test_write_str(self):
        stream = Stream(bytes(8))
        s = "thingy"
        stream.pos = 0
        stream.write_str("thingy", 'str', len(s)*8, None, 'ascii')
        stream.pos = 0
        self.assertEqual(stream.read_str('str', len(s)*8, None, 'ascii'), s)
