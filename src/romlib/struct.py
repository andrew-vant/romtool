# A structure type needs a list of fields and some way of describing how they
# relate to each other for pointer purposes.

# A structure instance gets an attribute for each field in the structure type.

# There must be some way for modules to create their own structure types for
# purposes like loading extra data after the main struct. Field descriptions
# need some way of indicating whether they should be loaded or not

# Perhaps a meta field indicating data, pointer, optional? No, pointer is
# already implied by the pointer field, so I need default-vs-optional.

# Possibility: structure type contains a list of fields to treat as
# baseload/postload/dereference, defaults to all except
# pointers/nothing/pointers

# No, should be explicit in map. Just not sure which field it belongs in.

import io
import csv
import pathlib
import logging
from collections import OrderedDict
from importlib.machinery import SourceFileLoader

import bitstring

from . import util
from . import field


class MetaStruct(type):
    def __init__(cls, name, bases, dct):
        super().__init__(name, bases, dct)
        cls.fieldmap = {}
        for field in cls.fields.values():
            # Forbid shadowing
            if field.id in dir(cls):
                msg = "Field id {}.{} conflicts with builtin method."
                raise ValueError(msg, name, field.id)
            # Make it easy to dereference labels
            cls.fieldmap[field.id] = field
            cls.fieldmap[field.label] = field


class Structure(object, metaclass=MetaStruct):
    # Map of field names to field classes
    # Problem: inherting must specify explicitly?
    fields = OrderedDict()

    @classmethod
    def _realkey(cls, key):
        """ Dereference labels to ids if needed."""
        return cls.fieldmap[key].id

    @property
    @classmethod
    def base_fields(cls):
        """ Get a list of primary data fields in the structure.

        The list will be in the same order that they should be read from a rom
        file, so you can loop over it when reading.
        """
        return [field for field in cls.fields.values()
                if not field.pointer and field.meta != "extra"]

    @property
    @classmethod
    def extra_fields(cls):
        """ Get a list of extended data fields after the structure.

        These are optional data fields for variable-length structures. They
        should be read after primary data, but before links. They will be
        listed in the order they appear in the structure definition file.
        """
        return [field for field in cls.fields.values()
                if field.meta == "extra"]

    @property
    @classmethod
    def link_fields(cls):
        """ Get a list of data links in the structure.

        These are values that are pointed-to by something in the structure's
        primary data, so they have to be loaded after the primary data fields.
        """
        return [field for field in cls.fields.values()
                if field.pointer]

    def __init__(self, auto=None):
        # Non-present optional fields are represented by "None." It is an
        # error for non-optional fields to remain None at the end of
        # initialization.
        self.data = {field.id: None for field in self.fields}

        # Initializing using whichever method is called for by the type of
        # input.
        dispatch = {bitstring.Bits: self._init_from_bitstring,
                    io.IOBase: self._init_from_file,
                    dict: self._init_from_dict}
        for tp, func in dispatch.items():
            if isinstance(auto, tp):
                func[tp](auto)
                break

        # Make sure no non-optional fields are still None, which would indicate
        # somebody made a mistake.
        mandatory = chain(self.base_fields, self.link_fields)
        assert(not any(self[field.id] is None for field in mandatory))

    def _init_from_dict(self, dct):
        for key, string in dct:
            self[key] = string

        # Empty strings in optional fields indicate that they're not present.
        for field in self.extra_fields:
            if self[field.id] == "":
                del self[field.id]

    def _init_from_file(self, f):
        bs = bitstring.ConstBitStream(f)
        self._init_from_bs(bs)

    def _init_from_bs(self, bs):
        self.read_base(bs)
        self.read_extra(bs)
        self.read_links(bs)

    def read_base(self, bs):
        """ Read primary data

        This reads the main, fixed portion of a data structure. After reading,
        the bit position of `bs` will be one bit past the end of the data read.
        """
        for field in self.base_fields:
            self.data[field.id] = field(bs, self)

    def read_extra(self, bs):
        """ Read optional data

        This is a hook for variable-length structs or structs with
        context-dependent data. It must be overridden to be of any use.
        After reading, the bit position of `bs` must be set one bit past the
        end of the data read. This will happen automatically with repeated
        bs.read calls.
        """
        if len(self.extra_fields) > 0:
            msg = "'{}' has extra fields but didn't implement them"
            raise NotImplementedError(msg, type(self))

    def read_links(self, bs):
        """ Read linked data.

        Order matters; this shouldn't be run until after pointers are read in.
        FIXME: Recursive pointers would be nice to support.

        read_links should restore the read position of `bs` before returning, but
        this is not guaranteed if an exception is thrown.
        """
        oldpos = bs.pos # Save this to reset it after reading links.
        for field in self.link_fields:
            pointer = self.fieldmap[field.pointer]
            offset = self[pointer.id] + pointer.mod
            bs.pos = offset * 8
            self.data[field.id] = field(bs.read(field.size), parent)
        bs.pos = oldpos

    def __setitem__(self, key, value):
        """ Set an attribute using dictionary syntax.

        Attributes can be looked by by label as well as ID.
        """
        key = self._realkey(key)
        if self.data[key] is None:
            self.data[key] = self.fields[key](value, self)
        else:
            self.data[key].value = value

    def __getitem__(self, key):
        """ Get an attribute using dictionary syntax.

        Attributes can be looked by by label as well as ID.
        """
        key = self._realkey(key)
        if self.data[key] is None:
            return None
        else:
            return self.data[key].value

    def __delitem__(self, key):
        """ Unset a field value.

        For variable-length structures or other weird edge cases, this
        indicates that a given field is unused or omitted and should be skipped
        or ignored when generating patches.

        This doesn't actually delete the underlying attribute, just sets it to
        None.
        """
        self.data[_realkey(key)] = None

    def __getattr__(self, name):
        if name in self.data:
            return self[name]
        elif hasattr(super(), "__getattr__"):
            return super().__getattr__(name)
        else:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self.data:
            self[name] = value
        else:
            super().__setattr__(name, value)

    def __delattr__(self, name):
        """ Remove a field by id.

        This sets the underlying data to None, which is interpreted as
        "this field isn't present in the structure in ROM. Use for
        'optional' fields.
        """
        if name in self.ids():
            del self[name]
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
        return (self[field.id] for field in self.fields)

    def items(self, *, labels=False):
        return ((field.id, self[field.id]) for field in self.fields)

    def offset(self, fieldname):
        """ Get the offset of a field from the start of the structure."""
        raise NotImplementedError

    def dump(self):
        """ Get a string-to-string dictionary of the structure's contents.

        Suitable for putting in a csv file or similar. All display conversions
        are handled by the fields' .string methods.
        """
        return {fid: (field.string if field is not None else "")
                for fid, field in self.data.items()}

    def bytemap(self, offset):
        raise NotImplementedError


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
    """ Return a list of field names in a sensible order for tabular output.

    This sorts based on a number of properties, in order of priority

    1. Name vs. non-name (name comes first).
    2. Explicit order in field spec.
    3. Pointer vs. non-pointer (non-pointer comes first).
    4. Order of parent structure in structure_classes.
    5. Order the field appears in the structure spec.
    """
    conflict_check(structure_classes)
    # Build a dict mapping field ids/labels to ordering tuples.
    ordering = {}
    for structorder, structure in enumerate(structure_classes):
        for specorder, field in enumerate(structure.fields):
            nameorder = 0 if field.label == "Name" else 1
            # Cheap kludge, should really check for other fields pointing to it.
            ptrorder = 1 if field.display == "pointer" else 0
            output_key = field.label if use_labels else field.id
            ordering[output_key] = (nameorder, field.order, ptrorder,
                                    structorder, specorder)

    # Sort by the ordering tuple and return the corresponding keys.
    sorter = lambda header, order: order
    return [fid for fid, order in sorted(ordering.items, key=sorter)]


def define_struct(name, specs):
    # spec should be an iterable of dictionaries, each in the format used by
    # romlib.Field.
    # Can this be done by mucking with the input dictionary in MetaStruct
    # safely?

    fields = OrderedDict()
    for spec in specs:
        logging.debug("Processing field '%s'", spec['id'])
        fid = spec['id']
        fields[fid] = field.define_field(fid, spec)
    bases = (Structure,)
    clsdict = {"fields": fields}
    cls = type(name, bases, clsdict)
    return cls


def load(path):
    path = pathlib.Path(path)  # I hate lines like this so much.
    name = path.stem
    logging.info("Loading '%s' from %s", name, str(path))
    with path.open() as f:
        specs = list(csv.DictReader(f, delimiter="\t"))
    base = define_struct(name, specs)
    try:
        modulepath = str(path.parent.joinpath(name + '.py'))
        module = SourceFileLoader(name, modulepath).load_module()
        return module.make_struct(base)
    except FileNotFoundError:
        return base
