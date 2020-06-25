import unittest
from types import SimpleNamespace

import yaml
from bitstring import BitStream
from addict import Dict

from romlib.types import Structure, Field, Size, Offset, Array

class TestField(unittest.TestCase):
    # A field's getter should
    def setUp(self):
        self.field = Field('uint', '0', '8')
        self.instance = SimpleNamespace(
                stream = BitStream(uint=1, length=8),
                offset = 0
                )

    # Rough plan: Test __get__ and __set__ directly, avoids external
    # dependencies. Test self.factory.
    @unittest.skip("not yet implemented")
    def test_construction(self):
        pass

    @unittest.skip("not yet implemented")
    def test_spec_construction(self):
        pass

    @unittest.skip("not yet implemented")
    def test_factory(self):
        pass

    def test_get(self):
        self.assertEqual(self.field.__get__(self.instance), 1)

    @unittest.skip("not yet implemented")
    def test_set(self):
        pass


@unittest.skip("not yet implemented")
class TestOffset(unittest.TestCase):
    def test_valid_specs(self):
        pass
    def test_invalid_specs(self):
        pass
    def test_count_spec(self):
        pass
    def test_sibling_spec(self):
        pass


class TestSize(unittest.TestCase):
    def test_valid_specs(self):
        valid_specs = '5', 'bytes:17', 'bits:23'
        for spec in valid_specs:
            self.assertIsInstance(Size.from_spec(spec), Size)

    def test_invalid_specs(self):
        invalid_specs = '4:bits', 'notaunit:4'
        for spec in invalid_specs:
            msg = f"Size.from_spec('{spec}') succeeded, but shouldn't have"
            with self.assertRaises(ValueError, msg=msg):
                Size.from_spec(spec)

    def test_spec_scale(self):
        for unit, scale in {'bits': 1, 'bytes': 8, 'kb': 8*1024}.items():
            self.assertEqual(Size.from_spec(f'{unit}:1').scale, scale)

    def test_count_spec(self):
        size = Size.from_spec('bytes:5')
        self.assertEqual(size.count, 5)
        self.assertEqual(size.scale, 8)
        self.assertIs(size.sibling, None)

    def test_sibling_spec(self):
        size = Size.from_spec('bytes:sibling')
        self.assertEqual(size.count, None)
        self.assertEqual(size.scale, 8)
        self.assertEqual(size.sibling, 'sibling')


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.data = b'\x01\x02\x03\x04abcdef'
        self.fields = [{'id': 'one',
                        'label': 'One Label',
                        'type': 'uint',
                        'offset': '0',
                        'size': '8',
                        'mod': '0'},
                       {'id': 'two',
                        'label': 'Two Label',
                        'type': 'uint',
                        'offset': '8',
                        'size': '8',
                        'mod': '0'},
                       {'id': 'modded',
                        'label': 'Modded Label',
                        'type': 'uint',
                        'offset': '16',
                        'size': '8',
                        'mod': '1'},
                       {'id': 'str',
                        'label': 'String',
                        'type': 'str',
                        'offset': '32',
                        'size': '48',
                        'mod': '',
                        'display': ''}]

    def test_define_struct(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        self.assertTrue(issubclass(structtype, Structure))

    def test_instantiate_struct(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        self.assertIsInstance(struct, structtype)

    def test_read_struct_attr(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        stream = BitStream(self.data)
        struct = structtype(stream, 0)
        self.assertEqual(struct.one, 1)

    def test_read_struct_item_by_fid(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        self.assertEqual(struct['one'], 1)

    def test_read_struct_item_by_label(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        self.assertEqual(struct['One Label'], 1)

    def test_write_struct_attr(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        struct.one = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['one'], 2)
        self.assertEqual(struct['One Label'], 2)

    def test_write_struct_item_by_fid(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        struct['one'] = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['one'], 2)
        self.assertEqual(struct['One Label'], 2)

    def test_write_struct_stream_contents(self):
        # Test that writes do the right thing with the underlying stream
        structtype = Structure.define('scratch', self.fields, force=True)
        stream = BitStream(self.data)
        struct = structtype(stream, 0)
        struct.one = 2
        stream.pos = 0
        self.assertEqual(stream.bytes[0], 2)

    def test_read_field_with_offset(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        self.assertEqual(struct.two, 2)
        self.assertEqual(struct['two'], 2)

    def test_write_field_with_offset(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        struct.two = 4
        self.assertEqual(struct.two, 4)
        self.assertEqual(struct['two'], 4)
        self.assertEqual(struct['Two Label'], 4)

    def test_modded_field(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        self.assertEqual(struct.modded, 4)
        struct.modded = 4
        self.assertEqual(struct.stream.bytes[2], 3)
        self.assertEqual(struct.modded, 4)

    def test_read_string_field(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        self.assertEqual(struct.str, 'abcdef')

    def test_write_string_field(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        struct.str = 'zyxwvu'
        expected = b'\x01\x02\x03\x04zyxwvu'
        self.assertEqual(struct.str, 'zyxwvu')
        self.assertEqual(struct.stream.bytes, expected)

    def test_oversized_string(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        with self.assertRaises(ValueError):
            struct.str = 'abcdefghy'

    def test_undersized_string(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        with self.assertRaises(ValueError):
            struct.str = 'abc'


class TestArray(unittest.TestCase):
    def setUp(self):
        self.data = b'\x01\x02\x03\x04abcdef'
        self.fields = [{'id': 'one',
                        'label': 'One Label',
                        'type': 'uint',
                        'offset': '0',
                        'size': '8',
                        'mod': '0'}]

    def test_primitive_array(self):
        bs = BitStream(self.data)
        array = Array(bs, 'uint', 0, len(self.data), 1)
        self.assertEqual(len(self.data), len(array))
        self.assertEqual(list(self.data), list(array))

    def test_struct_array(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        bs = BitStream(self.data)
        array = Array(bs, 'scratch', 0, len(self.data), 1)
        self.assertEqual(len(self.data), len(array))
        self.assertEqual(list(self.data), [s.one for s in array])
