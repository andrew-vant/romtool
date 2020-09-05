from abc import ABC, abstractmethod

from bitarray import bitarray
from bitarray.util import ba2int, int2ba
from fixedint import FixedInt
from fixedint.util import HexFormattingMixin


# Types in this module are expected to be immutable, low-level types that can
# be read and written to a stream, or interoperate with built-in types. So far
# these are all integrals.

class Primitive(ABC):
    """Interface for primitive types

    All primitives must define these methods. They are used by structs, lists,
    etc to read and write fields and items."""

    @classmethod
    @abstractmethod
    def from_bits(cls, ba):
        raise NotImplementedError

    @abstractmethod
    @classmethod
    def from_stream(cls, ba):
        raise NotImplementedError

    @abstractmethod
    def to_bits(self):
        raise NotImplementedError

    @abstractmethod
    def to_stream(self, stream):
        raise NotImplementedError


class uint_mixin:
    @classmethod
    def from_bits(cls, ba):
        return cls(ba2int(ba), width=len(ba), signed=False, mutable=False)

    @classmethod
    def from_stream(cls, stream):
        return cls.from_bits(stream.readbits(cls.width))

    def to_bits(self):
        return int2ba(self, length=self.width)

    def to_stream(self, stream):
        stream.writebits(self.to_bits())

    # Convenience properties
    @property
    def bits(self):
        return self.to_bits()

    @property
    def bytes(self):
        return self.to_bytes()


class uintle_mixin(uint_mixin):
    def to_bytes(self):
        return super().to_bytes('little')

    def to_bits(self):
        _bytes = self.to_bytes()
        ba = bitarray()
        ba.frombytes(_bytes)
        return ba

    @classmethod
    def from_bits(cls, ba):
        return cls.from_bytes(ba.tobytes(), byteorder='little', signed=False)


class uintbe_mixin(uint_mixin):
    def to_bytes(self):
        return super().to_bytes('big')

    def to_bits(self):
        _bytes = self.to_bytes()
        ba = bitarray()
        ba.frombytes(_bytes)
        return ba

    @classmethod
    def from_bits(cls, ba):
        return cls.from_bytes(ba.tobytes(), byteorder='big', signed=False)


def uint_cls(tpname, sz_bits, fmt=None):
    registry = {'uint': uint_mixin,
                'uintle': uintle_mixin,
                'uintbe': uintbe_mixin}

    bases = []
    bases.append(Primitive)
    bases.append(FixedInt(width=sz_bits, signed=False, mutable=False))
    if fmt == 'hex':
        bases.append(HexFormattingMixin)  # Love that this is builtin
    bases.append(registry[tpname])

    clsname = f'{tpname}{sz_bits}'
    newcls = type(clsname, tuple(reversed(bases)), {})
    return newcls

class String(collections.UserString):
    maxlength = None
    codec = None

    def from_bits(cls, ba):
        pass

    def to_bits(self):
        pass
