# romtool

A game-independent ROM-editing API.

(and a simple frontend for using it)

## What is this?

Some people like to modify old games from the Age of Cartridges. Some
games have tools available for exactly that, such as [Lunar Magic][lm] for
Super Mario World. Such tools are usually for some specific game and do
not work for other games.

There are some tasks that are common to *any* game, though. For example,
the format of binary data structures may differ from one ROM to another,
but the act of digging that structure out and putting it in a form
someone can use is universal. Reading a string is not fundamentally
different from one game to another, either.

**romtool** is an attempt to collect game-independent functionality into
an API and a very basic patch-making tool. The idea is to make simple
hacks possible for non-programmers, and provide a useful set of
primitives for more complex game-specific hacking tools.

Here are some things you can do with it that might be useful:

- Inspect ROM data tables, e.g. monster stats, dialogue strings, or
  spell lists. This is useful for creating guides or just understanding
  a game.
- Edit the same in a spreadsheet, then make a patch implementing the
  changes. This is useful for balance patches to RPGs and other
  statistics-heavy games.
- Version-control rom hacking projects. Romtool's dump format is TSV,
  and it can generate patches from several different text-based input
  formats. All are friendly to version control tools.
- Merge multiple existing patches together. Useful for players who want
  to pick and choose features from several unrelated hacks.
- See what an existing patch actually does. Useful for reverse
  engineering patches from authors who didn't document them.
- Examine and manipulate ROM headers. Useful for identifying or
  organizing ROMs.

Romtool isn't magic; it does need to be told where to find the data it is
going to extract or patch. For this it needs a "rom map", which at the
moment is a set of TSV files specifying the location and format of the
data structures in the ROM, and the relationships between them. My hope
is that maps for romtool can eventually serve as well-defined,
machine-readable documentation of how different games' internals are
structured.

Romtool is late-alpha/early-beta. It's *probably* usable, but its
behavior may still change before a 1.0 release. While the commands
documented in this file work as described, other commands listed in
`romtool --help` may not.

## Installation

There is a packaged installer available for Windows (FIXME: link here).

On Linux, for now, install from pip: `pip install romtool`. Be aware
that you may need to have a C compiler installed for `pip install` to
work, as romtool has at least one dependency (bitarray) that does not
provide pre-built wheels.

Sometime before v1.0, I intend to arrange .deb and .rpm packages. The
main blocker for this are dependencies that do not themselves provide
packages.

For development installs, see CONTRIBUTING.md.

The installation process should place the `romtool` command somewhere in
your PATH, but I don't trust this yet and would like feedback. If
`romtool --help` prints usage instructions, you're good to go.

## Tutorial

**NOTE**: This tutorial uses *7th Saga* for its examples, because at
time of writing it has the most complete support. If you want to follow
along, you will need a copy of the *7th Saga* ROM, preferably in a
directory by itself.

### Identifying a ROM

Before trying to do anything, you probably want to check that your ROM
is supported. `romtool ident` will look at a ROM and print some
identifying information about it:

```console
user@host:~$ romtool ident 7thsaga.smc
name:       7th Saga, The (USA)
file:       7thsaga.rom.smc
type:       snes
size:       1572864
crc32:      B3ABDDE6
sha1:       8d2b8aea636a2239805c99744bf48c0b4df8d96e
md5:        a42772a0beaf71f9256a8e1998bfe6e3
supported:  yes
map:        /path/to/romtool/maps/7th Saga, The(US)
```

For now, the important fields here are `name`, `supported`, and `map`.

The `name` field will tell you if romtool can correctly identify
your ROM.

The `supported` field indicates whether romtool can find a map of the
ROM. A *map* is a set of files that tell romtool where to find things
like monster data, spell data, text, and the like. If `supported` is
*no*, only very basic commands will work. Romtool ships with maps for
only a few games, so far, but it is possible to create your own.

If a map is found, the `map` field will show where it is. This is useful
if you want to see how maps work, or to create your own.

For now, romtool ships with maps for only a few games. You can look in
the parent of the `map` directory to see which games.

### Dumping ROM data

`romtool dump` extracts data tables from a ROM, and is usually the next
thing you'll want to try. The following example will find all known data
tables in `7thsaga.smc`, translate them into TSV files, and put those
files in `mod_directory`:

```console
user@host:~$ romtool dump 7thsaga.smc mod_directory
user@host:~$ ls mod_directory
armor.tsv       dropsets.tsv  monsters.tsv  spells.tsv
characters.tsv  items.tsv     scripts.tsv   weapons.tsv
```

In this example, the output files contain lists of the game's weapons,
armor, monsters, items, etc.

The files thus created are plain-text files of tab-separated values.
They can be opened in any spreadsheet program. I use LibreOffice.

### Modifying data tables

**WARNING**: If possible, disable any auto-formatting or auto-correct
features your spreadsheet program provides before proceeding. They
*will* get in your way.

You can now edit the files created in the previous section. Change a
monster's HP, or a weapon's attack value, or a name. Note that there are
usually limits to what you can change. For example, if a monster's attack
power is stored in the ROM as a single byte, you cannot give it \>255
attack (the maximum single-byte value). If you're lucky, romtool will
notice the problem and complain. Not so lucky, and it will cheerfully
make a patch that breaks the game.

For the most part, as long as you limit any values you change to within
the range of values used by the game, they should work.

**WARNING**: When saving your changes, be sure you save them in-place,
in .tsv format, *not* .xls, .ods, .csv, or anything else.

When you're done making changes, do this to preview the patch:

```console
user@host:~$ romtool build 7thsaga.smc mod_directory
PATCH
006263:0001:FF
006265:0001:FF
006272:0002:B2C2
0062FE:0008:01050E0C10221B15
006307:0006:21161C1E1D23
00630E:0000:000F:1
EOF
```

This prints out a textual representation of an IPS patch. If you are not
familiar with the IPS format, it will look like gibberish, but that's
okay. The main thing you want to check is the output's length; if you
made a small change but get a huge patch, something is probably wrong.

If it looks okay, you can build the actual patch with:

```console
user@host:~$ romtool build 7thsaga.smc mod_directory --out 7thsaga.ips
```

That creates an IPS patch named `7thsaga.ips` implementing your changes.
Give the patch the same name as the ROM, but with a .ips extension; this
will allow some (most?) emulators to automatically make use of it,
without physically modifying the original ROM.

### Seeing Your Changes in Action

Now you can fire up your emulator of choice and load the ROM. If the
emulator supports implicit patching, and if your patch is named
correctly, you should see your changes in-game.

## Other Features

### Changeset Files

Editing spreadsheets isn't the only way to generate a patch. Romtool
also accepts *changeset files* -- YAML or JSON formatted descriptions of
changes to make.

The main advantage of changeset files is self-documentation. You can
tell at a glance what a they will do. In contrast, it's easy to lose
track of changes you've made to a spreadsheet. Also, changesets can be
written in a standard text editor, so you don't have to fight with
spreadsheet autoformat "features".

Their main disadvantage is the need to remember the names of object
types and their properties. These are specified in the map files for
each ROM. Also, you must understand YAML or JSON syntax to write
changesets effectively.

Here is a YAML example:

```yaml
# changeset.yaml
characters:   # Top-level keys indicate the table to change
  Esuna:      # Second-level keys are the name or table-index of an object
    hp: 200   # Third level are the object properties to change
    mp: 200
    spd: 50   # This will make Esuna considerably stronger out the gate
monsters:
  Hermit:
    hp: 500   # But so are the Hermit monsters found near the start
```

The preceding changeset can be supplied to `romtool build` instead of a
directory. The resulting patch will do exactly what you expect:

```console
user@host:~$ romtool build 7thsaga.smc changeset.yaml
PATCH
006263:0001:C8
006265:0001:C8
00626A:0001:32
0078DD:0002:F401
EOF
```

### Viewing Patches

IPS patches are binary, thus annoying to inspect. You can convert them
to a readable text format like this:

```console
user@host:~$ romtool convert patch.ips patch.ipst
```

Romtool's `.ipst` format is a textual representation of IPS. You can
read it in a standard text editor. If you are familiar with the IPS
format, you can also change it and then convert it back.

### Feature Wishlist

Here are some additional features that have not been added yet, but that
I want to support. This isn't a complete list, just the things that come
to mind at time of writing:

- ROM expansion
- Empty-space search
- Game documentation generation
  - monster/item/equipment lists (for players)
  - data table specs (for romhackers)
- Alternate input and output formats
  - More than just tsv for maps.
  - More than just IPS for patches
- Archaeological tools
  - working out text encodings
  - locating strings
  - locating data arrays

## Supported Games

You can see the maps that ship with romtool [here][maps]. Their
completeness varies.

## Troubleshooting

Note that you can get help at any time with `romtool --help` or `romtool
{subcommand} --help`. Trust the help output more than this section,
because I may forget to update it from time to time.

You can add `--verbose` to any command to show more information about
what is happening.

Notes on specific common issues follow.

**romtool: command not found (or not recognized, etc)**

The directory romtool was installed to isn't in your PATH. You'll have
to add it. On linux, this is probably `$HOME/.local/bin`. On windows, it
is `%LOCALAPPDATA%\Programs\Python\PythonXY\Scripts`.

**Q. ROM map detection failed. Why?**

Possible causes:

1. There may not be an available map for your ROM. At the moment only a
   few games are supported out of the box. If there isn't an existing
   map, you will have to create your own. I haven't written
   documentation for this process yet, but looking at the contents of
   the data/maps directory in the repo will probably be informative.
2. You may have an SNES ROM with an SMC header. The header changes the
   sha1 hash of the rom, which is what romtool uses to identify it.
   Remove the header and try again (eventually romtool will be able to
   do this for you).
3. The ROM may have been physically modified, perhaps by applying a
   patch to the file instead of relying on an emulator's implicit
   patching. If you are trying to dump data from a modified ROM, you
   can specify a map with the -m option.

**Q. My system doesn't know what program to use to open .tsv files.**

The tsv file type may not be associated with anything. The method for
associating filetypes differs by OS. On Windows 7 you can do it from the
file properties; look for "Opens With \<something>" followed by a button
marked 'Change'. Other Windows versions should be pretty similar. On
Linux you're on your own, but you probably Googled the answer before you
got here anyway.

**Q. The changes in my patch don't show up in-game.**

1. Your patch may be named incorrectly. It should usually have the same
   filename as the ROM, but with a .ips extension.
2. Your emulator may not support implicit patching. Either physically
   apply the patch with `romtool apply`, or use an emulator that does
   support it. Here is a list of emulators known to support implicit
   patching:

   - ZSNES
   - snes9x
   - FCEUX (name as romname.nes.ips instead of romname.ips)
   - FIXME: Add more here....

**Q. My patch changes produce garbage.**

Probably your spreadsheet application's autoformat function is trying to
be smart. Turn it off.

**Q. I already have a modified ROM and want to make a patch from it.**

Do this:

```sh
romtool diff original.rom modified.rom -o patch.ips
```

**Q. I have an IPS patch and want to see what's in it.**

Do this:

```sh
romtool convert patch.ips patch.ipst
```

## Writing New Maps

**TODO**

Notes on creating map files properly go here...

Notes: the various map spec files may have any number of extra columns
not used by romtool. This is intentional; extensions or client
applications can implement UI hints by looking for extra columns in the
spec.

(there probably needs to be a convention for app-specific columns vs
extension columns vs official columns...)

## Useful Tools

* [fasm][], with an accompanying [macro set][fm], can translate 6502
  (NES) assembly snippets into something you can put in a patch.
* [fasmg][], its successor, also has macro sets for a number of
  languages, including [6502][fgm].

TODO: give romtool a way to take an asm file, pass it to fasm, and
produce a patch inserting the result at a given offset.

TODO: detect and optionally download external tools. No installable
packages for fasmg (yet) or the macro sets (probably ever).

[lm]: http://fusoya.eludevisibility.org/lm/index.html
[maps]: ./src/romtool/maps
[py]: https://www.python.org/downloads/
[git]: https://git-scm.com/downloads
[fasm]: https://flatassembler.net/download.php
[fasmg]: https://flatassembler.net/download.php
[fm]: https://board.flatassembler.net/topic.php?t=16366
[fgm]: https://board.flatassembler.net/topic.php?t=19389
