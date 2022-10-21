import logging
from functools import partial
from dataclasses import dataclass, fields, asdict
from io import BytesIO
from abc import ABC, abstractmethod
from collections.abc import Mapping

from asteval import Interpreter

from .io import Unit
from .util import HexInt, IndexInt

from .exceptions import RomtoolError

log = logging.getLogger(__name__)


class FieldContext(Mapping):
    """ A dict-like context intended to be passed to asteval

    The following names are available when evaluating:

    * `root` refers to the root file view
    * `rom` refers to the rom object
    * all field IDs of the structure being evaluated are available, and will
      read the value of that field.
    * TODO: table names from the ROM, so you don't need rom.table
    * TODO: the index of the struct within its table. Useful for
      cross-references.
    """

    def __init__(self, struct):
        self.struct = struct

    def __getitem__(self, key):
        if key == 'root':
            return self.struct.view.root
        if key == 'rom':
            raise NotImplementedError
        if key in self.struct.fids:
            return getattr(self.struct, key)
        raise ValueError(f"name not in context: {key}")

    def __iter__(self):
        yield 'rom'
        yield 'root'
        yield from self.struct.fids

    def __len__(self):
        return len(iter(self))


class FieldExpr:
    """ A field property whose value may be variable

    This is mainly of use for field offsets and sizes that are defined by
    another field of the parent structure.
    """


    def __init__(self, spec):
        if not spec:
            raise ValueError("empty fieldexpr spec")
        self.spec = spec

        # Eval of any kind can be dangerous, and I'd like third-party maps to
        # be safe-ish, so for now let's avoid any builtin stuff at all and see
        # if it's good enough.
        #
        # NOTE: Interpreter creation is *surprisingly* expensive, espcially the
        # default symtable creation. So skip the default creation and make the
        # interpreter only once. We'll set the actual symtable just before
        # using it.
        self.interpreter = Interpreter({}, minimal=True)

        # NOTE: eval itself is pretty expensive, and the vast majority of
        # these expressions are simple integers. Let's pre-calculate if
        # possible.
        try:
            self.value = int(spec, 0)
            self.static = True
        except ValueError:
            self.value = None
            self.static = False

    def __str__(self):
        return self.spec

    def eval(self, parent):
        if self.static:
            return self.value
        self.interpreter.symtable = FieldContext(parent)
        result = self.interpreter.eval(self.spec)
        errs = self.interpreter.error
        if errs:
            msg = "error evaluating FieldExpr '{}': {}"
            for err in errs:
                log.error(msg.format(self.spec, err.msg))
            raise RomtoolError(msg.format(self.spec, err.msg))
        return result

@dataclass
class Field(ABC):
    """ Define a ROM object's type and location

    There's a lot of things needed to fully characterize "what something is,
    and where":

    - id       (python identifier)
    - type     (could be a sub-struct or str or custom type (FF1 spell arg))
    - origin   ([parent], rom, file)
    - unit     (bits, bytes, kb)
    - offset   (0, 0xFF, other_field, other_field +0xFF? default to previous field's offset + length, or 0)
    - size     (8, 0xFF)
    - arg      (endian for bits, modifier for ints?)
    - display  (format spec (ints) or encoding (str), implement __format__ somewhere?)
    - ref      (int is an index of a table entry)
    - order    (output order)
    - comment  (e.g. meaning of bits (but pretty sure I should use substruct for bitfields?))
    """

    id: str
    name: str = None
    type: str = 'uint'
    origin: str = None
    unit: Unit = Unit.bytes
    offset: FieldExpr = None
    size: FieldExpr = '1'
    arg: int = None
    ref: str = None
    display: str = None
    order: int = 0
    comment: str = ''

    handlers = {}
    handles = []

    def __post_init__(self):
        self.name = self.name or self.id
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None and not isinstance(value, field.type):
                raise ValueError(f'Expected {field.name} to be {field.type}, '
                                 f'got {type(value)}')
        if self.offset is None:
            msg = f"'{self.id}' field missing required offset property"
            raise RomtoolError(msg)

    def _sort_for_readability(self):
        """ Get an ordering key for this field

        It's often useful to order fields for readability rather than the
        typical (in specs) offset order. This orders name fields first, pushes
        opaque or unknown fields towards the end, and otherwise orders
        according to the sort order given in the spec.

        Sorting an iterable of fields directly will use this key.
        """
        return (
                not self.is_name,
                self.is_slop,
                self.is_ptr,
                self.is_unknown,
                self.is_flag,
                self.order or 0,
               )

    def __lt__(self, other):
        return self._sort_for_readability() < other._sort_for_readability()

    @property
    def is_name(self):
        return 'name' in (self.id.lower(), self.name.lower())

    @property
    def is_flag(self):
        return self.size.spec == '1' and self.unit == Unit.bits

    @property
    def is_ptr(self):
        return self.display == 'pointer'

    @property
    def is_unknown(self):
        return 'unknown' in self.name.lower()

    @property
    def is_slop(self):
        slop_names = ['padding', 'reserved']
        return self.name.lower() in slop_names

    @property
    def identifiers(self):
        return [self.id, self.name]

    def view(self, obj):
        """ Get the bitview corresponding to this field's data """
        # Get the parent view that this field is "relative to"
        context = (obj.view if not self.origin
                   else obj.view.root if self.origin == 'root'
                   else obj.view.root.find(self.origin))
        offset = self.offset.eval(obj) * self.unit
        size = self.size.eval(obj) * self.unit
        end = offset + size
        return context[offset:end]

    def read(self, obj, objtype=None):
        """ Read from a structure field

        The default implementation assumes the field's `type` is a readable
        attribute of a bitview.
        """
        if obj is None:
            return self
        view = self.view(obj)
        assert len(view) == self.size.eval(obj) * self.unit
        return getattr(view, self.type)

    def write(self, obj, value):
        """ Write to a structure field

        The default implementation assigns to the bitview attribute named by
        self.type.
        """
        setattr(self.view(obj), self.type, value)

    def parse(self, string):
        """ Parse the string representation of this field's value type

        The resulting value is returned, for convenience.
        """
        raise NotImplementedError("don't know how to parse a %s", type(self))

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for typename in cls.handles:
            cls.handle(typename)

    @classmethod
    def from_tsv_row(cls, row):
        kwargs = {}
        convtbl = {int: partial(int, base=0),
                   Unit: Unit.__getitem__,
                   FieldExpr: FieldExpr,
                   str: str}
        for field in fields(cls):
            k = field.name
            v = row.get(k, None) or None  # ignore missing or empty values
            if v is not None:
                kwargs[k] = convtbl[field.type](v)
        if kwargs['type'] not in cls.handlers:
            raise RomtoolError(f"'{kwargs['type']}' is not a known field type")
        cls = cls.handlers[kwargs['type']]
        return cls(**kwargs)

    def asdict(self):
        return {f.name: getattr(self, f.name) or '' for f in fields(self)}

    @classmethod
    def handle(cls, typename):
        name = cls.__name__
        if typename in cls.handlers:
            other = cls.handlers[typename].__name__
            msg = (f"{name} wants to handle type '{typename}', "
                   f"but it is already handled by {other}")
            raise ValueError(msg)
        cls.handlers[typename] = cls
        log.debug(f"{name} registered as handler for '{typename}'")


class StringField(Field):
    handles = ['str', 'strz']

    def __post_init__(self):
        super().__post_init__()

    def read(self, obj, objtype=None):
        if obj is None:
            return self
        return getattr(self.view(obj), self.type).read(self.display)

    def write(self, obj, value):
        getattr(self.view(obj), self.type).write(value, self.display)

    def parse(self, string):
        return string


class IntField(Field):
    handles = ['int', 'uint', 'uintbe', 'uintle']
    enums = {}

    @property
    def enum(self):
        """ Get enum type for this field, if relevant, otherwise int"""
        return self.enums.get(self.display)

    def read(self, obj, objtype=None, realtype=None):
        if obj is None:
            return self
        view = self.view(obj)
        i = getattr(view, (realtype or self.type)) + (self.arg or 0)
        if self.display in ('hex', 'pointer'):
            i = HexInt(i, len(view))
        if self.enum:
            try:
                i = self.enum(i)
            except ValueError:
                pass
        if self.ref:
            i = IndexInt(obj.root.entities[self.ref], i)
        return i

    def write(self, obj, value, realtype=None):
        if isinstance(value, str):
            if self.enum:
                try:
                    value = self.enum[value]
                except KeyError:
                    value = int(value, 0)
            elif self.ref:
                value = obj.root.entities[self.ref].locate(value)
            else:
                value = int(value, 0)
        view = self.view(obj)
        value -= (self.arg or 0)
        setattr(view, (realtype or self.type), value)

    def parse(self, string):
        parser = self.enum.parse if self.enum else partial(int, base=0)
        return parser(string)

    @classmethod
    def handle(cls, typename, enum=None):
        super().handle(typename)
        if enum:
            cls.enums[typename] = enum


class BytesField(Field):
    handles = ['bytes']

    def parse(self, string):
        return bytes.fromhex(string)


class StructField(Field):
    handles = []

    def read(self, obj, objtype=None, realtype=None):
        if obj is None:
            return self
        view = self.view(obj)
        return obj.registry[realtype or self.type](view, obj)

    def write(self, obj, value, realtype=None):
        target = self.read(obj)
        if isinstance(value, str):
            target.parse(value)
        else:
            value.copy(target)

    def parse(self, string):
        raise NotImplementedError


class BinField(Field):
    handles = ['bin']

    def parse(self, string):
        # libreoffice thinks it's hilarious to truncate 000011 to 11; pad as
        # necessary if possible.
        if isinstance(self.size, int):
            string = string.zfill(self.size * self.unit)
        return string
