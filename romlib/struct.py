import bitstring

from bitstring import ConstBitStream
from collections import namedtuple, OrderedDict

from . import util

class Struct(object):
    def __init__(self, definition, auto=None,
                 fileobj=None, bitstr=None, bytesobj=None, dictionary=None,
                 offset=0, dereference=True):
        """ Create a structure with a given definition from input data.

        definition: a StructDef object.

        One and only one of the following initialization objects should be
        set:

        auto: Automatically determine input type.
        fobj: Initialize from a file object.
        bitstr: Initialize from a bitstring object.
        bytesobj: Initialize from a bytes object.
        dictionary: Initialize from a dictionary. Dictionary keys
                    may be either ids or labels.
        """
        self.sdef = definition
        self.data = OrderedDict()

        # Check that no more than one initializer was provided
        initializers = [auto, fileobj, bitstr, bytesobj, dictionary]
        numinit = sum(1 for i in initializers if i is not None)
        if numinit > 1:
            raise TypeError("Multiple initializers provided, expected 1.")

        # Several types are treated the same, get the one that was
        # provided, if any.
        fileesque = next((f for f in [fileobj, bitstr, bytesobj]
                         if f is not None), None)

        # Figure out what to do with auto if it was provided.
        if isinstance(auto, dict):
            dictionary = auto
        elif isinstance(auto, object):
            fileesque = auto

        # Initialize. Note that if no initializers were given, this
        # does nothing, and we end up with an empty structure.
        if dictionary:
            self._init_from_dict(dictionary)
        if fileesque:
            self._init_from_fileesque(fileesque, offset, dereference)


    def _init_from_fileesque(self, f, offset, dereference):
        # This should work for bitstreams, files, or bytes, because
        # of this initial conversion.
        bs = ConstBitStream(f)
        self.read(bs, offset)
        if dereference:
            self.dereference(bs)


    def _init_from_dict(self, d):
        lm = OrderedDict(self.sdef.labelmap)
        for k, v in d.items():
            # Convert labels to ids as needed.
            if k in lm:
                k = lm[k]
            if k in self.sdef.attributes:
                self.data[k] = v

    def read(self, f, offset=None):
        stream = ConstBitStream(f)
        if offset is not None:
            stream.pos = offset
        for a in self.sdef.datafields:
            fmt = "{}:{}".format(a.type, a.size)
            self.data[a.id] = stream.read(fmt)

    def dereference(self, f):
        """ Dereference pointers and load their values."""

        # Loop over calcmap, convert the pointer's arch address to a rom
        # address, then read in the value from that address.
        for ptr, attr in self.sdef.pointermap:
            archaddr = self.data[ptr.id]
            romaddr = Address(archaddr, ptr.subtype).rom
            if attr.type == "strz":
                ttable = self.tbl[attr.display]
                s = ttable.readstring(f, romaddr)
                self.data[attr.id] = s


class StructDef(object):
    Attribute = namedtuple("Attribute",
                           "id label size type subtype "
                           "display order info comment")

    def __init__(self, name, fields, texttables=[]):
        """ Create a structure definition.

        name: The class name of this type of structure.
        fields: A list of dictionaries defining this structure's fields.
        texttables: A dictionary of text tables for decoding strings.
        """
        self.name = name
        self.tbl = texttables
        self.attributes = OrderedDict()
        for d in fields:
            a = self._dict_to_attr(d)
            self.attributes[a.id] = a

    @property
    def allfields(self):
        return self.attributes.values()

    @property
    def datafields(self):
        return (a for a in self.attributes.values()
                if a.id.isalnum())

    @property
    def calcfields(self):
        return (a for a in self.attributes.values()
                if a.id.startswith("_"))

    @property
    def pointermap(self):
        """ Get pairs of attributes mapping pointers to their attributes."""
        return ((self.attributes[f.id[1:]], f)
                 for f in self.calcfields)

    @property
    def labelmap(self):
        """ Get a map of labels to ids."""
        return ((a.label, a.id) for a in self.attributes.values())

    @property
    def namefield(self):
        return next(a for a in self.attributes.values()
                    if a.info.lower() == "name")

    @classmethod
    def from_file(cls, name, f):
        return StructDef(name, util.OrderedDictReader(f))

    @classmethod
    def from_primitive_array(cls, arrayspec):
        # Should this be implemented by the array class constructing a
        # dict for the regular init method?
        pass

    @classmethod
    def _dict_to_attr(cls, d):
        """ Define a structure attribute from a dictionary.

        This is intended to take input from a csv.DictReader or similar and
        do any necessary string-to-whatever conversions, sanity checks, etc.
        """
        d = d.copy()
        d['size'] = util.tobits(d['size'])
        try:
            d['order'] = int(d['order'])
        except ValueError:
            d['order'] = 0
        return StructDef.Attribute(**d)
