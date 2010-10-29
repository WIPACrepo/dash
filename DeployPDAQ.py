#!/usr/bin/env python

# DeployPDAQ.py
# Jacobsen Feb. 2007
#
# Deploy valid pDAQ cluster configurations to any cluster

import optparse, os, sys

from ClusterConfig import ClusterConfigException
from DAQConfig import DAQConfig, DAQConfigParser, XMLFileNotFound
from ParallelShell import ParallelShell

# pdaq subdirectories to be deployed
SUBDIRS = ("target", "cluster-config", "config", "dash", "src")

# Defaults for a few args
NICE_ADJ_DEFAULT = 19
EXPRESS_DEFAULT  = False

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info, store_svnversion

SVN_ID = "$Id: DeployPDAQ.py 12352 2010-10-29 18:40:17Z dglo $"

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
    p.add_option("-C", "--cluster-desc", type="string", dest="clusterDesc",
                 action="store", default=None,
                 help="Cluster description name")
    p.add_option("-c", "--config-name", type="string", dest="configName",
                 action="store", default=None,
                 help="REQUIRED: Configuration name")
    p.add_option("", "--delete", dest="delete",
                 action="store_true", default=True,
                 help="Run rsync's with --delete")
    p.add_option("", "--no-delete", dest="delete",
                 action="store_false", default=True,
                 help="Run rsync's without --delete")
    p.add_option("-l", "--list-configs", dest="doList",
                 action="store_true", default=False,
                 help="List available configs")
    p.add_option("-n", "--dry-run", dest="dryRun",
                 action="store_true", default=False,
                 help="Don't run rsyncs, just print as they would be run" +
                 " (disables quiet)")
    p.add_option("", "--deep-dry-run", dest="deepDryRun",
                 action="store_true", default=False,
                 help="Run rsync's with --dry-run (implies verbose and serial)")
    p.add_option("-p", "--parallel", dest="doParallel",
                 action="store_true", default=True,
                 help="Run rsyncs in parallel (default)")
    p.add_option("-q", "--quiet", dest="quiet",
                 action="store_true", default=False,
                 help="Run quietly")
    p.add_option("-s", "--serial", dest="doSerial",
                 action="store_true", default=False,
                 help="Run rsyncs serially (overrides parallel and unsets" +
                 " timeout)")
    p.add_option("-t", "--timeout", type="int", dest="timeout",
                 action="store", default=300,
                 help="Number of seconds before rsync is terminated")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Be chatty")
    p.add_option("", "--undeploy", dest="undeploy",
                 action="store_true", default=False,
                 help="Remove entire ~pdaq/.m2 and ~pdaq/pDAQ_current dirs" +
                 " on remote nodes - use with caution!")
    p.add_option("", "--nice-adj", type="int", dest="niceAdj",
                 action="store", default=NICE_ADJ_DEFAULT,
                 help="Set nice adjustment for remote rsyncs" +
                 " [default=%default]")
    p.add_option("-E", "--express", dest="express",
                 action="store_true", default=EXPRESS_DEFAULT,
                 help="Express rsyncs, unsets and overrides any/all" +
                 " nice adjustments")
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

    # How often to report count of processes waiting to finish
    monitorIval = None
    if traceLevel >= 0 and opt.timeout:
        monitorIval = max(opt.timeout * 0.01, 2)

    if opt.doList:
        DAQConfig.showList(None, None)
        raise SystemExit

    if not opt.configName:
        print >>sys.stderr, 'No configuration specified'
        p.print_help()
        raise SystemExit

    try:
        cdesc = opt.clusterDesc
        config = \
            DAQConfigParser.getClusterConfiguration(opt.configName, False,
                                                    clusterDesc=cdesc)
    except XMLFileNotFound:
        print >>sys.stderr, 'Configuration "%s" not found' % opt.configName
        p.print_help()
        raise SystemExit

    if traceLevel >= 0:
        print "CONFIG: %s" % config.configName()

        nodeList = config.nodes()
        nodeList.sort()

        print "NODES:"
        for node in nodeList:
            print "  %s(%s)" % (node.hostName(), node.locName()),

            compList = node.components()
            compList.sort()

            for comp in compList:
                print comp.fullName(),
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
           opt.dryRun, opt.deepDryRun, opt.undeploy, traceLevel, monitorIval,
           opt.niceAdj, opt.express)

def deploy(config, parallel, homeDir, pdaqDir, subdirs, delete, dryRun,
           deepDryRun, undeploy, traceLevel, monitorIval=None,
           niceAdj=NICE_ADJ_DEFAULT, express=EXPRESS_DEFAULT):
    m2  = os.path.join(homeDir, '.m2')

    # build stub of rsync command
    if express:
        rsyncCmdStub = "rsync"
    else:
        rsyncCmdStub = 'nice rsync --rsync-path "nice -n %d rsync"' % (niceAdj)

    rsyncCmdStub += " -azLC%s%s" % (delete and ' --delete' or '',
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
                                   os.path.basename(pdaqDir))
        if traceLevel >= 0: print "  "+cmd
        parallel.add(cmd)

    parallel.start()
    if parallel.isParallel():
        parallel.wait(monitorIval)

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
