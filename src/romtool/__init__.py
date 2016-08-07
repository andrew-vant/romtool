#!/usr/bin/python3

""" CLI frontend to romlib.

Performs as many functions useful to romhackers as I can come up with.
"""


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
    """ Indicates that we couldn't autodetect the map to use for a ROM."""
    pass


def detect(romfile, maproot=None):
    """ Detect the map to use with a given ROM.

    maproot -- A root directory containing a set of rom maps and a hashdb.txt
               file associating sha1 hashes with map names.
    """
    if maproot is None:
        maproot = _get_path("maps")

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
            msg = "sha1 hash for {} not in hashdb.".format(romfile)
            raise RomDetectionError(msg)

        name = line.split(maxsplit=1)[1].strip()
        logging.info("ROM map found: %s", name)
        return os.path.join(maproot, name)


def dump(args):
    """ Dump all known data from a ROM."""
    if args.map is None:
        args.map = detect(args.rom)
    rmap = romlib.RomMap(args.map)
    logging.info("Opening ROM file: %s", args.rom)
    with open(args.rom, "rb") as rom:
        data = rmap.read(rom)
    logging.info("Dumping ROM data")
    rmap.dump(data, args.datafolder, allow_overwrite=args.force)
    logging.info("Dump finished")


def build(args):
    """ Build a patch from a data set containing changes.

    Intended to be applied to a directory created by the dump subcommand.
    """
    if args.map is None and args.rom is None:
        raise ValueError("At least one of -r or -m must be provided.")
    if args.map is None:
        args.map = detect(args.rom)
    rmap = romlib.RomMap(args.map)
    msg = "Loading mod dir %s using map %s."
    logging.info(msg, args.moddir, args.map)
    data = rmap.load(args.moddir)
    patch = romlib.Patch(rmap.bytemap(data))
    _filterpatch(patch, args.rom)
    _writepatch(patch, args.out)


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


def _add_yaml_omap():
    """ Register the omap type with libyaml.

    I'm not actually sure this is necessary anymore. Pretty sure the
    list-of-pairs construction returns tuples that I can use to initialize an
    odict.
    """
    def omap_constructor(loader, node):
        """ libyaml constructor for ordered dictionaries."""
        return OrderedDict(loader.construct_pairs(node))
    yaml.add_constructor("!omap", omap_constructor)


def _get_path(subfile=None):
    """ Get the full path to the containing directory of this file.

    Optionally get a path to a file within same. This is a utility function to
    avoid having to do a bunch of distracting __file__ juggling.
    """
    # FIXME: should this go in util? Maybe not, nothing in romlib uses it.
    path = os.path.realpath(__file__)
    path = os.path.dirname(path)
    if subfile is not None:
        path = os.path.join(path, subfile)
    return path


def main():
    """ Entry point for romtool."""

    # It's irritating to keep all the help information as string literals in
    # the source, so argument details are loaded from a yaml file that's
    # easier to maintain. See args.yaml for the actual available arguments.
    # FIXME: After some thought, probably better to use one big string in the
    # source. :-(

    _add_yaml_omap()

    with open(_get_path("args.yaml")) as argfile:
        argdetails = yaml.load(argfile)

    def argument_setup(parser, details):
        """ Add arguments to a parser.

        This is split out to make it easy to add the global argument set to
        each subparser.
        """
        # FIXME: Should this be done with parent?
        for name, desc in details.get("args", {}).items():
            names = name.split("|")
            parser.add_argument(*names, help=desc)
        for name, desc in details.get("args+", {}).items():
            names = name.split("|")
            parser.add_argument(*names, nargs="+", help=desc)
        for name, desc in details.get("opts", {}).items():
            names = name.split("|")
            parser.add_argument(*names, help=desc)
        for name, desc in details.get("ropts", {}).items():
            names = name.split("|")
            parser.add_argument(*names, help=desc, action="append")
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
