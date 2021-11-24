import logging
import enum
import hashlib
import zlib
import codecs

from bitarray import bitarray
from bitarray.util import int2ba, ba2int, bits2bytes, ba2hex, hex2ba
from anytree import NodeMixin
from anytree.search import find
from collections import namedtuple
from io import BytesIO

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
        self._ba = None
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
                       else len(self.ba) - self.abs_start)
        assert len(self.bits) == len(self), f"{len(self.bits)} != {len(self)}"

    def __len__(self):
        return self.length

    def __eq__(self, other):
        return self.bits == other.bits

    @property
    def sha1(self):
        """ Get sha1 hash of contents """
        return hashlib.sha1(self.bytes).hexdigest()

    @property
    def md5(self):
        return hashlib.md5(self.bytes).hexdigest()

    @property
    def crc32(self):
        checksum = zlib.crc32(self.bytes)
        return f"{checksum:08X}"

    @property
    def ct_bytes(self):
        if len(self) % Unit.bytes:
            raise ValueError("Not an even number of bytes")
        else:
            return len(self) // Unit.bytes

    @property
    def ct_bits(self):
        return len(self)

    @property
    def os_bytes(self):
        if len(self) % Unit.bytes:
            raise ValueError("Not an even number of bytes")
        else:
            return self.offset // Unit.bytes

    def __str__(self):
        bits = ''.join('1' if b else '0' for b in self)
        return f'BitArrayView({bits})'

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

        if unit is None:
            unit = 1
        if isinstance(unit, str):
            unit = Unit[unit]

        if start is None:
            start = 0
        else:
            start *= unit

        if stop is None:
            stop = self.end
        else:
            stop *= unit

        if start < 0:
            start += len(self)
        if stop < 0:
            stop += len(self)

        return BitArrayView(self, start, stop-start)

    @property
    def ba(self):
        return self._ba or self.root.ba

    @property
    def abs_start(self):
        return self.offset + sum(s.offset for s in self.ancestors)

    @property
    def abs_end(self):
        return self.abs_start + len(self)

    @property
    def abs_slice(self):
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
        bits = self.ba[self.abs_slice]
        return bits

    @bits.setter
    def bits(self, ba):
        old = self.bits
        if len(ba) != len(self):
            msg = f"expected {len(self)} bits, got {len(ba)}"
            raise ValueError(msg)
        self.ba[self.abs_slice] = ba
        new = self.bits
        if new != old:
            log.debug("change detected: %s -> %s", old, new)

    @property
    def str(self):
        nt = namedtuple('str', 'read write')
        return nt(self.str_read, self.str_write)

    @property
    def strz(self):
        nt = namedtuple('strz', 'read write')
        return nt(self.strz_read, self.strz_write)

    def str_read(self, encoding):
        encoding = encoding or 'ascii'
        return self.bytes.decode(encoding)

    def str_write(self, value, encoding):
        encoding = encoding or 'ascii'
        codec = codecs.lookup(encoding)
        s_old, bct_old = codec.decode(self.bytes)

        # Avoid spurious changes when there's multiple valid encodings
        if value == s_old:
            return

        # Pad fixed-length strings with spaces
        content = BytesIO(' '.encode(encoding) * len(self.bytes))
        content.write(value.encode(encoding))
        content.seek(0)
        self.bytes = content.read()


    def strz_read(self, encoding):
        encoding = 'ascii' if not encoding else encoding + '-clean'
        codec = codecs.lookup(encoding)
        # Evil way to figure out if we're using a default codec, like ascii.
        # The default codecs don't stop on nulls, but we probably want to.
        # FIXME: Awful, find a better way to do this.
        if hasattr(codec, 'eos'):
            data = self.bytes
        else:
            data = self.bytes.partition(b'\0')[0]
        return data.decode(encoding)

    def strz_write(self, value, encoding):
        encoding = 'ascii' if not encoding else encoding + '-clean'
        codec = codecs.lookup(encoding)
        b_old = (self.bytes if hasattr(codec, 'eos')
                 else self.bytes.partition(b'\0')[0])
        s_old, bct_old = codec.decode(b_old)

        # Avoid spurious changes when there's multiple valid encodings
        if value == s_old:
            return

        # Scribbling past the old string's terminator will usually cause
        # problems, but it might be intentional, so warn rather than failing.
        #
        # FIXME: this check doesn't work with builtin codecs. They don't treat
        # nulls as EOS, so always read to the end of the view. Need a way to
        # deal with that.
        b_new = value.encode(encoding)
        overrun = len(b_new) - bct_old
        log.debug(f"replacing string '{s_old}' (len {bct_old}) "
                  f"with '{value}' (len {len(b_new)})")
        if overrun > 0:
            log.warning(f"replacement string '{value}' overruns end of old "
                        f"string '{s_old}' by {overrun} bytes")
        content = BytesIO(self.bytes)
        content.write(b_new)
        content.seek(0)
        self.bytes = content.read()

    @property
    def bin(self):
        return ''.join('1' if bit else '0' for bit in self)

    @bin.setter
    def bin(self, string):
        self.bits = bitarray(string, endian=self.ba.endian())

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
        if isinstance(i, str):
            i = int(i, 0)
        old = self.uint
        self.bits = int2ba(i, length=len(self), endian=self.ba.endian())
        if old != self.uint:
            log.debug("change detected: %s -> %s", old, self.uint)

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
        if isinstance(i, str):
            i = int(i, 0)
        self.bytes = (i).to_bytes(bits2bytes(len(self)), 'little')

    @property
    def int(self):
        return ba2int(self.bits, signed=True)

    @int.setter
    def int(self, i):
        if isinstance(i, str):
            i = int(i, 0)
        old = self.int
        self.bits = int2ba(
                i,
                length=len(self),
                endian=self.ba.endian(),
                signed=True
                )
        if old != self.int:
            log.debug("change detected: %s -> %s", old, self.int)
