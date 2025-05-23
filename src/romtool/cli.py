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
    document            Generate documentation from rom
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
import os
import pdb
import shutil
import itertools
import json
import re
from datetime import datetime
from importlib import resources
from itertools import groupby
from textwrap import dedent
from functools import partial
from collections import namedtuple
from inspect import getdoc
from pathlib import Path

import jinja2
import yaml
from addict import Dict
from appdirs import AppDirs
from docopt import docopt
from alive_progress import alive_bar

from . import util, config, charset
from .rommap import RomMap, MapDB
from .rom import Rom
from .patch import Patch
from .util import slurp, loadyaml
from .util import pipeline, HexInt
from .version import version
from .exceptions import RomtoolError, RomDetectionError, ChangesetError

log = logging.getLogger(__name__)
pkgroot = resources.files(__package__)

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


def _loadrom(romfile, mapdir=None, patches=None):
    """ Load a rom from a file with an appropriate map

    Helper function to reduce command boilerplate.
    """
    # Possibly this should be in Rom.__init__ or maybe a classmethod?
    if __debug__:
        log.info("Optimizations disabled; dumping may be slow. "
                 "Consider setting PYTHONOPTIMIZE=TRUE")
    if patches:
        raise NotImplementedError("Pre-patching of dumps not yet implemented")
    with open(romfile, 'rb') as file:
        rmap = RomMap.load(mapdir) if mapdir else MapDB.detect(file)
        return Rom.make(file, rmap)


def cmd_dump(args):
    """ Dump all known data from a ROM

    Usage: romtool dump [--help] [options] <rom> <outdir> [<patches>...]

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
        --pdb               Start interactive debugger on crash

    If <patches>... are given, they will be applied to the ROM in-memory before
    dumping. This is intended to allow examining a patch's effects without
    physically modifying the rom.
    """
    rom = _loadrom(args.rom, args.map, args.patches)
    log.info("Dumping ROM data to: %s", args.outdir)
    os.makedirs(args.outdir, exist_ok=True)
    try:
        rom.dump(args.outdir, args.force)
    except FileExistsError as err:
        log.error(err)
        log.error("Aborting, would overwrite files in %s", args.outdir)
        log.error("you can use --force if you really mean it")
        sys.exit(2)
    log.info("Dump finished")


def cmd_initchg(args):
    """ Generate a starter changeset file

    Usage: romtool initchg <rom> <filename>

    The generated file should indicate what tables are available for
    modification, what fields exist for the objects in those tables, and
    if possible provide minimal commented examples.

    NOTE: not implemented yet
    """
    raise NotImplementedError("`initchg` command not implemented yet")


def cmd_build(args):
    """ Build patches from a data set containing changes.

    Usage: romtool build [--help] [options] <rom> [<input>...]

    Positional arguments:
        rom     ROM to generate a patch against
        input   directories or patch files

    Options:
        -m, --map PATH      Manually specify rom map
        -o, --out FILE      Output filename (default stdout)

        -E, --extend        Include any map-provided extension patches
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
    rom = _loadrom(args.rom, args.map)
    # For each supported changeset type, specify a set of functions to apply in
    # sequence to the filename to load it.
    typeloaders = {'.ips': [Patch.load, rom.apply_patch],
                   '.ipst': [Patch.load, rom.apply_patch],
                   '.yaml': [slurp, loadyaml, rom.apply_changeset],
                   '.json': [slurp, json.loads, rom.apply_changeset],
                   '.asm': [rom.apply_assembly],
                   '<dir>': [rom.apply_moddir]}
    if args.extend:
        args.input = rom.map.extensions + args.input
    for path in args.input:
        if isinstance(path, str):
            path = Path(path)
        log.info("Applying changes from: %s", path)
        if __debug__ and path.is_dir():
            log.info("Optimizations disabled; building from a "
                     "directory may be slow. Consider setting "
                     "PYTHONOPTIMIZE=TRUE")
        try:
            loaders = typeloaders['<dir>' if path.is_dir() else path.suffix]
        except KeyError as ex:
            msg = f"Don't know what to do with input file: {path}"
            raise RomtoolError(msg) from ex
        try:
            pipeline(path, *loaders)
        except ChangesetError as ex:
            raise ChangesetError(f"Error in '{path}': {ex}") from ex
    if args.debug:
        for node in rom, rom.data:
            for line in yaml.dump(util.nodestats(node)).splitlines():
                log.debug(line)
    _writepatch(rom.patch, args.out)


def cmd_convert(args):
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


def cmd_diff(args):
    """ Build a patch by diffing two roms.

    Usage: romtool diff [--help] [options] <original> <modified>

    Arguments:
        original        Original ROM file
        modified        Modified ROM file

    Options:
        -o, --out FILE      Output filename
        -R, --reverse       Reverse diff

        -h, --help          Print this help
        -q, --quiet         Quiet output
        -v, --verbose       Verbose output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash


    If someone has been making their changes in-place, they can use this
    to get a patch.
    """
    fn_base = args.original if not args.reverse else args.modified
    fn_modded = args.modified if not args.reverse else args.original

    with open(fn_base, "rb") as original:
        with open(fn_modded, "rb") as changed:
            patch = Patch.from_diff(original, changed)
    _writepatch(patch, args.out)


def cmd_fix(args):
    """ Fix header/checksum issues in a ROM

    Usage: romtool fix [--help] [options] <rom>

    Not implemented yet.
    """
    raise NotImplementedError("`fix` command not implemented yet")


def cmd_apply(args):
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
    with open(tgt, "r+b") as file:
        for path in args.patches:
            log.info("Applying patch: %s", path)
            patch = Patch.load(path)
            patch.apply(file)


def cmd_sanitize(args):
    """ Sanitize a ROM or save file

    This uses map-specific hooks to correct any checksum errors or similar
    file-level issues in a rom or savegame.

    FIXME: Supply separate sanitizer
    """
    rom = _loadrom(args.target, args.map)
    log.info("Sanitizing '%s'", args.target)
    rom.sanitize()
    rom.write(args.target)


def cmd_charmap(args):
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
    with open(args.strings, encoding='utf-8') as file:
        strings = [s.strip() for s in file]

    log.info("Loading rom")
    with open(args.rom, "rb") as rom:
        data = rom.read()
        view = memoryview(data)
    log.debug("rom length: %s bytes", len(data))

    log.info("Starting search")
    maps = {s: [] for s in strings}
    for string in strings:
        log.debug("Searching for %s", string)
        pattern = charset.Pattern(string)
        for i in range(len(data) - len(string) + 1):
            chunk = view[i:i+len(string)]
            try:
                cmap = pattern.buildmap(chunk)
            except charset.NoMapping:
                continue
            log.debug("Found match for %s at %s", string, i)
            if cmap in maps[string]:
                log.debug("Duplicate mapping, skipping")
            else:
                log.info("New mapping found for '%s' at %s", string, i)
                maps[string].append(cmap)

        found = len(maps[string])
        msg = "Found %s possible mappings for '%s'"
        log.info(msg, found, string)

    charsets = []
    for mapping in itertools.product(*maps.values()):
        try:
            merged = charset.merge(*mapping)
        except charset.MappingConflictError:
            log.debug("Mapping conflict")
        else:
            log.info("Found consistent character map.")
            charsets.append(merged)

    if len(charsets) == 0:
        log.error("Could not find any consistent character set")
    else:
        log.info("Found %s consistent character sets", len(charsets))

    for i, cset in enumerate(charsets):
        print(f"### {i} ###")
        out = sorted((byte, char) for char, byte in cset.items())
        for byte, char in out:
            print(f"{byte:02X}={char}")


def cmd_document(args):
    """ Generate html documentation for a ROM

    Usage: romtool document [--help] [options] <rom> [<outdir>] [<patches>...]

    Arguments:
        rom       The ROM file to document
        outdir    Directory to build documentation
        patches   Patches to apply before documenting

    Options:
        -m, --map PATH      Specify path to ROM map
        -f, --force         Overwrite existing output files

        -h, --help          Print this help
        -v, --verbose       Verbose output
        -q, --quiet         Quiet output
        -D, --debug         Even more verbose output
        --pdb               Start interactive debugger on crash

    The built documentation includes the following:

        * ROM and map metadata
        * data table locations
        * data structure formats
        * data table contents (optional, slow)
    """
    rom = _loadrom(args.rom, args.map, args.patches)
    structures = {}
    for path in util.get_subfiles(rom.map.path, 'structs', '.tsv'):
        name = path.stem
        log.info("Generating doc table for %s", path)
        name = path.stem.title()
        try:
            with open(path, encoding='utf-8') as file:
                structures[name] = util.tsv2html(file, name)
        except jinja2.TemplateSyntaxError as ex:
            log.critical("Error while documenting %s structure: [%s:%s] %s",
                         name, ex.name, ex.lineno, ex.message)
            sys.exit(2)
    path = Path(rom.map.path, "rom.tsv")
    log.info("Documenting data tables")
    indexes = {t.index: rom.map.tables[t.index]
               for t in rom.map.tables.values()}
    tables = {tid: table for tid, table in rom.tables.items()
              if tid not in indexes}
    sys.stdout.reconfigure(encoding='utf8')
    print(util.jrender('monolithic.html',
                       rom=rom,
                       tables=tables,
                       indexes=indexes,
                       structures=structures))
    #     rom.document(args.outdir, args.force)
    # except FileExistsError as ex:
    #     log.error("%s (use --force to permit overwriting)", ex)
    #     sys.exit(1)
    # log.info("Dump finished")


def cmd_findblocks(args):
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
            log.debug("Noting block at %s (0x%X)", offset, offset)
            blocks.append((len(block), offset, value))
        offset += len(block)
    if args.sort:
        blocks.sort(reverse=True)
    if not args.noheaders:
        print("start\tend\tbyte\tlength\thexlen")
    for length, offset, byte in blocks[0:limit]:
        fmt = "{:06X}\t{:06X}\t0x{:02X}\t{}\t{:X}"
        print(fmt.format(offset, offset+length, byte, length, length))


def cmd_ident(args):
    """ Print identifying information for a ROM

    Usage: romtool ident [--help] [options] <roms>...

    Command options:
        -F, --format FORMAT   Output format
        -s, --short           Alias for --format short
        -l, --long            Alias for --format long
        -n, --name            Always echo filename in short format
        -N, --no-name         Never echo filename in short format
        -H, --header-data     Include header metadata in long format

    Common options:
        -h, --help            Print this help
        -V, --version         Print version and exit
        -q, --quiet           Quiet output
        -v, --verbose         Verbose output
        -D, --debug           Even more verbose output
        --pdb                 Start interactive debugger on crash

    Attempt to identify one or more ROMs and prints information about them.
    There are two output formats available. The `short` format prints the
    canonical name and type information for the rom. The `long` format prints
    everything romtool can figure out about it.

    By default, long format is used when a single filename is supplied.
    Otherwise, short format is used.
    """
    # FIXME: assumes all input files actually *are* roms. They may not be (e.g.
    # passing an ips patch, or something else entirely) Probably each rom class
    # needs a checker, or something. Suggest use of `file` if romtool can't
    # identify it.
    def use_long_format():
        if (args.format or 'auto') not in ('long', 'short', 'auto'):
            raise RomtoolError(f"invalid output format: '{args.format}'")
        if sum(1 for arg in [args.long, args.short, args.format] if arg) > 1:
            raise RomtoolError("multiple output formats specified")
        return (False if args.short or args.format == 'short'
                else True if args.long or args.format == 'long'
                else len(args.roms) <= 1)

    first = True
    for filename in args.roms:
        if first:
            first = False
        elif use_long_format():
            print("%%")
        try:
            rmap = MapDB.detect(filename)
        except RomDetectionError:
            rmap = None
        with open(filename, 'rb') as file:
            rom = Rom.make(file, rmap)
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

        info.map = rom.map.path or "(no map found)"
        if args['header-data']:
            for key, value in getattr(rom, 'header', {}).items():
                info[f'header.{key}'] = value
        if not use_long_format():
            prefix = (
                f"{filename}:\t"
                if args.name or not args['no-name'] and len(args.roms) > 1
                else ""
            )
            print(f"{prefix}{rom}")
        else:
            for key, value in info.items():
                print(f"{key+':':16}{value}")


def _matchlength(offsets, maxdiff, alignment):
    """ Get prospective pointer-index length

    Look for offsets that are no further separated than the underlying
    array, and relatively aligned with the stride of the array.
    Return the number of contiguous offsets that match said conditions.
    """
    minv = maxv = offsets[0]
    if minv in (0, 0xFF, 0xFFFF, 0xFFFFFF, 0xFFFFFFFF):
        return 0
    i = None
    for i, offset in enumerate(offsets, 1):
        if (offset - minv) % alignment:
            return i
        if offset < minv:
            minv = offset
        if offset > maxv:
            maxv = offset
        if maxv - minv > maxdiff:
            return i
    assert i is not None
    return i


def cmd_search(args):
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
        -m, --map PATH      Specify ROM map
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
        raise RomtoolError("don't know how to search for that")


def search_index(args):
    """ Search for pointer indexes """
    rom = _loadrom(args.rom, args.map)
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
    pbar = partial(alive_bar, disable=not args.progress, title_length=25)
    with pbar(len(data), title='generating pointers') as progress:
        def mkptrs(data, sz_ptr):
            i = 0
            for i, chunk in enumerate(util.chunk(data, sz_ptr)):
                yield int.from_bytes(chunk, endian)
                if not i % prg_interval:
                    progress(prg_interval)
            progress(i % prg_interval)
        pointers = {i: tuple(mkptrs(data[i:], ptr_bytes))
                    for i in range(ptr_bytes)}

    hits = []
    Hit = namedtuple('Hit', 'offset ml head')
    with pbar(len(data), title='searching') as progress:
        for offset, ptrs in pointers.items():
            log.info("looking for hits at starting offset %s", offset)
            for i in range(len(ptrs)):
                length = _matchlength(
                        ptrs[i:i+count*2],
                        coverage,
                        align
                        )
                uniques = len(set(ptrs[i:i+length]))
                if length > threshold and uniques > threshold:
                    abs_start = HexInt(offset + i * ptr_bytes)
                    log.info("reasonable match found at 0x%X (%s length)",
                             abs_start, length)
                    head = ', '.join(str(HexInt(p, ptr_bytes*8))
                                     for p in ptrs[i:i+5])
                    hits.append(Hit(abs_start, length, head))
                if not i % prg_interval:
                    progress(prg_interval)
            progress(i % prg_interval)
    if not hits:
        print("no apparent indexes found")
        sys.exit(2)

    print("possible index starts:")
    fmt = "{}\t{} items\t[{}...]"
    print(fmt.format(*hits[0]))
    for a, b in util.pairwise(hits):  # pylint: disable=invalid-name
        if b.ml > a.ml or b.offset != a.offset + ptr_bytes:
            print(fmt.format(*b))


def search_strings(args):
    """ Search for strings in a rom """
    rom = _loadrom(args.rom, args.map)
    log.info("searching for valid strings using encoding '%s'", args.encoding)
    data = rom.data.bytes
    codec = rom.map.ttables[args.encoding].clean
    offset = 0
    vowels = re.compile(r'[AEIOUYaeiouy]')
    special = re.compile(r'\[[A-Z0-9]+\]')
    nonword = re.compile(r'\W+')
    pbar = partial(alive_bar, disable=not args.progress, enrich_print=False)

    def report_hit(string, consumed, minlen=3):  # FIXME: take minlen from args
        """ Check whether a decoded string counts as a hit

        Tries to determine whether a string is Actual Text rather than
        coincidentally decodable. At the moment it does so by stripping
        whitespace and control characters, then checking if the result is
        >minlen characters and contains at least one vowel.
        """
        string = special.sub('', string)
        string = nonword.sub('', string)
        string = string.strip()
        return (len(string) > minlen
                and consumed > minlen
                and vowels.search(string))

    with pbar(len(data), title='searching for strings') as progress:
        while offset < len(data):
            string, consumed = codec.decode(data[offset:], 'stop')
            if report_hit(string, consumed):
                print(f"0x{offset:X}\t{string}")
            offset += consumed
            progress(consumed)


def search_values(args):
    """ Search for known values in a ROM """
    rom = _loadrom(args.rom, args.map)
    data = rom.data.bytes
    size = int(args.size, 0)
    endian = args.endian
    expected = [int(v, 0) for v in args.expected]
    pbar = partial(alive_bar, disable=not args.progress, enrich_print=False)

    def value(offset):
        return int.from_bytes(data[offset:offset+size], endian)

    with pbar(len(data)) as progress:
        for offset in range(len(data)):
            actual = (value(offset+i*size) for i in range(len(expected)))
            if all(e == a for e, a in zip(expected, actual)):
                print(f"0x{offset:X}")
            progress()


def cmd_dirs(args):  # pylint: disable=unused-argument
    """ Print romtool directory paths

    Usage: romtool dirs [--help]

    Romtool keeps its configuration, data files, and logs in user directories
    that vary between platforms. This command prints the directories used on
    your current platform.
    """
    ad = AppDirs("romtool")  # pylint: disable=invalid-name
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
    """ Set up logging """
    key = ('debug' if args.debug
           else 'verbose' if args.verbose
           else 'quiet' if args.quiet
           else 'default')
    logconf = config.load('logging.yaml')
    logging.config.dictConfig(logconf[key])


def main(argv=None):
    """ Entry point for romtool."""
    ts_start = datetime.now()
    args = Args(docopt(__doc__.strip(), argv,
                version=version, options_first=True))
    initlog(args)
    util.debug_structure(args)
    util.debug_structure(dict(args.items()))

    expected = (FileNotFoundError, NotImplementedError, RomtoolError)

    try:
        cmd = globals().get(f'cmd_{args.command}')
        if not cmd:
            log.critical("'%s' is not a valid command; see romtool --help",
                         args.command)
            sys.exit(1)
        args = Args(docopt(getdoc(cmd), argv, version=version))
        if args.debug:
            expected = ()  # dump all exceptions in debug mode
        initlog(args)  # because log opts may come before or after the command
        cmd(args)
        log.debug("total running time: %s", datetime.now()-ts_start)
    except KeyboardInterrupt:
        log.error("keyboard interrupt; aborting")
        sys.exit(2)
    except expected as ex:
        # I'd rather not separately handle this in every command that uses it.
        # Let exceptions provide an extended message. There has to be a better
        # way to do this.
        if hasattr(ex, 'log'):
            ex.log()
        else:
            log.error(ex)
        sys.exit(2)
    except Exception as ex:  # pylint: disable=broad-except
        # I want to break this into a function and use it as excepthook, but
        # every time I try it doesn't work.
        log.exception(ex)
        if not args.pdb:
            sys.exit(2)
        print("\n\nCRASH -- UNHANDLED EXCEPTION")
        msg = ("Starting debugger post-mortem. If you got here by "
               "accident (perhaps by trying to see what --pdb does), "
               "you can get out with 'quit'.\n\n")
        print("\n{}\n\n".format("\n".join(textwrap.wrap(msg))))
        pdb.post_mortem()
        sys.exit(2)


if __name__ == "__main__":
    main()
