"""Exceptions used in DAQConfig AND in some cluster configuration parsing code
"""

class DAQConfigException(Exception): pass
class BadComponentName(DAQConfigException): pass
class BadDOMID(DAQConfigException): pass
class ConfigNotSpecifiedException(DAQConfigException): pass
class DOMNotInConfigException(DAQConfigException): pass
