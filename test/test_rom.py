import os
import unittest
import logging
from pathlib import Path
from functools import partialmethod

import romlib.rom
import romlib.rommap
from romlib.rom import Rom, SNESRom
from romlib.rommap import RomMap
from romlib.structures import Structure, Table
from romlib.types import Field
from romtool.util import pkgfile


romenv = 'ROMLIB_TEST_ROM'
mapenv = 'ROMLIB_TEST_MAP'
romfile = os.environ.get(romenv, None)
rommap = os.environ.get(mapenv, None)
log = logging.getLogger(__name__)


@unittest.skipUnless(romfile, f'{romenv} not set, skipping')
class TestRom(unittest.TestCase):
    def setUp(self):
        self.file = open(romfile, 'rb')

    def tearDown(self):
        self.file.close()

    def test_make_rom(self):
        rom = Rom.make(self.file)
        self.assertIsInstance(rom, Rom)

    def test_make_rom_validation(self):
        rom = Rom.make(self.file, ignore_extension=True)
        self.assertIsInstance(rom, Rom)

    def test_noop_patch(self):
        rom = Rom.make(self.file, ignore_extension=True)
        patch = rom.patch
        self.assertFalse(patch.changes)
        rom.apply_patch(patch)
        self.assertEqual(rom.file, rom.orig)

    @unittest.skip
    def test_print_rom_header(self):
        with open(self.rom, 'rb') as f:
            rom = Rom.make(f)
        print(rom.header)
        try:
            print(rom.registration)
        except AttributeError:
            pass


class TestRomMap(unittest.TestCase):
    def setUp(self):
        structs = {'snesheaders': romlib.rom.headers['snes-hdr']}
        tables = {'snesheaders':
                     {'id': 'snesheaders',
                      'name': 'Header',
                      'set': '',
                      'type': 'snes-hdr',
                      'offset': '0x7FC0',
                      'size': '32',
                      'count': '2',
                      'stride': '0x8000'}
                     }
        self.rmap = RomMap('nameless', None, structs, tables)

    def test_init(self):
        self.assertIsInstance(self.rmap, RomMap)
        self.assertEqual(len(self.rmap.structs), 1)
        self.assertEqual(len(self.rmap.tables), 1)
        self.assertEqual(len(self.rmap.ttables), 0)


class TestKnownMaps(unittest.TestCase):
    known_map_roots = [p for p
                       in Path(pkgfile('maps')).iterdir()
                       if p.is_dir()
                       and Path(p, 'meta.yaml').exists()]
    rom_dir = Path('~/.local/share/romtool/roms').expanduser()

    def _find_rom(self, rmap):
        for parent, dirs, files in os.walk(self.rom_dir):
            for filename in files:
                if filename == rmap.meta.file:
                    return Path(parent, filename)
        raise FileNotFoundError(f"no matching rom for {rmap.name}")

    def _test_map(self, maproot):
        rmap = RomMap.load(str(maproot))
        self.assertTrue(rmap.meta, f"metadata missing for {rmap.name}")
        try:
            with open(self._find_rom(rmap), 'rb') as f:
                rom = Rom.make(f, rmap)
        except FileNotFoundError as ex:
            self.skipTest(ex)

        self.assertIsInstance(rom, Rom)
        for d in rmap.tests:
            slug = rmap.meta.slug
            tbl = d.table
            idx = d.item
            attr = d.attribute
            expected = d.value
            with self.subTest(f'{slug}:{tbl}[{idx}].{attr}=={expected}'):
                item = rom.entities[tbl][idx]
                value = item if not attr else getattr(item, attr)
                # The str here covers things like enums. Probably something
                # will go horribly wrong with this eventually.
                emsg = f'expected {expected}, found {value}'
                self.assertIn(expected, [value, str(value)], emsg)

    @classmethod
    def add_map_tests(cls):
        """ Dynamically add a test for each map in the builtin map directory """
        for root in cls.known_map_roots:
            # Kludgy way to get a usable identifier for each test
            with open(Path(root, 'meta.yaml')) as f:
                slug = next(line.split(':')[-1].strip()
                            for line in f
                            if line.startswith('slug:'))  # ew
            method = partialmethod(cls._test_map, root)
            name = f"test_map_{slug}"
            setattr(cls, name, method)

    def setUp(self):
        self.std_struct_registry = Structure.registry.copy()
        self.std_field_handlers = Field.handlers.copy()

    def tearDown(self):
        Structure.registry = self.std_struct_registry
        Field.handlers = self.std_field_handlers

TestKnownMaps.add_map_tests()
