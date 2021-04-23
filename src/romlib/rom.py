import io
import string
import logging
import math
from abc import ABCMeta
from os.path import dirname, basename, realpath, splitext
from os.path import join as pathjoin

from bitstring import BitStream, ConstBitStream

from . import util


log = logging.getLogger(__name__)
headers = util.load_builtins('headers', '.tsv', struct.define)


class RomFormatError(Exception):
    pass


class HeaderError(RomFormatError):
    pass


class Rom:
    extensions = {'.nes': INESRom,
                  '.sfc': SNESRom}

    def __new__(cls, romfile, rommap=None):
        subcls = cls.identify(romfile)
        return subcls(romfile, rommap)

    def __init__(self, romfile, rommap=None):
        ba = bitarray()
        ba.fromfile(romfile)

        self.file = Stream(ba)
        self.orig = Stream(bitarray(ba))
        self.map = rommap

    def validate(self):
        raise NotImplementedError(f"No validator available for {type(self)}")

    @classmethod
    def identify(cls, romfile):
        # Check file extension first, if possible
        ext = splitext(romfile.name)[1]
        if ext in cls.extensions:
            return cls.extensions[ext]

        log.debug("Unknown extension '%s', inspecting contents", ext)
        for subcls in self.__subclasses__():
            log.debug("Trying: %s", romcls.romtype)
            try:
                subcls.validate(romfile)
                return subcls
            except RomFormatError:
                pass
        raise RomFormatError("Can't figure out what type of ROM this is")


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
