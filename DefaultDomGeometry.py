#!/usr/bin/env python
#
# Rewrite the default-dom-geometry file from 64 DOMs per in-ice string to
# 60 DOMs per in-ice string and 32 DOMs per icetop hub and print the
# result to sys.stdout

import os, re, sys, traceback

from xml.dom import minidom, Node

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

class XMLError(Exception): pass
class ProcessError(XMLError): pass
class BadFileError(XMLError): pass

class XMLParser(object):
    
    @staticmethod
    def getChildText(node):
        "Return the text from this node's child"
        nodeName = "<%s>" % str(node.nodeName)
        if nodeName == "<#document>":
            nodeName = "top-level"

        if node.childNodes is None or len(node.childNodes) == 0:
            raise ProcessError("No %s child nodes" % nodeName)

        text = None
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                if text is not None:
                    raise ProcessError("Found multiple %s text nodes" %
                                       nodeName)
                text = kid.nodeValue
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                raise ProcessError("Unexpected %s child <%s>" %
                                   (node.nodeName, kid.nodeName))

            raise ProcessError("Found unknown %s node <%s>" %
                               (nodeName, kid.nodeName))

        if text is None:
            raise ProcessError("No text child node for %s" % nodeName)

        return text


class DomGeometry(object):
    "Data for a single DOM"
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

class DefaultDomGeometry(object):
    def __init__(self, translateDoms=True):
        self.__stringToDom = {}
        self.__translateDoms = translateDoms
        self.__domIdToDom = {}

    def addDom(self, dom):
        self.__stringToDom[dom.string()].append(dom)

        if self.__translateDoms:
            mbId = dom.id()
            if self.__domIdToDom.has_key(mbId):
                oldNum = self.__domIdToDom[mbId].string()
                if oldNum != dom.string():
                    print >>sys.stderr, ("DOM %s belongs to both" +
                                         " string %d and %d") % \
                                         (mbId, oldNum, dom.string())

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

        print "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
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

    @staticmethod
    def getIcetopNum(strNum):
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
        if strNum in [41, 32, 24, 15, 35, 25, 8, 16]: return 209
        if strNum in [42, 43, 33, 34, 23, 51]: return 210
        raise ProcessError("Could not find icetop hub for string %d" % strNum)

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

class DefaultDomGeometryReader(XMLParser):

    @classmethod
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

        dom = DomGeometry(stringNum, pos, id, name, prod, chanId, x, y, z)
        dom.validate()

        return dom

    @classmethod
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

    @classmethod
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

        geom = DefaultDomGeometry(translateDoms)
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

        # clean up XML objects
        dom.unlink()

        return geom


class DomsTxtReader(object):
    @staticmethod
    def parse(fileName=None, geom=None):
        if fileName is None:
            fileName = os.path.join(metaDir, "config", "doms.txt")

        if not os.path.exists(fileName):
            raise BadFileError("Cannot read doms.txt file \"%s\"" %
                               fileName)

        fd = open(fileName, "r")

        newGeom = geom is None
        if newGeom:
            geom = DefaultDomGeometry()

        for line in fd:
            line = line.rstrip()
            if len(line) == 0:
                continue

            #(id, prodId, name, loc, desc) = re.split("\s+", line, 4)
            (loc, prodId, name, id) = re.split("\s+", line, 3)
            if id == "mbid":
                continue

            try:
                (strStr, posStr) = re.split("-", loc)
                strNum = int(strStr)
                pos = int(posStr)
            except:
                print >>sys.stderr, "Bad location \"%s\" for DOM \"%s\"" % \
                    (loc, prodId)
                continue

            geom.addString(strNum, errorOnMulti=False)

            if newGeom:
                oldDom = None
            else:
                oldDom = geom.getDom(strNum, pos)

            if oldDom is None:
                dom = DomGeometry(strNum, pos, id, name, prodId)
                dom.validate()

                geom.addDom(dom)

        return geom


class NicknameReader(object):
    @staticmethod
    def parse(fileName=None, geom=None):
        if fileName is None:
            fileName = os.path.join(metaDir, "config", "nicknames.txt")

        if not os.path.exists(fileName):
            raise BadFileError("Cannot read nicknames file \"%s\"" %
                               fileName)

        fd = open(fileName, "r")

        newGeom = geom is None
        if newGeom:
            geom = DefaultDomGeometry()

        for line in fd:
            line = line.rstrip()
            if len(line) == 0:
                continue

            (id, prodId, name, loc, desc) = re.split("\s+", line, 4)
            if id == "mbid":
                continue

            try:
                (strStr, posStr) = re.split("-", loc)
                strNum = int(strStr)
                pos = int(posStr)
            except:
                print >>sys.stderr, "Bad location \"%s\" for DOM \"%s\"" % \
                    (loc, prodId)
                continue

            geom.addString(strNum, errorOnMulti=False)

            if newGeom:
                oldDom = None
            else:
                oldDom = geom.getDom(strNum, pos)

            if oldDom is not None:
                oldDom.setDesc(desc)
            else:
                dom = DomGeometry(strNum, pos, id, name, prodId)
                dom.validate()

                geom.addDom(dom)

        return geom

if __name__ == "__main__":
    # read in default-dom-geometry.xml
    #defDomGeom = DefaultDomGeometryReader.parse()

    defDomGeom = DefaultDomGeometryReader.parse()

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    defDomGeom.rewrite()

    # dump the new default-dom-geometry data to sys.stdout
    defDomGeom.dump()
