import romlib
from itertools import chain

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
