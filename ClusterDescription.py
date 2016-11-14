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


class ClusterDescriptionException(Exception):
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

        self.__load_xml(fileName)

        self.__path = fileName
        self.__mtime = os.stat(self.__path).st_mtime
        self.__configName = configName

    def __load_xml(self, path):
        try:
            dom = minidom.parse(path)
        except Exception as exc:
            raise XMLFormatError('%s: %s' % (path, str(exc)))

        self.extractFrom(dom)

    @property
    def configName(self):
        return self.__configName

    def extractFrom(self, dom):
        raise NotImplementedError('extractFrom method is not implemented')

    def loadIfChanged(self):
        new_mtime = os.stat(self.__path).st_mtime
        if new_mtime == self.__mtime:
            return False

        self.__load_xml(self.__path)

        self.__mtime = new_mtime

        return True


class HSArgs(object):
    def __init__(self, directory, interval, max_files):
        self.__directory = directory
        self.__interval = interval
        self.__max_files = max_files

    def __str__(self):
        outstr = None
        if self.__directory is None:
            outstr = "?"
        else:
            outstr = self.__directory

        if self.__interval is not None:
            outstr += " ival=%s" % self.__interval
        if self.__max_files is not None:
            outstr += " max=%s" % self.__max_files

        return outstr

    @property
    def directory(self):
        return self.__directory

    @property
    def interval(self):
        return self.__interval

    @property
    def maxFiles(self):
        return self.__max_files


class JVMArgs(object):
    def __init__(self, path, isServer, heapInit, heapMax, args, extraArgs):
        self.__path = path
        self.__is_server = isServer
        self.__heap_init = heapInit
        self.__heap_max = heapMax
        self.__args = args
        self.__extra_args = extraArgs

    def __str__(self):
        outstr = None
        if self.__path is None:
            outstr = "?"
        else:
            outstr = self.__path

        if self.__is_server is not None and not self.__is_server:
            outstr += " !server"

        if self.__heap_init is not None:
            outstr += " ms=" + self.__heap_init
        if self.__heap_max is not None:
            outstr += " mx=" + self.__heap_max

        if self.__args is not None:
            outstr += " | " + self.__args

        if self.__extra_args is not None:
            outstr += " | " + self.__extra_args

        return outstr

    @property
    def args(self):
        return self.__args

    @property
    def extraArgs(self):
        return self.__extra_args

    @property
    def heapInit(self):
        return self.__heap_init

    @property
    def heapMax(self):
        return self.__heap_max

    @property
    def isServer(self):
        return self.__is_server == True

    @property
    def path(self):
        return self.__path


class DAQComponent(Component):
    def __init__(self, name, num, logLevel=None):
        super(DAQComponent, self).__init__(name, num, logLevel=logLevel)

        self.__jvm = None

    @property
    def jvmArgs(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.args

    @property
    def jvmExtraArgs(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.extraArgs

    @property
    def jvmHeapInit(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.heapInit

    @property
    def jvmHeapMax(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been set")
        return self.__jvm.heapMax

    @property
    def jvmPath(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been"
                                              " set for %s" % self.fullname)
        return self.__jvm.path

    @property
    def jvmServer(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been"
                                              " set for %s" % self.fullname)
        return self.__jvm.isServer

    @property
    def jvmStr(self):
        if self.__jvm is None:
            raise ClusterDescriptionException("JVM options have not been"
                                              " set for %s" % self.fullname)
        return str(self.__jvm)

    def setJVMOptions(self, defaults, path, isServer, heapInit, heapMax, args,
                      extraArgs):
        # fill in default values for all unspecified JVM quantities
        if path is None:
            path = defaults.find(self.name, 'jvmPath')
            if path is None:
                path = defaults.JVM.path
        if isServer is None:
            isServer = defaults.find(self.name, 'jvmServer')
            if isServer is None:
                isServer = defaults.JVM.isServer
                if isServer is None:
                    isServer = False
        if heapInit is None:
            heapInit = defaults.find(self.name, 'jvmHeapInit')
            if heapInit is None:
                heapInit = defaults.JVM.heapInit
        if heapMax is None:
            heapMax = defaults.find(self.name, 'jvmHeapMax')
            if heapMax is None:
                heapMax = defaults.JVM.heapMax
        if args is None:
            args = defaults.find(self.name, 'jvmArgs')
            if args is None:
                args = defaults.JVM.args
        if extraArgs is None:
            extraArgs = defaults.find(self.name, 'jvmExtraArgs')
            if extraArgs is None:
                extraArgs = defaults.JVM.extraArgs

        self.__jvm = JVMArgs(path, isServer, heapInit, heapMax, args,
                             extraArgs)


class ControlComponent(DAQComponent):
    def __init__(self):
        super(ControlComponent, self).__init__("CnCServer", 0, logLevel=None)

    def __str__(self):
        return self.name

    @property
    def hasHitSpoolOptions(self):
        return False

    @property
    def isControlServer(self):
        return True

    @property
    def isSimHub(self):
        return False

    @property
    def required(self):
        return True


class ClusterComponent(DAQComponent):
    def __init__(self, name, num, logLevel, required):
        self.__required = required

        super(ClusterComponent, self).__init__(name, num, logLevel=logLevel)

    def __str__(self):
        if self.__required:
            rStr = " REQUIRED"
        else:
            rStr = ""

        return "%s@%s(%s | %s)%s" % \
            (self.fullname, str(self.logLevel), self.jvmStr, self.internalStr,
             rStr)

    @property
    def hasHitSpoolOptions(self):
        return False

    @property
    def internalStr(self):
        return ""

    @property
    def isControlServer(self):
        return False

    @property
    def isRealHub(self):
        return False

    @property
    def isSimHub(self):
        return False

    @property
    def required(self):
        return self.__required


class HubComponent(ClusterComponent):
    def __init__(self, name, num, logLevel, required):
        super(HubComponent, self).__init__(name, num, logLevel, required)

        self.__hs = None

    @property
    def hasHitSpoolOptions(self):
        return True

    @property
    def hitspoolDirectory(self):
        if self.__hs is None:
            raise ClusterDescriptionException("HitSpool options have not" +
                                              " been set")
        return self.__hs.directory

    @property
    def hitspoolInterval(self):
        if self.__hs is None:
            raise ClusterDescriptionException("HitSpool options have not" +
                                              " been set")
        return self.__hs.interval

    @property
    def hitspoolMaxFiles(self):
        if self.__hs is None:
            raise ClusterDescriptionException("HitSpool options have not" +
                                              " been set")
        return self.__hs.maxFiles

    @property
    def internalStr(self):
        if self.__hs is None:
            raise ClusterDescriptionException("HitSpool options have not" +
                                              " been set")
        return "hs[%s]" % str(self.__hs)

    @property
    def isRealHub(self):
        return True

    def setHitSpoolOptions(self, directory, interval, maxFiles, defaults):
        if directory is None:
            directory = defaults.find(self.name, 'hitspoolDirectory')
        if interval is None:
            interval = defaults.find(self.name, 'hitspoolInterval')
        if maxFiles is None:
            maxFiles = defaults.find(self.name, 'hitspoolMaxFiles')
        self.__hs = HSArgs(directory, interval, maxFiles)


class SimHubComponent(ClusterComponent):
    def __init__(self, host, number, priority, ifUnused):
        self.__host = host
        self.__number = number
        self.__priority = priority
        self.__ifUnused = ifUnused

        super(SimHubComponent, self).__init__("SimHub", 0, None, False)

    def __str__(self):
        if self.__ifUnused:
            uStr = "(ifUnused)"
        else:
            uStr = ""
        return "%s*%d^%d%s" % \
            (self.__host, self.__number, self.__priority, uStr)

    @property
    def host(self):
        return self.__host

    @property
    def ifUnused(self):
        return self.__ifUnused

    @property
    def isSimHub(self):
        return True

    @property
    def number(self):
        return self.__number

    @property
    def priority(self):
        return self.__priority


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

    def addComponent(self, name, num, logLevel, required=False):
        if name.endswith("Hub"):
            comp = HubComponent(name, num, logLevel, required)
        else:
            comp = ClusterComponent(name, num, logLevel, required)

        compKey = comp.fullname
        if compKey in self.compMap:
            errMsg = 'Multiple entries for component "%s" in host "%s"' % \
                (compKey, self.name)
            raise ClusterDescriptionFormatError(errMsg)
        self.compMap[compKey] = comp

        return comp

    def addSimulatedHub(self, num, prio, ifUnused):
        newHub = SimHubComponent(self, num, prio, ifUnused)

        if self.simHubs is None:
            self.simHubs = []
        for sh in self.simHubs:
            if prio == sh.priority:
                errMsg = 'Multiple <simulatedHub> nodes at prio %d for %s' % \
                         (prio, self.name)
                raise ClusterDescriptionFormatError(errMsg)
        self.simHubs.append(newHub)
        return newHub

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

    @property
    def isControlServer(self):
        return self.ctlServer

    def setControlServer(self):
        self.ctlServer = True


class ClusterDefaults(object):
    def __init__(self):
        self.Components = {}
        self.HS = HSArgs(None, None, None)
        self.JVM = JVMArgs(None, None, None, None, None, None)
        self.LogLevel = ClusterDescription.DEFAULT_LOG_LEVEL

    def __str__(self):
        if not self.Components:
            cstr = ""
        else:
            cstr = ", " + str(self.Components)

        return "ClusterDefaults[hs %s, jvm %s, logLvl %s, args %s]" % \
            (self.HS, self.JVM, self.LogLevel, cstr)

    def find(self, compName, valName):
        if compName is not None and \
                self.Components is not None and \
                compName in self.Components and \
                valName in self.Components[compName]:
            return self.Components[compName][valName]

        if valName == 'hitspoolDirectory':
            return self.HS.directory
        elif valName == 'hitspoolInterval':
            return self.HS.interval
        elif valName == 'hitspoolMaxFiles':
            return self.HS.maxFiles

        if valName == 'jvmPath':
            return self.JVM.path
        elif valName == 'jvmServer':
            return self.JVM.isServer
        elif valName == 'jvmHeapInit':
            return self.JVM.heapInit
        elif valName == 'jvmHeapMax':
            return self.JVM.heapMax
        elif valName == 'jvmArgs':
            return self.JVM.args
        elif valName == 'jvmExtraArgs':
            return self.JVM.extraArgs

        if valName == 'logLevel':
            return self.LogLevel

        return None


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
        self.__host_map = None
        self.__defaults = None

        self.__spade_log_dir = None
        self.__log_dir_copies = None
        self.__daq_data_dir = None
        self.__daq_log_dir = None
        self.__pkg_stage_dir = None
        self.__pkg_install_dir = None

        self.__default_hs = HSArgs(None, None, None)
        self.__default_jvm = JVMArgs(None, None, None, None, None, None)
        self.__default_log_level = self.DEFAULT_LOG_LEVEL

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
    def ___parse_component_node(cls, clusterName, defaults, host, node):
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

        # look for optional logLevel
        logLvl = cls.getValue(node, 'logLevel')
        if logLvl is None:
            logLvl = defaults.find(name, 'logLevel')

        # look for "required" attribute
        reqStr = cls.getValue(node, 'required')
        required = cls.parseBooleanString(reqStr) == True

        comp = host.addComponent(name, num, logLvl, required=required)

        (jvmPath, jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtraArgs) = \
             cls.__parse_jvm_nodes(name, node)
        comp.setJVMOptions(defaults, jvmPath, jvmServer, jvmHeapInit,
                           jvmHeapMax, jvmArgs, jvmExtraArgs)

        if comp.isRealHub:
            (hsDir, hsInterval, hsMaxFiles) = cls.__parse_hs_nodes(name, node)
            comp.setHitSpoolOptions(hsDir, hsInterval, hsMaxFiles, defaults)
            if not cls.dumped:
                cls.dumped = True
    dumped = False

    def __parse_default_nodes(self, cluName, defaults, node):
        """load JVM defaults"""
        (hsDir, hsIval, hsMaxF) = \
            self.__parse_hs_nodes(cluName, node)
        defaults.HS = HSArgs(hsDir, hsIval, hsMaxF)

        (path, isServer, heapInit, heapMax, args, extraArgs) = \
            self.__parse_jvm_nodes(cluName, node)
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

                (hsDir, hsIval, hsMaxF) = self.__parse_hs_nodes(name, kid)
                if hsDir is not None:
                    defaults.Components[name]['hitspoolDirectory'] = hsDir
                if hsIval is not None:
                    defaults.Components[name]['hitspoolInterval'] = hsIval
                if hsMaxF is not None:
                    defaults.Components[name]['hitspoolMaxFiles'] = hsMaxF

                (path, isServer, heapInit, heapMax, args, extraArgs) = \
                    self.__parse_jvm_nodes(name, kid)
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
    def __parse_host_nodes(cls, name, defaults, hostNodes):
        hostMap = {}
        compToHost = {}

        for node in hostNodes:
            hostname = cls.getValue(node, 'name')
            if hostname is None:
                errMsg = ('Cluster "%s" has <host> node without "name"' +
                          ' attribute') % name
                raise ClusterDescriptionFormatError(errMsg)

            host = ClusterHost(hostname)

            for kid in node.childNodes:
                if kid.nodeType != Node.ELEMENT_NODE:
                    continue

                if kid.nodeName == 'component':
                    cls.___parse_component_node(name, defaults, host, kid)
                elif kid.nodeName == 'controlServer':
                    host.setControlServer()
                elif kid.nodeName == 'simulatedHub':
                    cls.__parse_simhub_node(name, defaults, host, kid)

            # add host to internal host dictionary
            if not hostname in hostMap:
                hostMap[hostname] = host
            else:
                errMsg = 'Multiple entries for host "%s"' % hostname
                raise ClusterDescriptionFormatError(errMsg)

            for comp in host.getComponents():
                compKey = comp.fullname
                if compKey in compToHost:
                    errMsg = 'Multiple entries for component "%s"' % compKey
                    raise ClusterDescriptionFormatError(errMsg)
                compToHost[compKey] = host

        return hostMap

    @classmethod
    def __parse_hs_nodes(cls, name, node):
        # create all hitspool-related variables
        hsDir = None
        interval = None
        maxFiles = None

        # look for jvm node
        for hsNode in cls.getChildNodes(node, 'hitspool'):
            tmpDir = cls.getAttr(hsNode, 'directory')
            if tmpDir is not None:
                hsDir = os.path.expanduser(tmpDir)
            tmpStr = cls.getAttr(hsNode, 'interval', defaultVal=interval)
            if tmpStr is not None:
                interval = float(tmpStr)
            tmpStr = cls.getAttr(hsNode, 'maxfiles', defaultVal=maxFiles)
            if tmpStr is not None:
                maxFiles = int(tmpStr)

        return (hsDir, interval, maxFiles)


    @classmethod
    def __parse_jvm_nodes(cls, name, node):
        # create all JVM-related variables
        path = None
        isServer = None
        heapInit = None
        heapMax = None
        args = None
        extraArgs = None

        # look for jvm node
        for jvmNode in cls.getChildNodes(node, 'jvm'):
            tmpPath = cls.getAttr(jvmNode, 'path')
            if tmpPath is not None:
                path = os.path.expanduser(tmpPath)
            tmpSrvr = cls.getAttr(jvmNode, 'server')
            if tmpSrvr is not None:
                isServer = cls.parseBooleanString(tmpSrvr)
            heapInit = cls.getAttr(jvmNode, 'heapInit', defaultVal=heapInit)
            heapMax = cls.getAttr(jvmNode, 'heapMax', defaultVal=heapMax)
            args = cls.getAttr(jvmNode, 'args')
            extraArgs = cls.getAttr(jvmNode, 'extraArgs', defaultVal=extraArgs)

        return (path, isServer, heapInit, heapMax, args, extraArgs)

    @classmethod
    def __parse_simhub_node(cls, clusterName, defaults, host, node):
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

        comp = host.addSimulatedHub(num, prio, ifUnused)

        (jvmPath, jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtraArgs) = \
             cls.__parse_jvm_nodes(clusterName, node)
        comp.setJVMOptions(defaults, jvmPath, jvmServer, jvmHeapInit,
                           jvmHeapMax, jvmArgs, jvmExtraArgs)

        return host

    @property
    def daqDataDir(self):
        if self.__daq_data_dir is None:
            return self.DEFAULT_DATA_DIR
        return self.__daq_data_dir

    @property
    def daqLogDir(self):
        if self.__daq_log_dir is None:
            return self.DEFAULT_LOG_DIR
        return self.__daq_log_dir

    def defaultHSDirectory(self, compName=None):
        return self.__defaults.find(compName, 'hitspoolDirectory')

    def defaultHSInterval(self, compName=None):
        return self.__defaults.find(compName, 'hitspoolInterval')

    def defaultHSMaxFiles(self, compName=None):
        return self.__defaults.find(compName, 'hitspoolMaxFiles')

    def defaultJVMArgs(self, compName=None):
        return self.__defaults.find(compName, 'jvmArgs')

    def defaultJVMExtraArgs(self, compName=None):
        return self.__defaults.find(compName, 'jvmExtraArgs')

    def defaultJVMHeapInit(self, compName=None):
        return self.__defaults.find(compName, 'jvmHeapInit')

    def defaultJVMHeapMax(self, compName=None):
        return self.__defaults.find(compName, 'jvmHeapMax')

    def defaultJVMPath(self, compName=None):
        return self.__defaults.find(compName, 'jvmPath')

    def defaultJVMServer(self, compName=None):
        return self.__defaults.find(compName, 'jvmServer')

    def defaultLogLevel(self, compName=None):
        return self.__defaults.find(compName, 'logLevel')

    def dump(self, fd=None, prefix=None):
        if fd is None:
            fd = sys.stdout
        if prefix is None:
            prefix = ""

        print >>fd, "%sDescription %s" % (prefix, self.name)
        if self.__spade_log_dir is not None:
            print >>fd, "%s  SPADE log directory: %s" % \
                (prefix, self.__spade_log_dir)
        if self.__log_dir_copies is not None:
            print >>fd, "%s  Copied log directory: %s" % \
                (prefix, self.__log_dir_copies)
        if self.__daq_data_dir is not None:
            print >>fd, "%s  DAQ data directory: %s" % \
                (prefix, self.__daq_data_dir)
        if self.__daq_log_dir is not None:
            print >>fd, "%s  DAQ log directory: %s" % \
                (prefix, self.__daq_log_dir)
        if self.__pkg_stage_dir is not None:
            print >>fd, "%s  Package staging directory: %s" % \
                (prefix, self.__pkg_stage_dir)
        if self.__pkg_install_dir is not None:
            print >>fd, "%s  Package installation directory: %s" % \
                (prefix, self.__pkg_install_dir)

        if self.__default_hs is not None:
            if self.__default_hs.directory is not None:
                print >>fd, "%s  Default HS directory: %s" % \
                    (prefix, self.__default_hs.directory)
            if self.__default_hs.interval is not None:
                print >>fd, "%s  Default HS interval: %s" % \
                    (prefix, self.__default_hs.interval)
            if self.__default_hs.maxFiles is not None:
                print >>fd, "%s  Default HS max files: %s" % \
                    (prefix, self.__default_hs.maxFiles)

        if self.__default_jvm is not None:
            if self.__default_jvm.path is not None:
                print >>fd, "%s  Default Java executable: %s" % \
                    (prefix, self.__default_jvm.path)
            if self.__default_jvm.isServer is not None:
                print >>fd, "%s  Default Java server flag: %s" % \
                    (prefix, self.__default_jvm.isServer)
            if self.__default_jvm.heapInit is not None:
                print >>fd, "%s  Default Java heap init: %s" % \
                    (prefix, self.__default_jvm.heapInit)
            if self.__default_jvm.heapMax is not None:
                print >>fd, "%s  Default Java heap max: %s" % \
                    (prefix, self.__default_jvm.heapMax)
            if self.__default_jvm.args is not None:
                print >>fd, "%s  Default Java arguments: %s" % \
                    (prefix, self.__default_jvm.args)
            if self.__default_jvm.extraArgs is not None:
                print >>fd, "%s  Default Java extra arguments: %s" % \
                    (prefix, self.__default_jvm.extraArgs)

        if self.__default_log_level is not None:
            print >>fd, "%s  Default log level: %s" % \
                (prefix, self.__default_log_level)

        if self.__defaults.Components is None or \
           len(self.__defaults.Components) == 0:
            print >>fd, "  **No default components**"
        else:
            print >>fd, "  Default components:"
            for comp in self.__defaults.Components.keys():
                print >>fd, "%s    %s:" % (prefix, comp)

                if 'hitspoolDirectory' in self.__defaults.Components[comp]:
                    print >>fd, "%s      HS directory: %s" % \
                        (prefix,
                         self.__defaults.Components[comp]['hitspoolDirectory'])
                if 'hitspoolInterval' in self.__defaults.Components[comp]:
                    print >>fd, "%s      HS interval: %s" % \
                        (prefix,
                         self.__defaults.Components[comp]['hitspoolInterval'])
                if 'hitspoolMaxFiles' in self.__defaults.Components[comp]:
                    print >>fd, "%s      HS max files: %s" % \
                        (prefix,
                         self.__defaults.Components[comp]['hitspoolMaxFiles'])

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

        if self.__host_map is not None:
            hKeys = self.__host_map.keys()
            hKeys.sort()

            for key in hKeys:
                self.__host_map[key].dump(fd=fd, prefix=prefix + "  ")

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
            self.__parse_default_nodes(name, defaults, node)

        hostNodes = cluster.getElementsByTagName('host')
        if len(hostNodes) < 1:
            errMsg = 'No hosts defined for cluster "%s"' % name
            raise ClusterDescriptionFormatError(errMsg)

        hostMap = self.__parse_host_nodes(name, defaults, hostNodes)

        self.name = name
        self.__defaults = defaults
        self.__host_map = hostMap

        self.__spade_log_dir = self.getValue(cluster, 'logDirForSpade')
        # expand tilde
        if self.__spade_log_dir is not None:
            self.__spade_log_dir = os.path.expanduser(self.__spade_log_dir)

        self.__log_dir_copies = self.getValue(cluster, 'logDirCopies')
        if self.__log_dir_copies is not None:
            self.__log_dir_copies = os.path.expanduser(self.__log_dir_copies)

        self.__daq_data_dir = self.getValue(cluster, 'daqDataDir')
        if self.__daq_data_dir is not None:
            self.__daq_data_dir = os.path.expanduser(self.__daq_data_dir)

        self.__daq_log_dir = self.getValue(cluster, 'daqLogDir')
        if self.__daq_log_dir is not None:
            self.__daq_log_dir = os.path.expanduser(self.__daq_log_dir)

        self.__pkg_stage_dir = self.getValue(cluster, 'packageStageDir')
        if self.__pkg_stage_dir is not None:
            self.__pkg_stage_dir = os.path.expanduser(self.__pkg_stage_dir)

        self.__pkg_install_dir = self.getValue(cluster, 'packageInstallDir')
        if self.__pkg_install_dir is not None:
            self.__pkg_install_dir = os.path.expanduser(self.__pkg_install_dir)

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
        if not name in self.__host_map:
            return None

        return self.__host_map[name]

    def listHostComponentPairs(self):
        for host in self.__host_map.keys():
            for comp in self.__host_map[host].getComponents():
                yield (host, comp)
            if self.__host_map[host].isControlServer:
                yield (host, ControlComponent())

    def listHostSimHubPairs(self):
        for host in self.__host_map.keys():
            if self.__host_map[host].simHubs is not None:
                for sh in self.__host_map[host].simHubs:
                    yield (host, sh)

    @property
    def logDirForSpade(self):
        return self.__spade_log_dir

    @property
    def logDirCopies(self):
        return self.__log_dir_copies

    @property
    def packageStageDir(self):
        if self.__pkg_stage_dir is None:
            return self.DEFAULT_PKGSTAGE_DIR
        return self.__pkg_stage_dir

    @property
    def packageInstallDir(self):
        if self.__pkg_install_dir is None:
            return self.DEFAULT_PKGINSTALL_DIR
        return self.__pkg_install_dir


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
                print >> sys.stderr, 'For %s:' % path
                traceback.print_exc()
                return
            except:
                print >> sys.stderr, 'For %s:' % path
                traceback.print_exc()
                return

        print 'Saw description %s' % cluster.name
        cluster.dump()

    configDir = find_pdaq_config()

    if len(sys.argv) == 1:
        tryCluster(configDir)
    for name in sys.argv[1:]:
        tryCluster(configDir, name)
