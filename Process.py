#!/usr/bin/env python

import os
import re
from subprocess import Popen, PIPE, STDOUT

def processList():
    command = "ps axww"
    p = Popen(command, shell=True, close_fds=True, stdout=PIPE, stderr=STDOUT)
    output = p.stdout.readlines()
    result = p.wait()
    if result:
        print "%(command)s failed: %(output)s" % locals()
        raise SystemExit
    return [s.strip() for s in output]

def findProcess(name, plist=None): # Iterate over list plist
    if plist is None:
        plist = processList()
    for p in plist:
        m = re.match(r'\s*(\d+)\s+.+?[pP]ython[\d\.]* .+?%s' % name, p)
        if m:
            yield int(m.group(1))
    return
