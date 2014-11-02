import logging
import specs
from bitstring import ConstBitStream
from collections import OrderedDict

class BinaryException(Exception):
    pass

class BinaryFormatError(BinaryException):
    pass


def read(stream, struct, offset = 0):
    """ Read an arbitrary structure from a bitstream.

    The offset is the location in the stream where the structure begins. If
    the stream was created from a file, then it's the offset in the file.
    """
    stream.pos = offset
    od = OrderedDict()
    ordering = {}
    for field in struct:
        value = stream.read("{}:{}".format(field['type'], field['size']))
        fid = field['id']
        od[fid] = value
        ordering[fid] = field['order']
        if "hex" in field.tags or "pointer" in field.tags:
            digits = field['size'] * 2 # Two hex digits per byte
            fmtstr = "0x{{:0{}X}}".format(digits)
            od[fid] = fmtstr.format(value)

    od = OrderedDict(sorted(od.items(), key=lambda item: ordering[item[0]]))
    return od

