Equipment names appear as a long list of contiguous null-terminated
strings. The game appears to find name N by scanning through strings
until passing N string terminators. It is not clear whether it starts
the scan from the beginning of the global name table or the
part of the table specific to the type of thing being looked up -- i.e.
I’m not whether shortening, say, the weapon list, will throw off
whatever looks up armor names.

Monsters should be safe because there are no strings immediately
following the monster list.
