import logging
import unittest
import io
import itertools
from bitstring import ConstBitStream
from tempfile import TemporaryFile, NamedTemporaryFile
from collections import OrderedDict
from pprint import pprint

import io
import romlib
from romlib import util


class TestArrayDef(unittest.TestCase):
    def setUp(self):
        struct_od = OrderedDict({
            "name": "arr1",
            "label": "arr1",
            "set": "",
            "type": "romstruct_good",
            "offset": "0x06",
            "length": "3",
            "stride": "2",
            "display": "",
            "comment": ""
         })
        primitive_od = OrderedDict({
            "name": "arr1",
            "label": "arr1",
            "set": "",
            "type": "uint",
            "offset": "0x00",
            "length": "1",
            "stride": "1",
            "display": "",
            "comment": ""
        })
        self.maproot = "test/map"
        with open(self.maproot + "/structs/romstruct_good.csv") as f:
            self.sdef = romlib.StructDef.from_file("good", f)
        self.array = romlib.ArrayDef(struct_od, self.sdef)
        self.parray = romlib.ArrayDef(primitive_od, None)

    def test_rom_array_init(self):
        correct = {
            "name": "arr1",
            "length": 3,
            "offset": 0x06*8,
            "stride": 2*8,
            "sdef": self.sdef
        }

        for k, v in correct.items():
            self.assertEqual(getattr(self.array, k), v)

    def test_rom_array_init_primitive(self):
        pa = self.parray
        correct_attribute = {
            "id": "value",
            "label": "arr1",
            "size": 8,
            "type": "uint"
        }
        self.assertEqual(pa.name, pa.sdef.name)
        self.assertEqual(len(pa.sdef.attributes), 1)
        a = next(iter(pa.sdef.attributes.values()))
        for k, v in correct_attribute.items():
            self.assertEqual(getattr(a, k), v)

    def test_rom_array_read(self):
        # Twenty copies of a romstruct.
        data = b'\x34\x56' * 20
        ntf = NamedTemporaryFile()
        ntf.write(data)
        ntf.seek(0)
        with open(ntf.name, "rb") as f:
            for s in self.array.read(f):
                self.assertEqual(s.data['fld3'], "0110")


class TestStruct(unittest.TestCase):
    def setUp(self):
        self.maproot = "test/map"
        file1 = self.maproot + "/structs/romstruct_good.csv"
        file2 = self.maproot + "/structs/romstruct_good2.csv"
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

    def test_changeset(self):
        s = romlib.Struct(self.d1, self.data)
        cs = s.changeset(0)
        correct = {
            0: 0x34,
            1: 0x56
        }
        self.assertEqual(cs, correct)

    def test_changeset_at_offset(self):
        s = romlib.Struct(self.d1, self.data)
        o = 0x666
        cs = s.changeset(o)
        correct = {
            o: 0x34,
            o+1: 0x56
        }
        self.assertEqual(cs, correct)


class TestStructDef(unittest.TestCase):
    def setUp(self):
        self.maproot = "test/map"
        sd1file = self.maproot + "/structs/romstruct_good.csv"
        sd2file = self.maproot + "/structs/romstruct_good2.csv"
        self.bits = ConstBitStream('0x3456')
        with open(sd1file) as f1, open(sd2file) as f2:
            self.sd1 = romlib.StructDef.from_file("good", f1)
            self.sd2 = romlib.StructDef.from_file("good", f2)
        self.sd = self.sd1

    def test_malformed_romstruct_file(self):
        badfile = self.maproot + "/binary/romstruct_malformed.csv"
        self.assertRaises(Exception, romlib.StructDef, badfile)

    def test_basic_initialization(self):
        self.assertEqual(self.sd.name, "good")
        self.assertEqual(self.sd.attributes['fld1'].label, "Field 1")
        self.assertEqual(self.sd.attributes['fld2'].order, -1)

    def test_size_conversion(self):
        self.assertEqual(self.sd.attributes['fld2'].size, 4)
        self.assertEqual(self.sd.attributes['fld1'].size, 8)

    def test_correct_namefield(self):
        self.assertEqual(self.sd.namefield.id, 'fld3')

    def test_namefield_exception(self):
        with self.assertRaises(AttributeError):
            self.sd2.namefield

    def test_keyorder(self):
        keys = itertools.chain(self.sd1.attributes.keys(),
                               self.sd2.attributes.keys())
        keys = romlib.StructDef.attribute_order(keys, [self.sd1, self.sd2])
        correct = [
            'fld2',
            'fld3',
            'fld5',
            'fld6',
            'fld4',
            'fld1'
        ]
        self.assertEqual(keys, correct)

    @unittest.skip("Array not reimplemented yet.")
    def test_load_from_array(self):
        arraydict = OrderedDict({"name": "arrprim",
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


class TestRomMap(unittest.TestCase):
    def setUp(self):
        self.maproot = "test/map"
        self.map = romlib.RomMap(self.maproot)

    def test_rom_map_array_load(self):
        self.assertEqual(len(self.map.arrays), 4)
        self.assertEqual(self.map.arrays['arr1'].name, "arr1")

    def test_rom_map_struct_load(self):
        self.assertEqual(len(self.map.sdefs), 2)
        self.assertTrue('romstruct_good' in self.map.sdefs)
        s = self.map.sdefs['romstruct_good']
        self.assertTrue('fld1' in s.attributes)
        self.assertEqual(s.attributes['fld1'].label, "Field 1")

    def test_changeset(self):
        cs = self.map.changeset("test/out")
        correct = {i: 0x66 for i in range(18)}
        self.assertEqual(cs, correct)


class TestFunctions(unittest.TestCase):
    pass
