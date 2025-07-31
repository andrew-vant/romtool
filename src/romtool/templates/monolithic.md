# {{ rom.name }} ROM Documentation

This document describes the ROM data structures for "{{ rom.name }}",
and includes a dump of all data thus described. The descriptions and the
dump are derived from the same underlying code and definitions; to the
extent that the dump is correct, the structure specs should be too.

If you are writing a tool to edit the game, start here, at the top. If
you simply want to see what's in the game data, you can skip ahead to
the [Data Dump](#data-dump) section.

## Data Table Locations

The following data tables exist in the ROM.

For tables without an index, ‘offset’ is relative to the start of the
ROM data, and indicates the beginning of the table. The offset of the
Nth item will be `offset + (N * stride)`, where N starts at zero.

For tables with an index, ‘offset’ is added to the index values to
convert them to ROM offsets. The offset of the Nth item will be
`offset + index[N]`.

Multiple tables may contain data for the same set of logical entities.
In this case they will have the same ‘group’ in the list below.

The ‘type’ field and its possible values are described in the following
section.

**A note on offsets**: All offsets are relative to something. Most of
the offsets in this document are relative to the beginning of the ROM
data. If your ROM has a header, you can convert ROM offsets to file
offsets by adding the length of the header.


{{ rom }}

## Data Types

### Primitives

Most data structures have several fields; most of those fields are
either integers or strings.

Integers may be signed or unsigned, and if they are larger than one
byte, they may be big-endian (most significant byte first) or
little-endian (least-significant byte first). Big-endian is how most
people write numbers; little-endian is more common in ROM data. This
document sometimes uses hexadecimal notation for integers where it makes
sense to do so, e.g. for pointers.

Character strings may have a fixed length, or they may have a terminator
byte indicating the end of the string (typically 0).

These are the primitive-type variants that may appear in structure
fields below:

int
: Signed integer.

uint
: Unsigned integer, single-byte.

uintbe
: Unsigned integer, bit-endian.

uintle
: Unsigned integer, little-endian.

nbcd
: Natural binary-coded decimal integer, single-byte.

nbcdle
: Natural binary-coded decimal integer, little-endian.

nbcdbe
: Natural binary-coded decimal integer, big-endian.

bytes
: Raw bytes.

bin
: Array of single bits, each of which may be 1 or 0.

str
: Fixed-length character string.

strz
: Terminated character string.

### Bitfields

Bitfields are sets of single-bit flags grouped together. In the
following, the bits in each field are numbered in lsb0 order unless
otherwise stated. That is, bit 0 is the least-significant bit of the
first byte, bit 8 is the least-significant bit of the second byte, and
so on.

Each bit is assigned a letter as a mnemonic label. The letters are used
as a shorthand in the data dumps when multiple bits are set.

{%- for name, struct in rom.map.bitfields.items() %}

#### {{ name | title }}

{{ struct }}

{%- endfor %}

### Structures

These are the known data structure types and their fields. Fields may be
smaller than one byte; in such cases, the offset and size are expressed
in bits instead. Bits are again numbered in lsb0 order.

Fields may be pointers to other objects. In such cases the target’s
offset is expressed in terms of the pointer.

Some fields are indexes of an object in another table. The `ref` column,
if present, specifies which other table.

{%- for name, struct in rom.map.structs.items() %}
{%- if struct not in rom.map.bitfields.values() %}

#### {{ name | title }}

{{ struct }}

{%- endif %}
{%- endfor %}

## Data Dump

These are lists of all known data in the ROM. This section is
meant for players; where possible, related tables have been joined,
and integer cross-references rendered as object names.

Each dataset is also available in .tsv format, which you can open
in most spreadsheet applications.

{%- for name, dataset in rom.entities.items() %}

### {{ name | title }}

{{ dataset }}

{%- endfor %}

## Raw Tables

These are the data tables as they appear in the ROM, without joining
into logical objects. The offsets given for each entry are relative to
the start of the ROM data. If your ROM has a header, the absolute offset
in the file will differ.

This is probably only useful if you are hand-hacking in a hex
editor.

{%- for table in rom.tables.values() %}
{%- if table not in rom.indexes %}

### {{ table.name }}

{{ table }}

{%- endif %}
{%- endfor %}

## References

### Glossary

**TODO**: This section to contain romhacking jargon definitions.

{%- if rom.map.meta.credits %}

### Acknowledgments

Information in this document was gathered from or otherwise aided by the
following sources:
{% for name, link in rom.map.meta.credits.items() %}
* [{{ name }}]({{ link }})
{%- endfor %}
{%- endif %}
