import logging
import enum

from bitarray import bitarray
from bitarray.util import int2ba, ba2int, bits2bytes, ba2hex, hex2ba
from anytree import NodeMixin
from anytree.search import find

from .util import bytes2ba

log = logging.getLogger(__name__)


class Unit(enum.IntEnum):
    bits = 1
    bytes = 8
    kb = 8 * 2**10
    mb = 8 * 2**20
    gb = 8 * 2**30

    def __contains__(self, item):
        return item in type(self).__members__


class BitArrayView(NodeMixin):
    """ Low level data handler

    A BitArrayView is a view on part of a bitarray -- typically a data block (header
    vs rom), or a structure's contents. Slicing a view will produce a smaller
    view. The "step" slice attribute has been altered; it represents the
    size-unit of the slice indexes.

    Hence, view[1:8:Unit.bytes] would return a view containing bytes one
    through seven inclusive. view[1:8:Unit.bits] would get a view of
    *bits* one through seven inclusive.

    Slices are indexed relative to the view's start and end, not the
    underlying bitarray. The underlying bitarray is available as BitArrayView.bits.
    """
    def __init__(self, auto, offset=None, length=None, name=None):
        if isinstance(auto, BitArrayView):
            self.parent = auto
        elif isinstance(auto, bitarray):
            self.parent = None
            self._ba = auto
        else:
            raise TypeError(f"Don't know what to do with a {type(auto)}")

        self.name = name
        self.offset = offset or 0
        self.length = (length if length
                       else (len(self.parent) - self.offset) if self.parent
                       else len(self._ba) - self.abs_start)
        assert self.length >= 0

    def __len__(self):
        return self.length

    def __str__(self):
        return f'BitArrayView[{self.offset}:{self.end}]'

    def __repr__(self):
        _inobj = 'parent' if self.parent else 'ba'
        return f'BitArrayView({_inobj}, {self.offset}, {len(self)})'

    def origin(self, name):
        return find(self.root, lambda n: n.name == name)

    @property
    def end(self):
        return self.offset + len(self)

    def __getitem__(self, sl):
        if not isinstance(sl, slice):
            return self.bits[sl]

        start, stop, unit = sl.start, sl.stop, sl.step

        if start is None:
            start = 0
        if stop is None:
            stop = self.end
        if unit is None:
            unit = 1
        if isinstance(unit, str):
            unit = Unit[unit]

        start *= unit
        stop *= unit

        if start < 0:
            start += len(self)
        if stop < 0:
            stop += len(self)

        return BitArrayView(self, start, stop-start)

    @property
    def ba(self):
        return self.root._ba

    @property
    def abs_start(self):
        return self.offset + sum(s.offset for s in self.ancestors)

    @property
    def abs_end(self):
        return self.abs_start + len(self)

    @property
    def abs_slice(self):
        assert self.abs_end - self.abs_start == len(self)
        return slice(self.abs_start, self.abs_end)

    #
    # TYPE INTERPRETATION PROPERTIES START HERE
    #

    @property
    def hex(self):
        return ba2hex(self.bits)

    @hex.setter
    def hex(self, s):
        self.bits = hex2ba(s, endian=self.ba.endian())

    @property
    def bits(self):
        return self.ba[self.abs_slice]

    @bits.setter
    def bits(self, ba):
        if len(ba) != len(self):
            msg = f"expected {len(self)} bits, got {len(ba)}"
            raise ValueError(msg)
        self.ba[self.abs_slice] = ba

    @property
    def bytes(self):
        return self.bits.tobytes()

    @bytes.setter
    def bytes(self, _bytes):
        self.bits = bytes2ba(_bytes, endian=self.ba.endian())

    @property
    def uint(self):
        return ba2int(self.bits)

    @uint.setter
    def uint(self, i):
        self.bits = int2ba(i, length=len(self), endian=self.ba.endian())

    @property
    def uintbe(self):
        return self.uint

    @uintbe.setter
    def uintbe(self, i):
        self.uint = i

    @property
    def uintle(self):
        return int.from_bytes(self.bytes, 'little')

    @uintle.setter
    def uintle(self, i):
        self.bytes = (i).to_bytes(bits2bytes(len(self)), 'little')
