#!/usr/bin/env python

import os
import re

def processList():
    command = "ps axww"
    (cmdin, cmdout) = os.popen4(command); cmdin.close()
    output = cmdout.read()
    result = cmdout.close()
    if result:
        print "%(command)s failed: %(output)s" % locals()
        raise SystemExit
    return output.split('\n')

def findProcess(name, plist=None): # Iterate over list plist
    if plist is None:
        plist = processList()
    for p in plist:
        m = re.match(r'\s*(\d+)\s+.+?[pP]ython .+?%s' % name, p)
        if m:
            yield int(m.group(1))
    return
