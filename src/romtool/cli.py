"""romtool

Usage:
    romtool dump [options] <rom> <moddir> [<patches>...]
    romtool build [options] <rom> <input>...

Commmands:
    dump                Dump all known data from a ROM to tsv files
    build               Construct a patch from input files

Options:
    -i, --interactive   Prompt for confirmation on destructive operations
    -n, --dryrun        Show what would be done, but don't do it
    -f, --force         Never ask for confirmation
    -o, --out PATH      Output file or directory. Detects type by extension

    -m, --map           Manually specify rom map
    -S, --sanitize      Include internal checksum updates in patches

    -h, --help          Print this help
    -V, --version       Print version and exit
    -v, --verbose       Verbose output
    -D, --debug         Even more verbose output
    --pdb               Start interactive debugger on crash
"""

import os
import sys
import logging
import argparse
import textwrap
from itertools import chain
from addict import Dict

import yaml
from docopt import docopt

import romtool.commands
from romtool import util
from romtool.util import pkgfile
from romtool.version import version
from . import commands

log = logging.getLogger(__name__)

class Args(Dict):
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
    def flags(self):
        return [k for k, v in self.items()
                if k.startswith('-') and isinstance(v, bool)]

    @property
    def options(self):
        return [k for k, v in self.items()
                if k.startswith('-') and not isinstance(v, bool)]

    @property
    def commands(self):
        return [k for k in self if k.isalnum()]

    @property
    def arguments(self):
        return [k for k in self if k.startswith('<')]

    @property
    def command(self):
        return next(k for k, v in self.items()
                    if k in self.commands
                    and v)


def main(argv=None):
    """ Entry point for romtool."""
    args = Args(docopt(__doc__, argv, version=version))

    if args.version:
        print(version)
        sys.exit(0)

    # Set up logging
    logging.basicConfig(format="%(levelname)s\t%(filename)s:%(lineno)s\t%(message)s")
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    util.debug_structure(args)

    # If no subcommand supplied, print help.
    if not hasattr(args, 'func'):
        topparser.print_help()
        sys.exit(1)

    # Probable crash behavior: Normally, log exception message as CRITICAL. If
    # --debug is enabled, also print the full trace. If --pdb is enabled, print
    # the trace and also break into the debugger.
    try:
        getattr(commands, args.command)(args)
    except FileNotFoundError as e:
        logging.critical(str(e))
        sys.exit(2)
    except Exception as e:
        # logging.critical("Unhandled exception: '{}'".format(str(e)))
        logging.exception(e)
        if args.pdb:
            import pdb, traceback
            print("\n\nCRASH -- UNHANDLED EXCEPTION")
            msg = ("Starting debugger post-mortem. If you got here by "
                   "accident (perhaps by trying to see what --pdb does), "
                   "you can get out with 'quit'.\n\n")
            print("\n{}\n\n".format("\n".join(textwrap.wrap(msg))))
            pdb.post_mortem()

if __name__ == "__main__":
    main()
