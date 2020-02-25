#!/usr/bin/env python
"""
Exceptions used in DAQConfig AND in some cluster configuration parsing code
"""


class DAQConfigException(Exception):
    "Base DAQ configuration exception"


class BadComponentName(DAQConfigException):
    "Invalid name for component"


class BadDOMID(DAQConfigException):
    "Invalid ID for DOM"


class ConfigNotSpecifiedException(DAQConfigException):
    "No configuration was specified"


class DOMNotInConfigException(DAQConfigException):
    "A DOM is missing from the configuration"
