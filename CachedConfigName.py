#!/usr/bin/env python
#
# Deal with the various configuration name caches

import os

class NoNameException(Exception): pass

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class CachedFile(object):
    
    @staticmethod
    def __getCachedNamePath(useActiveConfig):
        "get the active or default cluster configuration"
        if useActiveConfig:
            return os.path.join(os.environ["HOME"], ".active")
        return os.path.join(metaDir, 'config', ".config")

    @staticmethod
    def __readCacheFile(useActiveConfig):
        "read the cached cluster name"
        clusterFile = CachedFile.__getCachedNamePath(useActiveConfig)
        try:
            f = open(clusterFile, "r")
            ret = f.readline()
            f.close()
            return ret.rstrip('\r\n')
        except:
            return None

    @staticmethod
    def clearActiveConfig():
        "delete the active cluster name"
        activeName = CachedFile.__getCachedNamePath(True)
        if os.path.exists(activeName): os.remove(activeName)

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
            print >>fd, name
        

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
