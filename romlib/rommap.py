import romlib

from collections import OrderedDict
from . import util

class RomMap(object):
    pass

class ArrayDef(object):
    def __init__(self, spec, sdef=None):
        # Record some basics, convert as needed.
        self.name = spec['name']
        self.type = spec['type']
        self.length = int(spec['length'])
        self.offset = util.tobits(spec['offset'])
        self.stride = util.tobits(spec['stride'])

        # If no set ID is provided, use our name. Same thing for labels.
        # The somewhat awkward use of get here is because we want to treat
        # an empty string the same as a missing element.
        self.set = spec['set'] if spec.get('set', None) else self.name
        self.label = spec['label'] if spec.get('label', None) else self.name

        # If no sdef is provided, assume we're an array of primitives.
        self.sdef = sdef if sdef else self._init_primitive_structdef(spec)

    def _init_primitive_structdef(self, spec):
        sdef_single_field = {
            "id":       "value",
            "label":    spec['name'],
            "size":     spec['stride'],
            "type":     spec['type'],
            "subtype":  "",
            "display":  "",
            "order":    "",
            "info":     "",
            "comment":  ""
        }
        return romlib.StructDef(spec['name'], [sdef_single_field])

    def read(self, rom):
        """ Read a rom and yield structures from this array.

        rom: A file object opened in binary mode.
        """
        for i in range(self.length):
            pos = self.offset + (i * self.stride)
            yield romlib.Struct(self.sdef, rom, offset=pos)

