import os
import csv
import itertools
from collections import OrderedDict
from types import SimpleNamespace

from bitstring import BitStream

import romlib
from .struct import StructDef, Field
from . import util, text


class RomMap(object):
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
        for name, path in _get_subfiles(root, "structs", ".csv"):
            with open(path) as f:
                reader = util.OrderedDictReader(f)
                sdef = romlib.StructDef(name, reader, self.texttables)
                self.sdefs[name] = sdef

        # Now load the array definitions
        with open("{}/arrays.csv".format(root)) as f:
            specs = list(util.OrderedDictReader(f))

        indexes = [spec for spec in specs
                   if any(otherspec['index'] == spec['name'] for otherspec in
                       specs)
        for spec in specs:
            sdef = self.sdefs.get(spec['type'], None)
            if sdef is None:
                sdef = StructDef.from_primitive(
                        _id='value',
                        _type=spec['type'],
                        label=spec['label'],
                        bits=util.tobits(spec['stride']),
                        mod=util.intify(spec['mod']),
                        display=spec['display'],
                        ttable=self.texttables.get(spec['ttable'], None)
                        )
            adef = ArrayDef(
                    name=spec['name'],
                    _set=spec['set'],
                    offset=util.intify(spec['offset']),
                    length=util.intify(spec['length']),
                    stride=util.intify(spec['stride']),
                    sdef=sdef,
                    index=self.arrays.get(spec['index'], None)
                    )
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

    def dump(self, data, dest, allow_overwrite=False):
        """ Dump ROM data to a collection of csv files.

        This produces one file for each array set.

        FIXME: Perhaps this should actually produce a dict of lists of
        orderedicts, and leave file output up to the caller? and have a
        top-level function for doing the Right Thing?
        """

        # Group arrays by set.
        arrays = sorted(self.arrays.values(), lambda a: a['set'])
        arraysets = itertools.groupby(arrays, lambda a: a['set'])

        for aset in arraysets:
            # Get a bunch of merged dictionaries representing the data in the
            # set.
            data_subset = zip(getattr(data, arr.name) for arr in aset)
            odicts = [StructDef.to_mergedict(stuff) for stuff in data_subset]

            # Note the original order of items so it can be preserved when
            # reading back a re-sorted file.
            for i, d in enumerate(odicts):
                d['_idx_'] = i

            # Now dump
            entity = aset[0].name
            filename = "{}/{}.csv".format(dest, entity)
            mode = "w" if allow_overwrite else "x"
            headers = odicts[0].keys()
            with open(filename, mode, newline='') as f:
                writer = csv.DictWriter(f, headers, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                for item in data:
                    writer.writerow(item)

    def load(self, modfolder):
        """ Reload the data from a previous dump."""
        data = SimpleNamespace()
        for entity in set(arr.set for arr in self.arrays.values()):
            filename = "{}/{}.csv".format(modfolder, entity)
            arrays = (a for a in self.arrays.values() if a.set == entity)
            try:
                with open(filename) as f:
                    dicts = list(util.OrderedDictReader(f))
                    for arr in arrays:
                        setattr(data, arr.name, arr.load(dicts))
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
    def __init__(self, name, _set, offset, length, stride, sdef, index=None):
        """ Define an array.

        name -- The name of the objects in the array.
        _set -- The set to which the array belongs.
        offset -- The offset at which the array starts, in bytes.
        length -- the number of items in the array.
        stride -- The offset from the beginning of one item to the beginning of
                  the next.
        sdef -- The structure definition for items in the array.
        index -- An optional list of integers representing the offset of each
                 item within the rom.

        If index is provided, it will be used to locate and order items in the
        array. If not provided, offset, length, and stride will be used
        instead.
        """
        if not index and not all(offset, stride, length):
            msg = "Array {} requires either an index or offset/length/stride."
            raise ValueError(msg, name)
        self.name = name
        self.set = _set if _set else name
        self.offset = offset
        self.length = length
        self.stride = stride
        self.sdef = sdef
        if index is not None:
            self.index = index.copy()
        else:
            self.index = [offset + i * stride
                          for i in range(length)]

    @classmethod
    def from_primitive(cls, name, _type, offset=0, length=0, size=0, mod=0,
                       _set=None, display=None, label=None,
                       index=None, ttable=None):
        """ Define an array of primitive values.

        This is for values that don't have an existing structdef, e.g. bare
        ints.
        """
        sdef = StructDef.from_primitive(_id='value',
                                        _type=_type,
                                        bits=size*8,
                                        label=label if label else name,
                                        mod=mod,
                                        display=display,
                                        ttable=ttable)
        return cls(name, _set, offset, length, size, sdef, index)

    @classmethod
    def from_stringdict(cls, spec, sdefs=None, ttables=None, indexes=None):
        """ Create an arraydef from a dictionary of strings.

        Mostly this is to make it convenient to get from a .csv to an arraydef.
        """
        spec = spec.copy()
        casters = {
                'offset': util.intify,
                'length': util.intify,
                'stride': util.intify
                'mod': util.intify
                }
        for key, caster in casters:
            spec[key] = caster(spec[key])

        sdef = sdefs.get(spec['type'], None)
        ttable = ttables.get(spec['display'], None)
        index = indexes.get(spec['index'], None)

        if sdef is not None:
            return ArrayDef(name=spec['name'],
                            _set=spec['set'],
                            offset=spec['offset'],
                            length=spec['length'],
                            stride=spec['stride'],
                            mod=spec['mod'],
                            sdef=sdef,
                            index=index)

        else:
            return cls.from_primitive(name=spec['name'],
                                      _type=spec['type'],
                                      offset=spec['offset'],
                                      length=spec['length'],
                                      size=spec['stride'],
                                      _set=spec['set'],
                                      display=spec['display'],
                                      label=spec['label'],
                                      index=index,
                                      ttable=ttable)


    def load(self, csvfile):
        """ Initialize a list of structures from a csv file.

        The file must be opened in text mode.
        """
        # FIXME: Means having to re-open or at least re-seek the file for files
        # containing mergedicts. Not sure what the right thing to do there is.
        for item in csv.DictReader(csvfile):
            yield self.sdef.from_dict(item)

    def dump(self, outfile, structures):
        """ Dump an array to a csv file.

        outfile must be opened in writable text mode.
        """
        self.multidump(outfile, [structures])

    def read(self, rom):
        """ Read a rom and yield structures from this array.

        rom: A file object opened in binary mode.
        """
        for offset in self.index:
            yield self.sdef.from_file(rom, offset)

    def bytemap(self, structs):
        """ Return a bytemap
        """
        bmap = {}
        for offset, struct in zip(index, structs):
            bmap.update(self.sdef.to_bytemap(struct, offset))

    @staticmethod
    def multidump(outfile, *arrays):
        """ Splice and dump multiple arrays that are part of a set. """
        odicts = [StructDef.to_mergedict(structs) for structs in zip(arrays)]
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
