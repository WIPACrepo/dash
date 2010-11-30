#!/usr/bin/env python

import os, sys, traceback

from xml.dom import minidom, Node

from Component import Component

class XMLError(Exception): pass
class XMLFileDoesNotExist(XMLError): pass
class XMLFormatError(XMLError): pass
class ClusterDescriptionFormatError(XMLFormatError): pass
class UnimplementedException(Exception): pass

class ConfigXMLBase(object):
    def __init__(self, configDir, configName, suffix='.xml'):
        fileName = os.path.join(configDir, configName)
        if not configName.endswith(suffix):
            fileName += suffix
        else:
            configName = configName[:-len(suffix)]
        if not os.path.exists(fileName):
            raise XMLFileDoesNotExist('File "%s" does not exist' % fileName)

        try:
            dom = minidom.parse(fileName)
        except Exception, e:
            raise XMLFormatError('%s: %s' % (fileName, str(e)))

        self.extractFrom(dom)

        self.__configDir = configDir
        self.__configName = configName

    def configName(self):
        return self.__configName

    def extractFrom(self, dom):
        raise UnimplementedException('extractFrom method is not implemented')

    def getNodeName(node):
        nodeName = '<%s>' % str(node.nodeName)
        if nodeName == '<#document>':
            nodeName = 'top-level'
        return nodeName
    getNodeName = staticmethod(getNodeName)

    def getChildText(node):
        if node.childNodes is None or len(node.childNodes) == 0:
            raise XMLFormatError('No %s child nodes' %
                                 ConfigXMLBase.getNodeName(node))

        text = None
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                if text is not None:
                    raise XMLFormatError('Found multiple text nodes under %s' %
                                         ConfigXMLBase.getNodeName(node))

                text = kid.nodeValue
                continue

        if text is None:
            raise XMLFormatError('No text node for %s' %
                                 ConfigXMLBase.getNodeName(node))

        return text

    getChildText = staticmethod(getChildText)

    def getSingleChild(node, name):
        kids = node.getElementsByTagName(name)
        if len(kids) < 1:
            raise XMLFormatError('No <%s> node found' % name)
        elif len(kids) > 1:
            raise XMLFormatError('Multiple <%s> nodes found' % name)

        return kids[0]

    getSingleChild = staticmethod(getSingleChild)

    def getValue(self, node, name, defaultVal=None):
        if node.attributes is not None and node.attributes.has_key(name):
            return node.attributes[name].value

        try:
            return self.getChildText(self.getSingleChild(node, name))
        except:
            return defaultVal

class ControlComponent(Component):
    def __init__(self):
        super(ControlComponent, self).__init__("CnCServer", 0, None)

    def __str__(self):
        return "CnCServer"

    def isControlServer(self): return True
    def required(self): return True

class ClusterComponent(Component):
    def __init__(self, name, id, logLevel, jvm, jvmArgs, required):
        self.__jvm = jvm
        self.__jvmArgs = jvmArgs
        self.__required = required

        super(ClusterComponent, self).__init__(name, id, logLevel)

    def __str__(self):
        if self.__jvm is None:
            if self.__jvmArgs is None:
                jStr = "?"
            else:
                jStr = "? | %s" % self.__jvmArgs
        else:
            if self.__jvmArgs is None:
                jStr = self.__jvm
            else:
                jStr = "%s | %s" % (self.__jvm, self.__jvmArgs)

        if self.__required:
            rStr = " REQUIRED"
        else:
            rStr = ""

        return "%s@%s(%s)%s" % \
            (self.fullName(), str(self.logLevel()), jStr, rStr)

    def isControlServer(self): return False
    def jvm(self): return self.__jvm
    def jvmArgs(self): return self.__jvmArgs
    def required(self): return self.__required

class ClusterSimHub(object):
    def __init__(self, host, number, priority, ifUnused):
        self.host = host
        self.number = number
        self.priority = priority
        self.ifUnused = ifUnused

    def __str__(self):
        if self.ifUnused:
            uStr = "(ifUnused)"
        else:
            uStr = ""
        return "%s*%d^%d%s" % (self.host, self.number, self.priority, uStr)

    def sortByPriority(x, y):
        val = cmp(y.priority, x.priority)
        if val == 0:
            val = cmp(x.host.name, y.host.name)
        return val

    sortByPriority = staticmethod(sortByPriority)

class ClusterHost(object):
    def __init__(self, name):
        self.name = name
        self.compMap = {}
        self.simHub = None
        self.ctlServer = False

    def __str__(self):
        return self.name

    def addComponent(self, name, id, logLevel, jvm, jvmArgs, required):
        comp = ClusterComponent(name, id, logLevel, jvm, jvmArgs, required)

        compKey = str(comp)
        if self.compMap.has_key(compKey):
            errMsg = 'Multiple entries for component "%s" in host "%s"' % \
                (compKey, self.name)
            raise ClusterDescriptionFormatError(errMsg)
        self.compMap[compKey] = comp

    def addSimulatedHub(self, simHub):
        if self.simHub is not None:
            errMsg = 'Multiple <simulatedHub> nodes for %s' % self.name
            raise ClusterDescriptionFormatError(errMsg)
        self.simHub = simHub

    def dump(self, prefix=None):
        if prefix is None:
            prefix = ""

        print "%sHost %s:" % (prefix, self.name)

        cKeys = self.compMap.keys()
        cKeys.sort()

        for key in cKeys:
            comp = self.compMap[key]
            print "%s  Comp %s" % (prefix, str(comp))

        if self.simHub is not None:
            if self.simHub.ifUnused:
                uStr = " (ifUnused)"
            else:
                uStr = ""
            print "%s  SimHub*%d prio %d%s" % \
                (prefix, self.simHub.number, self.simHub.priority, uStr)

        if self.ctlServer:
            print "%s  ControlServer" % prefix

    def getComponents(self):
        return self.compMap.values()

    def getSimulatedHub(self):
        return self.simHub

    def isControlServer(self):
        return self.ctlServer

    def setControlServer(self):
        self.ctlServer = True

class ClusterDescription(ConfigXMLBase):
    LOCAL = "localhost"
    SPS = "sps"
    SPTS = "spts"
    SPTS64 = "spts64"

    def __init__(self, configDir, configName, suffix='.cfg'):

        self.name = None
        self.__hostMap = None
        self.__compToHost = None

        self.__logDirForSpade = None
        self.__logDirCopies = None
        self.__defaultLogLevel = "INFO"
        self.__defaultJVM = None
        self.__defaultJVMArgs = None
        self.__defaultComponent = None

        try:
            super(ClusterDescription, self).__init__(configDir, configName,
                                                     suffix)
        except XMLFileDoesNotExist, e:
            if not configName.endswith('.cfg'):
                retryName = configName
            else:
                retryName = configName[:-4]

            if not retryName.endswith('-cluster'):
                retryName += '-cluster'

            try:
                super(ClusterDescription, self).__init__(configDir, retryName,
                                                         suffix)
            except XMLFileDoesNotExist, e2:
                raise e

    def __str__(self):
        return self.name

    def __findDefault(self, compName, valName):
        if compName is not None and \
                self.__defaultComponent is not None and \
                self.__defaultComponent.has_key(compName) and \
                self.__defaultComponent[compName].has_key(valName):
            return self.__defaultComponent[compName][valName]

        if valName == 'logLevel':
            return self.__defaultLogLevel
        elif valName == 'jvm':
            return self.__defaultJVM
        elif valName == 'jvmArgs':
            return self.__defaultJVMArgs

        return None

    def ___parseComponentNode(self, clusterName, host, node):
        "Parse a <component> node from a run cluster description file"
        name = self.getValue(node, 'name')
        if name is None:
            errMsg = ('Cluster "%s" host "%s" has <component> node' +
                      ' without "name" attribute') % (clusterName, host.name)
            raise ClusterDescriptionFormatError(errMsg)

        idStr = self.getValue(node, 'id', '0')
        try:
            id = int(idStr)
        except ValueError:
            errMsg = 'Cluster "%s" host "%s" component "%s" has bad ID "%s"' % \
                (clusterName, host.name, name)
            raise ClusterDescriptionFormatError(errMsg)

        logLvl = self.getValue(node, 'logLevel')
        if logLvl is None:
            logLvl = self.__findDefault(name, 'logLevel')

        jvm = self.getValue(node, 'jvm')
        if jvm is None:
            jvm = self.__findDefault(name, 'jvm')

        jvmArgs = self.getValue(node, 'jvmArgs')
        if jvmArgs is None:
            jvmArgs = self.__findDefault(name, 'jvmArgs')

        required = False

        reqStr = self.getValue(node, 'required')
        if reqStr is not None:
            reqStr = reqStr.lower()
            if reqStr == 'true' or reqStr == '1' or reqStr == 'on':
                required = True

        host.addComponent(name, id, logLvl, jvm, jvmArgs, required)

    def __parseDefaultNodes(self, node):
        for kid in node.childNodes:
            if kid.nodeType != Node.ELEMENT_NODE:
                continue

            if kid.nodeName == 'logLevel':
                self.__defaultLogLevel = self.getChildText(kid)
            elif kid.nodeName == 'jvm':
                self.__defaultJVM = self.getChildText(kid)
            elif kid.nodeName == 'jvmArgs':
                self.__defaultJVMArgs = self.getChildText(kid)
            elif kid.nodeName == 'component':
                name = self.getValue(kid, 'name')
                if name is None:
                    errMsg = ('Cluster "%s" default section has <component>' +
                              ' node without "name" attribute') % clusterName
                    raise ClusterDescriptionFormatError(errMsg)

                if self.__defaultComponent is None:
                    self.__defaultComponent = {}
                self.__defaultComponent[name] = {}

                for cKid in kid.childNodes:
                    if cKid.nodeType != Node.ELEMENT_NODE:
                        continue

                    for valName in ('jvm', 'jvmArgs'):
                        if cKid.nodeName == valName:
                            self.__defaultComponent[name][valName] = \
                                self.getChildText(cKid)

    def __parseSimulatedHubNode(self, clusterName, host, node):
        "Parse a <simulatedHub> node from a run cluster description file"
        numStr = self.getValue(node, 'number', '0')
        try:
            num = int(numStr)
        except ValueError:
            errMsg = ('Cluster "%s" host "%s" has <simulatedHub> node with' +
                      ' bad number "%s"') % (clusterName, host.name, numStr)
            raise ClusterDescriptionFormatError(errMsg)

        prioStr = self.getValue(node, 'priority')
        if prioStr is None:
            errMsg = ('Cluster "%s" host "%s" has <simulatedHub> node' +
                      ' without "priority" attribute') % \
                      (clusterName, host.name)
            raise ClusterDescriptionFormatError(errMsg)
        try:
            prio = int(prioStr)
        except ValueError:
            errMsg = ('Cluster "%s" host "%s" has <simulatedHub> node' +
                      ' with bad priority "%s"') % \
                      (clusterName, host.name, prioStr)
            raise ClusterDescriptionFormatError(errMsg)

        ifUnused = False

        ifStr = self.getValue(node, 'ifUnused')
        if ifStr is None:
            ifUnused = False
        else:
            ifStr = ifStr.lower()
            ifUnused = ifStr == 'true' or ifStr == '1' or ifStr == 'on'

        return ClusterSimHub(host, num, prio, ifUnused)

    def defaultJVM(self, compName=None):
        return self.__findDefault(compName, 'jvm')
    def defaultJVMArgs(self, compName=None):
        return self.__findDefault(compName, 'jvmArgs')
    def defaultLogLevel(self, compName=None):
        return self.__findDefault(compName, 'logLevel')

    def dump(self, prefix=None):
        if prefix is None:
            prefix = ""

        print "%sDescription %s" % (prefix, self.name)
        if self.__logDirForSpade is not None:
            print "%s  SPADE log directory: %s" % \
                (prefix, self.__logDirForSpade)
        if self.__logDirCopies is not None:
            print "%s  Copied log directory: %s" % (prefix, self.__logDirCopies)
        if self.__defaultLogLevel is not None:
            print "%s  Default log level: %s" % (prefix, self.__defaultLogLevel)
        if self.__defaultJVM is not None:
            print "%s  Default Java executable: %s" % \
                (prefix, self.__defaultJVM)
        if self.__defaultJVMArgs is not None:
            print "%s  Default Java arguments: %s" % \
                (prefix, self.__defaultJVMArgs)
        if self.__defaultComponent is not None:
            print "  Default components:"
            for comp in self.__defaultComponent.keys():
                print "%s    %s:" % (prefix, comp)
                if self.__defaultComponent[comp].has_key('jvm'):
                    print "%s      Java executable: %s" % \
                        (prefix, self.__defaultComponent[comp]['jvm'])
                if self.__defaultComponent[comp].has_key('jvmArgs'):
                    print "%s      Java arguments: %s" % \
                        (prefix, self.__defaultComponent[comp]['jvmArgs'])

        if self.__hostMap is not None:
            hKeys = self.__hostMap.keys()
            hKeys.sort()

            for key in hKeys:
                self.__hostMap[key].dump(prefix + "  ")

    def extractFrom(self, dom):
        "Extract all necessary information from a run cluster description file"
        cluster = self.getSingleChild(dom, 'cluster')

        self.name = self.getValue(cluster, 'name')

        self.__logDirForSpade = self.getValue(cluster, 'logDirForSpade')
        self.__logDirCopies = self.getValue(cluster, 'logDirCopies')

        dfltNodes = cluster.getElementsByTagName('default')
        for node in dfltNodes:
            self.__parseDefaultNodes(node)

        hostNodes = cluster.getElementsByTagName('host')
        if len(hostNodes) < 1:
            errMsg = 'No hosts defined for cluster "%s"' % self.name
            raise ClusterDescriptionFormatError(errMsg)

        self.__hostMap = {}
        self.__compToHost = {}

        for node in hostNodes:
            hostName = self.getValue(node, 'name')
            if hostName is None:
                errMsg = ('Cluster "%s" has <host> node without "name"' +
                          ' attribute') % self.name
                raise ClusterDescriptionFormatError(errMsg)

            host = ClusterHost(hostName)

            simHub = None
            for kid in node.childNodes:
                if kid.nodeType != Node.ELEMENT_NODE:
                    continue

                if kid.nodeName == 'component':
                    self.___parseComponentNode(self.name, host, kid)
                elif kid.nodeName == 'controlServer':
                    host.setControlServer()
                elif kid.nodeName == 'simulatedHub':
                    if simHub is not None:
                        errMsg = ('Cluster "%s" host "%s" has multiple' +
                                  ' <simulatedHub> nodes') % (self.name, host)
                        raise ClusterDescriptionFormatError(errMsg)

                    simHub = self.__parseSimulatedHubNode(self.name, host, kid)

            # if we found a <simulatedHub> node, add it now
            if simHub is not None:
                host.addSimulatedHub(simHub)

            # add host to internal host dictionary
            if not self.__hostMap.has_key(hostName):
                self.__hostMap[hostName] = host
            else:
                errMsg = 'Multiple entries for host "%s"' % hostName
                raise ClusterDescriptionFormatError(errMsg)

            for comp in host.getComponents():
                compKey = str(comp)
                if self.__compToHost.has_key(compKey):
                    errMsg = 'Multiple entries for component "%s"' % compKey
                    raise ClusterDescriptionFormatError(errMsg)
                self.__compToHost[compKey] = host

    def getClusterFromHostName(cls):
        """
        Use the host name of the current machine to determine the cluster name.
        Returned values are "sps", "spts", "spts64", or "localhost"
        """

        try:
            hostname = socket.gethostname()
        except:
            hostname = None

        if hostname is not None:
            # SPS is easy
            if hostname.endswith("icecube.southpole.usap.gov"):
                return cls.SPS
            # try to identify test systems
            if hostname.endswith("icecube.wisc.edu"):
                hlist = hostname.split(".")
                if len(hlist) > 4 and \
                       (hlist[1] == cls.SPTS64 or hlist[1] == cls.SPTS):
                    return hlist[1]

        return cls.LOCAL
    getClusterFromHostName = classmethod(getClusterFromHostName)

    def getJVM(self, compName):
        return self.__findDefault(compName, 'jvm')

    def getJVMArgs(self, compName):
        return self.__findDefault(compName, 'jvmArgs')

    def getLogLevel(self, compName):
        return self.__findDefault(compName, 'logLevel')

    def listHostComponentPairs(self):
        for host in self.__hostMap.keys():
            for comp in self.__hostMap[host].getComponents():
                yield (host, comp)
            if self.__hostMap[host].isControlServer():
                yield (host, ControlComponent())

    def listHostSimHubPairs(self):
        for host in self.__hostMap.keys():
            yield (host, self.__hostMap[host].getSimulatedHub())

    def logDirForSpade(self): return self.__logDirForSpade
    def logDirCopies(self): return self.__logDirCopies

if __name__ == '__main__':
    if len(sys.argv) <= 1:
        print >>sys.stderr, 'Usage: %s configXML [configXML ...]' % sys.argv[0]
        sys.exit(1)

    if os.environ.has_key("PDAQ_HOME"):
        metaDir = os.environ["PDAQ_HOME"]
    else:
        from locate_pdaq import find_pdaq_trunk
        metaDir = find_pdaq_trunk()

    configDir = os.path.abspath(os.path.join(metaDir, 'config'))

    for name in sys.argv[1:]:
        dirName = os.path.dirname(name)
        if dirName is None:
            dirName = configDir
            baseName = name
        else:
            baseName = os.path.basename(name)

        try:
            cluster = ClusterDescription(dirName, baseName)
        except UnimplementedException, ue:
            print >>sys.stderr, 'For %s:' % name
            traceback.print_exc()
            continue
        except KeyboardInterrupt:
            break
        except:
            print >>sys.stderr, 'For %s:' % name
            traceback.print_exc()
            continue

        print 'Saw description %s' % cluster.name
        cluster.dump()
