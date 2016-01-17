import os
import csv
import romlib

from collections import OrderedDict
from itertools import chain, groupby

from . import util, text
from .struct import Struct
from pprint import pprint


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
        for name, path in self._get_subfiles(root, "texttables", ".tbl"):
            with open(path) as f:
                tbl = text.TextTable(name, f)
                self.texttables[name] = tbl

        # Repeat for structs.
        for name, path in self._get_subfiles(root, "structs", ".csv"):
            with open(path) as f:
                tts = self.texttables.values()
                reader = util.OrderedDictReader(f)
                sdef = romlib.StructDef(name, reader, self.texttables)
                self.sdefs[name] = sdef

        # Now load the array definitions
        with open("{}/arrays.csv".format(root)) as f:
            reader = util.OrderedDictReader(f)
            for spec in reader:
                sdef = self.sdefs.get(spec['type'], None)
                adef = ArrayDef(spec, sdef)
                self.arrays[adef.name] = adef

    def _get_subfiles(self, root, folder, extension):
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
            bmap.update(arr.bytemap(getattr(data, name))
        return bmap


class ArrayDef(object):
    def __init__(self, spec, sdef=None):
        # Record some basics, convert as needed.
        self.name = spec['name']
        self.type = spec['type']
        self.length = int(spec['length'])
        self.offset = util.tobits(spec['offset'])
        self.stride = util.tobits(spec['stride'])

        # If no set ID is provided, use our name. Same thing for labels.
        # The somewhat awkward use of get here is because we want to treat
        # an empty string the same as a missing element.
        self.set = spec['set'] if spec.get('set', None) else self.name
        self.label = spec['label'] if spec.get('label', None) else self.name

        # If no sdef is provided, assume we're an array of primitives.
        self.sdef = sdef if sdef else self._init_primitive_structdef(spec)

    def _init_primitive_structdef(self, spec):
        sdef_single_field = {
            "id":       "value",
            "label":    spec['label'],
            "size":     spec['stride'],
            "type":     spec['type'],
            "subtype":  "",
            "display":  spec['display'],
            "mod":      spec['mod'],
            "order":    "",
            "info":     "",
            "comment":  ""
        }
        return romlib.StructDef(spec['name'], [sdef_single_field])


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
        bs = BitStream(rom)
        for i in range(self.length):
            pos = self.offset + (i * self.stride)
            yield self.sdef.from_bitstream(bs, pos)

    def bytemap(self, structs):
        """ Return a bytemap
        """
        bmap = {}
        for i, struct in enumerate(structs):
            offset = self.offset + self.stride * i
            bmap.update(self.sdef.to_bytemap(struct, offset))
        return bmap

    @staticmethod
    def multidump(outfile, *arrays):
        """ Splice and dump multiple arrays that are part of a set. """
        odicts = [StructDef.to_mergedict(structs) for structs in zip(arrays)]
        writer = csv.DictWriter(outfile, odicts[0].keys())
        writer.writeheader()
        for odict in odicts:
            writer.writerow(odict)
