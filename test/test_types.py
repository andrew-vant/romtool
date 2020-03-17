import unittest

from romlib.types import Structure, Field, Size, Offset
from bitstring import BitStream

class TestField(unittest.TestCase):
    def setUp(self):
        pass

    # Rough plan: mock the passed-in object to provide results for stream.read,
    # etc.

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
        self.fields = [{'fid': 'one',
                        'label': 'One Label',
                        'type': 'uint',
                        'offset': '0',
                        'size': '1'},
                       {'fid': 'two',
                        'label': 'Two Label',
                        'type': 'uint',
                        'offset': '1',
                        'size': '1'}]

    def test_define_struct(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        self.assertTrue(issubclass(structtype, Structure))

    def test_instantiate_struct(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
        self.assertIsInstance(struct, structtype)

    def test_read_struct_attr(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(BitStream(self.data), 0)
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
