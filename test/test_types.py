import unittest

from romlib.types import Structure, Field
from bitstring import BitStream


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.data = BitStream(b'\x01\x02\x03\x04abcdef')
        self.fields = [{'fid': 'one',
                        'label': 'One Label',
                        'type': 'uint',
                        'offset': '0'}]

    def test_define_struct(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        self.assertTrue(issubclass(structtype, Structure))

    def test_instantiate_struct(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(self.data, 0)
        self.assertIsInstance(struct, structtype)

    def test_read_struct_attr(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(self.data, 0)
        self.assertEqual(struct.one, 1)

    def test_read_struct_item_by_fid(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(self.data, 0)
        self.assertEqual(struct['one'], 1)

    def test_read_struct_item_by_label(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(self.data, 0)
        self.assertEqual(struct['One Label'], 1)

    def test_write_struct_attr(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(self.data, 0)
        struct.one = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['one'], 2)
        self.assertEqual(struct['One Label'], 2)

    def test_write_struct_item_by_fid(self):
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(self.data, 0)
        struct['one'] = 2
        self.assertEqual(struct.one, 2)
        self.assertEqual(struct['one'], 2)
        self.assertEqual(struct['One Label'], 2)

    def test_write_struct_stream_contents(self):
        # Test that writes do the right thing with the underlying stream
        structtype = Structure.define('scratch', self.fields, force=True)
        struct = structtype(self.data, 0)
        struct.one = 2
        
