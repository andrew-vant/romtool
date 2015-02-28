# romtool/romlib

A game-independent ROM-editing API.

(and a simple frontend for using it)

## What is this?

Some people like to modify old games from the Age of Cartridges. Some games have tools available for exactly that, such as [Lunar Magic](http://fusoya.eludevisibility.org/lm/index.html) for Super Mario World. Such tools are usually for some specific game and do not work for other games.

There are some tasks that are common to *any* game, though. For example, the format of binary data structures may differ from one ROM to another, but the act of digging that structure out and putting it in a form someone can use is universal. Reading a string is not fundamentally different from one game to another, either. 

romlib is an attempt to collect game-independent functionality into an API and a very basic patch-making tool. The idea is to make simple hacks possible for non-programmers, and provide a useful set of primitives for more complex game-specific hacking tools.

It *does* need to be told where to find the data it is going to extract or patch. For this it needs a "rom map", which at the moment is a set of .csv files specifying the location and format of the data structures in the ROM. My hope is that maps for romlib can eventually serve as thorough, standardized documentation of how different games' internals are structured.

romlib and romtool are still very, very alpha. At the moment it mainly converts data tables from a rom into csv files, which the user can then edit in any spreadsheet program and then generate an IPS patch from their changes. This functionality is most likely to be useful for balance patches to RPGs and other statistics-heavy games. The program is smart enough to assemble multiple related data tables into joint objects, and also to attach the appropriate name strings to them, as long as the necessary locations and relations are included in the map. 

Some additional features that have not been added yet, but that I want to support. This isn't a complete list, just the things that come to mind as I am writing:

* String editing
* Patch merging
* Patch textualization
* ROM expansion
* Binary diffs
* Code assembly/disassembly
* ROM header removal
* Game documentation generation
  - monster/item/equipment lists
  - information for romhackers
* Alternate input and output formats
  - More than just csv for maps.
  - More than just IPS for patches
  - Conversion from one patch format to another
* Archaeological tools
  - working out text encodings
  - locating strings
  - locating data arrays

## Installing

"Proper" installation isn't quite ready yet. To set it up by hand: 

1. Install Python 3.4 or above. Older versions of Python 3 may work. Python 2 definitely won't.
2. Install bitstring and patricia-trie via pip.
3. Clone this repo or download/unpack the zip.
4. For Windows systems:
  1. Add the directory containing romtool to PATH.
  2. Add .py to PATHEXT
5. For Linux systems:
  1. Symlink romtool.py somewhere in your path, probably at /usr/local/bin/romtool (if you have root access) or ~/bin/romtool (if you don't)
6. For Mac/BSD/Anything else:
  1. I have no idea, sorry.
7. Profit.

## Usage

You can get help at any time with `romtool -h` or `romtool <subcommand> -h`.

Right now romtool does only two things: Dump information from the ROM to spreadsheets for editing, and create IPS patches from changes to those spreadsheets. Only a few games are directly supported, although in theory anyone can create a map for an unsupported game.

The following command will extract all known data from the ROM named some_game.smc, and save it as .csv files in datafolder. Each file contains a list of entities; for example, there may be a monsters.csv containing information about monsters, or a characters.csv with character stats.

```
romtool dump some_game.smc datafolder
```

Note that you do not need to specify which rom map to use; romtool will attempt to autodetect it. If autodetection fails, it will complain. You can force it to use a map in a particular folder by appending `-m <pathtomap>`.

After dumping is finished, make whatever changes you want to the files in `datafolder`. Any spreadsheet application should do the job; I use LibreOffice, but Excel should also work. When saving your changes, be sure you save in .csv format, *not* .xls, .ods, or anything else.

There are some limits to what you can change. For example, if a monster's attack power is stored in the ROM as a single byte, you cannot give it >255 attack (the maximum single-byte value). Romtool should complain if you attempt to make a patch containing invalid values, but the necessary checks aren't implemented yet. Caution advised.

When you're done making changes, do this:

```
romtool makepatch some_game.smc datafolder some_game.ips
```

That will create an IPS patch containing your changes. It should be given the same name as the ROM, but with a .ips extension (this will probably be the default in future versions). The reason the name should match is that it will cause some emulators (ZSNES at least, probably others) to implicitly make use of it, without physically modifying the original ROM. 

To test your patch, fire up an emulator and point it to the ROM. Assuming the emulator supports implicit patching and your patch is named correctly, you should see your changes in-game.

## Troubleshooting

**Q. ROM map detection failed. Why?**

Possible causes:

1. There may not be an available map for your ROM. At the moment only a few games are supported. If there isn't an existing map, you will have to create your own. I haven't written documentation for this process yet.
2. You may have an SNES ROM with an SMC header. At the moment, only headerless ROMs are supported. Remove the header and try again (eventually romtool will be able to do this for you).
3. The ROM may have been physically modified, perhaps by applying a patch to the file instead of relying on an emulator's implicit patching. If you are trying to dump data from a modified ROM, you can specify a map with the -m option. You should not try to generate a patch using a modified ROM; your patch will not work for anyone using the original ROM. Get a clean copy.

**Q. The changes in my patch don't show up in-game.**

1. Your patch may be named incorrectly. It should have the same filename as the ROM, but with a .ips extension.
2. Your emulator may not support implicit patching. Either physically apply the patch (romtool will support this eventually, but KEEP A CLEAN COPY), or use an emulator that does support it. Here is a list of emulators known to support implicit patching:
    * ZSNES
