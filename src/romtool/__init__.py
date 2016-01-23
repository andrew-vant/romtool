#!/usr/bin/python3

import argparse
import sys
import hashlib
import logging
import os
from pprint import pprint
from itertools import chain
from collections import OrderedDict
import yaml

import romlib


class RomDetectionError(Exception):
    pass


def detect(romfile):
    with open("hashdb.txt") as hashdb, open(romfile, "rb") as rom:
        # FIXME: Reads whole file into memory, likely to fail on giant images,
        # e.g cds/dvds.
        logging.info("Detecting ROM map for: %s.", romfile)
        romhash = hashlib.sha1(rom.read()).hexdigest()
        logging.info("sha1 hash is: %s.", romhash)
        try:
            line = next(line for line in hashdb if line.startswith(romhash))
        except StopIteration:
            msg = "sha1 hash for {} not in hashdb.".format(romfile)
            raise RomDetectionError(msg)

        name = line.split(maxsplit=1)[1].strip()
        logging.info("ROM map found: %s", name)
        return "specs/{}".format(name)


def dump(args):
    if args.map is None:
        args.map = detect(args.rom)
    rmap = romlib.RomMap(args.map)
    msg = "Dumping data from %s to %s using map %s."
    logging.info(msg, args.rom, args.datafolder, args.map)
    with open(args.rom, "rb") as rom:
        rmap.dump(rom, args.datafolder, allow_overwrite=args.force)
    logging.info("Dump finished.")


def makepatch(args):
    if args.map is None:
        args.map = detect(args.rom)
    rmap = romlib.RomMap(args.map)
    msg = "Creating patch for %s from data at %s using map %s."
    logging.info(msg, args.rom, args.datafolder, args.map)
    changes = rmap.changeset(args.datafolder)
    with open(args.rom, "rb") as rom:
        patch = romlib.Patch(changes, rom)
    patchfunc = _patch_func(args.patchfile, patch, True)
    mode = _patch_mode(args.patchfile, True)
    with open(args.patchfile, mode) as patchfile:
        patchfunc(patchfile)
    logging.info("Patch created at %s.", args.patchfile)
    logging.info("There were %s changes.", len(patch.changes))


def diffpatch(args):
    with open(args.original, "rb") as original:
        with open(args.modified, "rb") as changed:
            patch = romlib.Patch.from_diff(original, changed)
    patchfunc = _patch_func(args.patchfile, patch, True)
    mode = _patch_mode(args.patchfile, True)
    with open(args.patchfile, mode) as pfile:
        patchfunc(pfile)


def _patch_func(path, patch=None, writing=False):
    """ Figure out what function to use to convert to/from a given format."""
    prefix = "to" if writing else "from"
    extension = os.path.splitext(path)[-1]
    func = "{}_{}".format(prefix, extension.lstrip("."))
    return getattr(patch, func) if writing else getattr(romlib.Patch, func)


def _patch_mode(path, writing=False):
    """ Figure out what file mode to use for a given format."""
    mode = "w" if writing else "r"
    mode += "t" if path.endswith("t") else "b"
    return mode


def convert(args):
    raise NotImplementedError("Patch conversion subcommand not ready yet.")


def _add_yaml_omap():
    def omap_constructor(loader, node):
        return OrderedDict(loader.construct_pairs(node))
    yaml.add_constructor("!omap", omap_constructor)


def main():
    # It's irritating to keep all the help information as string literals in
    # the source, so argument details are loaded from a yaml file that's
    # easier to maintain. See args.yaml for the actual available arguments.
    # FIXME: After some thought, probably better to use one big string in the
    # source. :-(
    _add_yaml_omap()
    path = os.path.realpath(__file__)
    youarehere = os.path.dirname(path)
    argspath = os.path.join(youarehere, "args.yaml")
    with open(argspath) as argfile:
        argdetails = yaml.load(argfile)

    def argument_setup(parser, details):
        # This utility function takes an argument set and adds it to a
        # parser. It's split out like this to make it easy to add the global
        # set to itself and each subparser.
        for name, desc in details.get("args", {}).items():
            names = name.split("|")
            parser.add_argument(*names, help=desc)
        for name, desc in details.get("opts", {}).items():
            names = name.split("|")
            parser.add_argument(*names, help=desc)
        for name, desc in details.get("flags", {}).items():
            names = name.split("|")
            parser.add_argument(*names, help=desc, action="store_true")

    topdetails = argdetails.pop("global")
    topparser = argparse.ArgumentParser(**topdetails.get('spec', {}))
    subparsers = topparser.add_subparsers(title="commands")
    argument_setup(topparser, topdetails)
    for command, details in sorted(argdetails.items()):
        subparser = subparsers.add_parser(command,
                                          conflict_handler='resolve',
                                          **details.get("spec", {}))
        subparser.set_defaults(func=globals()[command])
        argument_setup(subparser, details)
        argument_setup(subparser, topdetails)

    # Parse whatever came in.
    args = topparser.parse_args()

    # Set up logging.
    if getattr(args, "verbose", False):
        logging.basicConfig(level=logging.INFO)
    if getattr(args, "debug", False):
        logging.basicConfig(level=logging.DEBUG)

    # If no subcommand supplied, print help.
    if not hasattr(args, 'func'):
        topparser.print_help()
        sys.exit(1)

    # Pass the args on as appropriate
    args.func(args)

if __name__ == "__main__":
    main()
