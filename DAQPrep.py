#!/usr/bin/env python

# DAQPrep.py
# John Jacobsen, NPX Designs, Inc., jacobsen\@npxdesigns.com
# Started: Fri Jun  1 15:57:10 2007

import sys, optparse, re
from os import environ, getcwd, listdir, system
from os.path import abspath, isabs, join

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add 'cluster-config' to Python library search path
#
sys.path.append(join(metaDir, 'cluster-config'))

from ClusterConfig import *
from ParallelShell import *

def main():
    "Main program"
    usage = "%prog [options]"
    p = optparse.OptionParser()
    p.add_option("-c", "--config-name",  action="store", type="string", dest="clusterConfigName",
                 help="REQUIRED: Configuration name")
    p.add_option("-n", "--dry-run",      action="store_true",           dest="dryRun",
                 help="Don't actually run DOMPrep - just print what would be done")
    p.add_option("-l", "--list-configs", action="store_true",           dest="doList",
                 help="List available configs")
    
    p.set_defaults(clusterConfigName = None,
                   dryRun            = False,
                   doList            = False)
    
    opt, args = p.parse_args()

    config = ClusterConfig(metaDir, opt.clusterConfigName, opt.doList)

    # Get relevant hubs - if it has a stringhub component on it, run DOMPrep.py there.
    hublist = config.getHubNodes()

    cmds = ParallelShell(dryRun = opt.dryRun, timeout = 45)
    ids = {}
    for hub in hublist:
        cmd = "ssh %s DOMPrep.py" % hub
        ids[hub] = (cmds.add(cmd))

    cmds.start()
    cmds.wait()

    numPlugged       = 0
    numPowered       = 0
    numCommunicating = 0
    numIceboot       = 0
    
    for hub in hublist:
        print "Hub %s: " % hub,
        result = cmds.getResult(ids[hub])
        result = result.rstrip()
        print result
        # Parse template:
        # 2 pairs plugged, 2 powered; 4 DOMs communicating, 4 in iceboot
        match = re.search(r'(\d+) pairs plugged, (\d+) powered; (\d+) DOMs communicating, (\d+) in iceboot',
                          result)

        if match:
            numPlugged       += int(match.group(1))
            numPowered       += int(match.group(2))
            numCommunicating += int(match.group(3))
            numIceboot       += int(match.group(4))

    print "TOTAL: %d pairs plugged, %d pairs powered; %d DOMs communicating, %d in iceboot" \
          % (numPlugged, numPowered, numCommunicating, numIceboot)

            
if __name__ == "__main__": main()

