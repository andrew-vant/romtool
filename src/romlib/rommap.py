"""This module contains classes for locating data within a ROM."""

import os
import csv
import itertools
import logging
import codecs
import inspect
from collections import OrderedDict
from types import SimpleNamespace
from importlib.machinery import SourceFileLoader
from pprint import pprint

from . import util, text, struct, field, array


class RomMap(object):
    """ A ROM Map.

    The properties of this object describe what kinds of structures a given ROM
    contains, their data format, their locations within the rom, and, for
    textual data, the text table to use to decode them.

    This is romlib's top-level object. All paths start here.
    """
    def __init__(self, root):
        """ Create a ROM map.

        root: The directory holding the map's spec files.
        """
        logging.info("Loading ROM map from %s", root)
        self.structures = OrderedDict()
        self.arrays = OrderedDict()

        # Import fields.py and register any field types therein
        try:
            path = root + "fields.py"
            logging.info("Loading primitive types from %s", path)
            modulepath = "{}/fields.py".format(root)
            module = SourceFileLoader("fields", modulepath).load_module()
        except FileNotFoundError:
            logging.info("%s not present", path)
        else:
            for name, cls in inspect.getmembers(module):
                if isinstance(cls, field.Field):
                    logging.info("Registering data type '%s'", name)
                    field.register(cls)

        # Find all tbl files in the texttables directory and register them.
        # FIXME: It should be possible to hook codecs in just like structs or
        # whatever. That makes it possible to handle things like compressed
        # text.
        logging.info("Loading text tables")
        for name, path in util.get_subfiles(root, "texttables", ".tbl"):
            msg = "Loading text table '%s' from %s"
            logging.info(msg, name, path)
            with open(path) as f:
                text.add_tt(name, f)

        # Repeat for structs.
        logging.info("Loading structures")
        structfiles = util.get_subfiles(root, 'structs', '.tsv')
        for i, (name, path) in enumerate(structfiles):
            logging.info("Loading structure '%s' from '%s'", name, path)
            structure = struct.load(path)
            self.structures[name] = structure

        # Now load the array definitions
        path = root + "/arrays.tsv"
        logging.info("Loading array specs from %s", path)
        with open(path) as f:
            specs = list(util.OrderedDictReader(f, delimiter="\t"))
        # The order in which arrays are processed matters. Indexes need to be
        # loaded before the arrays that require them. Also, in the event that
        # pointers in different arrays go to the same place and only one is
        # later edited, the last one loaded wins. The 'priority' column lets
        # the map-maker specify the winner of such conflicts by ensuring
        # higher-priority arrays get processed last.

        indexnames = set([spec['index'] for spec in specs if spec['index']])
        sorter = lambda spec: spec['name'] not in indexnames
        specs.sort(key=lambda spec: (spec['name'] not in indexnames,
                                     util.intify(spec.get('priority', 0))))
        arrays = []
        for spec in specs:
            logging.debug("Loading array: '%s'", spec['name'])
            structure = self.structures.get(spec['type'], None)
            arrays.append(array.Array(spec, structure))
        sorter = lambda arr: (isinstance(arr.index, str), arr.priority)
        for adef in sorted(arrays, key=sorter):
            self.arrays[adef.name] = adef

    def read(self, rom):
        """ Read all known data in a ROM.

        rom should be a file object opened in binary mode. The returned dataset
        is a simple namespace where the contents of each array are stored as a
        list in a property.
        """
        data = {}
        for adef in self.arrays.values():
            data[adef.name] = list(adef.read(rom, self._mkindex(adef, data)))
        return SimpleNamespace(**data)

    @staticmethod
    def _mkindex(adef, data):
        if isinstance(adef.index, str):
            try:
                tgt, attr = adef.index.split(".")
            except ValueError:
                tgt, attr = adef.index, None
            try:
                return array.CrossIndex(data[tgt], attr)
            except TypeError:
                return array.CrossIndex(getattr(data, tgt), attr)
        else:
            return None

    def dump(self, data):
        """ Dump all available ROM data.

        Returns a dictionary of lists of ordereddicts, suitable for sending to
        util.tsvwriter.
        """
        output = {}
        # Group arrays by set.
        keyfunc = lambda a: a.set
        arrays = sorted(self.arrays.values(), key=keyfunc)
        for entity, arrays in itertools.groupby(arrays, keyfunc):
            arrays = list(arrays)
            msg = "Serializing entity set '%s' (%s)"
            structnames = ", ".join(a.name for a in arrays)
            logging.info(msg, entity, structnames)
            data_subset = [getattr(data, array.name) for array in arrays]
            output[entity] = array.mergedump(data_subset, True, True)
        return output


    def load(self, modfolder):
        """ Reload the data from a previous dump."""
        data = SimpleNamespace()
        for entity in set(adef.set for adef in self.arrays.values()):
            filename = "{}/{}.tsv".format(modfolder, entity)
            logging.info("Loading arrays from: %s", filename)
            try:
                contents = util.readtsv(filename)
            except FileNotFoundError:
                logger.warning("%s missing, skipping", filename)
                continue
            arrays = (a for a in self.arrays.values() if a.set == entity)
            for adef in arrays:
                msg = "Loading array data for '%s'"
                logging.info(msg, adef.name)
                setattr(data, adef.name, list(adef.load(contents)))
        return data


    def bytemap(self, data):
        """ Get all possible changes from a data set."""
        bmap = util.CheckedDict()
        for name, adef in self.arrays.items():
            adata = getattr(data, name, None)
            if not adata:
                msg = "Tried to patch data from '%s' but it isn't there"
                logging.warning(msg, name)
                continue
            index = self._mkindex(adef, data)
            bmap.update(adef.bytemap(adata, index))
        return bmap
