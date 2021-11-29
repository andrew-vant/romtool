"""This module contains classes for locating data within a ROM."""

import os
import logging
from typing import Mapping, Sequence
from functools import partial
from dataclasses import dataclass, field
from os.path import relpath

from addict import Dict

import romlib.util as util
import romlib.text as text
from .structures import Structure, BitField, Table
from .text import TextTable


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

    structs: Mapping[str, Structure] = _adctfld()
    tables: Mapping[str, Table] = _adctfld()
    ttables: Mapping[str, TextTable] = _adctfld()
    tests: Sequence = list


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
        """
        # Import fields.py and register any field types therein
        try:
            path = root + "fields.py"
            log.info("Loading primitive types from %s", path)
            modulepath = "{}/fields.py".format(root)
            module = SourceFileLoader("fields", modulepath).load_module()
        except FileNotFoundError:
            log.info("%s not present", path)
        else:
            for name, cls in inspect.getmembers(module):
                if isinstance(cls, field.Field):
                    log.info("Registering data type '%s'", name)
                    field.register(cls)
        """

        # Find all tbl files in the texttables directory and register them.
        # TODO: It should be possible to hook codecs in just like structs or
        # whatever. That makes it possible to handle things like compressed
        # text.
        log.info("Loading text tables")
        kwargs = Dict()
        files = partial(util.get_subfiles, root)

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
            structcls = Structure.define_from_tsv(path)
            kwargs.structs[name] = structcls

        # Now load the array definitions. Note that this doesn't instantiate
        # them, just stores the appropriate kwargs for use by the program.

        kwargs.tables = Dict()
        path = root + "/arrays.tsv"
        log.info("Loading array specs from %s", path)
        kwargs.tables = {record['id']: record for record in util.readtsv(path)}
        # we should check that tables in the same set are the same length

        path = root + "/tests.tsv"
        if os.path.exists(path):
            log.info("Loading test specs from %s", path)
            kwargs.tests = [MapTest(**row) for row in util.readtsv(path)]

        return cls(**kwargs)
