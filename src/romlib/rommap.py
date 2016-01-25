"""This module contains classes for locating data within a ROM."""

import os
import csv
import itertools
from collections import OrderedDict
from types import SimpleNamespace

from .struct import StructDef, Field
from . import util, text


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
        # FIXME: Order matters now, texttables are required to build
        # structdefs.
        self.sdefs = OrderedDict()
        self.texttables = OrderedDict()
        self.arrays = OrderedDict()

        # Find all csv files in the texttables directory and load them into
        # a dictionary keyed by their base name.
        for name, path in _get_subfiles(root, "texttables", ".tbl"):
            with open(path) as f:
                tbl = text.TextTable(name, f)
                self.texttables[name] = tbl

        # Repeat for structs.
        structfiles = _get_subfiles(root, 'structs', '.csv')
        for i, (name, path) in enumerate(structfiles):
            with open(path) as f, util.loading_context('structure', name, i):
                reader = util.OrderedDictReader(f)
                sdef = StructDef.from_stringdicts(name, reader, self.texttables)
                self.sdefs[name] = sdef

        # Now load the array definitions
        with open("{}/arrays.csv".format(root)) as f:
            specs = list(util.OrderedDictReader(f))

        # Make sure unindexed specs get loaded first to ensure that indexes get
        # loaded before the arrays that require them. This assumes no recursive
        # indexes, so it may break some day. FIXME: Do empty strings get sorted
        # before all other strings?
        specs.sort(key=lambda spec: spec['index'])
        for i, spec in enumerate(specs):
            sdef = self.sdefs.get(spec['type'], None)
            index = self.arrays.get(spec['index'], None)
            if sdef is None:
                # We have a primitive
                with util.loading_context("array spec", spec['name'], i):
                    field = Field(
                        _id=spec['name'],
                        _type=spec['type'],
                        label=spec['label'],
                        bits=util.tobits(spec['stride'], 0),
                        mod=util.intify(spec['mod']),
                        display=spec['display'],
                        ttable=self.texttables.get(spec['display'], None)
                        )
                    sdef = StructDef(spec['name'], [field])
            adef = ArrayDef.from_stringdict(spec, sdef, index)
            self.arrays[adef.name] = adef


    def read(self, rom):
        """ Read all known data in a ROM.

        rom should be a file object opened in binary mode. The returned object
        is a simple namespace where the contents of each array are stored as a
        list in a property.
        """
        data = SimpleNamespace()
        for arr in self.arrays.values():
            setattr(data, arr.name, list(arr.read(rom)))
        return data

    def dump(self, data, dest, allow_overwrite=False):
        """ Dump ROM data to a collection of csv files.

        This produces one file for each array set.

        FIXME: Perhaps this should actually produce a dict of lists of
        orderedicts, and leave file output up to the caller? and have a
        top-level function for doing the Right Thing?
        """

        # Group arrays by set.
        arrays = sorted(self.arrays.values(), key=lambda a: a.set)
        # FIXME: I've yet to figure out how to iterate over groupby results
        # naturally so screw it for now I'll just listify everything it
        # returns...
        arraysets = [(entity, list(arrays))
                     for entity, arrays
                     in itertools.groupby(arrays, lambda a: a.set)]

        for entity, arrays in arraysets:
            # Get a bunch of merged dictionaries representing the data in the
            # set.
            data_subset = zip(*[getattr(data, arr.name) for arr in arrays])
            odicts = [StructDef.multidump(item) for item in data_subset]

            # Note the original order of items so it can be preserved when
            # reading back a re-sorted file.
            for i, odict in enumerate(odicts):
                odict['_idx_'] = i

            # Now dump
            filename = "{}/{}.csv".format(dest, entity)
            mode = "w" if allow_overwrite else "x"
            headers = odicts[0].keys()
            with open(filename, mode, newline='') as f:
                writer = csv.DictWriter(f, headers, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                for item in odicts:
                    writer.writerow(item)

    def load(self, modfolder):
        """ Reload the data from a previous dump."""
        data = SimpleNamespace()
        for entity in set(arr.set for arr in self.arrays.values()):
            filename = "{}/{}.csv".format(modfolder, entity)
            arrays = (a for a in self.arrays.values() if a.set == entity)
            try:
                with open(filename, 'rt', newline='') as f:
                    for arr in arrays:
                        setattr(data, arr.name, list(arr.load(f)))
            except FileNotFoundError:
                pass # Ignore missing files. FIXME: Log warning?
        return data

    def bytemap(self, data):
        """ Get all possible changes from a data set."""
        bmap = {}
        for name, arr in self.arrays.items():
            bmap.update(arr.bytemap(getattr(data, name)))
        return bmap


class ArrayDef(object):
    """ Definition of a data table within a ROM.

    In short, this describes where a data table starts, how long it is, and
    what sort of data in contains. If cross-references to the table are against
    a separate table of pointers, that table will be used when reading,
    writing, or comparing data.
    """
    def __init__(self, name, _set, sdef, offset=0, length=0, stride=0, index=None):
        """ Define an array.

        name -- The name of the objects in the array.
        _set -- The set to which the array belongs.
        sdef -- The structure definition for items in the array.
        offset -- The offset at which the array starts, in bytes.
        length -- the number of items in the array.
        stride -- The offset from the beginning of one item to the beginning of
                  the next.
        index -- an optional ArrayDef describing an array of pointers.

        If index is provided, it will be used to locate and order items in the
        array. If not provided, offset, length, and stride will be used
        instead.
        """
        if not index and not all([offset, stride, length]):
            msg = "Array {} requires either an index or offset/length/stride."
            raise ValueError(msg, name)
        self.name = name
        self.set = _set or name
        self.offset = offset
        self.length = length
        self.stride = stride
        self.sdef = sdef
        self.index = index
        if index:
            if self.set != index.set:
                # If the array and its index don't share a set, they won't be
                # dumped in the same csv and the offsets can't be reaquired on
                # load.
                msg = "Array {} uses index {} but they don't share a set."
                raise ValueError(msg, self.name, index.name)
            # Indexes should only have one field so this should work...
            self._indexer = next(iter(index.sdef.fields.values()))
            self._indices = None
        else:
            self._indexer = None
            self._indices = [offset+i*stride for i in range(length)]

    @classmethod
    def from_stringdict(cls, spec, sdef, index=None):
        """ Create an arraydef from a dictionary of strings.

        Mostly this is to make it convenient to get from a .csv to an arraydef.
        The behavior here is somewhat counterintuitive; you *do* need to create
        the sdef and index (if applicable) first, and pass them to this
        function. All this does is unpack and convert non-type-related fields,
        then pass the lot on to the constructor.
        """
        return cls(name=spec['name'],
                   _set=spec['set'],
                   offset=util.intify(spec['offset']),
                   length=util.intify(spec['length']),
                   stride=util.intify(spec['stride']),
                   sdef=sdef,
                   index=index)

    def load(self, csvfile):
        """ Initialize a list of structures from a csv file.

        The file must be opened in text mode.
        """
        # FIXME: Means having to re-open or at least re-seek the file for files
        # containing mergedicts. Not sure what the right thing to do there is.
        if self.index:
            self._indices = []

        # The value in the csvfile should be a rom offset rather than raw so we
        # don't need to mod it here...
        for item in csv.DictReader(csvfile):
            if self.index:
                self._indices.append(int(item[self._indexer.id], 0))
            yield self.sdef.load(item)

    def dump(self, outfile, structures):
        """ Dump an array to a csv file.

        outfile must be opened in writable text mode.
        """
        self.multidump(outfile, [structures])

    def read(self, rom):
        """ Read a rom and yield structures from this array.

        rom: A file object opened in binary mode.
        """
        if self._indices is None:
            mod = self._indexer.mod
            attr = self._indexer.id
            self._indices = [getattr(struct, attr) + mod
                             for struct in self.index.read(rom)]

        for offset in self._indices:
            # FIXME: bits vs. bytes Should really grep for offset.
            yield self.sdef.read(rom, offset*8)

    def bytemap(self, structs, indices=None):
        """ Return a bytemap.

        Indices need only be provided for indexed arrays that have been built
        "from scratch" i.e. not from .load or .read. This should happen
        approximately never.
        """

        if indices is None:
            indices = self._indices
        bmap = {}
        for offset, struct in zip(indices, structs):
            bmap.update(self.sdef.bytemap(struct, offset))
        return bmap

    @staticmethod
    def multidump(outfile, *arrays):
        """ Splice and dump multiple arrays that are part of a set. """
        odicts = [StructDef.multidump(structs) for structs in zip(arrays)]
        writer = csv.DictWriter(outfile, odicts[0].keys())
        writer.writeheader()
        for odict in odicts:
            writer.writerow(odict)


def _get_subfiles(root, folder, extension):
    try:
        filenames = [filename for filename
                     in os.listdir("{}/{}".format(root, folder))
                     if filename.endswith(extension)]
        names = [os.path.splitext(filename)[0]
                 for filename in filenames]
        paths = ["{}/{}/{}".format(root, folder, filename)
                 for filename in filenames]
        return zip(names, paths)
    except FileNotFoundError:
        # FIXME: Subfolder missing. Log warning here?
        return []
