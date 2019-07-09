import os
import sys
import logging
import argparse
import textwrap

import yaml

from romtool import commands
from romtool import util
from romtool.util import pkgfile

def parser_setup(parser, spec):
    """ Create parser arguments from an args.yaml spec

    This is split out to make it easy to add the global argument set to
    each subparser.
    """

    argtypes = yaml.safe_load("""
    args:
      nargs: '?'
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
            parser.add_argument(*names, **metaargs, help=desc)

def main():
    """ Entry point for romtool."""

    # It's irritating to keep all the help information as string literals in
    # the source, so argument details are loaded from a yaml file that's
    # easier to maintain. See args.yaml for the actual available arguments.
    # FIXME: After some thought, probably better to use one big string in the
    # source. :-(

    logging.basicConfig()  # Do this here so it doesn't happen implicitly later

    with open(pkgfile("args.yaml")) as argfile:
        argspecs = yaml.load(argfile, Loader=yaml.SafeLoader)

    # Set up the toplevel parser. This takes some magic. The conf file arg must
    # be parsed before any others, and --help must be suppressed until after
    # said processing. The simplest way I could find to do that is to create a
    # "dummy" parser.
    #
    # For some reason, checking for -v here breaks concatenated short args,
    # e.g.  -vf doesn't work. I think I can't mix concatenated args across
    # multiple parsings, which means I can't support verbose here, only debug
    # (which has no short form)

    bootstrapper = argparse.ArgumentParser(add_help=False)
    bootstrapper.add_argument("-c", "--conf")
    bootstrapper.add_argument("--debug", action="store_true")
    args, remainingargs = bootstrapper.parse_known_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    globalargs = argspecs.pop("global")
    topparser = argparse.ArgumentParser(**globalargs.get('spec', {}))
    parser_setup(topparser, globalargs)

    # Process the conf file if there is one; any options given in it become
    # defaults, but can still be overridden on the rest of the command line.
    defaults = {}
    if args.conf:
        logging.debug("Loading conf file '%s'", args.conf)
        try:
            with open(args.conf) as conffile:
                defaults.update(yaml.load(conffile, Loader=yaml.SafeLoader))
        except FileNotFoundError as e:
            logging.error("Failed to load conf file. " + str(e))
            exit(2)
        logging.debug("Loaded args:")
        for arg, default in defaults.items():
            logging.debug("%s: %s", arg, default)
    topparser.set_defaults(**defaults)

    # Create the subparsers
    subparsers = topparser.add_subparsers(title="commands")
    for command, argspec in sorted(argspecs.items()):
        subparser = subparsers.add_parser(command,
                                          conflict_handler='resolve',
                                          **argspec.get("spec", {}))
        parser_setup(subparser, argspec)
        parser_setup(subparser, globalargs)
        subparser.set_defaults(func=getattr(commands, command), **defaults)

    # Parse remaining arguments and add the results to the args namespace.
    args = topparser.parse_args(args=remainingargs, namespace=args)

    # Set up logging
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # If no subcommand supplied, print help.
    if not hasattr(args, 'func'):
        topparser.print_help()
        sys.exit(1)

    # Probable crash behavior: Normally, log exception message as CRITICAL. If
    # --debug is enabled, also print the full trace. If --pdb is enabled, print
    # the trace and also break into the debugger.
    try:
        args.func(args)
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
