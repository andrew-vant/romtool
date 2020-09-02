# Thinking: Ignore file objects completely. Just convert to bitstream
# when the rom object is instantiated. Everything everywhere assumes
# bitstring objects.
#
# Move most of the reader functions out of RomMap and into Rom?
#
# Alternately, generate Rom class from the map, rather than having a
# RomMap object?
#
# Use __getattr__ and some listlike object to let the program navigate
# through the rom data through normal attribute access and list
# indexing? Seems like it would help with crossreferencing.
#
# Fake a database interface? Where the object offset is the ID within
# its table. Dumps them become the equivalent of a select; patches the
# equivalent of an update (but what happens when an object's offset
# changes?)
#
# Alternately: No lists. Everything is a dict of offset to object. For
# pointers, just keep dereferencing until you get a real object. (nope,
# this doesn't work, some crossrefs are by list index. So each object
# needs both an index and an offset.)
#
# Seriously consider just doing everything in memory. Anything big
# enough to be too big for memory probably has a real filesystem.

import io
import string
import logging
import math
from abc import ABCMeta
from os.path import dirname, basename, realpath
from os.path import join as pathjoin

from bitstring import BitStream, ConstBitStream

from . import util


log = logging.getLogger(__name__)
headers = util.load_builtins('headers', '.tsv', struct.load)

class RomFormatError(Exception):
    pass


class HeaderError(RomFormatError):
    pass


class Rom:
    def __init__(self, infile, rommap):
        ba = bitarray()
        ba.fromfile(infile)

        self.stream = Stream(ba)
        self.orig = Stream(bitarray(ba))
        self.map = rommap


class Rom:
    def __init__(self, romfile, rommap=None):
        self.validate(romfile)
        self.map = rommap
        self.file = ConstBitStream(romfile)
        self.data = BitStream(self.file)

    @classmethod
    def make(cls, romfile):
        log.debug("Autodetecting rom type")
        for romcls in cls.__subclasses__():
            try:
                log.debug("Trying: %s", romcls.romtype)
                if romcls.validate(romfile):
                    return romcls(romfile)
            except RomFormatError:
                pass
        else:
            raise RomFormatError("Input does not match any known ROM format")


class INESRom(Rom):
    romtype = 'ines'
    hdr_ident = b"NES\x1a"

    def __init__(self, romfile, rommap=None):
        super().__init__(romfile, rommap)
        bs_head = self.file[:16*8]
        self.header = headers[self.romtype](bs_head)
        self.data = self.file[16*8:]

    @classmethod
    def validate(cls, romfile):
        romfile.seek(0)
        ident = romfile.read(4)
        if ident != cls.hdr_ident:
            msg = "Bad ines header ident ({} != {})"
            raise HeaderError(msg.format(ident, cls.hdr_ident))
        return True


class SNESRom(Rom):
    romtype = 'snes'
    sz_smc = 0x200
    ofs_lorom = 0x7FB0
    ofs_hirom = 0xFFB0

    def __init__(self, romfile, rommap=None):
        super().__init__(romfile, rommap)
        self.smc = self._load_smc(romfile)
        self.header = self._load_header(romfile)
        self.data = BitStream(self.file[len(self.smc*8):])

    @classmethod
    def validate(cls, romfile):
        try:
            return bool(cls._load_header(romfile))
        except HeaderError:
            return False

    @classmethod
    def _load_smc(cls, romfile):
        sz_file = util.filesize(romfile)
        sz_smc = sz_file % 1024
        if sz_smc == 0:
            return None
        elif sz_smc == cls.sz_smc:
            romfile.seek(0)
            return romfile.read(sz_smc)
        else:
            raise HeaderError("Bad rom file size or corrupt SMC header")

    @classmethod
    def checksum(cls, romdata):
        if not math.log(len(romdata), 2).is_integer():
            msg = "Rom size {} is not a power of two"
            raise NotImplementedError(msg.format(len(romdata)))
        return sum(romdata) % 0xFFFF


    @classmethod
    def _load_header(cls, romfile):
        smc = cls._load_smc(romfile)
        romfile.seek(len(smc))
        data = romfile.read()

        for offset in [cls.ofs_hirom, cls.ofs_lorom]:
            if offset > len(data):
                # Happens for at least one Game Genie rom -- it's lorom and not
                # physically large enough to be hirom
                continue
            bs_head = BitStream(bytes=data[offset:offset+64])
            try:
                header = headers[cls.romtype](bs_head)
                cls._validate_header(offset, len(data), header)
                return header
            except (UnicodeDecodeError, HeaderError) as e:
                # The unicode one gets thrown when the name string isn't valid.
                log.debug(str(e))
                continue
        raise HeaderError("No valid header found")

    @classmethod
    def _validate_header(cls, offset, datasize, header):
        sz_max = 1024*2**(header.sz_rom)

        if offset != (cls.ofs_hirom if header.hirom else cls.ofs_lorom):
            raise HeaderError("Hirom bit doesn't match location")
        if not sz_max >= datasize > sz_max/2:
            raise HeaderError("Rom file size doesn't match header.")
        if not all(c in string.printable for c in header.name):
            raise HeaderError("Bogus ROM name in header.")

        return True


def identify(romfile):
    # Requires reading the whole rom to determine its type. There must be a
    # better way to do this.
    return Rom.make(romfile).romtype

