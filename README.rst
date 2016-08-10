romtool/romlib
==============

A game-independent ROM-editing API.

(and a simple frontend for using it)

What is this?
-------------

Some people like to modify old games from the Age of Cartridges. Some
games have tools available for exactly that, such as `Lunar
Magic <http://fusoya.eludevisibility.org/lm/index.html>`__ for Super
Mario World. Such tools are usually for some specific game and do not
work for other games.

There are some tasks that are common to *any* game, though. For example,
the format of binary data structures may differ from one ROM to another,
but the act of digging that structure out and putting it in a form
someone can use is universal. Reading a string is not fundamentally
different from one game to another, either.

romlib is an attempt to collect game-independent functionality into an
API and a very basic patch-making tool. The idea is to make simple hacks
possible for non-programmers, and provide a useful set of primitives for
more complex game-specific hacking tools.

It *does* need to be told where to find the data it is going to extract
or patch. For this it needs a "rom map", which at the moment is a set of
.tsv files specifying the location and format of the data structures in
the ROM. My hope is that maps for romlib can eventually serve as
thorough, standardized documentation of how different games' internals
are structured.

romlib and romtool are still very, very alpha. At the moment it mainly
converts data tables from a rom into tsv files, which the user
can edit in any spreadsheet program and then generate an IPS patch from
their changes. This functionality is most likely to be useful for
balance patches to RPGs and other statistics-heavy games. The program is
smart enough to assemble multiple related data tables into joint
objects, and also to attach the appropriate name strings to them, as
long as the necessary locations and relations are included in the map.

Some additional features that have not been added yet, but that I want
to support. This isn't a complete list, just the things that come to
mind as I am writing:

-  ROM expansion
-  Header removal
-  Empty-space search
-  Game documentation generation
   -  monster/item/equipment lists
   -  information for romhackers
-  Alternate input and output formats
   -  More than just tsv for maps.
   -  More than just IPS for patches
-  Archaeological tools
   -  working out text encodings
   -  locating strings
   -  locating data arrays
-  Physical patch application.

Installation
------------

Romlib requires Python 3.4 or later.

I really want to have platform-native packages for the major operating
systems, but that's a ways in the future still. In the meantime, once Python
is installed, you can install romlib from Pip:

::

    pip3 install romlib

If you're looking to work on the code, you probably want to fork the repo on
github, then clone your fork and install from there:

::

    git clone git@github.com:yourghname/romlib.git
    cd romlib
    python3 setup.py develop

The installation process should place the ``romtool`` command somewhere in
your PATH, but I don't trust this yet and would like feedback.

Usage
-----

You can get help at any time with ``romtool -h`` or ``romtool <subcommand>
-h``. Trust the help output more than this section, because I may forget to
update it from time to time.

The following command will extract all known data from the ROM named
``some_game.smc``, and save it as .tsv files in ``moddir``. Each file
contains a list of entities; for example, there may be a monsters.tsv
containing information about monsters, or a characters.tsv with character
stats.

::

    romtool dump some_game.smc moddir

Note that you do not need to specify which rom map to use; romtool will
attempt to autodetect it. If autodetection fails, you can force it to use a
map in a particular folder by appending ``-m <pathtomap>``. If you are
developing a map of your own you will almost certainly need to do this.

After dumping is finished, make whatever changes you want to the files
in ``moddir``. Any spreadsheet application should do the job; I use
LibreOffice, but Excel should also work.

When saving your changes, be sure you save them in place in .tsv format, *not*
.xls, .ods, .csv, or anything else. It's probably a good idea to turn off
autocorrect or similar features, too.

There are some limits to what you can change. For example, if a
monster's attack power is stored in the ROM as a single byte, you cannot
give it >255 attack (the maximum single-byte value). If you're lucky, romtool
will complain. Not so lucky, and it will cheerfully make a patch that breaks
the game.

When you're done making changes, do this:

::

    romtool build -r some_game.rom -o some_game.ips moddir

That will create an IPS patch containing your changes. It should be
given the same name as the ROM, but with a .ips extension (this will
probably be the default in future versions). The reason the name should
match is that it will cause some emulators (ZSNES and SNES9x at least,
probably others) to automatically make use of it, without physically
modifying the original ROM.

If you want to view the binary changes the patch is going to make, name
the output file with a .ipst extension instead of .ips. This will create
a textualized representation of the ips patch that is readable in any
editor. Omitting ``-o some_game.ips`` will do the same thing, but instead
print the textualized representation to stdout.

To test your patch, fire up an emulator and point it to the ROM.
Assuming the emulator supports implicit patching and your patch is named
correctly, you should see your changes in-game.

If you have an existing, modified ROM and want to create an IPS patch
from it, you can do it this way:

::

    romtool diff original.rom modified.rom -o patch.ips

Troubleshooting
---------------

**Q. ROM map detection failed. Why?**

Possible causes:

1. There may not be an available map for your ROM. At the moment only a few
   games are supported out of the box. If there isn't an existing map, you
   will have to create your own. I haven't written documentation for this
   process yet, but looking at the contents of the data/maps directory in the
   repo will probably be informative.
2. You may have an SNES ROM with an SMC header. The header changes the sha1
   hash of the rom, which is what romlib uses to identify it.  Remove the
   header and try again (eventually romtool will be able to do this for you).
3. The ROM may have been physically modified, perhaps by applying a
   patch to the file instead of relying on an emulator's implicit
   patching. If you are trying to dump data from a modified ROM, you can
   specify a map with the -m option.

**Q. My system doesn't know what program to use to open .tsv files.**

The tsv file type may not be properly associated. The method for associating
filetypes differs by OS. On Windows 7 you can do it from the file properties;
look for "Opens With <something>" followed by a button marked 'Change'. Other
Windows versions should be pretty similar. On Linux you're on your own, but you
probably Googled the answer before you got here anyway.

**Q. The changes in my patch don't show up in-game.**

1. Your patch may be named incorrectly. It should have the same filename
   as the ROM, but with a .ips extension.
2. Your emulator may not support implicit patching. Either physically
   apply the patch (romtool will support this eventually, but KEEP A
   CLEAN COPY), or use an emulator that does support it. Here is a list
   of emulators known to support implicit patching:

   -  ZSNES
   -  snes9x
   -  FCEUX (name as romname.nes.ips instead of romname.ips)

Map Files
---------

Notes on creating map files propertly go here...

Notes: the various map spec files may have any number of extra columns not
used by romlib.  This is intentional; extensions or client applications can
implement UI hints by looking for extra columns in the spec.

(there probably needs to be a naming convention for app-specific columns vs
extension columns vs official columns...)
