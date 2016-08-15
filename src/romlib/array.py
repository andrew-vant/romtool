import struct
from collections import OrderedDict
from itertools import chain

# When arrays are serialized to an external file, the user will probably want
# to be able to rearrange them to suit whatever they're working on. But they
# need to be in their original order for patching to work correctly. Array
# serialization adds a column recording the original order; IDXHDR is the
# string that column's header will use.
IDXHDR = "_idx_"

class FixedIndex(object):
    def __init__(self, offset, stride, length, **kwargs):
        # kwargs is just there to eat extras so you can double splat a spec
        # dict.
        intify = lambda i: int(i, 0) if isinstance(str, i) else i
        self.offset = intify(offset)
        self.stride = intify(stride)
        self.length = intify(length)

    def indices(self):
        for i in range(self.length):
            yield self.stride * i + self.offset


class CrossIndex(object):
    def __init__(self, data, attr=None):
        """ Index on a list of structures.

        `data` should contain a list of structures as returned by Array.read or
        Array.load. `attr` should be the field id of the piece of the structure
        that serves as the index. attr defaults to the first field
        alphabetically. For single-element indexes (i.e. most of them), it's
        okay not to provide attr.

        Be aware that changing the items in data will also change what this
        index returns.
        """
        if not attr:
            attr = next(sorted(data[0].ids()))
        self.attr = attr
        self.array = data

    def indices(self):
        for item in self.array:
            yield item[self.attr]

class Array(object):
    """ Really just an unpacker for specs"""
    def __init__(self, spec, struct=None):
        self.name = spec['name']
        self.set = spec['set']
        self.struct = struct if struct else primitive(spec)
        self.index = spec['index']
        self.priority = util.intify(spec['priority'], 0)
        if not self.index:
            self.index = FixedIndex(**spec)

    def read(self, rom, index=None):
        if not index:
            index = self.index
        bs = util.bsify(rom)
        for offset in index.indices():
            bs.pos = offset * 8
            yield self.struct(bs)


    def load(self, dicts):
        """ Deserialize this array from an iterable of dicts."""
        sorter = lambda d: util.intify(d.get('_idx_', None))
        for dct in sorted(dicts, key=sorter):
            yield self.struct(dct)


    def dump(self, structs):
        # This could be top-level but it's here for API consistency
        for struct in structs:
            yield struct.dump()


    def bytemap(self, structs, index=None):
        if not index:
            index = self.index
        bytemap = {}
        for offset, struct in zip(index.indices(), structs):
            bytemap.update(struct.bytemap(offset))
        return bytemap

def primitive(aspec):
    """ Create a structure for use by an array of primitives"""
    sspec = {
            "id": aspec['name'],
            "label": aspec['label'],
            "type": aspec['type'],
            "size": aspec['stride'],
            "mod": aspec['mod'],
            "display": aspec['display']
            }
    name = aspec['name']
    return struct.define_struct(name, [aspec])


def mergedump(*arraydata, use_labels=True, record_order=True):
    """ Splice and dump multiple arrays that are part of a set.

    record_order adds an extra key recording the original order of the items in
    the arrays, so it can be preserved when reading back a re-sorted file.

    The returned items are OrderedDicts. This means .keys() can be used to get
    the appropriate headers for exporting to tsv.
    """
    keys = None
    for structs in zip(arraydata):
        if keys is None:
            classes = [type(structure) for structure in structs]
            keys = struct.output_fields(*classes) + ['_idx_']
        cm = itertools.ChainMap(s.dump() for s in structs)
        yield OrderedDict((key, cm[key]) for key in keys)
