import os
import unittest
import logging

import romlib.rom
import romlib.rommap
from romlib.rom import Rom, SNESRom
from romlib.rommap import RomMap
from romlib.structures import Structure, Table


romenv = 'ROMLIB_TEST_ROM'
mapenv = 'ROMLIB_TEST_MAP'
romfile = os.environ.get(romenv, None)
rommap = os.environ.get(mapenv, None)
log = logging.getLogger(__name__)


@unittest.skipUnless(romfile, f'{romenv} not set, skipping')
class TestRom(unittest.TestCase):
    def setUp(self):
        self.rom = romfile

    def test_make_rom(self):
        with open(self.rom, 'rb') as f:
            rom = Rom.make(f)
        self.assertIsInstance(rom, Rom)

    def test_make_rom_validation(self):
        with open(self.rom, 'rb') as f:
            rom = Rom.make(f, ignore_extension=True)
        self.assertIsInstance(rom, Rom)

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
        self.rmap = RomMap(structs, tables)

    def test_init(self):
        self.assertIsInstance(self.rmap, RomMap)
        self.assertEqual(len(self.rmap.structs), 1)
        self.assertEqual(len(self.rmap.tables), 1)
        self.assertEqual(len(self.rmap.ttables), 0)


@unittest.skipUnless(romfile, f'{romenv} not set, skipping')
class TestMappedRom(unittest.TestCase):
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
        self.rmap = RomMap(structs, tables)
        filename = romfile
        if not filename:
            self.skipTest(f"{rom_envvar} not set, skipping")
        with open(filename, 'rb') as f:
            self.rom = Rom.make(f, self.rmap)

    def test_init(self):
        self.assertIsInstance(self.rom, Rom)
        self.assertEqual(len(self.rom.snesheaders), 2)
        log.info(type(romlib.rom.headers))
        log.info(type(self.rom.snesheaders))
        headcls = romlib.rom.headers['snes-hdr']
        log.debug(headcls)
        log.debug(type(self.rom.snesheaders[0]))
        self.assertIsInstance(self.rom.snesheaders[0], headcls)

    def test_header(self):
        if not isinstance(self.rom, SNESRom):
            self.skipTest("test requires an SNES rom")
        real_header = next(h for h in self.rom.snesheaders
                           if h.view.offset == self.rom.header.view.offset)
        self.assertEqual(real_header.csum + real_header.csum2, 0xFFFF)


@unittest.skipUnless(rommap, f'{mapenv} not set, skipping')
class TestMapLoading(unittest.TestCase):
    def setUp(self):
        self.rmap = RomMap.load(rommap)

    def test_load(self):
        pass

    def test_use(self):
        with open(romfile, 'rb') as f:
            rom = Rom.make(f, self.rmap)

    def test_check(self):
        with open(romfile, 'rb') as f:
            rom = Rom.make(f, self.rmap)
        self.assertIsInstance(rom.monsters, Table)
        self.assertIsInstance(rom.monsters[0], Structure.registry['monster'])
        self.assertEqual(rom.monsters[2].hp, 30)
        hermit = next(m for m in rom.monsters if m.name.startswith('Hermit'))
        self.assertEqual(hermit.lvl, 1)
