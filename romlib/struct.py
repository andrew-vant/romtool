import logging

from pprint import pprint
from itertools import chain
from collections import OrderedDict, namedtuple
from bitstring import ConstBitStream, Bits, BitStream

from .util import tobits, OrderedDictReader, merge_dicts, flatten, hexify


class Struct(object):
    def __init__(self, definition):
        """ Create an empty structure of a given type."""
        self.definition = definition
        self.data = None
        self.calculated = None

#        default = [None for i in definition._datant._fields]
#        self.data = definition._datant(*default)
#        default = [None for i in definition._pointersnt._fields]
#        self.calculated = definition._pointersnt(*default)

    @classmethod
    def from_dict(cls, definition, d):
        """ Initialize a structure from a dictionary. """
        return cls.from_mergedict([definition], d)[0]

    @classmethod
    def from_mergedict(cls, definitions, md):
        """ Decompose a dictionary into multiple structures.

        This is useful when loading a set of structures from an edited csv
        using csv.DictReader.
        """
        # Currently totally broken.

        out = []
        for sdef in definitions:
            # Build a dict mapping labels to their field id. Useful since our
            # input will likely be labeled rather than id'd.
            ofs = sdef._output_fields()
            ids = [i[0] for i in ofs]
            unlabel = {i[1]: i[0] for i in ofs}

            # Build another dict containing only the data we want to insert.
            # Handle both id and label mappings.
            d = {k: md[k] for k in md
                 if k in ids}
            d.update({unlabel[k]: md[k] for k in md
                      if k in unlabel})

            s = Struct(sdef)
            s.data = sdef._datant(**d)
            out.append(s)
        return out

    def read(self, data, offset=None):
        """ Read data into a structure from a bitstream.

        data is any kind of object that can be sanely converted to a
        BitStream. Most commonly this will be a file opened in binary mode,
        a bytes object, or another bitstream.

        The offset is the location in the stream where the structure begins. If
        the stream was created from a file, then it's the offset in the file.
        If offset is None, the current stream position will be used.

        Returns an object with attributes for each field of the structure.
        """
        stream = ConstBitStream(data)
        if offset is not None:
            stream.pos = offset
        fmt = ["{}:{}".format(f['type'], f['size'])
               for f in self.definition.fields]
        self.data = self.definition._datant(*stream.readlist(fmt))

    def to_od(self):
        """ Create an ordered dict from the struct's properties.

        The output will be human readable and suitable for saving to a csv
        file. The name will come first, then regular properties in definition-
        order, then computed properties in definition-order, then pointer
        properties in definition-order.
        """
        out = OrderedDict()
        for fid, label in self.definition._output_fields():
            field = self.definition._get_field_by_id(fid)
            value = getattr(self.data, fid,
                            getattr(self.calculated, fid.lstrip('*'), ""))
            out[label] = display.get(field["display"])(value, field)
        return out

    @classmethod
    def to_merged_od(cls, structs):
        """ Create an ordered dict from the properties of a list of structs.

        The output will be human readable and suitable for saving to a csv
        file. The name will come first. Remaining properties will be sorted
        first as data/computed/pointer properties, then in order of the
        original list.
        """
        # Find out what order to print fields in.
        sdefs = [s.definition for s in structs]
        outputfields = StructDef._output_fields_merged(sdefs)
        out = OrderedDict()
        for fid, label in outputfields:
            value = None
            for s in structs:
                if fid in s.data.__dict__:
                    value = getattr(s.data, fid)
                elif s.calculated is not None and fid in s.calculated.__dict__:
                    value = getattr(s.calculated, fid)
            # assert value is not None
            out[label] = value
        return out

    def to_bytes(self):
        """ Generate a bytes object from the struct's properties.

        The output will be suitable for writing back to the ROM or generating
        a patch. Currently it outputs normal data fields only.
        """
        bitinit = []
        for field in self.definition.fields:
            tp = field['type']
            size = field['size']
            value = getattr(self.data, field['id'])
            bitinit.append("{}:{}={}".format(tp, size, value))
        return Bits(", ".join(bitinit)).bytes

    def calculate(self, f):
        """ Dereference pointers and populate calculated properties. """
        for ptr in definition.pointers:
            # Take off the asterisk to get the id of the pointer field. Convert
            # that pointer to a ROM address, then read from that address.
            fid = ptr['id'][1:]
            archaddr = getattr(self.data, fid)
            romaddr = Address(archaddr, ptr['ptype']).rom
            if ptr['type'] == "strz":
                ttable = self.tbl[ptr['display']]
                s = ttable.readstring(f, romaddr)
                setattr(self.calculated, fid, s)


class StructDef(object):
    def __init__(self, name, fields, texttables=None):
        """ Create a structure definition.

        name: The class name of this type of structure.
        fields: A list of dictionaries defining this structure's fields.
        texttables: A dictionary of text tables for decoding strings.
        """
        self.tbl = texttables
        fields = list(fields)  # In case we were passed a generator
        self.pointers = [f for f in fields if self.ispointer(f)]
        self.fields = [f for f in fields if self.isdata(f)]
        for f in self.fields:
            f['size'] = tobits(f['size'])

        fids = [f['id'] for f in self.fields]
        pids = [f['id'] for f in self.pointers]
        self._datant = namedtuple(name + "data", ",".join(fids))
        self._pointersnt = namedtuple(name + "ptr", ",".join(pids))

    @classmethod
    def from_file(cls, name, f):
        return StructDef(name, OrderedDictReader(f))

    @classmethod
    def from_primitive_array(cls, arrayspec):
        spec = OrderedDict()
        spec['id'] = arrayspec['name']
        spec['label'] = arrayspec['label']
        spec['size'] = arrayspec['stride']
        spec['type'] = arrayspec['type']
        spec['display'] = arrayspec['display']
        spec['tags'] = arrayspec['tags']
        spec['comment'] = arrayspec['comment']
        spec['order'] = ""
        return StructDef(arrayspec['name'], [spec])

    def _get_field_by_id(self, fid):
        out = None
        try:
            out = next(f for f in self.fields if f['id'] == fid)
        except StopIteration:
            out = next(f for f in self.pointers if f['id'] == fid)
        finally:
            if out is None:
                raise KeyError("No field named {}.".format(fid))
            return out

    def _output_fields(self):
        """ Get the ordering for data fields in csv output."""
        allfields = self.fields + self.pointers
        try:
            name = [next(f for f in allfields if self.isname(f))]
        except StopIteration:
            name = []
        normal = [f for f in self.fields if not self.isname(f)]
        pointers = [f for f in self.pointers if not self.isname(f)]
        return [(f['id'], f['label']) for f in name+normal+pointers]

    @classmethod
    def _output_fields_merged(cls, sdefs):
        """ Order fields from multiple structdefs into a complete set."""
        # ordering should be: name first, then data (in order), then pointers
        # (in order).
        # Probably simpler to order them all and then move the name to
        # the front of the list.

        allfields = [s.fields + s.pointers for s in sdefs]
        allfields = chain.from_iterable(allfields)
        out = []
        name = None
        try:
            name = next(f for f in allfields if cls.isname(f))
            out.append(name['id'], name['label'])
        except StopIteration:
            pass
        for sdef in sdefs:
            out += [(f['id'], f['label'])
                    for f in sdef.fields
                    if f != name]
        for sdef in sdefs:
            out += [(f['id'], f['label'])
                    for f in sdef.pointers
                    if f != name]
        return out

    @classmethod
    def isdata(cls, field):
        return field['id'].isalnum()

    @classmethod
    def ispointer(cls, field):
        return field['id'][0] == "*"

    @classmethod
    def isname(cls, field):
        return field['label'] == "Name"

    @property
    def bytes(self):
        """ The size of this structure in bytes."""
        return sum(f['size'] / 8 for f in self.fields)

    @property
    def bits(self):
        """ The size of this structure in bits."""
        return sum(f['size'] for f in self.fields)

    def changeset(self, item, offset):
        """ Get all changes made by item """
        initializers = []
        for fid, value in item.items():
            size = self[fid]['size']
            ftype = self[fid]['type']
            # bitstring can't implicitly convert ints expressed as hex
            # strings, so let's do it ourselves.
            if "int" in ftype:
                value = int(value, 0)
            initializers.append("{}:{}={}".format(ftype, size, value))
        itemdata = Bits(", ".join(initializers))
        return {offset+i: b for i, b in enumerate(itemdata.bytes)}

display = {
    "hexify": lambda value, field: hexify(value, field['size']),
    "hex": lambda value, field: hexify(value, field['size']),
    "": lambda value, field: value
}
