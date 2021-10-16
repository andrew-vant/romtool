"""romtool

A tool for examining and modifying ROMs

Usage:
    romtool --help
    romtool dump [options] <rom> <moddir> [<patches>...]
    romtool build [options] <rom> <input>...
    romtool apply <rom> <patches>...
    romtool diff <original> <modified>
    romtool fix <rom>
    romtool info <rom>
    romtool charmap <rom> <strings>...
    romtool convert <infile> <outfile>
    romtool initchg <rom> <filename>

Commmands:
    dump                Dump all known data from a ROM to `moddir`
    build               Construct a patch from input files
    apply               Apply patches to a ROM
    diff                Construct a patch by diffing two ROMs
    fix                 Fix bogus headers and checksums
    info                Print rom type information and metadata
    charmap             Generate a texttable from known strings
    convert             Convert a patch from one format to another
    initchg             Generate a starter changeset file.

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
import textwrap

from docopt import docopt
from addict import Dict

from romtool import util
from romtool.version import version
from . import commands

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
    fmt = '\t'.join(['%(levelname)s',
                     '%(filename)s:%(lineno)s',
                     '%(message)s'])
    level = (logging.DEBUG if args.debug
             else logging.INFO if args.verbose
             else logging.WARN)

    logging.basicConfig(format=fmt, level=level)


def main(argv=None):
    """ Entry point for romtool."""

    args = Args(docopt(__doc__, argv, version=version))
    initlog(args)
    util.debug_structure(args)

    try:
        getattr(commands, args.command)(args)
    except FileNotFoundError as ex:
        # I'd rather not separately handle this in every command that uses it.
        logging.error(ex)
        sys.exit(2)
    except Exception as ex:  # pylint: disable=broad-except
        # I want to break this into a function and use it as excepthook, but
        # every time I try it doesn't work.
        logging.exception(ex)
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
