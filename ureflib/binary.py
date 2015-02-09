import logging, os, csv, sys
from bitstring import ConstBitStream
from collections import OrderedDict
from csv import DictWriter
from . import text

from .util import tobits, validate_spec, OrderedDictReader

class RomMap(object):
    def __init__(self, root):
        self.structs = {}
        self.texttables = {}
        self.arrays = []

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
        ttfiles = [f for f
                   in os.listdir("{}/texttables".format(root))
                   if f.endswith(".tbl")]
        for tf in ttfiles:
            tblname = os.path.splitext(tf)[0]
            tbl = text.TextTable("{}/texttables/{}".format(root, tf))
            self.texttables[tblname] = tbl

        # Now load the array definitions.
        with open("{}/arrays.csv".format(root)) as f:
            self.arrays = [ArrayDef(od, self.structs)
                           for od in OrderedDictReader(f)]


    def dump(self, rom, folder, allow_overwrite=False):
        """ Look at a ROM and export all known data to folder."""
        stream = ConstBitStream(rom)
        mode = "w" if allow_overwrite else "x"
        for array in self.arrays:
            fname = "{}/{}.csv".format(folder, array['name'])
            data = array.read(stream)
            data = [d.struct_def.dereference_pointers(d, self, rom)
                    for d in data]
            with open(fname, mode, newline='') as f:
                # Note that we need to use QUOTE_ALL or spreadsheet programs
                # will do bad things to bitfields that start with zero.
                writer = DictWriter(f, data[0].keys(), quoting=csv.QUOTE_ALL)
                labels = {field['id']: field['label']
                          for field in array.struct.values()}
                labels.update({field['id']: field['id']
                              for field in array.struct.pointers})
                writer.writerow(labels)
                for struct in data:
                    writer.writerow(struct)


    def makepatch(self, rom, modfolder):
        """ Generate a ROM patch."""
        raise NotImplementedError("not written yet.")


class ArrayDef(OrderedDict):
    requiredproperties = "name", "type", "offset", "length", "stride", "comment"

    def __init__(self, od, structtypes={}):
        super().__init__(od)
        validate_spec(self)
        if self['type'] in structtypes:
            self.struct = structtypes[self['type']]
        else:
            self.struct = StructDef.from_primitive_array(self)
        self['offset'] = tobits(self['offset'])
        self['stride'] = tobits(self['stride'])

    def read(self, stream):
        for i in range(int(self['length'])):
            pos = i*self['stride'] + self['offset']
            yield self.struct.read(stream, pos)


class StructDef(OrderedDict):
    """ Specifies the format of a structure type in a ROM. """

    def __init__(self, fields):
        """ Create a StructDef from a list of ordered dicts."""
        super().__init__()
        fields = list(fields)
        self.pointers = [f for f in fields if f['id'][0] == "*"]
        for field in [f for f in fields if f['id'][0] not in "*_"]:
            field['size'] = tobits(field['size'])
            self[field['id']] = field

    @classmethod
    def from_file(cls, filename):
        with open(filename, newline="") as f:
            fields = list(OrderedDictReader(f))
        return StructDef(fields)

    @classmethod
    def from_primitive_array(cls, arrayspec):
        spec = OrderedDict()
        spec['id'] = "val"
        spec['label'] = arrayspec['name']
        spec['size'] = arrayspec['stride']
        spec['type'] = arrayspec['type']
        spec['display'] = arrayspec['display']
        spec['tags'] = arrayspec['tags']
        spec['comment'] = arrayspec['comment']
        spec['order'] = ""

        return StructDef([spec])

    def read(self, stream, offset = 0, rommap = None):
        """ Read an arbitrary structure from a bitstream.

        The offset is the location in the stream where the structure begins. If
        the stream was created from a file, then it's the offset in the file.
        """
        stream.pos = offset
        od = OrderedDict()
        ordering = {}
        for fid, field in self.items():
            value = stream.read("{}:{}".format(field['type'], field['size']))
            od[fid] = display[field['display']](value, field)
            ordering[fid] = field['order']

        od = OrderedDict(sorted(od.items(), key=lambda item: ordering[item[0]]))
        od.struct_def = self
        return od

    def dereference_pointers(self, item, rommap, rom):
        ''' Dereference pointers in a struct. '''
        for ptr in self.pointers:
            pid = ptr['id']
            ptype = ptr['ptype']
            ramaddr = int(item[ptr['label']], 0)
            romaddr = ptr_ram_to_rom[ptype](ramaddr)
            if ptr['type'] == "strz":
                tbl = rommap.texttables[ptr['display']]
                s = tbl.readstr(rom, romaddr)
                item[pid] = s
            if pid == "*name":
                item.move_to_end(pid, False)
        return item


def hexify(i, length = None):
    """ Converts an integer to a hex string.

    If bitlength is provided, the string will be padded enough to represent
    at least bitlength bits, even if those bits are all zero.
    """
    if length is None:
        return hex(i)

    numbytes = length // 8
    if length % 8 != 0: # Check for partial bytes
        numbytes += 1
    digits = numbytes * 2 # Two hex digits per byte
    fmtstr = "0x{{:0{}X}}".format(digits)
    return fmtstr.format(i)

ptr_ram_to_rom = {
    "hirom": lambda address: address - 0xC00000
}

display = {
    "hexify": lambda value, field: hexify(value, field['size']),
    "hex": lambda value, field: hexify(value, field['size']),
    "": lambda value, field: value
}
