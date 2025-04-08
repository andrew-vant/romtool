""" Romtool configuration-handling functions. """

import os
import logging
from importlib.resources import files
from pathlib import Path
from functools import cache, partial

import yaml
from addict import Dict
from appdirs import user_config_dir


_loadyaml = partial(yaml.load, Loader=yaml.SafeLoader)
CFG_USER = user_config_dir('romtool')  # Default config search path
CFG_EVAR = 'ROMTOOL_CONFIG_DIR'        # Environment var overrides default
DEFAULTS = {f.name: _loadyaml(f.read_text())
            for f in files(__name__).iterdir()
            if f.suffix == '.yaml'}


@cache
def load(name, search_paths=None):
    """ Load a yaml config file

    The file will be merged with (and override) any defaults for the same file.
    Search paths can be specified via an environment variable, or as an
    argument.

    The contents of config files are cached, and repeated calls will not
    reload them. To force a reload, call load.cache_clear().
    """
    if name not in DEFAULTS:
        raise ValueError(f"not a known config file: {name}")
    if search_paths is None:
        search_paths = [Path(os.environ.get(CFG_EVAR) or CFG_USER)]

    log = logging.getLogger(__name__)
    loadyaml = partial(yaml.load, Loader=yaml.SafeLoader)
    dataset = Dict()
    dataset.update(DEFAULTS[name])
    for path in search_paths:
        try:
            with open(Path(path, name), encoding='utf8') as f:
                dataset.update(loadyaml(f))
        except FileNotFoundError as ex:
            log.debug(ex)
        except IOError as ex:
            log.warning(ex)
    return dataset
