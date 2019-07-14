import os
import sys
import logging
import argparse
import textwrap

import yaml

import romtool.commands
from romtool import util
from romtool.util import pkgfile

def parser_setup(parser, spec):
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

def load_conf_file(filename):
    """ Load a project conf file """
    options = {}
    try:
        with open(args.conf) as conffile:
            options.update(yaml.load(conffile, Loader=yaml.SafeLoader))
    except FileNotFoundError as e:
        logging.error("Failed to load conf file. " + str(e))
        exit(2)
    logging.debug("Loaded args:")
    for arg, default in defaults.items():
        logging.debug("%s: %s", arg, default)
    return options


def main():
    """ Entry point for romtool."""

    # It's irritating to keep all the help information as string literals in
    # the source, so argument details are loaded from a yaml file that's
    # easier to maintain. See args.yaml for the actual available arguments.
    # FIXME: After some thought, probably better to use one big string in the
    # source. :-(

    # Do this here so it doesn't happen implicitly later
    # FIXME: replace with dictConfig. Set root in dictconfig, log
    # individual files with module name as logger name.
    logging.basicConfig()

    with open(pkgfile("args.yaml")) as argfile:
        argspecs = yaml.load(argfile, Loader=yaml.SafeLoader)

    # Set up CLI parser
    # FIXME: function this out more. Or make a custom argumentparser
    # class?
    globalargs = argspecs.pop("global")
    topparser = argparse.ArgumentParser(**globalargs.get('spec', {}))
    parser_setup(topparser, globalargs)

    subparsers = topparser.add_subparsers(title="commands")
    for cmd, argspec in sorted(argspecs.items()):
        sp = subparsers.add_parser(cmd, conflict_handler='resolve',
                                   **argspec.get("spec", {}))
        parser_setup(sp, argspec)
        parser_setup(sp, globalargs)
        sp.set_defaults(func=getattr(romtool.commands, cmd))

    # Parse arguments
    args = topparser.parse_args()

    # Set up logging
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Read and apply project conf if supplied.
    if args.conf:
        logging.info("Loading conf file '%s'", args.conf)
        conf = load_conf_file(args.conf)
        for k, v in conf.items():
            # This is supposed to fill in arguments from the conf file
            # iff they were not given on the cli.
            argdict = args.__dict__
            if k in argdict and argdict[k] is None:
                argdict[k] = v

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
