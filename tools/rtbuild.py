#!/usr/bin/python3

""" Build supporting files for romtool

At the moment this just turns the datomatic xml files into tsvs to put in the
wheel.
"""

import csv
import logging
import os
import sys
import xml.etree.ElementTree as ET
from configparser import ConfigParser
from inspect import getdoc
from dataclasses import dataclass, fields, asdict
from functools import partialmethod
from argparse import ArgumentParser, FileType
from os.path import splitext
from itertools import chain
from pathlib import Path
from platform import python_version

from appdirs import AppDirs

log = logging.getLogger()
csv.register_dialect(
        'tsv',
        delimiter='\t',
        lineterminator=os.linesep,
        quoting=csv.QUOTE_NONE,
        doublequote=False,
        quotechar=None,
        strict=True,
        )


@dataclass
class DatRom:
    """ Container for the datomatic rom data we're interested in """
    name: str
    ext: str = None
    size: int = None
    crc: str = None
    md5: str = None
    sha1: str = None

    def __lt__(self, other):
        return (self.ext, self.name) < (other.ext, other.name)


class Datomatic:
    hashes = ['crc', 'md5', 'sha1']
    def __init__(self, source):
        self.tree = ET.parse(source)

    @property
    def roms(self):
        fnames = [f.name for f in fields(DatRom)]
        for node in self.tree.findall('./game/rom'):
            kwargs = {k: v for k, v in node.attrib.items() if k in fnames}
            kwargs['name'], kwargs['ext'] = splitext(kwargs['name'])
            yield DatRom(**kwargs)


class CLIParser(ArgumentParser):
    """ Customized parser with convenience aliases """
    addarg = ArgumentParser.add_argument
    addflag = partialmethod(addarg, action='store_true')

    @staticmethod
    def addsub(sp, func, *args, **kwargs):
        if 'help' not in kwargs:
            kwargs['help'] = getdoc(func)
        sub = sp.add_parser(*args, **kwargs)
        sub.set_defaults(func=func)
        return sub


def cmd_datomatic(args):
    """ Build rom db from datomatic files """
    def load_infile(infile):
        log.info("reading %s", infile.name)
        with open(infile, 'r') as f:
            dm = Datomatic(f)
        for i, dr in enumerate(dm.roms):
            yield dr
        log.info("found %s rom definitions", i)

    datpath = Path(AppDirs("romtool").user_data_dir, 'datomatic')
    for line in args.file_list or []:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        args.infile.append(Path(datpath, line))

    log.debug("sorting output")
    data = sorted(chain.from_iterable(load_infile(f) for f in args.infile))
    log.info("writing to %s", args.outfile.name)
    headers = [field.name for field in fields(DatRom)]
    writer = csv.DictWriter(args.outfile, headers, dialect='tsv')
    writer.writeheader()
    for item in data:
        writer.writerow(asdict(item))


def cmd_nsist(args):
    from setuptools_scm import get_version
    cfg = ConfigParser()
    cfg.read(args.infile)
    cfg['Application']['version'] = get_version()
    cfg['Python']['version'] = python_version()
    cfg.write(args.outfile)


def main(argv=None):
    """ build script helper """
    if argv is None:
        argv = sys.argv[1:]
    parser = CLIParser(description="build script helper")
    sp = parser.add_subparsers(dest='cmd')
    dom = parser.addsub(sp, cmd_datomatic, 'datomatic')
    dom.addarg("infile", nargs='*',
                help="input file(s) (default stdin)")
    dom.addarg("-f", "--file-list", type=FileType('r'),
                help="get infile arguments from file")
    dom.addarg("-o", "--outfile", type=FileType('w'), default=sys.stdout,
                help="output file (default stdout)")
    nst = parser.addsub(sp, cmd_nsist, 'nsis')
    nst.addarg("infile", help="yaml metadata file")
    nst.addarg("-o", "--outfile", type=FileType('w'), default=sys.stdout,
                help="output file (default stdout)")
    for p in [parser, dom, nst]:
        p.addflag("-v", "--verbose", help="verbose output")
        p.addflag("-D", "--debug", help="even more verbose output")
        p.addflag("--pdb", help="start debugger on crash")
    args = parser.parse_args(argv)

    loglevel = (logging.DEBUG if args.debug
                else logging.INFO if args.verbose
                else logging.WARNING)
    logging.basicConfig(level=loglevel, format="%(levelname)s\t%(message)s")
    log.debug("debug logging enabled")
    try:
        args.func(args)
    except FileNotFoundError as ex:
        log.error(ex)
        sys.exit(2)
    except Exception as ex:  # pylint: disable=broad-except
        log.exception(ex)
        if not args.pdb:
            sys.exit(2)
        import pdb
        pdb.post_mortem()
        sys.exit(2)

if __name__ == '__main__':
    main()
