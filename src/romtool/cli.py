"""romtool

A tool for examining and modifying ROMs

Usage:
    romtool --help
    romtool ident [-l|--long] [options] <roms>...
    romtool dump [options] <rom> <moddir> [<patches>...]
    romtool build [options] <rom> <input>...
    romtool convert [options] <infile> <outfile>
    romtool apply [options] <rom> <patches>...
    romtool diff [options] <original> <modified>
    romtool fix [options] <rom>
    romtool charmap <rom> <strings>...
    romtool initchg <rom> <filename>
    romtool dirs

Commmands:
    ident               Print information about a ROM file
    dump                Dump all known data from a ROM to `moddir`
    build               Construct a patch from input files
    convert             Convert a patch from one format to another
    apply               Apply patches to a ROM
    diff                Construct a patch by diffing two ROMs
    fix                 Fix bogus headers and checksums
    charmap             Generate a texttable from known strings
    initchg             Generate a starter changeset file.
    dirs                Print directory paths used by romtool

Options:
    -i, --interactive   Prompt for confirmation on destructive operations
    -n, --dryrun        Show what would be done, but don't do it
    -f, --force         Never ask for confirmation

    -o, --out PATH      Output file or directory. Detects type by extension
    -m, --map PATH      Manually specify rom map
    -S, --sanitize      Include internal checksum updates in patches
    -N, --nobackup      Don't create backup when patching files

    -h, --help          Print this help
    -V, --version       Print version and exit
    -v, --verbose       Verbose output
    -q, --quiet         Quiet output
    -D, --debug         Even more verbose output
    --pdb               Start interactive debugger on crash

    -l, --long          Print additional ROM information

Examples:
    A simple modding session looks like this:

    $ romtool dump game.rom projectdir
    # <edit the files in projectdir with a spreadsheet program>
    $ romtool build game.rom projectdir -o game.ips
"""

import sys
import logging
import logging.config
import textwrap
import hashlib
import os
import shutil
import itertools
import csv
import json
from os.path import splitext
from itertools import chain
from textwrap import dedent

from addict import Dict
from appdirs import AppDirs
from docopt import docopt

from . import util, config, charset
from .rommap import RomMap
from .rom import Rom
from .patch import Patch
from .util import pkgfile, slurp, loadyaml
from .util import pipeline
from .version import version
from .exceptions import RomtoolError, RomDetectionError, ChangesetError

log = logging.getLogger(__name__)

try:
    # Try to do the right thing when piping to head, etc.
    from signal import signal, SIGPIPE, SIG_DFL
    signal(SIGPIPE, SIG_DFL)
except ImportError:
    # SIGPIPE isn't available on Windows, at least not on my machine. For now
    # just ignore it, but I should probably test piping on windows at some
    # point.
    pass


# FIXME: Add subcommand to list available maps on the default search paths.
# Probably its output should advise the user that it's only what shipped with
# romtool and they're free to supply their own.

def detect(romfile, maproot=None):
    """ Detect the map to use with a given ROM.

    maproot -- A root directory containing a set of rom maps and a hashdb.txt
               file associating sha1 hashes with map names.
    """
    cfg = config.load('romtool.yaml')
    if maproot is None:
        maproot = next(chain(cfg.map_paths, [pkgfile("maps")]))

    dbfile = os.path.join(maproot, 'hashdb.txt')
    with open(dbfile) as hashdb, open(romfile, "rb") as rom:
        # FIXME: Reads whole file into memory, likely to fail on giant images,
        # e.g cds/dvds.
        log.info("Detecting ROM map for: %s.", romfile)
        romhash = hashlib.sha1(rom.read()).hexdigest()
        log.info("sha1 hash is: %s.", romhash)
        try:
            line = next(line for line in hashdb if line.startswith(romhash))
        except StopIteration:
            raise RomDetectionError(romhash, romfile)
        name = line.split(maxsplit=1)[1].strip()
        log.info("ROM map found: %s", name)
        return os.path.join(maproot, name)


def dump(args):
    """ Dump all known data from a ROM."""
    if __debug__:
        log.info("Optimizations disabled; dumping may be slow. "
                 "Consider setting PYTHONOPTIMIZE=TRUE")
    if not args.map:
        try:
            args.map = detect(args.rom)
        except RomDetectionError as e:
            e.log()
            sys.exit(2)

    # This gets awkward since we want to open ROM always but open SAVE
    # only sometimes. I suspect this means the design needs some work.
    # Can't they be loaded separately? (maybe not, saves may have
    # pointers to stuff in the rom that need dereferencing?)
    rmap = RomMap.load(args.map)
    log.info("Opening ROM file: %s", args.rom)
    with open(args.rom, "rb") as f:
        rom = Rom.make(f, rmap)

    log.info("Dumping ROM data to: %s", args.moddir)
    os.makedirs(args.moddir, exist_ok=True)
    try:
        rom.dump(args.moddir, args.force)
    except FileExistsError as err:
        log.error(err)
        dest = os.path.abspath(args.moddir)
        log.error("Aborting, dump would overwrite files in %s", dest)
        log.error("you can use --force if you really mean it")
        sys.exit(2)
    log.info("Dump finished")


def initchg(args):
    """ Generate a starter changeset file

    The generated file should indicate what tables are available for
    modification, what fields exist for the objects in those tables, and
    if possible provide minimal commented examples.
    """
    raise NotImplementedError("`initchg` command not implemented yet")


def build(args):
    """ Build patches from a data set containing changes.

    Intended to be applied to a directory created by the dump subcommand.
    """
    # FIXME: Optionally, generate a changelog along with the patch. Changes
    # should specify a table, name, key, and value, in most cases. Changelog
    # should be something like "esuna's HP increased from 16 to 100" or
    # similar. If this is the mode encouraged for novices, it gets around the
    # stupid shit with spreadsheet programs, too. Also makes patch testing
    # easier. Might also make it eaiser to migrate mods from one version of
    # the map to another.

    # FIXME: I'd like to print a warning if overlapping changes occur, but
    # I'm not sure how to detect that

    if not args.map:
        try:
            args.map = detect(args.rom)
        except RomDetectionError as e:
            e.log()
            sys.exit(2)

    log.info("Loading ROM map at: %s", args.map)
    rmap = RomMap.load(args.map)
    log.info("Opening ROM file at: %s", args.rom)
    with open(args.rom, "rb") as f:
        rom = Rom.make(f, rmap)
    # For each supported changeset type, specify a set of functions to apply in
    # sequence to the filename to load it.
    typeloaders = {'.ips': [Patch.load, rom.apply_patch],
                   '.ipst': [Patch.load, rom.apply_patch],
                   '.yaml': [slurp, loadyaml, rom.apply],
                   '.json': [slurp, json.loads, rom.apply]}
    for path in args.input:
        log.info("Loading changes from: %s", path)
        ext = splitext(path)[1]
        loaders = typeloaders.get(ext, None)
        if loaders:
            try:
                pipeline(path, *loaders)
            except ChangesetError as ex:
                raise ChangesetError(f"Error in '{path}': {ex}")
        elif os.path.isdir(path):
            if __debug__:
                log.info("Optimizations disabled; building from a "
                         "directory may be slow. Consider setting "
                         "PYTHONOPTIMIZE=TRUE")
            rom.load(path)
        else:
            raise ValueError(f"Don't know what to do with input file: {path}")
    _writepatch(rom.patch, args.out)


def convert(args):
    """ Convert one patch format to another. """
    patch = Patch.load(args.infile)
    patch.save(args.outfile)

def diff(args):
    """ Build a patch by diffing two roms.

    If someone has been making their changes in-place, they can use this to get
    a patch.
    """
    with open(args.original, "rb") as original:
        with open(args.modified, "rb") as changed:
            patch = Patch.from_diff(original, changed)
    _writepatch(patch, args.out)

def fix(args):
    """ Fix header/checksum issues in a ROM """
    raise NotImplementedError("`fix` command not implemented yet")

def apply(args):
    """ Apply a patch to a file, such as a rom or a save.

    By default this makes a backup of the existing file at filename.bak.
    """
    # Move the target to a backup name first to preserve its metadata, then
    # copy it back to its original name, then patch it there.
    tgt = args.rom
    _backup(args.rom, args.nobackup)
    with open(tgt, "r+b") as f:
        for path in args.patches:
            log.info("Applying patch: %s", path)
            patch = Patch.load(path)
            patch.apply(f)


def sanitize(args):
    """ Sanitize a ROM or save file

    This uses map-specific hooks to correct any checksum errors or similar
    file-level issues in a rom or savegame.

    FIXME: Supply separate sanitizer
    """
    if args.map is None:
        try:
            args.map = detect(args.target)
        except RomDetectionError as e:
            e.log()
            sys.exit(2)
    rmap = RomMap.load(args.map)
    _backup(args.target, args.nobackup)
    rom = Rom.make(args.target, rmap)
    log.info("Sanitizing '%s'", args.target)
    rom.sanitize()
    rom.write(args.target)


def charmap(args):
    # FIXME: Much of this should probably be moved into the text module or
    # something.
    log.info("Loading strings")
    with open(args.strings) as f:
        strings = [s.strip() for s in f]

    log.info("Loading rom")
    with open(args.rom, "rb") as rom:
        data = rom.read()
        view = memoryview(data)
    log.debug("rom length: %s bytes", len(data))

    log.info("Starting search")
    maps = {s: [] for s in strings}
    for s in strings:
        log.debug("Searching for %s", s)
        pattern = charset.Pattern(s)
        for i in range(len(data) - len(s) + 1):
            chunk = view[i:i+len(s)]
            try:
                cmap = pattern.buildmap(chunk)
            except charset.NoMapping:
                continue
            log.debug("Found match for %s at %s", s, i)
            if cmap in maps[s]:
                log.debug("Duplicate mapping, skipping")
            else:
                log.info("New mapping found for '%s' at %s", s, i)
                maps[s].append(cmap)

        found = len(maps[s])
        msg = "Found %s possible mappings for '%s'"
        log.info(msg, found, s)

    charsets = []
    for m in itertools.product(*maps.values()):
        try:
            merged = charset.merge(*m)
        except charset.MappingConflictError:
            log.debug("Mapping conflict")
        else:
            log.info("Found consistent character map.")
            charsets.append(merged)

    if len(charsets) == 0:
        log.error("Could not find any consistent character set")
    else:
        log.info("Found %s consistent character sets", len(charsets))

    for i, cs in enumerate(charsets):
        print("### {} ###".format(i))
        out = sorted((byte, char) for char, byte in cs.items())
        for byte, char in out:
            print("{:02X}={}".format(byte, char))

def findblocks(args):
    """ Search for unused blocks in a rom """
    # Most users likely use Windows, so I can't rely on them having sort, head,
    # etc or equivalents available, nor that they'll know how to use them.
    # Hence some extra args for sorting/limiting the output
    args.byte = util.intify(args.byte, None)
    args.num = util.intify(args.num, None)
    args.min = util.intify(args.min, 16)

    log.info("Loading rom")
    with open(args.rom, "rb") as rom:
        data = rom.read()

    log.debug("rom length: %s bytes", len(data))
    log.info("Starting search")

    blocks = []
    blocklen = 1
    last = None
    for i, byte in enumerate(data):
        if last is not None and byte != last:
            # End of block. Add to the list if it's long enough to care. If the
            # user specified a byte to search for and this isn't it, skip it.
            if blocklen > args.min:
                if args.byte is None or last == args.byte:
                    log.debug("Noting block at %s", i-blocklen)
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

def meta(args):
    """ Print rom metadata, e.g. console and header info"""

    writer = None
    for filename in args.rom:
        log.info("Inspecting ROM: %s", filename)
        with open(filename, 'rb') as romfile:
            try:
                rom = rom.Rom.make(romfile)
            except rom.RomFormatError as e:
                log.error("Error inspecting %s: %s", filename, str(e))
                continue
        header_data = {"File": filename}
        header_data.update(rom.header.dump())
        columns = ['File'] + list(rom.header.labels)
        if not writer:
            writer = csv.DictWriter(sys.stdout, columns, dialect='romtool')
            writer.writeheader()
        writer.writerow(header_data)


def ident(args):
    # FIXME: assumes all input files actually *are* roms. They may not be (e.g.
    # passing an ips patch, or something else entirely) Probably each rom class
    # needs a checker, or something. Suggest use of `file` if romtool can't
    # identify it.
    first = True
    for filename in args.roms:
        if first:
            first = False
        elif args.long:
            print("%%")

        try:
            rmap = RomMap.load(detect(filename))
        except RomDetectionError:
            rmap = None

        with open(filename, 'rb') as f:
            rom = Rom.make(f, rmap)
        info = Dict()
        info.name = rom.name
        info.file = filename
        info.type = rom.romtype
        info.size = len(rom.file.bytes)
        info.crc32 = rom.file.crc32
        info.sha1 = rom.file.sha1
        info.md5 = rom.file.md5
        info.supported = 'yes' if rom.map.path else 'no'
        info.map = rom.map.path or '(no map found)'
        if not args.long:
            prefix = f"{filename}:\t" if len(args.roms) > 1 else ""
            print(f"{prefix}{rom}")
        else:
            for k, v in info.items():
                print(f"{k+':':12}{v}")


def dirs(args):
    ad = AppDirs("romtool")
    out = f"""
        config:     {ad.user_config_dir}
        data:       {ad.user_data_dir}
        state:      {ad.user_state_dir}
        cache:      {ad.user_cache_dir}
        logs:       {ad.user_log_dir}
        """
    print(dedent(out).strip())


def _backup(filename, skip=False):
    """ Make a backup, or warn if no backup."""
    bak = filename + ".bak"
    if not skip:
        log.info("Backing up '%s' as '%s'", filename, bak)
        os.replace(filename, bak)
        shutil.copyfile(bak, filename)
    else:
        log.warning("Backup suppressed")


def _filterpatch(patch, romfile):
    # Fixme: Ask forgiveness, not permission here? And should the check be
    # handled by the caller?
    if romfile is not None:
        msg = "Filtering changes against %s."
        log.info(msg, romfile)
        with open(romfile, "rb") as rom:
            patch.filter(rom)


def _writepatch(patch, outfile):
    """ Write a patch to a file.

    Logs a bit if needed and redirects to stdout if needed.
    """
    if outfile:
        log.info("Creating patch at %s.", outfile)
        patch.save(outfile)
    else:
        patch.to_ipst(sys.stdout)
    log.info("There were %s changes.", len(patch.changes))

class Args(Dict):
    """ Convenience wrapper for the docopt dict

    This exists so I can do args.whatever and get the Right Thing out of it.
    """

    keyfmts = ['{key}',
               '-{key}',
               '--{key}',
               '<{key}>']

    def _realkey(self, key):
        # Look for the first key-variant that's present, otherwise use the
        # original key.
        for fmt in type(self).keyfmts:
            realkey = fmt.format(key=key)
            if realkey in self:
                return realkey
        return key

    def __getitem__(self, key):
        key = self._realkey(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        key = self._realkey(key)
        super().__setitem__(key, value)

    @property
    def command(self):
        return next(k for k, v in self.items()
                    if k.isalnum() and v)


def initlog(args):
    key = ('debug' if args.debug
           else 'verbose' if args.verbose
           else 'quiet' if args.quiet
           else 'default')
    logconf = config.load('logging.yaml')
    logging.config.dictConfig(logconf[key])


def main(argv=None):
    """ Entry point for romtool."""

    args = Args(docopt(__doc__, argv, version=version))
    initlog(args)
    util.debug_structure(args)

    expected = (FileNotFoundError, NotImplementedError, RomtoolError) if not args.debug else ()

    try:
        globals()[args.command](args)
    except KeyboardInterrupt as ex:
        log.error(f"keyboard interrupt; aborting")
        sys.exit(2)
    except expected as ex:
        # I'd rather not separately handle this in every command that uses it.
        log.error(ex)
        sys.exit(2)
    except Exception as ex:  # pylint: disable=broad-except
        # I want to break this into a function and use it as excepthook, but
        # every time I try it doesn't work.
        log.exception(ex)
        if not args.pdb:
            sys.exit(2)
        import pdb
        print("\n\nCRASH -- UNHANDLED EXCEPTION")
        msg = ("Starting debugger post-mortem. If you got here by "
               "accident (perhaps by trying to see what --pdb does), "
               "you can get out with 'quit'.\n\n")
        print("\n{}\n\n".format("\n".join(textwrap.wrap(msg))))
        pdb.post_mortem()
        sys.exit(2)


if __name__ == "__main__":
    main()
