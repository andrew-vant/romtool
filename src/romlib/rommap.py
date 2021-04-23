"""This module contains classes for locating data within a ROM."""

import logging
from typing import Mapping
from functools import partial
from dataclasses import dataclass, field

from addict import Dict

import romlib.util as util
import romlib.text as text
from .structures import Structure, Table
from .text import TextTable


log = logging.getLogger(__name__)


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

        kwargs.ttables = Dict()
        for name, path in util.get_subfiles(root, "texttables", ".tbl"):
            msg = "Loading text table '%s' from %s"
            log.info(msg, name, path)
            with open(path) as f:
                kwargs.ttables[name] = text.add_tt(name, f)

        # Repeat for structs.
        kwargs.structs = Dict()
        log.info("Loading structures")
        structfiles = util.get_subfiles(root, 'structs', '.tsv')
        for name, path in structfiles:
            log.info("Loading structure '%s' from '%s'", name, path)
            structcls = Structure.define(name, util.readtsv(path))
            kwargs.structs[name] = structcls

        # Now load the array definitions. Note that this doesn't instantiate
        # them, just stores the appropriate kwargs for use by the program.

        kwargs.tables = Dict()
        path = root + "/arrays.tsv"
        log.info("Loading array specs from %s", path)
        specs = list(util.readtsv(path))
        for spec in specs:
            # Intify integral fields
            integral_fields = ['offset', 'count', 'stride']
            util.intify_items(spec, integral_fields)
            if not spec.index:
                spec.index = Table.make_index(
                    spec.offset,
                    spec.count,
                    spec.stride
                    )
            kwargs.tables[spec.name] = spec
        return cls(**kwargs)
