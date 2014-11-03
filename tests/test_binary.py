import logging
import unittest
from bitstring import ConstBitStream
from tempfile import TemporaryFile
from collections import OrderedDict

import ureflib
from ureflib import util

class TestRomArray(unittest.TestCase):
    def setUp(self):
        rp = ureflib.RomArray.requiredproperties
        od = OrderedDict({"name": "arr1",
                          "type": "romstruct_good",
                          "offset": "0x06",
                          "length": "3",
                          "stride": "2",
                          "comment": ""})
        self.typedict = {"romstruct_good":
                    ureflib.RomStruct("tests/binary/romstruct_good.csv")}

        self.array = ureflib.RomArray(od, self.typedict)

    def test_rom_array_size_conversion(self):
        self.assertEqual(self.array['offset'], 0x06*8)
        self.assertEqual(self.array['stride'], 2*8)

    def test_rom_array_struct_attachment(self):
        self.assertEqual(self.array.struct, self.typedict['romstruct_good'])

    def test_rom_array_read(self):
        pass

class TestRomStruct(unittest.TestCase):
    def setUp(self):
        self.bits = ConstBitStream('0x3456')
        self.struct = ureflib.RomStruct("tests/binary/romstruct_good.csv")

    def test_malformed_romstruct_file(self):
        badfile = "tests/binary/romstruct_malformed.csv"
        self.assertRaises(Exception, ureflib.RomStruct, badfile)

    def test_read_struct(self):
        s = self.struct.read(self.bits, 0)
        self.assertEqual(s['fld3'], "0110")

    def test_read_struct_order(self):
        s = self.struct.read(self.bits, 0)
        self.assertEqual(list(s.keys()), ['fld1','fld3','fld2'])

    def test_struct_hextag(self):
        s = self.struct.read(self.bits, 0)
        s = self.assertEqual(s['fld1'], "0x34")


class TestRomStructField(unittest.TestCase):
    def setUp(self):
        rp = ureflib.RomStructField.requiredproperties
        od = OrderedDict()
        for p in rp:
            od[p] = p+"val"
        od['size'] = "b14"
        od['tags'] = "what|is|this"
        self.basedict = od
        self.rsf = ureflib.RomStructField(od)

    def test_RSF_size_conversion(self):
        self.assertEqual(self.rsf['size'], 14)

    def test_RSF_tag_split(self):
        self.assertEqual(len(self.rsf.tags), 3)
        self.assertEqual(self.rsf.tags, {"what","is","this"})

    def test_missing_fields(self):
        self.basedict.popitem(last=False)
        self.assertRaises(ureflib.SpecFieldMismatch,
                          ureflib.RomStructField,
                          self.basedict)

