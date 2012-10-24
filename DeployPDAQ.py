#!/usr/bin/env python

# DeployPDAQ.py
# Jacobsen Feb. 2007
#
# Deploy valid pDAQ cluster configurations to any cluster

import optparse
import os
import sys

from DAQConfigExceptions import DAQConfigException
from DAQConfig import DAQConfig, DAQConfigParser
from ParallelShell import ParallelShell
from XMLFileCache import XMLFileNotFound
from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from utils.Machineid import Machineid

# pdaq subdirectories to be deployed
SUBDIRS = ("target", "config", "dash", "data", "src")

# Defaults for a few args
NICE_ADJ_DEFAULT = 19
EXPRESS_DEFAULT = False
TIMEOUT_DEFAULT = 300

# add meta-project python dir to Python library search path
metaDir = find_pdaq_trunk()
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info, store_svnversion

SVN_ID = "$Id: DeployPDAQ.py 13974 2012-10-24 17:09:53Z dglo $"


def getUniqueHostNames(config):
    # There's probably a much better way to do this
    retHash = {}
    for node in config.nodes():
        retHash[str(node.hostName())] = 1
    return retHash.keys()


def getHubType(compID):
    if compID % 1000 == 0:
        return "amanda"
    elif compID % 1000 <= 200:
        return "in-ice"
    else:
        return "icetop"


def replaceHome(homeDir, curDir):
    if curDir.startswith(homeDir):
        return "~%s" % os.environ["USER"] + curDir[len(homeDir):]
    return curDir


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
                 help=("Run rsync's with --dry-run "
                       "(implies verbose and serial)"))
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
                 action="store", default=TIMEOUT_DEFAULT,
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
    p.add_option("-m", "--no-host-check", dest="nohostcheck", default=False,
                 help="Disable checking the host type for run permission")
    p.add_option("-z", "--no-schema-validation", dest="validation",
                 action="store_false", default=True,
                 help="Disable schema validation of xml configuration files")

    opt, args = p.parse_args()

    if not opt.nohostcheck:
        hostid = Machineid()
        if(not (hostid.is_build_host() or
           (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
            print >>sys.stderr, ("Are you sure you are running DeployPDAQ "
                                 "on the correct host?")
            raise SystemExit

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
    if opt.dryRun:
        opt.quiet = False

    # Map quiet/verbose to a 2-value tracelevel
    traceLevel = 0
    if opt.quiet:
        traceLevel = -1
    if opt.verbose:
        traceLevel = 1

    # DAQ Launch does not allow both quiet and verbose.
    # make the behaviour uniform
    if opt.quiet and opt.verbose:
        print >>sys.stderr, "Cannot specify both -q(uiet) and -v(erbose)"
        raise SystemExit

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
            DAQConfigParser.getClusterConfiguration(opt.configName,
                                                    clusterDesc=cdesc,
                                                    validate=opt.validation)
    except XMLFileNotFound:
        print >> sys.stderr, 'Configuration "%s" not found' % opt.configName
        p.print_help()
        raise SystemExit
    except DAQConfigException as e:
        print >> sys.stderr, 'Cluster configuration file problem:\n%s' % e
        raise SystemExit

    if traceLevel >= 0:
        if config.descName() is None:
            print "CLUSTER CONFIG: %s" % config.configName()
        else:
            print "CONFIG: %s" % config.configName()
            print "CLUSTER: %s" % config.descName()

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

        ver = store_svnversion(metaDir)
        print "VERSION: %s" % ver

    deploy(config, os.environ["HOME"], metaDir, SUBDIRS, opt.delete,
           opt.dryRun, opt.deepDryRun, opt.undeploy, traceLevel,
           monitorIval=monitorIval, niceAdj=opt.niceAdj, express=opt.express,
           doParallel=opt.doParallel, timeout=opt.timeout)


def deploy(config, homeDir, pdaqDir, subdirs, delete, dryRun,
           deepDryRun, undeploy, traceLevel, monitorIval=None,
           niceAdj=NICE_ADJ_DEFAULT, express=EXPRESS_DEFAULT,
           parallel=None, doParallel=True, timeout=TIMEOUT_DEFAULT):
    if subdirs is None:
        subdirs = SUBDIRS

    # convert to a relative path
    # (~pdaq is a different directory on different machines)
    pdaqDir = replaceHome(homeDir, pdaqDir)

    # record the configuration being deployed so
    # it gets copied along with everything else
    if not dryRun:
        config.writeCacheFile()

    if parallel is None:
        parallel = ParallelShell(parallel=doParallel, dryRun=dryRun,
                                 verbose=(traceLevel > 0 or dryRun),
                                 trace=(traceLevel > 0), timeout=timeout)

    # build stub of rsync command
    if express:
        rsyncCmdStub = "rsync"
    else:
        rsyncCmdStub = 'nice rsync --rsync-path "nice -n %d rsync"' % (niceAdj)

    rsyncCmdStub += " -azLC%s%s" % (delete and ' --delete' or '',
                                    deepDryRun and ' --dry-run' or '')

    rsyncConfigSrc = None
    if "config" in subdirs:
        # The 'SRC' arg for the config rsync command.
        configDir = find_pdaq_config()
        cfgSubdir = os.path.join(os.path.expanduser(pdaqDir), "config")
        if configDir != cfgSubdir:
            rsyncConfigSrc = configDir

            # config directory is not under pdaqDir
            # so needs to be removed from subdirs list
            subtmp = []
            subtmp += subdirs
            subtmp.remove("config")
            subdirs = subtmp

    # The 'SRC' arg for the main rsync command.  The sh "{}" syntax is used
    # here so that only one rsync is required for each node. (Running
    # multiple rsync's in parallel appeared to give rise to race
    # conditions and errors.)
    rsyncDeploySrc = os.path.join(pdaqDir, "{" + ",".join(subdirs) + "}")
    if not rsyncDeploySrc.startswith("~"):
        rsyncDeploySrc = os.path.abspath(rsyncDeploySrc)

    if not rsyncDeploySrc.startswith("~"):
        rsyncDeploySrc = os.path.abspath(rsyncDeploySrc)

    rsyncNodes = getUniqueHostNames(config)

    # Check if targetDir (the result of a build) is present
    targetDir = os.path.join(pdaqDir, 'target')
    if targetDir.startswith("~"):
        targetDir = os.path.join(homeDir, targetDir[targetDir.find("/") + 1:])
    if not undeploy and not os.path.isdir(targetDir) and not dryRun:
        raise Exception(("Target dir (%s) does not exist.\n" % targetDir) +
                        "Did you run 'mvn clean install assembly:assembly'?")

    cmdToNodeNameDict = {}

    done = False
    for nodeName in rsyncNodes:

        # Ignore localhost - already "deployed"
        if nodeName == "localhost":
            continue
        if not done and traceLevel > 0:
            print "COMMANDS:"
            done = True

        if undeploy:
            cmd = 'ssh %s "\\rm -rf ~%s/config %s"' % \
                  (nodeName, os.environ["USER"], pdaqDir)
        else:
            cmd = "%s %s %s:%s" % (rsyncCmdStub, rsyncDeploySrc, nodeName,
                                   pdaqDir)
            if rsyncConfigSrc is not None:
                cmd += " && %s %s %s:~%s" % (rsyncCmdStub, rsyncConfigSrc,
                                            nodeName, os.environ["USER"])

        cmdToNodeNameDict[cmd] = nodeName
        if traceLevel > 0 or dryRun:
            print "  " + cmd
        if not dryRun:
            parallel.add(cmd)

    if not dryRun:
        parallel.start()
        if parallel.isParallel():
            parallel.wait(monitorIval)

    if not dryRun:
        cmd_results_dict = parallel.getCmdResults()
        for cmd in cmd_results_dict:
            rtn_code, result = cmd_results_dict[cmd]
            if cmd not in cmdToNodeNameDict:
                nodeName = "unknown"
            else:
                nodeName = cmdToNodeNameDict[cmd]
            if(rtn_code != 0):
                print "-" * 60
                print ("Error non-zero return code  ( %d ) "
                       "for host:%s cmd:%s") % (rtn_code, nodeName, cmd)
                if(len(result) > 0):
                    print "Results: %s" % result


if __name__ == "__main__":
    main()
