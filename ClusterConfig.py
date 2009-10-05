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

CLUSTER_CONGIF_DEFAULTS = "cluster-config-defaults.xml"
GLOBAL_DEFAULT_LOG_LEVEL = "INFO"
HUB_COMP_NAME = "StringHub"

class deployComponent:
    "Record-keeping class for deployed components"
    def __init__(self, compName, compID, logLevel, jvm, jvmArgs):
        self.compName = compName;
        self.compID   = compID;
        self.logLevel = logLevel
        self.jvm      = jvm
        self.jvmArgs  = jvmArgs

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
        
        self.configFile, icecubeNode = self.openAndParseConfig(configDir, configName)

        # Get "remarks" string if available
        self.remarks = self.getValue(icecubeNode, "remarks")
        
        cluster = icecubeNode.getElementsByTagName("cluster")
        if len(cluster) != 1: raise MalformedDeployConfigException(self.configFile)
        self.clusterName = self.getValue(cluster[0], "name")

        # Get location of SPADE output
        self.logDirForSpade = self.getValue(cluster[0], "logDirForSpade")

        # Get location of SPADE/logs copies
        self.logDirCopies = self.getValue(cluster[0], "logDirCopies")
            
        # Get default log level
        self.defaultLogLevel = self.getValue(cluster[0], "defaultLogLevel",
                                             GLOBAL_DEFAULT_LOG_LEVEL)
        
        # Get default java info as a dictionary
        self.defaultJavaInfo = self.getJavaInfo(cluster[0], configDir,
                                                CLUSTER_CONGIF_DEFAULTS)

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

                moduleJavaInfo = self.getJavaInfo(compXML, inModule=True)

                if compName == HUB_COMP_NAME:
                    jvm = moduleJavaInfo.get('jvm', self.defaultJavaInfo['hubJvm'])
                    jvmArgs = moduleJavaInfo.get('jvmArgs', self.defaultJavaInfo['hubJvmArgs'])
                    jvmArgs += " -Dicecube.daq.stringhub.componentId=%d" % compID
                else:
                    jvm = moduleJavaInfo.get('jvm', self.defaultJavaInfo['jvm'])
                    jvmArgs = moduleJavaInfo.get('jvmArgs', self.defaultJavaInfo['jvmArgs'])

                thisNode.addComp(deployComponent(compName, compID, logLevel, jvm, jvmArgs))
                                       
                                       
    def getElementSingleTagName(root, name, deep=True, enforce=True):
        """ Fetch a single element tag name of form
        <tagName>yowsa!</tagName>.  If deep is False, then only look
        at immediate child nodes. If enforce is True, raise
        MalformedDeployConfigException if other than one matching
        element is found.  If enforce if False, then either None or
        the data from the first matched element will be returned."""

        if deep:
            elems = root.getElementsByTagName(name)
        else:
            elems = minidom.NodeList()
            for node in root.childNodes:
                if node.nodeType == minidom.Node.ELEMENT_NODE and \
                        (name == "*" or node.tagName == name):
                    elems.append(node)

        if enforce:
            if len(elems) != 1:
                raise MalformedDeployConfigException("Expected exactly one %s" % name)
            if len(elems[0].childNodes) != 1:
                raise MalformedDeployConfigException("Expected exactly one child node of %s" %name)
        elif len(elems) == 0:
            return None
        return elems[0].childNodes[0].data.strip()
    getElementSingleTagName = staticmethod(getElementSingleTagName)

    def getHubNodes(self):
        hublist = []
        for node in self.nodes:
            for comp in node.comps:
                if comp.compName == HUB_COMP_NAME:
                    try:
                        hublist.index(node.hostName)
                    except ValueError:
                        hublist.append(node.hostName)
        return hublist

    def getJavaInfo(self, node, configDir=None, defaultConfig=None, inModule=False):
        """ Return a dict of the values for jvm and jvmArgs.  Used
        both for defaultJava element at top of the cluster config and
        the optional java element in each module.  If not in a module,
        then look for defaultJava element and if not found in the
        current config then consult the provided defaultConfig in
        configDir if provided.

        Returns a dict with at least the following keys: 'jvm',
        'jvmArgs' and also 'hubJvm', 'hubJvmArgs' if inModule is True
        and the hubs sub-element is found in the xml.  Raises
        MalformedDeployConfigException on problem with reading config
        xml."""

        ret = {}
        javaElementName = "defaultJava"

        # If we're in a module, then look for "java" element
        if inModule:
            javaElementName = "java"

        javaNodes = node.getElementsByTagName(javaElementName)

        if len(javaNodes) >= 1:
            val = self.getElementSingleTagName(javaNodes[0], 'jvm', deep=False,
                                               enforce = not inModule)
            if val:
                ret['jvm'] = val

            val = self.getElementSingleTagName(javaNodes[0], 'jvmArgs',
                                               deep=False,
                                               enforce = not inModule)
            if val:
                ret['jvmArgs'] = val

            if not inModule:
                hubNodes = javaNodes[0].getElementsByTagName("hubs")
                if len(hubNodes) >= 1:
                    val = self.getElementSingleTagName(hubNodes[0], 'jvm',
                                                       enforce=False)
                    if val:
                        ret['hubJvm'] = val

                    val = self.getElementSingleTagName(hubNodes[0], 'jvmArgs',
                                                       enforce=False)
                    if val:
                        ret['hubJvmArgs'] = val
            
        elif not inModule:  # Look in default cluster config file
            defConfigFile, icecubeNode = self.openAndParseConfig(configDir, defaultConfig)
            cluster = icecubeNode.getElementsByTagName("cluster")
            if len(cluster) != 1: raise MalformedDeployConfigException(self.configFile)
            ret = self.getJavaInfo(cluster[0]) # recurse without default config file.

        return ret

        
    def getValue(self, node, name, defaultVal=None):
        if node.attributes is not None and node.attributes.has_key(name):
            return node.attributes[name].value

        try:
            return self.getElementSingleTagName(node, name)
        except:
            return defaultVal

    def openAndParseConfig(self, configDir, configName):
        """ Open the given configName'd file in the configDir dir
        returning name of the file parsed and the top-level icecube
        element node. """
        configFile = self.xmlOf(join(configDir,configName))
        if not exists(configFile): raise ConfigNotFoundException(configName)
        try:
            parsed = minidom.parse(configFile)
        except:
            import sys,traceback
            traceback.print_exc(file=sys.stdout)
            raise MalformedDeployConfigException(configFile)
        icecube = parsed.getElementsByTagName("icecube")
        if len(icecube) != 1: raise MalformedDeployConfigException(configFile)
        return configFile, icecube[0]

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
