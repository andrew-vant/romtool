import logging
from pprint import pprint
from functools import partial
from io import BytesIO

from bitstring import BitArray

from romlib.structures import Structure
from romlib.types import Field
from romlib.io import Unit
from romlib.util import HexInt


def monster_extras(monster):
    tail = monster.view[33:33+9:Unit.bytes]
    for i in range(3):
        extype = tail.bytes[0]
        if not extype:
            return
        data_view = tail[i*3+1:i*3+3:Unit.bytes]
        yield extype, data_view

class MonsterOptionPointer(Field):
    """ Field used for monster "tail options"

    At the end of the monster structure are up to three optional fields
    pointing to their loot table, combat script, and resistances. Each set is a
    one-byte integer type indicator followed by a two-byte pointer. The type
    indicator has three known values: 0x03 (drop pointer), 0x07 (script pointer),
    and 0x08 (resist pointer). 0x00 means stop. The fields, if present, always
    appear in this order.

    Monsters with no drop pointer never drop anything; monsters with no script
    pointer only attack; monsters with no resist pointer have neutral resists.
    """

    handles = ['mptr']
    excode = {'sptr': 0x07,  # script pointer
              'rptr': 0x08}  # resists pointer

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
    # FIXME: Is there a way to alter a logger within the main dump/load loop such
    # that it can print the index of the monster being processed even if the
    # function logging the message does not know it?

    def read(self, obj, objtype=None):
        ptr = next((view.uintle for extype, view
                    in monster_extras(obj)
                    if extype == self.excode[self.id]),
                    0)
        return HexInt(ptr, 2*Unit.bytes)

    def write(self, obj, value):
        view = next((view for extype, view
                     in monster_extras(obj)
                     if extype == self.excode[self.id]),
                     None)
        if not view:
            msg = ("Can't add script pointers to a monster (yet)")
            raise NotImplementedError(msg)
        elif value is None:
            msg = ("Can't remove script pointers from a monster (yet)")
            raise NotImplementedError(msg)
        view.uintle = value

    def parse(self, string):
        raise NotImplementedError


class MonsterDrop(Field):
    handles = ['drop']
    excode = 0x03

    def read(self, obj, objtype=None):
        view = next((view for extype, view
                     in monster_extras(obj)
                     if extype == self.excode),
                     None)
        if not view:
            return None
        size = self.size.eval(obj) * self.unit
        return view[:size].uint

    def write(self, obj, value):
        raise NotImplementedError

    def parse(self, string):
        raise NotImplementedError


class MonsterDropChance(Field):
    handles = ['dchance']
    excode = 0x03

    def read(self, obj, objtype=None):
        view = next((view for extype, view
                     in monster_extras(obj)
                     if extype == self.excode),
                     None)
        size = self.size.eval(obj) * self.unit
        if not view:
            return None
        # FIXME: for some reason slicing-to-end-of-view is not working as I
        # expect it to here, and I'm not sure why.
        start = len(view) - size
        end = len(view)
        return view[start:end].uint

    def write(self, obj, value):
        raise NotImplementedError

    def parse(self, string):
        raise NotImplementedError
