import logging
import unittest
import io
import itertools
from bitstring import ConstBitStream
from tempfile import TemporaryFile, NamedTemporaryFile
from collections import OrderedDict
from pprint import pprint

import romlib
from romlib import util

"""
class TestArrayDef(unittest.TestCase):
    def setUp(self):
        rp = romlib.ArrayDef.requiredproperties
        od = OrderedDict({"name": "arr1",
                          "label": "arr1",
                          "set": "",
                          "type": "romstruct_good",
                          "offset": "0x06",
                          "length": "3",
                          "stride": "2",
                          "comment": ""})
        self.typedict = {
            "romstruct_good": romlib.StructDef.from_file(
                              "tests/map/structs/romstruct_good.csv")}

        self.array = romlib.ArrayDef(od, self.typedict)

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
"""
class TestStruct(unittest.TestCase):
    def setUp(self):
        file1 = "tests/map/structs/romstruct_good.csv"
        file2 = "tests/map/structs/romstruct_good2.csv"
        with open(file1) as f1, open(file2) as f2:
            self.d1 = romlib.StructDef.from_file("good1", f1)
            self.d2 = romlib.StructDef.from_file("good2", f2)
        self.data = b'\x34\x56'
        self.bits = ConstBitStream(self.data)

    def test_struct_from_bits(self):
        s = romlib.Struct(self.d1, self.bits)
        self.assertEqual(s.data['fld1'], 0x34)
        self.assertEqual(s.data['fld3'], "0110")

    def test_struct_from_bytes(self):
        s = romlib.Struct(self.d1, self.data)
        self.assertEqual(s.data['fld1'], 0x34)
        self.assertEqual(s.data['fld3'], "0110")

    def test_struct_from_file(self):
        with NamedTemporaryFile("w+b") as ntf:
            ntf.write(self.data)
            ntf.seek(0)
            with open(ntf.name, "rb") as f:
                s = romlib.Struct(self.d1, f)
                self.assertEqual(s.data['fld1'], 0x34)
                self.assertEqual(s.data['fld3'], "0110")

    def test_struct_from_iddict(self):
        d = {'fld1': 1,
             'fld2': 1,
             'fld3': "0110"}
        s = romlib.Struct(self.d1, d)
        self.assertEqual(s.data['fld1'], 1)
        self.assertEqual(s.data['fld3'], "0110")

    def test_struct_to_merged_od(self):
        s1 = romlib.Struct(self.d1, self.bits)
        s2 = romlib.Struct(self.d2, self.bits)
        od = romlib.Struct.to_mergedict([s1, s2])
        correct = {
            'fld1': 52,
            'fld2': 5,
            'fld3': '0110',
            'fld4': 52,
            'fld5': 5,
            'fld6': '0110'
        }
        self.assertEqual(od, correct)

    def test_struct_to_bytes(self):
        s = romlib.Struct(self.d1, self.bits)
        self.assertEqual(s.to_bytes(), b'\x34\x56')

    def test_keyorder(self):
        keys = itertools.chain(self.d1.attributes.keys(),
                               self.d2.attributes.keys())
        keys = romlib.StructDef.attribute_order(keys, [self.d1, self.d2])
        correct = [
            'fld1',
            'fld4',
            'fld3',
            'fld6',
            'fld2',
            'fld5'
        ]
        self.assertEqual(keys, correct)

"""
class TestStructDef(unittest.TestCase):
    def setUp(self):
        self.bits = ConstBitStream('0x3456')
        self.struct = romlib.StructDef.from_file("tests/map/structs/romstruct_good.csv")

    def test_malformed_romstruct_file(self):
        badfile = "tests/binary/romstruct_malformed.csv"
        self.assertRaises(Exception, romlib.StructDef, badfile)

    def test_read_struct(self):
        s = self.struct.read(self.bits, 0)
        self.assertEqual(s['fld3'], "0110")

    def test_read_struct_order(self):
        s = self.struct.read(self.bits, 0)
        self.assertEqual(list(s.keys()), ['fld1','fld3','fld2'])

    def test_struct_hextag(self):
        s = self.struct.read(self.bits, 0)
        s = self.assertEqual(s['fld1'], "0x34")

    def test_load_from_array(self):
        arraydict = OrderedDict({ "name": "arrprim",
                                  "label": "Primitive",
                                  "set": "none",
                                  "type": "uintle",
                                  "offset": "0x06",
                                  "length": "3",
                                  "stride": "2",
                                  "display": "",
                                  "tags": "",
                                  "comment": ""})
        s = romlib.StructDef.from_primitive_array(arraydict)
        self.assertEqual(s['arrprim']['id'], arraydict['name'])
        self.assertEqual(s['arrprim']['type'], arraydict['type'])
        self.assertEqual(s['arrprim']['size'], 16)

    @unittest.skip("Test not implemented yet.")
    def test_pointer_dereferencing(self):
        pass

    def test_extract_fields_from_object(self):
        fields = [("fld1", "something"),
                  ("fld2", "something 2"),
                  ("fld3", "something 3"),
                  ("fld4", "something 4"),
                  ("fld5", "something 5")]

        me = OrderedDict(fields[0:3])
        source = OrderedDict(fields)
        self.assertEqual(self.struct.extract(source), me)

    def test_extract_fields_by_label(self):
        me = OrderedDict([("fld1", "something"),
                          ("fld2", "something 2"),
                          ("fld3", "something 3")])

        source = OrderedDict([("Field 1", "something"),
                              ("Field 2", "something 2"),
                              ("Field 3", "something 3"),
                              ("Field 4", "something 4"),
                              ("Field 5", "something 5")])

        self.assertEqual(self.struct.extract(source), me)

class TestRomMap(unittest.TestCase):
    def setUp(self):
        self.map = romlib.RomMap("tests/map")

    def test_rom_map_array_load(self):
        self.assertEqual(len(self.map.arrays), 4)
        self.assertEqual(self.map.arrays['arr1']['name'], "arr1")

    def test_rom_map_struct_load(self):
        self.assertEqual(len(self.map.structs), 1)
        self.assertTrue('romstruct_good' in self.map.structs)
        s = self.map.structs['romstruct_good']
        self.assertTrue('fld1' in s)
        self.assertEqual(s['fld1']['label'], "Field 1")

class TestFunctions(unittest.TestCase):
    def test_hexify(self):
        self.assertEqual(romlib.binary.hexify(4, 8), "0x04")
        self.assertEqual(romlib.binary.hexify(4), "0x4")
        self.assertEqual(romlib.binary.hexify(4, 12), "0x0004")
"""
