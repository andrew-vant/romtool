import string
import logging
import math
import io
import operator
from operator import itemgetter
from os.path import splitext, basename
from os.path import join as pathjoin
from itertools import groupby, chain

from bitarray import bitarray
from anytree import NodeMixin

from . import util
from .patch import Patch
from .io import Unit, BitArrayView as Stream
from .structures import Structure, Table, Index
from .rommap import RomMap


log = logging.getLogger(__name__)
headers = util.load_builtins('headers', '.tsv', Structure.define_from_tsv)


class RomFormatError(Exception):
    pass


class HeaderError(RomFormatError):
    pass


class Rom(NodeMixin):
    registry = {}
    extensions = []

    def __init__(self, romfile, rommap=None):
        if rommap is None:
            rommap = RomMap()

        romfile.seek(0)
        ba = bitarray(endian='little')
        ba.fromfile(romfile)

        self.file = Stream(ba)
        self.orig = Stream(ba.copy())

        self.map = rommap
        byidx = lambda row: row.get('index', '')
        for spec in sorted(self.map.tables.values(), key=byidx):
            log.debug("creating table: %s", spec['id'])
            setattr(self, spec['id'], Table.from_tsv_row(spec, self, self.data))

    @property
    def data(self):
        return self.file

    @property
    def tables(self):
        return {table['id']: getattr(self, table.id)
                for table in self.map.tables.values()}

    def dump(self, folder, force=False):
        """ Dump all rom data to `folder` in tsv format"""

        byset = lambda row: row.get('set', None) or row['id']
        tablespecs = sorted(self.map.tables.values(), key=byset)

        for tset, tspecs in groupby(tablespecs, byset):
            tspecs = list(tspecs)
            ct_tables = len(tspecs)
            ct_items = int(tspecs[0]['count'], 0)
            log.info(f"Dumping dataset: {tset} ({ct_tables} tables, {ct_items} items)")
            path = pathjoin(folder, f'{tset}.tsv')

            records = []
            for i in range(ct_items):
                log.debug("Dumping %s #%s", tset, i)
                record = {'_idx': i}
                for tspec in tspecs:
                    tid = tspec['id']
                    item = getattr(self, tid)[i]
                    if isinstance(item, Structure):
                        record.update(item.items())
                    else:
                        record[tspec['name']] = item
                records.append(record)
            keys = set(records[0].keys())
            for r in records:
                assert not (set(r.keys()) - keys)
            util.writetsv(path, records, force)

    def load(self, folder):
        data = {}
        for _set in self.map.sets:
            path = pathjoin(folder, f'{_set}.tsv')
            log.debug("loading mod set '%s' from %s", _set, path)
            contents = util.readtsv(path)
            byidx = lambda row: int(row['_idx'], 0)
            try:
                contents = sorted(contents, key=byidx)
            except KeyError:
                log.warning('_idx field not present; assuming input order is correct')
            data[_set] = contents

        for tspec in self.map.tables.values():
            log.info("Loading table '%s' from set '%s'",
                     tspec['id'], tspec['set'])
            table = getattr(self, tspec['id'])
            for i, (orig, new) in enumerate(zip(table, data[tspec['set']])):
                log.debug("Loading %s #%s (%s)",
                          tspec['id'], i, new.get('Name', 'nameless'))
                if isinstance(orig, Structure):
                    orig.load(new)
                else:
                    table[i] = new[tspec['name']]

    @property
    def patch(self):
        old = io.BytesIO(self.orig.bytes)
        new = io.BytesIO(self.data.bytes)
        return Patch.from_diff(old, new)

    def validate(self):
        raise NotImplementedError(f"No validator available for {type(self)}")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        name = cls.__name__
        for ext in cls.extensions:
            if ext in cls.registry:
                msg = ("%s attempted to claim %s extension, but it is "
                      "already registered; ignoring")
                log.warning(msg, name, ext)
            else:
                cls.registry[ext] = cls

    @classmethod
    def make(cls, romfile, rommap=None, ignore_extension=False):
        # Check file extension first, if possible
        ext = splitext(romfile.name)[1]
        if ext in cls.registry and not ignore_extension:
            subcls = cls.registry[ext]
            rom = subcls(romfile, rommap)
            msg = "%s loaded by extension as a %s"
            log.info(msg, basename(romfile.name), subcls.__name__)
            return cls.registry[ext](romfile, rommap)

        log.debug("Unknown extension '%s', inspecting contents", ext)
        for subcls in Rom.__subclasses__():
            log.debug("Trying: %s", subcls.romtype)
            try:
                rom = subcls(romfile)
                rom.validate()
                msg = "%s loaded as a %s"
                log.info(msg, basename(romfile.name), subcls.__name__)
                return rom
            except RomFormatError as ex:
                log.debug("Couldn't validate: %s", ex)
        raise RomFormatError("Can't figure out what type of ROM this is")


class INESRom(Rom):
    romtype = 'ines'
    extensions = ['.nes', '.ines']
    hdr_ident = b"NES\x1a"
    sz_header = 16

    def __init__(self, romfile, rommap=None):
        super().__init__(romfile, rommap)
        hsz = self.sz_header * Unit.bytes
        hcls = headers[self.romtype]
        self.header = hcls(self.file[:hsz])

    @property
    def data(self):
        return self.file[self.sz_header * Unit.bytes:]

    def validate(self):
        hid = self.header.ident
        if hid != self.hdr_ident:
            msg = f"Bad ines header ident ({hid} != {self.hdr_ident})"
            raise HeaderError(msg)
        return True


class SNESRom(Rom):
    romtype = 'snes'
    extensions = ['.sfc', '.smc']
    sz_smc = 0x200
    # FIXME: Pretty sure these are SNES addresses, not ROM addresses, will have
    # to work out correponding address
    header_locations = {0x20: 0x7FC0,
                        0x21: 0xFFC0,
                        0x23: 0x7FC0,
                        0x30: 0x7FC0,
                        0x31: 0xFFC0,
                        0x32: 0x7FC0,
                        0x35: 0xFFC0}

    devid_magic = 0x33  # Indicates extended registration data available

    @property
    def data(self):
        """ Data block """
        offset = len(self.smc) if self.smc else 0
        return self.file[offset:]

    @property
    def header(self):
        for offset in set(self.header_locations.values()):
            log.debug("Looking for header at 0x%X", offset)
            hdr = headers['snes-hdr'](self.data[offset::Unit.bytes])

            # Mapping mode check
            if self.header_locations.get(hdr.mapmode, None) == offset:
                log.debug("0x%X: mapmode check: ok", offset)
            else:
                log.debug("0x%X: mapmode check: failed "
                          "(mode doesn't match header location)", offset)
                continue

            # Size byte check
            sz_max = 2**(hdr.sz_rom) * 1024
            sz_min = sz_max // 2
            sz_real = self.data.ct_bytes
            if sz_max >= sz_real > sz_min:
                log.debug("0x%X: size check: ok", offset)
            else:
                msg = "0x%X: size check: failed (%s not between %s and %s)"
                log.debug(msg, offset, sz_real, sz_min, sz_max)
                continue

            # Header version 2 has a null byte where the last printable character
            # would be, so strip it for this check.
            if all(chr(c) in string.printable for c in hdr.b_name[:-1]):
                log.debug("0x%X: name check: ok", offset)
            else:
                log.debug("0x%X: name check: failed (unprintable chars in name)", offset)

            log.debug("0x%X: all header checks passed, using this header", offset)
            return hdr
        else:
            raise HeaderError("No valid SNES header found")

    @property
    def registration(self):
        if self.header.devid != self.devid_magic:
            return None
        offset = self.header_locations[self.header.mapmode] - 0x10
        return headers['snes-reg'](self.data[offset::Unit.bytes])

    @property
    def smc(self):
        sz_smc = self.file.ct_bytes % 1024
        if sz_smc == 0:
            return None
        elif sz_smc == self.sz_smc:
            return self.file[0:sz_smc:Unit.bytes]
        else:
            raise HeaderError("Bad rom file size or corrupt SMC header")

    @property
    def checksum(self):
        if not math.log(self.data.ct_bytes, 2).is_integer():
            msg = "Rom size {self.data.ct_bytes} is not a power of two"
            raise NotImplementedError(msg)
        return sum(self.data.bytes) % 0xFFFF

    def validate(self):
        return bool(self.header)
