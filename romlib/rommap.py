import os
import csv
import itertools
import romlib

from collections import OrderedDict
from . import util, text
from pprint import pprint

class RomMap(object):
    def __init__(self, root):
        """ Create a ROM map.

        root: The directory holding the map's spec files.
        """
        self.sdefs = OrderedDict()
        self.texttables = OrderedDict()
        self.arrays = OrderedDict()
        self.arraysets = OrderedDict()

        # Find all csv files in the texttables directory and load them into
        # a dictionary keyed by their base name.
        for name, path in self._get_subfiles(root, "texttables", ".tbl"):
            with open(path) as f:
                tbl = text.TextTable(name, f)
                self.texttables[name] = tbl

        # Repeat for structs.
        for name, path in self._get_subfiles(root, "structs", ".csv"):
            with open(path) as f:
                sdef = romlib.StructDef.from_file(name, f, self.texttables.values())
                self.sdefs[name] = sdef

        # Now load the array definitions
        with open("{}/arrays.csv".format(root)) as f:
            reader = util.OrderedDictReader(f)
            for spec in reader:
                sdef = self.sdefs.get(spec['type'], None)
                adef = ArrayDef(spec, sdef)
                self.arrays[adef.name] = adef

        # Construct array sets
        sets = set([a.set for a in self.arrays.values()])
        for s in sets:
            self.arraysets[s] = []
        for a in self.arrays.values():
            self.arraysets[a.set].append(a)


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


    def dump(self, rom, dest, allow_overwrite=False):
        mode = "w" if allow_overwrite else "x"
        for entity, adefs in self.arraysets.items():
            # Read the arrays in each set, then splice them.
            data = [ad.read(rom) for ad in adefs]
            data = romlib.Struct.splice(data)

            # Now dump
            filename = "{}/{}.csv".format(dest, entity)

            # Get headers and turn them into labels
            chain = itertools.chain.from_iterable
            labeler = dict(chain(ad.sdef.labelmap
                                 for ad in adefs))
            data = [util.remap_od(od, labeler) for od in data]
            headers = data[0].keys()

            with open(filename, mode, newline='') as f:
                writer = csv.DictWriter(f, headers, quoting=csv.QUOTE_ALL)
                writer.writeheader()
                for item in data:
                    writer.writerow(item)


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
            "label":    spec['name'],
            "size":     spec['stride'],
            "type":     spec['type'],
            "subtype":  "",
            "display":  "",
            "order":    "",
            "info":     "",
            "comment":  ""
        }
        return romlib.StructDef(spec['name'], [sdef_single_field])

    def read(self, rom):
        """ Read a rom and yield structures from this array.

        rom: A file object opened in binary mode.
        """
        for i in range(self.length):
            pos = self.offset + (i * self.stride)
            yield romlib.Struct(self.sdef, rom, offset=pos)

