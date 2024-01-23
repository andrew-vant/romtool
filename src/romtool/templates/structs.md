<p>The fields for each data structure.</p>

<p>Some fields are smaller than one byte; in such cases, the
offset and size are expressed in bits instead. Bits are numbered in
lsb0 order -- that is, bit 0 is the least-significant bit of the first
byte, bit 8 is the least-significant bit of the second byte, and so
on.</p>

<p>Some fields are pointers to other objects, typically strings. In
these cases the target’s offset is expressed in terms of the
pointer.</p>

<p>’Origin’ indicates what the offset is relative to. Typically this is
the start of the structure, but sometimes (typically for pointer
targets) it is from the start of the ROM. In the latter case the origin
is given as ‘root’.</p>

<p>’Ref’ indicates that the field’s value references an item in another
table.</p>
