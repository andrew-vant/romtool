import logging
from itertools import islice

from romtool.rom import INESRom
from romtool.field import Field
from romtool.structures import Table
from romtool.util import RomObject

log = logging.getLogger(__name__)

class Rom(INESRom):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        spec = self.map.tables.mnames
        log.debug("Replacing mnames table")
        self.tables.mnames = Names(self, self.data, spec)


class Names(Table):
    def __iter__(self):
        rom = self.root
        return (' '.join(nm_parts) for nm_parts
                in zip(rom.tables.nm1_monsters, rom.tables.nm2_monsters))

    def __getitem__(self, i):
        if isinstance(i, slice):
            return SequenceView(self, i)
        return next(islice(self, i, None))

    def __setitem__(self, i, v):
        nm1, _, nm2 = v.partition(" ")
        self.root.tables.nm1_monsters[i] = nm1.strip()
        self.root.tables.nm2_monsters[i] = nm2.strip()


class MonsterName(Field):
    """ Virtual field extracting a monster's full name

    Internally, names are stored as two separate 'words', in which the second
    word is often empty.
    """
    def read(self, obj, cls=None):
        return ' '.join(obj.name1, obj.name2).strip()

    def write(self, obj, value):
        first, _, last = value.partition(" ")
        obj.name1 = first.strip()
        obj.name2 = last.strip()

MAP_TABLES = {'mnames': Names}
