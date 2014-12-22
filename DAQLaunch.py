#!/usr/bin/env python

#
# DAQ launch script - assumes deployment has occurred already.
# Run from an "experiment control" node - localhost/laptop or spXsX-expcont
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

import os
import sys

from utils.Machineid import Machineid

from ComponentManager import ComponentManager
from DAQConfig import DAQConfig, DAQConfigParser
from DAQConfigExceptions import DAQConfigException
from DAQConst import DAQPort
from locate_pdaq import find_pdaq_config, find_pdaq_trunk


# add meta-project python dir to Python library search path
metaDir = find_pdaq_trunk()
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID = "$Id: DAQLaunch.py 15324 2014-12-22 20:49:38Z dglo $"


class ConsoleLogger(object):
    def __init__(self):
        pass

    def error(self, msg):
        print >> sys.stderr, msg

    def info(self, msg):
        print msg


def add_arguments_both(parser):
    parser.add_argument("-9", "--kill-kill", dest="killWith9",
                        action="store_true", default=False,
                        help="just kill everything with extreme (-9) prejudice")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="kill components even if there is an active run")
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help=("Disable checking the host type for"
                              " run permission"))
    parser.add_argument("-n", "--dry-run", dest="dryRun",
                        action="store_true", default=False,
                        help="\"Dry run\" only, don't actually do anything")
    parser.add_argument("-S", "--server-kill", dest="serverKill",
                        action="store_true", default=False,
                        help="Kill all the components known by the server")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Log output for all components to terminal")
    parser.add_argument("-z", "--no-schema-validation", dest="validation",
                        action="store_false", default=True,
                        help=("Disable schema validation of"
                              " xml configuration files"))


def add_arguments_kill(parser):
    pass


def add_arguments_launch(parser, config_as_arg=True):
    parser.add_argument("-C", "--cluster-desc", dest="clusterDesc",
                   help="Cluster description name.")
    if config_as_arg:
        parser.add_argument("-c", "--config-name", dest="configName",
                            help="REQUIRED: Configuration name")
    else:
        parser.add_argument("configName",
                            help="Run configuration name")
    parser.add_argument("-e", "--event-check", dest="eventCheck",
                   action="store_true", default=False,
                   help="Event builder will validate events")
    parser.add_argument("-F", "--no-force-restart", dest="forceRestart",
                   action="store_false", default=True,
                   help="Do not force healthy components to restart at run end")
    parser.add_argument("-s", "--skip-kill", dest="skipKill",
                   action="store_true", default=False,
                   help="Don't kill anything, just launch")


def add_arguments_old(parser):
    parser.add_argument("-k", "--kill-only", dest="killOnly",
                   action="store_true",  default=False,
                   help="Kill pDAQ components, don't restart")
    parser.add_argument("-l", "--list-configs", dest="doList",
                   action="store_true", default=False,
                   help="List available configs")


def check_running_on_expcont(prog):
    "exit the program if it's not running on 'expcont' on SPS/SPTS"
    hostid = Machineid()
    if (not (hostid.is_control_host() or
            (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
        raise SystemExit("Are you sure you are running" +
                         " %s on the correct host?" % prog)


def check_detector_state():
    (runsets, active) = ComponentManager.countActiveRunsets()
    if active > 0:
        if len(runsets) == 1:
            plural = ''
        else:
            plural = 's'
        print >> sys.stderr, 'Found %d active runset%s:' % \
            (len(runsets), plural)
        for id in runsets.keys():
            print >> sys.stderr, "  %d: %s" % (id, runsets[id])
        raise SystemExit('To force a restart, rerun with the --force option')


def kill(cfgDir, logger, args=None, clusterDesc=None, validation=False,
         serverKill=False):
    if args is not None:
        if clusterDesc is not None or validation is not None or \
           serverKill is not None:
            errmsg = "DAQLaunch.kill() called with 'args' and" + \
                     " values for individual parameters"
            if logger is not None:
                logger.error(errmsg)
            else:
                print >> sys.stderr, errmsg
        clusterDesc = args.clusterDesc
        validation = args.validation
        serverKill = args.serverKill

    comps = ComponentManager.getActiveComponents(clusterDesc,
                                                 configDir=cfgDir,
                                                 validate=validation,
                                                 useCnC=serverKill,
                                                 logger=logger)

    if comps is not None:
        doCnC = True

        ComponentManager.kill(comps, args.verbose, args.dryRun, doCnC,
                              args.killWith9, logger=logger)

    if args.force:
        print >> sys.stderr, "Remember to run SpadeQueue.py to recover" + \
            " any orphaned data"


def launch(cfgDir, dashDir, logger, args=None, clusterDesc=None,
           configName=None, validate=False, verbose=False, dryRun=False,
           eventCheck=False, forceRestart=False):
    if args is not None:
        if clusterDesc is not None or configName is not None or \
           validate is not None or verbose is not None or \
           dryRun is not None or eventCheck is not None or \
           forceRestart is not None:
            errmsg = "DAQLaunch.launch() called with 'args' and" + \
                     " values for individual parameters"
            if logger is not None:
                logger.error(errmsg)
            else:
                print >> sys.stderr, errmsg

        cluDesc = args.clusterDesc
        cfgName = args.configName
        validate = args.validation
        verbose = args.verbose
        dryRun = args.dryRun
        eventCheck = args.eventCheck
        forceRestart = args.forceRestart

    try:
        clusterConfig = \
            DAQConfigParser.getClusterConfiguration(cfgName,
                                                    useActiveConfig=False,
                                                    clusterDesc=cluDesc,
                                                    configDir=cfgDir,
                                                    validate=validate)
    except DAQConfigException as e:
        print >> sys.stderr, "DAQ Config exception:\n\t%s" % e
        raise SystemExit

    if verbose:
        print "Version: %(filename)s %(revision)s %(date)s %(time)s " \
            "%(author)s %(release)s %(repo_rev)s" % \
            get_version_info(SVN_ID)
        if clusterConfig.descName() is None:
            print "CLUSTER CONFIG: %s" % clusterConfig.configName()
        else:
            print "CONFIG: %s" % clusterConfig.configName()
            print "CLUSTER: %s" % clusterConfig.descName()

        nodeList = clusterConfig.nodes()
        nodeList.sort()

        print "NODES:"
        for node in nodeList:
            print "  %s(%s)" % (node.hostName(), node.locName()),

            compList = node.components()
            compList.sort()

            for comp in compList:
                print "%s#%d " % (comp.name(), comp.id()),
            print

    spadeDir = clusterConfig.logDirForSpade()
    copyDir = clusterConfig.logDirCopies()
    logDir = clusterConfig.daqLogDir()
    logDirFallback = os.path.join(metaDir, "log")
    daqDataDir = clusterConfig.daqDataDir()

    doCnC = True

    logPort = None
    livePort = DAQPort.I3LIVE_ZMQ

    ComponentManager.launch(doCnC, dryRun, verbose, clusterConfig, dashDir,
                            cfgDir, daqDataDir, logDir, logDirFallback,
                            spadeDir, copyDir, logPort, livePort,
                            eventCheck=eventCheck, checkExists=True,
                            startMissing=True, forceRestart=forceRestart,
                            logger=logger)


if __name__ == "__main__":
    import argparse

    LOGMODE_OLD = 1
    LOGMODE_LIVE = 2
    LOGMODE_BOTH = LOGMODE_OLD | LOGMODE_LIVE

    p = argparse.ArgumentParser()

    add_arguments_kill(p)
    add_arguments_launch(p)
    add_arguments_both(p)
    add_arguments_old(p)

    args = p.parse_args()

    # complain about superfluous options
    ignored = []
    if args.killOnly:
        if args.skipKill:
            raise SystemExit("Cannot specify both -k(illOnly) and -s(kipKill")
        if args.configName is not None:
            ignored.append("--config-name")
        if args.eventCheck:
            ignored.append("--event-check")
    elif args.skipKill:
        if args.killWith9:
            ignored.append("--kill-kill")
        if args.force:
            ignored.append("--force")
        if args.serverKill:
            ignored.append("--server-kill")
    if len(ignored) > 0:
        print >>sys.stderr, "Ignoring " + ", ".join(ignored)

    if not args.nohostcheck:
        check_running_on_expcont("DAQLaunch")

    if not args.force:
        check_detector_state()

    cfgDir = find_pdaq_config()
    dashDir = os.path.join(metaDir, "dash")

    logger = ConsoleLogger()

    if not args.skipKill:
        kill(cfgDir, logger, args=args)

    if not args.killOnly:
        launch(cfgDir, dashDir, logger, args=args)
