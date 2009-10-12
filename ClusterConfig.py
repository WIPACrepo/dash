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
DEFAULT_CLUSTER_NAME = "localhost"
GLOBAL_DEFAULT_LOG_LEVEL = "INFO"
HUB_COMP_NAME = "StringHub"

class deployComponent(object):
    "Record-keeping class for deployed components"
    def __init__(self, compName, compID, logLevel, jvm, jvmArgs):
        self.compName = compName
        self.compID   = compID
        self.logLevel = logLevel
        self.jvm      = jvm
        self.jvmArgs  = jvmArgs

    def __str__(self):
        if self.compID == 0 and not self.compName.lower().endswith("hub"):
            return "%s@%s" % (self.compName, self.logLevel)
        return "%s#%d@%s" % (self.compName, self.compID, self.logLevel)

class deployNode(object):
    "Record-keeping class for host targets"
    def __init__(self, locName, hostName):
        self.locName  = locName
        self.hostName = hostName
        self.comps    = []

    def addComp(self, comp): self.comps.append(comp)

class deployConfig(object):
    """ Class for parsing and storing pDAQ cluster configurations
    stored in XML files """
    def __init__(self, configDir, configName):
        self.nodes = []
        
        self.configFile, icecubeNode = \
            self.openAndParseConfig(configDir, configName)

        # Get "remarks" string if available
        self.remarks = self.getValue(icecubeNode, "remarks")
        
        cluster = icecubeNode.getElementsByTagName("cluster")
        if len(cluster) != 1:
            raise MalformedDeployConfigException(self.configFile)
        self.clusterName = self.getValue(cluster[0], "name")

        # Get location of SPADE output
        self.logDirForSpade = self.getValue(cluster[0], "logDirForSpade")

        # Get location of SPADE/logs copies
        self.logDirCopies = self.getValue(cluster[0], "logDirCopies")
            
        # Get default log level
        self.defaultLogLevel = self.getValue(cluster[0], "defaultLogLevel",
                                             GLOBAL_DEFAULT_LOG_LEVEL)
        
        # Get default java info as a dict of modules and fallback defaults
        self.defaultJava, self.fallBackJava = \
            self.getDefaultJavaInfo(configDir, self.clusterName)

        locations = cluster[0].getElementsByTagName("location")
        for nodeXML in locations:
            name = self.getValue(nodeXML, "name")
            if name is None:
                raise MalformedDeployConfigException(\
                    "<location> is missing 'name' attribute")

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
                    raise MalformedDeployConfigException(\
                        "Found module without 'name'")

                idStr = self.getValue(compXML, "id", "0")
                try:
                    compID = int(idStr)
                except:
                    raise MalformedDeployConfigException(\
                        "Bad id '%s' for module '%d'" % (idStr, compName))

                logLevel = self.getValue(compXML, "logLevel",
                                         self.defaultLogLevel)

                # Get the jvm/jvmArgs from the default cluster config
                jvm     = self.defaultJava.get(compName,
                                               self.fallBackJava).get('jvm')
                jvmArgs = self.defaultJava.get(compName,
                                               self.fallBackJava).get('jvmArgs')

                # Override if module has a jvm a/o jvmArgs defined
                modJvm = self.getElementSingleTagName(compXML, 'jvm',
                                                      deep=False,
                                                      enforce=False)
                if modJvm: jvm = modJvm

                modJvmArgs = self.getElementSingleTagName(compXML, 'jvmArgs',
                                                          deep=False,
                                                          enforce=False)
                if modJvmArgs: jvmArgs = modJvmArgs

                # Hubs need special ID arg
                if compName == HUB_COMP_NAME:
                    jvmArgs += " -Dicecube.daq.stringhub.componentId=%d" % \
                        compID

                thisNode.addComp(deployComponent(compName, compID, logLevel,
                                                 jvm, jvmArgs))
                                       
                                       
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
                raise MalformedDeployConfigException(\
                    "Expected exactly one %s" % name)
            if len(elems[0].childNodes) != 1:
                raise MalformedDeployConfigException(\
                    "Expected exactly one child node of %s" %name)
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

    def getDefaultJavaInfo(self, configDir, clusterName):
        """ Get the default set of java information from the
        cluster-config default file for clusterName.

        Return a tuple of dictionaties: a nested dictionary populated
        with jvm & jvmArgs (i.e. d['eventBuilder']['jvm']) and
        fallback dict with just 'jvm' and 'jvmArgs' keys.  The latter
        is what was in the "default" module for the cluster and the
        former has such a dict for each named module. """

        defJavaDict = {}
        fbJavaDict = {}

        # Parse the default cluster config file
        configFile, icecubeNode = \
            self.openAndParseConfig(configDir, CLUSTER_CONGIF_DEFAULTS)

        # Get the proper cluster node, using 'localhost' as fallback
        clusterNodes = icecubeNode.getElementsByTagName("cluster")
        if len(clusterNodes) < 1:
            raise MalformedDeployConfigException(\
                "No cluster elements in cluster config defaults while "
                "looking for default java info.  configFile='%s'" %
                configFile)
        clusterNode = defaultClusterNode = None
        for node in clusterNodes:
            if clusterNode is None and \
                    node.getAttribute("name") == clusterName:
                clusterNode = node
            if defaultClusterNode is None and \
                    node.getAttribute("name") == DEFAULT_CLUSTER_NAME:
                defaultClusterNode = node
            if None not in (clusterNode, defaultClusterNode):
                break
        if defaultClusterNode is None:
            raise MalformedDeployConfigException(\
                "Missing '%s' cluster config in '%s'" % \
                    (DEFAULT_CLUSTER_NAME, CLUSTER_CONGIF_DEFAULTS))
        if clusterNode is None:
            clusterNode = defaultClusterNode
            print "Warning: No '%s' cluster in '%s'.  Using cluster '%s'." % \
                (clusterName, CLUSTER_CONGIF_DEFAULTS, DEFAULT_CLUSTER_NAME)

        # Get list of module nodes
        moduleNodes = clusterNode.getElementsByTagName("module")
        for node in moduleNodes:
            name = node.getAttribute("name")
            if name:
                if name == "default":
                    fbJavaDict['jvm'] = \
                        self.getElementSingleTagName(node, 'jvm')
                    fbJavaDict['jvmArgs'] = \
                        self.getElementSingleTagName(node, 'jvmArgs')
                else:
                    defJavaDict[name] = {}
                    defJavaDict[name]['jvm'] = \
                        self.getElementSingleTagName(node, 'jvm')
                    defJavaDict[name]['jvmArgs'] = \
                        self.getElementSingleTagName(node, 'jvmArgs')
            else:
                raise MalformedDeployConfigException(\
                    "Unnamed module found in cluster '%s' in cluster config "
                    "defaults while looking for default java info. "
                    "configFile='%s'" % (clusterName, configFile))

        return defJavaDict, fbJavaDict

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
        configFile = self.xmlOf(join(configDir, configName))
        if not exists(configFile): raise ConfigNotFoundException(configName)
        try:
            parsed = minidom.parse(configFile)
        except:
            import sys, traceback
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
