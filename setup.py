#!/usr/bin/env python3

import os
import os.path
from os.path import dirname, join
from setuptools import setup, find_packages
from pprint import pprint


def read(relative_path):
    with open(join(dirname(__file__), relative_path)) as f:
        return f.read()

dependencies = ["bitstring>=3.1.3",
                "patricia-trie>=10",
                "pyyaml>=3.10"]

setup(name="romlib",
      version="0.1.0a1",
      packages=find_packages("src") + ["romlib-maps"],
      package_dir={'': "src", "romlib-maps": "data/maps"},
      include_package_data=True,
      install_requires=dependencies,
      tests_require=['tox'],
      author="Andrew Vant",
      author_email="ajvant@gmail.com",
      description="Library and tool for manipulating video game ROMs.",
      long_description=read("README.md"),
      keywords="rom roms snes",
      url="https://github.com/andrew-vant/romlib",
      test_suite="tests",
      entry_points={"console_scripts": ["romtool = romtool:main"]},
      )
