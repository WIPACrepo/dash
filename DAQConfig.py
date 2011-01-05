#!/usr/bin/env python

import copy, os, sys

from xml.dom import Node

from CachedConfigName import CachedConfigName
from ClusterConfig import ClusterConfigParser, ConfigNotFoundException
from Component import Component
from DefaultDomGeometry import BadFileError, DefaultDomGeometryReader, \
    ProcessError, XMLParser
from RunCluster import RunCluster
from XMLFileCache import XMLFileCache, XMLFileNotFound

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class DAQConfigException(Exception): pass
class BadComponentName(DAQConfigException): pass
class BadDOMID(DAQConfigException): pass
class ConfigNotSpecifiedException(DAQConfigException): pass
class DOMNotInConfigException(DAQConfigException): pass

class KeyValuePairs(object):
    "Container for a list of key/value pairs extracted from an XML file"

    def __init__(self, tag):
        self.__tag = tag
        self.__attr = {}
        self.__attrOrder = []

    def __cmp__(self, other):
        val = cmp(self.__tag, other.__tag)
        if val == 0:
            val = len(self.__attr) - len(other.__attr)
            if val == 0:
                for k in self.__attr.keys():
                    if not other.__attr.has_key(k):
                        val = 1
                        break
                    val = cmp(self.__attr[k], other.__attr[k])
                    if val != 0:
                        break
        return val

    def addAttribute(self, key, val):
        if self.__attr.has_key(key):
            if self.__attr[key] != val:
                print >>sys.stderr, \
                      "Changing <%s> \"%s\" value from \"%s\" to \"%s\"" % \
                      (self.__tag, key, self.__attr[key], val)
        else:
            self.__attrOrder.append(key)
        self.__attr[key] = val.strip()

    def tag(self): return self.__tag

    def write(self, fd, indent, indentLevel):
        in1 = ""
        for i in range(indentLevel):
            in1 += indent

        print >>fd, "%s<%s>" % (in1, self.__tag)
        self.writeAttrs(fd, indent, indentLevel + 1)
        print >>fd, "%s</%s>" % (in1, self.__tag)

    def writeAttrs(self, fd, indent, indentLevel):
        in1 = ""
        for i in range(indentLevel):
            in1 += indent

        for key in self.__attrOrder:
            print >>fd, "%s<%s> %s </%s>" % (in1, key, self.__attr[key], key)

class LocalCoincidence(KeyValuePairs):
    "DOM local coincidence data"

    def __init__(self):
        self.__cableLen = []

        super(LocalCoincidence, self).__init__("localCoincidence")

    def __cmp__(self, other):
        val = super(LocalCoincidence, self).__cmp__(other)

        if val == 0:
            val = len(self.__cableLen) - len(other.__cableLen)
            if val == 0:
                for i in range(len(self.__cableLen)):
                    val = cmp(self.__cableLen[i], other.__cableLen[i])
                    if val != 0:
                        break

        return val

    def addCableLength(self, dirUp, dist, cableLen):
        self.__cableLen.append((dirUp, dist, cableLen))

    def write(self, fd, indent, indentLevel):
        in1 = ""
        for i in range(indentLevel):
            in1 += indent

        in2 = in1 + indent

        print >>fd, "%s<%s>" % (in1, self.tag())

        self.writeAttrs(fd, indent, indentLevel + 1)

        for cl in self.__cableLen:
            (dirUp, dist, cableLen) = cl
            if dirUp:
                dirStr = "up"
            else:
                dirStr = "down"

            print >>fd, ("%s<cableLength dir=\"%s\" dist=\"%d\"> %d" +
                         " </cableLength>") % (in2, dirStr, dist, cableLen)

        print >>fd, "%s</%s>" % (in1, self.tag())

class RunDom(object):
    """Minimal details for a single DOM"""

    ATTR_CHGHIST = "chargeHistogram"
    ATTR_CHGSTAMP = "chargeStamp"
    ATTR_FORMAT = "format"
    ATTR_ICETOP_MB = "enableIceTopMinBias"
    ATTR_LCL_COIN = "localCoincidence"
    ATTR_SIM = "simulation"
    ATTR_SN_MODE = "supernovaMode"

    FMT_DELTA = 2
    FMT_ENG = 1

    def __init__(self, id, strNum, pos, name, domCfg):
        self.__id = id
        self.__string = strNum
        self.__pos = pos
        self.__name = name
        self.__domCfg = domCfg

        self.__attr = {}
        self.__attrOrder = []

        self.__format = None
        self.__icetopMinBias = False
        self.__chargeStamp = None
        self.__localCoincidence = None
        self.__chargeHist = None
        self.__supernovaMode = None
        self.__simulation = None

    def __cmp__(self, other):
        val = self.__id - other.__id

        if val == 0:
            val = self.__compareValues(self.__format, other.__format)

        if val == 0:
            val = len(self.__attr) - len(other.__attr)
            if val == 0:
                for k in self.__attr.keys():
                    if not other.__attr.has_key(k):
                        val = 1
                        break
                    val = cmp(self.__attr[k], other.__attr[k])
                    if val != 0:
                        break

        if val == 0:
            val = cmp(self.__icetopMinBias, other.__icetopMinBias)

        if val == 0:
            val = self.__compareValues(self.__chargeStamp, other.__chargeStamp)

        if val == 0:
            val = self.__compareValues(self.__localCoincidence,
                                       other.__localCoincidence)

        if val == 0:
            val = self.__compareValues(self.__chargeHist, other.__chargeHist)

        if val == 0:
            val = self.__compareValues(self.__supernovaMode,
                                       other.__supernovaMode)

        if val == 0:
            val = self.__compareValues(self.__simulation,
                                       other.__simulation)

        return val

    def __repr__(self):  return str(self)

    def __str__(self):
        return "%012x" % self.__id

    def __compareValues(self, aVal, bVal):
        if aVal is None:
            if bVal is None:
                return 0
            return 1

        if bVal is None:
            return -1

        return cmp(aVal, bVal)

    def addAttribute(self, key, val):
        if self.__attr.has_key(key):
            if self.__attr[key] != val:
                print >>sys.stderr, "Changing %s <%s> value from %s to %s" % \
                      (self, key, self.__attr[key], val)
        else:
            self.__attrOrder.append(key)
        self.__attr[key] = val.strip()

    def domConfig(self): return self.__domCfg

    def enableIcetopMinBias(self):
        self.__icetopMinBias = True
        self.__attrOrder.append(self.ATTR_ICETOP_MB)

    def id(self): return self.__id
    def name(self): return self.__name
    def pos(self): return self.__pos

    def setChargeHistogram(self, chgHist):
        self.__chargeHist = chgHist
        self.__attrOrder.append(self.ATTR_CHGHIST)

    def setChargeStamp(self, csType):
        self.__chargeStamp = csType
        self.__attrOrder.append(self.ATTR_CHGSTAMP)

    def setDeltaCompressed(self):
        self.__format = self.FMT_DELTA
        self.__attrOrder.append(self.ATTR_FORMAT)

    def setEngineeringFormat(self):
        self.__format = self.FMT_ENG
        self.__attrOrder.append(self.ATTR_FORMAT)

    def setLocalCoincidence(self, lc):
        self.__localCoincidence = lc
        self.__attrOrder.append(self.ATTR_LCL_COIN)

    def setSimulation(self, sim):
        self.__simulation = sim
        self.__attrOrder.append(self.ATTR_SIM)

    def setSupernovaMode(self, mode):
        self.__supernovaMode = mode
        self.__attrOrder.append(self.ATTR_SN_MODE)

    def string(self): return self.__string

    def write(self, fd, indent, indentLevel):
        in1 = ""
        for i in range(indentLevel):
            in1 += indent

        in2 = in1 + indent
        in3 = in2 + indent

        print >>fd, "%s<domConfig mbid=\"%012x\" name=\"%s\">" % \
              (in1, self.__id, self.__name)
        for key in self.__attrOrder:
            if self.__attr.has_key(key):
                print >>fd, "%s<%s> %s </%s>" % \
                      (in2, key, self.__attr[key], key)
            elif key == self.ATTR_CHGSTAMP:
                if len(self.__chargeStamp) == 1:
                    chanStr = ""
                else:
                    chanStr = " channel=\"%s\"" % self.__chargeStamp[1]
                print >>fd, "%s<%s type=\"%s\"%s/>" % \
                      (in2, key, self.__chargeStamp[0], chanStr)
            elif key == self.ATTR_CHGHIST:
                print >>fd, "%s<%s>" % (in2, key)
                print >>fd, "%s<interval>%d</interval>>" % \
                      (in3, self.__chargeHist[0])
                print >>fd, "%s<prescale>%d</prescale>>" % \
                      (in3, self.__chargeHist[1])
                print >>fd, "%s</%s>" % (in2, key)
            elif key == self.ATTR_FORMAT:
                if self.__format == self.FMT_DELTA:
                    fmtStr = "deltaCompressed"
                elif self.__format == self.FMT_ENG:
                    fmtStr = "engineeringFormat"
                else:
                    raise ProcessError("Unknown format value %s" %
                                       self.__format)
                print >>fd, "%s<%s>" % (in2, key)
                print >>fd, "%s<%s/>" % (in3, fmtStr)
                print >>fd, "%s</%s>" % (in2, key)
            elif key == self.ATTR_ICETOP_MB:
                print >>fd, "%s<%s/>" % (in2, key)
            elif key == self.ATTR_LCL_COIN:
                self.__localCoincidence.write(fd, indent, indentLevel + 1)
            elif key == self.ATTR_SIM:
                self.__simulation.write(fd, indent, indentLevel + 2)
            elif key == self.ATTR_SN_MODE:
                (enabled, deadtime, disc) = self.__supernovaMode
                if enabled:
                    enStr = "true"
                else:
                    enStr = "false"
                print >>fd, "%s<%s enabled=\"%s\">" % (in2, key, enStr)
                print >>fd, "%s<deadtime> %s </deadtime>" % (in3, deadtime)
                print >>fd, "%s<disc> %s </disc>" % (in3, disc)
                print >>fd, "%s</%s>" % (in2, key)

        print >>fd, "%s</domConfig>" % in1

class DomConfigParser(XMLParser, XMLFileCache):
    "Parse DOM configuration file"

    DEFAULT_DOM_GEOMETRY = None
    DOM_ID_TO_DOM = None

    PARSE_DOM_DATA = False

    def __init__(self):
        """Use this object's class methods directly"""
        raise Exception("Cannot create this object")

    def __loadDomIdMap(cls):
        if cls.DEFAULT_DOM_GEOMETRY is None:
            cls.DEFAULT_DOM_GEOMETRY = \
                DefaultDomGeometryReader.parse(translateDoms=True)

        return cls.DEFAULT_DOM_GEOMETRY.getDomIdToDomDict()
    __loadDomIdMap = classmethod(__loadDomIdMap)

    def __parseChargeHistogram(cls, dom, node):
        interval = None
        prescale = None

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "interval":
                    interval = int(cls.getChildText(kid))
                elif kid.nodeName == "prescale":
                    prescale = int(cls.getChildText(kid))
                else:
                    raise ProcessError(("Unknown %s <%s> child <%s>") %
                                       (dom, node.nodeName, kid.nodeName))

        if interval is None or prescale is None:
            raise ProcessError(("%s <%s> should specify both interval" +
                                " and prescale") % (dom, kid.nodeName))

        return (interval, prescale)
    __parseChargeHistogram = classmethod(__parseChargeHistogram)

    def __parseChargeStamp(self, dom, node):
        if node.attributes is None or \
               len(node.attributes) == 0:
            raise ProcessError("%s <%s> node has no attributes" %
                               (dom, node.nodeName))
        if len(node.attributes) > 2:
            raise ProcessError("%s <%s> node has extra attributes" %
                               (dom, node.nodeName))
        if not node.attributes.has_key("type"):
            raise ProcessError(("%s <%s> node should have"
                                " \"type\" attribute") %
                               (dom, node.nodeName))

        if not node.attributes.has_key("channel"):
            return (node.attributes["type"].value, )

        return (node.attributes["type"].value,
                node.attributes["channel"].value)
    __parseChargeStamp = classmethod(__parseChargeStamp)

    def __parseDomData(cls, dom, node):
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "format":
                    cls.__setDomFormat(dom, kid)
                    continue

                if kid.nodeName == "chargeHistogram":
                    chgHist = cls.__parseChargeHistogram(dom, kid)
                    dom.setChargeHistogram(chgHist)
                    continue

                if kid.nodeName == "chargeStamp":
                    chgStamp = cls.__parseChargeStamp(dom, kid)
                    dom.setChargeStamp(chgStamp)
                    continue

                if kid.nodeName == "localCoincidence":
                    lc = cls.__parseLocalCoincidence(dom, kid)
                    dom.setLocalCoincidence(lc)
                    continue

                if kid.nodeName == "enableIceTopMinBias":
                    dom.enableIcetopMinBias()
                    continue

                if kid.nodeName == "supernovaMode":
                    mode = cls.__parseSupernovaMode(dom, kid)
                    dom.setSupernovaMode(mode)
                    continue

                if kid.nodeName == "simulation":
                    sim = cls.__parseSimulation(dom, kid)
                    dom.setSimulation(sim)
                    continue

                if kid.attributes is not None and \
                       len(kid.attributes) > 0:
                    raise ProcessError("%s <%s> node has attributes" %
                                       (dom, kid.nodeName))
                dom.addAttribute(kid.nodeName, cls.getChildText(kid))
    __parseDomData = classmethod(__parseDomData)

    def __parseLocalCoincidence(cls, dom, node):
        lc = LocalCoincidence()

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "cableLength":
                    if kid.attributes is None or \
                           len(kid.attributes) == 0:
                        raise ProcessError("%s %s <%s> node has attributes" %
                                           (dom, node.nodeName, kid.nodeName))
                    if not kid.attributes.has_key("dir"):
                        raise ProcessError(("%s %s <%s> node is missing" +
                                            " \"dir\" attribute") %
                                           (dom, node.nodeName, kid.nodeName))
                    elif not kid.attributes.has_key("dist"):
                        raise ProcessError(("%s %s <%s> node is missing" +
                                            " \"dist\" attribute") %
                                           (dom, node.nodeName, kid.nodeName))

                    dirStr = kid.attributes["dir"].value.lower()
                    if dirStr == "up":
                        dirUp = True
                    elif dirStr == "down":
                        dirUp = False
                    else:
                        raise ProcessError(("Bad value \"%s\" for %s %s" +
                                            " <%s> \"dir\" attribute") %
                                           (kid.attributes["dir"].value, dom,
                                            node.nodeName, kid.nodeName))

                    dist = int(str(kid.attributes["dist"].value))
                    cableLen = int(cls.getChildText(kid))

                    lc.addCableLength(dirUp, dist, cableLen)
                    continue

                if kid.attributes is not None and \
                       len(kid.attributes) > 0:
                    raise ProcessError("%s %s <%s> node has attributes" %
                                       (dom, node.nodeName, kid.nodeName))
                lc.addAttribute(kid.nodeName, cls.getChildText(kid))

        return lc
    __parseLocalCoincidence = classmethod(__parseLocalCoincidence)

    def __parseSimulation(cls, dom, node):
        sim = KeyValuePairs("simulation")

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.attributes is not None and \
                       len(kid.attributes) > 0:
                    raise ProcessError("%s <%s> node has attributes" %
                                       (dom, kid.nodeName))
                sim.addAttribute(kid.nodeName, cls.getChildText(kid))

        return sim
    __parseSimulation = classmethod(__parseSimulation)

    def __parseSupernovaMode(cls, dom, node):
        if node.attributes is None or \
               len(node.attributes) == 0:
            raise ProcessError("%s <%s> node has no attributes" %
                               (dom, node.nodeName))
        attrName = "enabled"
        if not node.attributes.has_key(attrName):
            raise ProcessError("%s <%s> node should have \"%s\" attribute" %
                               (dom, node.nodeName, attrName))

        eStr = node.attributes[attrName].value.lower()
        if eStr == "true":
            enabled = True
        elif eStr == "false":
            enabled = False
        else:
            raise ProcessError(("Bad value \"%s\" for %s <%s> \"%s\"" +
                                " attribute") %
                               (eStr, dom, node.nodeName, attrName))

        deadtime = None
        disc = None

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "deadtime":
                    deadtime = int(cls.getChildText(kid))
                elif kid.nodeName == "disc":
                    disc = cls.getChildText(kid).strip()
                else:
                    raise ProcessError(("Unknown %s <%s> child <%s>") %
                                       (dom, node.nodeName, kid.nodeName))

        if enabled and (deadtime is None or disc is None):
            raise ProcessError(("%s <%s> should specify both deadtime" +
                                " and disc") % (dom, node.nodeName))

        return (enabled, deadtime, disc)
    __parseSupernovaMode = classmethod(__parseSupernovaMode)

    def __setDomFormat(cls, dom, node):
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "deltaCompressed":
                    dom.setDeltaCompressed()
                elif kid.nodeName == "engineeringFormat":
                    dom.setEngineeringFormat()
                else:
                    print >>sys.stderr, "Unknown format <%s>" % kid.nodeName
    __setDomFormat = classmethod(__setDomFormat)

    def parse(cls, dom, configDir, baseName, strict):
        dcListList = dom.getElementsByTagName("domConfigList")
        if dcListList is None or len(dcListList) == 0:
            raise ProcessError("No <domConfigList> tag found in %s" % fileName)
        dcList = dcListList[0]

        if dcList.attributes is None or \
                not dcList.attributes.has_key("configId"):
            cfgId = None
        else:
            cfgId = dcList.attributes["configId"].value

        domIdToDom = cls.__loadDomIdMap()

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

                    #name = kid.attributes["name"].value

                    dom = RunDom(long(domId, 16), domGeom.string(),
                                 domGeom.pos(), domGeom.name(), domCfg)
                    if cls.PARSE_DOM_DATA:
                        cls.__parseDomData(dom, kid)
                    domCfg.addDom(dom)

                    domNum += 1
                else:
                    raise ProcessError("Unexpected %s child <%s>" %
                                       (dcList.nodeName, kid.nodeName))
                continue

            raise ProcessError("Found unknown %s node <%s>" %
                               (dcList.nodeName, kid.nodeName))

        return domCfg
    parse = classmethod(parse)

    def parseAllDomData(cls):
        cls.PARSE_DOM_DATA = True
    parseAllDomData = classmethod(parseAllDomData)

class DomConfigName(object):
    "DOM configuration file name and hub"""

    def __init__(self, fileName, hub):
        self.__fileName = fileName
        self.__hub = hub

    def xml(self, indent):
        if self.__hub is None or DomConfig.OMIT_HUB_NUMBER:
            hubStr = ""
        else:
            hubStr = " hub=\"%d\"" % self.__hub
        return "%s<domConfigList%s>%s</domConfigList>" % \
               (indent, hubStr, self.__fileName)

class DomConfig(object):
    """DOM configuration file details"""

    OMIT_HUB_NUMBER = False

    def __init__(self, fileName):
        self.__fileName = fileName
        self.__domList = []
        self.__stringMap = {}
        self.__commentOut = False
        self.__runCfgList = []

    def __cmp__(self, other):
        val = len(self.__domList) - len(other.__domList)
        if val == 0:
            sDoms = self.__domList[:]
            sDoms.sort()
            oDoms = other.__domList[:]
            oDoms.sort()
            for i in range(len(sDoms)):
                val = cmp(sDoms[i], oDoms[i])
                if val != 0:
                    break

        return val

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

    def addRunConfig(self, runCfg):
        self.__runCfgList.append(runCfg)

    def basename(self):
        b = os.path.basename(self.__fileName)
        if b.endswith(".xml"):
            b = b[:-4]
        return b

    def commentOut(self):
        """This domconfig file should be commented-out"""
        self.__commentOut = True

    def filename(self): return self.__fileName

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

    def getDOMsByHub(self, hub):
        hubDoms = []
        for d in self.__domList:
            if d.string() == hub:
                hubDoms.append(d)

        if len(hubDoms) == 0:
            return None
        return hubDoms

    def hubs(self):
        """Get the list of strings whose DOMs are referenced in this file"""
        return self.__stringMap.keys()

    def omitHubNumber(cls): cls.OMIT_HUB_NUMBER = True
    omitHubNumber = classmethod(omitHubNumber)

    def isCommentedOut(self):
        """Is domconfig file commented-out?"""
        return self.__commentOut

    def runCfgList(self):
        "Get the list of run configurations which reference this file"
        return self.__runCfgList[:]

    def xml(self, indent):
        """Return the XML string for this DOM configuration file"""
        if self.__commentOut:
            prefix = "<!--"
            suffix = " -->"
        else:
            prefix = ""
            suffix = ""
        hubs = self.__stringMap.keys()
        if self.OMIT_HUB_NUMBER or len(hubs) != 1:
            nStr = ""
        else:
            nStr = " hub=\"%d\"" % hubs[0]
        return "%s%s<domConfigList%s>%s</domConfigList>%s" % \
            (prefix, indent, nStr, self.__fileName, suffix)

    def write(self, fd, indent):
        print >>fd, "<?xml version='1.0' encoding='UTF-8'?>"
        print >>fd, "<domConfigList>"
        for dom in self.__domList:
            dom.write(fd, indent, 1)
        print >>fd, "</domConfigList>"

class StringHub(Component):
    "String hub data from a run configuration file"

    def __init__(self, id):
        self.__domConfigs = []

        super(StringHub, self).__init__("stringHub", id)

    def addDomConfig(self, domCfg):
        self.__domConfigs.append(domCfg)

    def deleteDomConfig(self, domCfg):
        "Return True if the dom configuration was found and deleted"
        deleted = True
        for i in range(len(self.__domConfigs)):
            if domCfg == self.__domConfigs[i]:
                del self.__domConfigs[i]
                deleted = True
                break
        return deleted

    def getDomConfigs(self):
        return self.__domConfigs[:]

    def isDeepCore(self):
        return (self.id() % 1000) > 78 and (self.id() % 1000) < 200

    def isIceTop(self):
        return (self.id() % 1000) >= 200

    def isInIce(self):
        return (self.id() % 1000) < 200

class ReplayHub(Component):
    "Replay hub data from a run configuration file"

    def __init__(self, id, hitFile):
        self.__hitFile = hitFile

        super(ReplayHub, self).__init__("replayHub", id)

    def xml(self, indent):
        return "%s<hub id=\"%d\" hitFile=\"%s\" />" % \
               (indent, self.id(), self.__hitFile)

class DAQConfig(object):
    """Run configuration data"""

    LIST_CLUSTER_CONFIGS = False

    def __init__(self, fileName):
        self.__fileName = fileName

        self.__comps = []
        self.__trigCfg = None
        self.__domCfgList = []
        self.__domCfgNames = []
        self.__replayBaseDir = None
        self.__replayHubList = []
        self.__stringHubs = {}
        self.__topComment = None
        self.__strayStream = None
        self.__senderOption = None

    def __cmp__(self, other):
        val = len(self.__comps) - len(other.__comps)
        if val == 0:
            val = len(self.__domCfgList) - len(other.__domCfgList)
            if val == 0:
                val = len(self.__domCfgNames) - len(other.__domCfgNames)
                if val == 0:
                    val = cmp(self.__trigCfg, other.__trigCfg)
                    if val == 0:
                        sComps = self.__comps[:]
                        sComps.sort()
                        oComps = other.__comps[:]
                        oComps.sort()
                        for i in range(len(sComps)):
                            val = cmp(sComps[i], oComps[i])
                            if val != 0:
                                break
                        if val == 0:
                            sDomCfgs = self.__domCfgList[:]
                            sDomCfgs.sort()
                            oDomCfgs = other.__domCfgList[:]
                            oDomCfgs.sort()
                            for i in range(len(sDomCfgs)):
                                val = cmp(sDomCfgs[i], oDomCfgs[i])
                                if val != 0:
                                    break
                            if val == 0:
                                sDCNames = self.__domCfgNames[:]
                                sDCNames.sort()
                                oDCNames = other.__domCfgNames[:]
                                oDCNames.sort()
                                for i in range(len(sDCNames)):
                                    val = cmp(sDCNames[i], oDCNames[i])
                                    if val != 0:
                                        break
        return val

    def __str__(self):
        if len(self.__domCfgList) > 0:
            if len(self.__domCfgNames) > 0:
                dcType = "mixed"
            else:
                dcType = "parsed"
        else:
            dcType = "names"
        return "%s[C*%d]%s" % (self.__fileName, len(self.__comps), dcType)

    def __hasHubs(self):
        """Does this run configuration include any DOMs or replayHubs?"""
        for c in self.__comps:
            if c.isHub():
                return True
        return False

    def addComponent(self, compName, strict):
        """Add a component name"""
        pound = compName.rfind("#")
        if pound < 0:
            self.__comps.append(Component(compName, 0))
        elif strict:
            raise BadComponentName("Found \"#\" in component name \"%s\"" %
                                   compName)
        else:
            self.__comps.append(Component(compName[:pound],
                                          int(compName[pound+1:])))

    def addDomConfig(self, domCfg, hub=None):
        """Add a DomConfig object"""
        self.__domCfgList.append(domCfg)
        domCfg.addRunConfig(self)

        hubs = domCfg.hubs()
        if hub is not None:
            if len(hubs) != 1:
                print >>sys.stderr, \
                          "Expected \"%s\" to be for hub %d, not %s" % \
                          (hub, hubs)
            elif hubs[0] != hub:
                print >>sys.stderr, \
                          "Expected \"%s\" to be for hub %d, not %s" % \
                          (hub, hubs[0])

        for s in hubs:
            if not self.__stringHubs.has_key(s):
                hub = StringHub(s)
                self.__stringHubs[s] = hub
                self.__comps.append(hub)
            self.__stringHubs[s].addDomConfig(domCfg)

    def addDomConfigName(self, dcName, hub):
        """Add a DomConfig object"""
        self.__domCfgNames.append(DomConfigName(dcName, hub))

        if hub is not None and not self.__stringHubs.has_key(hub):
            sh = StringHub(hub)
            self.__stringHubs[hub] = sh
            self.__comps.append(sh)

    def addReplayHub(self, id, hitFile):
        rh = ReplayHub(id, hitFile)
        self.__replayHubList.append(rh)
        self.__comps.append(rh)

    def basename(self):
        b = os.path.basename(self.__fileName)
        if b.endswith(".xml"):
            b = b[:-4]
        return b

    def components(self):
        objs = self.__comps[:]
        objs.sort()
        return objs

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

    def deleteDomConfig(self, domCfg):
        "Return True if the dom configuration was found and deleted"
        deleted = True
        for i in range(len(self.__domCfgList)):
            if domCfg == self.__domCfgList[i]:
                del self.__domCfgList[i]
                deleted = True
                break
        return deleted

    def filename(self): return self.__fileName

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
                newCfg.addComponent(c.name(), True)
        newCfg.setTriggerConfig(self.__trigCfg)
        for dc in self.__domCfgList:
            if not omitMap.has_key(dc):
                newCfg.addDomConfig(dc)
            else:
                dup = copy.copy(dc)
                dup.commentOut()
                newCfg.addDomConfig(dup)

        return newCfg

    def replace(self, domCfg, newList):
        "Replace one dom configuration with one or more new config files"
        deleted = self.deleteDomConfig(domCfg)
        if not deleted:
            raise DAQConfigException("Cannot find %s in %s" %
                                     (domCfg.filename(), self.__fileName))

        for s in domCfg.hubs():
            if self.__stringHubs.has_key(s):
                self.__stringHubs[s].deleteDomConfig(domCfg)

        for n in newList:
            self.addDomConfig(n)

    def setReplayBaseDir(self, dir):
        self.__replayBaseDir = dir

    def setSenderOption(self, hub, fwdIsolatedHits):
        self.__senderOption = (hub, fwdIsolatedHits)

    def setStrayStream(self, name, prescale):
        self.__strayStream = (name, prescale)

    def setTopComment(self, text):
        if self.__topComment is None:
            self.__topComment = text

    def setTriggerConfig(self, name):
        """Set the trigger configuration file for this run configuration"""
        self.__trigCfg = name

    def showList(cls, configDir, configName):
        if configDir is None:
            if cls.LIST_CLUSTER_CONFIGS:
                configDir = os.path.join(metaDir, "cluster-config", "src",
                                         "main", "xml")
            else:
                configDir = os.path.join(metaDir, "config")

        if not os.path.exists(configDir):
            raise DAQConfigDirNotFound("Could not find config dir %s" %
                                       configDir)

        if configName is None:
            configName = \
                CachedConfigName.getConfigToUse(None, False, True)


        cfgs = []

        for f in os.listdir(configDir):
            if not f.endswith(".xml"): continue
            cfg = os.path.basename(f[:-4])
            if cfg == 'default-dom-geometry': continue
            cfgs.append(cfg)

        cfgs.sort()
        for cname in cfgs:
            if configName is None:
                mark = ""
            elif cname == configName:
                mark = "=> "
            else:
                mark = "   "
            try:
                print "%s%-60s" % (mark, cname)
            except IOError:
                break
    showList = classmethod(showList)

    def validate(self):
        if not self.__hasHubs():
            raise ProcessError("No doms or replayHubs found in %s" %
                               self.basename())
        if self.__trigCfg is None:
            raise ProcessError("No <triggerConfig> found in %s" %
                               self.basename())

        (iiHub, iiTrig, ttHub, ttTrig) = (False, False, False, False)
        for c in self.__comps:
            if c.isHub():
                if c.isInIce():
                    iiHub = True
                else:
                    ttHub = True
            elif c.isTrigger():
                if c.name().lower().startswith("inice"):
                    iiTrig = True
                else:
                    ttTrig = True

        if iiHub and not iiTrig:
            raise ProcessError("Found in-ice hubs but no in-ice trigger in %s" %
                               self.basename())
        if not iiHub and iiTrig:
            raise ProcessError("Found in-ice trigger but no in-ice hubs in %s" %
                               self.basename())
        if ttHub and not ttTrig:
            raise ProcessError("Found icetop hubs but no icetop trigger in %s" %
                               self.basename())
        if not ttHub and ttTrig:
            raise ProcessError("Found icetop trigger but no icetop hubs in %s" %
                               self.basename())

    def write(self, fd):
        """Write this run configuration to the specified file descriptor"""
        indent = "    "
        in2 = indent + indent
        print >>fd, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        if self.__topComment is not None:
            print >>fd, "<!--%s-->" % self.__topComment
        print >>fd, "<runConfig>"
        for d in self.__domCfgList:
            print >>fd, d.xml(indent)
        for n in self.__domCfgNames:
            print >>fd, n.xml(indent)
        if self.__replayBaseDir is not None:
            print >>fd, "%s<hubFiles baseDir=\"%s\">" % \
                  (indent, self.__replayBaseDir)
            for r in self.__replayHubList:
                print >>fd, r.xml(in2)
            print >>fd, "%s</hubFiles>" % indent
        print >>fd, "%s<triggerConfig>%s</triggerConfig>" % \
            (indent, self.__trigCfg)
        for c in self.__comps:
            if not c.isHub():
                print >>fd, "%s<runComponent name=\"%s\"/>" % \
                      (indent, c.name())

        if self.__strayStream is not None:
            (name, prescale) = self.__strayStream
            in3 = in2 + indent

            print >>fd, "%s<stream name=\"%s\">" % (in2, name)
            print >>fd, "%s<prescale>%d</prescale>" % (in3, prescale)
            print >>fd, "%s</stream>" % in2

        if self.__senderOption is not None:
            (hub, fwdIsolatedHits) = self.__senderOption
            fwdName = "forwardIsolatedHitsToTrigger"
            if fwdIsolatedHits:
                fwdVal = "true"
            else:
                fwdVal = "false"

            in3 = in2 + indent
            in4 = in3 + indent

            print >>fd, "%s<stringHub hubId=\"%d\">" % (in2, hub)
            print >>fd, "%s<sender>" % in3
            print >>fd, "%s<%s>%s</%s>" % (in4, fwdName, fwdVal, fwdName)
            print >>fd, "%s</sender>" % in3
            print >>fd, "%s</stringHub>" % in2

        print >>fd, "</runConfig>"

class DAQConfigParser(XMLParser, XMLFileCache):
    """Run configuration file parser"""

    PARSE_DOM_CONFIG = True
    STRAY_STREAM_HACK = False

    def __init__(self):
        """Use this object's class methods directly"""
        raise Exception("Cannot create this object")

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

                    runCfg.addReplayHub(id, kid.attributes["hitFile"].value)
                else:
                    raise ProcessError("Unexpected %s child <%s>" %
                                       (topNode.nodeName, kid.nodeName))
    __parseHubFiles = classmethod(__parseHubFiles)

    def __parseSenderOption(cls, topNode, runCfg):
        if topNode.attributes is None or len(topNode.attributes) == 0:
            raise ProcessError("<%s> node has no attributes" %
                               topNode.nodeName)
        if len(topNode.attributes) != 1:
            raise ProcessError("<%s> node has extra attributes" %
                               topNode.nodeName)
        attrName = "hubId"
        if not topNode.attributes.has_key(attrName):
            raise ProcessError(("<%s> node should have \"%s\"" +
                                " attribute, not \"%s\"") %
                               (topNode.nodeName, attrName,
                                topNode.attributes.keys()[0]))

        hubId = int(topNode.attributes[attrName].value)
        fwdIsolatedHits = None

        for kid in topNode.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName != "sender":
                    raise ProcessError("Unknown <%s> node under <%s>" %
                                       (kid.nodeName, topNode.nodeName))

                for gkid in kid.childNodes:
                    if gkid.nodeType == Node.TEXT_NODE or \
                           gkid.nodeType == Node.COMMENT_NODE:
                        continue

                    if gkid.nodeType == Node.ELEMENT_NODE:
                        if gkid.nodeName != "forwardIsolatedHitsToTrigger":
                            raise ProcessError("Unknown <%s> node under <%s>" %
                                               (gkid.nodeName, kid.nodeName))

                        val = cls.getChildText(gkid).strip().lower()
                        if val == "true":
                            fwdIsolatedHits = True
                        elif val == "false":
                            fwdIsolatedHits = False
                        else:
                            msg = "Unknown value \"%s\" for <%s>" % \
                                  (val, gkid.nodeName)
                            raise ProcessError(msg)

        if fwdIsolatedHits is None:
            raise ProcessError("No value specified for <%s>" %
                               topNode.nodeName)

        runCfg.setSenderOption(hubId, fwdIsolatedHits)
    __parseSenderOption = classmethod(__parseSenderOption)

    def __parseStrayStream(cls, topNode, runCfg):
        if topNode.attributes is None or len(topNode.attributes) == 0:
            raise ProcessError("<%s> node has no attributes" %
                               topNode.nodeName)
        if len(topNode.attributes) != 1:
            raise ProcessError("<%s> node has extra attributes" %
                               topNode.nodeName)
        attrName = "name"
        if not topNode.attributes.has_key(attrName):
            raise ProcessError(("<%s> node should have \"%s\"" +
                                " attribute, not \"%s\"") %
                               (topNode.nodeName, attrName,
                                topNode.attributes.keys()[0]))

        name = topNode.attributes[attrName].value
        prescale = None

        for kid in topNode.childNodes:
            if kid.nodeType == Node.TEXT_NODE or \
                   kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName != "prescale":
                    raise ProcessError("Unknown <%s> node under <%s>" %
                                       (kid.nodeName, topNode.nodeName))

                prescale = int(cls.getChildText(kid))

        if prescale is None:
            raise ProcessError("No <prescale> specified for <%s>" %
                               topNode.nodeName)

        runCfg.setStrayStream(name, prescale)
    __parseStrayStream = classmethod(__parseStrayStream)

    def __parseTriggerConfig(cls, configDir, baseName):
        """Parse a trigger configuration file and return nothing"""
        fileName = os.path.join(configDir, "trigger", baseName)
        if not fileName.endswith(".xml"):
            fileName += ".xml"

        if not os.path.exists(fileName):
            raise BadFileError("Cannot read trigger config file \"%s\"" %
                               fileName)
    __parseTriggerConfig = classmethod(__parseTriggerConfig)

    def configExists(cls, configName,
                     configDir=os.path.join(metaDir, "config")):
        return cls.__buildPath(configDir, configName) != None
    configExists = classmethod(configExists)

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
                CachedConfigName.getConfigToUse(None, False, useActiveConfig)
            if configName is None:
                raise ConfigNotSpecifiedException("No configuration specified")

        sepIndex = configName.find('@')
        if sepIndex > 0:
            clusterDesc = configName[sepIndex+1:]
            configName = configName[:sepIndex]

        if doList:
            cls.showList(configDir, configName)
            return

        ccDir = \
            os.path.join(metaDir, 'cluster-config', 'src', 'main', 'xml')

        try:
            cfg = ClusterConfigParser.load(configName, ccDir)
        except XMLFileNotFound, xfnf:
            ex = xfnf

        if ex is not None:
            if configDir is None:
                configDir = os.path.join(metaDir, "config")

            savedValue = cls.PARSE_DOM_CONFIG
            cls.PARSE_DOM_CONFIG = False
            try:
                try:
                    runCfg = cls.load(configName, configDir)
                except XMLFileNotFound, nfe:
                    raise ex
            finally:
                cls.PARSE_DOM_CONFIG = savedValue

            cfg = RunCluster(runCfg, clusterDesc, configDir)
        return cfg
    getClusterConfiguration = classmethod(getClusterConfiguration)

    def parse(cls, dom, configDir, fileName, strict=True):
        """Parse a run configuration file and return a DAQConfig object"""
        topComment = None
        rcNode = None
        for kid in dom.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                topComment = kid.nodeValue
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "runConfig":
                    if rcNode is None:
                        rcNode = kid
                    else:
                        msg = "Found multiple <runConfig> tags in %s" % \
                              fileName
                        raise ProcessError(msg)

        if rcNode is None:
            raise ProcessError("No <runConfig> tag found in %s" % fileName)

        domcfgDir = os.path.join(configDir, "domconfigs")

        runCfg = DAQConfig(fileName)
        if topComment is not None:
            runCfg.setTopComment(topComment)

        hubFiles = None
        for kid in rcNode.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "domConfigList":
                    if kid.attributes is None or len(kid.attributes) == 0:
                        hub = None
                    else:
                        if len(kid.attributes) != 1:
                            raise ProcessError(("<%s> node has extra" +
                                                " attributes") % kid.nodeName)
                        attrName = "hub"
                        if not kid.attributes.has_key(attrName):
                            raise ProcessError(("<%s> node should have" +
                                                "  \"%s\" attribute, not" +
                                                " \"%s\"") %
                                               (kid.nodeName, attrName,
                                                kid.attributes.keys()[0]))

                        hub = int(kid.attributes[attrName].value)

                    dcName = cls.getChildText(kid).strip()
                    if hub is None or cls.PARSE_DOM_CONFIG:
                        domCfg = DomConfigParser.load(dcName, domcfgDir,
                                                      strict)
                        runCfg.addDomConfig(domCfg, hub)
                    else:
                        runCfg.addDomConfigName(dcName, hub)
                elif kid.nodeName == "triggerConfig":
                    trigCfg = cls.getChildText(kid)
                    cls.__parseTriggerConfig(configDir, trigCfg)
                    runCfg.setTriggerConfig(trigCfg)
                elif kid.nodeName == "hubFiles":
                    if kid.attributes is None or len(kid.attributes) == 0:
                        raise ProcessError("<%s> node has no attributes" %
                                           kid.nodeName)
                    if len(kid.attributes) != 1:
                        raise ProcessError("<%s> node has extra attributes" %
                                           kid.nodeName)
                    attrName = "baseDir"
                    if not kid.attributes.has_key(attrName):
                        raise ProcessError(("<%s> node should have \"%s\"" +
                                            " attribute, not \"%s\"") %
                                           (kid.nodeName, attrName,
                                            kid.attributes.keys()[0]))

                    runCfg.setReplayBaseDir(kid.attributes[attrName].value)

                    cls.__parseHubFiles(kid, runCfg)
                elif kid.nodeName == "stringHub":
                    cls.__parseSenderOption(kid, runCfg)
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

                    runCfg.addComponent(kid.attributes["name"].value, strict)

                elif kid.nodeName == "defaultLogLevel":
                    pass
                elif kid.nodeName == "stream":
                    if cls.STRAY_STREAM_HACK:
                        cls.__parseStrayStream(kid, runCfg)
                    else:
                        print >>sys.stderr, "Ignoring stray <stream> in %s" % \
                              fileName
                else:
                    raise ProcessError("Unknown runConfig node <%s> in %s" %
                                       (kid.nodeName, fileName))
                continue

            raise ProcessError("Found unknown runConfig node <%s>" %
                               kid.nodeName)

        if strict:
            runCfg.validate()

        return runCfg
    parse = classmethod(parse)

if __name__ == "__main__":
    import datetime, optparse

    p = optparse.OptionParser()
    p.add_option("-c", "--check-config", type="string", dest="toCheck",
                 action="store", default=None,
                 help="Check whether configuration is valid")
    opt, args = p.parse_args()

    configDir  = os.path.join(metaDir, "config")

    if opt.toCheck:
        try:
            DAQConfigParser.load(opt.toCheck, configDir)
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
        dc = DAQConfigParser.load(configName, configDir)
        diff = datetime.datetime.now() - startTime
        initTime = float(diff.seconds) + (float(diff.microseconds) / 1000000.0)

        comps = dc.components()
        comps.sort()
        for comp in comps:
            print 'Comp %s log %s' % (str(comp), str(comp.logLevel()))

        startTime = datetime.datetime.now()
        dc = DAQConfigParser.load(configName, configDir)
        diff = datetime.datetime.now() - startTime
        nextTime = float(diff.seconds) + (float(diff.microseconds) / 1000000.0)
        print "Initial time %.03f, subsequent time: %.03f" % \
            (initTime, nextTime)
