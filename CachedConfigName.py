#!/usr/bin/env python
#
# Deal with the various configuration name caches

from __future__ import print_function

import os

from locate_pdaq import find_pdaq_config


class NoNameException(Exception):
    pass


class CachedFile(object):

    @staticmethod
    def __getCachedNamePath(useActiveConfig):
        "get the active or default cluster configuration"
        if useActiveConfig:
            return os.path.join(os.environ["HOME"], ".active")
        configDir = find_pdaq_config()
        return os.path.join(configDir, ".config")

    @staticmethod
    def __readCacheFile(useActiveConfig):
        "read the cached cluster name"
        clusterFile = CachedFile.__getCachedNamePath(useActiveConfig)
        try:
            with open(clusterFile, 'r') as f:
                ret = f.readline()
                if ret is not None:
                    ret = ret.rstrip('\r\n')
                if ret is None or len(ret) == 0:
                    return None
                return ret
        except:
            return None

    @staticmethod
    def clearActiveConfig():
        "delete the active cluster name"
        activeName = CachedFile.__getCachedNamePath(True)
        if os.path.exists(activeName):
            os.remove(activeName)

    @staticmethod
    def getConfigToUse(cmdlineConfig, useFallbackConfig, useActiveConfig):
        "Determine the name of the configuration to use"
        if cmdlineConfig is not None:
            cfg = cmdlineConfig
        else:
            cfg = CachedFile.__readCacheFile(useActiveConfig)
            if cfg is None and useFallbackConfig:
                cfg = 'sim-localhost'

        return cfg

    @staticmethod
    def writeCacheFile(name, writeActiveConfig=False):
        "write this config name to the appropriate cache file"
        cachedNamePath = CachedFile.__getCachedNamePath(writeActiveConfig)

        with open(cachedNamePath, 'w') as fd:
            print(name, file=fd)


class CachedConfigName(CachedFile):
    def __init__(self):
        "Initialize instance variables"
        self.__configName = None

    @property
    def configName(self):
        "get the configuration name to write to the cache file"
        return self.__configName

    def setConfigName(self, name):
        self.__configName = name

    def writeCacheFile(self, writeActiveConfig=False):
        "write this config name to the appropriate cache file"
        if self.__configName is None:
            raise NoNameException("Configuration name has not been set")

        super(CachedConfigName, self).writeCacheFile(self.__configName,
                                                     writeActiveConfig)
