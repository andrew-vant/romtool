import romlib
from romlib import util

# The effectivity field may be either a bitfield (representing either statuses
# or elements) or a scalar (representing spell power). Which it is depends on
# the spell routine the spell uses.
_statusbits = 'dspbtlm'
_elembits = 'sptdfile'
_statusroutines = [0x03, 0x08, 0x12]
_elemroutines = [0x0A]

def postread(self, source):
    # Interpret effectivity.
    if self.code in _statusroutines:
        self.effect = util.displaybits(self.effect.bin[::-1], 'dspbtlmc')
    elif self.code in _elemroutines:
        self.effect = util.displaybits(self.effect.bin[::-1], 'sptdfile')
    else:
        self.effect = self.effect.uint

def postload(self):
    # Interpret effectivity.
    if self.code not in _statusroutines and self.code not in _elemroutines:
        self.effect = int(self.effect)
