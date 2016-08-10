# At the end of the monster structure are up to three optional fields
# pointing to their loot table, combat script, and resistances. Each set is a
# one-byte integer type indicator followed by a two-byte pointer. The type
# indicator has three known values: 0x03 (drop pointer), 0x07 (script pointer),
# and 0x08 (resist pointer). 0x00 means stop.
#
# Monsters with no drop pointer never drop anything; monsters with no script
# pointer only attack; monsters with no resist pointer have neutral resists.
#
# I am not sure what to do if a different type indicator is encountered. One
# possibility is to throw an exception, but that precludes experimenting with
# other values. A second possibility is to log a warning and treat it as if it
# were a stop marker. A third is to continue onward and store the pointer as an
# unknown -- I am not sure if or whether that will break other things.
#
# When logging such warnings it should probably record the faulty type code and
# the location the pointer would have gone if it were valid, so one can
# manually investigate if desired.
#
# No, don't raise an exception, then you can't dump bugged monsters.
#
# FIXME: Is there a way to alter a logger within the main dump/load loop such
# that it can print the index of the monster being processed even if the
# function logging the message does not know it?

import logging
from pprint import pprint

codes = {0x03: "drop",
         0x07: "script",
         0x08: "resist"}

def make_struct(base):
    class monster(base):
        def read_extra(self, bs):
            nextcode = lambda: bs.read(8).uint
            for code in iter(nextcode, 0):
                pointer = bs.read(16).uintle
                if code not in codes:
                    msg = "Unknown monster pointer code: %s, targeting %s"
                    logging.warning(msg, code, pointer)
                    break
                self[codes[code]] = pointer # Always zero, bug.
    return monster
