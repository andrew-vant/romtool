import os
import unittest

import romlib.rom
from romlib.rom import Rom

class TestRom(unittest.TestCase):
    rom_envvar = 'ROMLIB_TEST_ROM'

    def setUp(self):
        self.rom = os.environ.get(self.rom_envvar, None)
        if not self.rom:
            self.skipTest(f"{self.rom_envvar} not set, skipping")

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
