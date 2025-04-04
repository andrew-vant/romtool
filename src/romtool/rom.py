""" Objects representing a ROM file. """
import string
import logging
import math
import io
import re
import subprocess as sp
from functools import cmp_to_key
from os.path import splitext, basename
from os.path import join as pathjoin
from shutil import which
from tempfile import TemporaryDirectory

from bitarray import bitarray
from addict import Dict
from more_itertools import unique_everseen as unique

from . import util
from .patch import Patch
from .io import Unit, BitArrayView as Stream
from .structures import Structure, Strings, Table, Index, EntityList
from .rommap import RomMap
from .util import locate
from .exceptions import RomError, RomtoolError, ChangesetError


log = logging.getLogger(__name__)
headers = util.load_builtins('headers', '.tsv', Structure.define_from_tsv)


class RomFormatError(RomError):
    """ Input file not the expected type of ROM """


class HeaderError(RomFormatError):
    """ ROM header failed to validate """


class Rom(util.NodeMixin):
    """ Base class for ROMs """
    romtype = 'unknown'
    prettytype = "Unknown ROM type"
    registry = {}
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
        # Load indexes before any tables that depend on them

        def cmp(spec1, spec2):
            return (1 if spec1.index == spec2.id
                    else -1 if spec2.index == spec1.id
                    else 0)

        for spec in sorted(self.map.tables.values(), key=cmp_to_key(cmp)):
            # Check for table class overrides, otherwise infer from spec
            cls = getattr(rommap.hooks, spec.cls,
                          Strings if spec.type == 'strz' and spec.stride == 0
                          else Table)
            index = (None if not spec.index
                     else self.tables[spec.index] if spec.index in self.tables
                     else Index(spec.index, self.tables, spec.count))
            log.info("creating table %s as class %s", spec.id, cls)
            self.tables[spec.id] = cls(self.data, self, spec, index)
        # Sanity check
        for t in self.tables.values():
            assert (t.spec.index not in self.map.tables
                    or t._index == self.tables[t.spec.index])
        self.entities = Dict()
        specs = list(self.map.tables.values())
        for tset in unique(spec.set for spec in specs):
            if not tset:
                # Ignore tables that aren't associated with an entity
                continue
            parts = [self.tables[spec.id] for spec in specs
                     if spec.set == tset]
            # FIXME: add format dunder to types involved?
            pdesc = ', '.join(p.name or p.id for p in parts)
            log.debug("making entityset '%s' from table(s): [%s]", tset, pdesc)
            self.entities[tset] = EntityList(tset, parts)

    def __str__(self):
        return f"{self.name} ({self.prettytype})"

    @property
    def name(self):
        """ The name of this ROM, if known """
        return (util.nointro().get(self.data.sha1)
                or util.nointro().get(self.data.sha1)
                or self.map.name
                or "Unknown ROM")

    @property
    def rom(self):
        """ Alias for rom.data. """
        return self.data

    @property
    def data(self):
        """ A bitview of the ROM's data, omitting any header """
        return self.file

    def dump(self, folder, force=False):
        """ Dump all rom data to `folder` in tsv format"""
        for name, elist in self.entities.items():
            log.info("Dumping %s (%s items)", name, len(elist))
            path = pathjoin(folder, f'{name}.tsv')
            util.dumptsv(path, elist, force, elist.etype.keys(), '_idx')

    def lookup(self, key):
        """ Look up a rom table or entityset by ID """
        # FIXME: hate the whole call chain this is involved in
        if key in self.map.sets:
            log.debug("set found for %s", key)
            return util.Searchable(self.entities[key])
        if key in self.map.tables:
            return self.map.tables[key]
        raise LookupError(f"no table or set with id '{key}'")

    def apply_moddir(self, folder):
        """ Apply ROM changes from a modified dump directory """
        data = {}
        for _set in self.map.sets:
            path = pathjoin(folder, f'{_set}.tsv')
            log.debug("loading mod set '%s' from %s", _set, path)
            try:
                contents = util.readtsv(path)
            except FileNotFoundError as ex:
                log.warning("skipping %s: %s", _set, ex)
                continue
            try:
                # Put items back in their original order if possible.
                contents = sorted(contents,
                                  key=lambda row: int(row['_idx'], 0))
            except KeyError:
                log.warning('%s._idx not present; using input order', _set)
            data[_set] = contents

        with locate.cached():
            # Crossref resolution is slow. Cache results during load. FIXME: I
            # am *sure* there's a better way to do this. Should probably
            # iterate over the input data rather than the entity list, for one
            # thing, so missing entries are skipped instead of breaking.
            for etype, elist in self.entities.items():
                if etype not in data:
                    continue
                log.info("Loading %s %s", len(elist), etype)
                for i, (orig, new) in enumerate(zip(elist, data[etype])):
                    name = new.get('Name', 'nameless')
                    log.debug("Loading %s #%s (%s)", etype, i, name)
                    with util.loading_context(etype, name, i):
                        orig.update(new)

    def apply_changeset(self, changeset):
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
                    raise ChangesetError(msg) from ex
            try:
                setattr(parent, attr, value)
            except AttributeError as ex:
                path = ':'.join(str(k) for k in path)
                msg = f"{attr} is not a valid attribute of {path}"
                raise ChangesetError(msg) from ex

    def apply_assembly(self, path):
        """ Insert assembly code into the ROM

        Scans the input for a line matching 'romtool: patch@{address}', which
        indicates where the assembled bytecode should be inserted. Then passes
        the code itself to an external assembler.

        Expects the content of the file as a string.
        """
        re_ctrl = r'romtool: patch@([0-9A-Fa-f]+):(.*)$'
        with util.flexopen(path) as stream:
            for i, line in enumerate(stream):
                match = re.search(re_ctrl, line)
                if match:
                    try:
                        location = int(match.group(1), 16)
                        cmd = match.group(2)
                    except ValueError as ex:
                        msg = f"error on line {i}: {ex}"
                        raise ChangesetError(msg) from ex
                    break
            else:
                raise ChangesetError("no patch location given")

        with TemporaryDirectory(prefix='romtool.') as tmp:
            outfile = f'{tmp}/{basename(path)}.bin'
            # FIXME: cl65 leaves a .o file behind next to the original .asm,
            # making it appear as a map extension on next run.
            known_assemblers = {
                'cl65': [which('cl65'), '-t', 'none', '-o', outfile, path],
                'xa65': [which('xa'), '-w', '-c', '-M', '-o', outfile, path],
                }
            args = known_assemblers.get(cmd)
            if not args:
                raise RomtoolError(f"don't know how to assemble with {cmd}")
            log.info("assembling %s", basename(path))
            # FIXME: pretty sure this won't work for resources pulled from zip.
            # Not sure what to do about that yet.
            log.debug("executing external command: %s",
                      " ".join(str(arg) for arg in args))
            proc = sp.run(args, check=False)
            if proc.returncode:
                raise ChangesetError(f"external assembly failed with return "
                                     f"code {proc.returncode}")
            with util.flexopen(outfile, 'rb') as stream:
                data = stream.read()
        end = location + len(data)
        log.info("patching assembled %s to %s (%s bytes)",
                 basename(path), hex(location), len(data))
        self.data[location:end:Unit.bytes].bytes = data

    @property
    def patch(self):
        """ Generate a patch incorporating any changes to this ROM """
        old = io.BytesIO(self.orig.bytes)
        new = io.BytesIO(self.file.bytes)
        return Patch.from_diff(old, new)

    def changes(self):
        """ Generate changeset dictionary """
        # This might be hard. Loop over each table, look for items that differ
        # between orig and self, emit table:name:key:value dict tree
        raise RomtoolError("Changeset generator not implemented yet")

    def apply_patch(self, patch):
        """ Apply a Patch to this ROM """
        contents = io.BytesIO(self.file.bytes)
        patch.apply(contents)
        contents.seek(0)
        self.file.bytes = contents.read()

    def validate(self):
        """ Validate the format of this ROM

        Subclasses are expected to override this method, and should raise a
        RomFormatError if there is a problem with the ROM format.
        """
        raise NotImplementedError(f"No validator available for {type(self)}")

    def __init_subclass__(cls, extensions=None, **kwargs):
        super().__init_subclass__(**kwargs)
        name = cls.__name__
        extensions = extensions or []
        for ext in extensions:
            if ext in cls.registry:
                msg = ("%s attempted to claim %s extension, but it is "
                       "already registered; ignoring")
                log.warning(msg, name, ext)
            else:
                log.debug('registering file extension %s as %s', ext, name)
                cls.registry[ext] = cls

    @classmethod
    def make(cls, romfile, rommap=None, ignore_extension=False):
        """ Construct a Rom from a file of unknown type """
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

    def write(self, target, force=True):
        """ Write a rom to a path or file object """
        mode = 'wb' if force else 'xb'
        with util.flexopen(target, mode) as stream:
            stream.write(self.file.bytes)


class INESRom(Rom, extensions=('.nes', '.ines')):
    """ An NES ROM in .ines format """
    romtype = 'ines'
    prettytype = "INES ROM"
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


class SNESRom(Rom, extensions=['.sfc', '.smc']):
    """ An SNES ROM """
    romtype = 'snes'
    prettytype = "SNES ROM"
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
        return f'{self.name} ({self.prettytype})'

    @property
    def prettytype(self):  # pylint: disable=function-redefined
        """ Override of prettytype that includes SMC header status """
        detail = "headered" if self.smc else "unheadered"
        return f'SNES ROM, {detail}'

    @property
    def data(self):
        """ Data block """
        offset = len(self.smc) if self.smc else 0
        return self.file[offset:]

    @property
    def header(self):
        """ The SNES internal metadata header

        Note that this is distinct from the SMC header.
        """
        # FIXME: This 'header' has three slightly-different possible formats,
        # registration data isn't always included, and I don't think I'm
        # handling this very well. *Probably* I should have three variations of
        # the `snes-hdr` structure.
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

            # Header version 2 has a null byte where the last printable
            # character would be, so strip it for this check.
            if all(chr(c) in string.printable for c in hdr.b_name[:-1]):
                log.debug("0x%X: name check: ok", offset)
            else:
                log.debug("0x%X: name check: failed "
                          "(unprintable chars in name)",
                          offset)

            log.debug("0x%X: valid header found", offset)
            return hdr
        raise HeaderError("No valid SNES header found")

    @property
    def registration(self):
        """ The ROM's registration data, if available """
        if self.header.devid != self.devid_magic:
            return None
        offset = self.header_locations[self.header.mapmode] - 0x10
        return headers['snes-reg'](self.data[offset::Unit.bytes])

    @property
    def smc(self):
        """ The SMC header, if present """
        sz_smc = self.file.ct_bytes % 1024
        if sz_smc == 0:
            return None
        if sz_smc == self.sz_smc:
            return self.file[0:sz_smc:Unit.bytes]
        raise HeaderError("Bad rom file size or corrupt SMC header")

    @property
    def checksum(self):
        """ The ROM's data checksum

        For comparison against the expected checksum in the metadata header.
        """
        if not math.log(self.data.ct_bytes, 2).is_integer():
            msg = "Rom size {self.data.ct_bytes} is not a power of two"
            raise NotImplementedError(msg)
        return sum(self.data.bytes) % 0xFFFF

    def validate(self):
        return bool(self.header)


class GBARom(Rom, extensions=['.gba']):
    """ A Gameboy Advance ROM """
    romtype = 'gba'
    prettytype = "GBA ROM"
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
        except IndexError as ex:
            msg = "Header would be off the end of the data"
            raise RomFormatError(msg) from ex

    def validate(self):
        expected = self.hdr_magic      # Expected value
        actual = self.header.magic  # Actual value
        if actual != expected:
            msg = f"Bad magic number in header ({actual} != {expected})"
            raise HeaderError(msg)
        return True
