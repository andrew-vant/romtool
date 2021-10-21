import logging
from functools import partial
from dataclasses import dataclass, fields
from io import BytesIO
from abc import ABC, abstractmethod

from .io import Unit
from .util import HexInt

log = logging.getLogger(__name__)


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
    offset: int = None
    size: int = None
    arg: int = None
    display: str = None
    order: int = 0
    comment: str = ''

    handlers = {}
    handles = []

    def __post_init__(self):
        self.name = self.name or self.id

    @property
    def identifiers(self):
        return [self.id, self.name]

    def read(self, bitview):
        """ Read a value from a bitview

        The default implementation assumes the field's `type` is a readable
        attribute of a bitview.
        """
        if self.size:
            expected = self.size * self.unit
            assert len(bitview) == expected, f'{len(bitview)} != {expected}'
        return getattr(bitview, self.type)

    def write(self, bitview, value):
        """ Write a value to a bitview

        The default implementation assigns to the bitview attribute named by
        self.type.
        """
        setattr(bitview, self.type, value)

    @abstractmethod
    def parse(self, bitview, string):
        """ Write a stringified value to a bitview

        The resulting value is returned, for convenience.
        """
        pass

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for typename in cls.handles:
            cls.handle(typename)

    @classmethod
    def from_tsv_row(cls, row):
        kwargs = {}
        convtbl = {int: partial(int, base=0),
                   Unit: Unit.__getitem__,
                   str: str}
        for field in fields(cls):
            k = field.name
            v = row.get(k, None) or None  # ignore missing or empty values
            if v is not None:
                try:
                    kwargs[k] = convtbl[field.type](v)
                except ValueError:
                    kwargs[k] = v
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

    def read(self, bitview):
        return bitview.bytes.decode(self.encoding)

    def write(self, bitview, value):
        # This check avoids spurious changes in patches when there's more than
        # one way to encode the same string.
        if value == self.read(bitview):
            return
        # I haven't come up with a good way to give views a .str property (no
        # way to feed it a codec), so this is a bit circuitous.
        content = BytesIO(bitview.bytes)
        content.write(value.encode(self.encoding))
        content.seek(0)
        bitview.bytes = content.read()

    def parse(self, string):
        return string


class IntField(Field):
    handles = ['int', 'uint', 'uintbe', 'uintle']

    def read(self, bitview):
        i = getattr(bitview, self.type) + (self.arg or 0)
        if self.display in ('hex', 'pointer'):
            return HexInt(i, len(bitview))
        else:
            return i

    def write(self, bitview, value):
        value -= (self.arg or 0)
        setattr(bitview, self.type, value)

    def parse(self, string):
        return int(string, 0)


class BytesField(Field):
    handles = ['bytes']

    def parse(self, string):
        return bytes.fromhex(string)


class StructField(Field):
    handles = []

    def read(self, bitview, parent):
        return parent.registry[self.type](bitview, parent)

    def write(self, bitview, value):
        value.copy(self.read(bitview, parent))

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
