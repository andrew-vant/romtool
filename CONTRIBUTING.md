# Developing

This is sparse because it's a one-man show for now, so these are mostly
notes to myself. I'll fill it out if someone wants to contribute and
runs into trouble.

## TODO

* sdist
* fix nointro wart -- `pip install -e .` for development won't do the
  right thing unless nointro.tsv has already been built.

## Prerequisites

Packages needed on Debian/Ubuntu systems:

* build-essential
* pytest
* python3
* python3-dev
* python3-setuptools
* python3-setuptools-scm
* tox
* (optional) python3-bitarray
  * this is to avoid having to compile it during pip install

I am not sure of the equivalents for other distributions.

Windows builds additionally require:

* The version of python specified in pynsist.in.cfg
* The MSVC C++ build tools (see below)
* pynsist (to build intaller packages)
* GNU Make

Windows builds require the MSVC C++ build tools (to build dependencies'
C extensions), and finding them was a giant pain. Google suggests they
once existed as a standalone package, but at time of writing, the only
way I've been able to get them is as part of [Visual Studio Community
Edition][vsce]. They appear on the Individual Components tab when
installing or modifying.

## Setting up a build environment

1. Install the prerequisites above.
2. Clone the git repository
3. In the base of the repository, run `pip install -e .`
4. Run tests: `pytest`.

## Building a release

1. Run full tests: `tox`.
2. Tag the commit to be released: `git tag -a`
3. `make` to build the linux packages
4. **(Windows)**: `make winpkg` to build the windows installer.

**TODO**: directions for uploading

[vsce]: https://visualstudio.microsoft.com/downloads/
