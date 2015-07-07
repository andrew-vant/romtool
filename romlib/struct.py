import itertools
import collections
import bitstring

from bitstring import Bits, ConstBitStream
from collections import namedtuple, OrderedDict
from pprint import pprint

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
            self.dereference(f)


    def _init_from_dict(self, d):
        lm = OrderedDict(self.sdef.unlabelmap)
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
            romaddr = util.Address(archaddr, ptr.subtype).rom
            if attr.type == "strz":
                ttable = self.sdef.tbl[attr.display]
                s = ttable.readstr(f, romaddr)
                self.data[attr.id] = s

    def to_bytes(self):
        """ Generate a bytes object from the struct's properties.

        The output will be suitable for writing back to the ROM or generating
        a patch. Currently it outputs normal data fields only.
        """
        bitinit = []
        for field in self.sdef.datafields:
            tp = field.type
            size = field.size
            value = self.data[field.id]
            bitinit.append("{}:{}={}".format(tp, size, value))
        return Bits(", ".join(bitinit)).bytes


    def changeset(self, offset):
        """ Get an offset-to-byte-value dict.

        offset: where the struct should start when written back to a file.
                This offset should be given in bytes.
        """
        # FIXME: This should include changes for pointer values if present.

        initializers = []
        for df in self.sdef.datafields:
            value = self.data[df.id]
            # bitstring can't implicitly convert ints expressed as hex
            # strings, so let's do it ourselves.
            if "int" in df.type:
                try:
                    value = int(value, 0) # For strings
                except TypeError:
                    value = int(value) # for numbers

            initializers.append("{}:{}={}".format(df.type, df.size, value))
        data = Bits(", ".join(initializers))
        return {offset+i: b for i, b in enumerate(data.bytes)}


    @classmethod
    def to_mergedict(cls, structs):
        # If we were given a single struct, make it a one-element list
        if not hasattr(structs, "__iter__"):
            structs = [structs]
        return util.merge_dicts([s.data for s in structs])

    @classmethod
    def splice(cls, dataset):
        """ Merge a 2D list of structures.

        dataset: a list of lists of structs. The lists should be of equal
                 length. The corresponding elements of each list will be
                 merged and returned as an OrderedDict, with the OD keys
                 sorted by StructDef.attribute_order.
        """
        # This feels like black magic and I've no idea if it's in the "correct"
        # place in the code, but it has to go somewhere.

        # We might get passed generators in either list dimension, which is
        # an issue because I need to iterate over the dataset twice. This
        # should deal with it until I can figure out how to not need to
        # reuse anything.
        dataset = list(list(a) for a in dataset)

        # Get a list of merged dictionaries.
        elements = [Struct.to_mergedict(element)
                    for element in zip(*dataset)]

        # Get the union of the keys in all elements and find out what
        # order they should be in.
        chain = itertools.chain.from_iterable
        keys = set(chain(s.keys() for s in elements))
        sdefs = [s.sdef for s in next(zip(*dataset))]
        keys = StructDef.attribute_order(keys, sdefs)

        # Now re-order the keys in our returned list. There has to be
        # a better way to do this. :-(

        spliced = [OrderedDict((k, e.get(k, "")) for k in keys)
                   for e in elements]
        return spliced

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
        self.tbl = OrderedDict((tt.name, tt) for tt in texttables)
        self.attributes = OrderedDict()
        for d in fields:
            a = self._dict_to_attr(d)
            self.attributes[a.id] = a
        self.label = {a.id: a.label for a in self.attributes.values()}
        self.unlabel = {a.label: a.id for a in self.attributes.values()}

    @property
    def allfields(self):
        return self.attributes.values()

    @property
    def datafields(self):
        return (a for a in self.attributes.values()
                if a.id.isalnum())

    @property
    def pointers(self):
        return (a for a in self.attributes.values()
                if a.info == "pointer")

    @property
    def calcfields(self):
        return (a for a in self.attributes.values()
                if a.id.startswith("*"))

    @property
    def pointermap(self):
        """ Get pairs of attributes mapping pointers to their attributes."""
        return ((self.attributes[f.id[1:]], f)
                 for f in self.calcfields)

    @property
    def labelmap(self):
        """ Get a map of ids to labels."""
        return ((a.id, a.label) for a in self.attributes.values())

    @property
    def unlabelmap(self):
        """ Get a map of labels to ids."""
        return ((a.label, a.id) for a in self.attributes.values())

    @property
    def namefield(self):
        try:
            return next(a for a in self.attributes.values()
                        if a.info.lower() == "name")
        except StopIteration:
            err = "No name field in {} spec.".format(self.name)
            raise AttributeError(err)

    @classmethod
    def from_file(cls, name, f, texttables=[]):
        return StructDef(name, util.OrderedDictReader(f), texttables)

    @classmethod
    def from_primitive_array(cls, arrayspec):
        # Should this be implemented by the array class constructing a
        # dict for the regular init method?
        pass

    @classmethod
    def attribute_order(cls, keys, sdefs):
        """ Determine column order for output.

        This takes a list of keys from a mergedict and a structdef or list of
        structdefs you're outputting. It sorts the keys first by the
        corresponding attribute's explicit order, then by the type of data
        (name, normal, calculated, pointers), then by the order of the
        structure definitions given, then by the order within those structures.

        Returns a reordered list of keys."""

        keys = list(keys)  # Just in case we were passed an iterator.
        chain = itertools.chain.from_iterable  # Convenience alias.

        # Map all keys to their default position
        all_attribute_ids = chain(sd.attributes.keys() for sd in sdefs)
        posmap = {a: o for o, a in enumerate(all_attribute_ids)}

        # Map all keys to their corresponding attributes
        attrmap = util.merge_dicts([sd.attributes for sd in sdefs])

        # Map all keys to their explicit attribute order
        order = {k: attrmap[k].order for k in keys}

        # Find out which fields are name, data, calculated, pointers
        # and put them in order. Some fields may show up in more than
        # one list (e.g. a namefield that is also a calcfield) so
        # these are assigned in reverse order of priority. Last wins.
        typeorder = {}
        for sd in sdefs:
            for a in sd.datafields:
                typeorder[a.id] = 1
            for a in sd.calcfields:
                typeorder[a.id] = 2
            for a in sd.pointers:
                typeorder[a.id] = 3
            try:
                typeorder[sd.namefield.id] = 0
            except AttributeError:
                pass # Not every struct has a namefield.

        # Build a list of tuples with all the information we want to sort on.
        keytuples = [(order[k], typeorder[k], posmap[k], k)
                     for k in keys]

        # Sort the tuples and return the reordered keys
        return [kt[-1] for kt in sorted(keytuples)]


    @classmethod
    def _dict_to_attr(cls, d):
        """ Define a structure attribute from a dictionary.

        This is intended to take input from a csv.DictReader or similar and
        do any necessary string-to-whatever conversions, sanity checks, etc.
        """
        d = d.copy()
        d['size'] = util.tobits(d['size'], 0)
        try:
            d['order'] = int(d['order'])
        except ValueError:
            d['order'] = 0
        return StructDef.Attribute(**d)
