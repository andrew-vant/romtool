""" Romtool hooks for 7th Saga. """

from romtool.structures import Table
from romtool.util import ChainView


class LootTable(Table):
    """ Loot table wrapper.

    The weapon, armor, and item indexes are consecutive, and collectively
    form one big table. Item cross-references are often indices to the
    overall table rather than a particular subset, making resolving them
    difficult; a reference to table index #30 is an item, while a
    reference to table index #104 is a weapon.
    """
    @property
    def _sources(self):
        sources = [self.root.entities[k]
                   for k in ['items', 'weapons', 'armor']]
        return ChainView(*sources)

    def __getitem__(self, i):
        return self._sources[i]

    def __setitem__(self, i, v):
        self._sources[i] = v
