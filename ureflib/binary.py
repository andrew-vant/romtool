import logging, os, csv, sys, itertools, yaml
from bitstring import ConstBitStream
from collections import OrderedDict
from csv import DictWriter
from pprint import pprint

from . import text
from .util import tobits, validate_spec, OrderedDictReader, merge_dicts
from .exceptions import RomMapError

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
        ttfiles = [f for f
                   in os.listdir("{}/texttables".format(root))
                   if f.endswith(".tbl")]
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

        # Black magic begins here. We want to go through each set of arrays
        # and merge the corresponding structures from each, then output the
        # result. We want the output fields to remain well-ordered, and we
        # want the name field at the front if it is there.

        for entity, arrays in self.arraysets.items():

            # Read in each array, then dereference any pointers in their
            # respective items, then merge them so we get a single dict
            # for each object.
            data = [array.read(stream) for array in arrays]
            data = [[item.struct_def.dereference_pointers(item, self, rom)
                     for item in array] for array in data]
            try:
                data = [merge_dicts(parts) for parts in zip(*data)]
            except ValueError as e:
                # FIXME: These checks should really be done in init.
                msg = "The arrays in set {} have overlapping keys: {}"
                raise RomMapError(msg.format(entity, e.overlap))

            # Now work out what field IDs need to be included in the output.
            # This is the union of the IDs available in each array.
            # We also need to know what human-readable labels to print on
            # the first row.

            headermap = OrderedDict()
            for array in arrays:
                s = array.struct
                allfields = itertools.chain(s.values(), s.pointers)
                od = OrderedDict((field['id'], field['label'])
                                 for field in allfields)
                headermap.update(od)

            # If the object has a name, move it to the front of the output.
            name = next((k for k, v in headermap.items() if v == "Name"), None)
            if name is not None:
                headermap.move_to_end(name, False)

            # Now dump.
            fname = "{}/{}.csv".format(folder, entity)
            with open(fname, mode, newline='') as f:
                writer = DictWriter(f, headermap.keys(), quoting=csv.QUOTE_ALL)
                writer.writerow(headermap)
                for item in data:
                    writer.writerow(item)

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
        if not self['set']:
            self['set'] = self['name']
        if not self['label']:
            self['label'] = self['name']

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
        self.pointers = [f for f in fields if self.ispointer(f)]
        self.name = next((f for f in fields if self.isname(f)), None)

        normal_fields = [f for f in fields if self.isnormal(f)]
        for field in normal_fields:
            field['size'] = tobits(field['size'])
            self[field['id']] = field

    @classmethod
    def from_file(cls, filename):
        with open(filename, newline="") as f:
            fields = list(OrderedDictReader(f))
        return StructDef(fields)

    @classmethod
    def from_primitive_array(cls, arrayspec):
        # FIXME: This is actually working from a primitive array initialization
        # dict, not a real array.
        spec = OrderedDict()
        spec['id'] = arrayspec['name']
        spec['label'] = arrayspec['label']
        spec['size'] = arrayspec['stride']
        spec['type'] = arrayspec['type']
        spec['display'] = arrayspec['display']
        spec['tags'] = arrayspec['tags']
        spec['comment'] = arrayspec['comment']
        spec['order'] = ""

        return StructDef([spec])

    @classmethod
    def isnormal(cls, field):
        return field['id'].isalnum()

    @classmethod
    def ispointer(cls, field):
        return field['id'][0] == "*"

    @classmethod
    def isname(cls, field):
        return field['label'] == "Name"

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
            # Take off the asterisk to get the id of the pointer field.
            # Get the value of that pointer, intify it, then do whatever's
            # required by ptype. Pay attention to the difference between the
            # id of the pointer (pid) and the id of the dereferenced field
            # (fid) here. This could probably use clarity work.
            fid = ptr['id']
            pid = ptr['id'][1:]
            ptype = ptr['ptype']
            ramaddr = int(item[pid], 0)
            romaddr = ptr_ram_to_rom[ptype](ramaddr)
            if ptr['type'] == "strz":
                tbl = rommap.texttables[ptr['display']]
                s = tbl.readstr(rom, romaddr)
                item[fid] = s
            if self.isname(ptr):
                item.move_to_end(fid, False)
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
