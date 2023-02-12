import string
import logging
import math
import io
import re
import subprocess as sp
from operator import itemgetter
from os.path import splitext, basename
from os.path import join as pathjoin
from itertools import groupby, chain
from functools import reduce, partial
from operator import itemgetter
from collections.abc import Mapping
from contextlib import ExitStack
from shutil import which
from tempfile import TemporaryDirectory

from bitarray import bitarray
from anytree import NodeMixin
from addict import Dict

from . import util
from .patch import Patch
from .io import Unit, BitArrayView as Stream
from .structures import Structure, Table, Entity, EntityList
from .rommap import RomMap
from .exceptions import MapError, RomError, RomtoolError, ChangesetError


log = logging.getLogger(__name__)
headers = util.load_builtins('headers', '.tsv', Structure.define_from_tsv)


class RomFormatError(RomError):
    pass


class HeaderError(RomFormatError):
    pass


class Rom(NodeMixin, util.RomObject):
    romtype = 'unknown'
    prettytype = "Unknown ROM type"
    registry = {}
    extensions = []
    sz_min = 0  # Files smaller than this are assumed to not be of this type

    def __init__(self, romfile, rommap=None):
        if rommap is None:
            rommap = RomMap()
        if isinstance(romfile, bytes):
            romfile = io.BytesIO(romfile)

        romfile.seek(0)
        ba = bitarray(endian='little')
        ba.fromfile(romfile)
        if len(ba) // Unit.bytes < self.sz_min:
            raise RomFormatError(f"Input is not a {type(self)} (too small)")

        self.file = Stream(ba)
        self.orig = Stream(ba.copy())

        self.map = rommap
        self.tables = Dict()
        byidx = lambda spec: bool(spec.index)
        for spec in sorted(self.map.tables.values(), key=byidx):
            log.debug("creating table: %s", spec.id)
            if spec.index and spec.index not in self.tables:
                raise MapError(f"table '{spec.id}' uses index '{spec.index}' "
                               f"but no such index exists")
            index = self.tables.get(spec.index)
            self.tables[spec.id] = Table(self, self.data, spec, index)

        self.entities = Dict()
        byset = lambda spec: spec.set or spec.id
        tables = sorted(self.map.tables.values(), key=byset)
        for tset, tspecs in groupby(tables, key=byset):
            parts = [self.tables[tspec.id] for tspec in tspecs]
            # FIXME: add format dunder to types involved?
            pdesc = ', '.join(p.name or p.id for p in parts)
            log.debug("Creating entityset '%s' from table(s) [%s]", tset, pdesc)
            self.entities[tset] = EntityList(tset, parts)

    def __str__(self):
        return f"{self.name} ({self.prettytype})"

    @property
    def name(self):
        return (util.nointro().get(self.data.sha1)
                or util.nointro().get(self.data.sha1)
                or self.map.name
                or "Unknown ROM")

    @property
    def data(self):
        return self.file

    def dump(self, folder, force=False):
        """ Dump all rom data to `folder` in tsv format"""

        byset = lambda tbl: tbl.set or tbl.id
        tablespecs = sorted(self.map.tables.values(), key=byset)

        for name, elist in self.entities.items():
            log.info("Dumping %s (%s items)", name, len(elist))
            path = pathjoin(folder, f'{name}.tsv')
            util.dumptsv(path, elist, force, elist.columns(), '_idx')

    def lookup(self, key):
        if key in self.map.sets:
            log.debug(f"set found for {key}")
            return util.Searchable(self.entities[key])
        elif key in self.map.tables:
            return self.map.tables[key]
        else:
            raise LookupError(f"no table or set with id '{key}'")

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

        with EntityList.cache_locate():
            # Crossref resolution is slow. Cache results during load. FIXME: I
            # am *sure* there's a better way to do this.
            for etype, elist in self.entities.items():
                log.info("Loading %s %s", len(elist), etype)
                for i, (orig, new) in enumerate(zip(elist, data[etype])):
                    name = new.get('Name', 'nameless')
                    log.debug("Loading %s #%s (%s)", etype, i, name)
                    with util.loading_context(etype, name, i):
                        orig.update(new)

    def apply(self, changeset):
        """ Apply a dictionary of changes to a ROM

        The changeset should be a nested dictionary describing key paths in the
        ROM. Keys will be recursively looked up, starting with top-level tables
        or table sets. Subkeys may have any type or value accepted by the
        parent object's .lookup() method. Leaf keys should be attributes or
        field ids of their parent.
        """

        for keys, value in util.flatten_dicts(changeset):
            log.info('applying change: %s -> %s',
                     ':'.join(str(k) for k in keys), value)
            attr = keys.pop()
            parent = self
            path = []  # note the path we've traversed for messages
            for key in keys:
                path.append(key)
                try:
                    parent = parent.lookup(key)
                except LookupError as ex:
                    path = ':'.join(str(k) for k in path)
                    msg = f"Bad lookup path '{path}' (typo?)"
                    raise ChangesetError(msg)
            try:
                setattr(parent, attr, value)
            except AttributeError as ex:
                path = ':'.join(str(k) for k in path)
                msg = f"{attr} is not a valid attribute of {path}"
                raise ChangesetError(msg)

    def apply_assembly(self, path):
        """ Insert assembly code into the ROM

        Scans the input for a line matching 'romtool: patch@{address}', which
        indicates where the assembled bytecode should be inserted. Then passes
        the code itself to an external assembler.

        Expects the content of the file as a string.
        """
        re_ctrl = r'romtool: patch@([0-9A-Fa-f]+):(.*)$'
        with open(path) as f:
            for i, line in enumerate(f):
                match = re.search(re_ctrl, line)
                if match:
                    try:
                        location = int(match.group(1), 16)
                        cmd = match.group(2)
                    except ValueError as ex:
                        raise ChangesetError(f"error on line {i}: {ex}")
                    break
            else:
                raise ChangesetError(f"no patch location given")

        with TemporaryDirectory(prefix='romtool.') as tmp:
            outfile = f'{tmp}/{basename(path)}.bin'
            known_assemblers = {
                'cl65': [which('cl65'), '-t', 'none', '-o', outfile, path],
                'xa65': [which('xa'), '-w', '-c', '-M', '-o', outfile, path],
                }
            args = known_assemblers.get(cmd)
            if not args:
                raise RomtoolError(f"don't know how to assemble with {cmd}")
            log.info("assembling %s", basename(path))
            log.debug("executing external command: %s", " ".join(args))
            proc = sp.run(args)
            if proc.returncode:
                raise ChangesetError(f"external assembly failed with return "
                                     f"code {proc.returncode}")
            with open(outfile, 'rb') as f:
                data = f.read()
        end = location + len(data)
        log.info("patching assembled %s to %s (%s bytes)",
                 basename(path), hex(location), len(data))
        self.data[location:end:Unit.bytes].bytes = data

    @property
    def patch(self):
        return self.make_patch()

    def changes(self):
        """ Generate changeset dictionary """
        # This might be hard. Loop over each table, look for items that differ
        # between orig and self, emit table:name:key:value dict tree
        raise Exception("Changeset generator not implemented yet")

    def make_patch(self):
        old = io.BytesIO(self.orig.bytes)
        new = io.BytesIO(self.file.bytes)
        return Patch.from_diff(old, new)

    def apply_patch(self, patch):
        contents = io.BytesIO(self.file.bytes)
        patch.apply(contents)
        contents.seek(0)
        self.file.bytes = contents.read()

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
        if rommap and hasattr(rommap.hooks, 'Rom'):
            rom = rommap.hooks.Rom(romfile, rommap)
            log.info("%s loaded using map hook", basename(romfile.name))
            return rom

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
                rom = subcls(romfile, rommap)
                rom.validate()
                msg = "%s loaded as a %s"
                log.info(msg, basename(romfile.name), subcls.__name__)
                return rom
            except RomFormatError as ex:
                log.debug("Couldn't validate: %s", ex)
        log.info("Can't figure out what type of ROM this is, using base")
        return Rom(romfile)

    def sanitize(self):
        """ Fix checksums, headers, etc as needed """
        self.map.sanitize(self)

    def lint(self):
        """ Run lint checks on the rom

        This prints messages for things like hp > maxhp or the like. Actual
        implementation must be punted to the map.
        """
        self.map.lint(self)

    def write(self, path, force=True):
        """ Write a rom to a file """
        mode = 'wb' if force else 'xb'
        with open(path, mode) as f:
            f.write(self.file.bytes)


class INESRom(Rom):
    romtype = 'ines'
    prettytype = "INES ROM"
    extensions = ['.nes', '.ines']
    hdr_ident = b"NES\x1a"
    sz_header = 16
    sz_min = sz_header

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
    prettytype = "SNES ROM"
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
    sz_min = 0x10000

    devid_magic = 0x33  # Indicates extended registration data available

    def __str__(self):
        wh = "headered" if self.smc else "unheadered"
        return f'{self.name} (SNES ROM, {wh})'

    @property
    def prettytype(self):
        wh = "headered" if self.smc else "unheadered"
        return f'SNES ROM, {wh}'

    @property
    def data(self):
        """ Data block """
        offset = len(self.smc) if self.smc else 0
        return self.file[offset:]

    @property
    def header(self):
        for offset in set(self.header_locations.values()):
            log.debug("Looking for header at 0x%X", offset)
            try:
                hdr = headers['snes-hdr'](self.data[offset::Unit.bytes])
                # NOTE: header lookup raises if the would-be header goes off
                # the end of the file (e.g. identification attempt on something
                # that isn't actually an SNES rom). Possibly in other cases
                # too. I haven't decided on correct behavior; for now just
                # continue and let HeaderError get raised at the bottom.
            except ValueError as ex:
                log.debug("No header at 0x%X (%s)", offset, ex)
                continue

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


class GBARom(Rom):
    romtype = 'gba'
    prettytype = "GBA ROM"
    extensions = ['.gba']
    hdr_offset = 0xA0
    hdr_sz = 32  # bytes
    hdr_magic = 0x96
    sz_min = hdr_offset + hdr_sz

    def __init__(self, romfile, rommap=None):
        super().__init__(romfile, rommap)
        self.header = self._header()

    def _header(self):
        hcls = headers[self.romtype]
        start = self.hdr_offset
        end = start + self.hdr_sz
        try:
            return hcls(self.file[start:end:Unit.bytes])
        except IndexError:
            msg = "Header would be off the end of the data"
            raise RomFormatError(msg)

    def validate(self):
        ev = self.hdr_magic      # Expected value
        av = self.header.magic  # Actual value
        if av != ev:
            raise HeaderError(f"Bad magic number in header ({av} != {ev})")
        return True
