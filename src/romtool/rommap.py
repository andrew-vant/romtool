"""This module contains classes for locating data within a ROM."""

import os
import importlib.resources as resources
import logging
import types
from typing import Mapping, Sequence
from collections import ChainMap
from functools import partial
from itertools import chain
from dataclasses import dataclass, field, fields
from os.path import relpath, basename
from pathlib import Path
from hashlib import sha1
from typing import Type
import importlib.util

from addict import Dict
from appdirs import AppDirs

from . import util, text, config
from .util import cache, get_subfiles as subfiles, Handler
from .structures import Structure, BitField, Table, TableSpec
from .text import TextTable
from .exceptions import RomtoolError, MapError, RomDetectionError
from .field import Field, IntField, StructField, DEFAULT_FIELDS


log = logging.getLogger(__name__)
ichain = chain.from_iterable  # convenience
dirs = AppDirs("romtool")


class MapTest:
    def __init__(self, table, item, attribute, value):
        self.table = table
        self.item = int(item, 0)
        self.attribute = attribute or None
        try:
            self.value = int(value, 0)
        except ValueError:
            self.value = value

@dataclass
class RomMap:
    """ A ROM map

    This describes what kinds of structures a given ROM contains, their data
    format, their locations within the rom, and, for textual data, their
    encoding.
    """
    _adctfld = partial(field, default_factory=Dict)
    _ext_suffixes = ['.asm', '.ips', '.ipst', '.yaml', '.json']

    name: str = None
    path: Path = None
    structs: Mapping[str, Type[Structure]] = _adctfld()
    tables: Mapping[str, TableSpec] = _adctfld()
    ttables: Mapping[str, TextTable] = _adctfld()
    enums: Mapping[str, Type[util.RomEnum]] = _adctfld()
    tests: Sequence = list
    hooks: types.ModuleType = None
    meta: Mapping[str, str] = _adctfld()
    handlers: Mapping[str, Type[Field]] = field(default_factory=dict)
    extensions: Sequence[os.PathLike] = list

    def __post_init__(self):
        """ Perform sanity checks after construction """
        self.handlers = ChainMap(
                self.handlers,
                getattr(self.hooks, 'MAP_FIELDS', {}),
                {name: StructField for name in self.structs},
                DEFAULT_FIELDS,
                )
        # Sanity checks
        assert all(issubclass(h, Field) for h in self.handlers.values())
        for name, struct in self.structs.items():
            assert name in self.handlers
            assert issubclass(self.handlers[name], StructField)
            for field in struct.fields:
                if field.type not in self.handlers:
                    # can't happen?
                    msg = f"unknown type for {name}.{field.id}: {field.type}"
                    raise MapError(msg)
        for name, table in self.tables.items():
            if table.type not in self.handlers:
                msg = f"unknown type for table '{name}': {table.type}"
                raise MapError(msg)

    @property
    def sets(self):
        return set(t.set for t in self.tables.values() if t.set)

    def find(self, top):
        """ Find the ROM corresponding to this map under top """
        if isinstance(top, str):
            top = Path(top)
        for parent, dirs, files in os.walk(top):
            for filename in files:
                if filename == self.meta.file:
                    path = Path(parent, filename)
                    with path.open('rb') as f:
                        if sha1(f.read()).hexdigest() == self.meta.sha1:
                            return path
        raise FileNotFoundError(f"no matching rom for {self.name}")

    @classmethod
    def load(cls, root):
        """ Create a ROM map from a directory tree

        root: the directory holding the map's spec files
        """

        log.info("Loading ROM map from %s", root)

        # This doesn't work right now since the field rework, but I want to
        # preserve the technique for future use.
        #
        # Import fields.py and register any field types therein
        # try:
        #     path = root + "fields.py"
        #     log.info("Loading primitive types from %s", path)
        #     modulepath = "{}/fields.py".format(root)
        #     module = SourceFileLoader("fields", modulepath).load_module()
        # except FileNotFoundError:
        #     log.info("%s not present", path)
        # else:
        #     for name, cls in inspect.getmembers(module):
        #         if isinstance(cls, field.Field):
        #             log.info("Registering data type '%s'", name)
        #             field.register(cls)

        if isinstance(root, str):
            root = Path(root)
        kwargs = Dict(path=root)
        try:
            with root.joinpath('meta.yaml').open() as f:
                kwargs.meta = Dict(util.loadyaml(f))
        except FileNotFoundError as ex:
            log.warning(f"map metadata missing: {ex}")

        # Load python hooks, if available. This has to be done first, because
        # it might provide types used later. FIXME: I am not sure if I'm doing
        # this correctly. In particular, if for some reason multiple maps are
        # loaded, multiple modules will be created with the name 'hooks', and I
        # am not sure if python will like that.
        path = root.joinpath("hooks.py")
        spec = importlib.util.spec_from_file_location("hooks", path)
        kwargs.hooks = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(kwargs.hooks)
            log.info("hooks loaded from %s", path)
        except FileNotFoundError:
            log.info("skipping hooks, %s not present", path)

        # TODO: It should be possible to hook codecs in just like structs or
        # whatever. That makes it possible to handle things like compressed
        # text.
        def load_tt(name, f):
            return text.add_tt(name, f)

        def load_enum(name, f):
            espec = {v: k for k, v in util.loadyaml(f).items()}
            ecls = util.RomEnum(name, espec)
            return ecls

        def load_struct(name, f):
            rows = util.readtsv(f)
            scls = Structure.define_from_rows(name, rows, kwargs.handlers)
            return scls

        def load_bf(name, f):
            rows = util.readtsv(f)
            bfcls = BitField.define_from_rows(name, rows, kwargs.handlers)
            kwargs.handlers[name] = StructField
            return bfcls

        loaders = [
            ('text table', 'ttables', 'texttables', '.tbl',  load_tt),
            ('enum',       'enums',   'enums',      '.yaml', load_enum),
            ('bitfield',   'structs', 'bitfields',  '.tsv',  load_bf),
            ('struct',     'structs', 'structs',    '.tsv',  load_struct),
            ]

        kwargs.handlers = getattr(kwargs.hooks, 'MAP_FIELDS', {})
        for otype, kwarg, parent, ext, loader in loaders:
            log.info("Loading %s", parent)
            paths = ichain((subfiles(source, parent, ext)
                           for source in (None, root)))
            for path in paths:
                name = path.stem
                rpath = relpath(path, root)
                log.info("Loading %s '%s' from %s", otype, name, rpath)
                with path.open() as f:
                    kwargs[kwarg][name] = loader(name, f)

        # Now load the rom tables. Note that this doesn't instantiate them,
        # just stores the appropriate kwargs for use by the program.

        path = root.joinpath("rom.tsv")
        log.info("Loading table specs from %s", path)
        kwargs.tables = Dict()
        for record in util.readtsv(path):
            record = Dict(((k, v) for k, v in record.items()
                          if k in (f.name for f in fields(TableSpec))))
            kwargs.tables[record['id']] = TableSpec.from_tsv_row(record)
        # we should check that tables in the same set are the same length

        kwargs.tests = cls.get_tests(root)
        kwargs.extensions = list(subfiles(root, 'ext', cls._ext_suffixes))
        return cls(basename(root), **kwargs)

    @classmethod
    def get_tests(cls, root):
        """ Get the list of tests for a map

        Broken out to allow tests to be loaded without loading the map itself
        (which pollutes various global-ish classvars)
        """
        path = Path(root, "tests.tsv")
        try:
            log.info("Loading test specs from %s", path)
            return [MapTest(**row) for row in util.readtsv(path)]
        except FileNotFoundError:
            return []


class MapDB(Mapping):
    """ A RomMap database

    A DB consists of a root directory with a hashdb.txt file in it, plus any
    number of individual map directories. MapDB keys are sha1 hashes; lookups
    return a RomMap object.

    Individual maps are loaded on first lookup. The resulting RomMap is
    cached, and multiple lookups return the same object. The cache can be
    cleared with MapDB.cache_clear().

    The MapDB root must be a string or path-like object.
    """
    _builtin_db_root = resources.files(__package__).joinpath('maps')

    def __init__(self, root):
        self.root = Path(root) if isinstance(root, str) else root
        with self.root.joinpath('hashdb.txt').open() as f:
            self.hashdb = dict((line.strip().split(maxsplit=1) for line in f))

    # hash and eq implemented mainly to allow caching getitem results
    def __hash__(self):
        return hash((self.root))

    def __eq__(self, other):
        return self.root == other.root

    def __iter__(self):
        yield from self.hashdb

    def __len__(self):
        return len(self.hashdb)

    def __str__(self):
        clsname = type(self).__name__
        return f'{clsname}({self.root})'

    @cache
    def __getitem__(self, sha):
        log.debug("looking for %s under %s", sha, self.root)
        path = self.root.joinpath(self.hashdb[sha])
        try:
            return RomMap.load(path)
        except KeyError as ex:
            msg = f"unrelated keyerror during rmap load: {ex}"
            raise Exception(msg) from ex

    @classmethod
    def cache_clear(cls):
        """ Clear the map cache """
        cls.__getitem__.cache_clear()

    @classmethod
    @cache
    def defaults(cls):
        """ Get a list of the default map databases

        The resulting list will be in lookup-priority order: First paths
        specified in the config file, then the user data directory, then the DB
        that ships with romtool.
        """
        paths = [
            *[Path(p) for p in config.load('romtool.yaml').map_paths],
            Path(dirs.user_data_dir, 'maps'),
            cls._builtin_db_root,
            ]
        dbs = []
        for path in paths:
            with Handler.missing(log):
                dbs.append(cls(path))
                log.debug("mapdb present at %s", path)
        return dbs

    @classmethod
    def detect(cls, romfile, sources=None, nodefaults=False):
        """ Detect the map to use with a given ROM

        romfile: a path-like object or open rom file object
        sources: map databases to search. Sources are checked in the order
                 they are given, and the first match wins. If None, maps
                 will be looked for in the default locations.
        nodefaults: Do not search the default locations.

        Returns a RomMap object, or raises RomDetectionError.
        """
        sha = util.sha1(romfile)
        db = ChainMap(
            *(sources or []),
            *([] if nodefaults else cls.defaults()),
        )
        try:
            return db[sha]
        except KeyError as ex:
            raise RomDetectionError(str(ex), romfile) from ex
