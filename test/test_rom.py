import abc
import os
import unittest
import logging
from pathlib import Path
from os.path import basename

from addict import Dict

import romtool.rom
import romtool.rommap
import romtool.text
import codecs
from romtool.rom import Rom
from romtool.rommap import RomMap
from romtool.structures import Structure
from romtool.field import Field, DEFAULT_FIELDS
from romtool.util import pkgfile, IndexInt


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
        with open(self.file, 'rb') as f:
            rom = Rom.make(f)
        print(rom.header)
        try:
            print(rom.registration)
        except AttributeError:
            pass


class TestRomMap(unittest.TestCase):
    def setUp(self):
        structs = {'snesheader': romtool.rom.headers['snes-hdr']}
        tables = {'snesheaders':
                     Dict({'id': 'snesheaders',
                      'name': 'Header',
                      'set': '',
                      'type': 'snesheader',
                      'offset': '0x7FC0',
                      'size': '32',
                      'count': '2',
                      'stride': '0x8000'})
                     }
        self.rmap = RomMap('nameless', None, structs, tables)

    def test_init(self):
        self.assertIsInstance(self.rmap, RomMap)
        self.assertEqual(len(self.rmap.structs), 1)
        self.assertEqual(len(self.rmap.tables), 1)
        self.assertEqual(len(self.rmap.ttables), 0)


class TestKnownMapBase(abc.ABC, unittest.TestCase):
    known_map_roots = [p for p
                       in Path(pkgfile('maps')).iterdir()
                       if p.is_dir()
                       and Path(p, 'meta.yaml').exists()]
    rom_dir = Path('~/.local/share/romtool/roms').expanduser()
    codec_cache_tainted = False

    @classmethod
    def setUpClass(cls):
        cls.rmap = RomMap.load(str(cls.maproot))
        assert cls.rmap.meta, f"metadata missing for {cls.rmap.name}"
        try:
            with open(cls.rmap.find(cls.rom_dir), 'rb') as f:
                cls.rom = Rom.make(f, cls.rmap)
        except FileNotFoundError as ex:
            cls.tearDownClass()
            raise unittest.SkipTest(str(ex))

    @classmethod
    def tearDownClass(cls):
        # FIXME: String tests fail if different maps have codecs with the same
        # name. Unfortunately the ability to un-register codecs was only added
        # in 3.10, so for now, treat all runs after the first as tainted.
        if hasattr(codecs, 'unregister'):
            romtool.text.clear_tt_codecs()
        else:
            TestKnownMapBase.codec_cache_tainted = True

    def __init_subclass__(cls, maproot, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.maproot = maproot
        for t in RomMap.get_tests(maproot):
            tbl = t.table
            idx = t.item
            attr = t.attribute
            expected = t.value
            desc = f'{tbl}[{idx}].{attr}=={expected}'
            name = f'{basename(maproot)}::{desc}'
            testfunc = cls.makeTest(tbl, idx, attr, expected)
            setattr(cls, f"test_{name}", testfunc)

    @staticmethod
    def makeTest(table, idx, attr, expected):
        def testfunc(self):
            item = self.rom.entities[table][idx]
            value = item if not attr else getattr(item, attr)
            stringlike = isinstance(value, str) or isinstance(value, IndexInt)
            if stringlike and self.codec_cache_tainted:
                self.skipTest("string tests broken in python <3.10")
            # The str here covers things like enums. Probably something
            # will go horribly wrong with this eventually.
            emsg = f"expected '{expected}', found '{value}'"
            self.assertIn(expected, [value, str(value)], emsg)
        return testfunc


    @classmethod
    def add_known_map_test_cases(cls):
        for i, root in enumerate(cls.known_map_roots):
            clsname = f"TestKnownMap{i}"
            subcls = type(clsname, (cls,), {}, maproot=root)
            globals()[clsname] = subcls

    def setUp(self):
        self.assertIsInstance(self.rom, Rom)

TestKnownMapBase.add_known_map_test_cases()
