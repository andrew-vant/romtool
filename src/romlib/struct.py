"""This module contains classes for manipulating binary structures in ROMs."""

# FIXME: What is the canonical internal representation for a bitfield? It
# probably should not be a string.

import types
import itertools
import collections
import pathlib
import inspect
import codecs
from importlib.machinery import SourceFileLoader

import bitstring
from bitstring import ConstBitStream, BitStream, Bits

from . import util

class MetaStruct(type):
    """ Metaclass for structure objects.

    The main point of this is to ensure that the class attribute "fields" and
    its related, derived attributes are properly set when Structure is
    inherited.
    """
    def __new__(cls, name, bases, dct, *, fields):
        # See: http://martyalchin.com/2011/jan/20/class-level-keyword-arguments/
        return super().__new__(cls, name, bases, dct)

    def __init__(cls, name, bases, dct, *, fields):
        super().__init__(name, bases, dct)
        cls.fields = fields.copy()
        # Insert field-to-struct callbacks here? I'm still doing something
        # wrong.
        cls._links = [f for f in fields if f.pointer]
        cls._nonlinks = [f for f in fields if not f.pointer]
        cls.fieldmap = {}
        for field in fields:
            if field.id in dir(cls):
                msg = "Illegal field id '{}' in struct '{}'."
                raise ValueError(msg, field.id, name)
            cls.fieldmap[field.id] = field
            cls.fieldmap[field.label] = field

        # FIXME: Check for overlapping label/ids? Not sure if this should be
        # allowed.


class Structure(object, metaclass=MetaStruct, fields=[]):
    def __init__(self, auto=None):
        self.data = types.SimpleNamespace()
        if isinstance(auto, dict):
            self.load(auto)
        else:
            self.read(auto)

    @classmethod
    def _realkey(cls, key):
        """ Dereference labels to ids if needed."""
        return cls.fieldmap[key].id

    def __setitem__(self, key, value):
        """ Set an attribute using dictionary syntax.

        Attributes can be looked by by label as well as ID.
        """
        setattr(self.data, self._realkey(key), value)

    def __getitem__(self, key):
        """ Get an attribute using dictionary syntax.

        Attributes can be looked by by label as well as ID.
        """
        return getattr(self.data, self._realkey(key))

    def __delitem__(self, key):
        """ Unset a field value.

        For variable-length structures or other weird edge cases, this
        indicates that a given field is unused or omitted and should be skipped
        or ignored when generating patches.

        This doesn't actually delete the underlying attribute, just sets it to
        None.
        """
        self[key] = None

    def __getattr__(self, name):
        if name in self.ids():
            return getattr(self.data, name)
        elif hasattr(super(), "__getattr__"):
            return super().__getattr__(name)
        else:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self.ids():
            setattr(self.data, name, value)
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        """ Remove a field by id.

        This sets the underlying data to None, which is interpreted as "this
        field isn't present in the structure in ROM. Use for 'optional' fields.
        """
        if name in self.ids():
            setattr(self.data, name, None)
        else:
            super().__delattr__(name)

    def __contains__(self, key):
        try:
            key = self._realkey(key)
        except KeyError: # FIXME: Should probably use custom exception.
            return False
        return self[key] is not None

    def keys(self, *, labels=False):
        return self.labels() if labels else self.ids()

    def ids(self):
        return (field.id for field in self.fields)

    def labels(self):
        return (field.label for field in self.fields)

    def values(self):
        return (getattr(self.data, field.id)
                for field in self.fields)

    def items(self, *, labels=False):
        return zip(self.keys(labels), self.values())

    def fields(self):
        return (field for field in self.fields)

    def offset(self, fieldname):
        """ Get the offset of a field from the start of the structure."""
        raise NotImplementedError

    # Reading and loading routines begin here. If you have a really weird
    # structure, these are the functions you want to override to deal with it.

    def load(self, dictionary):
        """ Initialize a structure from a dictionary of strings.

        This works whether the dictionary is keyed by field id, field label, or
        a mix of both. It's intended to be used for input from a
        csv.DictReader.
        """
        for key, value in dictionary.items():
            if key not in self.fieldmap:
                continue # Probably the input is merged with another struct.
            field = self.fieldmap[key]
            self[key] = field.load(value)
        self.postload()

    def postload(self):
        """ Loading hook for weird structures, e.g. containing unions.

        If a given structure contains unions, they are always loaded as
        strings. This function should replace them with whatever type is
        appropriate.

        Unions should never be strings and it is an error to leave them that
        way.
        """
        pass

    def read(self, source, bit_offset=None):
        """ Read in a new structure"""
        bs = util.bsify(source)
        if bit_offset is not None:
            bs.pos = bit_offset

        for field in self._nonlinks:
            self[field.id] = field.read(bs)
        end = bs.pos  # Save this to reset it after reading links.

        for field in self._links:
            desc = "{} field".format(type(self).__name__)
            with util.loading_context(desc, field.id):
                pointer = self.fieldmap[field.pointer]
                bs.pos = (self[pointer.id] + pointer.mod) * 8
                self[field.id] = field.read(bs)

        bs.pos = end  # Should be one bit past the fixed structure.
        self.postread(source)

        # Make sure any hook-requiring fields were actually processed.
        unset = [field.id for field in self.fields if field.id not in self]
        if len(unset) > 0:
            msg = "Fields '{}' in struct '{}' not processed properly."
            raise Exception(msg, unset, type(self).__name__)


    def postread(self, source):
        """ Reading hook for weird structures, e.g. with optional fields.

        `source` will always be a bitstring, and its position will always be
        set to the first bit past the "fixed" part of the structure.

        If a given structure contains unions, they are initially left as
        bitstrings; this function should interpret them, and not doing so will
        raise an exception.

        If a given structure contains optional fields, they are initially
        unread. This function should read them. If they are not present, they
        should be set to None. Not doing one or the other will raise an
        exception.
        """
        pass

    def bytemap(self, offset):
        """ Get an offset-to-byte-value dict for use by Patch.

        Offset indicates the start point of the structure.
        """
        changes = {}

        # Deal with regular data fields first. These are expected to all be
        # bitstring-supported types because I've yet to see a ROM that wasn't
        # that way. For now the main data of the structure must be of
        # whole-byte size.
        bs = BitStream()
        for field in self._nonlinks:
            value = self[field.id]
            bs.append(field.bits(value))
        for i, byte in enumerate(bs.bytes):
            changes[offset+i] = byte

        # Deal with pointers. For now pointers require whole-byte values.
        # Note that we no longer care about the struct's start point so we can
        # reuse offset.
        for field in self._links:
            value = self[field.id]
            pointer = self.fieldmap[field.pointer]
            offset = self[field.pointer] + pointer.mod
            for i, byte in enumerate(field.bytes(value)):
                changes[offset+i] = byte

        # Apply hooks.
        changes.update(self.postbytemap(offset))
        return changes

    def postbytemap(self, offset):
        """ Bytemap hook for weird structures, e.g. with unions.

        Offset indicates the start point of the structure in ROM.

        This function must return a dictionary of offsets and byte values for
        union and optional fields. It need not include data for fixed fields or
        pointers; if it does they will override anything included by the
        default behavior.
        """
        return {}

    def dump(self, use_labels=True):
        """ Produce a dictionary of strings from a structure.

        The result is suitable for writing out to .tsv or similar.
        """
        # FIXME: What should this do for unions? str(whatever) *may* work, in
        # which case a hook isn't needed, but I'm not sure.
        out = {}
        for field in self.fields:
            key = field.label if use_labels else field.id
            value = field.dump(self[key])
            out[key] = value
        return out

def conflict_check(structure_classes):
    """ Verify that all ids and labels in a list of structure classes are unique. """
    for cls1, cls2 in itertools.permutations(structure_classes, r=2):
        for element in ("id", "label"):
            list1 = (getattr(field, element) for field in cls1.fields)
            list2 = (getattr(field, element) for field in cls2.fields)
            dupes = set(list1).intersection(list2)
            if len(dupes) > 0:
                msg = "Duplicate {}s '{}' appear in structures '{}' and '{}'."
                msg = msg.format(element, dupes, cls1.__name__, cls2.__name__)
                raise ValueError(msg)

def output_fields(*structure_classes, use_labels=True):
    """ Return a list of field names in a sensible order for tabular output."""
    conflict_check(structure_classes)

    record = collections.namedtuple("record", "key ordering")
    fieldnames = []
    for i, cls in enumerate(structure_classes):
        for field in cls.fields:
            key = field.label if use_labels else field.id
            ordering = field.sortorder(i)
            fieldnames.append(record(key, ordering))
    fieldnames.sort(key=lambda item: item.ordering)
    return [item.key for item in fieldnames]

class Field(object):  # pylint: disable=too-many-instance-attributes
    """ An individual field of a structure.

    For example, a 3-byte integer or a delimiter-terminated string. Most of the
    methods of Field are intended to transport value types to and from strings,
    bitstreams, file objects, etc.
    """
    def __init__(self, _id, label, _type, bits,
                 order=0, mod=0, comment="",
                 display=None, pointer=None):
        self.id = _id  # pylint: disable=invalid-name
        self.label = label
        self.type = _type
        self.bitsize = bits
        self.bytesize = util.divup(bits, 8)
        self.order = order
        self.mod = mod
        self.comment = comment
        self.display = display
        self.pointer = pointer

    @classmethod
    def from_stringdict(cls, odict):
        """ Create a Field object from a dictionary of strings.

        This is a convenience constructor intended to be used on the input from
        tsv structure definitions. All it does is convert values to the
        appropriate types and then pass them to the regular constructor.

        Missing values are assumed to be empty strings. Extra values are
        ignored.
        """
        expected_fields = ['id', 'label', 'type', 'size', 'order',
                           'mod', 'display', 'comment', 'pointer']
        odict = {key: odict.get(key, "") for key in expected_fields}

        return Field(_id=odict['id'],
                     label=odict['label'],
                     _type=odict['type'],
                     bits=util.tobits(odict['size'], 0),
                     order=util.intify(odict['order']),
                     mod=util.intify(odict['mod']),
                     comment=odict['comment'],
                     display=odict['display'],
                     pointer=odict['pointer'])

    @property
    def default(self):
        if 'str' in self.type:
            return ""
        else:
            return 0

    def read(self, source, bit_offset=None):
        """ Read a field from a bit offset within a bitstream.

        *source* may be any object that can be converted to a bitstream.

        *bit_offset* defaults to the current read position of *source* if
        possible, or to zero for objects that don't have a read position (e.g.
        bytes).

        The returned value will be a string or an int, as appropriate.
        """
        bs = util.bsify(source)
        if bit_offset is not None:
            bs.pos = bit_offset

        if self.type == 'union':
            return bs.read(self.bitsize)
        elif 'str' in self.type:
            maxbits = self.bitsize if self.bitsize else 1024*8
            pos = bs.pos
            data = bs.read(maxbits)
            return codecs.decode(data.bytes, self.display)
        else:
            try:
                fmt = "{}:{}".format(self.type, self.bitsize)
                return bs.read(fmt)
            except ValueError:
                msg = "Field '{}' of type '{}' isn't a valid type?"
                raise ValueError(msg, self.id, self.type)

    def bits(self, value):
        """ Convert a value to a Bits object."""
        if 'str' in self.type:
            return Bits(codecs.encode(value, self.display))
        elif 'bin' in self.type:
            # Separated because you can't pass length along with bin for some
            # reason.
            init = {self.type: value}
            return Bits(**init)
        else:
            init = {self.type: value, 'length': self.bitsize}
            return Bits(**init)

    def bytes(self, value):
        """ Convert a value to a bytes object.

        This may fail if the field is not a whole number of bytes long.
        """
        return self.bits(value).bytes

    def load(self, s):  # pylint: disable=invalid-name
        """ Convert the string *s* to an appropriate value type."""
        if self.type in ['str', 'strz', 'hex', 'union']:
            return s
        elif 'bin' in self.type:
            return util.undisplaybits(s, self.display)
        elif 'int' in self.type:
            return int(s, 0) - self.mod
        elif 'float' in self.type:
            return float(s) - self.mod
        else:
            msg = "Destringification of '{}' not implemented."
            raise NotImplementedError(msg, self.type)

    def dump(self, value):
        """ Convert *value* to a string.

        Note that we don't use the *str* builtin for this because some fields
        ought to have specific formatting in the output -- e.g. pointers should
        be a hex string padded to cover their width.
        """
        # FIXME bin types should have one letter per bit and use
        # upper/lowercase to indicate on/off. This is probably more useful
        # and keeps spreadsheets from trying to compact them to ints. Use the
        # display field to indicate the letters for each bit.
        if 'int' in self.type:
            value += self.mod
            fstr = util.int_format_str(self.display, self.bitsize)
            return fstr.format(value)
        if 'float' in self.type:
            value += self.mod
            return str(value)
        if 'bin' in self.type:
            return util.displaybits(value, self.display)
        if self.type in ['str', 'strz', 'hex']:
            return value
        if self.type == 'union':
            return str(value)
        # If we get here something is wrong.
        msg = "Stringification of '{}' not implemented."
        raise NotImplementedError(msg, self.type)

    def sortorder(self, origin_sequence_order=0):
        """ Get the sort order of this field for tabular output.

        This returns a tuple containing several properties relevant to sorting.
        Sort order is name, order given in definition, pointer/nonpointer
        (pointers go last), and the binary order of the field.

        This is done with a function rather than greater/less than because the
        field object doesn't actually know its binary order and needs to have
        it provided.
        """
        nameorder = 0 if self.label == "Name" else 1
        typeorder = 1 if self.display == "pointer" else 0
        return nameorder, self.order, typeorder, origin_sequence_order


def load(path, name=None, tts=None):
    spec = pathlib.Path(path)  # I hate lines like this so much.
    hooks = spec.parent.joinpath(spec.stem + '.py')
    if name is None:
        name = spec.stem
    with spec.open() as f:
        reader = util.OrderedDictReader(f, delimiter="\t")
        fields = [Field.from_stringdict(row)
                  for row in reader]
    try:
        module = SourceFileLoader(hooks.stem, str(hooks)).load_module()
        structure = module.make_struct(fields)
    except FileNotFoundError:
        structure = MetaStruct(name, (Structure,), {}, fields=fields)
    return structure
