import romlib
import logging
from itertools import chain
from bitstring import BitArray

# The effectivity field may be either a bitfield (representing either statuses
# or elements) or a scalar (representing spell power). Which it is depends on
# the spell routine the spell uses.

_statusbits = 'dspbtlmc'
_elembits = 'sptdfile'
_statusroutines = [0x03, 0x08, 0x12]
_elemroutines = [0x0A]

class effect(romlib.field.Union):
    @property
    def type(self):
        spelltype = self.parent.code
        if spelltype in chain(_statusroutines, _elemroutines):
            return "lbin"
        else:
            return "uint"

    @property
    def display(self):
        spelltype = self.parent.code
        if spelltype in _statusroutines:
            return _statusbits
        elif spelltype in _elemroutines:
            return _elembits
        else:
            return None

class equipment(romlib.field.Value):
    # It's helpful to separate equipment id from current equipped status
    @property
    def equipped(self):
        return self.data[0]

    @equipped.setter
    def equipped(self, equipped):
        self.data[0] = equipped

    @property
    def eid(self):
        return self.data[1:].uint + self.mod

    @eid.setter
    def eid(self, value):
        fmt = "bool={}, uint:7={}".format(self.equipped, value-self.mod)
        self.data = BitArray(fmt)

    @property
    # weapon and armor id get/set, doesn't touch equipped
    def value(self):
        return self.eid

    @value.setter
    def value(self, value):
        assert False
        self.eid = value

    @property
    def string(self):
        e = "E-" if self.equipped else "U-"
        eid = str(self.eid) if self.eid >= 0 else "None"
        return e + eid

    @string.setter
    def string(self, s):
        self.equipped = s.startswith("E-")
        s = s[2:]
        self.eid = -1 if s == "None" else int(s)
