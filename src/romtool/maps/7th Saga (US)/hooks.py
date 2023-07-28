import logging
from functools import lru_cache

from romtool.rom import SNESRom
from romtool.structures import Table
from romtool.util import ChainView

class Rom(SNESRom):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        spec = self.map.tables.loot
        # The weapon, armor, and item indexes are consecutive, and collectively
        # form one big table. Item cross-references are often indices to the
        # overall table rather than a particular subset, making resolving them
        # difficult; a reference to table index #30 is an item, while a
        # reference to table index #104 is a weapon.
        loot = ChainView(*[self.root.entities[k]
                           for k in ['items', 'weapons', 'armor']])
        self.tables['loot'] = loot
