#!/usr/bin/env python
"""
Exceptions used in DAQConfig AND in some cluster configuration parsing code
"""


class DAQConfigException(Exception):
    "Base DAQ configuration exception"
    pass


class BadComponentName(DAQConfigException):
    "Invalid name for component"
    pass


class BadDOMID(DAQConfigException):
    "Invalid ID for DOM"
    pass


class ConfigNotSpecifiedException(DAQConfigException):
    "No configuration was specified"
    pass


class DOMNotInConfigException(DAQConfigException):
    "A Dom is missing from the configuration"
    pass
