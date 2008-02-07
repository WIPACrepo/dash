#!/usr/bin/env python

# DAQ Configuration reader/parser
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
#
# Class to parse XML configuration information for IceCube runs

import re
import sys
import optparse
from os import environ, listdir
from os.path import exists, join
from xml.dom import minidom
from exc_string import *

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
        self.configName = configName

    def __str__(self):
        return self.configName
    
class noDeployedStringsListFound (Exception): pass
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
        dc = DAQConfig(configName, configDir)
        print "%s/%s is ok." % (configDir, configName)
        return True
    except Exception, e:
        print "%s/%s is not a valid config: %s [%s]" % (configDir, configName, e, exc_string())
        return False
        
class DAQConfig(object):
    
    DEPLOYEDDOMS            = "default-dom-geometry.xml"
    deployedDOMsParsed      = None  # Parse this only once, in case we cycle over multiple configs
    persister               = {}
    
    def __init__(self, configName="default", configDir="/usr/local/icecube/config"):
        # Optimize by looking up pre-parsed configurations:
        if DAQConfig.persister.has_key(configName):
            self.__dict__ = DAQConfig.persister[configName]
            return
                
        if not exists(configDir):
            raise DAQConfigDirNotFound("Could not find config dir %s" % configDir)
        self.configFile = xmlOf(join(configDir, configName))
        if not exists(self.configFile): raise DAQConfigNotFound(self.configFile)

        # Parse the runconfig
        parsed = minidom.parse(self.configFile)
        configs = parsed.getElementsByTagName("runConfig")
        if len(configs) < 1: raise noRunConfigFound("No runconfig field found!")

        # Parse the comprehensive lookup table "default-dom-geometry.xml"
        if DAQConfig.deployedDOMsParsed == None:
            deployedDOMsXML = xmlOf(join(configDir, DAQConfig.DEPLOYEDDOMS))
            if not exists(deployedDOMsXML): raise noDeployedDOMsListFound("no deployed DOMs list found!")
            DAQConfig.deployedDOMsParsed = minidom.parse(deployedDOMsXML)

        deployedStrings = DAQConfig.deployedDOMsParsed.getElementsByTagName("string")
        if len(deployedStrings) < 1: raise noDeployedStringsListFound("No string list in deployed DOMs XML!")

        self.nameOf   = {} # Save names from deployed DOMs list - these supercede names in domconfig files.
        self.stringOf = {}
        self.posOf    = {}
        positionDict  = {}
        kindDict      = {}
        compDict      = {}

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
                kind        = "in-ice"
                if(position > 60): kind = "icetop"
                if(re.search(r'AMANDA_', name)): kind = "amanda"
                # print "%20s %25s %2d %2d %s" % (domID, name, stringNum, position, kind)
            
                self.nameOf[domID]   = name
                self.stringOf[domID] = stringNum
                self.posOf[domID]    = position
                compDict[domID]      = DAQConfig.lookUpHubIDbyStringAndPosition(stringNum, position)
                kindDict[domID]      = kind

        configList = []
        noDOMs = configs[0].getElementsByTagName("noDOMConfig")
        if len(noDOMs) > 0:
            configList = []
        else:
            for domConfig in configs[0].getElementsByTagName("domConfigList"):
                
                domConfigName = domConfig.childNodes[0].data
                # print "Parsing %s" % domConfigName
                domConfigXML = xmlOf(join(configDir, "domconfigs", domConfigName))
                
                if not exists(domConfigXML): raise noDOMConfigFound("DOMConfig not found: %s" % domConfigName)
                
                domConfigParsed = minidom.parse(domConfigXML)
                configList += domConfigParsed.getElementsByTagName("domConfig")

        self.ndoms = len(configList)
        # print "Found %d DOMs." % self.ndoms

        hubIDInConfigDict = {}
        kindInConfigDict  = {}
        self.domlist      = []
        
        for dom in configList:
            domID  = dom.getAttribute("mbid")
            self.domlist.append(domID)
            hubID  = compDict[domID]
            kind   = kindDict[domID]
            # print "Got DOM %s hub %s kind %s" % (domID, hubID, kind)
            hubIDInConfigDict[hubID] = True
            kindInConfigDict[kind]   = True

        self.kindList   = kindInConfigDict.keys()
        self.hubIDList = hubIDInConfigDict.keys()

        triggerConfigs = configs[0].getElementsByTagName("triggerConfig")
        if len(triggerConfigs) == 0: raise triggerException("no triggers found")
        for trig in triggerConfigs:
            trigName = trig.childNodes[0].data
            trigXML = xmlOf(join(configDir, "trigger", trigName))
            if not exists(trigXML): raise triggerException("trigger config file not found: %s" % trigXML)
            
        self.compList = []
        compNodes = configs[0].getElementsByTagName("runComponent")
        if len(compNodes) == 0: raise noComponentsFound("No components found")
        for node in compNodes:
            if not node.attributes.has_key('id'):
                nodeId = 0
            else:
                nodeId = int(node.attributes['id'].value)

            self.compList.append(node.attributes['name'].value + '#' +
                                 str(nodeId))

        DAQConfig.persister             [ configName ] = self.__dict__

    def lookUpHubIDbyStringAndPosition(stringNum, position):
        # This is a somewhat kludgy approach but we let the L2 make the call and file
        # a mantis issue to clean this up later...
        # ithub01: 46, 55, 56, 65, 72, 73, 77, 78
        # ithub02: 38, 39, 48, 58, 64, 66, 71, 74
        # ithub03: 30, 40, 47, 49, 50, 57, 59, 67
        # ithub04: 21, 29
        if position <= 60: return stringNum
        if stringNum in [46, 55, 56, 65, 72, 73, 77, 78]: return 81
        if stringNum in [38, 39, 48, 58, 64, 66, 71, 74]: return 82
        if stringNum in [30, 40, 47, 49, 50, 57, 59, 67]: return 83
        if stringNum in [21, 29]: return 84
        if stringNum in [62, 54, 63, 45, 75, 76, 69, 70]: return 85
        if stringNum in [60, 68, 61, 44, 52, 53]: return 86

        if stringNum == 0: return 0
        return stringNum
    lookUpHubIDbyStringAndPosition = staticmethod(lookUpHubIDbyStringAndPosition)

    def nDOMs(self):
        "return number of DOMs in parsed configuration"
        return self.ndoms
    
    def kinds(self):
        """
        Return list of detectors in configuration: any of
        amanda, in-ice, icetop
        """
        return self.kindList
    
    def hubIDs(self):
        """
        Return list of strings in parsed configuration.  String 0 refers to AMANDA.
        """
        return self.hubIDList
    
    def components(self):
        """
        Return list of components in parsed configuration.
        """
        return self.compList

    def hasDOM(self, domid):
        "Indicate whether DOM mainboard id domid is in the current configuration"
        for d in self.domlist:
            if d == domid: return True
        return False
    
    def getIDbyName(self, name):
        """
        Get DOM mainboard ID for given DOM name (e.g., 'Alpaca').  Raise DOMNotInConfigException
        if DOM is missing
        """        
        for d in self.nameOf.keys():
            if self.nameOf[d] == name: return str(d) # Convert from unicode to ASCII
        raise DOMNotInConfigException()
    
    def getIDbyStringPos(self, string, pos):
        """
        Get DOM mainboard ID for a given string, position.  Raise DOMNotInConfigException
        if DOM is missing
        """
        for d in self.domlist:
            if self.stringOf.has_key(d)   and self.posOf.has_key(d) and \
               string == self.stringOf[d] and pos == self.posOf[d]:
                return str(d)
        raise DOMNotInConfigException()
        
if __name__ == "__main__":
    p = optparse.OptionParser()
    p.add_option("-l", "--list-configs", action="store_true", dest="doList",
                 help="List available configs")
    p.add_option("-c", "--check-config", action="store", type="string", dest="toCheck",
                 help="Check whether configuration is valid")
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
    configName = "sim5str"

    for i in range(4):
        print "Trial %d config %s" % (i, configName)
        dc = DAQConfig(configName, configDir)
        print "Number of DOMs in configuration: %s" % dc.nDOMs()
        for hubID in dc.hubIDs():
            print "String/hubID %d is in configuration." % hubID
        for kind in dc.kinds():
            print "Configuration includes %s" % kind
        for comp in dc.components():
            print "Configuration requires %s" % comp

