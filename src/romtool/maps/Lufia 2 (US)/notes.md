Method to get changed monster data into same space:

Let map override array bytemap. Write standard data for each item; reserve
bytes at the end for pointers as needed, but don't specify them.

At end of monster data, write each unique resist/ai script and record its
address (maybe hash the data and map hash->address?). Then go back and update
the pointers for each monster to point to the appropriate resist or script.

I *think* that, when run against the base game, this will result in array data
of the same length as the original data, but with all pointer targets at the
end. This will result in an unnecessarily large but stable patch. I don't
think there's a good way to keep lufia patches small, unless there is empty
space at the end of the array -- in that case we can put changed items in
empty space and update the index to point to them, which makes much smaller
patches, but wastes space.

Maybe figure out how much space there is, and if there is, do the small patch
method if possible and revert to the compact data method if needed.

The trouble with complicated patches on simple changes is that it's hard to be
sure they're doing only what you want. Possible solution: Generate the clunky
patch, apply it to a temporary file or overlay, dump that version, diff the
two.

More general solution for sanity checking maps: Verify that *either* 1. no
changes = empty patch, or 2. no changes = patch that, when applied and
re-dumped, diffs identical to original. Doing 2 will by definition also do 1,
but doing 1 first makes for more efficient testing if needed.

This sanity check doesn't deal with items writing out of dump range by
accident. Possibility: Add `end` property to arrays, supplying the first
address past the end of the array. In the default array bytemapper, raise an
exception if any non-pointer value is mapped beyond `end` or before `offset`.
`end` defaults to offset + size * length + 1. Main difficulty: I'm not sure
the array bytemapper knows which values are pointers and which are not. Pretty
sure that information is lost when the struct does its own bytemapping.

Maybe the struct should return metadata about the bytemap its generating? But
what might we need to know?
