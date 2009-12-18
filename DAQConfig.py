#!/usr/bin/env python

# DAQ Configuration reader/parser
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started November, 2006
#
# Class to parse XML configuration information for IceCube runs

import copy, os, sys
from xml.dom import minidom, Node

from CachedConfigName import CachedConfigName
from ClusterConfig \
    import ClusterConfig, ConfigNotFoundException, ConfigNotSpecifiedException
from DefaultDomGeometry import BadFileError, DefaultDomGeometryReader, \
    ProcessError, XMLError, XMLParser
from RunCluster import RunCluster

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class DAQConfigException(Exception): pass
class BadComponentName(DAQConfigException): pass
class BadDAQConfig(DAQConfigException): pass
class BadDOMID(DAQConfigException): pass
class DOMNotInConfigException(DAQConfigException): pass
class DAQConfigNotFound(DAQConfigException): pass

class RunDom(object):
    """Minimal details for a single DOM"""
    def __init__(self, id, strNum, pos, name, domCfg):
        self.__id = id
        self.__string = strNum
        self.__pos = pos
        self.__name = name
        self.__domCfg = domCfg

    def __repr__(self):  return str(self)

    def __str__(self):
        return "%012x" % self.__id

    def domConfig(self): return self.__domCfg
    def id(self): return self.__id
    def name(self): return self.__name
    def pos(self): return self.__pos
    def string(self): return self.__string

class DomConfig(object):
    """Minimal details for a DOM configuration file"""
    def __init__(self, fileName):
        self.__fileName = fileName
        self.__domList = []
        self.__stringMap = {}
        self.__commentOut = False

    def __str__(self):
        dlStr = "["
        for d in self.__domList:
            if len(dlStr) > 1:
                dlStr += ", "
            dlStr += str(d)
        dlStr += "]"

        keys = self.__stringMap.keys()
        keys.sort()

        sStr = "["
        for s in keys:
            if len(sStr) > 1:
                sStr += ", "
            sStr += str(s)
        sStr += "]"

        return "%s: %s %s" % (self.__fileName, dlStr, sStr)

    def addDom(self, dom):
        """Add a DOM"""
        self.__domList.append(dom)
        if not self.__stringMap.has_key(dom.string()):
            self.__stringMap[dom.string()] = []
        self.__stringMap[dom.string()].append(dom)

    def commentOut(self):
        """This domconfig file should be commented-out"""
        self.__commentOut = True

    def filename(self): return self.__fileName

    def getStringList(self):
        """Get the list of strings whose DOMs are referenced in this file"""
        return self.__stringMap.keys()

    def getDOMByID(self, domid):
        for d in self.__domList:
            if d.id() == domid:
                return d
        return None

    def getDOMByName(self, name):
        for d in self.__domList:
            if d.name() == name:
                return d
        return None

    def getDOMByStringPos(self, string, pos):
        for d in self.__domList:
            if d.string() == string and d.pos() == pos:
                return d
        return None

    def isCommentedOut(self):
        """Is domconfig file commented-out?"""
        return self.__commentOut

    def xml(self, indent):
        """Return the XML string for this DOM configuration file"""
        includeStringNumber = False

        if self.__commentOut:
            prefix = "<!--"
            suffix = " -->"
        else:
            prefix = ""
            suffix = ""
        strList = self.__stringMap.keys()
        if not includeStringNumber or len(strList) != 1:
            nStr = ""
        else:
            nStr = " n=\"%d\"" % strList[0]
        return "%s%s<domConfigList%s>%s</domConfigList>%s" % \
            (prefix, indent, nStr, self.__fileName, suffix)

class Component(object):
    def __init__(self, name, id):
        self.__name = name
        self.__id = id
        self.__logLevel = None

    def __cmp__(self, other):
        val = cmp(self.__name, other.__name)
        if val == 0:
            val = cmp(self.__id, other.__id)
        return val

    def __str__(self):
        return self.fullname()

    def __repr__(self): return self.__str__()

    def id(self): return self.__id

    def fullname(self):
        if self.__id == 0 and not self.isHub():
            return self.__name
        return '%s#%d' % (self.__name, self.__id)

    def isHub(self):
        return self.__name.lower().find('hub') >= 0

    def isRealHub(self):
        return self.__name.lower() == 'stringhub' and self.__id < 1000

    def logLevel(self): return self.__logLevel
    def name(self): return self.__name

    def setLogLevel(self, lvl):
        self.__logLevel = lvl

class StringHub(Component):
    def __init__(self, id):
        self.__domConfigs = []

        super(StringHub, self).__init__("stringHub", id)

    def addDomConfig(self, domCfg):
        self.__domConfigs.append(domCfg)

    def getDomConfigs(self):
        return self.__domConfigs[:]

class ReplayHub(Component):
    def __init__(self, id, hitFile):
        self.__hitFile = hitFile

        super(ReplayHub, self).__init__("replayHub", id)

class DAQConfig(object):

    CACHE = {}

    """Run configuration data"""
    def __init__(self, fileName):
        self.__fileName = fileName

        self.__comps = []
        self.__trigCfg = None
        self.__domCfgList = []
        self.__stringHubs = {}
        self.__hasReplayHubs = False

        self.__modTime = None

    def __str__(self):
        return "%s[C*%d]" % (self.__fileName, len(self.__comps))

    def addComponent(self, compName):
        """Add a component name"""
        if compName.find("#") > 0:
            raise BadComponentName("Found \"#\" in component name \"%s\"" %
                                   compName)
        self.__comps.append(Component(compName, 0))

    def addDomConfig(self, domCfg):
        """Add a DomConfig object"""
        self.__domCfgList.append(domCfg)

        for s in domCfg.getStringList():
            if not self.__stringHubs.has_key(s):
                hub = StringHub(s)
                self.__stringHubs[s] = hub
                self.__comps.append(hub)
            self.__stringHubs[s].addDomConfig(domCfg)

    def addReplayHub(self, id, hitFile):
        self.__comps.append(ReplayHub(id, hitFile))

    def components(self):
        objs = self.__comps[:]
        objs.sort()
        return objs

    def configExists(cls, configName,
                     configDir=os.path.join(metaDir, "config")):
        if not os.path.exists(configDir): return False
        fileName = os.path.join(configDir, configName)
        if not fileName.endswith(".xml"): fileName += ".xml"
        if not os.path.exists(fileName): return False
        return True
    configExists = classmethod(configExists)

    def configFile(self): return self.__fileName

    def createOmitFileName(cls, configDir, fileName, hubIdList):
        """
        Create a new file name from the original name
        and the list of omitted hubs
        """
        baseName = os.path.basename(fileName)
        if baseName.endswith(".xml"):
            baseName = baseName[:-4]

        noStr = ""
        for h in hubIdList:
            noStr += "-no" + cls.getHubName(h)

        return os.path.join(configDir, baseName + noStr + ".xml")
    createOmitFileName = classmethod(createOmitFileName)

    def filename(self): return self.__fileName

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
            runCfg = DAQConfig.load(configName, configDir)
            cfg = RunCluster(runCfg, clusterDesc, configDir)
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

    def getHubName(cls, num):
        """Get the standard representation for a hub number"""
        baseNum = num % 1000
        if baseNum > 0 and baseNum < 100:
            return "%02d" % baseNum
        if baseNum > 200 and baseNum < 220:
            return "%02dt" % (baseNum - 200)
        return "?%d?" % baseNum
    getHubName = classmethod(getHubName)

    def getIDbyName(self, name):
        for dc in self.__domCfgList:
            dom = dc.getDOMByName(name)
            if dom is not None:
                return "%12x" % dom.id()

        raise DOMNotInConfigException("Cannot find DOM named \"%s\"" % name)

    def getIDbyStringPos(self, string, pos):
        for dc in self.__domCfgList:
            dom = dc.getDOMByStringPos(string, pos)
            if dom is not None:
                return "%12x" % dom.id()

        raise DOMNotInConfigException("Cannot find DOM named \"%s\"" % name)

    def hasDOM(self, domid):
        if type(domid) != int and type(domid) != long:
            try:
                val = long(domid, 16)
                domid = val
            except ValueError:
                raise BadDOMID("Invalid DOM ID \"%s\"" % domid)

        for dc in self.__domCfgList:
            dom = dc.getDOMByID(domid)
            if dom is not None:
                return True

        return False

    def hasHubs(self):
        """Does this run configuration include any DOMs or replayHubs?"""
        for c in self.__comps:
            if c.isHub():
                return True
        return False

    def hasTriggerConfig(self):
        """Does this run configuration have a trigger configuration file?"""
        return self.__trigCfg is not None

    def isModTime(self, modTime):
        return self.__modTime == modTime

    def load(cls, cfgName, configDir=os.path.join(metaDir, "config")):
        "Load the run configuration"

        fileName = os.path.join(configDir, cfgName)
        if not fileName.endswith(".xml"):
            fileName += ".xml"
        if not os.path.exists(fileName):
            raise DAQConfigNotFound(cfgName)

        try:
            cfgStat = os.stat(fileName)
        except OSError:
            raise DAQConfigNotFound(fileName)

        # Optimize by looking up pre-parsed configurations:
        if DAQConfig.CACHE.has_key(fileName):
            if DAQConfig.CACHE[fileName].isModTime(cfgStat.st_mtime):
                return DAQConfig.CACHE[fileName]

        parsed = False
        try:
            dom = minidom.parse(fileName)
            parsed = True
        except Exception, e:
            raise BadDAQConfig("Couldn't parse \"%s\": %s" % (fileName, str(e)))
        except KeyboardInterrupt:
            raise BadDAQConfig("Couldn't parse \"%s\": KeyboardInterrupt" %
                               fileName)

        if parsed:
            try:
                rc = DAQConfigParser.parse(dom, configDir, fileName)
            except XMLError, xe:
                raise BadDAQConfig("%s: %s" % (fileName, str(xe)))
            except KeyboardInterrupt:
                raise BadDAQConfig("Couldn't parse \"%s\": KeyboardInterrupt" %
                                   fileName)

            rc.setModTime(cfgStat.st_mtime)
            DAQConfig.CACHE[fileName] = rc
            return rc

        return None
    load = classmethod(load)

    def omit(self, hubIdList):
        """Create a new run configuration which omits the specified hubs"""
        omitMap = {}

        error = False
        for h in hubIdList:
            if not self.__stringHubs.has_key(h):
                print >>sys.stderr, "Hub %s not found in %s" % \
                    (self.getHubName(h), self.__fileName)
                error = True
            else:
                domCfgs = self.__stringHubs[h].getDomConfigs()
                if len(domCfgs) == 1:
                    omitMap[domCfgs[0]] = h
                else:
                    dfStr = None
                    for dc in domCfgs:
                        if dfStr is None:
                            dfStr = dc.filename()
                        else:
                            dfStr += ", " + dc.filename()
                    print >>sys.stderr, ("Hub %s is specified in multiple" +
                                         " domConfig files: %s") % \
                                         (self.getHubName(h), dfStr)
                    error = True

        if error:
            return None

        dir = os.path.dirname(self.__fileName)
        base = os.path.basename(self.__fileName)
        newCfg = DAQConfig(self.createOmitFileName(dir, base, hubIdList))
        for c in self.__comps:
            if not c.isHub():
                newCfg.addComponent(c.name())
        newCfg.setTriggerConfig(self.__trigCfg)
        for dc in self.__domCfgList:
            if not omitMap.has_key(dc):
                newCfg.addDomConfig(dc)
            else:
                dup = copy.copy(dc)
                dup.commentOut()
                newCfg.addDomConfig(dup)

        return newCfg

    def setModTime(self, modTime):
        self.__modTime = modTime

    def setTriggerConfig(self, name):
        """Set the trigger configuration file for this run configuration"""
        self.__trigCfg = name

    def write(self, fd):
        """Write this run configuration to the specified file descriptor"""
        indent = "    "
        print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        print >>fd, "<runConfig>"
        for d in self.__domCfgList:
            print >>fd, d.xml(indent)
        print >>fd, "%s<triggerConfig>%s</triggerConfig>" % \
            (indent, self.__trigCfg)
        for c in self.__comps:
            if not c.isHub():
                print >>fd, "%s<runComponent name=\"%s\"/>" % (indent, c.name())
        print >>fd, "</runConfig>"

class DAQConfigParser(XMLParser):
    """Run configuration file parser"""

    DEFAULT_DOM_GEOMETRY = None

    def __init__(self):
        """Use this object's class methods directly"""
        raise Exception("Cannot create this object")

    def __parseDomConfig(cls, configDir, baseName):
        """Parse a DOM configuration file and return a DomConfig object"""
        if DAQConfigParser.DEFAULT_DOM_GEOMETRY is None:
            try:
                DAQConfigParser.DEFAULT_DOM_GEOMETRY = \
                    DefaultDomGeometryReader.parse(translateDoms=True)
            except AttributeError:
                DAQConfigParser.DEFAULT_DOM_GEOMETRY = \
                    DupDefaultDomGeometryReader.parse(translateDoms=True)

        domIdToDom = DAQConfigParser.DEFAULT_DOM_GEOMETRY.getDomIdToDomDict()

        fileName = os.path.join(configDir, "domconfigs", baseName)
        if not fileName.endswith(".xml"):
            fileName += ".xml"

        if not os.path.exists(fileName):
            raise BadFileError("Cannot read dom config file \"%s\"" % fileName)

        try:
            dom = minidom.parse(fileName)
        except Exception, e:
            raise ProcessError("Couldn't parse \"%s\": %s" % (fileName, str(e)))

        dcListList = dom.getElementsByTagName("domConfigList")
        if dcListList is None or len(dcListList) == 0:
            raise ProcessError("No <domConfigList> tag found in %s" % fileName)
        dcList = dcListList[0]

        if dcList.attributes is None or \
                not dcList.attributes.has_key("configId"):
            cfgId = None
        else:
            cfgId = dcList.attributes["configId"].value

        domCfg = DomConfig(baseName)

        domNum = 0
        for kid in dcList.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "domConfig":
                    if kid.attributes is None or len(kid.attributes) == 0:
                        raise ProcessError("<%s> node has no attributes" %
                                           kid.nodeName)
                    if not kid.attributes.has_key("mbid"):
                        raise ProcessError(("<%s> node should have \"mbid\"" +
                                            " attribute") % kid.nodeName)

                    domId = kid.attributes["mbid"].value
                    if not domIdToDom.has_key(domId):
                        raise ProcessError("Unknown DOM #%d ID %s" %
                                           (domNum, domId))

                    domGeom = domIdToDom[domId]

                    name = kid.attributes["name"].value

                    dom = RunDom(long(domId, 16), domGeom.string(),
                                 domGeom.pos(), domGeom.name(), domCfg)
                    domCfg.addDom(dom)

                    domNum += 1
                else:
                    raise ProcessError("Unexpected %s child <%s>" %
                                       (dcList.nodeName, kid.nodeName))
                continue

            raise ProcessError("Found unknown %s node <%s>" %
                               (dcList.nodeName, kid.nodeName))

        return domCfg
    __parseDomConfig = classmethod(__parseDomConfig)

    def __parseHubFiles(cls, topNode, runCfg):
        hubNodeNum = 0
        for kid in topNode.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "hub":
                    hubNodeNum += 1
                    if not kid.attributes.has_key("id") or \
                            not kid.attributes.has_key("hitFile"):
                        raise ProcessError(("<%s> node #%d does not have" +
                                            "  \"id\" and/or \"hitFile\"" +
                                            " attributes") %
                                           (kid.nodeName, hubNodeNum))

                    idStr = kid.attributes["id"].value
                    try:
                        id = int(idStr)
                    except:
                        raise ProcessError(("Bad \"id\" attribute \"%s\"" +
                                            " for <%s> #%d") %
                                           (idStr, kid.nodeName, hubNodeNum))
                    runCfg.addReplayHub(id,  kid.attributes["hitFile"].value)
                else:
                    raise ProcessError("Unexpected %s child <%s>" %
                                       (topNode.nodeName, kid.nodeName))
    __parseHubFiles = classmethod(__parseHubFiles)

    def __parseTriggerConfig(cls, configDir, baseName):
        """Parse a trigger configuration file and return nothing"""
        fileName = os.path.join(configDir, "trigger", baseName)
        if not fileName.endswith(".xml"):
            fileName += ".xml"

        if not os.path.exists(fileName):
            raise BadFileError("Cannot read trigger config file \"%s\"" %
                               fileName)
    __parseTriggerConfig = classmethod(__parseTriggerConfig)

    def parse(cls, dom, configDir, fileName):
        """Parse a run configuration file and return a DAQConfig object"""
        rcList = dom.getElementsByTagName("runConfig")
        if rcList is None or len(rcList) == 0:
            raise ProcessError("No <runConfig> tag found in %s" % fileName)

        runCfg = DAQConfig(fileName)

        hubFiles = None
        for kid in rcList[0].childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "domConfigList":
                    domCfg = cls.__parseDomConfig(configDir,
                                                  cls.getChildText(kid))
                    runCfg.addDomConfig(domCfg)
                elif kid.nodeName == "triggerConfig":
                    trigCfg = cls.getChildText(kid)
                    cls.__parseTriggerConfig(configDir, trigCfg)
                    runCfg.setTriggerConfig(trigCfg)
                elif kid.nodeName == "hubFiles":
                    cls.__parseHubFiles(kid, runCfg)
                elif kid.nodeName == "stringHub":
                    print >>sys.stderr, "Ignoring <stringHub> in \"%s\"" % \
                        fileName
                elif kid.nodeName == "runComponent":
                    if kid.attributes is None or len(kid.attributes) == 0:
                        raise ProcessError("<%s> node has no attributes" %
                                           kid.nodeName)
                    if len(kid.attributes) != 1:
                        raise ProcessError("<%s> node has extra attributes" %
                                           kid.nodeName)
                    if not kid.attributes.has_key("name"):
                        raise ProcessError(("<%s> node should have \"name\"" +
                                            " attribute, not \"%s\"") %
                                           (kid.nodeName,
                                            kid.attributes.keys()[0]))

                    runCfg.addComponent(kid.attributes["name"].value)

                elif kid.nodeName == "defaultLogLevel":
                    pass
                else:
                    raise ProcessError("Unknown runConfig node <%s>" %
                                       kid.nodeName)
                continue

            raise ProcessError("Found unknown runConfig node <%s>" %
                               kid.nodeName)

        if not runCfg.hasHubs():
            raise ProcessError("No doms or replayHubs found")
        if not runCfg.hasTriggerConfig():
            raise ProcessError("No <triggerConfig> found")

        return runCfg
    parse = classmethod(parse)

if __name__ == "__main__":
    import optparse

    p = optparse.OptionParser()
    p.add_option("-l", "--list-configs", action="store_true",
                 dest="doList", help="List available configs")
    p.add_option("-c", "--check-config", action="store", type="string",
                 dest="toCheck", help="Check whether configuration is valid")
    p.set_defaults(doList  = False,
                   toCheck = None)
    opt, args = p.parse_args()

    configDir  = os.path.join(metaDir, "config")

    if opt.doList:
        if not os.path.exists(configDir):
            raise DAQConfigDirNotFound("Could not find config dir %s" %
                                       configDir)
        l = os.listdir(configDir)

        import re

        cfgs = []
        for f in l:
            match = re.search(r'^(.+?)\.xml$', f)
            if not match: continue
            cfg = match.group(1)
            if cfg == 'default-dom-geometry': continue
            cfgs.append(cfg)

        cfgs.sort()
        for cname in cfgs:
            print "%-60s" % cname

        raise SystemExit

    if opt.toCheck:
        try:
            DAQConfig.load(opt.toCheck, configDir)
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
        dc = DAQConfig.load(configName, configDir)

        comps = dc.components()
        comps.sort()
        for comp in comps:
            print 'Comp %s log %s' % (str(comp), str(comp.logLevel()))
