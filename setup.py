#!/usr/bin/env python3

import os
import os.path
from os.path import dirname, join
from setuptools import setup, find_packages
from pathlib import Path
from warnings import warn


readme = Path(__file__).parent / "README.md"
# Keep these alphabetical, if possible

def bapkg():
    """ Figure out what bitarray dependency to use

    Bitarray has no Windows wheels, and for end users, arranging matters so it
    can install its C extensions is non-trivial. A third-party re-package
    called `bitarray-hardbyte` is available, and works fine, but will conflict
    with any other packages using the "real" bitarray.

    For now I'm handling the problem by depending on bitarray-hardbyte iff
    bitarray isn't pre-installed.
    """
    try:
        import bitarray
    except ModuleNotFoundError:
        bitarray = None
    if bitarray or os.name != 'nt':
        return "bitarray"
    warn("Due to issues installing one of romtool's dependencies (bitarray) "
         "on Windows, the third-party bitarray-hardbyte package will be "
         "used instead. This may cause conflicts in future if you install "
         "another package that also uses bitarray. ")
    return "bitarray-hardbyte"

deps = [
        f"{bapkg()}>=1.5.0",  # careful editing this
        "addict>=2",
        "anytree",
        "appdirs",
        "asteval",
        "docopt",
        "patricia-trie>=10",
        "pyyaml>=3.10",
        ]

builddeps = [
        'setuptools-scm>=3.3.0',
        'wheel',
        ]

scm_version_options = {
        'write_to': 'src/romtool/version.py',
        'fallback_version': 'UNKNOWN',
        }
classifiers = ["Development Status :: 3 - Alpha",
               "Intended Audience :: Developers",
               "Natural Language :: English",
               "Operating System :: OS Independent",
               "Programming Language :: Python :: 3",
               "Topic :: Software Development :: Libraries :: Python Modules"]

setup(name="romtool",
      packages=find_packages("src") + ['romtool.maps'],
      package_dir={'': "src"},
      include_package_data=True,
      install_requires=deps,
      setup_requires=builddeps,
      use_scm_version=scm_version_options,
      tests_require=['tox', 'pytest-subtests'],
      author="Andrew Vant",
      author_email="ajvant@gmail.com",
      description="Library and tool for manipulating video game ROMs.",
      long_description=readme.read_text(),
      long_description_content_type='text/markdown',
      classifiers=classifiers,
      zip_safe=False,
      keywords="rom roms snes",
      url="https://github.com/andrew-vant/romlib",
      test_suite="tests",
      entry_points={"console_scripts": ["romtool = romtool.cli:main"]},
      )
