#!/usr/bin/env python

import os

from xml.dom import minidom
from DefaultDomGeometry import XMLError

class XMLFileCacheException(Exception): pass
class XMLFileNotFound(XMLFileCacheException): pass
class XMLFileParseError(XMLFileCacheException): pass

class XMLData(object):
    def __init__(self, data, modTime):
        self.__data = data
        self.__modTime = modTime

    def data(self): return self.__data
    def modTime(self): return self.__modTime

class XMLFileCache(object):
    "Cached file"
    CACHE = {}

    def buildPath(cls, dir, name):
        fileName = os.path.join(dir, name)
        if not fileName.endswith(".xml"):
            fileName += ".xml"
        if not os.path.exists(fileName):
            return None
        return fileName
    buildPath = classmethod(buildPath)

    def load(cls, cfgName, configDir, strict=True):
        "Load the XML file"

        fileName = cls.buildPath(configDir, cfgName)
        if fileName is None:
            raise XMLFileNotFound("%s in directory %s" % (cfgName, configDir))

        try:
            fileStat = os.stat(fileName)
        except OSError:
            raise XMLFileNotFound(fileName)

        # Optimize by looking up pre-parsed configurations:
        if cls.CACHE.has_key(fileName):
            if cls.CACHE[fileName].modTime() == fileStat.st_mtime:
                return cls.CACHE[fileName].data()

        try:
            dom = minidom.parse(fileName)
        except Exception, e:
            raise XMLFileParseError("Couldn't parse \"%s\": %s" %
                                    (fileName, str(e)))
        except KeyboardInterrupt:
            raise XMLFileParseError(("Couldn't parse \"%s\":" +
                                     " KeyboardInterrupt") % fileName)

        try:
            data = cls.parse(dom, configDir, cfgName, strict)
        except XMLError, xe:
            raise XMLFileParseError("%s: %s" % (fileName, str(xe)))
        except KeyboardInterrupt:
            raise XMLFileParseError(("Couldn't parse \"%s\":" +
                                     " KeyboardInterrupt") % fileName)

        cls.CACHE[fileName] = XMLData(data, fileStat.st_mtime)
        return data

        return None
    load = classmethod(load)

    def parse(cls, dom, configDir, fileName, strict=True):
        raise NotImplementedError("parse() method has not been" +
                                     " implemented for %s" % cls)
    parse = classmethod(parse)
