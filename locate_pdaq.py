#!/usr/bin/env python

import os

class HostNotFoundException(Exception): pass

def find_pdaq_trunk():
    curDir   = os.getcwd()
    homePDAQ = os.path.join(os.environ["HOME"], "pDAQ_trunk")
    [parentDir, baseName] = os.path.split(curDir)
    for d in [curDir, parentDir, homePDAQ]:
        if os.path.isdir(os.path.join(d, 'config')) and \
                os.path.isdir(os.path.join(d, 'cluster-config')) and \
                os.path.isdir(os.path.join(d, 'dash')):
                    return d

    raise HostNotFoundException, 'Couldn\'t find pDAQ trunk'
