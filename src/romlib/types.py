from functools import lru_cache, partial
from dataclasses import dataclass, fields
from collections import UserList
from io import BytesIO

from anytree import NodeMixin

from .io import BitArrayView, Unit
from .util import intify

@dataclass
class Field:
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

    def __post_init__(self):
        self.name = self.name or self.id

    @property
    def is_int(self):
        return self.type in ['int', 'uint', 'uintbe', 'uintle']

    @property
    def is_str(self):
        return self.type in ['str', 'strz']

    @property
    def identifiers(self):
        return [self.id, self.name]

    def read(self, bitview):
        """ Plumbing behind getitem/getattr """
        if self.size:
            expected = self.size * self.unit
            assert len(bitview) == expected, f'{len(bitview)} != {expected}'
        return self.reader(bitview)

    def write(self, bitview, value):
        self.writer(bitview, value)

    @property
    def reader(self):
        return partial(self.readers[self.type], self)

    @property
    def writer(self):
        return partial(self.writers[self.type], self)

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
                kwargs[k] = convtbl[field.type](v)
        return cls(**kwargs)

    def _get_str(self, bitview):
        if not self.display:
            return bitview.bytes
        else:
            return bitview.bytes.decode(self.display)

    def _set_str(self, bitview, value):
        # This check avoids spurious changes in patches when there's more than
        # one way to encode the same string.
        if value == self._get_str(bitview):
            return
        # I haven't come up with a good way to give views a .str property (no
        # way to feed it a codec), so this is a bit circuitous.
        content = BytesIO(bitview.bytes)
        content.write(value.encode(self.display))
        content.seek(0)
        bitview.bytes = content.read()

    def _get_int(self, bitview):
        return getattr(bitview, self.type) + (self.arg or 0)

    def _set_int(self, bitview, value):
        value -= (self.arg or 0)
        setattr(bitview, self.type, value)

    @classmethod
    def register_type(cls, name, reader, writer):
        cls.readers[name] = reader
        cls.writers[name] = writer


    readers = {'int':    _get_int,
               'uint':   _get_int,
               'uintbe': _get_int,
               'uintle': _get_int,
               'str':    _get_str,
               'strz':   _get_str}

    writers = {'int':    _set_int,
               'uint':   _set_int,
               'uintbe': _set_int,
               'uintle': _set_int,
               'str':    _set_str,
               'strz':   _set_str}
