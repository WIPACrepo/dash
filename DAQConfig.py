#!/usr/bin/env python

# DAQ Configuration reader/parser
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
#
# Class to parse XML configuration information for IceCube runs

import optparse, os, re
from xml.dom import minidom
from exc_string import exc_string
from CachedConfigName import CachedConfigName
from ClusterConfig \
    import ClusterConfig, ConfigNotFoundException, ConfigNotSpecifiedException
from RunCluster import RunCluster

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class DAQConfigException      (Exception)         : pass
class DAQConfigNotFound       (DAQConfigException): pass
class DAQConfigDirNotFound    (DAQConfigException): pass
class multipleStringNumbers   (DAQConfigException): pass
class noRunConfigFound        (DAQConfigException): pass
class noDOMConfigFound        (DAQConfigException):
    def __init__(self, configName):
        Exception.__init__(self, configName)

        self.configName = configName

    def __str__(self):
        return self.configName

class noDeployedDOMsListFound (DAQConfigException): pass
class badDeployedDOMsListFound(DAQConfigException): pass
class noComponentsFound       (DAQConfigException): pass
class triggerException        (DAQConfigException): pass
class DOMNotInConfigException (DAQConfigException): pass

def showList(configDir, configName=None):
    if not os.path.exists(configDir):
        raise DAQConfigDirNotFound("Could not find config dir %s" % configDir)
    l = os.listdir(configDir)

    cfgs = []
    for f in l:
        match = re.search(r'^(.+?)\.xml$', f)
        if not match: continue
        cfg = match.group(1)
        if cfg == 'default-dom-geometry': continue
        cfgs.append(cfg)

    cfgs.sort()
    for cname in cfgs:
        if cname == configName: arrow = '=> '
        else: arrow = '   '
        print "%3s%60s" % (arrow, cname)

def xmlOf(name):
    if not re.search(r'^(.+?)\.xml$', name): return name+".xml"
    return name

def configExists(configDir, configName):
    if not os.path.exists(configDir): return False
    configFile = xmlOf(os.path.join(configDir, configName))
    if not os.path.exists(configFile): return False
    return True

def checkForValidConfig(configDir, configName):
    try:
        DAQConfig(configName, configDir)
        print "%s/%s is ok." % (configDir, configName)
        return True
    except Exception, e:
        print "%s/%s is not a valid config: %s [%s]" % \
            (configDir, configName, e, exc_string())
        return False

class DOMData(object):
    """
    DOM Geometry data
    """
    def __init__(self, name, string, pos):
        self.name = name
        self.string = string
        self.pos = pos

        if(re.search(r'AMANDA_', name)): self.kind = "amanda"
        elif(pos > 60):                  self.kind = "icetop"
        else:                            self.kind = "in-ice"

class DefaultDOMGeometry(object):

    DEPLOYEDDOMS            = "default-dom-geometry.xml"

    def __init__(self, configDir):
        """
        Convert the default-dom-geometry.xml file to a dictionary
        of DOMData objects
        """
        deployedDOMsXML = xmlOf(os.path.join(configDir, self.DEPLOYEDDOMS))
        if not os.path.exists(deployedDOMsXML):
            raise noDeployedDOMsListFound("no deployed DOMs list found!")

        try:
            deployedDOMsParsed = minidom.parse(deployedDOMsXML)
        except:
            raise badDeployedDOMSListFound("Cannot parse %s" % deployedDOMsXML)

        deployedStrings = deployedDOMsParsed.getElementsByTagName("string")
        if len(deployedStrings) < 1:
            raise noDeployedDOMsListFound("No string list in %s!" %
                                          DefaultDOMGeometry.DEPLOYEDDOMS)

        self.domDict  = {}

        for string in deployedStrings:
            stringNumTag = string.getElementsByTagName("number")
            if len(stringNumTag) != 1:
                raise multipleStringNumbers("Found multiple string numbers")
            stringNum    = int(stringNumTag[0].childNodes[0].data)
            domlist = string.getElementsByTagName("dom")
            for dom in domlist:
                domIDtag    = dom.getElementsByTagName("mainBoardId")
                domID       = domIDtag[0].childNodes[0].data
                nameTag     = dom.getElementsByTagName("name")
                name        = nameTag[0].childNodes[0].data
                positionTag = dom.getElementsByTagName("position")
                position    = int(positionTag[0].childNodes[0].data)
                # print "%20s %25s %2d %2d %s" % \
                # (domID, name, stringNum, position, kind)

                self.domDict[domID] = DOMData(name, stringNum, position)

        # clean up DOM
        deployedDOMsParsed.unlink()

    def getHubID(self, domID):
        """
        Get the stringhub id associated with the DOM mainboard ID
        """
        if not self.domDict.has_key(domID):
            raise DOMNotInConfigException("Cannot find DOM %12s" % domID)
        return self.domDict[domID].string

    def getKind(self, domID):
        """
        Get the trigger kind associated with the DOM mainboard ID
        """
        if not self.domDict.has_key(domID):
            raise DOMNotInConfigException("Cannot find DOM %12s" % domID)
        return self.domDict[domID].kind

    def getIDbyName(self, domlist, name):
        """
        Get DOM mainboard ID for given DOM name (e.g., 'Alpaca').
        Names from deployed DOMs list supercede names in domconfig files.
        Raise DOMNotInConfigException if DOM is missing
        """
        for d in domlist:
            if self.domDict.has_key(d) and self.domDict[d].name == name:
                return str(d) # Convert from unicode to ASCII
        raise DOMNotInConfigException("Cannot find DOM named \"%s\"" % name)

    def getIDbyStringPos(self, domlist, string, pos):
        """
        Get DOM mainboard ID for a given string, position.
        Raise DOMNotInConfigException if DOM is missing
        """
        for d in domlist:
            if self.domDict.has_key(d) and \
                    string == self.domDict[d].string and \
                    pos == self.domDict[d].pos:
                return str(d)
        raise DOMNotInConfigException("Cannot find string %d pos %d" %
                                      (string, pos))

class Component(object):
    def __init__(self, name, id, logLevel):
        self.__name = name
        self.__id = id
        self.__logLevel = logLevel

    def __cmp__(self, other):
        val = cmp(self.__name, other.__name)
        if val == 0:
            val = cmp(self.__id, other.__id)
        return val

    def __str__(self):
        if self.__id == 0 and not self.isHub():
            return self.__name
        return '%s#%d' % (self.__name, self.__id)

    def __repr__(self): return self.__str__()

    def id(self): return self.__id

    def isHub(self):
        return self.__name.lower().find('hub') >= 0

    def isRealHub(self):
        return self.__name == 'StringHub' and self.__id < 1000

    def logLevel(self): return self.__logLevel
    def name(self): return self.__name

    def setLogLevel(self, lvl):
        self.__logLevel = lvl

class DAQConfig(object):

    # Parse this only once, in case we cycle over multiple configs
    DeployedDOMs   = None
    persister      = {}

    def __init__(self, configName="default",
                 configDir=metaDir + "/config"):

        if configName is None:
            raise DAQConfigNotFound('No filename specified')

        if not os.path.exists(configDir):
            raise DAQConfigDirNotFound("Could not find config dir %s" %
                                       configDir)
        tmpFile = xmlOf(os.path.join(configDir, configName))

        try:
            cfgStat = os.stat(tmpFile)
        except OSError:
            raise DAQConfigNotFound(tmpFile)

        # Optimize by looking up pre-parsed configurations:
        if DAQConfig.persister.has_key(tmpFile):
            self.__dict__ = DAQConfig.persister[tmpFile]

            if self.__modTime == cfgStat.st_mtime:
                # file has not been modified; use old values
                return

        self.configFile = tmpFile
        self.__modTime = cfgStat.st_mtime

        # Parse the runconfig
        try:
            parsed = minidom.parse(self.configFile)
        except:
            raise DAQConfigException("Cannot parse %s" % self.configFile)

        configs = parsed.getElementsByTagName("runConfig")
        if len(configs) < 1: raise noRunConfigFound("No runconfig field found!")

        # Parse the comprehensive lookup table "default-dom-geometry.xml"
        if DAQConfig.DeployedDOMs == None:
            DAQConfig.DeployedDOMs = DefaultDOMGeometry(configDir)

        self.domlist = []
        self.kindList  = []

        hubIDList = []

        noDOMs = configs[0].getElementsByTagName("noDOMConfig")
        domCfgList = configs[0].getElementsByTagName("domConfigList")
        hubFileList = configs[0].getElementsByTagName("hubFiles")

        hubType = None

        if len(noDOMs) > 0:
            pass

        elif len(domCfgList) > 0:
            for domConfig in domCfgList:
                if len(domConfig.childNodes) == 0:
                    continue

                domConfigName = domConfig.childNodes[0].data
                # print "Parsing %s" % domConfigName

                domConfigXML = \
                    xmlOf(os.path.join(configDir, "domconfigs", domConfigName))
                if not os.path.exists(domConfigXML):
                    raise noDOMConfigFound("DOMConfig not found: %s" %
                                           domConfigName)

                try:
                    domConfigParsed = minidom.parse(domConfigXML)
                except:
                    raise noDOMConfigFound("Cannot parse %s" % domConfigXML)

                for dom in domConfigParsed.getElementsByTagName("domConfig"):
                    self.domlist.append(dom.getAttribute("mbid"))
                domConfigParsed.unlink()

            hubIDInConfigDict = {}
            kindInConfigDict  = {}

            for domID in self.domlist:
                hubID  = DAQConfig.DeployedDOMs.getHubID(domID)
                kind   = DAQConfig.DeployedDOMs.getKind(domID)
                # print "Got DOM %s hub %s kind %s" % (domID, hubID, kind)
                hubIDInConfigDict[hubID] = True
                kindInConfigDict[kind]   = True

            self.kindList  = kindInConfigDict.keys()
            hubIDList      = hubIDInConfigDict.keys()

            hubType = 'stringHub'

        elif len(hubFileList) == 1:
            # WARNING: not currently building the 'kind' list
            for hubNode in hubFileList[0].getElementsByTagName("hub"):
                idStr = hubNode.getAttribute("id")
                hubIDList.append(int(idStr))

            hubType = 'replayHub'

        self.ndoms = len(self.domlist)
        # print "Found %d DOMs." % self.ndoms

        self.checkTriggerConfigFile(configs[0], configDir)

        self.compList = []

        for hubID in hubIDList:
            self.__addComponent(hubType, hubID)

        self.__extractComponents(configs[0])

        DAQConfig.persister[self.configFile] = self.__dict__

    def __addComponent(self, compName, compId, logLevel=None):
        comp = self.__findComponent(compName, compId)
        if comp is None:
            self.compList.append(Component(compName, compId, logLevel))
        elif logLevel is not None:
            if comp.logLevel() is None:
                comp.setLogLevel(logLevel)
            elif logLevel != comp.logLevel():
                #print >>sys.stderr, '%s: Changing log level "%s" to "%s"' % \
                #    (str(comp), comp.logLevel(), logLevel)
                comp.setLogLevel(logLevel)

    def __extractComponents(self, config):
        compNodes = config.getElementsByTagName("runComponent")
        if len(compNodes) == 0: raise noComponentsFound("No components found")
        for node in compNodes:
            if not node.attributes.has_key('name'):
                continue

            nodeName = node.attributes['name'].value
            if not node.attributes.has_key('id'):
                nodeId = 0
            else:
                nodeId = int(node.attributes['id'].value)
            if not node.attributes.has_key('logLevel'):
                logLevel = None
            else:
                logLevel = node.attributes['logLevel'].value

            self.__addComponent(nodeName, nodeId, logLevel)

    def __findComponent(self, compName, compId):
        if compName is not None:
            for comp in self.compList:
                if comp.name().lower() == compName.lower() and \
                        comp.id() == compId:
                    return comp
        return None

    def checkTriggerConfigFile(self, config, configDir):
        triggerConfigs = config.getElementsByTagName("triggerConfig")
        if len(triggerConfigs) == 0: raise triggerException("no triggers found")
        for trig in triggerConfigs:
            if len(trig.childNodes) == 0:
                continue

            trigName = trig.childNodes[0].data
            trigXML = xmlOf(os.path.join(configDir, "trigger", trigName))
            if not os.path.exists(trigXML):
                raise triggerException("trigger config file not found: %s" %
                                       trigXML)

    def kinds(self):
        """
        Return list of detectors in configuration: any of
        amanda, in-ice, icetop
        """
        return self.kindList

    def components(self):
        "Return list of components (as strings) in parsed configuration."
        compStr = []
        for comp in self.compList:
            compStr.append(str(comp))
        return compStr

    def getClusterConfig(self, clusterDesc=None, configDir=None):
        "Get cluster->component mapping for the current configuration"
        return RunCluster(self, clusterDesc, configDir)

    def getComponentObjects(self):
        "Return list of components objects in parsed configuration."
        return self.compList

    def hasDOM(self, domid):
        """
        Indicate whether DOM mainboard id domid is in the current configuration
        """
        for d in self.domlist:
            if d == domid: return True
        return False

    def getIDbyName(self, name):
        """
        Get DOM mainboard ID for given DOM name (e.g., 'Alpaca').
        Names from deployed DOMs list supercede names in domconfig files.
        Raise DOMNotInConfigException if DOM is missing
        """
        return DAQConfig.DeployedDOMs.getIDbyName(self.domlist, name)

    def getIDbyStringPos(self, string, pos):
        """
        Get DOM mainboard ID for a given string, position.
        Raise DOMNotInConfigException if DOM is missing
        """
        return DAQConfig.DeployedDOMs.getIDbyStringPos(self.domlist, string,
                                                       pos)

    def getClusterConfiguration(cls, configName, doList=False,
                                useActiveConfig=False, clusterDesc=None,
                                configDir=None):
        """
        Find and parse the cluster configuration from either the
        run configuration directory or from the old cluster configuration
        directory
        """
        ex = None

        if configName is None:
            configName = \
                CachedConfigName().getConfigToUse(None, False, useActiveConfig)
            if configName is None:
                raise ConfigNotSpecifiedException("No configuration specified")

        sepIndex = configName.find('@')
        if sepIndex > 0:
            clusterDesc = configName[sepIndex+1:]
            configName = configName[:sepIndex]

        if configDir is None:
            configDir = os.path.join(metaDir, 'config')

        if doList:
            showList(configDir, configName)
            return

        try:
            runCfg = DAQConfig(configName, configDir)
            cfg = runCfg.getClusterConfig(clusterDesc)
        except DAQConfigNotFound, nfe:
            ex = nfe

        if ex is not None:
            try:
                cfg = ClusterConfig(configDir, configName,
                                    useFallbackConfig=False)
            except ConfigNotFoundException, ex2:
                raise ex

        return cfg

    getClusterConfiguration = classmethod(getClusterConfiguration)

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-l", "--list-configs", action="store_true",
                 dest="doList", help="List available configs")
    p.add_option("-c", "--check-config", action="store", type="string",
                 dest="toCheck", help="Check whether configuration is valid")
    p.set_defaults(doList  = False,
                   toCheck = None)
    opt, args = p.parse_args()

    configDir  = os.path.join(metaDir, "config")

    if(opt.doList):
        showList(configDir)
        raise SystemExit

    if(opt.toCheck):
        checkForValidConfig(configDir, opt.toCheck)
        raise SystemExit

    # Code for testing:
    if len(args) == 0:
        args.append("sim5str")

    for configName in args:
        print '-----------------------------------------------------------'
        print "Config %s" % configName
        dc = DAQConfig(configName, configDir)
        print "Number of DOMs in configuration: %s" % dc.ndoms

        kinds = dc.kinds()
        kinds.sort()
        for kind in kinds:
            print "Configuration includes %s" % kind

        comps = dc.components()
        comps.sort()
        for comp in comps:
            print "Configuration requires %s" % comp

        objs = dc.getComponentObjects()
        objs.sort()
        for comp in objs:
            print 'Comp %s log %s' % (str(comp), str(comp.logLevel()))
