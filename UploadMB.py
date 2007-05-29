#!/usr/bin/env python

import optparse
import sys
from os import environ
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
    p = optparse.OptionParser()
    p.add_option("-c", "--config-name",  action="store", type="string",
                 dest="clusterConfigName",
                 help="Cluster configuration name, subset of deployed configuration.")
    p.set_defaults(clusterConfigName = None)
    opt, args = p.parse_args()

    readClusterConfig = getDeployedClusterConfig(join(metaDir, 'cluster-config', '.config'))

    # Choose configuration
    configToUse = "sim-localhost"
    if readClusterConfig:
        configToUse = readClusterConfig
    if opt.clusterConfigName:
        configToUse = opt.clusterConfigName

    print configToUse

    clusterConfigDir = join(metaDir, 'cluster-config', 'src', 'main', 'xml')
    # Get/parse cluster configuration
    clusterConfig = deployConfig(clusterConfigDir, configToUse)
          
if __name__ == "__main__": main()
