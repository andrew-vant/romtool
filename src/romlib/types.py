import logging
from functools import partial
from dataclasses import dataclass, fields
from io import BytesIO
from abc import ABC, abstractmethod

from .io import Unit
from .util import HexInt

log = logging.getLogger(__name__)


class FieldExpr:
    """ A field property whose value may be variable

    This is mainly of use for field offsets and sizes that are defined by
    another field of the parent structure.
    """


    def __init__(self, spec):
        self.spec = spec

    def eval(self, parent):
        try:
            return int(self.spec, 0)
        except ValueError:
            return getattr(parent, self.spec)


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

    @abstractmethod
    def parse(self, string):
        """ Parse the string representation of this field's value type

        The resulting value is returned, for convenience.
        """

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
        cls = cls.handlers[kwargs['type']]
        return cls(**kwargs)

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

    @property
    def encoding(self):
        return ('ascii' if not self.display
                else self.display + '-clean' if self.type == 'strz'
                else self.display)

    def read(self, obj, objtype=None):
        if obj is None:
            return self
        return self.view(obj).bytes.decode(self.encoding)

    def write(self, obj, value):
        # This check avoids spurious changes in patches when there's more than
        # one way to encode the same string.
        if value == self.read(obj):
            return
        # I haven't come up with a good way to give views a .str property (no
        # way to feed it a codec), so this is a bit circuitous.
        view = self.view(obj)
        content = BytesIO(view.bytes)
        content.write(value.encode(self.encoding))
        content.seek(0)
        view.bytes = content.read()

    def parse(self, string):
        return string


class IntField(Field):
    handles = ['int', 'uint', 'uintbe', 'uintle']

    def read(self, obj, objtype=None):
        if obj is None:
            return self
        view = self.view(obj)
        i = getattr(view, self.type) + (self.arg or 0)
        if self.display in ('hex', 'pointer'):
            i = HexInt(i, len(view))
        return i

    def write(self, obj, value):
        view = self.view(obj)
        value -= (self.arg or 0)
        setattr(view, self.type, value)

    def parse(self, string):
        return int(string, 0)


class BytesField(Field):
    handles = ['bytes']

    def parse(self, string):
        return bytes.fromhex(string)


class StructField(Field):
    handles = []

    def read(self, obj, objtype=None):
        view = self.view(obj)
        return obj.registry[self.type](view, obj)

    def write(self, obj, value):
        value.copy(self.read(obj))

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
