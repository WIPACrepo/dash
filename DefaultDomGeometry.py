#!/usr/bin/env python
#
# Rewrite the default-dom-geometry file from 64 DOMs per in-ice string to
# 60 DOMs per in-ice string and 32 DOMs per icetop hub and print the
# result to sys.stdout

import os, re, sys, traceback

from xml.dom import minidom, Node

class ProcessError(Exception): pass
class BadFileError(Exception): pass

class Dom(object):
    "Data for a single DOM"
    def __init__(self, string, pos=None):
        self.prevString = None
        self.string = string
        self.pos = pos

        self.id = None
        self.name = None
        self.prod = None
        self.chanId = None

        self.x = None
        self.y = None
        self.z = None

        self.desc = None

        self.origOrder = None

    def __cmp__(self, other):
        if self.origOrder is None:
            if other.origOrder is not None:
                return -1
        elif other.origOrder is None:
            return 1
        elif self.origOrder != other.origOrder:
            return self.origOrder - other.origOrder

        if self.string is None:
            if other.string is not None:
                return -1
        elif other.string is None:
            return 1
        elif self.string != other.string:
            return self.string - other.string

        if self.prevString is None:
            if other.prevString is not None:
                return -1
        elif other.prevString is None:
            return 1
        elif self.prevString != other.prevString:
            return self.prevString - other.prevString

        if self.pos is None:
            if other.pos is not None:
                return -1
        elif other.pos is None:
            return 1
        elif self.pos != other.pos:
            return self.pos - other.pos

        return 0

    def __str__(self):
        return '%s[%s] %02d-%02d' % (self.id, self.name, self.string, self.pos)

    def finish(self):
        if self.pos is None:
            if self.name is not None:
                dname = self.name
            elif id is not None:
                dname = self.id
            else:
                raise ProcessError('Blank DOM entry in string %d' % self.string)

            raise ProcessError('DOM %s is missing ID in string %s' % dname)

        if self.id is None:
            raise ProcessError('DOM pos %d is missing ID in string %s' %
                               (self.pos, self.string))

        if self.name is None:
            raise ProcessError('DOM %s is missing ID in string %s' % self.id)

    def getDesc(self):
        if self.desc is None:
            return "-"
        return self.desc

    def getId(self): return self.id
    def getName(self): return self.name
    def getPos(self): return self.pos
    def getProdId(self): return self.prod
    def getString(self): return self.string

    def setDesc(self, desc):
        if desc is None or desc == "-" or desc == "NULL":
            self.desc = None
        else:
            self.desc = desc

    def setId(self, id): self.id = id
    def setChannelId(self, chanId): self.chanId = chanId
    def setName(self, name): self.name = name
    def setOriginalOrder(self, num): self.origOrder = num
    def setPos(self, pos): self.pos = pos
    def setProdId(self, prod): self.prod = prod

    def setString(self, strNum):
        self.prevString = self.string
        self.string = strNum

    def setX(self, x): self.x = x
    def setY(self, y): self.y = y
    def setZ(self, z): self.z = z

class DefaultDomGeometry(object):
    def __init__(self):
        self.__stringToDom = {}
        #self.__domIdToDom = {}

    def addDom(self, stringNum, dom):
        self.__stringToDom[stringNum].append(dom)

        #mbId = dom.id
        #if self.__domIdToDom.has_key(mbId):
        #    oldNum = self.__domIdToDom[mbId].getString()
        #    if oldNum != stringNum:
        #        print >>sys.stderr, ('DOM %s belongs to both' +
        #                             ' string %d and %d') % \
        #                             (mbId, oldNum, stringNum)

        #self.__domIdToDom[mbId] = dom

    def addString(self, stringNum, errorOnMulti=True):
        if not self.__stringToDom.has_key(stringNum):
            self.__stringToDom[stringNum] = []
        elif errorOnMulti:
            errMsg = 'Found multiple entries for string %d' % stringNum
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

        print '<?xml version="1.0"?>'
        print '<domGeometry>'
        for s in strList:
            domList = self.__stringToDom[s]
            if len(domList) == 0:
                continue

            print '   <string>'
            print '      <number>%02d</number>' % s

            domList.sort()
            for dom in domList:
                print '     <dom>'
                if dom.pos is not None:
                    if s % 1000 == 1:
                        print '        <position>%d</position>' % dom.pos
                    else:
                        print '        <position>%02d</position>' % dom.pos
                if dom.chanId is not None:
                    print '        <channelId>%s</channelId>' % dom.chanId
                if dom.id is not None:
                    print '        <mainBoardId>%s</mainBoardId>' % dom.id
                if dom.name is not None:
                    print '        <name>%s</name>' % dom.name
                if dom.prod is not None:
                    print '        <productionId>%s</productionId>' % dom.prod
                if dom.x is not None:
                    if dom.x == 0.0:
                        xStr = "0.0"
                    else:
                        xStr = "%4.2f" % dom.x
                    print '        <xCoordinate>%s</xCoordinate>' % xStr
                if dom.y is not None:
                    if dom.y == 0.0:
                        yStr = "0.0"
                    else:
                        yStr = "%4.2f" % dom.y
                    print '        <yCoordinate>%s</yCoordinate>' % yStr
                if dom.z is not None:
                    if dom.z == 0.0:
                        zStr = "0.0"
                    else:
                        zStr = "%4.2f" % dom.z
                    print '        <zCoordinate>%s</zCoordinate>' % zStr
                print '     </dom>'

            print '   </string>'
        print '</domGeometry>'

    def dumpNicknames(self):
        "Dump the DOM data in nicknames.txt format"
        allDoms = []
        for s in self.__stringToDom:
            for dom in self.__stringToDom[s]:
                allDoms.append(dom)

        allDoms.sort(cmp=lambda x,y : cmp(x.getName(), y.getName()))

        print "mbid\tthedomid\tthename\tlocation\texplanation"
        for dom in allDoms:
            name = dom.getName().encode("iso-8859-1")

            try:
                desc = dom.getDesc().encode("iso-8859-1")
            except:
                desc = "-"

            print "%s\t%s\t%s\t%02d-%02d\t%s" % \
                (dom.getId(), dom.getProdId(), name, dom.getString(),
                 dom.getPos(), desc)

    def getDom(self, strNum, pos):
        if self.__stringToDom.has_key(strNum):
            for dom in self.__stringToDom[strNum]:
                if dom.getPos() == pos:
                    return dom

        return None
        
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
        raise ProcessError('Could not find icetop hub for string %d' % strNum)
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
                if dom.pos < 1 or dom.pos > 64:
                    print >>sys.stderr, "Bad position %d for %s" % \
                        (dom.pos, dom)
                else:
                    if baseNum < 200:
                        pos = dom.pos - 1
                    elif dom.origOrder is not None:
                        pos = dom.origOrder
                    dom.chanId = (baseNum * 64) + pos

                if (baseNum <= 80 and dom.pos <= 60) or \
                        (baseNum > 200 and dom.pos > 60) or \
                        (not rewriteOldIcetop and baseNum > 80 and \
                             dom.pos > 60):
                    pass
                else:
                    if dom.pos <= 60:
                        it = baseNum
                    elif rewriteOldIcetop and baseNum > 80 and baseNum < 200:
                        it = baseNum % 10 + 200
                    else:
                        try:
                            it = DefaultDomGeometry.getIcetopNum(s)
                        except ProcessError:
                            print >>sys.stderr, \
                                "Dropping %d-%d: Unknown icetop hub" % \
                                (s, dom.pos)
                            self.deleteDom(s, dom)
                            it = s

                    if it != baseNum:
                        self.deleteDom(s, dom)

                        it = (s / 1000) * 1000 + (it % 1000)
                        dom.setString(it)

                        self.addString(it, errorOnMulti=False)
                        self.addDom(it, dom)

class XMLParser(object):
    def getChildNode(cls, node, childName, hasAttr=False, hasKids=True):
        """
        Get the child node which has the specified name.
        Will also verify that the child node does not have any attributes
        and has its own child nodes -- this check can be changed by setting
        'hasAttr' or 'hasKids' to the appropriate boolean value, or disabled
        by setting the value to None
        """
        nodeName = '<%s>' % str(node.nodeName)
        if nodeName == '<#document>':
            nodeName = 'top-level'

        if node.childNodes is None or len(node.childNodes) == 0:
            raise ProcessError('No %s child nodes' % nodeName)

        # find first child node which matches the specified name
        #
        child = None
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE and kid.nodeName == childName:
                if child is not None:
                    raise ProcessError('Found multiple copies of %s node <%s>' %
                                       (nodeName, kid.nodeName))
                child = kid
                continue

            raise ProcessError('Found unknown %s node <%s>' %
                               (nodeName, kid.nodeName))

        if child is None:
            raise ProcessError('No <%s> child node for %s' %
                               (childName, nodeName))

        if hasAttr is not None:
            if hasAttr:
                if child.attributes is None or len(child.attributes) == 0:
                    raise ProcessError('<%s> node has no attributes' %
                                       childName)
            elif child.attributes is not None and len(child.attributes) > 0:
                raise ProcessError('<%s> node has unexpected attributes' %
                                   childName)

        if hasKids is not None:
            if hasKids:
                if child.childNodes is None or len(child.childNodes) == 0:
                    raise ProcessError('<%s> node has no children' % childName)
            elif child.childNodes is not None and len(child.childNodes) > 0:
                raise ProcessError('<%s> node has unexpected children' %
                                   childName)

        return child
    getChildNode = classmethod(getChildNode)

    def getChildText(cls, node):
        "Return the text from this node's child"
        nodeName = '<%s>' % str(node.nodeName)
        if nodeName == '<#document>':
            nodeName = 'top-level'

        if node.childNodes is None or len(node.childNodes) == 0:
            raise ProcessError('No %s child nodes' % nodeName)

        text = None
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                if text is not None:
                    raise ProcessError('Found multiple %s text nodes' %
                                       nodeName)
                text = kid.nodeValue
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                raise ProcessError('Unexpected %s child <%s>' %
                                   (node.nodeName, kid.nodeName))

            raise ProcessError('Found unknown %s node <%s>' %
                               (nodeName, kid.nodeName))

        if text is None:
            raise ProcessError('No text child node for %s' % nodeName)

        return text
    getChildText = classmethod(getChildText)

class DefaultDomGeometryReader(XMLParser):
    def __parseDom(self, stringNum, domNode):
        "Extract a single DOM's data from the default-dom-geometry XML tree"
        if domNode.attributes is not None and len(domNode.attributes) > 0:
            raise ProcessError('<%s> node has unexpected attributes' %
                               domNode.nodeName)

        dom = Dom(stringNum)

        for kid in domNode.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == 'position':
                    dom.setPos(int(self.getChildText(kid)))
                elif kid.nodeName == 'mainBoardId':
                    dom.setId(self.getChildText(kid))
                elif kid.nodeName == 'channelId':
                    dom.setChannelId(int(self.getChildText(kid)))
                elif kid.nodeName == 'name':
                    dom.setName(self.getChildText(kid))
                elif kid.nodeName == 'productionId':
                    dom.setProdId(self.getChildText(kid))
                elif kid.nodeName == 'xCoordinate':
                    dom.setX(float(self.getChildText(kid)))
                elif kid.nodeName == 'yCoordinate':
                    dom.setY(float(self.getChildText(kid)))
                elif kid.nodeName == 'zCoordinate':
                    dom.setZ(float(self.getChildText(kid)))
                else:
                    raise ProcessError('Unexpected %s child <%s>' %
                                       (domNode.nodeName, kid.nodeName))
                continue

            raise ProcessError('Found unknown %s node <%s>' %
                               (node.nodeName, kid.nodeName))

        dom.finish()

        return dom

    def __parseStringGeometry(self, ddg, node):
        "Extract data from a default-dom-geometry <string> node tree"
        if node.attributes is not None and len(node.attributes) > 0:
            raise ProcessError('<%s> node has unexpected attributes' %
                               node.nodeName)

        stringNum = None
        origOrder = 0

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == 'number':
                    stringNum = int(self.getChildText(kid))
                    ddg.addString(stringNum)
                    origOrder = 0
                elif kid.nodeName == 'dom':
                    if stringNum is None:
                        raise ProcessError('Found <dom> before <number>' +
                                           ' under <string>')
                    dom = self.__parseDom(stringNum, kid)
                    dom.setOriginalOrder(origOrder)
                    origOrder += 1

                    ddg.addDom(stringNum, dom)
                else:
                    raise ProcessError('Unexpected %s child <%s>' %
                                       (node.nodeName, kid.nodeName))
                continue

            raise ProcessError('Found unknown %s node <%s>' %
                               (node.nodeName, kid.nodeName))

        if stringNum is None:
            raise ProcessError('String is missing number')

    def read(self, fileName=None):
        if fileName is None:
            if not os.environ.has_key('PDAQ_HOME'):
                raise ProcessError('No PDAQ_HOME environment variable')

            fileName = os.path.join(os.environ['PDAQ_HOME'], 'config',
                                    'default-dom-geometry.xml')

        if not os.path.exists(fileName):
            raise BadFileError('Cannot read default dom geometry file "%s"' %
                               fileName)

        try:
            dom = minidom.parse(fileName)
        except Exception, e:
            raise ProcessError("Couldn't parse \"%s\": %s" % (fileName, str(e)))

        ddg = DefaultDomGeometry()

        geom = self.getChildNode(dom, 'domGeometry')

        for kid in geom.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == 'string':
                    self.__parseStringGeometry(ddg, kid)
                else:
                    raise ProcessError('Unknown domGeometry node <%s>' %
                                       kid.nodeName)
                continue

            raise ProcessError('Found unknown domGeometry node <%s>' %
                               kid.nodeName)

        return ddg

class NicknameReader(object):
    def read(self, fileName=None, geom=None):
        if fileName is None:
            if not os.environ.has_key('PDAQ_HOME'):
                raise ProcessError('No PDAQ_HOME environment variable')

            fileName = os.path.join(os.environ['PDAQ_HOME'], 'config',
                                    'nicknames.txt')

        if not os.path.exists(fileName):
            raise BadFileError('Cannot read nicknames file "%s"' %
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
                dom = Dom(strNum, pos)
                dom.setId(id)
                dom.setProdId(prodId)
                dom.setName(name)
                dom.setDesc(desc)
                dom.finish()

                geom.addDom(strNum, dom)

        return geom

if __name__ == "__main__":
    # read in default-dom-geometry.xml
    #defDomGeom = DefaultDomGeometryReader().read()

    defDomGeom = DefaultDomGeometryReader().read()

    # rewrite the 64-DOM strings to 60 DOM strings plus 32 DOM icetop hubs
    defDomGeom.rewrite()

    # dump the new default-dom-geometry data to sys.stdout
    defDomGeom.dump()
