#!/usr/bin/env python

import os

from xml.dom import Node, minidom
from CachedConfigName import CachedConfigName
from Component import Component
from XMLFileCache import XMLFileCache

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class ClusterConfigException(Exception): pass
class ConfigNotFoundException(ClusterConfigException): pass
class MalformedDeployConfigException(ClusterConfigException): pass

class ClusterComponent(Component):
    "Record-keeping class for deployed components"
    def __init__(self, name, id, logLevel, jvm, jvmArgs, host):
        self.__jvm = jvm
        self.__jvmArgs = jvmArgs
        self.__host = host

        super(ClusterComponent, self).__init__(name, id, logLevel)

    def __str__(self):
        return "%s@%s" % (self.fullName(), self.logLevel())

    def host(self): return self.__host
    def isControlServer(self): return False
    def jvm(self): return self.__jvm
    def jvmArgs(self): return self.__jvmArgs

class ClusterNode(object):
    "Record-keeping class for host targets"
    def __init__(self, locName, hostName):
        self.__locName  = locName
        self.__hostName = hostName
        self.__comps    = []

    def __cmp__(self, other):
        val = cmp(self.__hostName, other.__hostName)
        if val == 0:
            val = cmp(self.__locName, other.__locName)
        return val

    def addComp(self, comp): self.__comps.append(comp)

    def components(self): return self.__comps[:]
    def hostName(self): return self.__hostName
    def locName(self): return self.__locName

class ClusterConfig(CachedConfigName):
    def __init__(self, configName, remarks, clusterName):
        self.__remarks = remarks
        self.__clusterName = clusterName

        self.__logDirForSpade = None
        self.__logDirCopies = None
        self.__defaultLogLevel = None

        self.__nodes = []

        super(ClusterConfig, self).__init__()

        self.setConfigName(configName)

    def addNode(self, name, hostname):
        node = ClusterNode(name, hostname)
        self.__nodes.append(node)
        return node

    def defaultLogLevel(self): return self.__defaultLogLevel
    def descName(self): return None
    def logDirCopies(self): return self.__logDirCopies
    def logDirForSpade(self): return self.__logDirForSpade
    def nodes(self): return self.__nodes[:]

    def setLogDirForSpade(self, logDir):
        self.__logDirForSpade = logDir

    def setLogDirCopies(self, copyDir):
        self.__logDirCopies = copyDir

    def setDefaultLogLevel(self, logLevel):
        self.__defaultLogLevel = logLevel

class ClusterConfigParser(XMLFileCache):
    """
    Class for parsing and storing pDAQ cluster configuration XML files
    """

    CLUSTER_CONFIG_DEFAULTS = "cluster-config-defaults.xml"
    DEFAULT_CLUSTER_NAME = "localhost"
    GLOBAL_DEFAULT_LOG_LEVEL = "INFO"

    def __init__(self):
        self.__nodes = []

    def defaultLogLevel(self): return self.GLOBAL_DEFAULT_LOG_LEVEL

    @classmethod
    def getDefaultJavaInfo(cls, configDir, clusterName):
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
            cls.openAndParseConfig(configDir, cls.CLUSTER_CONFIG_DEFAULTS)

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
                    node.getAttribute("name") == cls.DEFAULT_CLUSTER_NAME:
                defaultClusterNode = node
            if None not in (clusterNode, defaultClusterNode):
                break
        if defaultClusterNode is None:
            raise MalformedDeployConfigException(\
                "Missing '%s' cluster config in '%s'" % \
                    (cls.DEFAULT_CLUSTER_NAME, cls.CLUSTER_CONFIG_DEFAULTS))
        if clusterNode is None:
            clusterNode = defaultClusterNode
            print "Warning: No '%s' cluster in '%s'.  Using cluster '%s'." % \
                (clusterName, cls.CLUSTER_CONFIG_DEFAULTS,
                 cls.DEFAULT_CLUSTER_NAME)

        # Get list of module nodes
        moduleNodes = clusterNode.getElementsByTagName("module")
        for node in moduleNodes:
            name = node.getAttribute("name")
            if name:
                if name == "default":
                    fbJavaDict['jvm'] = \
                        cls.getElementSingleTagName(node, 'jvm')
                    fbJavaDict['jvmArgs'] = \
                        cls.getElementSingleTagName(node, 'jvmArgs')
                else:
                    defJavaDict[name] = {}
                    defJavaDict[name]['jvm'] = \
                        cls.getElementSingleTagName(node, 'jvm')
                    defJavaDict[name]['jvmArgs'] = \
                        cls.getElementSingleTagName(node, 'jvmArgs')
            else:
                raise MalformedDeployConfigException(\
                    "Unnamed module found in cluster '%s' in cluster config "
                    "defaults while looking for default java info. "
                    "configFile='%s'" % (clusterName, configFile))

        return defJavaDict, fbJavaDict

    @classmethod
    def getElementSingleTagName(cls, root, name, deep=True, enforce=True):
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


    def getHubNodes(self):
        hublist = []
        for node in self.__nodes:
            addHost = False
            for comp in node.components():
                if comp.isHub():
                    addHost = True
                    break

            if addHost:
                try:
                    hublist.index(node.hostName())
                except ValueError:
                    hublist.append(node.hostName())
        return hublist

    @classmethod
    def getValue(cls, node, name, defaultVal=None):
        if node.attributes is not None and node.attributes.has_key(name):
            return node.attributes[name].value
        try:
            return cls.getElementSingleTagName(node, name)
        except:
            return defaultVal

    @staticmethod
    def openAndParseConfig(configDir, configName):
        """ Open the given configName'd file in the configDir dir
        returning name of the file parsed and the top-level icecube
        element node. """
        configFile = os.path.join(configDir, configName)
        if not configFile.endswith(".xml"):
            configFile += ".xml"
        if not os.path.exists(configFile):
            raise ConfigNotFoundException(configName)

        try:
            parsed = minidom.parse(configFile)
        except:
            raise MalformedDeployConfigException(configFile)

        icecube = parsed.getElementsByTagName("icecube")
        if len(icecube) != 1: raise MalformedDeployConfigException(configFile)
        return configFile, icecube[0]

    @classmethod
    def parse(cls, dom, configDir, configName, strict=True):
        "Load the configuration data from the XML-formatted file"
        icecube = dom.getElementsByTagName("icecube")
        if len(icecube) != 1: raise MalformedDeployConfigException(configName)

        # Get "remarks" string if available
        remarks = cls.getValue(icecube[0], "remarks")

        cluster = icecube[0].getElementsByTagName("cluster")
        if len(cluster) != 1:
            raise MalformedDeployConfigException(configName)
        clusterName = cls.getValue(cluster[0], "name")

        cluCfg = ClusterConfig(configName, remarks, clusterName)

        # Get location of SPADE output
        cluCfg.setLogDirForSpade(cls.getValue(cluster[0], "logDirForSpade"))

        # Get location of SPADE/logs copies
        cluCfg.setLogDirCopies(cls.getValue(cluster[0], "logDirCopies"))

        # Get default log level
        cluCfg.setDefaultLogLevel(cls.getValue(cluster[0], "defaultLogLevel",
                                               cls.GLOBAL_DEFAULT_LOG_LEVEL))

        # Get default java info as a dict of modules and fallback defaults
        defaultJava, fallBackJava = \
            cls.getDefaultJavaInfo(configDir, clusterName)

        locations = cluster[0].getElementsByTagName("location")
        for nodeXML in locations:
            name = cls.getValue(nodeXML, "name")
            if name is None:
                raise MalformedDeployConfigException(\
                    "<location> is missing 'name' attribute")

            # Get address
            if nodeXML.attributes.has_key("host"):
                hostname = nodeXML.attributes["host"].value
            else:
                address = nodeXML.getElementsByTagName("address")
                hostname = cls.getElementSingleTagName(address[0], "host")

            thisNode = cluCfg.addNode(name, hostname)

            # Get modules: name and ID
            modules = nodeXML.getElementsByTagName("module")
            for compXML in modules:
                compName = cls.getValue(compXML, "name")
                if compName is None:
                    raise MalformedDeployConfigException(\
                        "Found module without 'name'")

                idStr = cls.getValue(compXML, "id", "0")
                try:
                    compID = int(idStr)
                except:
                    raise MalformedDeployConfigException(\
                        "Bad id '%s' for module '%d'" % (idStr, compName))

                logLevel = cls.getValue(compXML, "logLevel",
                                         cluCfg.defaultLogLevel())

                # Get the jvm/jvmArgs from the default cluster config
                jvm = defaultJava.get(compName, fallBackJava).get('jvm')
                jvmArgs = \
                    defaultJava.get(compName, fallBackJava).get('jvmArgs')

                # Override if module has a jvm a/o jvmArgs defined
                modJvm = cls.getElementSingleTagName(compXML, 'jvm',
                                                     deep=False,
                                                     enforce=False)
                if modJvm: jvm = modJvm

                modJvmArgs = cls.getElementSingleTagName(compXML, 'jvmArgs',
                                                         deep=False,
                                                         enforce=False)
                if modJvmArgs: jvmArgs = modJvmArgs

                # Hubs need special ID arg
                #if compName == HUB_COMP_NAME:
                #    jvmArgs += " -Dicecube.daq.stringhub.componentId=%d" % \
                #        compID

                thisNode.addComp(ClusterComponent(compName, compID, logLevel,
                                                 jvm, jvmArgs, hostname))

        return cluCfg

if __name__ == "__main__":
    import datetime, optparse

    p = optparse.OptionParser()
    p.add_option("-c", "--check-config", type="string", dest="toCheck",
                 action="store", default= None,
                 help="Check whether configuration is valid")
    opt, args = p.parse_args()

    configDir  = os.path.join(metaDir, "cluster-config", "src", "main", "xml")

    if opt.toCheck:
        try:
            ClusterConfigParser.load(opt.toCheck, configDir)
            print "%s/%s is ok." % (configDir, opt.toCheck)
        except Exception, e:
            from exc_string import exc_string
            print "%s/%s is not a valid config: %s [%s]" % \
                (configDir, opt.toCheck, e, exc_string())
        raise SystemExit

    # Code for testing:
    if len(args) == 0:
        args.append("sim5str")

    for configName in args:
        print '-----------------------------------------------------------'
        print "Config %s" % configName
        startTime = datetime.datetime.now()
        dc = ClusterConfigParser.load(configName, configDir)
        diff = datetime.datetime.now() - startTime
        initTime = float(diff.seconds) + (float(diff.microseconds) / 1000000.0)

        startTime = datetime.datetime.now()
        dc = ClusterConfigParser.load(configName, configDir)
        diff = datetime.datetime.now() - startTime
        nextTime = float(diff.seconds) + (float(diff.microseconds) / 1000000.0)
        print "Initial time %.03f, subsequent time: %.03f" % \
            (initTime, nextTime)
