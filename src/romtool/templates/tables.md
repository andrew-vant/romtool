<p>For tables without an index, ‘offset’ is relative to the start of the
ROM, and indicates the location of the zeroth item in the table. The
offset of the Nth item will be <code>offset + (N * stride)</code>, where
N starts at zero.

<p>For tables with an index, ‘offset’ is added to the index values to
convert them to ROM offsets. Hence, the offset of the Nth item is
<code>offset + index[N]</code>. The stride is informational
only.</p>

<p>FIXME: (it occurs to me that the offset calculation could be unified
as <code>offset(table[N]) = table.offset + index[N] + N *
table.stride</code>, where stride is 0 for indexed tables and index[N]
is 0 for non-indexed tables.)</p>
