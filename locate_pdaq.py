#!/usr/bin/env python

import os


class HostNotFoundException(Exception):
    pass


METADIR = None


def find_pdaq_trunk():
    "Find the pDAQ tree"
    global METADIR
    if METADIR is not None:
        return METADIR

    homePDAQ = os.path.join(os.environ["HOME"], "pDAQ_trunk")
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
            return dir

    raise HostNotFoundException("Couldn't find pDAQ trunk")
