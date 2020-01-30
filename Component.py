#!/usr/bin/env python
"Base class for pDAQ components"

class Component(object):
    "pDAQ Component"

    def __init__(self, name, id, log_level=None, host=None):
        "Create a component object"
        self.__name = name
        self.__id = id
        self.__log_level = log_level
        self.__host = host
        self.__order = None

    def __lt__(self, other):
        if self.__name < other.name:
            return True
        if self.__id < other.id:
            return True
        return False

    def __str__(self):
        "Return the full name of this component"
        return self.fullname

    def __repr__(self):
        "Return the full name of this component"
        return self.fullname

    @property
    def fullname(self):
        """
        Return the full name of this component
        (including instance number only on hub components)
        """
        if self.__id == 0 and not self.is_hub:
            return self.__name
        return "%s#%d" % (self.__name, self.__id)

    @property
    def host(self):
        "Return the name of the host on which this component is running"
        return self.__host

    @host.setter
    def host(self, newhost):
        "Set the name of the host on which this component is running"
        self.__host = newhost

    @property
    def id(self):
        "CnCServer identifier for this component"
        return self.__id

    @property
    def is_builder(self):
        "Return True if this is an eventBuilder or secondaryBuilders component"
        return self.__name.lower().find("builder") >= 0

    @property
    def is_hub(self):
        "Return True if this is a stringHub component"
        return self.__name.lower().find("hub") >= 0

    @property
    def is_localhost(self):
        "Return True if this component is running on the local machine"
        return self.__host is not None and \
            (self.__host == "localhost" or self.__host == "127.0.0.1")

    @property
    def is_real_hub(self):
        "Return True if this is a stringHub component running at SPS"
        return self.__name.lower() == "stringhub" and self.__id < 1000

    @property
    def is_source(self):
        "Return True if this is a source component"
        return self.is_hub

    @property
    def is_trigger(self):
        "Return True if this is a trigger component"
        return self.__name.lower().find("trigger") >= 0

    @property
    def log_level(self):
        "Return the logging level for this component"
        return self.__log_level

    @log_level.setter
    def log_level(self, lvl):
        "Set the logging level for this component"
        self.__log_level = lvl

    @property
    def name(self):
        "Component name"
        return self.__name

    @property
    def num(self):
        "Component instance number"
        return self.__id

    @property
    def order(self):
        "Return the order of this component in the DAQ 'supply chain'"
        return self.__order

    def set_order(self, num):
        "Set the order for this component"
        self.__order = num
