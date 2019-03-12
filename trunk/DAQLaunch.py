#!/usr/bin/env python

#
# DAQ launch script - assumes deployment has occurred already.
# Run from an "experiment control" node - localhost/laptop or spXsX-expcont
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

from __future__ import print_function

import os
import subprocess
import sys

from utils.Machineid import Machineid

from ComponentManager import ComponentManager
from DAQConfig import DAQConfigParser
from DAQConfigExceptions import DAQConfigException
from DAQConst import DAQPort
from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from scmversion import get_scmversion_str


# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()


class ConsoleLogger(object):
    def __init__(self):
        pass

    def error(self, msg):
        print(msg, file=sys.stderr)

    def info(self, msg):
        print(msg)


def add_arguments_both(parser):
    parser.add_argument("-9", "--kill-kill", dest="killWith9",
                        action="store_true", default=False,
                        help="just kill everything with extreme (-9)"
                        " prejudice")
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


def add_arguments_kill(_):
    pass


def add_arguments_launch(parser, config_as_arg=True):
    parser.add_argument("-C", "--cluster-desc", dest="clusterDesc",
                        help="Cluster description name.")
    if config_as_arg:
        parser.add_argument("-c", "--config-name", dest="configName",
                            help="Configuration name")
    else:
        parser.add_argument("configName", nargs="?",
                            help="Run configuration name")
    parser.add_argument("-e", "--event-check", dest="eventCheck",
                        action="store_true", default=False,
                        help="Event builder will validate events")
    parser.add_argument("-F", "--no-force-restart", dest="forceRestart",
                        action="store_false", default=True,
                        help="Do not force healthy components to restart at"
                        " run end")
    parser.add_argument("-s", "--skip-kill", dest="skipKill",
                        action="store_true", default=False,
                        help="Don't kill anything, just launch")


def add_arguments_old(parser):
    parser.add_argument("-k", "--kill-only", dest="killOnly",
                        action="store_true", default=False,
                        help="Kill pDAQ components, don't restart")
    parser.add_argument("-l", "--list-configs", dest="doList",
                        action="store_true", default=False,
                        help="List available configs")


def check_detector_state():
    (runsets, active) = ComponentManager.countActiveRunsets()
    if active > 0:
        if len(runsets) == 1:
            plural = ''
        else:
            plural = 's'
        print('Found %d active runset%s:' % \
            (len(runsets), plural), file=sys.stderr)
        for rid in list(runsets.keys()):
            print("  %d: %s" % (rid, runsets[rid]), file=sys.stderr)
        raise SystemExit('To force a restart, rerun with the --force option')


def kill(cfgDir, logger, args=None, clusterDesc=None, validate=None,
         serverKill=None, verbose=None, dryRun=None, killWith9=None,
         force=None, parallel=None):
    if args is not None:
        if clusterDesc is not None or validate is not None or \
           serverKill is not None or verbose is not None or \
           dryRun is not None or killWith9 is not None or \
           force is not None:
            errmsg = "DAQLaunch.kill() called with 'args' and" + \
                     " values for individual parameters"
            if logger is not None:
                logger.error(errmsg)
            else:
                print(errmsg, file=sys.stderr)
        clusterDesc = args.clusterDesc
        validate = args.validation
        serverKill = args.serverKill
        verbose = args.verbose
        dryRun = args.dryRun
        killWith9 = args.killWith9
        force = args.force

    comps = ComponentManager.getActiveComponents(clusterDesc,
                                                 configDir=cfgDir,
                                                 validate=validate,
                                                 useCnC=serverKill,
                                                 logger=logger)

    if comps is not None:
        killCnC = True

        ComponentManager.kill(comps, verbose=verbose, dryRun=dryRun,
                              killCnC=killCnC, killWith9=killWith9,
                              logger=logger, parallel=parallel)

    if force:
        print("Remember to run SpadeQueue.py to recover" + \
            " any orphaned data", file=sys.stderr)


def launch(cfgDir, dashDir, logger, args=None, clusterDesc=None,
           configName=None, validate=None, verbose=None, dryRun=None,
           eventCheck=None, parallel=None, forceRestart=None,
           checkExists=True):
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
                print(errmsg, file=sys.stderr)

        clusterDesc = args.clusterDesc
        configName = args.configName
        validate = args.validation
        verbose = args.verbose
        dryRun = args.dryRun
        eventCheck = args.eventCheck
        forceRestart = args.forceRestart

    if configName is None:
        configName = livecmd_default_config()

    try:
        clusterConfig = \
            DAQConfigParser.getClusterConfiguration(configName,
                                                    useActiveConfig=False,
                                                    clusterDesc=clusterDesc,
                                                    configDir=cfgDir,
                                                    validate=validate)
    except DAQConfigException as e:
        raise SystemExit("DAQ Config exception:\n\t%s" % str(e))

    if verbose:
        print("Version info: " + get_scmversion_str())
        if clusterConfig.description is None:
            print("CLUSTER CONFIG: %s" % (clusterConfig.configName, ))
        else:
            print("CONFIG: %s" % (clusterConfig.configName, ))
            print("CLUSTER: %s" % clusterConfig.description)

        nodeList = sorted(clusterConfig.nodes())

        print("NODES:")
        for node in nodeList:
            print("  %s(%s)" % (node.hostname, node.location), end=' ')

            compList = sorted(node.components())

            for comp in compList:
                print("%s#%d " % (comp.name, comp.id), end=' ')
            print()

    spadeDir = clusterConfig.logDirForSpade
    copyDir = clusterConfig.logDirCopies
    logDir = clusterConfig.daqLogDir
    logDirFallback = os.path.join(PDAQ_HOME, "log")
    daqDataDir = clusterConfig.daqDataDir

    doCnC = True

    logPort = None
    livePort = DAQPort.I3LIVE_ZMQ

    ComponentManager.launch(doCnC, dryRun, verbose, clusterConfig, dashDir,
                            cfgDir, daqDataDir, logDir, logDirFallback,
                            spadeDir, copyDir, logPort, livePort,
                            eventCheck=eventCheck, checkExists=checkExists,
                            startMissing=True, forceRestart=forceRestart,
                            logger=logger, parallel=parallel)


def livecmd_default_config():
    cmd = "livecmd config"

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, close_fds=True,
                            shell=True)
    proc.stdin.close()

    config = None
    for line in proc.stdout:
        if config is None:
            config = line.rstrip()

    proc.stdout.close()
    proc.wait()

    if proc.returncode > 1:
        raise SystemExit("Cannot get default run config file name"
                         " from \"livecmd\"")

    return config


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
        print("Ignoring " + ", ".join(ignored), file=sys.stderr)

    if not args.nohostcheck:
        # exit if not running on expcont
        hostid = Machineid()
        if (not (hostid.is_control_host() or
                 (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
            raise SystemExit("Are you sure you are launching"
                             " from the correct host?")

    if not args.force:
        check_detector_state()

    cfgDir = find_pdaq_config()
    dashDir = os.path.join(PDAQ_HOME, "dash")

    logger = ConsoleLogger()

    if not args.skipKill:
        kill(cfgDir, logger, args=args)

    if not args.killOnly:
        launch(cfgDir, dashDir, logger, args=args)
