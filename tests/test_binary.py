import logging
import unittest
import ureflib.binary as binary
import ureflib.specs as specs
from bitstring import ConstBitStream
from tempfile import TemporaryFile

class TestBinaryFunctions(unittest.TestCase):
    def setUp(self):
        self.bits = ConstBitStream('0x3456')
        f = open("tests/specfiles/test_struct.csv")
        self.spec = list(specs.StructFieldReader(f))

    def test_read_struct(self):
        s = binary.read(self.bits, self.spec, 0)
        self.assertEqual(s['fld1'], 0x34)
        self.assertEqual(s['fld2'], 0x5)
        self.assertEqual(s['fld3'], "0110")

    def test_read_struct_order(self):
        s = binary.read(self.bits, self.spec, 0)
        self.assertEqual(list(s.keys()), ['fld1','fld3','fld2'])

if __name__ == '__main__':
    unittest.main()

