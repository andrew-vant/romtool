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


class ArgParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(self, *args, **kwargs)
        self._posargs = {}
        self._optargs = {}
        self._flags = {}

    @property
    def _all_known_args(self):
        return list(chain(self._posargs, self._optargs, self._flags))

    def add_argument(self, *args, **kwargs):
        action = super().add_argument(*args, **kwargs)
        where = (self._posargs if not action.option_strings
                 else self._flags if action.nargs == 0
                 else self._optargs)
        where[action.dest] = action
        return action

    def convert_arg_line_to_args(self, arg_line):
        # This would be easier if we could hook file loading itself...
        if not arg_line or arg_line.startswith('#'):
            return []  # Skip empty lines and comments
        elif ':' not in arg_line:
            raise ValueError(f"Malformed argument in file args: '{arg_line}'")

        arg, value = arg_line.split(':', 1)

        # Might as well accept options with or without prefix.
        if arg.startswith('--'):
            arg = arg[2:]
        value = value.strip()

        # Unknown args are probably intended for other subcommands.
        if arg not in self._all_known_args:
            log.debug("Ignoring unknown argument '%s'", arg)
            return []
        elif arg not in self._posargs:
            arg = '--' + arg

        return [arg.strip(), value.strip()]


def parser_setup(parser, spec, defaults):
    """ Create parser arguments from an args.yaml spec

    This is split out to make it easy to add the global argument set to
    each subparser.

    FIXME: that is what `parents` is for. Also, this setup only "works" by
    making all arguments optional, which loses the default argparse error
    checking. Better solution: parse twice, once with everything set to
    optional (to get -v, --debug, and especially --conf), then load the conf
    file, then re-parse with the conf file contents populating defaults.

    This might actually be a good feature to submit upstream. a conffile_arg
    option to argumentparser (and a conffile_callback that is expected to read
    the file and pass back a defaults dict -- perhaps defaulting to "assume
    configparser format)

    A similar use_envvars option might be nice too.

    Project: arg library that implements /etc /home envvar cli-conffile
    cli-args cascading of options. Interface similar to argparse, maybe just
    passes arguments to argparse and/or inherits argumentparser directly. User
    provides option spec as dict, along with a mapping of file types to loader
    functions.

    What about subcommands? Should the option spec be a nested dict, one for
    each subcommand, or should the ui be one call/construction per subcommand?
    (probably one call per subcommand -- avoids complexity)

    Read confs from json or configparser by default; read yaml if available
    (and suggest it if it's not with loglevel:error).

    Should spec format match the argparse interface? That would make
    implementation easier, at the cost of duplication (same arg specced
    multiple times in different commands...but wait, yaml has anchors!)

    How to map envvars to options? (PROG_[OPTION], probably)
    """

    argtypes = yaml.safe_load("""
    args: {}
    args+:
      nargs: '+'
    opts: {}
    ropts:
      action: append
    flags:
      action: store_true
    """)

    for argtype, metaargs in argtypes.items():
        for name, desc in spec.get(argtype, {}).items():
            names = name.split("|")
            conf_key = names[-1].lstrip("-")  # Turn `--argname` into `argname`
            default = defaults.get(conf_key, None)
            if argtype == "args" and default is not None:
                # Prevent complaints about missing positional args if a
                # default was provided
                metaargs['nargs'] = '?'
            parser.add_argument(*names, **metaargs, default=default, help=desc)

def conf_load(argv):
    """ Get the --conf argument and do the needful with it

    This copies argv before parsing, so it doesn't actually consume
    args. It returns the dict from the --conf file, or an empty dict if
    none was provided.
    """
    argv = argv.copy()
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--conf")
    filename = parser.parse_known_args(argv)[0].conf

    # If conf wasn't provided, return an empty dict
    if not filename:
        return {}

    with open(filename) as f:
        options = util.loadyaml(f)
    # Command line opts get tilde expansion automatically. If we want
    # it, we have to do it ourselves.
    options = {k: os.path.expanduser(v) for k, v in options.items()}
    return options


def debug_input(conffile_dict, args_object):
    """ Print the effective arguments and their sources """
    fmt = "%s:\t%s\t(%s)"
    for k, v in vars(args_object).items():
        if v is None:
            source = "default"
        elif v == conffile_dict.get(k, None):
            source = "conf"
        else:
            source = "args"
        log.debug(fmt, k, v, source)


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
