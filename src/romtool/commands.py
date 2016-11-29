import argparse
import sys
import hashlib
import logging
import os
import shutil
import textwrap
import itertools
from pprint import pprint
from itertools import chain
from importlib.machinery import SourceFileLoader

import yaml

import romlib
import romlib.charset
from romtool import util
from romtool.util import pkgfile

try:
    # Try to do the right thing when piping to head, etc.
    from signal import signal, SIGPIPE, SIG_DFL
    signal(SIGPIPE, SIG_DFL)
except ImportError:
    # SIGPIPE isn't available on Windows, at least not on my machine. For now
    # just ignore it, but I should probably test piping on windows at some
    # point.
    pass

class RomDetectionError(Exception):
    """ Indicates that we couldn't autodetect the map to use for a ROM."""
    def __init__(self, _hash=None, filename=None):
        self.hash = _hash
        self.filename = filename
    def __str__(self):
        return "ROM sha1 hash not in db: {}".format(self.hash)
    def log(self):
        logging.error("Couldn't autodetect ROM map for %s", self.filename)
        logging.error("%s", self)
        logging.error("The rom may be unsupported, or your copy may "
                      "be modified, or this may be a save file")
        logging.error("You will probably have to explicitly supply --map")

# FIXME: Add subcommand to list available maps on the default search paths.
# Probably its output should advice the user that it's only what shipped with
# romtool and they're free to supply their own.

def detect(romfile, maproot=None):
    """ Detect the map to use with a given ROM.

    maproot -- A root directory containing a set of rom maps and a hashdb.txt
               file associating sha1 hashes with map names.
    """
    if maproot is None:
        maproot = pkgfile("maps")

    dbfile = os.path.join(maproot, 'hashdb.txt')
    with open(dbfile) as hashdb, open(romfile, "rb") as rom:
        # FIXME: Reads whole file into memory, likely to fail on giant images,
        # e.g cds/dvds.
        logging.info("Detecting ROM map for: %s.", romfile)
        romhash = hashlib.sha1(rom.read()).hexdigest()
        logging.info("sha1 hash is: %s.", romhash)
        try:
            line = next(line for line in hashdb if line.startswith(romhash))
        except StopIteration:
            raise RomDetectionError(romhash, romfile)
        name = line.split(maxsplit=1)[1].strip()
        logging.info("ROM map found: %s", name)
        return os.path.join(maproot, name)


def dump(args):
    """ Dump all known data from a ROM."""
    if args.map is None:
        try:
            args.map = detect(args.rom)
        except RomDetectionError as e:
            e.log()
            sys.exit(2)

    if args.include is not None:
        raise NotImplementedError("Autopatched dumps not implemented")
        # FIXME: Patch rom in-memory with an ips so you can dump a mod without
        # applying it.

    rmap = romlib.RomMap(args.map)

    # This gets awkward since we want to open ROM always but open SAVE
    # only sometimes. I suspect this means the design needs some work.
    # Can't they be loaded separately? (maybe not, saves may have
    # pointers to stuff in the rom that need dereferencing?)
    logging.info("Opening ROM file: %s", args.rom)
    with open(args.rom, "rb") as rom:
        if args.save:
            logging.info("Opening SAVE file: %s", args.save)
            with open(args.save, "rb") as save:
                data = rmap.read(rom, save)
        else:
            logging.debug("No save file specified, skipping")
            data = rmap.read(rom, None)

    logging.info("Dumping ROM data to: %s", args.moddir)
    output = rmap.dump(data)
    os.makedirs(args.moddir, exist_ok=True)
    for entity, dicts in output.items():
        filename = "{}/{}.tsv".format(args.moddir, entity)
        logging.info("Writing output file: %s", filename)
        try:
            romlib.util.writetsv(filename, dicts, args.force)
        except FileExistsError as err:
            logging.error(err)
            dest = os.path.abspath(args.moddir)
            logging.error("Aborting, dump would overwrite files in " + dest)
            advice = "(you can use --force if you really mean it)"
            logging.error(advice)
            sys.exit(2)

    logging.info("Dump finished")


def build(args):
    """ Build patches from a data set containing changes.

    Intended to be applied to a directory created by the dump subcommand.
    """
    # FIXME: Really ought to support --include for auto-merging other patches.
    # Have it do the equivalent of build and then merge.

    if args.map is None and args.rom is None:
        logging.error("At least one of -s or -m must be provided.")
        sys.exit(1)
    if args.map is None:
        try:
            args.map = detect(args.rom)
        except RomDetectionError as e:
            e.log()
            sys.exit(2)

    rmap = romlib.RomMap(args.map)
    msg = "Loading mod dir %s using map %s."
    logging.info(msg, args.moddir, args.map)
    data = rmap.load(args.moddir)
    source = "save" if args.save else "rom"
    patch = romlib.Patch(rmap.bytemap(data, source))
    _filterpatch(patch, args.rom)
    _writepatch(patch, args.patch)


def merge(args):
    """ Merge multiple patches.

    This can accept and merge changes from any number of existing patches and
    formats. Overlapping changes will produce a warning. Last changeset
    specified on the command line wins.
    """
    changeset = romlib.util.CheckedDict()
    for patchfile in args.patches:
        msg = "Importing changes from %s."
        logging.info(msg, patchfile)
        changeset.update(romlib.Patch.load(patchfile).changes)

    # Filter the complete changeset against a target ROM if asked.
    patch = romlib.Patch(changeset)
    _filterpatch(patch, args.rom)
    _writepatch(patch, args.out)


def convert(args):
    """ Convert one patch format to another.

    This is just syntactic sugar over merge.
    """
    args.patches = [args.infile]
    args.out = args.outfile
    args.rom = None
    merge(args)


def diff(args):
    """ Build a patch by diffing two roms.

    If someone has been making their changes in-place, they can use this to get
    a patch.
    """
    with open(args.original, "rb") as original:
        with open(args.modified, "rb") as changed:
            patch = romlib.Patch.from_diff(original, changed)
    _writepatch(patch, args.out)

def apply(args):
    """ Apply a patch to a file, such as a rom or a save.

    By default this makes a backup of the existing file at filename.bak.
    """
    # Move the target to a backup name first to preserve its metadata, then
    # copy it back to its original name, then patch it there.
    patch = romlib.Patch.load(args.patch)
    tgt = args.target
    _backup(args.target, args.nobackup)
    logging.info("Applying patch")
    with open(tgt, "r+b") as f:
        patch.apply(f)
    logging.warning("Patch applied. Note: You may want to run `romtool "
                    "sanitize` next, especially if this is a save file.")


def sanitize(args):
    """ Sanitize a ROM or save file

    This uses map-specific hooks to correct any checksum errors or similar
    file-level issues in a rom or savegame.
    """
    if args.map is None:
        try:
            args.map = detect(args.target)
        except RomDetectionError as e:
            e.log()
            sys.exit(2)
    rmap = romlib.RomMap(args.map)

    # Maps must supply sanitize_save and sanitize_rom hooks. If they're not
    # found, assume nothing needs to be done. FIXME: separate sanatization into
    # mandatory parts (e.g checksums) and linting (e.g. hp > max hp, oops).
    # Call the latter lint_save, lint_rom, etc.

    try:
        path = args.map + "/hooks.py"
        logging.info("Loading map hooks from %s", path)
        hooks = SourceFileLoader("hooks", path).load_module()
    except FileNotFoundError:
        logging.info("%s not present", path)
        logging.info("Nothing needs to be done")
        sys.exit(0)
    else:
        logging.debug("Done loading hooks.")

    if not args.type:
        args.type = "rom"
    funcname = "sanitize_" + args.type
    logging.info("Looking for %s hook", funcname)
    try:
        sanitize = getattr(hooks, funcname)
    except AttributeError:
        logging.info("No hook for %s", funcname)
        logging.info("Nothing needs to be done")
        sys.exit(0)
    else:
        logging.debug("Found hook %s", funcname)

    # Well that was ugly. Here's the actual work:

    _backup(args.target, args.nobackup)
    with open(args.target, "r+b") as f:
        logging.info("Sanitizing '%s'", args.target)
        sanitize(f)


def charmap(args):
    # FIXME: Much of this should probably be moved into the text module or
    # something.
    logging.info("Loading strings")
    with open(args.strings) as f:
        strings = [s.strip() for s in f]

    logging.info("Loading rom")
    with open(args.rom, "rb") as rom:
        data = rom.read()
        view = memoryview(data)
    logging.debug("rom length: %s bytes", len(data))

    logging.info("Starting search")
    maps = {s: [] for s in strings}
    for s in strings:
        logging.debug("Searching for %s", s)
        pattern = romlib.charset.Pattern(s)
        for i in range(len(data) - len(s) + 1):
            chunk = view[i:i+len(s)]
            try:
                cmap = pattern.buildmap(chunk)
            except romlib.charset.NoMapping:
                continue
            logging.debug("Found match for %s at %s", s, i)
            if cmap in maps[s]:
                logging.debug("Duplicate mapping, skipping")
            else:
                logging.info("New mapping found for '%s' at %s", s, i)
                maps[s].append(cmap)

        found = len(maps[s])
        msg = "Found %s possible mappings for '%s'"
        logging.info(msg, found, s)

    charsets = []
    for m in itertools.product(*maps.values()):
        try:
            merged = romlib.charset.merge(*m)
        except romlib.charset.MappingConflictError:
            logging.debug("Mapping conflict")
            pass
        else:
            logging.info("Found consistent character map.")
            charsets.append(merged)

    if len(charsets) == 0:
        logging.error("Could not find any consistent character set")
    else:
        logging.info("Found %s consistent character sets", len(charsets))

    for i, cs in enumerate(charsets):
        print("### {} ###".format(i))
        out = sorted((byte, char) for char, byte in cs.items())
        for byte, char in out:
            print("{:02X}={}".format(byte, char))

def blocks(args):
    # Most users likely use Windows, so I can't rely on them having sort, head,
    # etc or equivalents available, nor that they'll know how to use them.
    # Hence some extra args that shouldn't be necessary but are.
    args.byte = romlib.util.intify(args.byte, None)
    args.num = romlib.util.intify(args.num, None)
    args.min = romlib.util.intify(args.min, 16)

    logging.info("Loading rom")
    with open(args.rom, "rb") as rom:
        data = rom.read()

    logging.debug("rom length: %s bytes", len(data))
    logging.info("Starting search")

    blocks = []
    blocklen = 1
    last = None
    for i, byte in enumerate(data):
        if last is not None and byte != last:
            # End of block. Add to the list if it's long enough to care. If the
            # user specified a byte to search for and this isn't it, skip it.
            if blocklen > args.min:
                if args.byte is None or last == args.byte:
                    logging.debug("Noting block at %s", i-blocklen)
                    blocks.append((blocklen, i-blocklen, last))
            blocklen = 1
            last = None
        else:
            blocklen += 1
            last = byte

    blocks.sort(reverse=True)
    print("offset\tblkbyte\tlength\thexlen")
    for length, offset, byte in blocks[0:args.num]:
        fmt = "{:06X}\t0x{:02X}\t{}\t{:X}"
        print(fmt.format(offset, byte, length, length))


def _backup(filename, skip=False):
    """ Make a backup, or warn if no backup."""
    bak = filename + ".bak"
    if not skip:
        logging.info("Backing up '%s' as '%s'", filename, bak)
        os.replace(filename, bak)
        shutil.copyfile(bak, filename)
    else:
        logging.warning("Backup suppressed")


def img(args):
    """ Read CHR images from a rom and display them.

    FIXME: Just a proof of concept for now. The `args` argument contains
    command line arguments from argparse.
    """
    import tkinter
    from bitstring import Bits

    # Argument type corrections
    args.count = int(args.count, 0)
    args.offset = int(args.offset, 0)
    args.zoom = int(args.zoom, 0) if args.zoom else 1

    def unpack(data):
        """ Turn raw bytes into a list of pixel color values

        The returned list ordering is left to right, top to bottom."""
        lowbits = Bits(data[:8])
        highbits = Bits(data[8:])
        pixels = [2 * int(high) + int(low)
                  for high, low
                  in zip(highbits, lowbits)]
        return pixels

    def makeimage(pixels):
        """ Initialize a PhotoImage from pixel colors"""
        image = tkinter.PhotoImage(width=8,height=8)
        palette = {0: "#000000",
                   1: "#22AA22",
                   2: "#2222FF",
                   3: "#DDDDDD"}
        for i, pixel in enumerate(pixels):
            x = i % 8
            y = i // 8
            image.put(palette[pixel], (x, y))
        return image

    # Read our data in 16-byte chunks and unpack each of them.
    images = []
    with open(args.rom, "rb") as rom:
        rom.seek(args.offset, 0)
        for n in range(args.count):
            data = rom.read(16)
            image = unpack(data)
            images.append(image)

    # Create the display canvas
    window = tkinter.Tk()
    canvas = tkinter.Canvas(window, width=640, height=480, bg="#000000")
    canvas.pack()

    # Create Tk.PhotoImages for each image and keep a handle to them in the
    # canvas for Reasons.
    canvas.sprites = []
    for image in images:
        pimg = makeimage(image)
        pimg = pimg.zoom(args.zoom, args.zoom) # Ow.
        canvas.sprites.append(pimg)

    # Now draw everything.
    for i, pimg in enumerate(canvas.sprites):
        columns = 640 // (8 * args.zoom)
        row = i // columns
        col = i % columns
        pos = (col * 8 * args.zoom, row * 8 * args.zoom)
        canvas.create_image(pos, image=pimg, anchor=tkinter.NW)

    window.mainloop()


def _filterpatch(patch, romfile):
    # Fixme: Ask forgiveness, not permission here? And should the check be
    # handled by the caller?
    if romfile is not None:
        msg = "Filtering changes against %s."
        logging.info(msg, romfile)
        with open(romfile, "rb") as rom:
                patch.filter(rom)


def _writepatch(patch, outfile):
    """ Write a patch to a file.

    Logs a bit if needed and redirects to stdout if needed.
    """
    if outfile:
        logging.info("Creating patch at %s.", outfile)
        patch.save(outfile)
    else:
        patch.to_ipst(sys.stdout)
    logging.info("There were %s changes.", len(patch.changes))
