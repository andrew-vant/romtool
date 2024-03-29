#!/usr/bin/env python3

import os
import os.path
from os.path import dirname, join
from setuptools import setup, find_packages
from pathlib import Path


readme = Path(__file__).parent / "README.md"
# Keep these alphabetical, if possible
deps = [
    "addict>=2",
    "alive-progress>=2",
    "anytree",
    "appdirs",
    "asteval",
    "bitarray>=1.5.0",
    "docopt",
    "jinja2",
    "more-itertools",
    "patricia-trie>=10",
    "pyyaml>=3.10",
    ]
bdeps = [
    'setuptools-scm>=3.3.0',
    'wheel',
    ]
tdeps = [
    'pytest-subtests',
    'tox',
    ]
scmver = {
    'write_to': 'src/romtool/version.py',
    'fallback_version': 'UNKNOWN',
    }
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Natural Language :: English",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Topic :: Software Development :: Libraries :: Python Modules"
    ]

setup(name="romtool",
      packages=find_packages("src") + ['romtool.maps'],
      package_dir={'': "src"},
      include_package_data=True,
      install_requires=deps,
      setup_requires=bdeps,
      tests_require=tdeps,
      use_scm_version=scmver,
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
