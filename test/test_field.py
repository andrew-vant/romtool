import unittest
import logging
from types import SimpleNamespace

import yaml
from addict import Dict

import romtool.text as text
from romtool.io import BitArrayView as Stream
from romtool.field import Field, StructField
from romtool.rom import Rom
from romtool.rommap import RomMap
from romtool.structures import Structure, BitField, TableSpec, Table, Index
from romtool.util import bytes2ba

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.specs =  [{'id': 'one',
                        'name': 'One Label',
                        'type': 'uint',
                        'offset': '0',
                        'size': '1',
                        'arg': '0'},
                       {'id': 'two',
                        'name': 'Two Label',
                        'type': 'uint',
                        'offset': '1',
                        'size': '1',
                        'arg': '0'},
                       {'id': 'modded',
                        'name': 'Modded Label',
                        'type': 'uint',
                        'offset': '2',
                        'size': '1',
                        'arg': '1'},
                       {'id': 'str',
                        'name': 'String',
                        'type': 'str',
                        'offset': '4',
                        'size': '6',
                        'arg': '',
                        'display': 'ascii'},
                       {'id': 'strb',
                        'name': 'strb',
                        'type': 'bytes',
                        'offset': '4',
                        'size': '6',
                        'arg': '',
                        'display': ''},
                       {'id': 'strz',
                        'name': 'String 2',
                        'type': 'strz',
                        'offset': '4',
                        'size': '7',
                        'arg': '',
                        'display': ''},
                       {'id': 'name',
                        'name': 'Name',
                        'type': 'str',
                        'offset': '4',
                        'size': '6',
                        'arg': '',
                        'display': 'ascii'}]
        self.fields = [Field.from_tsv_row(row) for row in self.specs]
        self.scratch = Structure.define('scratch', self.fields)
        self.rom = Rom(b'\x01\x02\x03\x04abcdef\x00DEADBEEFDEADBEEF',
                       RomMap(ttables=text.tt_codecs))
        self.struct = self.scratch(self.rom.data, self.rom)

    def test_define_struct(self):
        self.assertTrue(issubclass(self.scratch, Structure))

    def test_instantiate_struct(self):
        struct = self.struct
        self.assertIsInstance(struct, self.scratch)

    def test_read_struct_attr(self):
        struct = self.struct
        self.assertEqual(struct.one, 1)

    def test_read_struct_item(self):
        struct = self.struct
        self.assertEqual(struct['One Label'], 1)

    def test_write_struct_attr(self):
        struct = self.struct
        struct.one = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['One Label'], 2)

    def test_write_struct_item(self):
        struct = self.struct
        struct['One Label'] = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['One Label'], 2)

    def test_write_struct_stream_contents(self):
        struct = self.struct
        # Test that writes do the right thing with the underlying stream
        struct.one = 2
        struct.view.pos = 0
        self.assertEqual(struct.view.bytes[0], 2)

    def test_read_field_with_offset(self):
        struct = self.struct
        self.assertEqual(struct.two, 2)
        self.assertEqual(struct['Two Label'], 2)

    def test_write_field_with_offset(self):
        struct = self.struct
        struct.two = 4
        self.assertEqual(struct.two, 4)
        self.assertEqual(struct['Two Label'], 4)

    def test_modded_field(self):
        struct = self.struct
        self.assertEqual(struct.modded, 4)
        struct.modded = 4
        self.assertEqual(struct.view.bytes[2], 3)
        self.assertEqual(struct.modded, 4)

    def test_read_string_field(self):
        self.assertEqual(self.struct.str, 'abcdef')

    def test_write_string_field(self):
        struct = self.struct
        struct.str = 'zyxwvu'
        expected = b'\x01\x02\x03\x04zyxwvu\x00DEADBEEFDEADBEEF'
        self.assertEqual(struct.str, 'zyxwvu')
        self.assertEqual(struct.view.bytes, expected)

    def test_oversized_string(self):
        with self.assertRaises(ValueError):
            self.struct.str = 'abcdefghy'

    def test_overrun_warning(self):
        with self.assertLogs('romtool.field', logging.WARNING):
            self.struct.strz = 'abcdefg'

    def test_undersized_string(self):
        struct = self.struct
        struct.str = 'abc'
        self.assertEqual(struct.strb, b'abc   ')
        self.assertEqual(struct.str, 'abc')

    def test_repr(self):
        self.assertEqual(repr(self.struct), "<scratch@0x00 (abcdef)>")

    def test_iteration_keys(self):
        self.assertEqual(set(self.struct.keys()),
                         set(f['name'] for f in self.specs))

    @unittest.skip("Test not implemented yet")
    def test_copy(self):
        raise NotImplementedError


class TestSubstructures(unittest.TestCase):
    def setUp(self):
        subfields = [{'id': 'one',
                      'name': 'One Label',
                      'type': 'uint',
                      'offset': '0',
                      'size': '1',
                      'unit': 'bits',
                      'display': 'J',
                      'arg': '0'},
                     {'id': 'two',
                      'name': 'Two Label',
                      'type': 'uint',
                      'offset': '2',
                      'size': '1',
                      'unit': 'bits',
                      'display': 'Q',
                      'arg': '0'}]
        fields = [{'id': 'sub',
                   'name': 'sub',
                   'type': 'flags',
                   'offset': '0',
                   'size': '2',
                   'unit': 'bits',
                   'display': None,
                   'arg': None,}]
        self.cls_flags = BitField.define_from_rows('flags', subfields)
        self.cls_struct = Structure.define_from_rows(
            'scratch', fields, {'flags': StructField}
        )
        rmap = RomMap(
            structs={s.__name__: s for s in [self.cls_flags, self.cls_struct]},
        )
        self.rom = Rom(bytes([0b00000001]), rmap)

    def test_substruct(self):
        struct = self.cls_struct(self.rom.data, self.rom)
        self.assertTrue(struct.sub.one)



class TestBitField(unittest.TestCase):
    def setUp(self):
        self.data = bytes2ba(bytes([0b10000000]))
        self.specs = [{'id': 'one',
                       'name': 'One Label',
                       'type': 'uint',
                       'offset': '0',
                       'size': '1',
                       'unit': 'bits',
                       'display': 'J',
                       'arg': '0'},
                      # the extra 'unknown' field is here to catch a bug where
                      # parsing was iterating over fields in sorted order
                      # instead of the order used in the definition
                      {'id': 'unk',
                       'name': 'Unknown',
                       'type': 'uint',
                       'offset': '1',
                       'size': '1',
                       'unit': 'bits',
                       'display': 'U',
                       'arg': '0'},
                      {'id': 'two',
                       'name': 'Two Label',
                       'type': 'uint',
                       'offset': '2',
                       'size': '1',
                       'unit': 'bits',
                       'display': 'Q',
                       'arg': '0'}]
        self.fields = [Field.from_tsv_row(row) for row in self.specs]
        self.scratch = BitField.define('scratch', self.fields)

    def test_define(self):
        self.assertTrue(issubclass(self.scratch, BitField))

    def test_construction(self):
        bf = self.scratch(Stream(self.data))
        self.assertIsInstance(bf, BitField)
        self.assertTrue(bf.one)
        self.assertFalse(bf.two)

    def test_str(self):
        bf = self.scratch(Stream(self.data))
        self.assertEqual(str(bf), 'Juq')

    def test_repr(self):
        bf = self.scratch(Stream(self.data))
        self.assertEqual(repr(bf), '<scratch@0x00 (Juq)>')

    def test_parse(self):
        bf = self.scratch(Stream(self.data))
        bf.parse("juQ")
        self.assertFalse(bf.one)
        self.assertTrue(bf.two)
        self.assertEqual(str(bf), "juQ")


class TestIndex(unittest.TestCase):
    def test_make_index(self):
        index = Index(0, 4, 1)
        self.assertEqual(index, (0, 1, 2, 3))


class TestTable(unittest.TestCase):
    def setUp(self):
        self.struct_spec =  [{'id': 'one',
                              'name': 'One Label',
                              'type': 'uint',
                              'offset': '0',
                              'size': '1',
                              'arg': '0'}]
        self.fields = [Field.from_tsv_row(row) for row in self.struct_spec]
        self.scratch = Structure.define('scratch', self.fields)
        self.rmap = RomMap(structs={'scratch': self.scratch})
        self.rom = Rom(b'\x00\x01\x02\x03abcdef', self.rmap)
        self.stream = Stream(self.rom.data)

    def test_primitive_array_construction(self):
        spec = TableSpec('t1', 'uint', count=4, offset=0, stride=1)
        array = Table(self.rom, self.stream, spec)
        self.assertEqual(len(array), 4)
        self.assertEqual(len(array.index), 4)
        for i in range(4):
            self.assertEqual(array[i], i)

    def test_structure_array_construction(self):
        spec = TableSpec('t1', 'scratch', count=4, offset=0, stride=1)
        array = Table(self.rom, self.stream, spec)
        self.assertIsInstance(array[0], self.scratch)
        self.assertEqual(len(array), 4)
        self.assertEqual(len(array.index), 4)
        for i in range(4):
            self.assertEqual(array[i].one, i)

    def test_indexed_table(self):
        ispec = TableSpec('t1', 'uint', count=4, offset=0, stride=1)
        tspec = TableSpec('t2', 'scratch')
        index = Table(self.rom, self.stream, ispec)
        table = Table(self.rom, self.stream, tspec, index)
        for i in range(4):
            self.assertEqual(table[i].one, i)

    def test_primitive_table(self):
        ispec = TableSpec('t1', 'uint', count=4, offset=0, stride=1)
        tspec = TableSpec('t2', 'uint', size=1)
        index = Table(self.rom, self.stream, ispec) # 0 1 2 3
        table = Table(self.rom, self.stream, tspec, index)
        for i in range(4):
            self.assertEqual(table[i], i)
