#!/usr/bin/env python

# DAQ Configuration reader/parser
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
#
# Class to parse XML configuration information for IceCube runs

import re
import sys
from os import environ
from os.path import exists
from xml.dom import minidom

class DAQConfigNotFound          (Exception): pass
class DAQConfigDirNotFound       (Exception): pass
class noRunConfigFound           (Exception): pass
class noDOMConfigFound           (Exception): pass
class noDeployedStringsListFound (Exception): pass
class noComponentsFound          (Exception): pass

class DAQConfig(object):

    DEPLOYEDDOMS   = "default-dom-geometry" # ".xml" implied, below.

    parsedNDOMDict       = {}
    parsedKindListDict   = {}
    parsedStringListDict = {}
    parsedCompListDict   = {}
    
    def __init__(self, configName="default", configDir="/usr/local/icecube/config"):
        # Optimize by looking up pre-parsed configurations:
        if DAQConfig.parsedNDOMDict.has_key(configName):
            self.ndoms      = DAQConfig.parsedNDOMDict      [ configName ]
            self.kindList   = DAQConfig.parsedKindListDict  [ configName ]
            self.stringList = DAQConfig.parsedStringListDict[ configName ]
            self.compList   = DAQConfig.parsedCompListDict  [ configName ]
            return
        
        if not exists(configDir):
            raise DAQConfigDirNotFound("Could not find config dir %s" % configDir)
        self.configFile = configDir + "/" + configName + ".xml"
        if not exists(self.configFile): raise DAQConfigNotFound()
        parsed = minidom.parse(self.configFile)
        configs = parsed.getElementsByTagName("runConfig")
        if len(configs) < 1: raise noRunConfigFound()

        deployedDOMsXML = configDir + "/" + DAQConfig.DEPLOYEDDOMS + ".xml"
        if not exists(deployedDOMsXML): raise noDeployedDOMsListFound()
        deployedDOMsParsed = minidom.parse(deployedDOMsXML)

        deployedStrings = deployedDOMsParsed.getElementsByTagName("string")
        if len(deployedStrings) < 1: raise noDeployedStringsListFound()

        nameDict = {}; stringDict = {}; positionDict = {}; kindDict = {}

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
            
                nameDict[domID]     = name
                stringDict[domID]   = stringNum
                positionDict[domID] = position
                kindDict[domID]     = kind

        configList = []
        noDOMs = configs[0].getElementsByTagName("noDOMConfig")
        if len(noDOMs) > 0:
            configList = []
        else:
            for domConfig in configs[0].getElementsByTagName("domConfigList"):
                
                domConfigName = domConfig.childNodes[0].data
                domConfigXML = configDir + "/" + domConfigName + ".xml"
                
                if not exists(domConfigXML): raise noDOMConfigFound()
                
                domConfigParsed = minidom.parse(domConfigXML)
                configList += domConfigParsed.getElementsByTagName("domConfig")

        self.ndoms = len(configList)
        # print "Found %d DOMs." % self.ndoms

        stringInConfigDict = {}
        kindInConfigDict   = {}
        for dom in configList:
            domID = dom.getAttribute("mbid")
            string = stringDict[domID]
            kind   = kindDict[domID]
            # print "Got DOM %s string %s kind %s" % (domID, string, kind)
            stringInConfigDict[string] = True
            kindInConfigDict[kind]     = True

        self.kindList   = kindInConfigDict.keys()
        self.stringList = stringInConfigDict.keys()

        self.compList = []
        compNodes = configs[0].getElementsByTagName("runComponent")
        if len(compNodes) == 0: raise noComponentsFound()
        for node in compNodes:
            if not node.attributes.has_key('id'):
                nodeId = 0
            else:
                nodeId = int(node.attributes['id'].value)

            self.compList.append(node.attributes['name'].value + '#' +
                                 str(nodeId))

        DAQConfig.parsedNDOMDict      [ configName ] = self.ndoms
        DAQConfig.parsedKindListDict  [ configName ] = self.kindList
        DAQConfig.parsedStringListDict[ configName ] = self.stringList
        DAQConfig.parsedCompListDict  [ configName ] = self.compList

    def nDOMs(self):
        "return number of DOMs in parsed configuration"
        return self.ndoms
    
    def kinds(self):
        """
        Return list of detectors in configuration: any of
        amanda, in-ice, icetop
        """
        return self.kindList
    
    def strings(self):
        """
        Return list of strings in parsed configuration.  String 0 refers to AMANDA.
        """
        return self.stringList
    
    def components(self):
        """
        Return list of components in parsed configuration.
        """
        return self.compList
    
if __name__ == "__main__":
    configDir  = "../config"
    configName = "example-runconfig"
    
    dc = DAQConfig(configName, configDir)
    print "Number of DOMs in configuration: %s" % dc.nDOMs()
    for string in dc.strings():
        print "String %d is in configuration." % string
    for kind in dc.kinds():
        print "Configuration includes %s" % kind
    for comp in dc.components():
        print "Configuration requires %s" % comp

    # Do it again to test optimization
    dc = DAQConfig(configName, configDir)
    print "Number of DOMs in configuration: %s" % dc.nDOMs()
    for string in dc.strings():
        print "String %d is in configuration." % string
    for kind in dc.kinds():
        print "Configuration includes %s" % kind
    for comp in dc.components():
        print "Configuration requires %s" % comp
