import unittest
from types import SimpleNamespace

import yaml
from addict import Dict

from romlib.io import BitArrayView as Stream
from romlib.types import Field
from romlib.structures import Structure, BitField, Table, Index
from romlib.util import bytes2ba

class TestStructure(unittest.TestCase):
    def setUp(self):
        self.data = bytes2ba(b'\x01\x02\x03\x04abcdef')
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
                       {'id': 'name',
                        'name': 'Name',
                        'type': 'str',
                        'offset': '4',
                        'size': '6',
                        'arg': '',
                        'display': 'ascii'}]
        self.fields = [Field.from_tsv_row(row) for row in self.specs]
        self.scratch = Structure.define('scratch', self.fields)

    def tearDown(self):
        del Structure.registry['scratch']
        del Field.handlers['scratch']

    def test_define_struct(self):
        self.assertTrue(issubclass(self.scratch, Structure))

    def test_instantiate_struct(self):
        struct = self.scratch(Stream(self.data))
        self.assertIsInstance(struct, self.scratch)

    def test_read_struct_attr(self):
        stream = Stream(self.data)
        struct = self.scratch(stream)
        self.assertEqual(struct.one, 1)

    def test_read_struct_item(self):
        struct = self.scratch(Stream(self.data))
        self.assertEqual(struct['One Label'], 1)

    def test_write_struct_attr(self):
        struct = self.scratch(Stream(self.data))
        struct.one = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['One Label'], 2)

    def test_write_struct_item(self):
        struct = self.scratch(Stream(self.data))
        struct['One Label'] = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['One Label'], 2)


    def test_write_struct_stream_contents(self):
        # Test that writes do the right thing with the underlying stream
        stream = Stream(self.data)
        struct = self.scratch(stream)
        struct.one = 2
        stream.pos = 0
        self.assertEqual(stream.bytes[0], 2)

    def test_read_field_with_offset(self):
        struct = self.scratch(Stream(self.data))
        self.assertEqual(struct.two, 2)
        self.assertEqual(struct['Two Label'], 2)

    def test_write_field_with_offset(self):
        struct = self.scratch(Stream(self.data))
        struct.two = 4
        self.assertEqual(struct.two, 4)
        self.assertEqual(struct['Two Label'], 4)

    def test_modded_field(self):
        struct = self.scratch(Stream(self.data))
        self.assertEqual(struct.modded, 4)
        struct.modded = 4
        self.assertEqual(struct.view.bytes[2], 3)
        self.assertEqual(struct.modded, 4)

    def test_read_string_field(self):
        struct = self.scratch(Stream(self.data))
        self.assertEqual(struct.str, 'abcdef')

    def test_write_string_field(self):
        struct = self.scratch(Stream(self.data))
        struct.str = 'zyxwvu'
        expected = b'\x01\x02\x03\x04zyxwvu'
        self.assertEqual(struct.str, 'zyxwvu')
        self.assertEqual(struct.view.bytes, expected)

    def test_oversized_string(self):
        struct = self.scratch(Stream(self.data))
        with self.assertRaises(ValueError):
            struct.str = 'abcdefghy'

    def test_undersized_string(self):
        struct = self.scratch(Stream(self.data))
        struct.str = 'abc'
        self.assertEqual(struct.str, 'abc   ')

    def test_repr(self):
        struct = self.scratch(Stream(self.data))
        self.assertEqual(repr(struct), "<scratch@0x00 (abcdef)>")

    def test_iteration_keys(self):
        struct = self.scratch(Stream(self.data))
        self.assertEqual(set(struct.keys()),
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
        self.cls_struct = Structure.define_from_rows('scratch', fields)
        self.data = bytes2ba(bytes([0b10000000]))

    def tearDown(self):
        for name in ['scratch', 'flags']:
            del Structure.registry[name]
            del Field.handlers[name]

    def test_substruct(self):
        struct = self.cls_struct(Stream(self.data))
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

    def tearDown(self):
        del Structure.registry['scratch']
        del Field.handlers['scratch']

    def test_define(self):
        self.assertTrue(issubclass(self.scratch, BitField))

    def test_construction(self):
        bf = self.scratch(Stream(self.data))
        self.assertIsInstance(bf, BitField)
        self.assertTrue(bf.one)
        self.assertFalse(bf.two)

    def test_str(self):
        bf = self.scratch(Stream(self.data))
        self.assertEqual(str(bf), 'Jq')

    def test_repr(self):
        bf = self.scratch(Stream(self.data))
        self.assertEqual(repr(bf), '<scratch@0x00 (Jq)>')

    def test_parse(self):
        bf = self.scratch(Stream(self.data))
        bf.parse("jQ")
        self.assertFalse(bf.one)
        self.assertTrue(bf.two)
        self.assertEqual(str(bf), "jQ")


class TestIndex(unittest.TestCase):
    def test_make_index(self):
        index = Index(0, 4, 1)
        self.assertEqual(index, (0, 1, 2, 3))


class TestTable(unittest.TestCase):
    def setUp(self):
        self.data = bytes2ba(b'\x00\x01\x02\x03abcdef')
        self.struct_spec =  [{'id': 'one',
                              'name': 'One Label',
                              'type': 'uint',
                              'offset': '0',
                              'size': '1',
                              'arg': '0'}]
        self.fields = [Field.from_tsv_row(row) for row in self.struct_spec]
        self.stream = Stream(self.data)
        self.scratch = Structure.define('scratch', self.fields)

    def tearDown(self):
        del Structure.registry['scratch']
        del Field.handlers['scratch']

    def test_primitive_array_construction(self):
        array = Table(self.stream, 'uint', Index(0, 4, 1))
        self.assertEqual(len(array), 4)
        self.assertEqual(len(array.index), 4)
        for i in range(4):
            self.assertEqual(array[i], i)

    def test_structure_array_construction(self):
        array = Table(self.stream, 'scratch', Index(0, 4, 1))
        self.assertIsInstance(array[0], self.scratch)
        self.assertEqual(len(array), 4)
        self.assertEqual(len(array.index), 4)
        for i in range(4):
            self.assertEqual(array[i].one, i)

    def test_indexed_table(self):
        index = Table(self.stream, 'uint', Index(0, 4, 1)) # 0 1 2 3
        table = Table(self.stream, 'scratch', index)
        for i in range(4):
            self.assertEqual(table[i].one, i)

    def test_primitive_table(self):
        index = Table(self.stream, 'uint', Index(0, 4, 1)) # 0 1 2 3
        table = Table(self.stream, 'uint', index, size=1)
        for i in range(4):
            self.assertEqual(table[i], i)
