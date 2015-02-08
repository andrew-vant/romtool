import logging
import os
import csv
from bitstring import ConstBitStream
from collections import OrderedDict
from csv import DictWriter

from .util import tobits, validate_spec, OrderedDictReader


class RomMap(object):
    def __init__(self, root):
        # Find all the csv files in the structs directory and load them into
        # a dictionary keyed by their base name.
        structfiles = [f for f
                       in os.listdir("{}/structs".format(root))
                       if f.endswith(".csv")]

        self.structs = {}
        for sf in structfiles:
            typename = os.path.splitext(sf)[0]
            struct = RomStruct.from_file("{}/structs/{}".format(root, sf))
            self.structs[typename] = struct

        # Now load the array definitions.
        with open("{}/arrays.csv".format(root)) as f:
            self.arrays = [RomArray(od, self.structs)
                           for od in OrderedDictReader(f)]

    def dump(self, rom, folder, allow_overwrite=False):
        """ Look at a ROM and export all known data to folder."""
        stream = ConstBitStream(rom)
        mode = "w" if allow_overwrite else "x"
        for array in self.arrays:
            fname = "{}/{}.csv".format(folder, array['name'])
            data = array.read(stream)
            with open(fname, mode, newline='') as f:
                # Note that we need to use QUOTE_ALL or spreadsheet programs
                # will do bad things to bitfields that start with zero.
                writer = DictWriter(f, array.struct.keys(), quoting=csv.QUOTE_ALL)
                labels = {field['id']: field['label']
                          for field in array.struct.values()}
                writer.writerow(labels)
                for struct in data:
                    writer.writerow(struct)


    def makepatch(self, rom, modfolder):
        """ Generate a ROM patch."""
        raise NotImplementedError("not written yet.")


class RomArray(OrderedDict):
    requiredproperties = "name", "type", "offset", "length", "stride", "comment"

    def __init__(self, od, structtypes={}):
        super().__init__(od)
        validate_spec(self)
        if self['type'] in structtypes:
            self.struct = structtypes[self['type']]
        else:
            self.struct = RomStruct.from_primitive_array(self)
        self['offset'] = tobits(self['offset'])
        self['stride'] = tobits(self['stride'])

    def read(self, stream):
        for i in range(int(self['length'])):
            pos = i*self['stride'] + self['offset']
            yield self.struct.read(stream, pos)


class RomStruct(OrderedDict):
    """ Specifies the format of a structure type in a ROM. """

    def __init__(self, fields):
        """ Create a RomStruct from a list of struct fields."""
        super().__init__()
        for field in fields:
            self[field['id']] = field

    @classmethod
    def from_file(cls, filename):
        with open(filename, newline="") as f:
            fields = list(OrderedDictReader(f))
        return RomStruct([RomStructField(field) for field in fields])

    @classmethod
    def from_primitive_array(cls, arrayspec):
        d = { "id":     "val",
              "label":  arrayspec['name'],
              "size":   arrayspec['stride'],
              "type":   arrayspec['type'],
              "tags":   arrayspec['tags'],
              "comment":arrayspec['comment'],
              "order": ""}
        rsfspec = OrderedDict()
        for prop in RomStructField.requiredproperties:
            rsfspec[prop] = d[prop]
        return RomStruct([RomStructField(rsfspec)])

    def read(self, stream, offset = 0):
        """ Read an arbitrary structure from a bitstream.

        The offset is the location in the stream where the structure begins. If
        the stream was created from a file, then it's the offset in the file.
        """
        stream.pos = offset
        od = OrderedDict()
        ordering = {}
        for fid, field in self.items():
            value = stream.read("{}:{}".format(field['type'], field['size']))
            od[fid] = value
            ordering[fid] = field['order']
            if "hex" in field.tags or "pointer" in field.tags:
                od[fid] = hexify(value, field['size'])

        od = OrderedDict(sorted(od.items(), key=lambda item: ordering[item[0]]))
        return od


class RomStructField(OrderedDict):
    """ Specifies the format of a single field of a structure. """
    requiredproperties = "id", "label", "size", "type", "tags", "order", "comment"

    def __init__(self, od):
        super().__init__(od)
        self.tags = {s for s in od['tags'].split("|") if s}
        self['size'] = tobits(self['size'])
        validate_spec(self)

def hexify(i, bitlength = None):
    """ Converts an integer to a hex string.

    If bitlength is provided, the string will be padded enough to represent
    at least bitlength bits, even if those bits are all zero.
    """
    if bitlength is None:
        return hex(i)

    numbytes = bitlength // 8
    if bitlength % 8 != 0: # Check for partial bytes
        numbytes += 1
    digits = numbytes * 2 # Two hex digits per byte
    fmtstr = "0x{{:0{}X}}".format(digits)
    return fmtstr.format(i)
