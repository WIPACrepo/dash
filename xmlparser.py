#!/usr/bin/env python


import os

from xml.dom import Node


class XMLError(Exception):
    pass


class XMLFormatError(XMLError):
    pass


class XMLBadFileError(XMLError):
    pass


class XMLParser(object):

    @staticmethod
    def buildPath(configDir, configName, suffix='.xml'):
        fileName = os.path.join(configDir, configName)
        if os.path.exists(fileName):
            return fileName
        if not fileName.endswith(suffix):
            fileName += suffix
            if os.path.exists(fileName):
                return fileName
        return None

    @classmethod
    def getAttr(cls, node, attrName, defaultVal=None):
        "Return the text from this node's attribute"

        # NOTE: node.attributes doesn't support "attrName in node.attributes"
        if node.attributes is not None and \
           node.attributes.has_key(attrName):
            # return named attribute value
            return node.attributes[attrName].value

        return defaultVal

    @classmethod
    def getChildNodes(cls, node, name):
        if node.childNodes is not None:
            for kid in node.childNodes:
                if kid.nodeType == Node.ELEMENT_NODE and kid.nodeName == name:
                    yield kid

    @classmethod
    def getChildText(cls, node, strict=False):
        "Return the text from this node's child"

        if strict and (node.childNodes is None or len(node.childNodes) == 0):
            raise XMLFormatError("No %s child nodes" %
                                 cls.getNodeName(node))

        text = None
        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                if text is not None:
                    raise XMLFormatError("Found multiple %s text nodes" %
                                         cls.getNodeName(node))
                text = kid.nodeValue
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if strict:
                if kid.nodeType == Node.ELEMENT_NODE:
                    raise XMLFormatError("Unexpected %s child <%s>" %
                                         (cls.getNodeName(node),
                                          cls.getNodeName(kid)))

                raise XMLFormatError("Found unknown %s node <%s>" %
                                     (cls.getNodeName(node),
                                      cls.getNodeName(kid)))

        if strict and text is None:
            raise XMLFormatError("No text child node for %s" %
                                 cls.getNodeName(node))

        return text

    @classmethod
    def getNode(cls, node, name):
        """Get single subnode named 'name'"""
        kids = node.getElementsByTagName(name)
        if len(kids) < 1:
            return None

        if len(kids) > 1:
            raise XMLFormatError('Multiple <%s> nodes found' % name)

        return kids[0]

    @classmethod
    def getNodeName(cls, node):
        nodeName = '<%s>' % str(node.nodeName)
        if nodeName == '<#document>':
            nodeName = 'top-level'
        return nodeName

    @classmethod
    def getValue(cls, node, name, defaultVal=None, strict=False):
        """
        Get text value of either attribute (<node name=xxx/>)
        or subnode (<node><name>xxx</name></node>).  If neither is found,
        return defaultVal
        """
        attrVal = cls.getAttr(node, name)
        if attrVal is not None:
            # return named attribute value
            return attrVal

        kids = node.getElementsByTagName(name)
        if len(kids) < 1:
            # if no named attribute or node, return default value
            return defaultVal

        if len(kids) > 1:
            raise XMLFormatError('Multiple <%s> nodes found' % name)

        val = cls.getChildText(kids[0], strict=strict)
        if val is None:
            return defaultVal

        return val

    @staticmethod
    def parseBooleanString(valstr):
        "Return None if the value is not a valid boolean value"
        if valstr is None:
            return None

        lstr = valstr.lower()
        if lstr == "true" or lstr == "yes":
            return True
        if lstr == "false" or lstr == "no":
            return False
        try:
            val = int(valstr)
            return val == 0
        except:
            pass

        return None
