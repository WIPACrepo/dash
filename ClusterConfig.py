#!/usr/bin/env python

#
# ClusterConfig.py
#
# J. Jacobsen, NPX Designs, Inc. for UW-IceCube
#
# February, 2007

from os import environ, listdir, remove
from re import search
from os.path import abspath, exists, join
from xml.dom import minidom

class ConfigNotSpecifiedException(Exception): pass
class ConfigNotFoundException(Exception): pass
class MalformedDeployConfigException(Exception): pass

GLOBAL_DEFAULT_LOG_LEVEL = "INFO"

class deployComponent:
    "Record-keeping class for deployed components"
    def __init__(self, compName, compID, logLevel):
        self.compName = compName;
        self.compID   = compID;
        self.logLevel = logLevel

    def __str__(self):
        if self.compID == 0 and not self.compName.lower().endswith("hub"):
            return "%s@%s" % (self.compName, self.logLevel)
        return "%s#%d@%s" % (self.compName, self.compID, self.logLevel)

class deployNode:
    "Record-keeping class for host targets"
    def __init__(self, locName, hostName):
        self.locName  = locName;
        self.hostName = hostName;
        self.comps    = []
        
    def addComp(self, comp): self.comps.append(comp)

class deployConfig(object):
    "Class for parsing and storing pDAQ cluster configurations stored in XML files"
    def __init__(self, configDir, configName):
        self.nodes = []
        
        self.configFile = self.xmlOf(join(configDir,configName))
        if not exists(self.configFile): raise ConfigNotFoundException(configName)
        try:
            parsed = minidom.parse(self.configFile)
        except:
            import sys,traceback
            traceback.print_exc(file=sys.stdout)
            raise MalformedDeployConfigException(self.configFile)
        icecube = parsed.getElementsByTagName("icecube")
        if len(icecube) != 1: raise MalformedDeployConfigException(self.configFile)

        # Get "remarks" string if available
        self.remarks = self.getValue(icecube[0], "remarks")
        
        cluster = icecube[0].getElementsByTagName("cluster")
        if len(cluster) != 1: raise MalformedDeployConfigException(self.configFile)
        self.clusterName = self.getValue(cluster[0], "name")

        # Get location of SPADE output
        self.logDirForSpade = self.getValue(cluster[0], "logDirForSpade")

        # Get location of SPADE/logs copies
        self.logDirCopies = self.getValue(cluster[0], "logDirCopies")
            
        # Get default log level
        self.defaultLogLevel = self.getValue(cluster[0], "defaultLogLevel",
                                             GLOBAL_DEFAULT_LOG_LEVEL)
        
        locations = cluster[0].getElementsByTagName("location")
        for nodeXML in locations:
            name = self.getValue(nodeXML, "name")
            if name is None:
                raise MalformedDeployConfigException("<location> is missing 'name' attribute")

            # Get address
            if nodeXML.attributes.has_key("host"):
                hostname = nodeXML.attributes["host"].value
            else:
                address = nodeXML.getElementsByTagName("address")
                hostname = self.getElementSingleTagName(address[0], "host")

            thisNode = deployNode(name, hostname)
            self.nodes.append(thisNode)

            # Get modules: name and ID
            modules = nodeXML.getElementsByTagName("module")
            for compXML in modules:
                compName = self.getValue(compXML, "name")
                if compName is None:
                    raise MalformedDeployConfigException("Found module without 'name'")

                idStr = self.getValue(compXML, "id", "0")
                try:
                    compID = int(idStr)
                except:
                    raise MalformedDeployConfigException("Bad id '%s' for module '%d'" %
                                                         (idStr, compName))

                logLevel = self.getValue(compXML, "logLevel",
                                         self.defaultLogLevel)

                thisNode.addComp(deployComponent(compName, compID, logLevel))

    def getElementSingleTagName(root, name):
        "Fetch a single element tag name of form <tagName>yowsa!</tagName>"
        elems = root.getElementsByTagName(name)
        if len(elems) != 1:
            raise MalformedDeployConfigException("Expected exactly one %s" % name)
        if len(elems[0].childNodes) != 1:
            raise MalformedDeployConfigException("Expected exactly one child node of %s" %name)
        return elems[0].childNodes[0].data
    getElementSingleTagName = staticmethod(getElementSingleTagName)

    def getHubNodes(self):
        hublist = []
        for node in self.nodes:
            for comp in node.comps:
                if comp.compName == "StringHub":
                    try:
                        hublist.index(node.hostName)
                    except ValueError:
                        hublist.append(node.hostName)
        return hublist

    def getValue(self, node, name, defaultVal=None):
        if node.attributes is not None and node.attributes.has_key(name):
            return node.attributes[name].value

        try:
            return self.getElementSingleTagName(node, name)
        except:
            return defaultVal

    def xmlOf(self, name):
        if not name.endswith(".xml"): return name+".xml"
        return name

class ClusterConfig(deployConfig):
    def __init__(self, topDir, cmdlineConfig, showListAndExit=False,
                 useFallbackConfig=True, useActiveConfig=False):
        self.clusterConfigDir = abspath(join(topDir, 'cluster-config'))

        # Choose configuration
        if cmdlineConfig is not None:
            configToUse = cmdlineConfig
        else:
            configToUse = self.readCacheFile(useActiveConfig)
            if configToUse is None and useFallbackConfig:
                configToUse = 'sim-localhost'

        configXMLDir = join(self.clusterConfigDir, 'src', 'main', 'xml')

        if showListAndExit:
            self.showConfigs(configXMLDir, configToUse)
            raise SystemExit

        if configToUse is None:
            raise ConfigNotSpecifiedException

        self.configName = configToUse

        super(ClusterConfig, self).__init__(configXMLDir, configToUse)

    def clearActiveConfig(self):
        "delete the active cluster name"
        try:
            remove(self.getCachedNamePath(True))
        except:
            pass

    def getCachedNamePath(self, useActiveConfig):
        "get the active or default cluster configuration"
        if useActiveConfig:
            return join(environ["HOME"], ".active")
        return join(self.clusterConfigDir, ".config")

    def readCacheFile(self, useActiveConfig):
        "read the cached cluster name"
        clusterFile = self.getCachedNamePath(useActiveConfig)
        try:
            f = open(clusterFile, "r")
            ret = f.readline()
            f.close()
            return ret.rstrip('\r\n')
        except:
            return None

    def showConfigs(self, configDir, configToUse):
        "Utility to show all available cluster configurations in configDir"
        l = listdir(configDir)
        cfgs = []
        for f in l:
            match = search(r'^(.+?)\.xml$', f)
            if not match: continue
            cfgs.append(match.group(1))

        ok = []
        remarks = {}
        for cname in cfgs:
            try:
                config = deployConfig(configDir, cname)
                ok.append(cname)
                remarks[cname] = config.remarks
            except Exception: pass

        ok.sort()
        for cname in ok:
            sep = "==="
            if configToUse and cname == configToUse:
                sep = "<=>"
            print "%40s %3s " % (cname, sep),
            if remarks[cname]: print remarks[cname]
            else: print
        

    def writeCacheFile(self, writeActiveConfig=False):
        "cache this config name"
        cachedNamePath = self.getCachedNamePath(writeActiveConfig)
        fd = open(cachedNamePath, 'w')
        print >>fd, self.configName
        fd.close()
