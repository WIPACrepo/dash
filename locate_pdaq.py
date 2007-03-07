#!/usr/bin/env python

import os

class HostNotFoundException(Exception): pass

def find_pdaq_trunk():
    curDir   = os.getcwd()
    homePDAQ = os.path.join(os.environ["HOME"], "pDAQ_trunk")
    [parentDir, baseName] = os.path.split(curDir)
    for dir in [curDir, parentDir, homePDAQ]:
        if os.path.isdir(os.path.join(dir, 'config')) and \
                os.path.isdir(os.path.join(dir, 'cluster-config')) and \
                os.path.isdir(os.path.join(dir, 'dash')):
                    return dir

    raise HostNotFoundException, 'Couldn\'t find pDAQ trunk'
