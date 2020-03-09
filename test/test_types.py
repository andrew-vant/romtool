import unittest

from romlib.types import Structure, Field
from bitstring import BitStream

class TestField(unittest.TestCase):
    def setUp(self):
        pass

    # Rough plan: mock the passed-in object to provide results for stream.read,
    # etc.


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.data = b'\x01\x02\x03\x04abcdef'
        self.fields = [{'fid': 'one',
                        'label': 'One Label',
                        'type': 'uint',
                        'offset': '0'},
                       {'fid': 'two',
                        'label': 'Two Label',
                        'type': 'uint',
                        'offset': 1}]

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
