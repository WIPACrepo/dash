#!/usr/bin/env python
"read or update a file holding a configuration name (e.g. ~/.active)"

from __future__ import print_function

import os

from locate_pdaq import find_pdaq_config


class NoNameException(Exception):
    "No configuration name has been set"


class CachedFile(object):
    """
    Manage pDAQ's run configuration name, in either ~/.active or
    in $PDAQ_CONFIG/.config
    """

    @classmethod
    def __get_cached_name_path(cls, use_active_config):
        "get the active or default cluster configuration"
        if use_active_config:
            return os.path.join(os.environ["HOME"], ".active")
        return os.path.join(find_pdaq_config(), ".config")

    @classmethod
    def __read_cache_file(cls, use_active_config):
        "read the single line of cached text"
        cluster_file = cls.__get_cached_name_path(use_active_config)
        try:
            with open(cluster_file, 'r') as fin:
                ret = fin.readline()
                if ret is not None:
                    ret = ret.rstrip('\r\n')
                if ret is None or ret == "":
                    return None
                return ret
        except:  # pylint: disable=bare-except
            return None

    @classmethod
    def clear_active_config(cls):
        "delete the active cluster name"
        active_name = cls.__get_cached_name_path(True)
        if os.path.exists(active_name):
            os.remove(active_name)

    @classmethod
    def get_config_to_use(cls, cmdline_config, use_fallback_config,
                          use_active_config):
        "Determine the name of the configuration to use"
        if cmdline_config is not None:
            cfg = cmdline_config
        else:
            cfg = cls.__read_cache_file(use_active_config)
            if cfg is None and use_fallback_config:
                cfg = 'sim-localhost'

        return cfg

    @classmethod
    def write_name_to_cache_file(cls, name, write_active_config=False):
        "write this config name to the appropriate cache file"
        cached_name_path \
          = cls.__get_cached_name_path(write_active_config)

        with open(cached_name_path, 'w') as fin:
            print(name, file=fin)


class CachedConfigName(CachedFile):
    "Manage a file which caches a configuration name"

    def __init__(self):
        "Initialize instance variables"
        self.__config_name = None

    @property
    def config_name(self):
        "get the configuration name to write to the cache file"
        return self.__config_name

    def set_name(self, name):
        "Set the configuration name"
        self.__config_name = name

    def write_cache_file(self, write_active_config=False):
        "write this config name to the appropriate cache file"
        if self.__config_name is None:
            raise NoNameException("Configuration name has not been set")

        self.write_name_to_cache_file(self.__config_name, write_active_config)
