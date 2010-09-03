#!/usr/bin/env python

class Component(object):
    def __init__(self, name, id, logLevel=None):
        self.__name = name
        self.__id = id
        self.__logLevel = logLevel

    def __cmp__(self, other):
        val = cmp(self.__name, other.__name)
        if val == 0:
            val = cmp(self.__id, other.__id)
        return val

    def __str__(self):
        nStr = self.fullName()
        return nStr

    def __repr__(self): return self.fullName()

    def fullName(self):
        if self.__id == 0 and not self.isHub():
            return self.__name
        return "%s#%d" % (self.__name, self.__id)

    def id(self): return self.__id

    def isBuilder(self):
        "Is this an eventBuilder or secondaryBuilder component?"
        return self.__name.lower().endswith("builder")

    def isHub(self):
        "Is this a stringHub component?"
        return self.__name.lower().find("hub") >= 0

    def isRealHub(self):
        "Is this a stringHub component running at the South Pole?"
        return self.__name.lower() == "stringhub" and self.__id < 1000

    def logLevel(self): return self.__logLevel
    def name(self): return self.__name

    def setLogLevel(self, lvl):
        self.__logLevel = lvl
