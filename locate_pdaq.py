#!/usr/bin/env python

import os

class HostNotFoundException(Exception): pass

def find_pdaq_trunk():
    curDir = os.getcwd()
    [parentDir, baseName] = os.path.split(curDir)
    for dir in [curDir, parentDir]:
        if os.path.isdir(os.path.join(dir, 'config')) and \
                os.path.isdir(os.path.join(dir, 'cluster-config')) and \
                os.path.isdir(os.path.join(dir, 'dash')):
                    return dir

    raise HostNotFoundException, 'Couldn''t find pDAQ trunk'
