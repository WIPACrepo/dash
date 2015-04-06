#!/usr/bin/env python

import os
import socket
import sys
import traceback

from xml.dom import minidom, Node

from Component import Component
from locate_pdaq import find_pdaq_config
from xmlparser import XMLBadFileError, XMLFormatError, XMLParser


class ClusterDescriptionFormatError(XMLFormatError):
    pass


class ConfigXMLBase(XMLParser):
    def __init__(self, configDir, configName, suffix='.xml'):
        fileName = self.buildPath(configDir, configName, suffix=suffix)
        if not os.path.exists(configDir):
            raise XMLBadFileError("Config directory \"%s\" does not exist" %
                                  configDir)
        if fileName is None:
            raise XMLBadFileError('Cannot find "%s" in "%s"' %
                                  (configName, configDir))
        if configName.endswith(suffix):
            configName = configName[:-len(suffix)]

        self.__loadXML(fileName)

        self.__path = fileName
        self.__mtime = os.stat(self.__path).st_mtime
        self.__configName = configName

    def __loadXML(self, path):
        try:
            dom = minidom.parse(path)
        except Exception as e:
            raise XMLFormatError('%s: %s' % (path, str(e)))

        self.extractFrom(dom)

    def configName(self):
        return self.__configName

    def extractFrom(self, dom):
        raise NotImplementedError('extractFrom method is not implemented')

    def loadIfChanged(self):
        new_mtime = os.stat(self.__path).st_mtime
        if new_mtime == self.__mtime:
            return False

        self.__loadXML(self.__path)

        self.__mtime = new_mtime

        return True


class JVMArgs(object):
    def __init__(self, path, isServer, heapInit, heapMax, args, extraArgs):
        self.__path = path
        self.__isServer = isServer
        self.__heapInit = heapInit
        self.__heapMax = heapMax
        self.__args = args
        self.__extraArgs = extraArgs

    def __str__(self):
        outstr = None
        if self.__path is None:
            outstr = "?"
        else:
            outstr = self.__path

        if self.__isServer is not None and not self.__isServer:
            outstr += " !server"

        if self.__heapInit is not None:
            outstr += " ms=" + self.__heapInit
        if self.__heapMax is not None:
            outstr += " mx=" + self.__heapMax

        if self.__args is not None:
            outstr += " | " + self.__args

        if self.__extraArgs is not None:
            outstr += " | " + self.__extraArgs

        return outstr

    def args(self): return self.__args
    def extraArgs(self): return self.__extraArgs
    def heapInit(self): return self.__heapInit
    def heapMax(self): return self.__heapMax
    def isServer(self): return self.__isServer
    def path(self): return self.__path


class JVMComponent(Component):
    def __init__(self, name, num, path, isServer, heapInit, heapMax, args,
                 extraArgs, logLevel=None):
        super(JVMComponent, self).__init__(name, num, logLevel=logLevel)

        self.__jvm = JVMArgs(path, isServer, heapInit, heapMax, args, extraArgs)

    def jvmArgs(self):
        return self.__jvm.args()

    def jvmExtraArgs(self):
        return self.__jvm.extraArgs()

    def jvmHeapInit(self):
        return self.__jvm.heapInit()

    def jvmHeapMax(self):
        return self.__jvm.heapMax()

    def jvmPath(self):
        return self.__jvm.path()

    def jvmServer(self):
        return self.__jvm.isServer()

    def jvmStr(self):
        return str(self.__jvm)

class ControlComponent(JVMComponent):
    def __init__(self):
        super(ControlComponent, self).__init__("CnCServer", 0, None, None, None,
                                               None, None, None)

    def __str__(self):
        return self.name()

    def isControlServer(self):
        return True

    def isSimHub(self):
        return False

    def required(self):
        return True


class ClusterComponent(JVMComponent):
    def __init__(self, name, num, logLevel, jvmPath, jvmServer, jvmHeapInit,
                 jvmHeapMax, jvmArgs, jvmExtraArgs, required):
        self.__required = required

        super(ClusterComponent, self).__init__(name, num, jvmPath, jvmServer,
                                               jvmHeapInit, jvmHeapMax, jvmArgs,
                                               jvmExtraArgs, logLevel=logLevel)

    def __str__(self):
        if self.__required:
            rStr = " REQUIRED"
        else:
            rStr = ""

        return "%s@%s(%s)%s" % \
            (self.fullName(), str(self.logLevel()), self.jvmStr(), rStr)

    def isControlServer(self):
        return False

    def isSimHub(self):
        return False

    def required(self):
        return self.__required


class ClusterSimHub(ClusterComponent):
    def __init__(self, host, number, priority, ifUnused):
        self.host = host
        self.number = number
        self.priority = priority
        self.ifUnused = ifUnused

        super(ClusterSimHub, self).__init__("SimHub", 0, None, None, False,
                                            None, None, None, None, False)

    def __str__(self):
        if self.ifUnused:
            uStr = "(ifUnused)"
        else:
            uStr = ""
        return "%s*%d^%d%s" % (self.host, self.number, self.priority, uStr)

    def isSimHub(self):
        return True


class ClusterHost(object):
    def __init__(self, name):
        self.name = name
        self.compMap = {}
        self.simHubs = None
        self.ctlServer = False

    def __cmp__(self, other):
        return cmp(self.name, str(other))

    def __str__(self):
        return self.name

    def addComponent(self, name, num, logLevel, jvmPath, jvmServer, jvmHeapInit,
                     jvmHeapMax, jvmArgs, jvmExtraArgs, required=False):
        comp = ClusterComponent(name, num, logLevel, jvmPath, jvmServer,
                                jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtraArgs,
                                required)

        compKey = str(comp)
        if compKey in self.compMap:
            errMsg = 'Multiple entries for component "%s" in host "%s"' % \
                (compKey, self.name)
            raise ClusterDescriptionFormatError(errMsg)
        self.compMap[compKey] = comp

    def addSimulatedHub(self, host, num, prio, ifUnused):
        newHub = ClusterSimHub(host, num, prio, ifUnused)

        if self.simHubs is None:
            self.simHubs = []
        for sh in self.simHubs:
            if prio == sh.priority:
                errMsg = 'Multiple <simulatedHub> nodes at prio %d for %s' % \
                         (prio, self.name)
                raise ClusterDescriptionFormatError(errMsg)
        self.simHubs.append(newHub)

    def dump(self, fd=None, prefix=None):
        if fd is None:
            fd = sys.stdout
        if prefix is None:
            prefix = ""

        print >>fd, "%sHost %s:" % (prefix, self.name)

        cKeys = self.compMap.keys()
        cKeys.sort()

        for key in cKeys:
            comp = self.compMap[key]
            print >>fd, "%s  Comp %s" % (prefix, str(comp))

        if self.simHubs is not None:
            for sh in self.simHubs:
                if sh.ifUnused:
                    uStr = " (ifUnused)"
                else:
                    uStr = ""
                print >>fd, "%s  SimHub*%d prio %d%s" % \
                    (prefix, sh.number, sh.priority, uStr)

        if self.ctlServer:
            print >>fd, "%s  ControlServer" % prefix

    def getComponents(self):
        return self.compMap.values()

    def isControlServer(self):
        return self.ctlServer

    def setControlServer(self):
        self.ctlServer = True


class ClusterDefaults(object):
    def __init__(self):
        self.Components = {}
        self.LogLevel = ClusterDescription.DEFAULT_LOG_LEVEL
        self.JVM = JVMArgs(None, None, None, None, None, None)

    def __str__(self):
        if not self.Components:
            cstr = ""
        else:
            cstr = ", " + str(self.Components)

        return "ClusterDefaults[logLvl %s, jvm %s, args %s%s]" % \
            (self.LogLevel, self.JVM, cstr)


class ClusterDescription(ConfigXMLBase):
    LOCAL = "localhost"
    PDAQ2 = "pdaq2"
    SPS = "sps"
    SPTS = "spts"
    SPTSN = "sptsn"
    SPTS64 = "spts64"
    MDFL = "mdfl"

    DBTYPE_TEST = "test"
    DBTYPE_PROD = "production"
    DBTYPE_NONE = "none"

    DEFAULT_DATA_DIR = "/mnt/data/pdaqlocal"
    DEFAULT_LOG_DIR = "/mnt/data/pdaq/log"
    DEFAULT_LOG_LEVEL = "WARN"

    DEFAULT_PKGSTAGE_DIR = "/software/stage/pdaq/dependencies/tar"
    DEFAULT_PKGINSTALL_DIR = "/software/pdaq"

    def __init__(self, configDir=None, configName=None, suffix='.cfg'):

        self.name = None
        self.__hostMap = None

        self.__logDirForSpade = None
        self.__logDirCopies = None
        self.__daqDataDir = None
        self.__daqLogDir = None
        self.__pkgStageDir = None
        self.__pkgInstallDir = None
        self.__defaultLogLevel = self.DEFAULT_LOG_LEVEL
        self.__defaultJVM = JVMArgs(None, None, None, None, None, None)

        if configName is None:
            configName = self.getClusterFromHostName()

        if configDir is None:
            configDir = find_pdaq_config()

        try:
            super(ClusterDescription, self).__init__(configDir, configName,
                                                     suffix)
        except XMLBadFileError:
            saved_ex = sys.exc_info()

            if not configName.endswith('.cfg'):
                retryName = configName
            else:
                retryName = configName[:-4]

            if not retryName.endswith('-cluster'):
                retryName += '-cluster'

            try:
                super(ClusterDescription, self).__init__(configDir, retryName,
                                                         suffix)
            except XMLBadFileError:
                raise saved_ex[0], saved_ex[1], saved_ex[2]

    def __str__(self):
        return self.name

    @classmethod
    def __findDefault(cls, defaults, compName, valName):
        if compName is not None and \
                defaults.Components is not None and \
                compName in defaults.Components and \
                valName in defaults.Components[compName]:
            return defaults.Components[compName][valName]

        if valName == 'logLevel':
            return defaults.LogLevel
        elif valName == 'jvmPath':
            return defaults.JVM.path()
        elif valName == 'jvmServer':
            return defaults.JVM.isServer()
        elif valName == 'jvmHeapInit':
            return defaults.JVM.heapInit()
        elif valName == 'jvmHeapMax':
            return defaults.JVM.heapMax()
        elif valName == 'jvmArgs':
            return defaults.JVM.args()
        elif valName == 'jvmExtraArgs':
            return defaults.JVM.extraArgs()

        return None

    @classmethod
    def ___parseComponentNode(cls, clusterName, defaults, host, node):
        "Parse a <component> node from a cluster configuration file"
        name = cls.getValue(node, 'name')
        if name is None:
            errMsg = ('Cluster "%s" host "%s" has <component> node' +
                      ' without "name" attribute') % (clusterName, host.name)
            raise ClusterDescriptionFormatError(errMsg)

        idStr = cls.getValue(node, 'id', '0')
        try:
            num = int(idStr)
        except ValueError:
            errMsg = ('Cluster "%s" host "%s" component '
                      '"%s" has bad ID "%s"') % \
                (clusterName, host.name, name, idStr)
            raise ClusterDescriptionFormatError(errMsg)

        reqStr = cls.getValue(node, 'required')
        required = cls.parseBooleanString(reqStr) == True

        logLvl = cls.getValue(node, 'logLevel')
        if logLvl is None:
            logLvl = cls.__findDefault(defaults, name, 'logLevel')

        (jvmPath, jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtraArgs) = \
             cls.__parseJVMNodes(node)

        # fill in default values for all unspecified JVM quantities
        if jvmPath is None:
            jvmPath = cls.__findDefault(defaults, name, 'jvmPath')
        if jvmServer is None:
            jvmServer = cls.__findDefault(defaults, name, 'jvmServer')
        if jvmHeapInit is None:
            jvmHeapInit = cls.__findDefault(defaults, name, 'jvmHeapInit')
        if jvmHeapMax is None:
            jvmHeapMax = cls.__findDefault(defaults, name, 'jvmHeapMax')
        if jvmArgs is None:
            jvmArgs = cls.__findDefault(defaults, name, 'jvmArgs')
        if jvmExtraArgs is None:
            jvmExtraArgs = cls.__findDefault(defaults, name, 'jvmExtraArgs')

        host.addComponent(name, num, logLvl, jvmPath, jvmServer, jvmHeapInit,
                          jvmHeapMax, jvmArgs, jvmExtraArgs, required=required)

    def __parseDefaultNodes(self, cluName, defaults, node):
        """load JVM defaults"""
        (path, isServer, heapInit, heapMax, args, extraArgs) = \
            self.__parseJVMNodes(node)
        defaults.JVM = JVMArgs(path, isServer, heapInit, heapMax, args,
                               extraArgs)

        for kid in node.childNodes:
            if kid.nodeType != Node.ELEMENT_NODE:
                continue

            if kid.nodeName == 'logLevel':
                defaults.LogLevel = self.getChildText(kid)
            elif kid.nodeName == 'component':
                name = self.getValue(kid, 'name')
                if name is None:
                    errMsg = ('Cluster "%s" default section has <component>' +
                              ' node without "name" attribute') % cluName
                    raise ClusterDescriptionFormatError(errMsg)

                if not name in defaults.Components:
                    defaults.Components[name] = {}

                (path, isServer, heapInit, heapMax, args, extraArgs) = \
                    self.__parseJVMNodes(kid)
                if path is not None:
                    defaults.Components[name]['jvmPath'] = path
                if isServer is not None:
                    defaults.Components[name]['jvmServer'] = isServer
                if heapInit is not None:
                    defaults.Components[name]['jvmHeapInit'] = heapInit
                if heapMax is not None:
                    defaults.Components[name]['jvmHeapMax'] = heapMax
                if args is not None:
                    defaults.Components[name]['jvmArgs'] = args
                if extraArgs is not None:
                    defaults.Components[name]['jvmExtraArgs'] = extraArgs

                for cKid in kid.childNodes:
                    if cKid.nodeType == Node.ELEMENT_NODE and \
                       cKid.nodeName == 'logLevel':
                        defaults.Components[name]['logLevel'] = \
                            self.getChildText(cKid)
                        continue


    @classmethod
    def __parseHostNodes(cls, name, defaults, hostNodes):
        hostMap = {}
        compToHost = {}

        for node in hostNodes:
            hostName = cls.getValue(node, 'name')
            if hostName is None:
                errMsg = ('Cluster "%s" has <host> node without "name"' +
                          ' attribute') % name
                raise ClusterDescriptionFormatError(errMsg)

            host = ClusterHost(hostName)

            for kid in node.childNodes:
                if kid.nodeType != Node.ELEMENT_NODE:
                    continue

                if kid.nodeName == 'component':
                    cls.___parseComponentNode(name, defaults, host, kid)
                elif kid.nodeName == 'controlServer':
                    host.setControlServer()
                elif kid.nodeName == 'simulatedHub':
                    simData = cls.__parseSimulatedHubNode(name, host, kid)
                    host.addSimulatedHub(simData[0], simData[1], simData[2],
                                         simData[3])

            # add host to internal host dictionary
            if not hostName in hostMap:
                hostMap[hostName] = host
            else:
                errMsg = 'Multiple entries for host "%s"' % hostName
                raise ClusterDescriptionFormatError(errMsg)

            for comp in host.getComponents():
                compKey = str(comp)
                if compKey in compToHost:
                    errMsg = 'Multiple entries for component "%s"' % compKey
                    raise ClusterDescriptionFormatError(errMsg)
                compToHost[compKey] = host

        return (hostMap, compToHost)

    @classmethod
    def __parseJVMNodes(cls, node):
        # create all JVM-related variables
        path = None
        isServer = None
        heapInit = None
        heapMax = None
        args = None
        extraArgs = None

        # try to get text from old jvmArgs node
        for argsNode in cls.getChildNodes(node, 'jvmArgs'):
            args = cls.getChildText(argsNode)

        # look for jvm node
        for jvmNode in cls.getChildNodes(node, 'jvm'):
            nodePath = None
            tmpPath = cls.getChildText(jvmNode)
            if tmpPath is not None:
                tmpPath = tmpPath.strip()
                if tmpPath != "":
                    nodePath = os.path.expanduser(tmpPath)
            tmpPath = cls.getAttr(jvmNode, 'path')
            if tmpPath is not None:
                if nodePath is not None:
                    raise XMLFormatError("%s contains both <jvm path=xxx>"
                                         " and <jvm>xxx</jvm>" % name)
                nodePath = os.path.expanduser(tmpPath)
            if nodePath is not None:
                path = nodePath
            tmpSrvr = cls.getAttr(jvmNode, 'server')
            if tmpSrvr is not None:
                isServer = cls.parseBooleanString(tmpSrvr)
            heapInit = cls.getAttr(jvmNode, 'heapInit', defaultVal=heapInit)
            heapMax = cls.getAttr(jvmNode, 'heapMax', defaultVal=heapMax)
            tmpArgs = cls.getAttr(jvmNode, 'args')
            if tmpArgs is not None:
                if args is not None:
                    raise XMLFormatError("%s contains both <jvm args=xxx>"
                                         " and <jvmArgs>" % name)
                args = tmpArgs
            extraArgs = cls.getAttr(jvmNode, 'extraArgs', defaultVal=extraArgs)

        return (path, isServer, heapInit, heapMax, args, extraArgs)

    @classmethod
    def __parseSimulatedHubNode(cls, clusterName, host, node):
        "Parse a <simulatedHub> node from a cluster configuration file"
        numStr = cls.getValue(node, 'number', '0')
        try:
            num = int(numStr)
        except ValueError:
            errMsg = ('Cluster "%s" host "%s" has <simulatedHub> node with' +
                      ' bad number "%s"') % (clusterName, host.name, numStr)
            raise ClusterDescriptionFormatError(errMsg)

        prioStr = cls.getValue(node, 'priority')
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

        ifStr = cls.getValue(node, 'ifUnused')
        ifUnused = cls.parseBooleanString(ifStr) == True

        return (host, num, prio, ifUnused)

    def daqDataDir(self):
        if self.__daqDataDir is None:
            return self.DEFAULT_DATA_DIR
        return self.__daqDataDir

    def daqLogDir(self):
        if self.__daqLogDir is None:
            return self.DEFAULT_LOG_DIR
        return self.__daqLogDir

    def defaultJVMArgs(self, compName=None):
        return self.__findDefault(self.__defaults, compName, 'jvmArgs')

    def defaultJVMExtraArgs(self, compName=None):
        return self.__findDefault(self.__defaults, compName, 'jvmExtraArgs')

    def defaultJVMHeapInit(self, compName=None):
        return self.__findDefault(self.__defaults, compName, 'jvmHeapInit')

    def defaultJVMHeapMax(self, compName=None):
        return self.__findDefault(self.__defaults, compName, 'jvmHeapMax')

    def defaultJVMPath(self, compName=None):
        return self.__findDefault(self.__defaults, compName, 'jvmPath')

    def defaultJVMServer(self, compName=None):
        return self.__findDefault(self.__defaults, compName, 'jvmServer')

    def defaultLogLevel(self, compName=None):
        return self.__findDefault(self.__defaults, compName, 'logLevel')

    def dump(self, fd=None, prefix=None):
        if fd is None:
            fd = sys.stdout
        if prefix is None:
            prefix = ""

        print >>fd, "%sDescription %s" % (prefix, self.name)
        if self.__logDirForSpade is not None:
            print >>fd, "%s  SPADE log directory: %s" % \
                (prefix, self.__logDirForSpade)
        if self.__logDirCopies is not None:
            print >>fd, "%s  Copied log directory: %s" % \
                (prefix, self.__logDirCopies)
        if self.__daqDataDir is not None:
            print >>fd, "%s  DAQ data directory: %s" % \
                (prefix, self.__daqDataDir)
        if self.__daqLogDir is not None:
            print >>fd, "%s  DAQ log directory: %s" % \
                (prefix, self.__daqLogDir)
        if self.__pkgStageDir is not None:
            print >>fd, "%s  Package staging directory: %s" % \
                (prefix, self.__pkgStageDir)
        if self.__pkgInstallDir is not None:
            print >>fd, "%s  Package installation directory: %s" % \
                (prefix, self.__pkgInstallDir)
        if self.__defaultLogLevel is not None:
            print >>fd, "%s  Default log level: %s" % \
                (prefix, self.__defaultLogLevel)
        if self.__defaultJVM.path() is not None:
            print >>fd, "%s  Default Java executable: %s" % \
                (prefix, self.__defaultJVM.path())
        if self.__defaultJVM.isServer() is not None:
            print >>fd, "%s  Default Java server flag: %s" % \
                (prefix, self.__defaultJVM.isServer())
        if self.__defaultJVM.heapInit() is not None:
            print >>fd, "%s  Default Java heap init: %s" % \
                (prefix, self.__defaultJVM.heapInit())
        if self.__defaultJVM.heapMax() is not None:
            print >>fd, "%s  Default Java heap max: %s" % \
                (prefix, self.__defaultJVM.heapMax())
        if self.__defaultJVM.args() is not None:
            print >>fd, "%s  Default Java arguments: %s" % \
                (prefix, self.__defaultJVM.args())
        if self.__defaultJVM.extraArgs() is not None:
            print >>fd, "%s  Default Java extra arguments: %s" % \
                (prefix, self.__defaultJVM.extraArgs())
        if self.__defaults.Components is None or \
           len(self.__defaults.Components) == 0:
            print >>fd, "  **No default components**"
        else:
            print >>fd, "  Default components:"
            for comp in self.__defaults.Components.keys():
                print >>fd, "%s    %s:" % (prefix, comp)
                if 'jvmPath' in self.__defaults.Components[comp]:
                    print >>fd, "%s      Java executable: %s" % \
                        (prefix, self.__defaults.Components[comp]['jvmPath'])
                if 'jvmServer' in self.__defaults.Components[comp]:
                    print >>fd, "%s      Java server flag: %s" % \
                        (prefix, self.__defaults.Components[comp]['jvmServer'])
                if 'jvmHeapInit' in self.__defaults.Components[comp]:
                    print >>fd, "%s      Java initial heap size: %s" % \
                        (prefix,
                         self.__defaults.Components[comp]['jvmHeapInit'])
                if 'jvmHeapMax' in self.__defaults.Components[comp]:
                    print >>fd, "%s      Java maximum heap size: %s" % \
                        (prefix, self.__defaults.Components[comp]['jvmHeapMax'])
                if 'jvmArgs' in self.__defaults.Components[comp]:
                    print >>fd, "%s      Java arguments: %s" % \
                        (prefix, self.__defaults.Components[comp]['jvmArgs'])
                if 'jvmExtraArgs' in self.__defaults.Components[comp]:
                    print >>fd, "%s      Java extra arguments: %s" % \
                        (prefix,
                         self.__defaults.Components[comp]['jvmExtraArgs'])
                if 'logLevel' in self.__defaults.Components[comp]:
                    print >>fd, "%s      Log level: %s" % \
                        (prefix, self.__defaults.Components[comp]['logLevel'])

        if self.__hostMap is not None:
            hKeys = self.__hostMap.keys()
            hKeys.sort()

            for key in hKeys:
                self.__hostMap[key].dump(fd=fd, prefix=prefix + "  ")

    def extractFrom(self, dom):
        "Extract all necessary information from a cluster configuration file"
        cluName = 'cluster'
        kids = dom.getElementsByTagName(cluName)
        if len(kids) < 1:
            raise XMLFormatError('No <%s> node found' % cluName)
        elif len(kids) > 1:
            raise XMLFormatError('Multiple <%s> nodes found' % cluName)

        cluster = kids[0]

        name = self.getValue(cluster, 'name')

        defaults = ClusterDefaults()

        dfltNodes = cluster.getElementsByTagName('default')
        for node in dfltNodes:
            self.__parseDefaultNodes(name, defaults, node)

        hostNodes = cluster.getElementsByTagName('host')
        if len(hostNodes) < 1:
            errMsg = 'No hosts defined for cluster "%s"' % name
            raise ClusterDescriptionFormatError(errMsg)

        (hostMap, compToHost) = self.__parseHostNodes(name, defaults, hostNodes)

        self.name = name
        self.__defaults = defaults
        self.__hostMap = hostMap

        self.__logDirForSpade = self.getValue(cluster, 'logDirForSpade')
        # expand tilde
        if self.__logDirForSpade is not None:
            self.__logDirForSpade = os.path.expanduser(self.__logDirForSpade)

        self.__logDirCopies = self.getValue(cluster, 'logDirCopies')
        if self.__logDirCopies is not None:
            self.__logDirCopies = os.path.expanduser(self.__logDirCopies)

        self.__daqDataDir = self.getValue(cluster, 'daqDataDir')
        if self.__daqDataDir is not None:
            self.__daqDataDir = os.path.expanduser(self.__daqDataDir)

        self.__daqLogDir = self.getValue(cluster, 'daqLogDir')
        if self.__daqLogDir is not None:
            self.__daqLogDir = os.path.expanduser(self.__daqLogDir)

        self.__pkgStageDir = self.getValue(cluster, 'packageStageDir')
        if self.__pkgStageDir is not None:
            self.__pkgStageDir = os.path.expanduser(self.__pkgStageDir)

        self.__pkgInstallDir = self.getValue(cluster, 'packageInstallDir')
        if self.__pkgInstallDir is not None:
            self.__pkgInstallDir = os.path.expanduser(self.__pkgInstallDir)

    @classmethod
    def getClusterFromHostName(cls, hostname=None):
        """
        Determine the cluster name from 'hostname'.
        Returned values are "sps", "spts", "spts64", or "localhost".
        If 'hostname' is not set, the host name of the current machine is used.
        """

        if hostname is None:
            try:
                hostname = socket.gethostname()
            except:
                hostname = None

        if hostname is not None:
            # SPS is easy
            if hostname.endswith("icecube.southpole.usap.gov"):
                hname = hostname.split(".", 1)[0]
                if hname == "pdaq2":
                    return cls.PDAQ2
                else:
                    return cls.SPS
            # try to identify test systems
            if hostname.endswith("icecube.wisc.edu"):
                hlist = hostname.split(".")
                if len(hlist) > 4 and \
                       (hlist[1] == cls.SPTS64 or hlist[1] == cls.SPTS):
                    return hlist[1]
                if len(hlist) > 4 and hlist[1] == cls.SPTSN:
                    return cls.SPTS
                if hostname.startswith("mdfl"):
                    return cls.MDFL

        return cls.LOCAL

    @classmethod
    def getClusterDatabaseType(cls, clu=None):
        """
        Determine the database type for the cluster description.
        'clu' should be one of the ClusterDescription constants
        """
        if clu is None:
            clu = cls.getClusterFromHostName()
        if clu == cls.SPTS or clu == cls.SPTS64:
            dbname = cls.getLiveDBName()
            if dbname is None or dbname == "I3OmDb_test":
                return cls.DBTYPE_TEST
            elif dbname == "I3OmDb":
                return cls.DBTYPE_PROD
            raise NotImplementedError(("Unknown database \"%s\" for" +
                                       " cluster \"%s\"") % (dbname, clu))
        if clu == cls.SPS or clu == cls.PDAQ2:
            return cls.DBTYPE_PROD
        if clu == cls.LOCAL or clu == cls.MDFL:
            return cls.DBTYPE_NONE
        raise NotImplementedError("Cannot guess database" +
                                     " for cluster \"%s\"" % clu)

    @classmethod
    def getLiveDBName(cls):
        liveConfigName = ".i3live.conf"

        path = os.path.join(os.environ["HOME"], liveConfigName)
        if os.path.exists(path):
            with open(path, "r") as fd:
                for line in fd:
                    if line.startswith("["):
                        ridx = line.find("]")
                        if ridx < 0:
                            # ignore line with bad section marker
                            continue

                        section = line[1:ridx]
                        continue

                    if section != "livecontrol":
                        continue

                    pos = line.find("=")
                    if pos < 0:
                        continue

                    if line[:pos].strip() != "dbname":
                        continue

                    return line[pos + 1:].strip()

        return None


    def host(self, name):
        if not name in self.__hostMap:
            return None

        return self.__hostMap[name]

    def listHostComponentPairs(self):
        for host in self.__hostMap.keys():
            for comp in self.__hostMap[host].getComponents():
                yield (host, comp)
            if self.__hostMap[host].isControlServer():
                yield (host, ControlComponent())

    def listHostSimHubPairs(self):
        for host in self.__hostMap.keys():
            if self.__hostMap[host].simHubs is not None:
                for sh in self.__hostMap[host].simHubs:
                    yield (host, sh)

    def logDirForSpade(self):
        return self.__logDirForSpade

    def logDirCopies(self):
        return self.__logDirCopies

    def packageStageDir(self):
        if self.__pkgStageDir is None:
            return self.DEFAULT_PKGSTAGE_DIR
        return self.__pkgStageDir

    def packageInstallDir(self):
        if self.__pkgInstallDir is None:
            return self.DEFAULT_PKGINSTALL_DIR
        return self.__pkgInstallDir

    def setDefaultJVMPath(self, value):
        self.__defaultJVMPath = value

    def setDefaultJVMArgs(self, value):
        self.__defaultJVMArgs = value

    def setDefaultLogLevel(self, value):
        self.__defaultLogLevel = value

if __name__ == '__main__':
    def tryCluster(configDir, path=None):
        if path is None:
            cluster = ClusterDescription(configDir)
        else:
            dirName = os.path.dirname(path)
            if dirName is None or len(dirName) == 0:
                dirName = configDir
                baseName = path
            else:
                baseName = os.path.basename(path)

            try:
                cluster = ClusterDescription(dirName, baseName)
            except KeyboardInterrupt:
                return
            except NotImplementedError:
                print >> sys.stderr, 'For %s:' % name
                traceback.print_exc()
                return
            except:
                print >> sys.stderr, 'For %s:' % name
                traceback.print_exc()
                return

        print 'Saw description %s' % cluster.name
        cluster.dump()

    configDir = find_pdaq_config()

    if len(sys.argv) == 1:
        tryCluster(configDir)
    for name in sys.argv[1:]:
        tryCluster(configDir, name)
