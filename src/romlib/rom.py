import string
import logging
import math
import io
from operator import itemgetter
from os.path import splitext, basename
from os.path import join as pathjoin
from itertools import groupby, chain
from functools import reduce, partial
from operator import itemgetter
from collections.abc import Mapping

from bitarray import bitarray
from anytree import NodeMixin
from addict import Dict

from . import util
from .patch import Patch
from .io import Unit, BitArrayView as Stream
from .structures import Structure, Table, Entity
from .rommap import RomMap
from .exceptions import RomError, ChangesetError


log = logging.getLogger(__name__)
headers = util.load_builtins('headers', '.tsv', Structure.define_from_tsv)


class RomFormatError(RomError):
    pass


class HeaderError(RomFormatError):
    pass


class Rom(NodeMixin, util.RomObject):
    registry = {}
    extensions = []

    def __init__(self, romfile, rommap=None):
        if rommap is None:
            rommap = RomMap()
        self.name = romfile.name

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

    def __str__(self):
        return f"Rom({self.name})"

    @property
    def data(self):
        return self.file

    @property
    def tables(self):
        return {table['id']: getattr(self, table.id)
                for table in self.map.tables.values()}

    def entities(self, tset):
        # FIXME: I think I probably need an EntityList class to zip tables
        # together. I want lazy lookups and I need lookups of primitives to
        # work the same as lookups of struct keys, and I don't see a way to
        # accomplish that without a custom sequence type.

        components = {}
        for tspec in self.map.tables.values():
            if tset in (tspec.id, tspec.set):
                components[tspec.id] = getattr(self, tspec.id)
        if not components:
            raise ValueError(f"No such entity: {tset}")
        lengths = set(len(table) for table in components.values())
        if len(lengths) != 1:
            raise Exception(f"MAP BUG: mismatched table lengths in table set '{tset}'")
        for i in range(lengths.pop()):
            yield Entity(i, components)

    def dump(self, folder, force=False):
        """ Dump all rom data to `folder` in tsv format"""

        byset = lambda row: row.get('set', None) or row['id']
        tablespecs = sorted(self.map.tables.values(), key=byset)

        for tset, tspecs in groupby(tablespecs, byset):
            tspecs = [Dict(ts) for ts in tspecs]
            ct_tables = len(tspecs)
            ct_items = int(tspecs[0]['count'], 0)
            log.info(f"Dumping dataset: {tset} ({ct_tables} tables, {ct_items} items)")
            log.info(f"Dumping dataset: %s (%s tables, %s items)",
                     tset, ct_tables, ct_items)
            path = pathjoin(folder, f'{tset}.tsv')

            # Get headers sorted by field explicit order, then whether it's a
            # name, then whether it's a structural value (non-struct values are
            # usually pointers and belong at the end).
            header_ordering = {}
            def ordering(field):
                if any(s.lower() == 'name' for s in (field.id, field.name)):
                    return -1
                elif field.display == 'pointer':
                    return 1
                else:
                    return 0

            for tspec in tspecs:
                table = getattr(self, tspec.id)
                fields = (Structure.registry[table.typename].fields
                          if table.typename in Structure.registry
                          else [tspec])
                for field in fields:
                    order = (field.order or 0, ordering(field))
                    header_ordering[field.name] = order
            columns = [k for k, v
                       in sorted(header_ordering.items(),
                                 key=itemgetter(1))]
            columns.append('_idx')

            # Now turn the records themselves into dicts.
            records = []
            for i in range(ct_items):
                log.debug("Dumping %s #%s", tset, i)
                record = {'_idx': i}
                for tspec in tspecs:
                    item = getattr(self, tspec.id)[i]
                    if isinstance(item, Structure):
                        record.update(item.items())
                    else:
                        record[tspec.name] = item
                records.append(record)

            keys = set(records[0].keys())
            for r in records:
                assert not (set(r.keys()) - keys)
                assert not (set(keys - r.keys()))
            util.writetsv(path, records, force, columns)

    def lookup(self, key):
        if key in self.map.sets:
            log.debug(f"set found for {key}")
            return util.Searchable(self.entities(key))
        elif key in self.map.tables:
            return getattr(self, key)
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

        for tspec in self.map.tables.values():
            tspec = Dict(tspec)
            log.info("Loading table '%s' from set '%s'", tspec.id, tspec.set)
            table = getattr(self, tspec.id)
            for i, (orig, new) in enumerate(zip(table, data[tspec.set])):
                name = new.get('Name', 'nameless')
                log.debug("Loading %s #%s (%s)", tspec.id, i, name)
                with util.loading_context(tspec.id, name, i):
                    if isinstance(orig, Structure):
                        orig.load(new)
                    else:
                        table[i] = new[tspec['name']]

    def apply(self, changeset):
        """ Apply a dictionary of changes to a ROM

        The changeset should be a nested dictionary describing key paths in the
        ROM. Keys will be recursively looked up, starting with top-level tables
        or table sets. Subkeys may have any type or value accepted by the
        parent object's .lookup() method. Leaf keys should be attributes or
        field ids of their parent.
        """

        def flatten(dct, prefix='', sep=':'):
            for k, v in dct.items():
                if isinstance(v, Mapping):
                    yield from flatten(v, prefix+k+sep, sep=sep)
                else:
                    yield (prefix + k).split(sep), v

        for keys, value in flatten(changeset):
            attr = keys.pop()
            parent = self
            path = []
            for key in keys:
                try:
                    parent = parent.lookup(key)
                except LookupError as ex:
                    path = ':'.join(path + [str(ex)])
                    msg = f"Couldn't find item from changeset: {path}"
                    raise ChangesetError(msg)
                path.append(key)
            try:
                setattr(parent, attr, value)
            except AttributeError:
                path = ':'.join(path)
                msg = f"{attr} is not a valid attribute of {path}"
                raise ChangesetError(msg)


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
