#!/usr/bin/env python
#
# Classes to support pDAQ's default-dom-geometry.xml file which is the
# "database" of all static DOM information


import os
import re
import sys

from xml.dom import minidom, Node
from xmlparser import XMLBadFileError, XMLFormatError, XMLParser

from locate_pdaq import find_pdaq_config


def compute_channel_id(string, pos):
    """
    Compute the channel ID for a DOM's (string, position) information
    """
    if pos < 1 or pos > 66:
        raise Exception("Impossible position %d" % pos)

    kstring = string % 1000
    if kstring < 0 or kstring > 86:
        raise Exception("Impossible string %d" % string)

    if pos > 64:
        return (6000 + ((kstring - 1) * 2) + (pos - 65)) & 0xffff

    return ((kstring * 64) + (pos - 1)) & 0xffff


class DomGeometryException(Exception):
    pass


class DomGeometry(object):
    "maximum possible DOM position"
    MAX_POSITION = 66
    "maximum SPS string number"
    MAX_STRING = 86
    "maximum possible channel ID"
    MAX_CHAN_ID = 1000 * MAX_POSITION
    "start of range for icetop hub IDs"
    BASE_ICETOP_HUB_NUM = 200

    "Data for a single DOM"
    def __init__(self, string, pos, mbid, name, prod, chanId=None,
                 x=None, y=None, z=None):
        self.__string = string
        self.__pos = pos
        self.__mbid = mbid
        self.__name = name
        self.__prod = prod
        self.__chanId = chanId
        self.__x = x
        self.__y = y
        self.__z = z

        self.__desc = None

        self.__origOrder = None
        self.__origString = None

    def __cmp__(self, other):
        if self.__string > self.MAX_STRING:
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

        if self.__origString is None:
            if other.__origString is not None:
                return -1
        elif other.__origString is None:
            return 1
        elif self.__origString != other.__origString:
            return self.__origString - other.__origString

        if self.__pos is None:
            if other.__pos is not None:
                return -1
        elif other.__pos is None:
            return 1
        elif self.__pos != other.__pos:
            return self.__pos - other.__pos

        return 0

    def __str__(self):
        if self.__origString is not None:
            strnum = self.__origString
        else:
            strnum = self.__string
        return "%s[%s] %02d-%02d" % \
            (self.__mbid, self.__name, strnum, self.__pos)

    def channelId(self):
        return self.__chanId

    def desc(self):
        if self.__desc is None:
            return "-"
        return self.__desc

    @property
    def is_icetop(self):
        return self.__pos >= 61 and self.__pos <= 64

    @property
    def is_inice(self):
        return self.__pos >= 11 and self.__pos <= 60

    @property
    def is_real_dom(self):
        return self.__string >= 1 and self.__string <= 86 and \
            self.__pos >= 1 and self.__pos <= 64

    @property
    def is_scintillator(self):
        return self.__string >= 1 and self.__string <= 86 and \
            self.__pos >= 65 and self.__pos <= 66

    def location(self):
        if self.__origString is not None:
            strNum = self.__origString
        else:
            strNum = self.__string
        return "%02d-%02d" % (strNum, self.__pos)

    def mbid(self):
        return self.__mbid

    @property
    def name(self):
        return self.__name

    def originalOrder(self):
        return self.__origOrder

    def originalString(self):
        return self.__origString

    def pos(self):
        return self.__pos

    def prodId(self):
        return self.__prod

    def rewrite(self, verbose=False, rewriteOldIcetop=False):
        baseNum = self.__string % 1000

        if self.__pos < 1 or self.__pos > self.MAX_POSITION:
            if verbose:
                print >>sys.stderr, "Bad position %d for %s" % \
                      (self.__pos, self)
            return

        origStr = baseNum
        if self.__origString is not None:
            origStr = self.__origString

        if origStr <= self.MAX_STRING or self.__origOrder is not None:
            if self.__pos > 0 and origStr <= self.MAX_STRING:
                newChanId = compute_channel_id(origStr, self.__pos)
                if verbose and self.__chanId is not None and \
                   self.__chanId != newChanId:
                    print >>sys.stderr, \
                          "Rewriting %s channel ID from %s to %d" % \
                          (self.__name, self.__chanId, newChanId)
                self.__chanId = newChanId
            elif verbose and self.__chanId is None:
                print >>sys.stderr, "Not setting channel ID for %s" % \
                    self.__name

        changedString = False
        if (baseNum <= self.MAX_STRING and self.__pos <= 60) or \
           (baseNum > self.BASE_ICETOP_HUB_NUM and self.__pos > 60) or \
           (not rewriteOldIcetop and baseNum > self.MAX_STRING and
            self.__pos > 60):
            pass
        else:
            if self.__pos <= 60:
                it = baseNum
            elif rewriteOldIcetop and baseNum > self.MAX_STRING and \
                     baseNum < self.BASE_ICETOP_HUB_NUM:
                it = baseNum % 10 + self.BASE_ICETOP_HUB_NUM
            else:
                try:
                    it = DefaultDomGeometry.getIcetopNum(self.__string)
                except XMLFormatError:
                    it = self.__string

            if it != baseNum:
                it = (self.__string / 1000) * 1000 + (it % 1000)
                self.setString(it)
                changedString = True

        return changedString

    def setChannelId(self, chanId):
        if chanId > self.MAX_CHAN_ID:
            raise DomGeometryException("Bad channel ID %d for %s" %
                                       (chanId, self))
        self.__chanId = chanId

    def setDesc(self, desc):
        if desc is None or desc == "-" or desc == "NULL":
            self.__desc = None
        else:
            self.__desc = desc

    def setId(self, mbid):
        self.__mbid = mbid

    def setName(self, name):
        self.__name = name

    def setOriginalOrder(self, num):
        self.__origOrder = num

    def setOriginalString(self, num):
        self.__origString = num

    def setPos(self, pos):
        if pos < 1 or pos > self.MAX_POSITION:
            raise DomGeometryException("Bad position %d for %s" % (pos, self))
        self.__pos = pos

    def setProdId(self, prod):
        self.__prod = prod

    def setString(self, strNum):
        tmpNum = self.__string
        self.__string = strNum
        if self.__origString is not None:
            raise DomGeometryException(("Cannot overwrite original string %d" +
                                        " with %d for %s") %
                                       (self.__origString, tmpNum, self))
        self.__origString = tmpNum

    def setX(self, coord):
        self.__x = coord

    def setY(self, coord):
        self.__y = coord

    def setZ(self, coord):
        self.__z = coord

    def string(self):
        return self.__string

    def update(self, dom, verbose=False):
        "Copy missing info from DOM argument"
        if self.__mbid is None:
            self.__mbid = dom.__mbid
        elif verbose and dom.__string < self.BASE_ICETOP_HUB_NUM and \
             dom.__mbid is not None and self.__mbid != dom.__mbid:
            print >>sys.stderr, \
                  "Not changing DOM %s MBID from \"%s\" to \"%s\"" % \
                  (self, self.__mbid, dom.__mbid)

        if self.__name is None:
            self.__name = dom.__name
        elif verbose and dom.__string < self.BASE_ICETOP_HUB_NUM and \
             dom.__name is not None and self.__name != dom.__name:
            print >>sys.stderr, \
                  "Not changing DOM %s name from \"%s\" to \"%s\"" % \
                  (self, self.__name, dom.__name)

        if self.__prod is None:
            self.__prod = dom.__prod
        elif verbose and dom.__string < self.BASE_ICETOP_HUB_NUM and \
             dom.__prod is not None and self.__prod != dom.__prod:
            print >>sys.stderr, \
                  "Not changing DOM %s prodID from \"%s\" to \"%s\"" % \
                  (self, self.__prod, dom.__prod)

        if self.__chanId is None:
            self.__chanId = dom.__chanId
        elif verbose and dom.__string < self.BASE_ICETOP_HUB_NUM and \
             dom.__chanId is not None and self.__chanId != dom.__chanId:
            print >>sys.stderr, \
                  "Not changing DOM %s channel ID from %d to %d" % \
                  (self, self.__chanId, dom.__chanId)

        if self.__origString is None:
            self.__origString = dom.__origString
        elif verbose and dom.__origString is not None and \
             self.__origString != dom.__origString:
            print >>sys.stderr, \
                  "Not changing DOM %s original string from %d to %d" % \
                  (self, self.__origString, dom.__origString)

    def validate(self):
        if self.__pos is None:
            if self.__name is not None:
                dname = self.__name
            elif self.__mbid is not None:
                dname = self.__mbid
            else:
                raise XMLFormatError("Blank DOM entry")

            raise XMLFormatError("DOM %s is missing ID in string %s" %
                                 (dname, self.__string))
        if self.__mbid is None:
            raise XMLFormatError("DOM pos %d is missing MBID in string %s" %
                                 (self.__pos, self.__string))
        if self.__name is None:
            raise XMLFormatError("DOM %s is missing name in string %s" %
                                 (self.__mbid, self.__string))

    def x(self):
        return self.__x

    def y(self):
        return self.__y

    def z(self):
        return self.__z


class String(object):
    def __init__(self, num):
        self.__number = num
        self.__rack = None
        self.__partition = None
        self.__doms = []

    def add(self, dom):
        self.__doms.append(dom)

    def delete(self, dom):
        found = False
        for i in range(len(self.__doms)):
            cur = self.__doms[i]
            if dom.pos() <= 60 and dom.pos() == cur.pos():
                found = True
            elif dom.mbid() is not None and cur.mbid() is not None and \
                 dom.mbid() == cur.mbid():
                found = True
            elif dom.prodId() is not None and cur.prodId() is not None and \
                 dom.prodId() == cur.prodId():
                found = True

            if found:
                del self.__doms[i]
                return

        if dom.mbid() is not None or dom.name is not None:
            print >>sys.stderr, "Could not delete %s" % str(dom)

    @property
    def doms(self):
        return self.__doms[:]

    @property
    def number(self):
        return self.__number

    @property
    def partition(self):
        return self.__partition

    @property
    def rack(self):
        return self.__rack

    def setPartition(self, partition):
        if self.__partition is not None and self.__partition != partition:
            print >>sys.stderr, "Changing string %d partition %s to %s" % \
                  (self.__number, self.__partition, partition)
        self.__partition = partition

    def setRack(self, rack):
        if self.__rack is not None and self.__rack != rack:
            print >>sys.stderr, "Changing string %d rack %d to %d" % \
                (self.__number, self.__rack, rack)
        self.__rack = rack


class DefaultDomGeometry(object):
    FILENAME = "default-dom-geometry.xml"

    STRING_COMMENT = {
        2002: "MDFL3 DOMs",
        2012: "MDFL2 DOMs",
        2022: "ABSCAL DOMs",
    }

    def __init__(self, translateDoms=True):
        self.__strings = {}
        self.__translateDoms = translateDoms
        self.__domIdToDom = {}

    def __dumpCoordinate(self, out, axis, indent, value):
        name = axis + "Coordinate"

        vstr = "%3.2f" % value
        vstr = vstr.rstrip("0")
        if vstr.endswith("."):
            vstr += "0"

        print >>out, "%s<%s>%s</%s>" % (indent, name, vstr, name)

    def addDom(self, dom):
        self.__strings[dom.string()].add(dom)

        if self.__translateDoms:
            mbid = dom.mbid()
            if mbid is not None:
                if mbid in self.__domIdToDom:
                    oldNum = self.__domIdToDom[mbid].string()
                    if oldNum != dom.string():
                        print >>sys.stderr, ("DOM %s belongs to both" +
                                             " string %d and %d") % \
                                             (mbid, oldNum, dom.string())

                self.__domIdToDom[mbid] = dom

    def addString(self, stringNum, errorOnMulti=True):
        if stringNum not in self.__strings:
            self.__strings[stringNum] = String(stringNum)
        elif errorOnMulti:
            raise XMLFormatError("Found multiple entries for string %d" %
                                 stringNum)

    def deleteDom(self, stringNum, dom):
        if stringNum not in self.__strings:
            raise XMLFormatError("String %d does not exist" % stringNum)
        self.__strings[stringNum].delete(dom)

    def doms(self):
        "Convenience method to list all known DOMs"
        for domid in self.__domIdToDom:
            yield self.__domIdToDom[domid]

    def dump(self, out=sys.stdout):
        "Dump the string->DOM dictionary in default-dom-geometry format"
        strList = self.__strings.keys()
        strList.sort()

        indent = "  "
        domIndent = indent + indent + indent

        print >>out, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        print >>out, "<domGeometry>"
        for strnum in strList:
            domList = self.__strings[strnum].doms
            if len(domList) == 0:
                continue

            print >>out, "%s<string>" % indent
            if strnum in self.STRING_COMMENT:
                print >>out, "%s%s<!-- %s -->" % (indent, indent,
                                                  self.STRING_COMMENT[strnum])
            print >>out, "%s%s<number>%d</number>" % (indent, indent, strnum)

            if self.__strings[strnum].rack is not None:
                print >>out, "%s%s<rack>%d</rack>" % \
                    (indent, indent, self.__strings[strnum].rack)

            if self.__strings[strnum].partition is not None:
                print >>out, "%s%s<partition>%s</partition>" % \
                    (indent, indent, self.__strings[strnum].partition)

            domList.sort()
            for dom in domList:
                if dom.mbid() is None and dom.name is None and \
                   dom.prodId() is None:
                    continue
                print >>out, "%s%s<dom>" % (indent, indent)
                if dom.originalString() is not None and \
                   (dom.originalString() % 1000) < \
                   DomGeometry.BASE_ICETOP_HUB_NUM and \
                   dom.originalString() != dom.string():
                    print >>out, "%s<originalString>%d</originalString>" % \
                          (domIndent, dom.originalString())
                if dom.pos() is not None:
                    print >>out, "%s<position>%d</position>" % \
                          (domIndent, dom.pos())
                if dom.channelId() is not None:
                    print >>out, "%s<channelId>%d</channelId>" % \
                          (domIndent, dom.channelId())
                if dom.mbid() is not None:
                    print >>out, "%s<mainBoardId>%s</mainBoardId>" % \
                          (domIndent, dom.mbid())
                if dom.name is not None:
                    print >>out, "%s<name>%s</name>" % (domIndent, dom.name)
                if dom.prodId() is not None:
                    print >>out, "%s<productionId>%s</productionId>" % \
                          (domIndent, dom.prodId())
                if dom.x() is not None:
                    self.__dumpCoordinate(out, "x", domIndent, dom.x())
                if dom.y() is not None:
                    self.__dumpCoordinate(out, "y", domIndent, dom.y())
                if dom.z() is not None:
                    self.__dumpCoordinate(out, "z", domIndent, dom.z())
                print >>out, "%s%s</dom>" % (indent, indent)

            print >>out, "%s</string>" % indent
        print >>out, "</domGeometry>"

    def dumpNicknames(self, out=sys.stdout):
        "Dump the DOM data in nicknames.txt format"
        allDoms = []
        for strobj in self.__strings:
            allDoms += strobj.doms

        allDoms.sort(cmp=lambda x, y: cmp(x.name, y.name))

        print >>out, "mbid\tthedomid\tthename\tlocation\texplanation"
        for dom in allDoms:
            if dom.prodId() is None:
                continue
            if dom.string() >= 1000:
                continue

            name = dom.name.encode("iso-8859-1")

            try:
                desc = dom.desc().encode("iso-8859-1")
            except:
                desc = "-"

            if dom.originalString() is None:
                strNum = dom.string()
            else:
                strNum = dom.originalString()

            print >>out, "%s\t%s\t%s\t%02d-%02d\t%s" % \
                (dom.mbid(), dom.prodId(), name, strNum, dom.pos(), desc)

    def getDom(self, strNum, pos, prodId=None, origNum=None):
        if strNum not in self.__strings:
            return None

        for dom in self.__strings[strNum].doms:
            if dom.pos() == pos:
                if origNum is not None:
                    if dom.originalString() is not None and \
                       dom.originalString() == origNum:
                        return dom

                if prodId is not None:
                    if dom.prodId() == prodId:
                        return dom

                if prodId is None and origNum is None:
                    return dom

        return None

    def getDomIdToDomDict(self):
        "Get the DOM ID -> DOM object dictionary"
        return self.__domIdToDom

    @staticmethod
    def getIcetopNum(strNum):
        "Translate the in-ice string number to the corresponding icetop hub"
        if strNum % 1000 == 0 or strNum >= 2000:
            return strNum

        if strNum > 1000:
            return ((((strNum % 100) + 7)) / 8) + 1200

        # SPS map goes here

        if strNum in [46, 55, 56, 65, 72, 73, 77, 78]:
            return 201

        if strNum in [38, 39, 48, 58, 64, 66, 71, 74]:
            return 202

        if strNum in [30, 40, 47, 49, 50, 57, 59, 67]:
            return 203

        if strNum in [4, 5, 10, 11, 18, 20, 27, 36]:
            return 204

        if strNum in [45, 54, 62, 63, 69, 70, 75, 76]:
            return 205

        if strNum in [21, 29, 44, 52, 53, 60, 61, 68]:
            return 206

        if strNum in [2, 3, 6, 9, 12, 13, 17, 26]:
            return 207

        if strNum in [19, 28, 37]:
            return 208

        if strNum in [8, 15, 16, 24, 25, 32, 35, 41]:
            return 209

        if strNum in [23, 33, 34, 42, 43, 51]:
            return 210

        if strNum in [1, 7, 14, 22, 31, 79, 80, 81]:
            return 211

        raise XMLFormatError("Could not find icetop hub for string %d" %
                             strNum)

    def getDomsOnString(self, strnum):
        "Get the DOMs on the requested string"
        if strnum not in self.__strings:
            return None
        return self.__strings[strnum].doms

    def getPartitions(self):
        "Get the partition->string-number dictionary"
        partitions = {}
        for strnum, strobj in self.__strings.items():
            if strobj.partition is not None:
                if strobj.partition not in partitions:
                    partitions[strobj.partition] = []
                partitions[strobj.partition].append(strnum)
        return partitions

    def getStringsOnRack(self, racknum):
        "Get the string numbers for all strings on the requested rack"
        strings = []
        for strnum, strobj in self.__strings.items():
            if strobj.rack == racknum:
                strings.append(strnum)
        return strings

    def rewrite(self, verbose=False, rewriteOldIcetop=False):
        """
        Rewrite default-dom-geometry from 64 DOMs per string hub to
        60 DOMs per string hub and 32 DOMs per icetop hub
        """
        strList = self.__strings.keys()
        strList.sort()

        for strnum in strList:
            domList = self.__strings[strnum].doms

            for dom in domList:
                if dom.rewrite(verbose=verbose,
                               rewriteOldIcetop=rewriteOldIcetop):
                    self.__strings[strnum].delete(dom)

                    self.addString(dom.string(), errorOnMulti=False)
                    self.addDom(dom)

    def setPartition(self, stringNum, partition):
        if stringNum not in self.__strings:
            raise XMLFormatError("String %d does not exist" % stringNum)
        self.__strings[stringNum].setPartition(partition)

    def setRack(self, stringNum, rack):
        if stringNum not in self.__strings:
            raise XMLFormatError("String %d does not exist" % stringNum)
        self.__strings[stringNum].setRack(rack)

    def update(self, newDomGeom, verbose=False):
        "Copy missing string, DOM, or DOM info from 'newDomGeom'"
        keys = self.__strings.keys()

        for strnum in newDomGeom.__strings:
            if strnum not in keys:
                self.__strings[strnum] = newDomGeom.__strings[strnum]
                continue
            for nd in newDomGeom.__strings[strnum]:
                foundPos = False
                for dom in self.__strings[strnum]:
                    if dom.pos() == nd.pos():
                        foundPos = True
                        if dom.mbid() == nd.mbid():
                            dom.update(nd, verbose=verbose)
                if not foundPos:
                    self.addDom(nd)

    def validate(self):
        names = {}
        locs = {}

        strKeys = self.__strings.keys()
        strKeys.sort()

        for strNum in strKeys:
            for dom in self.__strings[strNum].doms:
                if dom.name not in names:
                    names[dom.name] = dom
                else:
                    print >>sys.stderr, "Found DOM \"%s\" at %s and %s" % \
                        (dom.name, dom.location(), names[dom.name].location())

                if dom.name.startswith("SIM") and \
                   dom.string() % 1000 >= 200 and dom.string() % 1000 < 299:
                    domnum = int(dom.name[3:])
                    origStr = ((domnum - 1) / 64) + 1001
                    if dom.originalString() is None:
                        dom.setOriginalString(origStr)
                    elif dom.originalString() != origStr:
                        print >>sys.stderr, \
                            "DOM %s \"%s\" should have origStr %d, not %d" % \
                            (dom.location(), dom.name, origStr,
                             dom.originalString())

                if dom.location() not in locs:
                    locs[dom.location()] = dom
                else:
                    print >>sys.stderr, "Position %s holds DOMS %s and %s" % \
                        (dom.location(), dom.name,
                         locs[dom.location()].name)

                if dom.originalString() is not None:
                    strNum = dom.originalString()
                else:
                    strNum = dom.string()

                if strNum % 1000 == 0:
                    # don't bother validating AMANDA entries
                    continue

                newId = compute_channel_id(strNum, dom.pos())
                if dom.channelId() is None:
                    if dom.pos() <= DomGeometry.MAX_POSITION:
                        print >> sys.stderr, \
                            "No channel ID for DOM %s \"%s\"" % \
                            (dom.location(), dom.name)
                elif newId != dom.channelId():
                    print >> sys.stderr, \
                        "DOM %s \"%s\" should have channel ID %d, not %d" % \
                        (dom.location(), dom.name, newId, dom.channelId())
                    dom.setChannelId(newId)


class DefaultDomGeometryReader(XMLParser):

    @classmethod
    def __parseDomNode(cls, stringNum, node):
        "Extract a single DOM's data from the default-dom-geometry XML tree"
        if node.attributes is not None and len(node.attributes) > 0:
            raise XMLFormatError("<%s> node has unexpected attributes" %
                                 node.nodeName)

        pos = None
        mbid = None
        name = None
        prod = None
        chanId = None
        x = None
        y = None
        z = None

        origStr = None

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "position":
                    pos = int(cls.getChildText(kid))
                elif kid.nodeName == "mainBoardId":
                    mbid = cls.getChildText(kid)
                elif kid.nodeName == "name":
                    name = cls.getChildText(kid)
                elif kid.nodeName == "productionId":
                    prod = cls.getChildText(kid)
                elif kid.nodeName == "channelId":
                    chanId = int(cls.getChildText(kid))
                elif kid.nodeName == "xCoordinate":
                    x = float(cls.getChildText(kid))
                elif kid.nodeName == "yCoordinate":
                    y = float(cls.getChildText(kid))
                elif kid.nodeName == "zCoordinate":
                    z = float(cls.getChildText(kid))
                elif kid.nodeName == "originalString":
                    origStr = int(cls.getChildText(kid))
                else:
                    raise XMLFormatError("Unexpected %s child <%s>" %
                                         (node.nodeName, kid.nodeName))
                continue

            raise XMLFormatError("Found unknown %s node <%s>" %
                                 (node.nodeName, kid.nodeName))

        dom = DomGeometry(stringNum, pos, mbid, name, prod, chanId, x, y, z)
        if origStr is not None:
            dom.setOriginalString(origStr)
        dom.validate()

        return dom

    @classmethod
    def __parseStringNode(cls, geom, node):
        "Extract data from a default-dom-geometry <string> node tree"
        if node.attributes is not None and len(node.attributes) > 0:
            raise XMLFormatError("<%s> node has unexpected attributes" %
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
                    if stringNum is not None:
                        raise XMLFormatError("Found multiple <number> nodes" +
                                             " under <string>")
                    stringNum = int(cls.getChildText(kid))
                    geom.addString(stringNum)
                    origOrder = 0
                elif kid.nodeName == "rack":
                    if stringNum is None:
                        raise XMLFormatError("Found <rack> before" +
                                             " <number> under <string>")
                    rack = int(cls.getChildText(kid))
                    geom.setRack(stringNum, rack)
                elif kid.nodeName == "partition":
                    if stringNum is None:
                        raise XMLFormatError("Found <partition> before" +
                                             " <number> under <string>")
                    geom.setPartition(stringNum, cls.getChildText(kid))
                elif kid.nodeName == "dom":
                    if stringNum is None:
                        raise XMLFormatError("Found <dom> before" +
                                             " <number> under <string>")
                    dom = cls.__parseDomNode(stringNum, kid)

                    dom.setOriginalOrder(origOrder)
                    origOrder += 1

                    geom.addDom(dom)
                else:
                    print >>sys.stderr, "Ignoring unknown %s child <%s>" % \
                        (node.nodeName, kid.nodeName)
                continue

            raise XMLFormatError("Found unknown %s node <%s>" %
                                 (node.nodeName, kid.nodeName))

        if stringNum is None:
            raise XMLFormatError("String is missing number")

    @classmethod
    def parse(cls, configDir=None, fileName=None, translateDoms=False):
        if configDir is None:
            configDir = find_pdaq_config()

        if fileName is None:
            fileName = os.path.join(configDir, DefaultDomGeometry.FILENAME)

        if not os.path.exists(fileName):
            raise XMLBadFileError("Cannot read default dom geometry file"
                                  " \"%s\"" % fileName)

        try:
            dom = minidom.parse(fileName)
        except Exception as e:
            raise XMLFormatError("Couldn't parse \"%s\": %s" %
                                 (fileName, str(e)))

        gList = dom.getElementsByTagName("domGeometry")
        if gList is None or len(gList) != 1:
            raise XMLFormatError("No <domGeometry> tag found in %s" % fileName)

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
                    raise XMLFormatError("Unknown domGeometry node <%s>" %
                                         kid.nodeName)
                continue

            raise XMLFormatError("Found unknown domGeometry node <%s>" %
                                 kid.nodeName)

        # clean up XML objects
        dom.unlink()

        return geom


class DomsTxtReader(object):
    "Read Mark Krasberg's doms.txt file"

    @staticmethod
    def parse(fileName=None, defDomGeom=None):
        "Parse a doms.txt file"
        if fileName is None:
            configDir = find_pdaq_config()
            fileName = os.path.join(configDir, "doms.txt")

        if not os.path.exists(fileName):
            raise XMLBadFileError("Cannot read doms.txt file \"%s\"" %
                                  fileName)

        with open(fileName, 'r') as fd:
            newGeom = defDomGeom is None
            if newGeom:
                defDomGeom = DefaultDomGeometry()

            for line in fd:
                line = line.rstrip()
                if len(line) == 0:
                    continue

                (loc, prodId, name, mbid) = re.split(r"\s+", line, 3)
                if mbid == "mbid":
                    continue

                try:
                    (strStr, posStr) = re.split("-", loc)
                    strNum = int(strStr)
                    pos = int(posStr)
                except:
                    print >> sys.stderr, ("Bad location \"%s\" "
                                          "for DOM \"%s\"") % \
                                          (loc, prodId)
                    continue

                if pos <= 60:
                    origStr = None
                else:
                    origStr = strNum
                    strNum = DefaultDomGeometry.getIcetopNum(origStr)

                defDomGeom.addString(strNum, errorOnMulti=False)

                if newGeom:
                    dom = None
                else:
                    dom = defDomGeom.getDom(strNum, pos, prodId)

                if dom is None:
                    dom = DomGeometry(strNum, pos, mbid, name, prodId)
                    dom.validate()

                    defDomGeom.addDom(dom)

                if origStr is not None:
                    if dom.originalString() is None or \
                            dom.originalString() != origStr:
                        dom.setOriginalString(origStr)

        return defDomGeom


class NicknameReader(object):
    "Read Mark Krasberg's nicknames.txt file"

    @staticmethod
    def parse(fileName=None, defDomGeom=None):
        if fileName is None:
            configDir = find_pdaq_config()
            fileName = os.path.join(configDir, "nicknames.txt")

        if not os.path.exists(fileName):
            raise XMLBadFileError("Cannot read nicknames file \"%s\"" %
                                  fileName)

        with open(fileName, 'r') as fd:
            newGeom = defDomGeom is None
            if newGeom:
                defDomGeom = DefaultDomGeometry()

            for line in fd:
                line = line.rstrip()
                if len(line) == 0:
                    continue

                (mbid, prodId, name, loc, desc) = re.split(r"\s+", line, 4)
                if mbid == "mbid":
                    continue

                try:
                    (strStr, posStr) = re.split("-", loc)
                    strNum = int(strStr)
                    pos = int(posStr)
                except:
                    print >> sys.stderr, ("Bad location \"%s\" "
                                          "for DOM \"%s\"") % \
                                          (loc, prodId)
                    continue

                if pos <= 60:
                    origStr = None
                else:
                    origStr = strNum
                    strNum = DefaultDomGeometry.getIcetopNum(origStr)

                defDomGeom.addString(strNum, errorOnMulti=False)

                if newGeom:
                    dom = None
                else:
                    dom = defDomGeom.getDom(strNum, pos, prodId)

                if dom is not None:
                    if desc != "-":
                        dom.setDesc(desc)
                else:
                    dom = DomGeometry(strNum, pos, mbid, name, prodId)
                    dom.validate()

                    defDomGeom.addDom(dom)

                if origStr is not None:
                    if dom.originalString() is None or \
                            dom.originalString() != origStr:
                        dom.setOriginalString(origStr)

        return defDomGeom


class GeometryFileReader(object):
    """Read IceCube geometry settings (from "Geometry releases" wiki page)"""

    @staticmethod
    def parse(fileName=None, defDomGeom=None, minCoordDiff=0.000001):
        "Parse text file containing IceCube geometry settings"

        if fileName is None:
            raise XMLBadFileError("No geometry file specified")

        if not os.path.exists(fileName):
            raise XMLBadFileError("Cannot read geometry file \"%s\"" %
                                  fileName)

        with open(fileName, 'r') as fd:
            newGeom = defDomGeom is None
            if newGeom:
                defDomGeom = DefaultDomGeometry()

            LINE_PAT = re.compile(r"^\s*(\d+)\s+(\d+)\s+(-*\d+\.\d+)" +
                                  r"\s+(-*\d+\.\d+)\s+(-*\d+\.\d+)\s*$")

            linenum = 0
            for line in fd:
                line = line.rstrip()
                linenum += 1

                if len(line) == 0:
                    continue

                m = LINE_PAT.match(line)
                if not m:
                    print >>sys.stderr, "Bad geometry line %d: %s" % (linenum,
                                                                      line)
                    continue

                strStr = m.group(1)
                posStr = m.group(2)
                xStr = m.group(3)
                yStr = m.group(4)
                zStr = m.group(5)

                try:
                    strNum = int(strStr)
                except:
                    print >> sys.stderr, "Bad string \"%s\" on line %d" % \
                        (strStr, linenum)
                    continue

                try:
                    pos = int(posStr)
                except:
                    print >> sys.stderr, "Bad position \"%s\" on line %d" % \
                        (posStr, linenum)
                    continue

                coords = []
                for cStr in (xStr, yStr, zStr):
                    try:
                        coords.append(float(cStr))
                    except:
                        if len(coords) == 0:
                            cname = "x"
                        elif len(coords) == 1:
                            cname = "y"
                        else:
                            cname = "z"
                        print >> sys.stderr, \
                            "Bad %s coord \"%s\" on line %d" % \
                            (cname, cStr, linenum)
                        break

                if len(coords) != 3:
                    continue

                if pos <= 60:
                    origStr = None
                else:
                    origStr = strNum
                    strNum = DefaultDomGeometry.getIcetopNum(origStr)

                defDomGeom.addString(strNum, errorOnMulti=False)

                if newGeom:
                    dom = None
                else:
                    dom = defDomGeom.getDom(strNum, pos, origNum=origStr)

                if dom is None:
                    dom = DomGeometry(strNum, pos, None, None, None)

                    defDomGeom.addDom(dom)

                if origStr is not None:
                    if dom.originalString() is None or \
                            dom.originalString() != origStr:
                        dom.setOriginalString(origStr)

                (x, y, z) = coords

                if dom.x() is None or \
                   (minCoordDiff is not None and
                    abs(dom.x() - x) > minCoordDiff):
                    dom.setX(x)
                if y is not None:
                    if dom.y() is None or \
                       (minCoordDiff is not None and
                        abs(dom.y() - y) > minCoordDiff):
                        dom.setY(y)
                if z is not None:
                    if dom.z() is None or \
                       (minCoordDiff is not None and
                        abs(dom.z() - z) > minCoordDiff):
                        dom.setZ(z)

        return defDomGeom

if __name__ == "__main__":
    import argparse

    op = argparse.ArgumentParser()
    op.add_argument("-f", "--file", dest="inputFile",
                    help="Name of input file")
    op.add_argument("-o", "--output", dest="outputFile",
                    help="Name of file where revised XML file will be written")

    args = op.parse_args()

    # read in default-dom-geometry.xml
    defDomGeom = DefaultDomGeometryReader.parse(fileName=args.inputFile)

    # validate everything
    defDomGeom.validate()

    # dump the new default-dom-geometry data
    if args.outputFile is not None:
        with open(args.outputFile, "w") as fd:
            defDomGeom.dump(fd)
