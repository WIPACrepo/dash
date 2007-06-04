#!/usr/bin/env python

# DAQPrep.py
# John Jacobsen, NPX Designs, Inc., jacobsen\@npxdesigns.com
# Started: Fri Jun  1 15:57:10 2007

import sys
import optparse
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

    configXMLDir = abspath(join(metaDir, 'cluster-config', 'src', 'main', 'xml'))
    readClusterConfig = getDeployedClusterConfig(join(metaDir, 'cluster-config', '.config'))

    if opt.doList: showConfigs(configXMLDir, readClusterConfig); raise SystemExit

    # Choose configuration
    configToUse = "sim-localhost"
    if readClusterConfig:
        configToUse = readClusterConfig
    if opt.clusterConfigName:
        configToUse = opt.clusterConfigName

    # Parse configuration
    config = deployConfig(configXMLDir, configToUse)
    
    # Get relevant hubs - if it has a stringhub component on it, run DOMPrep.py there.
    hublist = []
    for node in config.nodes:
        for comp in node.comps:
            if comp.compName == "StringHub":
                try:
                    hublist.index(node.hostName)
                except ValueError:
                    hublist.append(node.hostName)

    cmds = ParallelShell(dryRun = opt.dryRun, timeout = 30)
    ids = {}
    for hub in hublist:
        cmd = "ssh %s DOMPrep.py" % hub
        ids[hub] = (cmds.add(cmd))

    cmds.start()
    cmds.wait()
    
    for hub in hublist:
        print "Hub %s:" % hub
        print cmds.getResult(ids[hub])
        
if __name__ == "__main__": main()

