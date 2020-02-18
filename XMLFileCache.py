#!/usr/bin/env python

import os

from xml.dom import minidom
from xmlparser import XMLBadFileError, XMLError, XMLFormatError

from DAQConfigExceptions import DAQConfigException


class XMLFileCacheException(DAQConfigException):
    pass


class XMLFileCache(object):
    "Cached file"
    CACHE = {}

    @staticmethod
    def build_path(dirname, name):
        file_name = os.path.join(dirname, name)
        if not file_name.endswith(".xml"):
            file_name += ".xml"
        if not os.path.exists(file_name):
            return None
        return file_name

    @classmethod
    def load(cls, cfg_name, config_dir, strict=True):
        "Load the XML file"

        file_name = cls.build_path(config_dir, cfg_name)
        if file_name is None:
            raise XMLBadFileError("'%s' not found in directory %s" %
                                  (cfg_name, config_dir))

        try:
            file_stat = os.stat(file_name)
        except OSError:
            raise XMLBadFileError(file_name)

        # Optimize by looking up pre-parsed configurations:
        if file_name in cls.CACHE:
            if cls.CACHE[file_name][0] == file_stat.st_mtime:
                return cls.CACHE[file_name][1]

        try:
            dom = minidom.parse(file_name)
        except Exception as exc:
            raise XMLFormatError("Couldn't parse \"%s\": %s" %
                                 (file_name, str(exc)))
        except KeyboardInterrupt:
            raise XMLFormatError("Couldn't parse \"%s\": KeyboardInterrupt" %
                                 file_name)

        try:
            data = cls.parse(dom, config_dir, cfg_name, strict)
        except XMLError:
            from exc_string import exc_string
            raise XMLFormatError("%s: %s" % (file_name, exc_string()))
        except KeyboardInterrupt:
            raise XMLFormatError("Couldn't parse \"%s\": KeyboardInterrupt" %
                                 file_name)

        cls.CACHE[file_name] = (file_stat.st_mtime, data)
        return data

    @classmethod
    def parse(cls, dom, config_dir, file_name, strict=True):
        raise NotImplementedError("parse() method has not been" +
                                  " implemented for %s" % cls)
