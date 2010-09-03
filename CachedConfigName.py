#!/usr/bin/env python
#
# Deal with the various configuration name caches

import os, sys

class NoNameException(Exception): pass

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class CachedFile(object):
    def __getCachedNamePath(cls, useActiveConfig):
        "get the active or default cluster configuration"
        if useActiveConfig:
            return os.path.join(os.environ["HOME"], ".active")
        return os.path.join(metaDir, 'config', ".config")
    __getCachedNamePath = classmethod(__getCachedNamePath)

    def __readCacheFile(cls, useActiveConfig):
        "read the cached cluster name"
        clusterFile = cls.__getCachedNamePath(useActiveConfig)
        try:
            f = open(clusterFile, "r")
            ret = f.readline()
            f.close()
            return ret.rstrip('\r\n')
        except:
            return None
    __readCacheFile = classmethod(__readCacheFile)

    def clearActiveConfig(cls):
        "delete the active cluster name"
        activeName = cls.__getCachedNamePath(True)
        if os.path.exists(activeName): os.remove(activeName)
    clearActiveConfig = classmethod(clearActiveConfig)

    def getConfigToUse(cls, cmdlineConfig, useFallbackConfig, useActiveConfig):
        "Determine the name of the configuration to use"
        if cmdlineConfig is not None:
            cfg = cmdlineConfig
        else:
            cfg = cls.__readCacheFile(useActiveConfig)
            if cfg is None and useFallbackConfig:
                cfg = 'sim-localhost'

        return cfg
    getConfigToUse = classmethod(getConfigToUse)


    def writeCacheFile(cls, name, writeActiveConfig=False):
        "write this config name to the appropriate cache file"
        cachedNamePath = cls.__getCachedNamePath(writeActiveConfig)
        fd = open(cachedNamePath, 'w')
        print >>fd, name
        fd.close()
    writeCacheFile = classmethod(writeCacheFile)

class CachedConfigName(CachedFile):
    def __init__(self):
        "Initialize instance variables"
        self.__configName = None

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
