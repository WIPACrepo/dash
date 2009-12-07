#!/usr/bin/env python
#
# Deal with the various configuration name caches

import os, sys

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class CachedConfigName(object):
    def __init__(self):
        "Initialize instance variables"
        self.configName = None

    def __getCachedNamePath(self, useActiveConfig):
        "get the active or default cluster configuration"
        if useActiveConfig:
            return os.path.join(os.environ["HOME"], ".active")
        return os.path.join(metaDir, 'config', ".config")

    def __readCacheFile(self, useActiveConfig):
        "read the cached cluster name"
        clusterFile = self.__getCachedNamePath(useActiveConfig)
        try:
            f = open(clusterFile, "r")
            ret = f.readline()
            f.close()
            return ret.rstrip('\r\n')
        except:
            return None

    def clearActiveConfig(self):
        "delete the active cluster name"
        activeName = self.__getCachedNamePath(True)
        if os.path.exists(activeName): os.remove(activeName)

    def getConfigToUse(self, cmdlineConfig, useFallbackConfig, useActiveConfig):
        "Determine the name of the configuration to use"
        if cmdlineConfig is not None:
            cfg = cmdlineConfig
        else:
            cfg = self.__readCacheFile(useActiveConfig)
            if cfg is None and useFallbackConfig:
                cfg = 'sim-localhost'

        return cfg

    def getConfigName(self):
        "get the configuration name to write to the cache file"
        return self.configName

    def writeCacheFile(self, writeActiveConfig=False):
        "write this config name to the appropriate cache file"
        cachedNamePath = self.__getCachedNamePath(writeActiveConfig)
        fd = open(cachedNamePath, 'w')
        print >>fd, self.getConfigName()
        fd.close()
