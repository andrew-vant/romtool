Targeting mode.

It is not clear whether this is intended as an enum or a bitfield. If it
is supposed to be a bitfield, then the bits would correspond to
enemy/ally, single/all, and map-only, and you could make a spell target
“all allies” by setting the two lowest bits. No existing spell does
that, and I don’t know if it works.
