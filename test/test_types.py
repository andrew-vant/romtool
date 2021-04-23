import unittest
from types import SimpleNamespace

import yaml
from addict import Dict

from romlib.io import BitArrayView as Stream
from romlib.types import Field
from romlib.structures import Structure
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
                        'display': 'ascii'}]
        self.fields = [Field.from_tsv_row(row) for row in self.specs]
        self.scratch = Structure.define('scratch', self.fields)

    def tearDown(self):
        del Structure.registry['scratch']

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

class TestSubstructures(unittest.TestCase):
    def setUp(self):
        subfields = [{'id': 'one',
                      'name': 'One Label',
                      'type': 'flag',
                      'offset': '0',
                      'size': '1',
                      'display': 'J',
                      'arg': '0'},
                     {'id': 'two',
                      'name': 'Two Label',
                      'type': 'flag',
                      'offset': '2',
                      'size': '1',
                      'display': 'Q',
                      'arg': '0'}]
        fields = [{'id': 'sub',
                   'name': 'sub',
                   'type': 'flags',
                   'offset': '0',
                   'size': '2',
                   'display': None,
                   'arg': None,}]
        self.cls_flags = BitField.define('flags', subfields)
        self.cls_struct = Structure.define('scratch', fields)
        self.data = bytes2ba(bytes([0b10000000]))

    def test_substruct(self):
        struct = self.cls_struct(Stream(self.data))
        self.assertTrue(struct.sub.one)

    def tearDown(self):
        del Structure.registry['scratch']
        del Structure.registry['flags']


class TestBitField(unittest.TestCase):
    def setUp(self):
        self.data = bytes2ba(bytes([0b10000000]))
        self.fields = [{'id': 'one',
                        'name': 'One Label',
                        'type': 'flag',
                        'offset': '0',
                        'size': '1',
                        'display': 'J',
                        'arg': '0'},
                       {'id': 'two',
                        'name': 'Two Label',
                        'type': 'flag',
                        'offset': '2',
                        'size': '1',
                        'display': 'Q',
                        'arg': '0'}]
        self.scratch = BitField.define('scratch', self.fields)

    def test_define(self):
        self.assertTrue(issubclass(self.scratch, BitField))

    def test_construction(self):
        bf = self.scratch(Stream(self.data))
        self.assertIsInstance(bf, BitField)
        self.assertTrue(bf.one)
        self.assertFalse(bf.two)
        self.assertIsInstance(bf.one, Flag)
        self.assertIsInstance(bf.two, Flag)

    def test_chars(self):
        bf = self.scratch(Stream(self.data))
        self.assertEqual(bf.one.char, 'J')
        self.assertEqual(bf.two.char, 'Q')

    def test_str(self):
        bf = self.scratch(Stream(self.data))
        self.assertEqual(str(bf), 'Jq')

    def tearDown(self):
        del Structure.registry['scratch']


class TestArray(unittest.TestCase):
    def setUp(self):
        self.data = bytes2ba(b'\x01\x02\x03\x04abcdef')
        self.specs =  [{'id': 'one',
                        'name': 'One Label',
                        'type': 'uint',
                        'offset': '0',
                        'size': '8',
                        'arg': '0'}]
        self.fields = [Field.from_tsv_row(row) for row in self.specs]
        self.scratch = Structure.define('scratch', self.fields)

    def tearDown(self):
        del Structure.registry['scratch']

    def test_primitive_array(self):
        bs = Stream(self.data)
        uint = Primitive('uint', 8)
        array = Array(bs, uint, 0, len(self.data), 1)
        self.assertEqual(len(self.data), len(array))
        self.assertEqual(list(self.data), list(array))

    def test_struct_array(self):
        bs = Stream(self.data)
        array = Array(bs, self.scratch, 0, len(self.data), 1)
        self.assertEqual(len(self.data), len(array))
        self.assertEqual(list(self.data), [s.one for s in array])
