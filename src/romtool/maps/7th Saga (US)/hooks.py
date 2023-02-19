import logging
from functools import lru_cache

from romtool.rom import SNESRom
from romtool.structures import Table

class Rom(SNESRom):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        spec = self.map.tables.loot
        self.tables['loot'] = ObjectTable(
                self,
                self.data,
                spec,
                self.tables[spec.index],
                )



class ObjectTable(Table):
    """ Collective table for inventory objects

    The weapon, armor, and item table indexes are consecutive, and collectively
    form one big table. Item cross-references are often indices to the overall
    table rather than a particular subset, making resolving them difficult; a
    reference to table index #30 is an item, while a reference to table index
    #104 is a weapon.

    This virtual table forwards such cross-references to the appropriate
    sub-table.
    """
    def _subtables(self):
        return (self.root.entities[k] for k in ('items', 'weapons', 'armor'))

    def _target(self, i):
        # Get the subtable and subindex for a given index
        if i < 0 or i >= len(self):
            raise IndexError(f"Object #{i} is out of range")
        for subtable in self._subtables():
            if i < len(subtable):
                return subtable, i
            else:
                i -= len(subtable)
        assert False  # shouldn't happen

    def __len__(self):
        return sum(len(tbl) for tbl in self._subtables())

    def __getitem__(self, i):
        subtable, i = self._target(i)
        return subtable[i]

    def __setitem__(self, i, v):
        subtable, i = self._target(i)
        subtable[i] = v
