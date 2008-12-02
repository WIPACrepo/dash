#!/usr/bin/env python

# DAQ Configuration reader/parser
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
#
# Class to parse XML configuration information for IceCube runs

import re
import optparse
from os import environ, listdir
from os.path import exists, join
from xml.dom import minidom
from exc_string import exc_string

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class DAQConfigNotFound          (Exception): pass
class DAQConfigDirNotFound       (Exception): pass
class noRunConfigFound           (Exception): pass
class noDOMConfigFound           (Exception):
    def __init__(self, configName):
        super(noDOMConfigFound, self).__init__()

        self.configName = configName

    def __str__(self):
        return self.configName

class noDeployedDOMsListFound    (Exception): pass
class noComponentsFound          (Exception): pass
class triggerException           (Exception): pass
class DOMNotInConfigException    (Exception): pass

def showList(configDir):
    if not exists(configDir):
        raise DAQConfigDirNotFound("Could not find config dir %s" % configDir)
    l = listdir(configDir)

    cfgs = []
    for f in l:
        match = re.search(r'^(.+?)\.xml$', f)
        if not match: continue
        cfgs.append(match.group(1))

    ok = []
    for cname in cfgs:
        if re.search(r'default-dom-geometry', cname): continue
        ok.append(cname)

    ok.sort()
    for cname in ok: print "%60s" % cname

def xmlOf(name):
    if not re.search(r'^(.+?)\.xml$', name): return name+".xml"
    return name

def configExists(configDir, configName):
    if not exists(configDir): return False
    configFile = xmlOf(join(configDir, configName))
    if not exists(configFile): return False
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
        deployedDOMsXML = xmlOf(join(configDir, self.DEPLOYEDDOMS))
        if not exists(deployedDOMsXML):
            raise noDeployedDOMsListFound("no deployed DOMs list found!")
        deployedDOMsParsed = minidom.parse(deployedDOMsXML)

        deployedStrings = deployedDOMsParsed.getElementsByTagName("string")
        if len(deployedStrings) < 1:
            raise noDeployedDOMsListFound("No string list in %s!" %
                                          DefaultDOMGeometry.DEPLOYEDDOMS)

        self.domDict  = {}

        for string in deployedStrings:
            stringNumTag = string.getElementsByTagName("number")
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
        return self.domDict[domID].string

    def getKind(self, domID):
        """
        Get the trigger kind associated with the DOM mainboard ID
        """
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

class DAQConfig(object):

    # Parse this only once, in case we cycle over multiple configs
    DeployedDOMs   = None
    persister      = {}

    def __init__(self, configName="default",
                 configDir="/usr/local/icecube/config"):
        # Optimize by looking up pre-parsed configurations:
        if DAQConfig.persister.has_key(configName):
            self.__dict__ = DAQConfig.persister[configName]
            return

        if not exists(configDir):
            raise DAQConfigDirNotFound("Could not find config dir %s" %
                                       configDir)
        self.configFile = xmlOf(join(configDir, configName))
        if not exists(self.configFile): raise DAQConfigNotFound(self.configFile)

        # Parse the runconfig
        parsed = minidom.parse(self.configFile)
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
                domConfigName = domConfig.childNodes[0].data
                # print "Parsing %s" % domConfigName

                domConfigXML = \
                    xmlOf(join(configDir, "domconfigs", domConfigName))
                if not exists(domConfigXML):
                    raise noDOMConfigFound("DOMConfig not found: %s" %
                                           domConfigName)

                domConfigParsed = minidom.parse(domConfigXML)
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

        self.compList = self.extractComponents(configs[0])

        for hubID in hubIDList:
            self.compList.append('%s#%d' % (hubType, hubID))

        DAQConfig.persister             [ configName ] = self.__dict__

    def checkTriggerConfigFile(self, config, configDir):
        triggerConfigs = config.getElementsByTagName("triggerConfig")
        if len(triggerConfigs) == 0: raise triggerException("no triggers found")
        for trig in triggerConfigs:
            trigName = trig.childNodes[0].data
            trigXML = xmlOf(join(configDir, "trigger", trigName))
            if not exists(trigXML):
                raise triggerException("trigger config file not found: %s" %
                                       trigXML)

    def extractComponents(self, config):
        comps = []
        compNodes = config.getElementsByTagName("runComponent")
        if len(compNodes) == 0: raise noComponentsFound("No components found")
        for node in compNodes:
            nodeName = node.attributes['name'].value
            if not node.attributes.has_key('id'):
                nodeId = 0
            else:
                nodeId = int(node.attributes['id'].value)

            comps.append('%s#%d' % (nodeName, nodeId))

        return comps

    def kinds(self):
        """
        Return list of detectors in configuration: any of
        amanda, in-ice, icetop
        """
        return self.kindList

    def components(self):
        """
        Return list of components in parsed configuration.
        """
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

if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-l", "--list-configs", action="store_true",
                 dest="doList", help="List available configs")
    p.add_option("-c", "--check-config", action="store", type="string",
                 dest="toCheck", help="Check whether configuration is valid")
    p.set_defaults(doList  = False,
                   toCheck = None)
    opt, args = p.parse_args()

    configDir  = join(metaDir, "config")

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
        print "Config %s" % configName
        dc = DAQConfig(configName, configDir)
        print "Number of DOMs in configuration: %s" % dc.nDOMs()
        for hubID in dc.hubIDs():
            print "String/hubID %d is in configuration." % hubID
        for kind in dc.kinds():
            print "Configuration includes %s" % kind
        for comp in dc.components():
            print "Configuration requires %s" % comp

