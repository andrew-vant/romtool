import os
import logging
from pathlib import Path
from functools import partial

import yaml
from addict import Dict
from appdirs import user_config_dir


CFG_DFLT = Path(__file__).resolve().parent
CFG_USER = user_config_dir('romtool')  # Default config search path
CFG_EVAR = 'ROMTOOL_CONFIG_DIR'        # Environment var overrides default

_LOADED = Dict()

def known_files():
    return [p.name for p
            in CFG_DFLT.iterdir()
            if p.suffix == '.yaml']

def load(name, search_paths=None, refresh=False):
    """ Load a yaml config file

    The file will be merged with (and override) any defaults for the same file.
    Search paths can be specified via an environment variable, or as an
    argument.

    Repeated calls will not reload the file unless `refresh` is given.
    """
    if name in _LOADED and not refresh:
        return _LOADED[name]
    if name not in known_files():
        raise ValueError(f"not a known config file: {name}")
    if search_paths is None:
        userdir = Path(os.environ.get(CFG_EVAR) or CFG_USER)
        search_paths = [CFG_DFLT, userdir]

    log = logging.getLogger(__name__)
    loadyaml = partial(yaml.load, Loader=yaml.SafeLoader)
    dataset = Dict()
    for path in search_paths:
        try:
            with open(Path(path, name)) as f:
                dataset.update(loadyaml(f))
        except FileNotFoundError as ex:
            log.debug(ex)
        except IOError as ex:
            log.warning(ex)
    _LOADED[name] = dataset
    return dataset
