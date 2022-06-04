"""A toolset for examining and modifying ROMs

Usage: romtool [--help] [options] <command> [<args>...]

To see command-specific help, run `romtool <command> --help`

Commands:
    ident               Identify a ROM
    dump                Dump all known data from a ROM to `moddir`
    build               Build a patch
    diff                Build a patch by diffing two ROMs
    apply               Apply patches to a ROM
    convert             Convert a patch from one format to another
    findblocks          Find blocks of unused space in a ROM
    search              Search a rom for strings, indexes, etc.
    charmap             Generate a texttable from known strings
    initchg             Generate a starter changeset file.
    fix                 Fix bogus headers and checksums
    dirs                Print directory paths used by romtool

Options:
    -V, --version       Print version and exit

    The following options are accepted by (almost) all commands:

    -h, --help          Print this help
    -q, --quiet         Quiet output
    -v, --verbose       Verbose output
    -D, --debug         Even more verbose output
    --pdb               Start interactive debugger on crash


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
import re
import codecs
from os.path import splitext
from itertools import chain, groupby
from textwrap import dedent
from functools import partial
from collections import namedtuple
from inspect import getdoc

from addict import Dict
from appdirs import AppDirs
from docopt import docopt
from alive_progress import alive_bar

from . import util, config, charset
from .rommap import RomMap
from .rom import Rom
from .patch import Patch
from .util import pkgfile, slurp, loadyaml
from .util import pipeline, HexInt
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


def loadrom(romfile, mapdir=None):
    """ Load a rom from a file with an appropriate map

    Helper function to reduce command boilerplate
    """
    if not mapdir:
        try:
            mapdir = detect(romfile)
        except RomDetectionError as ex:
            ex.log()
            sys.exit(2)
    rmap = RomMap.load(mapdir)
    with open(romfile, 'rb') as f:
        rom = Rom.make(f, rmap)
    return rom


def dump(args):
    """ Dump all known data from a ROM

    Usage: romtool dump [--help] [options] <rom> <moddir> [<patches>...]

    Arguments:
        rom       The ROM file to dump
        outdir    Output directory
        patches   Patches to apply to the ROM data before dumping

    Options:
        -m, --map PATH      Specify path to ROM map
        -f, --force         Overwrite existing output files

        -h, --help          Print this help
        -v, --verbose       Verbose output
        -q, --quiet         Quiet output
        -D, --debug         Even more verbose output

    If <patches>... are given, they will be applied to the ROM in-memory before
    dumping. This is intended to allow examining a patch's effects without
    physically modifying the rom.
    """


    if __debug__:
        log.info("Optimizations disabled; dumping may be slow. "
                 "Consider setting PYTHONOPTIMIZE=TRUE")
    if args.patches:
        raise NotImplementedError("Pre-patching of dumps not yet implemented")
    if not args.map:
        try:
            args.map = detect(args.rom)
        except RomDetectionError as e:
            e.log()
            sys.exit(2)

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

    Usage: romtool initchg <rom> <filename>

    The generated file should indicate what tables are available for
    modification, what fields exist for the objects in those tables, and
    if possible provide minimal commented examples.

    NOTE: not implemented yet
    """
    raise NotImplementedError("`initchg` command not implemented yet")


def build(args):
    """ Build patches from a data set containing changes.

    Usage: romtool build [--help] [options] <rom> <input>...

    Positional arguments:
        rom     ROM to generate a patch against
        input   directories or patch files

    Options:
        -m, --map PATH      Manually specify rom map
        -o, --out FILE      Output filename (default stdout)

        -S, --sanitize      Include corrected checksums in patches

        -h, --help          Print this help
        -v, --verbose       Verbose output
        -q, --quiet         Quiet output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash

    <input>... may be any number of mod directories (as produced by the 'dump'
    command), changeset files, or patch files in any supported format. Input
    files are applied to the rom data in command-line order; the result is
    diffed against the original ROM to generate the patch.

    By default, the ouput patch will be printed in .ipst format to stdout for
    examination. If `--out FILE` is given, the file's extension will be used to
    determine the intended format.
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

    if args.sanitize:
        raise NotImplementedError("--sanitize option not yet implemented")

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
    """ Convert a patch from one format to another

    Usage: romtool convert [--help] [options] <infile> [<outfile>]

    Arguments:
        infile    input filename
        outfile   output filename

    Options:
        -h, --help          Print this help
        -q, --quiet         Quiet output
        -v, --verbose       Verbose output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash

    At present, the input and output formats are detected by filename,
    and only .ips and .ipst are supported. If <outfile> is omitted, the patch
    will be printed to stdout as .ipst.
    """
    # FIXME: Support stdin/stdout with -I and -O for in/out format
    patch = Patch.load(args.infile)
    _writepatch(patch, args.outfile)


def diff(args):
    """ Build a patch by diffing two roms.

    Usage: romtool diff [--help] [options] <original> <modified>

    Arguments:
        original        Original ROM file
        modified        Modified ROM file

    Options:
        -o, --out FILE      Output filename

        -h, --help          Print this help
        -q, --quiet         Quiet output
        -v, --verbose       Verbose output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash


    If someone has been making their changes in-place, they can use this
    to get a patch.
    """
    with open(args.original, "rb") as original:
        with open(args.modified, "rb") as changed:
            patch = Patch.from_diff(original, changed)
    _writepatch(patch, args.out)

def fix(args):
    """ Fix header/checksum issues in a ROM

    Usage: romtool fix [--help] [options] <rom>

    Not implemented yet.
    """
    raise NotImplementedError("`fix` command not implemented yet")

def apply(args):
    """ Apply patches to a file

    Usage: romtool apply [--help] [options] <rom> <patches>...

    Positional arguments:
        rom     file to patch
        input   directories or patch files

    Options:
        -m, --map PATH      Manually specify rom map
        -N, --nobackup      Don't create backup when patching files

        -h, --help          Print this help
        -v, --verbose       Verbose output
        -q, --quiet         Quiet output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash

    'input' may be any number of mod directories (as produced by the 'dump'
    command) or patch files in any supported format. Input files are applied to
    the rom in order.

    By default, a backup of the rom will be created at <rom>.bak. This behavior
    can be suppressed with --nobackup.
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
    """ Generate a texttable from known strings

    Usage: romtool charmap <rom> <strings>...

    Arguments:
        rom         ROM file to examine
        strings     Some strings known to be in the ROM

    Options:
        -h, --help          Print this help
        -q, --quiet         Quiet output
        -v, --verbose       Verbose output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash

    Attempts to guess the character encoding of the ROM and generate a text
    table. For best results, supply several strings of a few words each that
    are known to be present in the ROM, and that do not contain newlines,
    special characters, or common strings that may be compressed (e.g.
    character names).

    NOTE: If you can view the character-set tiles directly, do that instead.
    The charmap command is extremely slow and not terribly good at what it
    does.
    """
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
    """ Search for unused blocks in a rom

    Usage: romtool findblocks [--help] [options] <rom>

    Arguments:
        rom     ROM to search for empty blocks

    Options:
        -b, --byte BYTE   Specify byte to search for
        -s, --size N      Minimum block size to report
        -l, --limit N     Maximum number of blocks to report
        -S, --sort        Sort block list by size
        -H, --noheaders   Omit output headers

        -h, --help        Print this help
        -q, --quiet       Quiet output
        -v, --verbose     Verbose output
        -D, --debug       Even more verbose output
        --pdb             Start interactive debugger on crash

    Searches a ROM for blocks of potentially-unused space. By default,
    space is considered unused if it contains consecutive repetitions of an
    identical value for at least 256 bytes. The results are printed as a
    tab-separated table of block offsets and lengths.

    Basic sorting and filtering options are provided for convenience.
    If --sort is given, blocks will be sorted in descending order by
    size. If `--limit N` is given, only N blocks will be reported. Any
    sorting occurs before the limit is applied.
    """
    # Most users likely use Windows, so I can't rely on them having sort, head,
    # etc or equivalents available, nor that they'll know how to use them.
    # Hence some extra args for sorting/limiting the output
    byte = int(args.byte, 0) if args.byte else None
    min_size = int(args.size, 0) if args.size else 0x100
    limit = int(args.limit, 0) if args.limit else None

    log.info("Loading rom")
    with open(args.rom, "rb") as rom:
        data = rom.read()

    log.debug("rom length: %s bytes", len(data))
    log.info("Searching for %s%s-byte blocks of %s",
             '' if not limit else 'up to {limit} ',
             min_size,
             'any byte' if byte is None else hex(byte))
    blocks = []
    offset = 0
    for value, block in groupby(data):
        block = list(block)
        if len(block) >= min_size and byte in (None, value):
            log.debug("Noting block at %s", offset)
            blocks.append((len(block), offset, value))
        offset += len(block)
    if args.sort:
        blocks.sort(reverse=True)
    if not args.noheaders:
        print("offset\tbyte\tlength\thexlen")
    for length, offset, byte in blocks[0:limit]:
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
    """ Print identifying information for a ROM

    Usage: romtool ident [--help] [options] <roms>...

    Command options:
        -l, --long          Print all available ROM metadata

    Common options:
        -h, --help          Print this help
        -V, --version       Print version and exit
        -q, --quiet         Quiet output
        -v, --verbose       Verbose output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash

    By default, this command attempts to identify one or more ROMs and
    prints their canonical name(s) and type information (based on the
    no-intro rom set), one file per line. If --long is given, it prints
    some additional useful metadata about each ROM, such as file hashes.
    """
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

        with open(filename, 'rb') as f:
            rom = Rom.make(f)
        info = Dict()
        info.name = rom.name
        info.file = filename
        info.type = rom.prettytype
        info.size = len(rom.file.bytes)

        hashalgs = ['crc32', 'sha1', 'md5']
        for alg in hashalgs:
            h_file = getattr(rom.file, alg)
            h_data = getattr(rom.data, alg)
            if h_file == h_data:
                info[alg] = h_file
            else:
                info[alg + ' (file)'] = h_file
                info[alg + ' (data)'] = h_data

        try:
            info.map = detect(filename)
        except RomDetectionError:
            info.map = "(no map found)"
        if not args.long:
            prefix = f"{filename}:\t" if len(args.roms) > 1 else ""
            print(f"{prefix}{rom}")
        else:
            for k, v in info.items():
                print(f"{k+':':16}{v}")


def _matchlength(values, maxdiff, alignment):
    """ Get prospective pointer-index length

    Look for offsets that are no further separated than the underlying
    array, and relatively aligned with the stride of the array.
    """
    minv = maxv = values[0]
    if minv in (0, 0xFF, 0xFFFF, 0xFFFFFF, 0xFFFFFFFF):
        return 0
    for i, v in enumerate(values, 1):
        if (v - minv) % alignment:
            return i
        if v < minv:
            minv = v
        if v > maxv:
            maxv = v
        if maxv - minv > maxdiff:
            return i
    return i

def search(args):
    """ Search a rom for...things.

    NOTE: The search command is experimental, slow, poorly documented, and of
    dubious use. It was written to help me locate data table elements when
    writing maps, not for general use. If it breaks -- which is quite
    likely -- enjoy both pieces.

    Usage:
        romtool search index [options] <rom> <psize> <endian> <alignment> <count>
        romtool search strings [options] <rom> <encoding>
        romtool search values [options] <rom> <size> <endian> <expected>...
        romtool search -h | --help

    Options:
        -m, --map           Specify ROM map
        -P, --progress      Display progress bar

        -h, --help          Print this help
        -q, --quiet         Quiet output
        -v, --verbose       Verbose output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash
    """
    if args.index:
        search_index(args)
    elif args.strings:
        search_strings(args)
    elif args.values:
        search_values(args)
    else:
        raise Exception("don't know how to search for that")

def search_index(args):
    rom = loadrom(args.rom, args.map)
    log.info("searching for %s-byte %s-endian pointer index",
             args.psize, args.endian)
    ptr_bytes = int(args.psize, 0)
    align = int(args.alignment, 0)
    count = int(args.count, 0)
    endian = args.endian
    coverage = align * count
    threshold = count // 2
    # calling the progress bar counter is surprisingly expensive. Do so at
    # intervals. 701 eyeballed as a prime number ending in 01, which should
    # 'look like' it's counting up smoothly.
    prg_interval = 701
    data = rom.data.bytes
    log.info("creating pointers")
    cm = partial(alive_bar, disable=not args.progress, title_length=25)
    with cm(len(data), title='generating pointers') as progress:
        def mkptrs(data, sz_ptr):
            for i, c in enumerate(util.chunk(data, sz_ptr)):
                yield int.from_bytes(c, endian)
                if not i % prg_interval:
                    progress(prg_interval)
            progress(i % prg_interval)
        pointers = {i: tuple(mkptrs(data[i:], ptr_bytes))
                    for i in range(ptr_bytes)}

    hits = []
    Hit = namedtuple('Hit', 'offset ml head')
    with cm(len(data), title='searching') as progress:
        for offset, ptrs in pointers.items():
            log.info("looking for hits at starting offset %s", offset)
            for i in range(len(ptrs)):
                ml = _matchlength(
                        ptrs[i:i+count*2],
                        coverage,
                        align
                        )
                if ml > threshold and len(set(ptrs[i:i+ml])) > threshold:
                    abs_start = HexInt(offset + i * ptr_bytes)
                    log.info("reasonable match found at 0x%X (%s length)",
                             abs_start, ml)
                    head = ', '.join(str(HexInt(p, ptr_bytes*8))
                                     for p in ptrs[i:i+5])
                    hits.append(Hit(abs_start, ml, head))
                if not i % prg_interval:
                    progress(prg_interval)
            progress(i % prg_interval)
    if not hits:
        print("no apparent indexes found")
        sys.exit(2)

    print("possible index starts:")
    fmt = "{}\t{} items\t[{}...]"
    print(fmt.format(*hits[0]))
    for a, b in util.pairwise(hits):
        if b.ml > a.ml or b.offset != a.offset + ptr_bytes:
            print(fmt.format(*b))

def search_strings(args):
    rom = loadrom(args.rom, args.map)
    log.info(f"searching for valid strings using encoding '{args.encoding}'")
    data = rom.data.bytes
    codec = codecs.lookup(args.encoding + '_clean')
    offset = 0
    vowels = re.compile('[AEIOUaeiou]')
    binary = re.compile('\[\$[ABCDEF1234567890]+\]')
    cm = partial(alive_bar, disable=not args.progress, enrich_print=False)
    with cm(len(data), title='searching for strings') as progress:
        while offset < len(data):
            # Not a great way to do this, breaks strings at 20 chars because
            # passing the whole thing is dog-slow and it's unclear why. This is
            # good enough to eyeball the results to get string table offsets,
            # though.
            s, consumed = codec.decode(data[offset:offset+20])
            if len(s) > 3 and vowels.search(s) and not binary.search(s):
                print(f"0x{offset:X}\t{s}")
            offset += consumed
            progress(consumed)


def search_values(args):
    rom = loadrom(args.rom, args.map)
    data = rom.data.bytes
    size = int(args.size, 0)
    endian = args.endian
    expected = [int(v, 0) for v in args.expected]
    cm = partial(alive_bar, disable=not args.progress, enrich_print=False)

    def value(offset):
        return int.from_bytes(data[offset:offset+size], endian)

    with cm(len(data)) as progress:
        for offset in range(len(data)):
            actual = (value(offset+i*size) for i in range(len(expected)))
            if all(e == a for e, a in zip(expected, actual)):
                print(f"0x{offset:X}")
            progress()


def dirs(args):
    """ Print romtool directory paths

    Usage: romtool dirs [--help]

    Romtool keeps its configuration, data files, and logs in user directories
    that vary between platforms. This command prints the directories used on
    your current platform.
    """
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


def initlog(args):
    key = ('debug' if args.debug
           else 'verbose' if args.verbose
           else 'quiet' if args.quiet
           else 'default')
    logconf = config.load('logging.yaml')
    logging.config.dictConfig(logconf[key])


def main(argv=None):
    """ Entry point for romtool."""
    args = Args(docopt(__doc__.strip(), argv, version=version, options_first=True))
    initlog(args)
    util.debug_structure(args)
    util.debug_structure(dict(args.items()))

    expected = () if args.debug else (FileNotFoundError, NotImplementedError, RomtoolError)

    try:
        cmd = globals().get(args.command)
        if not cmd:
            log.critical("'%s' is not a valid command; see romtool --help",
                         args.command);
            sys.exit(1);
        args = Args(docopt(getdoc(cmd), argv, version=version))
        initlog(args)  # because log opts may come before or after the command
        cmd(args)
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
