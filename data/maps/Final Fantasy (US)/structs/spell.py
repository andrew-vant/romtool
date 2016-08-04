import romlib
from romlib import util
from itertools import chain

# The effectivity field may be either a bitfield (representing either statuses
# or elements) or a scalar (representing spell power). Which it is depends on
# the spell routine the spell uses.
_statusbits = 'dspbtlmc'
_elembits = 'sptdfile'
_statusroutines = [0x03, 0x08, 0x12]
_elemroutines = [0x0A]

def make_struct(fields):
    class spell(romlib.Structure, fields=fields):
        def postread(self, source):
            # Interpret effectivity.
            if self.code in _statusroutines:
                bits = self.effect.bin[::-1]
                self.effect = util.displaybits(bits, _statusbits)
            elif self.code in _elemroutines:
                bits = self.effect.bin[::-1]
                self.effect = util.displaybits(bits, _elembits)
            else:
                self.effect = self.effect.uint

        def postload(self):
            # Interpret effectivity.
            if self.code not in chain(_statusroutines, _elemroutines):
                self.effect = int(self.effect)

        def postbytemap(self, offset):
            # Interpret effectivity
            bytemap = {}
            effectivity_offset = offset + self.offset("effect")
            if self.code in _statusroutines:
                bytemap[effectivity_offset] = un
            if self.code in _statusroutines or self.code in _elemroutines:
                return {offset + self.offset("effect"): self.effect}
            else:
                return util.undisplaybits(self.effect)
    return spell

