"""This module contains classes for locating data within a ROM."""

import os
import logging
import types
from typing import Mapping, Sequence
from functools import partial
from dataclasses import dataclass, field
from os.path import relpath, basename
from pathlib import Path
import importlib.util

from addict import Dict

import romlib.util as util
import romlib.text as text
from .structures import Structure, BitField, Table
from .text import TextTable
from .exceptions import RomtoolError, MapError
from .types import IntField


log = logging.getLogger(__name__)


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

    name: str = 'unknown'
    path: Path = None
    structs: Mapping[str, Structure] = _adctfld()
    tables: Mapping[str, Table] = _adctfld()
    ttables: Mapping[str, TextTable] = _adctfld()
    enums: Mapping[str, util.RomEnum] = _adctfld()
    tests: Sequence = list
    hooks: types.ModuleType = None
    meta: Mapping[str, str] = _adctfld()

    @property
    def sets(self):
        return set(t['set'] for t in self.tables.values())

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

        kwargs = Dict()
        kwargs.path = Path(root)
        try:
            path = Path(root, 'meta.yaml')
            with open(path) as f:
                kwargs.meta = Dict(util.loadyaml(f))
        except FileNotFoundError as ex:
            log.warning(f"map metadata missing: {ex}")

        # Load python hooks, if available. This has to be done first, because
        # it might provide types used later. FIXME: I am not sure if I'm doing
        # this correctly. In particular, if for some reason multiple maps are
        # loaded, multiple modules will be created with the name 'hooks', and I
        # am not sure if python will like that.
        path = root + "/hooks.py"
        spec = importlib.util.spec_from_file_location("hooks", path)
        hooks = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(hooks)
        except FileNotFoundError:
            log.info("skipping hooks, %s not present", path)
        else:
            kwargs.hooks = hooks

        # Find all tbl files in the texttables directory and register them.
        # TODO: It should be possible to hook codecs in just like structs or
        # whatever. That makes it possible to handle things like compressed
        # text.
        def files(folder, ext):
            yield from util.get_subfiles(None, folder, ext)
            yield from util.get_subfiles(root, folder, ext)

        # TODO: lots of repetition here, can I function it out? args for
        # subdir, description, loaderfunc?

        log.info("Loading text tables")
        kwargs.ttables = Dict()
        for name, path in files('texttables', '.tbl'):
            rpath = relpath(path, root)
            log.info("Loading text table '%s' from %s", name, rpath)
            with open(path) as f:
                kwargs.ttables[name] = text.add_tt(name, f)

        # Repeat for bitfields
        kwargs.structs = Dict()
        log.info("Loading bitfields")
        for name, path in files('bitfields', '.tsv'):
            rpath = relpath(path, root)
            log.info("Loading bitfield '%s' from '%s'", name, rpath)
            structcls = BitField.define_from_tsv(path)
            kwargs.structs[name] = structcls

        # Repeat for structs.
        kwargs.structs = Dict()
        log.info("Loading structures")
        for name, path in files('structs', '.tsv'):
            rpath = relpath(path, root)
            log.info("Loading structure '%s' from '%s'", name, rpath)
            try:
                structcls = Structure.define_from_tsv(path)
            except RomtoolError as ex:
                msg = f"Map bug in '{name}' structure: {ex}"
                raise MapError(msg)
            kwargs.structs[name] = structcls

        # Again for enums
        kwargs.enums = Dict()
        log.info("Loading enums")
        for name, path in files('enums', '.yaml'):
            rpath = relpath(path, root)
            log.info("Loading enum '%s' from '%s'", name, rpath)
            try:
                with open(path) as f:
                    espec = {v: k for k, v in util.loadyaml(f).items()}
                ecls = util.RomEnum(name, espec)
                IntField.handle(name, ecls)
            except RomtoolError as ex:
                msg = f"Map bug in '{name}' enum: {ex}"
                raise MapError(msg)
            kwargs.enums[name] = ecls

        # Now load the array definitions. Note that this doesn't instantiate
        # them, just stores the appropriate kwargs for use by the program.

        path = root + "/arrays.tsv"
        log.info("Loading array specs from %s", path)
        kwargs.tables = Dict()
        for record in util.readtsv(path):
            tspec = Dict(record)
            if (tspec.source or 'rom') != 'rom':
                log.warning(f"skipping '{tspec.id}' array with invalid "
                            f"source '{tspec.source}'")
            elif tspec.type in ['str', 'strz'] and not tspec.display:
                raise MapError(f"Map bug in {tspec.id} array: "
                               f"'display' is required for string types")
            else:
                kwargs.tables[record['id']] = Dict(record)
        # we should check that tables in the same set are the same length

        path = root + "/tests.tsv"
        try:
            log.info("Loading test specs from %s", path)
            kwargs.tests = [MapTest(**row) for row in util.readtsv(path)]
        except FileNotFoundError:
            kwargs.tests = []

        return cls(basename(root), **kwargs)
