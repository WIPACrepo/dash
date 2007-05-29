#!/usr/bin/env python

import optparse
import sys
from os import environ
from os.path import abspath, isabs, join, exists

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
    p = optparse.OptionParser()
    p.add_option("-c", "--config-name",  action="store", type="string",
                 dest="clusterConfigName",
                 help="Cluster configuration name, subset of deployed configuration.")
    p.add_option("-q", "--quiet",        action="store_true",           dest="quiet",
                 help="Run quietly")
    p.add_option("-v", "--verbose",      action="store_true",           dest="verbose",
                 help="Be chatty")
    p.add_option("-n", "--dry-run",      action="store_true",           dest="dryRun",
                 help="Don't run rsyncs, just print as they would be run (disables quiet)")
    p.set_defaults(clusterConfigName = None,
                   quiet             = False,
                   verbose           = True,
                   dryRun            = False)
    opt, args = p.parse_args()

    usage = "Usage: UploadMB [args: -h to list] release.hex"
    if len(args) < 1:
        print usage
        raise SystemExit

    releaseFile = args[0]

    # Make sure file exists
    if not exists(releaseFile):
        print "Release file %s doesn't exist!\n\n" % releaseFile
        print usage
        raise SystemExit
    
    readClusterConfig = getDeployedClusterConfig(join(metaDir, 'cluster-config', '.config'))

    # Choose configuration
    configToUse = "sim-localhost"
    if readClusterConfig:
        configToUse = readClusterConfig
    if opt.clusterConfigName:
        configToUse = opt.clusterConfigName

    clusterConfigDir = join(metaDir, 'cluster-config', 'src', 'main', 'xml')
    # Get/parse cluster configuration
    clusterConfig = deployConfig(clusterConfigDir, configToUse)

    hublist = []
    
    for node in clusterConfig.nodes:
        addNode = False
        for comp in node.comps:
            if comp.compName == "StringHub": addNode = True
        if addNode: hublist.append(node.hostName)

    # Copy phase - copy mainboard release.hex file to remote nodes
    copySet = ParallelShell(parallel=True, dryRun=opt.dryRun, verbose=opt.verbose,
                            trace=opt.verbose)

    for domhub in hublist:
        copySet.add("scp -q %s %s:/tmp/release.hex" % (releaseFile, domhub))

    copySet.start()
    copySet.wait()

    # DOM prep phase - put DOMs in iceboot
    prepSet = ParallelShell(parallel=True, dryRun=opt.dryRun, verbose=opt.verbose,
                                                        trace=opt.verbose)

    for domhub in hublist:
        prepSet.add("/usr/local/bin/iceboot all")

    prepSet.start()
    prepSet.wait()
        
    # Upload phase - upload release
    uploadSet = ParallelShell(parallel=True, dryRun=opt.dryRun, verbose=opt.verbose,
                              trace=opt.verbose)

    for domhub in hublist:
        uploadSet.add("/usr/local/bin/reldall /tmp/release.hex")

    uploadSet.start()
    uploadSet.wait()
    
if __name__ == "__main__": main()
