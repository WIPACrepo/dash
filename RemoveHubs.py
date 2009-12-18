#!/usr/bin/env python
#
# Create a new run configuration without one or more hubs

import copy, os, re, sys, traceback

from xml.dom import minidom, Node

from DefaultDomGeometry import DefaultDomGeometryReader, XMLParser

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class XMLError(Exception): pass
class ProcessError(XMLError): pass
class BadFileError(XMLError): pass

class DupDomGeometry(object):
    "Duplicate class from DefaultDomGeometry.py"
    def __init__(self, string, pos, id, name, prod, chanId=None,
                 x=None, y=None, z=None):
        self.__string = string
        self.__pos = pos
        self.__id = id
        self.__name = name
        self.__prod = prod
        self.__chanId = chanId
        self.__x = x
        self.__y = y
        self.__z = z

        self.__desc = None

        self.__origOrder = None
        self.__prevString = None

    def __cmp__(self, other):
        if self.__origOrder is None:
            if other.__origOrder is not None:
                return -1
        elif other.__origOrder is None:
            return 1
        elif self.__origOrder != other.__origOrder:
            return self.__origOrder - other.__origOrder

        if self.__string is None:
            if other.__string is not None:
                return -1
        elif other.__string is None:
            return 1
        elif self.__string != other.__string:
            return self.__string - other.__string

        if self.__prevString is None:
            if other.__prevString is not None:
                return -1
        elif other.__prevString is None:
            return 1
        elif self.__prevString != other.__prevString:
            return self.__prevString - other.__prevString

        if self.__pos is None:
            if other.__pos is not None:
                return -1
        elif other.__pos is None:
            return 1
        elif self.__pos != other.__pos:
            return self.__pos - other.__pos

        return 0

    def __str__(self):
        return "%s[%s] %02d-%02d" % \
            (self.__id, self.__name, self.__string, self.__pos)

    def channelId(self): return self.__chanId

    def desc(self):
        if self.__desc is None:
            return "-"
        return self.__desc

    def id(self): return self.__id
    def name(self): return self.__name
    def originalOrder(self): return self.__origOrder
    def pos(self): return self.__pos
    def prodId(self): return self.__prod

    def setChannelId(self, chanId): self.__chanId = chanId

    def setDesc(self, desc):
        if desc is None or desc == "-" or desc == "NULL":
            self.__desc = None
        else:
            self.__desc = desc

    def setId(self, id): self.__id = id
    def setName(self, name): self.__name = name
    def setOriginalOrder(self, num): self.__origOrder = num
    def setPos(self, pos): self.__pos = pos
    def setProdId(self, prod): self.__prod = prod

    def setString(self, strNum):
        self.__prevString = self.__string
        self.__string = strNum

    def string(self): return self.__string

    def validate(self):
        if self.__pos is None:
            if self.__name is not None:
                dname = self.__name
            elif id is None:
                dname = self.__id
            else:
                raise ProcessError("Blank DOM entry")

            raise ProcessError("DOM %s is missing ID in string %s" % dname)
        if self.__id is None:
            raise ProcessError("DOM pos %d is missing ID in string %s" %
                               (self.__pos, self.__string))
        if self.__name is None:
            raise ProcessError("DOM %s is missing ID in string %s" % self.__id)

    def x(self): return self.__x
    def y(self): return self.__y
    def z(self): return self.__z

class DupDefaultDomGeometry(object):
    def __init__(self, translateDoms):
        self.__stringToDom = {}
        self.__translateDoms = translateDoms
        self.__domIdToDom = {}

    def addDom(self, dom):
        self.__stringToDom[dom.string()].append(dom)

        if self.__translateDoms:
            mbId = dom.id()
            if self.__domIdToDom.has_key(mbId):
                oldNum = self.__domIdToDom[mbId].getString()
                if oldNum != stringNum:
                    print >>sys.stderr, ("DOM %s belongs to both" +
                                         " string %d and %d") % \
                                         (mbId, oldNum, stringNum)

            self.__domIdToDom[mbId] = dom

    def addString(self, stringNum, errorOnMulti=True):
        if not self.__stringToDom.has_key(stringNum):
            self.__stringToDom[stringNum] = []
        elif errorOnMulti:
            errMsg = "Found multiple entries for string %d" % stringNum
            raise ProcessError(errMsg)

    def deleteDom(self, stringNum, dom):
        for i in range(len(self.__stringToDom[stringNum])):
            if dom == self.__stringToDom[stringNum][i]:
                del self.__stringToDom[stringNum][i]
                return

        print >>sys.stderr, "Could not delete %s from string %d" % \
            (dom, stringNum)

    def dump(self):
        "Dump the string->DOM dictionary in default-dom-geometry format"
        strList = self.__stringToDom.keys()
        strList.sort()

        print "<?xml version=\"1.0\"?>"
        print "<domGeometry>"
        for s in strList:
            domList = self.__stringToDom[s]
            if len(domList) == 0:
                continue

            print "   <string>"
            print "      <number>%02d</number>" % s

            domList.sort()
            for dom in domList:
                print "     <dom>"
                if dom.pos() is not None:
                    if s % 1000 == 1:
                        print "        <position>%d</position>" % dom.pos()
                    else:
                        print "        <position>%02d</position>" % dom.pos()
                if dom.channelId() is not None:
                    print "        <channelId>%s</channelId>" % dom.channelId()
                if dom.id() is not None:
                    print "        <mainBoardId>%s</mainBoardId>" % dom.id()
                if dom.name() is not None:
                    print "        <name>%s</name>" % dom.name()
                if dom.prodId() is not None:
                    print "        <productionId>%s</productionId>" % dom.prodId()
                if dom.x() is not None:
                    if dom.x() == 0.0:
                        xStr = "0.0"
                    else:
                        xStr = "%4.2f" % dom.x()
                    print "        <xCoordinate>%s</xCoordinate>" % xStr
                if dom.y() is not None:
                    if dom.y() == 0.0:
                        yStr = "0.0"
                    else:
                        yStr = "%4.2f" % dom.y()
                    print "        <yCoordinate>%s</yCoordinate>" % yStr
                if dom.z() is not None:
                    if dom.z() == 0.0:
                        zStr = "0.0"
                    else:
                        zStr = "%4.2f" % dom.z()
                    print "        <zCoordinate>%s</zCoordinate>" % zStr
                print "     </dom>"

            print "   </string>"
        print "</domGeometry>"

    def dumpNicknames(self):
        "Dump the DOM data in nicknames.txt format"
        allDoms = []
        for s in self.__stringToDom:
            for dom in self.__stringToDom[s]:
                allDoms.append(dom)

        allDoms.sort(cmp=lambda x,y : cmp(x.name(), y.name()))

        print "mbid\tthedomid\tthename\tlocation\texplanation"
        for dom in allDoms:
            name = dom.name().encode("iso-8859-1")

            try:
                desc = dom.desc().encode("iso-8859-1")
            except:
                desc = "-"

            print "%s\t%s\t%s\t%02d-%02d\t%s" % \
                (dom.id(), dom.prodId(), name, dom.string(), dom.pos(), desc)

    def getDom(self, strNum, pos):
        if self.__stringToDom.has_key(strNum):
            for dom in self.__stringToDom[strNum]:
                if dom.pos() == pos:
                    return dom

        return None
        
    def getDomIdToDomDict(self):
        "Get the DOM ID -> DOM object dictionary"
        return self.__domIdToDom

    def getIcetopNum(cls, strNum):
        "Translate the in-ice string number to the corresponding icetop hub"
        if strNum % 1000 == 0 or strNum >= 2000: return strNum
        if strNum > 1000: return ((((strNum % 100) + 7)) / 8) + 1200
        # SPS map goes here
        if strNum in [46, 55, 56, 65, 72, 73, 77, 78]: return 201
        if strNum in [38, 39, 48, 58, 64, 66, 71, 74]: return 202
        if strNum in [30, 40, 47, 49, 50, 57, 59, 67]: return 203
        if strNum in [4,  11, 27, 10, 5,  18, 20, 36]: return 204
        if strNum in [45, 54, 62, 63, 69, 70, 75, 76]: return 205
        if strNum in [21, 29, 44, 52, 53, 60, 61, 68]: return 206
        if strNum in [26, 6,  12, 9,  3,   2, 13, 17]: return 207
        if strNum in [19, 37, 28]: return 208  
        raise ProcessError("Could not find icetop hub for string %d" % strNum)
    getIcetopNum = classmethod(getIcetopNum)

    def getStringToDomDict(self):
        "Get the string number -> DOM object dictionary"
        return self.__stringToDom

    def mergeMissing(self, oldDomGeom):
        keys = self.__stringToDom.keys()

        for s in oldDomGeom.__stringToDom:
            if not s in keys:
                self.__stringToDom[s] = oldDomGeom.__stringToDom[s]

    def rewrite(self, rewriteOldIcetop=True):
        """
        Rewrite default-dom-geometry from 64 DOMs per string hub to
        60 DOMs per string hub and 32 DOMs per icetop hub
        """
        strList = self.__stringToDom.keys()
        strList.sort()

        for s in strList:
            baseNum = s % 1000
            domList = self.__stringToDom[s][:]

            for dom in domList:
                if dom.pos() < 1 or dom.pos() > 64:
                    print >>sys.stderr, "Bad position %d for %s" % \
                        (dom.pos(), dom)
                else:
                    if baseNum < 200:
                        pos = dom.pos() - 1
                    elif dom.originalOrder() is not None:
                        pos = dom.originalOrder()
                    dom.setChannelId((baseNum * 64) + pos)

                if (baseNum <= 80 and dom.pos() <= 60) or \
                        (baseNum > 200 and dom.pos() > 60) or \
                        (not rewriteOldIcetop and baseNum > 80 and \
                             dom.pos() > 60):
                    pass
                else:
                    if dom.pos() <= 60:
                        it = baseNum
                    elif rewriteOldIcetop and baseNum > 80 and baseNum < 200:
                        it = baseNum % 10 + 200
                    else:
                        try:
                            it = DefaultDomGeometry.getIcetopNum(s)
                        except ProcessError:
                            print >>sys.stderr, \
                                "Dropping %d-%d: Unknown icetop hub" % \
                                (s, dom.pos())
                            self.deleteDom(s, dom)
                            it = s

                    if it != baseNum:
                        self.deleteDom(s, dom)

                        it = (s / 1000) * 1000 + (it % 1000)
                        dom.setString(it)

                        self.addString(it, errorOnMulti=False)
                        self.addDom(dom)

class DupDefaultDomGeometryReader(XMLParser):
    def __parseDomNode(cls, stringNum, node):
        "Extract a single DOM's data from the default-dom-geometry XML tree"
        if node.attributes is not None and len(node.attributes) > 0:
            raise ProcessError("<%s> node has unexpected attributes" %
                               node.nodeName)

        pos = None
        id = None
        name = None
        prod = None
        chanId = None
        x = None
        y = None
        z = None

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "position":
                    pos = int(cls.getChildText(kid))
                elif kid.nodeName == "mainBoardId":
                    id = cls.getChildText(kid)
                elif kid.nodeName == "name":
                    name = cls.getChildText(kid)
                elif kid.nodeName == "productionId":
                    prod = cls.getChildText(kid)
                elif kid.nodeName == "channelId":
                    chanId = cls.getChildText(kid)
                elif kid.nodeName == "xCoordinate":
                    x = float(cls.getChildText(kid))
                elif kid.nodeName == "yCoordinate":
                    y = float(cls.getChildText(kid))
                elif kid.nodeName == "zCoordinate":
                    z = float(cls.getChildText(kid))
                else:
                    raise ProcessError("Unexpected %s child <%s>" %
                                       (node.nodeName, kid.nodeName))
                continue

            raise ProcessError("Found unknown %s node <%s>" %
                               (node.nodeName, kid.nodeName))

        dom = DupDomGeometry(stringNum, pos, id, name, prod, chanId, x, y, z)
        dom.validate()

        return dom
    __parseDomNode = classmethod(__parseDomNode)

    def __parseStringNode(cls, geom, node):
        "Extract data from a default-dom-geometry <string> node tree"
        if node.attributes is not None and len(node.attributes) > 0:
            raise ProcessError("<%s> node has unexpected attributes" %
                               node.nodeName)

        stringNum = None
        origOrder = 0

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "number":
                    stringNum = int(cls.getChildText(kid))
                    geom.addString(stringNum)
                    origOrder = 0
                elif kid.nodeName == "dom":
                    if stringNum is None:
                        raise ProcessError("Found <dom> before <number>" +
                                           " under <string>")
                    dom = cls.__parseDomNode(stringNum, kid)

                    dom.setOriginalOrder(origOrder)
                    origOrder += 1

                    geom.addDom(dom)
                else:
                    raise ProcessError("Unexpected %s child <%s>" %
                                       (node.nodeName, kid.nodeName))
                continue

            raise ProcessError("Found unknown %s node <%s>" %
                               (node.nodeName, kid.nodeName))

        if stringNum is None:
            raise ProcessError("String is missing number")
    __parseStringNode = classmethod(__parseStringNode)

    def parse(cls, fileName=None, translateDoms=False):
        if fileName is None:
            fileName = os.path.join(metaDir, "config",
                                    "default-dom-geometry.xml")

        if not os.path.exists(fileName):
            raise BadFileError("Cannot read default dom geometry file \"%s\"" %
                               fileName)

        try:
            dom = minidom.parse(fileName)
        except Exception, e:
            raise ProcessError("Couldn't parse \"%s\": %s" % (fileName, str(e)))

        gList = dom.getElementsByTagName("domGeometry")
        if gList is None or len(gList) != 1:
            raise ProcessError("No <domGeometry> tag found in %s" % fileName)

        geom = DupDefaultDomGeometry(translateDoms)
        for kid in gList[0].childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "string":
                    cls.__parseStringNode(geom, kid)
                else:
                    raise ProcessError("Unknown domGeometry node <%s>" %
                                       kid.nodeName)
                continue

            raise ProcessError("Found unknown domGeometry node <%s>" %
                               kid.nodeName)

        return geom
    parse = classmethod(parse)

class RunDom(object):
    """Minimal details for a single DOM"""
    def __init__(self, id, strNum, domCfg):
        self.__id = id
        self.__string = strNum
        self.__domCfg = domCfg

    def __repr__(self):  return str(self)

    def __str__(self):
        return "%012x" % self.__id

    def domConfig(self): return self.__domCfg
    def id(self): return self__id
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

    def isCommentedOut(self):
        """Is domconfig file commented-out?"""
        return self.__commentOut

    def xml(self, indent):
        """Return the XML string for this DOM configuration file"""
        includeStringNumber = False

        if self.__commentOut:
            prefix = "<!-- "
            suffix = " -->"
        else:
            prefix = indent
            suffix = ""
        strList = self.__stringMap.keys()
        if not includeStringNumber or len(strList) != 1:
            nStr = ""
        else:
            nStr = " n=\"%d\"" % strList[0]
        return "%s<domConfigList%s>%s</domConfigList>%s" % \
            (prefix, nStr, self.__fileName, suffix)

class RunConfig(object):
    """Run configuration data"""
    def __init__(self, fileName):
        self.__fileName = fileName

        self.__comps = []
        self.__trigCfg = None
        self.__domCfgList = []
        self.__stringMap = {}

    def __str__(self):
        return "%s[C*%d D*%d]" % \
            (self.__fileName, len(self.__comps), len(self.__domCfgList))

    def addComponent(self, comp):
        """Add a component name"""
        self.__comps.append(comp)

    def addDomConfig(self, domCfg):
        """Add a DomConfig object"""
        self.__domCfgList.append(domCfg)

        for s in domCfg.getStringList():
            if not self.__stringMap.has_key(s):
                self.__stringMap[s] = []
            self.__stringMap[s].append(domCfg)

    def components(self):
        """Return the list of component names"""
        return self.__comps[:]

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
            print >>fd, "%s<runComponent name=\"%s\"/>" % (indent, c)
        print >>fd, "</runConfig>"

    def filename(self): return self.__fileName

    def hasDomConfigs(self):
        """Does this run configuration have any DOM configuration files?"""
        return len(self.__domCfgList) > 0

    def hasTriggerConfig(self):
        """Does this run configuration have a trigger configuration file?"""
        return self.__trigCfg is not None

    def hubIds(self):
        keys = self.__stringMap.keys()
        keys.sort()

        hubIds = []
        for h in keys:
            for dc in self.__stringMap[h]:
                if not dc.isCommentedOut():
                    hubIds.append(h)
                    break

        return hubIds

    def omit(self, hubIdList):
        """Create a new run configuration which omits the specified hubs"""
        omitMap = {}

        error = False
        for h in hubIdList:
            if not self.__stringMap.has_key(h):
                print >>sys.stderr, "Hub %s not found in %s" % \
                    (getHubName(h), self.__fileName)
                error = True
            else:
                domCfgList = self.__stringMap[h]
                if len(domCfgList) != 1:
                    dfStr = None
                    for dc in domCfgList:
                        if dfStr is None:
                            dfStr = dc.filename()
                        else:
                            dfStr += ", " + dc.filename()
                    print >>sys.stderr, ("Hub %s is specified in multiple" +
                                         " domConfig files: %s") % \
                                         (getHubName(h), dfStr)
                    error = True
                else:
                    omitMap[domCfgList[0]] = h

        if error:
            return None

        newCfg = RunConfig(self.__fileName)
        for c in self.__comps:
            newCfg.addComponent(c)
        newCfg.setTriggerConfig(self.__trigCfg)
        for dc in self.__domCfgList:
            if not omitMap.has_key(dc):
                newCfg.addDomConfig(dc)
            else:
                dup = copy.copy(dc)
                dup.commentOut()
                newCfg.addDomConfig(dup)

        return newCfg

    def setTriggerConfig(self, name):
        """Set the trigger configuration file for this run configuration"""
        self.__trigCfg = name

class RunConfigParser(XMLParser):
    """Run configuration file parser"""

    DEFAULT_DOM_GEOMETRY = None

    def __init__(self):
        """Use this object's class methods directly"""
        raise Exception("Cannot create this object")

    def __parseDomConfig(cls, baseName):
        """Parse a DOM configuration file and return a DomConfig object"""
        if RunConfigParser.DEFAULT_DOM_GEOMETRY is None:
            try:
                RunConfigParser.DEFAULT_DOM_GEOMETRY = \
                    DefaultDomGeometryReader.parse(translateDoms=True)
            except AttributeError:
                RunConfigParser.DEFAULT_DOM_GEOMETRY = \
                    DupDefaultDomGeometryReader.parse(translateDoms=True)

        domIdToDom = RunConfigParser.DEFAULT_DOM_GEOMETRY.getDomIdToDomDict()

        fileName = os.path.join(metaDir, "config", "domconfigs", baseName)
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

                    strNum = domIdToDom[domId].string()

                    dom = RunDom(int(domId, 16), strNum, domCfg)
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

    def __parseTriggerConfig(cls, baseName):
        """Parse a trigger configuration file and return nothing"""
        fileName = os.path.join(metaDir, "config", "trigger", baseName)
        if not fileName.endswith(".xml"):
            fileName += ".xml"

        if not os.path.exists(fileName):
            raise BadFileError("Cannot read trigger config file \"%s\"" %
                               fileName)
    __parseTriggerConfig = classmethod(__parseTriggerConfig)

    def parse(cls, dom, fileName):
        """Parse a run configuration file and return a RunConfig object"""
        rcList = dom.getElementsByTagName("runConfig")
        if rcList is None or len(rcList) == 0:
            raise ProcessError("No <runConfig> tag found in %s" % fileName)

        runCfg = RunConfig(fileName)

        hubFiles = None
        for kid in rcList[0].childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "domConfigList":
                    domCfg = cls.__parseDomConfig(cls.getChildText(kid))
                    runCfg.addDomConfig(domCfg)
                elif kid.nodeName == "triggerConfig":
                    trigCfg = cls.getChildText(kid)
                    cls.__parseTriggerConfig(trigCfg)
                    runCfg.setTriggerConfig(trigCfg)
                elif kid.nodeName == "hubFiles":
                    print >>sys.stderr, \
                        "Ignoring <hubFiles> in \"%s\"" % fileName
                    hubFiles = True
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

        if not runCfg.hasDomConfigs() and hubFiles is None:
            raise ProcessError("No <domConfigList> found")
        if not runCfg.hasTriggerConfig():
            raise ProcessError("No <triggerConfig> found")

        return runCfg
    parse = classmethod(parse)

class CCCException(Exception): pass

class ClusterConfigCreator(object):
    CLUSTER = { "sps" :
                    { "spadeDir" : "/mnt/data/pdaqlocal",
                      "copyDir" : "/mnt/data/pdaq/log-copies",
                      "logLevel" : "INFO",
                      }
                }

    def __init__(self, clusterName):
        if not self.CLUSTER.has_key(clusterName):
            raise CCCException("Unknown cluster name \"%s\"" % clusterName)

        self.__clusterName = clusterName

    def __writeLocation(self, fd, name, component, id=None):
        host = self.__clusterName + "-" + name

        if component is None:
            print >>fd, "    <location name=\"%s\" host=\"%s\"/>" % \
                (name, host)
        else:
            if id is None:
                idStr = ""
            else:
                idStr = " id=\"%02d\"" % id

            print >>fd, "    <location name=\"%s\" host=\"%s\">" % (name, host)
            if type(component) != list:
                print >>fd, "      <module name=\"%s\"%s/>" % (component, idStr)
            else:
                for c in component:
                    print >>fd, "      <module name=\"%s\"%s/>" % (c, idStr)
            print >>fd, "    </location>"

    def write(self, fd, runCfg, cfgName=None):
        if cfgName is None:
            cfgStr = ""
        else:
            cfgStr = " configName=\"%s\"" % cfgName

        print >>fd, "<icecube%s>" % cfgStr
        print >>fd, "  <cluster name=\"%s\">" % self.__clusterName

        print >>fd, "    <logDirForSpade>%s</logDirForSpade>" % \
            self.CLUSTER[self.__clusterName]["spadeDir"]
        print >>fd, "    <logDirCopies>%s</logDirCopies>" % \
            self.CLUSTER[self.__clusterName]["copyDir"]
        print >>fd, "    <defaultLogLevel>%s</defaultLogLevel>" % \
            self.CLUSTER[self.__clusterName]["logLevel"]

        needInIce = False
        needIceTop = False

        for id in runCfg.hubIds():
            if id < 100:
                hubName = "ichub%02d" % id
                needInIce = True
            else:
                hubName = "ithub%02d" % (id - 200)
                needIceTop = True

            self.__writeLocation(fd, hubName, "StringHub", id)
            print >>fd, ""

        self.__writeLocation(fd, "2ndbuild", "SecondaryBuilders")
        self.__writeLocation(fd, "evbuilder", "eventBuilder")

        trigList = []
        if needInIce: trigList.append("inIceTrigger")
        if needIceTop: trigList.append("iceTopTrigger")
        trigList.append("globalTrigger")
        self.__writeLocation(fd, "trigger", trigList)
        print >>fd, ""

        self.__writeLocation(fd, "expcont", None)

        print >>fd, "  </cluster>"
        print >>fd, "</icecube>"

def createClusterConfigName(fileName, hubIdList):
    configDir = os.path.join(metaDir, "cluster-config", "src", "main", "xml")
    return createConfigName(configDir, fileName, hubIdList)

def createConfigName(configDir, fileName, hubIdList):
    """
    Create a new file name from the original name and the list of omitted hubs
    """
    baseName = os.path.basename(fileName)
    if baseName.endswith(".xml"):
        baseName = baseName[:-4]

    noStr = ""
    for h in hubIdList:
        noStr += "-no" + getHubName(h)

    return os.path.join(configDir, baseName + noStr + ".xml")

def createRunConfigName(fileName, hubIdList):
    """
    Create a new file name from the original name and the list of omitted hubs
    """
    configDir = os.path.join(metaDir, "config")
    return createConfigName(configDir, fileName, hubIdList)

def findFile(baseName):
    """Check all possible locations for the run configuration file"""
    for top in (metaDir, "."):
        for dir in ("config", "."):
            name = os.path.join(top, dir, baseName)
            if os.path.exists(name):
                return name
            elif os.path.exists(name + ".xml"):
                return name + ".xml"

    return None

def getHubName(num):
    """Get the standard representation for a hub number"""
    if num > 0 and num < 100:
        return "%02d" % num
    if num > 200 and num < 220:
        return "%02dt" % (num - 200)
    return "?%d?" % num

def loadConfig(cfgName):
    "Load the run configuration"
    fileName = findFile(cfgName)
    if fileName is not None:
        parsed = False
        try:
            dom = minidom.parse(fileName)
            parsed = True
        except Exception, e:
            print >>sys.stderr, "Couldn't parse \"%s\": %s" % (fileName, str(e))
        except KeyboardInterrupt:
            print >>sys.stderr, \
                "Couldn't parse \"%s\": KeyboardInterrupt" % fileName

        if parsed:
            try:
                return RunConfigParser.parse(dom, fileName)
            except XMLError, xe:
                print >>sys.stderr, "%s: %s" % (fileName, str(xe))
            except KeyboardInterrupt:
                print >>sys.stderr, \
                    "Couldn't parse \"%s\": KeyboardInterrupt" % fileName

    return (None, None)

def parseArgs():
    """
    Parse command-line arguments
    Return a tuple containing:
        a boolean indicating if the file should be overwritten if it exists
        the run configuration name
        the list of hub IDs to be removed
    """
    cfgDir = os.path.join(metaDir, "config")
    if not os.path.exists(cfgDir):
        print >>sys.stderr, "Cannot find configuration directory"

    cluCfgName = None
    forceCreate = False
    runCfgName = None
    hubIdList = []

    needCluCfgName = False

    usage = False
    for a in sys.argv[1:]:
        if a == "--force":
            forceCreate = True
            continue

        if a == "-C":
            needCluCfgName = True
            continue

        if needCluCfgName:
            cluCfgName = a
            needCluCfgName = False
            continue

        if runCfgName is None:
            path = os.path.join(cfgDir, a)
            if not path.endswith(".xml"):
                path += ".xml"

            if os.path.exists(path):
                runCfgName = a
                continue

        for s in a.split(","):
            if s.endswith("t"):
                try:
                    num = int(s[:-1])
                    hubIdList.append(200 + num)
                    continue
                except:
                    print >>sys.stderr, "Unknown argument \"%s\"" % s
                    usage = True
                    continue

            if s.endswith("i"):
                s = s[:-1]

            try:
                num = int(s)
                hubIdList.append(num)
                continue
            except:
                print >>sys.stderr, "Unknown argument \"%s\"" % a
                usage = True
                continue

    if not usage and runCfgName is None:
        print >>sys.stderr, "No run configuration specified"
        usage = True

    if not usage and len(hubIdList) == 0:
        print >>sys.stderr, "No hub IDs specified"
        usage = True

    if usage:
        print >>sys.stderr, \
            "Usage: %s runConfig hubId [hubId ...]" % sys.argv[0]
        print >>sys.stderr, "  (Hub IDs can be \"6\", \"06\", \"6i\", \"6t\")"
        raise SystemExit()

    return (forceCreate, runCfgName, cluCfgName, hubIdList)

if __name__ == "__main__":
    (forceCreate, runCfgName, cluCfgName, hubIdList) = parseArgs()

    newPath = createRunConfigName(runCfgName, hubIdList)
    if os.path.exists(newPath):
        if forceCreate:
            print >>sys.stderr, "WARNING: Overwriting %s" % newPath
        else:
            print >>sys.stderr, "WARNING: %s already exists" % newPath
            print >>sys.stderr, "Specify --force to overwrite this file"
            raise SystemExit()

    runCfg = loadConfig(runCfgName)
    if runCfg is not None:
        newCfg = runCfg.omit(hubIdList)
        if newCfg is not None:
            fd = open(newPath, "w")
            newCfg.write(fd)
            fd.close()
            print "Created %s" % newPath

            if cluCfgName is not None:
                cluPath = createClusterConfigName(cluCfgName, hubIdList)
                if os.path.exists(cluPath):
                    if forceCreate:
                        print >>sys.stderr, "WARNING: Overwriting %s" % cluPath
                    else:
                        print >>sys.stderr, "WARNING: %s already exists" % \
                            cluPath
                        print >>sys.stderr, \
                            "Specify --force to overwrite this file"
                        raise SystemExit()

                ccc = ClusterConfigCreator("sps")
                fd = open(cluPath, "w")
                ccc.write(fd, newCfg)
                fd.close()
                print "Created %s" % cluPath
