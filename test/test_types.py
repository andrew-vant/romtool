import unittest
from types import SimpleNamespace

import yaml
from bitstring import BitStream
from addict import Dict

from romlib.types import Structure, Field, Size, Offset

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

class TestOffset(unittest.TestCase):
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
                        'mod': '0'}]

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
