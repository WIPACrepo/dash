#!/usr/bin/env python

import os


class HostNotFoundException(Exception):
    pass


METADIR = None
CONFIGDIR = None


def find_pdaq_config():
    "find pDAQ's run configuration directory"
    global CONFIGDIR
    if CONFIGDIR is not None:
        return CONFIGDIR

    if "PDAQ_CONFIG" in os.environ:
        dir = os.environ["PDAQ_CONFIG"]
        if os.path.exists(dir):
            CONFIGDIR = dir
            return CONFIGDIR

    dir = os.path.join(find_pdaq_trunk(), "config")
    if os.path.exists(dir):
        CONFIGDIR = dir
        return CONFIGDIR

    dir = os.path.join(os.environ["HOME"], "config")
    if os.path.exists(dir):
        CONFIGDIR = dir
        return CONFIGDIR

    raise IOError("Cannot find DAQ configuration directory")


def find_pdaq_trunk():
    "Find the pDAQ tree"
    global METADIR
    if METADIR is not None:
        return METADIR

    if "PDAQ_HOME" in os.environ:
        dir = os.environ["PDAQ_HOME"]
        if os.path.exists(dir):
            METADIR = dir
            return METADIR

    homePDAQ = os.path.join(os.environ["HOME"], "pDAQ_current")
    curDir = os.getcwd()
    [parentDir, baseName] = os.path.split(curDir)
    for dir in [curDir, parentDir, homePDAQ]:
        # source tree has 'dash', 'src', and 'StringHub' (and maybe 'target')
        # deployed tree has 'dash', 'src', and 'target'
        if os.path.isdir(os.path.join(dir, 'dash')) and \
            os.path.isdir(os.path.join(dir, 'src')) and \
            (os.path.isdir(os.path.join(dir, 'target')) or
             os.path.isdir(os.path.join(dir, 'StringHub'))):
            METADIR = dir
            return METADIR

    raise HostNotFoundException("Cannot find pDAQ trunk")
