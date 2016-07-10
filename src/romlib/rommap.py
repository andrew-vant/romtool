"""This module contains classes for locating data within a ROM."""

import os
import csv
import itertools
from collections import OrderedDict
from types import SimpleNamespace
from pprint import pprint

from . import struct
from .struct import Structure, Field, MetaStruct
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
        self.structures = OrderedDict()
        self.texttables = OrderedDict()
        self.arrays = OrderedDict()

        # Find all tbl files in the texttables directory and load them into
        # a dictionary keyed by their base name.
        for name, path in _get_subfiles(root, "texttables", ".tbl"):
            with open(path) as f:
                tbl = text.TextTable(name, f)
                self.texttables[name] = tbl

        # Repeat for structs.
        structfiles = _get_subfiles(root, 'structs', '.tsv')
        for i, (name, path) in enumerate(structfiles):
            with open(path) as f, util.loading_context('structure', name, i):
                reader = util.OrderedDictReader(f, delimiter="\t")
                fields = [Field.from_stringdict(row, available_tts=self.texttables)
                          for row in reader]
                struct = MetaStruct(name, (Structure,), {}, fields=fields)
                self.structures[name] = struct

        # Now load the array definitions
        with open("{}/arrays.tsv".format(root)) as f:
            specs = list(util.OrderedDictReader(f, delimiter="\t"))

        # The order in which arrays get loaded matters. Indexes need to be
        # loaded before the arrays that require them. Also, in the event that
        # pointers in different arrays go to the same place and only one is
        # later edited, the last one loaded wins. The 'priority' column lets
        # the map-maker specify the winner of such conflicts by ensuring
        # higher-priority arrays get loaded last.
        indexnames = set([spec['index'] for spec in specs if spec['index']])
        specs.sort(key=lambda spec: (spec['name'] not in indexnames,
                                     util.intify(spec.get('priority', 0))))

        for i, spec in enumerate(specs):
            try:
                struct = self.structures[spec['type']]
            except KeyError:
                # We have a primitive.
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
                    name = spec['name']
                    base = (Structure,)
                    struct = MetaStruct(name, base, {}, fields=[field])

            index = self.arrays.get(spec['index'], None)
            adef = ArrayDef.from_stringdict(spec, struct, index)
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
        """ Dump ROM data to a collection of tsv files.

        This produces one file for each array set.

        FIXME: Perhaps this should actually produce a dict of lists of
        orderedicts, and leave file output up to the caller? and have a
        top-level function for doing the Right Thing?
        """

        os.makedirs(dest, exist_ok=True)

        # Group arrays by set.
        arrays = sorted(self.arrays.values(), key=lambda a: a.set)

        # FIXME: I've yet to figure out how to iterate over groupby results
        # naturally so screw it for now I'll just listify everything it
        # returns...
        arraysets = [(entity, list(arrays))
                     for entity, arrays
                     in itertools.groupby(arrays, lambda a: a.set)]

        for entity, arrays in arraysets:
            filename = "{}/{}.tsv".format(dest, entity)
            mode = "w" if allow_overwrite else "x"
            data_subset = [getattr(data, array.name) for array in arrays]
            with open(filename, mode, newline='') as f:
                ArrayDef.multidump(f, *data_subset)


    def load(self, modfolder):
        """ Reload the data from a previous dump."""
        data = SimpleNamespace()
        for entity in set(arr.set for arr in self.arrays.values()):
            filename = "{}/{}.tsv".format(modfolder, entity)
            arrays = (a for a in self.arrays.values() if a.set == entity)
            try:
                with open(filename, 'rt', newline='') as f:
                    for arr in arrays:
                        setattr(data, arr.name, list(arr.load(f)))
                        f.seek(0)
            except FileNotFoundError:
                pass  # Ignore missing files. FIXME: Log warning?
        return data

    def bytemap(self, data):
        """ Get all possible changes from a data set."""
        bmap = util.CheckedDict()
        for name, arr in self.arrays.items():
            if not hasattr(data, name):
                continue  # FIXME: Log warning?
            bmap.update(arr.bytemap(getattr(data, name)))
        return bmap


class ArrayDef(object):
    """ Definition of a data table within a ROM.

    In short, this describes where a data table starts, how long it is, and
    what sort of data in contains. If cross-references to the table are against
    a separate table of pointers, that table will be used when reading,
    writing, or comparing data.
    """
    def __init__(self, name, _set, struct, offset=0, length=0, stride=0, index=None):
        """ Define an array.

        name -- The name of the objects in the array.
        _set -- The set to which the array belongs.
        struct -- The structure class for items in the array.
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
        self.struct = struct
        self.index = index
        if index:
            if self.set != index.set:
                # If the array and its index don't share a set, they won't be
                # dumped in the same tsv and the offsets can't be reaquired on
                # load.
                msg = "Array {} uses index {} but they don't share a set."
                raise ValueError(msg, self.name, index.name)
            # Indexes should only have one field so this should work...
            self._indexer = index.struct.fields[0]
            self._indices = None
        else:
            self._indexer = None
            self._indices = [offset+i*stride for i in range(length)]

    @classmethod
    def from_stringdict(cls, spec, struct, index=None):
        """ Create an arraydef from a dictionary of strings.

        Mostly this is to make it convenient to get from a .tsv to an arraydef.
        The behavior here is somewhat counterintuitive; you *do* need to create
        the struct and index (if applicable) first, and pass them to this
        function. All this does is unpack and convert non-type-related fields,
        then pass the lot on to the constructor.
        """
        return cls(name=spec['name'],
                   _set=spec['set'],
                   offset=util.intify(spec['offset']),
                   length=util.intify(spec['length']),
                   stride=util.intify(spec['stride']),
                   struct=struct,
                   index=index)

    def load(self, tsvfile):
        """ Initialize a list of structures from a tsv file.

        The file must be opened in text mode.
        """
        # FIXME: Means having to re-open or at least re-seek the file for files
        # containing mergedicts. Not sure what the right thing to do there is.
        if self.index:
            self._indices = []

        # The value in the tsvfile should be a rom offset rather than raw so we
        # don't need to mod it here...
        for item in csv.DictReader(tsvfile, delimiter="\t"):
            if self.index:
                # FIXME: I'm doing this get+cast magic enough that I should
                # probably make it a field method or something. Accept a dict,
                # return a value.
                i = item.get(self._indexer.id, item[self._indexer.label])
                self._indices.append(int(i, 0))
            yield self.struct(item)

    def dump(self, outfile, structures):
        """ Dump an array to a tsv file.

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

        bs = util.bsify(rom)
        for offset in self._indices:
            # FIXME: bits vs. bytes Should really grep for offset.
            bs.pos = offset * 8
            yield self.struct(bs)

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
            bmap.update(self.struct.bytemap(struct, offset))
        return bmap

    @staticmethod
    def multidump(outfile, *arrays):
        """ Splice and dump multiple arrays that are part of a set.

        This adds an extra '_idx_' column recording the original order of the
        items in the arrays, so it can be preserved when reading back a
        re-sorted file.
        """
        classes = [type(array[0]) for array in arrays]
        headers = struct.output_fields(*classes) + ['_idx_']
        csvopts = {"quoting": csv.QUOTE_ALL,
                   "delimiter": "\t"}
        writer = csv.DictWriter(outfile, headers, **csvopts)
        writer.writeheader()
        for i, structs in enumerate(zip(*arrays)):
            out = {}
            for structure in structs:
                out.update(structure.dump())
            out['_idx_'] = i
            writer.writerow(out)

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
