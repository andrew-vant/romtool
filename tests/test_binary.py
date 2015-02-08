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
        self.typedict = {
            "romstruct_good": ureflib.RomStruct.from_file(
                              "tests/map/structs/romstruct_good.csv")}

        self.array = ureflib.RomArray(od, self.typedict)

    def test_rom_array_size_conversion(self):
        self.assertEqual(self.array['offset'], 0x06*8)
        self.assertEqual(self.array['stride'], 2*8)

    def test_rom_array_struct_attachment(self):
        self.assertEqual(self.array.struct, self.typedict['romstruct_good'])

    def test_rom_array_read(self):
        # Twenty copies of a romstruct.
        bits = ConstBitStream('0x3456') * 20
        for entry in self.array.read(bits):
            self.assertEqual(entry['fld3'], "0110")

class TestRomStruct(unittest.TestCase):
    def setUp(self):
        self.bits = ConstBitStream('0x3456')
        self.struct = ureflib.RomStruct.from_file("tests/map/structs/romstruct_good.csv")

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


class TestRomMap(unittest.TestCase):
    def setUp(self):
        self.map = ureflib.RomMap("tests/map")

    def test_rom_map_array_load(self):
        self.assertEqual(len(self.map.arrays), 3)
        self.assertEqual(self.map.arrays[0]['name'], "arr1")

    def test_rom_map_struct_load(self):
        self.assertEqual(len(self.map.structs), 1)
        self.assertTrue('romstruct_good' in self.map.structs)
        s = self.map.structs['romstruct_good']
        self.assertTrue('fld1' in s)
        self.assertEqual(s['fld1']['label'], "Field 1")

    def test_rom_map_dump(self):
        # FIXME: Uses real files.
        rompath = "resources/testrom.smc"
        specpath = "tests/map.testrom"
        outpath = "tests/temp"
        rom = open(rompath, "rb")
        map = ureflib.RomMap(specpath)
        map.dump(rom, outpath, True)
        rom.close()

class TestFunctions(unittest.TestCase):
    def test_hexify(self):
        self.assertEqual(ureflib.binary.hexify(4, 8), "0x04")
        self.assertEqual(ureflib.binary.hexify(4), "0x4")
