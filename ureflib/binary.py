import logging
import specs
from bitstring import ConstBitStream
from collections import OrderedDict

class BinaryException(Exception):
    pass

class BinaryFormatError(BinaryException):
    pass


def read(stream, spec, offset = 0):
    """ Read an arbitrary structure from a bitstream.

    The offset is the location in the stream where the structure begins. If
    the stream was created from a file, then it's the offset in the file.
    """
    stream.pos = offset
    od = OrderedDict()
    ordering = {}
    for field in spec:
        value = stream.read("{}:{}".format(field['type'], field['size']))
        od[field['id']] = value
        ordering[field['id']] = field['order']

    od = OrderedDict(sorted(od.items(), key=lambda item: ordering[item[0]]))
    return od

