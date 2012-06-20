#!/usr/bin/env python

#
# DAQ launch script - assumes deployment has occurred already.
# Run from an "experiment control" node - localhost/laptop or spXsX-expcont
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

import optparse
import os
import sys

from utils.Machineid import Machineid

from ComponentManager import ComponentManager
from DAQConfig import DAQConfig, DAQConfigParser
from DAQConfigExceptions import DAQConfigException
from DAQConst import DAQPort

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if "PDAQ_HOME" in os.environ:
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID = "$Id: DAQLaunch.py 13771 2012-06-20 04:27:56Z dglo $"


class ConsoleLogger(object):
    def __init__(self):
        pass

    def error(self, msg):
        print >> sys.stderr, msg

    def info(self, msg):
        print msg

if __name__ == "__main__":
    LOGMODE_OLD = 1
    LOGMODE_LIVE = 2
    LOGMODE_BOTH = LOGMODE_OLD | LOGMODE_LIVE

    ver_info = ("%(filename)s %(revision)s %(date)s %(time)s "
                "%(author)s %(release)s %(repo_rev)s") % \
                get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-9", "--kill-kill", dest="killWith9",
                 action="store_true", default=False,
                 help="just kill everything with extreme (-9) prejudice")
    p.add_option("-C", "--cluster-desc", type="string", dest="clusterDesc",
                 action="store", default=None,
                 help="Cluster description name.")
    p.add_option("-c", "--config-name", type="string",
                 dest="clusterConfigName",
                 action="store", default=None,
                 help="Cluster configuration name, subset of deployed" +
                 " configuration.")
    p.add_option("-e", "--event-check", dest="eventCheck",
                 action="store_true", default=False,
                 help="Event builder will validate events")
    p.add_option("-F", "--no-force-restart", dest="forceRestart",
                 action="store_false", default=True,
                 help="Do not force healthy components to restart at run end")
    p.add_option("-f", "--force", dest="force",
                 action="store_true", default=False,
                 help="kill components even if there is an active run")
    p.add_option("-k", "--kill-only", dest="killOnly",
                 action="store_true",  default=False,
                 help="Kill pDAQ components, don't restart")
    p.add_option("-l", "--list-configs", dest="doList",
                 action="store_true", default=False,
                 help="List available configs")
    p.add_option("-m", "--no-host-check", dest="nohostcheck", default=False,
                 help="Disable checking the host type for run permission")
    p.add_option("-n", "--dry-run", dest="dryRun",
                 action="store_true", default=False,
                 help="\"Dry run\" only, don't actually do anything")
    p.add_option("-S", "--server-kill", dest="serverKill",
                 action="store_true", default=False,
                 help="Kill all the components known by the server")
    p.add_option("-s", "--skip-kill", dest="skipKill",
                 action="store_true", default=False,
                 help="Don't kill anything, just launch")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Log output for all components to terminal")
    p.add_option("-z", "--no-schema-validation", dest="validation",
                 action="store_false", default=True,
                 help="Disable schema validation of xml configuration files")

    opt, args = p.parse_args()

    if not opt.nohostcheck:
        hostid = Machineid()
        if (not (hostid.is_control_host() or
           (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
            # to run daq launch you should either be a control host or
            # a totally unknown host
            raise SystemExit("Are you sure you are running DAQLaunch" +
                             " on the correct host?")

    # complain about superfluous options
    ignored = []
    if opt.killOnly:
        if opt.skipKill:
            raise SystemExit("Cannot specify both -k(illOnly) and -s(kipKill")
        if opt.clusterConfigName is not None:
            ignored.append("--config-name")
        if opt.eventCheck:
            ignored.append("--event-check")
    elif opt.skipKill:
        if opt.killWith9:
            ignored.append("--kill-kill")
        if opt.force:
            ignored.append("--force")
        if opt.serverKill:
            ignored.append("--server-kill")
    if len(ignored) > 0:
        print >>sys.stderr, "Ignoring " + ", ".join(ignored)

    if not opt.force:
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
            print >> sys.stderr, \
                'To force a restart, rerun with the --force option'
            raise SystemExit

    if opt.doList:
        DAQConfig.showList(None, None)
        raise SystemExit

    cfgDir = os.path.join(metaDir, 'config')
    dashDir = os.path.join(metaDir, 'dash')

    logger = ConsoleLogger()

    if not opt.skipKill:
        comps = ComponentManager.getActiveComponents(opt.clusterDesc,
                                                     configDir=cfgDir,
                                                     validate=opt.validation,
                                                     useCnC=opt.serverKill,
                                                     logger=logger)

        if comps is not None:
            doCnC = True

            ComponentManager.kill(comps, opt.verbose, opt.dryRun, doCnC,
                                  opt.killWith9, logger=logger)

        if opt.force:
            print >> sys.stderr, "Remember to run SpadeQueue.py to recover" + \
                " any orphaned data"

    if not opt.killOnly:
        try:
            cluDesc = opt.clusterDesc
            validate = opt.validation
            clusterConfig = \
                DAQConfigParser.getClusterConfiguration(opt.clusterConfigName,
                                                        useActiveConfig=False,
                                                        clusterDesc=cluDesc,
                                                        configDir=cfgDir,
                                                        validate=validate)
        except DAQConfigException as e:
            print >> sys.stderr, "DAQ Config exception:\n\t%s" % e
            raise SystemExit

        if opt.verbose:
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
        livePort = DAQPort.I3LIVE

        ComponentManager.launch(doCnC, opt.dryRun, opt.verbose, clusterConfig,
                                dashDir, cfgDir, daqDataDir, logDir,
                                logDirFallback, spadeDir, copyDir, logPort,
                                livePort, eventCheck=opt.eventCheck,
                                checkExists=True, startMissing=True,
                                forceRestart=opt.forceRestart,
                                logger=logger)
