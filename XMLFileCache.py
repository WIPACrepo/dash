#!/usr/bin/env python

import os

from DAQConfigExceptions import DAQConfigException
from xml.dom import minidom
from xmlparser import XMLBadFileError, XMLError, XMLFormatError


class XMLFileCacheException(DAQConfigException):
    pass


class XMLFileCache(object):
    "Cached file"
    CACHE = {}

    @staticmethod
    def buildPath(dirname, name):
        fileName = os.path.join(dirname, name)
        if not fileName.endswith(".xml"):
            fileName += ".xml"
        if not os.path.exists(fileName):
            return None
        return fileName

    @classmethod
    def load(cls, cfgName, configDir, strict=True):
        "Load the XML file"

        fileName = cls.buildPath(configDir, cfgName)
        if fileName is None:
            raise XMLBadFileError("'%s' not found in directory %s" %
                                  (cfgName, configDir))

        try:
            fileStat = os.stat(fileName)
        except OSError:
            raise XMLBadFileError(fileName)

        # Optimize by looking up pre-parsed configurations:
        if fileName in cls.CACHE:
            if cls.CACHE[fileName][0] == fileStat.st_mtime:
                return cls.CACHE[fileName][1]

        try:
            dom = minidom.parse(fileName)
        except Exception as e:
            raise XMLFormatError("Couldn't parse \"%s\": %s" %
                                 (fileName, str(e)))
        except KeyboardInterrupt:
            raise XMLFormatError("Couldn't parse \"%s\": KeyboardInterrupt" %
                                 fileName)

        try:
            data = cls.parse(dom, configDir, cfgName, strict)
        except XMLError:
            from exc_string import exc_string
            raise XMLFormatError("%s: %s" % (fileName, exc_string()))
        except KeyboardInterrupt:
            raise XMLFormatError("Couldn't parse \"%s\": KeyboardInterrupt" %
                                 fileName)

        cls.CACHE[fileName] = (fileStat.st_mtime, data)
        return data

    @classmethod
    def parse(cls, dom, configDir, fileName, strict=True):
        raise NotImplementedError("parse() method has not been" +
                                  " implemented for %s" % cls)
