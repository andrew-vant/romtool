from bitarray import bitarray
from bitarray.util import int2ba, ba2int


# Integer conversion functions
def _ba2uint(ba, /, byte_endianness) -> int:
    """ Helper function for ba->uint conversion """
    if len(ba) % 8 != 0:
        raise ValueError('a byte-aligned length is required')
    return int.from_bytes(ba, byte_endianness)


def _uint2ba(i, /, length, byte_endianness, endian=None) -> bitarray:
    if length % 8 != 0:
        raise ValueError('a byte-aligned length is required')
    ba = bitarray(endian=endian)
    _bytes = i.to_bytes(length // 8, byte_endianness)
    ba.frombytes(_bytes)
    return ba


def bytes2ba(_bytes, /, endian=None) -> bitarray:
    ba = bitarray(endian=endian)
    ba.frombytes(_bytes)
    return ba


def ba2bytes(ba, /) -> bytes:
    if len(ba) % 8 != 0:
        raise ValueError('a byte-aligned length is required')
    return ba.tobytes()

uint2ba = int2ba
ba2uint = ba2int
bytes2ba = bytes2ba
ba2bytes = ba2bytes
ba2uintle = partial(_ba2uint, byte_endianness='little')
ba2uintbe = partial(_ba2uint, byte_endianness='big')
uintle2ba = partial(_uint2ba, byte_endianness='little')
uintle2ba = partial(_uint2ba, byte_endianness='big')

def reader(typename):
    return globals()[f'{typename}2ba']

def writer(typename):
    return globals()[f'ba2{typename}']
