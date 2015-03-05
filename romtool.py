#!/usr/bin/python3

import argparse
import sys
import hashlib
import romlib
import logging

class RomDetectionError(Exception):
    pass

def detect(romfile):
    with open("hashdb.txt") as hashdb, open(romfile, "rb") as rom:
        # FIXME: Reads whole file into memory, likely to fail on giant images,
        # e.g cds/dvds.
        logging.info("Detecting ROM map for: {}.".format(romfile))
        romhash = hashlib.sha1(rom.read()).hexdigest()
        logging.info("sha1 hash is: {}.".format(romhash))
        try:
            line = next(line for line in hashdb if line.startswith(romhash))
        except StopIteration:
            raise RomDetectionError("sha1 hash for {} not in hashdb.".format(romfile))

        name = line.split(maxsplit=1)[1].strip()
        logging.info("ROM map found: {}".format(name))
        return "specs/{}".format(name)

def dump(args):
    if args.map is None:
        args.map = detect(args.rom)
    rmap = romlib.RomMap(args.map)
    logging.info("Dumping data from {} to {} using map {}.".format(
                args.rom, args.datafolder, args.map))
    with open(args.rom, "rb") as rom:
        rmap.dump(rom, args.datafolder, allow_overwrite=args.force)
    logging.info("Dump finished.")

def makepatch(args):
    if args.map is None:
        args.map = detect(args.rom)
    rmap = romlib.RomMap(args.map)
    logging.info("Creating patch for {} from data at {} using map {}.".format(
                args.rom, args.datafolder, args.map))
    rmap.makepatch(args.rom, args.datafolder, args.patchfile)
    logging.info("Patch created at {}.".format(args.patchfile))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool for examining and modifying ROMs")
    subparsers = parser.add_subparsers(title="subcommands")

    # Arguments for dump subcommand.
    parser_dump = subparsers.add_parser('dump',
                                        description="Dump all known data to csv files.")
    parser_dump.set_defaults(func=dump)
    parser_dump.add_argument("rom", help="ROM file to dump from")
    parser_dump.add_argument("datafolder", help="Send output to this folder")
    parser_dump.add_argument("-m", "--map", help="Specify ROM map instead of autodetecting")
    parser_dump.add_argument("-f", "--force", action='store_true', 
                             help="overwrite existing destination files")
    parser_dump.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser_dump.add_argument("--debug", action="store_true", help="Print debug information")

    # Arguments for makepatch subcommand.
    parser_patch = subparsers.add_parser('makepatch',
                                         description="Construct IPS patch from modified files.")
    parser_patch.set_defaults(func=makepatch)
    parser_patch.add_argument("rom", help="ROM to generate patch against")
    parser_patch.add_argument("datafolder", help="Get input from this folder")
    parser_patch.add_argument("patchfile", help="Patch filename")
    parser_patch.add_argument("-m", "--map", help="Specify ROM map instead of autodetecting")
    parser_patch.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser_patch.add_argument("--debug", action="store_true", help="Print debug information")

    # Parse whatever came in.
    args = parser.parse_args()

    # Set up logging.
    if args.verbose is True:
        logging.basicConfig(level=logging.INFO)
    if args.debug is True:
	    logging.basicConfig(level=logging.DEBUG)

    # If no subcommand supplied, print help.
    if not hasattr(args, 'func'):
        parser.print_help()
        sys.exit(1)

    # Pass the args on as appropriate
    args.func(args)

