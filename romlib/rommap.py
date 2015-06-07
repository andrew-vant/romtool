from collections import OrderedDict


class RomMap(object):
    def __init__(self, root):
        self.structs = {}
        self.texttables = {}
        self.arrays = {}
        self.arraysets = {}

        # Find all the csv files in the structs directory and load them into
        # a dictionary keyed by their base name.
        structfiles = [f for f
                       in os.listdir("{}/structs".format(root))
                       if f.endswith(".csv")]
        for sf in structfiles:
            typename = os.path.splitext(sf)[0]
            struct = StructDef.from_file("{}/structs/{}".format(root, sf))
            self.structs[typename] = struct

        # Repeat for text tables.
        try:
            ttfiles = [f for f
                       in os.listdir("{}/texttables".format(root))
                       if f.endswith(".tbl")]
        except FileNotFoundError:
            # FIXME: Log warning here?
            ttfiles = []

        for tf in ttfiles:
            tblname = os.path.splitext(tf)[0]
            tbl = text.TextTable("{}/texttables/{}".format(root, tf))
            self.texttables[tblname] = tbl

        # Now load the array definitions.
        with open("{}/arrays.csv".format(root)) as f:
            arrays = [ArrayDef(od, self.structs)
                      for od in OrderedDictReader(f)]
            self.arrays = {a['name']: a for a in arrays}
            arraysets = set([a['set'] for a in arrays])
            for _set in arraysets:
                self.arraysets[_set] = [a for a in arrays if a['set'] == _set]

    def dump(self, rom, folder, allow_overwrite=False):
        """ Look at a ROM and export all known data to folder."""
        stream = ConstBitStream(rom)
        mode = "w" if allow_overwrite else "x"
        for entity, arrays in self.arraysets.items():
            # Read in each array, then dereference any pointers
            data = [array.read(stream) for array in arrays]
            for array in data:
                for struct in array:
                    struct.calculate(rom)
            # Now merge corresponding items in each set.
            data = [Struct.merged_od(structset)
                    for structset in zip(*data)]
            # Now dump.
            fname = "{}/{}.csv".format(folder, entity)
            with open(fname, mode, newline='') as f:
                writer = DictWriter(f, data[0].keys(), quoting=csv.QUOTE_ALL)
                writer.writeheader()
                for item in data:
                    writer.writerow(item)

    def makepatch(self, romfile, modfolder, patchfile):
        # Get the filenames for all objects. Assemble a dictionary mapping
        # object types to all objects of that type.
        files = [f for f in os.listdir(modfolder)
                 if f.endswith(".csv")]
        paths = [os.path.join(modfolder, f) for f in files]
        objnames = [os.path.splitext(f)[0] for f in files]
        objects = {}
        for name, path in zip(objnames, paths):
            with open(path) as f:
                objects[name] = list(OrderedDictReader(f))

        # This mess splits the object-to-data mapping into an array-to-data
        # mapping. This should really be functioned out and unit tested
        # because it is confusing as hell.
        data = {array['name']: [] for array in self.arrays.values()}
        for otype, objects in objects.items():
            for array in self.arraysets[otype]:
                for o in objects:
                    data[array['name']].append(array.struct.extract(o))

        # Now get a list of bytes to change.
        changed = {}
        for arrayname, contents in data.items():
            a = self.arrays[arrayname]
            offset = int(a['offset'] // 8)
            stride = int(a['stride'] // 8)
            for item in contents:
                changed.update(a.struct.changeset(item, offset))
                offset += stride
        # Generate the patch
        p = Patch(changed)
        with open(romfile, "rb") as rom:
            p.filter(rom)
        with open(patchfile, "wb+") as patch:
            p.to_ips(patch)


class ArrayDef(OrderedDict):
    requiredproperties = ["name", "type", "offset",
                          "length", "stride", "comment"]

    def __init__(self, od, structtypes={}):
        super().__init__(od)
        if self['type'] in structtypes:
            self.struct = structtypes[self['type']]
        else:
            self.struct = StructDef.from_primitive_array(self)
        self['offset'] = tobits(self['offset'])
        self['stride'] = tobits(self['stride'])
        if not self['set']:
            self['set'] = self['name']
        if not self['label']:
            self['label'] = self['name']

    def read(self, stream):
        for i in range(int(self['length'])):
            pos = i*self['stride'] + self['offset']
            yield self.struct.read(stream, pos)
