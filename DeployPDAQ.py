#!/usr/bin/env python

# DeployPDAQ.py
# Jacobsen Feb. 2007
#
# Deploy valid pDAQ cluster configurations to any cluster

import optparse, os, sys

from ClusterConfig import ClusterConfigException
from DAQConfig import DAQConfig, DAQConfigNotFound
from ParallelShell import ParallelShell

# pdaq subdirectories to be deployed
SUBDIRS = ("target", "cluster-config", "config", "dash", "src")

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info, store_svnversion

SVN_ID = "$Id: DeployPDAQ.py 4889 2010-02-16 18:57:10Z dglo $"

def getUniqueHostNames(config):
    # There's probably a much better way to do this
    retHash = {}
    for node in config.nodes():
        retHash[str(node.hostName())] = 1
    return retHash.keys()

def getHubType(compID):
    if compID % 1000 == 0: return "amanda"
    elif compID % 1000 <= 200: return "in-ice",
    else: return "icetop",

def main():
    "Main program"
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s " \
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)
    p.add_option("-C", "--cluster-desc", action="store", type="string", dest="clusterDesc",
                 help="Cluster description name")
    p.add_option("-c", "--config-name",  action="store", type="string", dest="configName",
                 help="REQUIRED: Configuration name")
    p.add_option("", "--delete",         action="store_true",           dest="delete",
                 help="Run rsync's with --delete")
    p.add_option("", "--no-delete",      action="store_false",          dest="delete",
                 help="Run rsync's without --delete")
    p.add_option("-l", "--list-configs", action="store_true",           dest="doList",
                 help="List available configs")
    p.add_option("-n", "--dry-run",      action="store_true",           dest="dryRun",
                 help="Don't run rsyncs, just print as they would be run (disables quiet)")
    p.add_option("", "--deep-dry-run",   action="store_true",           dest="deepDryRun",
                 help="Run rsync's with --dry-run (implies verbose and serial)")
    p.add_option("-p", "--parallel",     action="store_true",           dest="doParallel",
                 help="Run rsyncs in parallel (default)")
    p.add_option("-q", "--quiet",        action="store_true",           dest="quiet",
                 help="Run quietly")
    p.add_option("-s", "--serial",       action="store_true",           dest="doSerial",
                 help="Run rsyncs serially (overrides parallel and unsets timeout)")
    p.add_option("-t", "--timeout",      action="store", type="int",    dest="timeout",
                 help="Number of seconds before rsync is terminated")
    p.add_option("-v", "--verbose",      action="store_true",           dest="verbose",
                 help="Be chatty")
    p.add_option("", "--undeploy",       action="store_true",           dest="undeploy",
                 help="Remove entire ~pdaq/.m2 and ~pdaq/pDAQ_current dirs on remote nodes - use with caution!")
    p.set_defaults(configName = None,
                   doParallel = True,
                   doSerial   = False,
                   verbose    = False,
                   quiet      = False,
                   delete     = True,
                   dryRun     = False,
                   undeploy   = False,
                   deepDryRun = False,
                   timeout    = 60,
                   clusterDesc = None)
    opt, args = p.parse_args()

    ## Work through options implications ##
    # A deep-dry-run implies verbose and serial
    if opt.deepDryRun:
        opt.doSerial = True
        opt.verbose = True
        opt.quiet = False

    # Serial overrides parallel and unsets timout
    if opt.doSerial:
        opt.doParallel = False
        opt.timeout = None

    # dry-run implies we want to see what is happening
    if opt.dryRun:   opt.quiet = False

    # Map quiet/verbose to a 3-value tracelevel
    traceLevel = 0
    if opt.quiet:                 traceLevel = -1
    if opt.verbose:               traceLevel = 1
    if opt.quiet and opt.verbose: traceLevel = 0

    if opt.doList:
        DAQConfig.showList(None, None)
        raise SystemExit

    if not opt.configName:
        print >>sys.stderr, 'No configuration specified'
        p.print_help()
        raise SystemExit

    try:
        config = DAQConfig.getClusterConfiguration(opt.configName, False,
                                                   clusterDesc=opt.clusterDesc)
    except DAQConfigNotFound:
        print >>sys.stderr, 'Configuration "%s" not found' % opt.configName
        p.print_help()
        raise SystemExit

    if traceLevel >= 0:
        print "CONFIG: %s" % config.configName

        nodeList = config.nodes()
        nodeList.sort()

        print "NODES:"
        for node in nodeList:
            print "  %s(%s)" % (node.hostName(), node.locName()),

            compList = node.components()
            compList.sort()

            for comp in compList:
                print "%s#%d" % (comp.name(), comp.id()),
                if comp.isHub():
                    print "[%s]" % getHubType(comp.id()),
                print " ",
            print

    if not opt.dryRun:
        config.writeCacheFile()
        ver = store_svnversion()
        if traceLevel >= 0:
            print "VERSION: %s" % ver

    parallel = ParallelShell(parallel=opt.doParallel, dryRun=opt.dryRun,
                             verbose=(traceLevel > 0 or opt.dryRun),
                             trace=(traceLevel > 0), timeout=opt.timeout)

    deploy(config, parallel, os.environ["HOME"], metaDir, SUBDIRS, opt.delete,
           opt.dryRun, opt.deepDryRun, opt.undeploy, traceLevel)

def deploy(config, parallel, homeDir, pdaqDir, subdirs, delete, dryRun,
           deepDryRun, undeploy, traceLevel):
    m2  = os.path.join(homeDir, '.m2')

    rsyncCmdStub = "nice rsync -azLC%s%s" % (delete and ' --delete' or '',
                                       deepDryRun and ' --dry-run' or '')

    # The 'SRC' arg for the rsync command.  The sh "{}" syntax is used
    # here so that only one rsync is required for each node. (Running
    # multiple rsync's in parallel appeared to give rise to race
    # conditions and errors.)
    rsyncDeploySrc = \
        os.path.abspath(os.path.join(pdaqDir, "{" + ",".join(subdirs) + "}"))

    rsyncNodes = getUniqueHostNames(config)

    # Check if targetDir (the result of a build) is present
    targetDir        = os.path.abspath(os.path.join(pdaqDir, 'target'))
    if not undeploy and not os.path.isdir(targetDir):
        print >>sys.stderr, \
            "ERROR: Target dir (%s) does not exist." % (targetDir)
        print >>sys.stderr, \
            "ERROR: Did you run 'mvn clean install assembly:assembly'?"
        raise SystemExit

    done = False
    for nodeName in rsyncNodes:

        # Ignore localhost - already "deployed"
        if nodeName == "localhost": continue
        if not done and traceLevel >= 0:
            print "COMMANDS:"
            done = True

        if undeploy:
            cmd = 'ssh %s "\\rm -rf %s %s"' % (nodeName, m2, pdaqDir)
        else:
            cmd = "%s %s %s:%s" % (rsyncCmdStub, rsyncDeploySrc, nodeName,
                                   pdaqDir)
        if traceLevel >= 0: print "  "+cmd
        parallel.add(cmd)

    parallel.start()
    if parallel.isParallel():
        parallel.wait()

    if traceLevel <= 0 and not dryRun:
        needSeparator = True
        rtnCodes = parallel.getReturnCodes()
        for i in range(len(rtnCodes)):
            result = parallel.getResult(i)
            if rtnCodes[i] != 0 or len(result) > 0:
                if needSeparator:
                    print "----------------------------------"
                    needSeparator = False

                print "\"%s\" returned %s:\n%s" % \
                    (parallel.getCommand(i), str(rtnCodes[i]), result)

if __name__ == "__main__": main()
