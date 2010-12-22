#!/usr/bin/env python

#
# DAQ launch script - assumes deployment has occurred already.
# Run from an "experiment control" node - localhost/laptop or spXsX-expcont
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

import optparse
import signal
import sys
from time import sleep
from os import environ, mkdir, system
from os.path import exists, isabs, join

from ClusterConfig \
    import ClusterConfig, ClusterConfigException, ConfigNotFoundException
from Component import Component
from DAQConfig import ConfigNotSpecifiedException, DAQConfig, \
    DAQConfigException, DAQConfigParser
from DAQConst import DAQPort
from DAQRPC import RPCClient
from GetIP import getIP
from Process import findProcess, processList
from RunSetState import RunSetState

from ParallelShell import *

# the pDAQ release name
#
RELEASE = "1.0.0-SNAPSHOT"

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID = "$Id: DAQLaunch.py 12495 2010-12-22 23:26:27Z dglo $"

class HostNotFoundForComponent   (Exception): pass
class ComponentNotFoundInDatabase(Exception): pass

# Component Name -> JarParts mapping.  For constructing the name of
# the proper jar file used for running the component, based on the
# lower-case name of the component.
compNameJarPartsMap = {
    "eventbuilder"      : ("eventBuilder-prod", "comp"    ),
    "secondarybuilders" : ("secondaryBuilders", "comp"    ),
    "inicetrigger"      : ("trigger",           "iitrig"  ),
    "simpletrigger"     : ("trigger",           "simptrig"),
    "icetoptrigger"     : ("trigger",           "ittrig"  ),
    "globaltrigger"     : ("trigger",           "gtrig"   ),
    "amandatrigger"     : ("trigger",           "amtrig"  ),
    "stringhub"         : ("StringHub",         "comp"    ),
    "replayhub"         : ("StringHub",         "replay"  ),
    }

def getCompJar(compName):
    """ Return the name of the executable jar file for the named
    component.  """

    jarParts = compNameJarPartsMap.get(compName.lower(), None)
    if not jarParts:
        raise ComponentNotFoundInDatabase(compName)

    return "%s-%s-%s.jar" % (jarParts[0], RELEASE, jarParts[1])

def runCmd(cmd, parallel):
    if parallel is None:
        system(cmd)
    else:
        parallel.system(cmd)

class LaunchComponent(Component):
    def __init__(self, name, id, logLevel, jvm, jvmArgs, host):
        self.__jvm = jvm
        self.__jvmArgs = jvmArgs
        self.__host = host

        super(LaunchComponent, self).__init__(name, id, logLevel)

    def host(self): return self.__host
    def isControlServer(self): return False
    def jvm(self): return self.__jvm
    def jvmArgs(self): return self.__jvmArgs

def __buildComponentList(clusterConfig):
    compList = []
    for node in clusterConfig.nodes():
        for comp in node.components():
            if not comp.isControlServer():
                compList.append(LaunchComponent(comp.name(), comp.id(),
                                                comp.logLevel(), comp.jvm(),
                                                comp.jvmArgs(),
                                                node.hostName()))
    return compList

def killJavaProcesses(dryRun, clusterConfig, verbose, killWith9, parallel=None):
    killJavaComponents(__buildComponentList(clusterConfig), dryRun, verbose,
                       killWith9, parallel)

def killJavaComponents(compList, dryRun, verbose, killWith9, parallel=None):
    if parallel is None:
        parallel = ParallelShell(dryRun=dryRun, verbose=verbose, trace=verbose)
    for comp in compList:
        if comp.jvm() is None: continue

        if comp.isHub():
            killPat = "stringhub.componentId=%d" % comp.id()
        else:
            killPat = getCompJar(comp.name())

        if comp.host() == "localhost": # Just kill it
            fmtStr = "pkill %%s -fu %s %s" % (environ["USER"], killPat)
        else:
            fmtStr = "ssh %s pkill %%s -f %s" % (comp.host(), killPat)

        # add '-' on first command
        if killWith9: add9 = 0
        else:         add9 = 1

        # only do one pass if we're using 'kill -9'
        for i in range(add9 + 1):
            # set '-9' flag
            if i == add9: niner = "-9"
            else:         niner = ""

            # sleep for all commands after the first pass
            if i == 0: sleepr = ""
            else:      sleepr = "sleep 2; "

            cmd = sleepr + fmtStr % niner
            if verbose: print cmd
            if dryRun:
                print cmd
            else:
                parallel.add(cmd)

    if not dryRun:
        parallel.start()
        parallel.wait()

def startJavaProcesses(dryRun, clusterConfig, configDir, dashDir, logPort,
                       livePort, verbose, eventCheck, checkExists=True,
                       parallel=None):
    startJavaComponents(__buildComponentList(clusterConfig), dryRun, configDir,
                        dashDir, logPort, livePort, verbose, eventCheck,
                        checkExists, parallel)

def startJavaComponents(compList, dryRun, configDir, dashDir, logPort, livePort,
                        verbose, eventCheck, checkExists=True, parallel=None):
    if parallel is None:
        parallel = ParallelShell(dryRun=dryRun, verbose=verbose, trace=verbose)

    # The dir where all the "executable" jar files are
    binDir = join(metaDir, 'target', 'pDAQ-%s-dist' % RELEASE, 'bin')
    if checkExists and not os.path.isdir(binDir):
        binDir = join(metaDir, 'target', 'pDAQ-%s-dist.dir' % RELEASE, 'bin')
        if not os.path.isdir(binDir):
            raise SystemExit("Cannot find jar file directory \"%s\"" % binDir)

    # how are I/O streams handled?
    if not verbose:
        quietStr = " </dev/null >/dev/null 2>&1"
    else:
        quietStr = ""

    for comp in compList:
        if comp.jvm() is None: continue

        myIP = getIP(comp.host())
        execJar = join(binDir, getCompJar(comp.name()))
        if checkExists and not exists(execJar):
            print "%s jar file does not exist: %s" % (comp.name(), execJar)
            continue

        javaCmd = comp.jvm()
        jvmArgs = comp.jvmArgs()

        switches = "-g %s" % configDir
        switches += " -c %s:%d" % (myIP, DAQPort.CNCSERVER)
        if logPort is not None:
            switches += " -l %s:%d,%s" % (myIP, logPort, comp.logLevel())
        if livePort is not None:
            switches += " -L %s:%d,%s" % (myIP, livePort, comp.logLevel())
        compIO = quietStr

        if comp.isHub():
            jvmArgs += " -Dicecube.daq.stringhub.componentId=%d" % comp.id()

        if eventCheck and comp.isBuilder():
            jvmArgs += " -Dicecube.daq.eventBuilder.validateEvents"

        if comp.host() == "localhost": # Just run it
            cmd = "%s %s -jar %s %s %s &" % \
                (javaCmd, jvmArgs, execJar, switches, compIO)
        else:                            # Have to ssh to run it
            cmd = """ssh -n %s \'sh -c \"%s %s -jar %s %s %s &\"%s &\'""" % \
                (comp.host(), javaCmd, jvmArgs, execJar, switches, compIO,
                 quietStr)

        if verbose: print cmd
        if dryRun:
            print cmd
        else:
            parallel.add(cmd)

    if verbose and not dryRun: parallel.showAll()
    if not dryRun:
        parallel.start()
        parallel.wait()

def reportAction(action, actionList, ignored):
    "Report which Python daemons were launched/killed and which were ignored"

    if len(actionList) > 0:
        if len(ignored) > 0:
            print "%s %s, ignored %s" % (action, ", ".join(actionList),
                                         ", ".join(ignored))
        else:
            print "%s %s" % (action, ", ".join(actionList))
    elif len(ignored) > 0:
        print "Ignored %s" % ", ".join(ignored)

def doKill(doCnC, dryRun, dashDir, verbose, quiet, clusterConfig,
           killWith9, parallel=None):
    "Kill pDAQ python and java components in clusterConfig"
    if verbose: print "COMMANDS:"

    killed = []
    ignored = []

    batch = ((True, "DAQLive"),
             (True, "DAQRun"),
             (doCnC, "CnCServer"))

    for b in batch:
        if b[0]:
            pids = list(findProcess(b[1], processList()))
            pid = int(os.getpid())
            for p in pids:
                if pid != p:
                    if dryRun:
                        print "kill -KILL %d" % p
                    else:
                        # print "Killing %d..." % p
                        os.kill(p, signal.SIGKILL)
                        if not quiet: killed.append(b[1])
        elif not dryRun and not quiet:
            ignored.append(b[1])

    killJavaProcesses(dryRun, clusterConfig, verbose, killWith9, parallel)
    if verbose and not dryRun: print "DONE with killing Java Processes."
    if not quiet:
        reportAction("Killed", killed, ignored)

    # clear the active configuration
    clusterConfig.clearActiveConfig()

def isRunning(procName, procList):
    "Is this process running?"
    pids = list(findProcess(procName, procList))
    return len(pids) > 0

def doLaunch(doCnC, dryRun, verbose, quiet, clusterConfig, dashDir,
             configDir, logDir, spadeDir, copyDir, logPort, livePort,
             eventCheck=False, checkExists=True, startMissing=True,
             parallel=None, forceRestart=True):
    "Launch components"
    # get a list of the running processes
    if not startMissing:
        procList = []
    else:
        procList = processList()

    launched = []
    ignored = []

    progBase = "CnCServer"
    progName = progBase + ".py"

    if startMissing and not doCnC:
        doCnC |= not isRunning(progName, procList)

    if doCnC:
        path  = join(dashDir, progName)
        # enable forceConfig and relaunch options
        options = " -c %s -o %s -s %s" % (configDir, logDir, spadeDir)
        if clusterConfig.descName() is not None:
            options += ' -C ' + clusterConfig.descName()
        if logPort is not None:
            options += ' -l localhost:%d' % logPort
        if livePort is not None:
            options += ' -L localhost:%d' % livePort
        if copyDir: options += " -a %s" % copyDir
        if not forceRestart: options += ' -F'
        if verbose: options += ' &'
        else: options += ' -d'

        cmd = "%s%s" % (path, options)
        if verbose: print cmd
        if dryRun:
            print cmd
        else:
            runCmd(cmd, parallel)
            if not quiet: launched.append(progBase)
    elif not dryRun and not quiet:
        ignored.append(progBase)


    startJavaProcesses(dryRun, clusterConfig, configDir, dashDir,
                       DAQPort.CATCHALL, livePort, verbose, eventCheck,
                       checkExists=checkExists, parallel=parallel)
    if verbose and not dryRun: print "DONE with starting Java Processes."
    if not quiet and (len(launched) > 0 or len(ignored) > 0):
        reportAction("Launched", launched, ignored)

    # remember the active configuration
    clusterConfig.writeCacheFile(True)

def cyclePDAQ(dashDir, clusterConfig, configDir, logDir, spadeDir, copyDir,
              logPort, livePort, eventCheck=False, checkExists=True,
              startMissing=True, parallel=None):
    """
    Stop and restart pDAQ programs - can be used when cycling
    pDAQ in an attempt to wipe the slate clean after a failure
    """
    doCnC = True
    dryRun = False
    verbose = False
    quiet = True
    killWith9 = False

    doKill(doCnC, dryRun, dashDir, verbose, quiet, clusterConfig, killWith9,
           parallel)
    doLaunch(doCnC, dryRun, verbose, quiet, clusterConfig, dashDir, configDir,
             logDir, spadeDir, copyDir, logPort, livePort,
             eventCheck=eventCheck, checkExists=checkExists,
             startMissing=startMissing, parallel=parallel)

if __name__ == "__main__":
    LOGMODE_OLD = 1
    LOGMODE_LIVE = 2
    LOGMODE_BOTH = LOGMODE_OLD | LOGMODE_LIVE

    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s %(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-C", "--cluster-desc", type="string", dest="clusterDesc",
                 action="store", default=None,
                 help="Cluster description name.")
    p.add_option("-c", "--config-name", type="string", dest="clusterConfigName",
                 action="store", default=None,
                 help="Cluster configuration name, subset of deployed" +
                 " configuration.")
    p.add_option("-e", "--event-check", dest="eventCheck",
                 action="store_true", default=False,
                 help="Event builder will validate events")
    p.add_option("-f", "--force", dest="force",
                 action="store_true", default=False,
                 help="kill components even if there is an active run")
    p.add_option("-F", "--no-force-restart", dest="forceRestart",
                 action="store_false", default=True,
                 help="Do not force healthy components to restart at run end")
    p.add_option("-k", "--kill-only", dest="killOnly",
                 action="store_true",  default=False,
                 help="Kill pDAQ components, don't restart")
    p.add_option("-l", "--list-configs", dest="doList",
                 action="store_true", default=False,
                 help="List available configs")
    p.add_option("-n", "--dry-run", dest="dryRun",
                 action="store_true", default=False,
                 help="\"Dry run\" only, don't actually do anything")
    p.add_option("-q", "--quiet", dest="quiet",
                 action="store_true", default=False,
                 help="Don't print actions")
    p.add_option("-s", "--skip-kill", dest="skipKill",
                 action="store_true", default=False,
                 help="Don't kill anything, just launch")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Log output for all components to terminal")
    p.add_option("-9", "--kill-kill", dest="killWith9",
                 action="store_true", default=False,
                 help="just kill everything with extreme (-9) prejudice")
    opt, args = p.parse_args()

    if opt.quiet and opt.verbose:
        print >>sys.stderr, "Cannot specify both -q(uiet) and -v(erbose)"
        raise SystemExit

    configDir = join(metaDir, 'config')
    logDir    = join(' ', 'mnt', 'data', 'pdaq', 'log').strip()
    logDirFallBack = join(metaDir, 'log')
    dashDir   = join(metaDir, 'dash')

    if not opt.force:
        # connect to CnCServer
        cnc = RPCClient('localhost', DAQPort.CNCSERVER)

        # Get the number of active runsets from CnCServer
        try:
            numSets = int(cnc.rpc_runset_count())
        except:
            numSets = None

        if numSets is not None and numSets > 0:
            inactiveStates = (RunSetState.READY, RunSetState.IDLE,
                              RunSetState.DESTROYED, RunSetState.ERROR)

            active = 0
            runsets = {}
            for id in cnc.rpc_runset_list_ids():
                runsets[id] = cnc.rpc_runset_state(id)
                if not runsets[id] in inactiveStates:
                    active += 1

            if active > 0:
                if numSets == 1:
                    plural = ''
                else:
                    plural = 's'
                print >>sys.stderr, 'Found %d active runset%s:' % \
                    (numSets, plural)
                for id in runsets.keys():
                    print >>sys.stderr, "  %d: %s" % (id, runsets[id])
                print >>sys.stderr, \
                    'To force a restart, rerun with the --force option'
                raise SystemExit

    if opt.doList:
        DAQConfig.showList(None, None)
        raise SystemExit

    if not opt.skipKill:
        doCnC = True

        caughtException = False
        try:
            activeConfig = \
                DAQConfigParser.getClusterConfiguration(None, False, True)
            doKill(doCnC, opt.dryRun, dashDir, opt.verbose, opt.quiet,
                   activeConfig, opt.killWith9)
        except ClusterConfigException:
            caughtException = True
        except DAQConfigException:
            caughtException = True
        if caughtException and opt.killOnly:
            print >>sys.stderr, 'DAQ is not currently active'

        if opt.force:
            print >>sys.stderr, "Remember to run SpadeQueue.py to recover" + \
                " any orphaned data"

    if not opt.killOnly:
        clusterConfig = \
            DAQConfigParser.getClusterConfiguration(opt.clusterConfigName,
                                                    opt.doList, False,
                                                    opt.clusterDesc,
                                                    configDir=configDir)
        if opt.doList: raise SystemExit

        if opt.verbose:
            print "Version: %(filename)s %(revision)s %(date)s %(time)s " \
                "%(author)s %(release)s %(repo_rev)s" % get_version_info(SVN_ID)
            print "CONFIG: %s" % clusterConfig.configName()

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

        spadeDir  = clusterConfig.logDirForSpade()
        # Assume non-fully-qualified paths are relative to metaproject top dir:
        if not isabs(spadeDir):
            spadeDir = join(metaDir, spadeDir)

        if not exists(spadeDir) and not opt.dryRun: mkdir(spadeDir)

        copyDir   = clusterConfig.logDirCopies()
        # Assume non-fully-qualified paths are relative to metaproject top dir:
        if copyDir:
            if not isabs(copyDir):
                copyDir = join(metaDir, copyDir)
            if not exists(copyDir) and not opt.dryRun: mkdir(copyDir)

        # Set up logDir
        if not exists(logDir):
            if not opt.dryRun:
                try:
                    mkdir(logDir)
                except OSError, (errno, strerror):
                    if opt.verbose:
                        print "Problem making log dir: '%s' (%s)" % \
                            (logDir, strerror)
                        print "Using fallback for logDir: %s" % (logDirFallBack)
                    logDir = logDirFallBack
                    if not exists(logDir): mkdir(logDir)

        doCnC = True

        logPort = None
        livePort = DAQPort.I3LIVE

        doLaunch(doCnC, opt.dryRun, opt.verbose, opt.quiet, clusterConfig,
                 dashDir, configDir, logDir, spadeDir, copyDir, logPort,
                 livePort, eventCheck=opt.eventCheck, checkExists=True,
                 startMissing=True, forceRestart=opt.forceRestart)
