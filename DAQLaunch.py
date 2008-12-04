#!/usr/bin/env python

#
# DAQ launch script - assumes deployment has occurred already.
# Run from an "experiment control" node - localhost/laptop or spXsX-expcont
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

import sys
import optparse
from time import sleep
from os import environ, mkdir, system
from os.path import exists, isabs, join

from DAQConst import DAQPort
from DAQRPC import RPCClient
from GetIP import getIP

SVN_ID = "$Id: DAQLaunch.py 3695 2008-12-04 20:00:24Z dglo $"

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add 'cluster-config' and meta-project python dir to Python library
# search path
sys.path.append(join(metaDir, 'cluster-config'))
sys.path.append(join(metaDir, 'src', 'main', 'python'))

from SVNVersionInfo import get_version_info
from ClusterConfig import *
from ParallelShell import *

class HostNotFoundForComponent   (Exception): pass
class ComponentNotFoundInDatabase(Exception): pass

class ComponentData(object):
    RELEASE = "1.0.0-SNAPSHOT"

    def __init__(self, name, type="comp", memory=1024, extraArgs=None):
        self.__name = name
        self.__type = type
        self.__memory = memory
        self.__extraArgs = extraArgs

    def getJVMArgs(self):
        jvmArgs = "-server -Xms%dm -Xmx%dm" % (self.__memory, self.__memory)

        if self.__extraArgs is not None:
            jvmArgs += " " + self.__extraArgs

        return jvmArgs

    def getJar(self):
        return "%s-%s-%s.jar" % \
            (self.__name, ComponentData.RELEASE, self.__type)

class TriggerData(ComponentData):
    def __init__(self, type, memory=1600):
        super(TriggerData, self).__init__("trigger", type, memory)

class HubData(ComponentData):
    def __init__(self, type, memory):
        extraArgs = "-Dicecube.daq.bindery.StreamBinder.prescale=1"
        super(HubData, self).__init__("StringHub", type, memory, extraArgs)

# note that the component name keys for componentDB should be lower-case
componentDB = { "eventbuilder"      : ComponentData("eventBuilder-prod"),
                "secondarybuilders" : ComponentData("secondaryBuilders"),
                "inicetrigger"      : TriggerData("iitrig"),
                "simpletrigger"     : TriggerData("simptrig"),
                "icetoptrigger"     : TriggerData("ittrig"),
                "globaltrigger"     : TriggerData("gtrig"),
                "amandatrigger"     : TriggerData("amtrig"),
                "stringhub"         : HubData("comp", 640),
                "replayhub"         : HubData("replay", 350),
              }

def getLaunchData(compName):
    key = compName.lower()

    if not componentDB.has_key(key):
        raise ComponentNotFoundInDatabase(compName)

    return componentDB[key]

def runCmd(cmd, parallel):
    if parallel is None:
        system(cmd)
    else:
        parallel.system(cmd)

def killJavaProcesses(dryRun, clusterConfig, verbose, killWith9, parallel=None):
    if parallel is None:
        parallel = ParallelShell(dryRun=dryRun, verbose=verbose, trace=verbose)
    for node in clusterConfig.nodes:
        for comp in node.comps:
            data = getLaunchData(comp.compName)
            jarName = data.getJar()
            if killWith9: niner = "-9"
            else:         niner = ""
            if node.hostName == "localhost": # Just kill it
                cmd = "pkill %s -fu %s %s" % (niner, environ["USER"], jarName)
                if verbose: print cmd
                parallel.add(cmd)
                if not killWith9:
                    cmd = "sleep 2; pkill -9 -fu %s %s" % (environ["USER"], jarName)
                    if verbose: print cmd
                    parallel.add(cmd)
            else:                            # Have to ssh to kill
                cmd = "ssh %s pkill %s -f %s" % (node.hostName, niner, jarName)
                parallel.add(cmd)
                if not killWith9:
                    cmd = "sleep 2; ssh %s pkill -9 -f %s" % (node.hostName, jarName)
                    parallel.add(cmd)

    if not dryRun:
        parallel.start()
        parallel.wait()

def startJavaProcesses(dryRun, clusterConfig, configDir, dashDir, logPort,
                       livePort, verbose, eventCheck, checkExists=True,
                       parallel=None):
    if parallel is None:
        parallel = ParallelShell(dryRun=dryRun, verbose=verbose, trace=verbose)

    # The dir where all the "executable" jar files are
    binDir = join(metaDir, 'target', 'pDAQ-1.0.0-SNAPSHOT-dist.dir', 'bin')

    # how are I/O streams handled?
    if not verbose:
        quietStr = " </dev/null >/dev/null 2>&1"
    else:
        quietStr = ""

    for node in clusterConfig.nodes:
        myIP = getIP(node.hostName)
        for comp in node.comps:
            data = getLaunchData(comp.compName)
            execJar = join(binDir, data.getJar())
            if checkExists and not exists(execJar):
                print "%s jar file does not exist: %s" % \
                    (comp.compName, execJar)
                continue

            javaCmd = "java"
            jvmArgs = data.getJVMArgs()

            switches = "-g %s" % configDir
            switches += " -c %s:%d" % (myIP, DAQPort.CNCSERVER)
            if logPort is not None:
                switches += " -l %s:%d,%s" % (myIP, logPort, comp.logLevel)
            if livePort is not None:
                switches += " -L %s:%d,%s" % (myIP, livePort, comp.logLevel)
            compIO = quietStr

            if comp.compName.endswith("Hub"):
                #javaCmd = "/usr/java/jdk1.5.0_07/bin/java"
                jvmArgs += " -Dicecube.daq.stringhub.componentId=%d" % comp.compID
                #switches += " -M 10"

            if eventCheck and comp.compName == "eventBuilder":
                jvmArgs += " -Dicecube.daq.eventBuilder.validateEvents"

            #compIO = " </dev/null >/tmp/%s.%d 2>&1" % (comp.compName, comp.compID)

            if node.hostName == "localhost": # Just run it
                cmd = "%s %s -jar %s %s %s &" % \
                    (javaCmd, jvmArgs, execJar, switches, compIO)
            else:                            # Have to ssh to run it
                cmd = \
                    """ssh -n %s \'sh -c \"%s %s -jar %s %s %s &\"%s &\'""" % \
                    (node.hostName, javaCmd, jvmArgs, execJar, switches,
                     compIO, quietStr)

            if verbose: print cmd
            parallel.add(cmd)

    if verbose and not dryRun: parallel.showAll()
    if not dryRun:
        parallel.start()
        parallel.wait()

def doKill(doDAQRun, dryRun, dashDir, verbose, clusterConfig, killWith9,
           parallel=None):
    "Kill pDAQ python and java components in clusterConfig"
    if verbose: print "COMMANDS:"
    if doDAQRun:
        # Kill DAQRun
        daqRun = join(dashDir, 'DAQRun.py')
        cmd = daqRun + ' -k'
        if verbose: print cmd
        if not dryRun:
            runCmd(cmd, parallel)
        # Kill DAQLive
        if killWith9: niner = "-9 "
        else:         niner = ""
        cmd = "pkill %s-fu %s DAQLive.py" % (niner, environ["USER"])
        if verbose: print cmd
        if not dryRun:
            runCmd(cmd, parallel)

    # Kill CnCServer
    cncServer = join(dashDir, 'CnCServer.py')
    cmd = cncServer + ' -k'
    if verbose: print cmd
    if not dryRun:
        runCmd(cmd, parallel)

    killJavaProcesses(dryRun, clusterConfig, verbose, killWith9, parallel)
    if verbose and not dryRun: print "DONE with killing Java Processes."

    # clear the active configuration
    clusterConfig.clearActiveConfig()

def doLaunch(doDAQRun, dryRun, verbose, clusterConfig, dashDir,
             configDir, logDir, spadeDir, copyDir, logPort, livePort,
             eventCheck=False, checkExists=True, parallel=None):
    "Launch components"

    # Start DAQRun
    if doDAQRun:
        daqRun  = join(dashDir, 'DAQRun.py')
        options = "-r -f -c %s -l %s -s %s -u %s" % \
            (configDir, logDir, spadeDir, clusterConfig.configName)
        if livePort is not None:
            if logPort is not None:
                options += " -B"
            else:
                options += " -L"
        if copyDir: options += " -a %s" % copyDir
        if verbose: options += " -n &"
        cmd = "%s %s" % (daqRun, options)
        if verbose: print cmd
        if not dryRun:
            runCmd(cmd, parallel)
        if verbose:
            sleep(5) # Fixme - this is a little kludgy, but CnCServer
                         # won't log correctly if DAQRun isn't started.

        # Start DAQLive
        daqLive = join(dashDir, 'DAQLive.py')
        cmd = "%s%s &" % (daqLive, verbose and " -v" or "")
        if verbose: print cmd
        if not dryRun:
            runCmd(cmd, parallel)

    # Start CnCServer
    cncCmd = join(dashDir, 'CnCServer.py')
    if logPort is not None:
        cncCmd += ' -l localhost:%d' % logPort
    if livePort is not None:
        cncCmd += ' -L localhost:%d' % livePort
    if verbose: cncCmd += ' &'
    else: cncCmd += ' -d'
    if verbose: print cmd
    if not dryRun:
        runCmd(cncCmd, parallel)

    startJavaProcesses(dryRun, clusterConfig, configDir, dashDir, logPort,
                       livePort, verbose, eventCheck, checkExists=checkExists,
                       parallel=parallel)
    if verbose and not dryRun: print "DONE with starting Java Processes."

    # remember the active configuration
    clusterConfig.writeCacheFile(True)

def cyclePDAQ(dashDir, clusterConfig, configDir, logDir, spadeDir, copyDir,
              logPort, livePort, eventCheck=False, checkExists=True,
              parallel=None):
    """
    Stop and restart pDAQ programs - can be used by DAQRun when cycling
    pDAQ in an attempt to wipe the slate clean after a failure
    """
    doDAQRun = False
    dryRun = False
    verbose = False
    killWith9 = False

    doKill(doDAQRun, dryRun, dashDir, verbose, clusterConfig, killWith9,
           parallel)
    doLaunch(doDAQRun, dryRun, verbose, clusterConfig, dashDir, configDir,
             logDir, spadeDir, copyDir, logPort, livePort,
             eventCheck=eventCheck, checkExists=checkExists, parallel=parallel)

if __name__ == "__main__":
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s %(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-B", "--log-to-files-and-i3live", action="store_true",
                 dest="bothMode",
                 help="Send log messages to both I3Live and to local files")

    p.add_option("-c", "--config-name",  action="store", type="string",
                 dest="clusterConfigName",
                 help="Cluster configuration name, subset of deployed configuration.")
    p.add_option("-e", "--event-check",  action="store_true", dest="eventCheck",
                 help="Event builder will validate events")
    p.add_option("-f", "--force",        action="store_true", dest="force",
                 help="kill components even if there is an active run")
    p.add_option("-k", "--kill-only",    action="store_true", dest="killOnly",
                 help="Kill pDAQ components, don't restart")
    p.add_option("-l", "--list-configs", action="store_true", dest="doList",
                 help="List available configs")
    p.add_option("-L", "--log-to-i3live", action="store_true", dest="liveMode",
                 help="Send all log messages to I3Live")
    p.add_option("-n", "--dry-run",      action="store_true",        dest="dryRun",
                 help="\"Dry run\" only, don't actually do anything")
    p.add_option("-s", "--skip-kill",    action="store_true",        dest="skipKill",
                 help="Don't kill anything, just launch")
    p.add_option("-v", "--verbose",      action="store_true",        dest="verbose",
                 help="Log output for all components to terminal")
    p.add_option("-9", "--kill-kill",    action="store_true",        dest="killWith9",
                 help="just kill everything with extreme (-9) prejudice")
    p.set_defaults(bothMode          = False,
                   clusterConfigName = None,
                   dryRun            = False,
                   verbose           = False,
                   doList            = False,
                   skipKill          = False,
                   killWith9         = False,
                   killOnly          = False,
                   eventCheck        = False,
                   force             = False,
                   liveMode          = False)
    opt, args = p.parse_args()

    if opt.bothMode and opt.liveMode:
        print >>sys.stderr, 'ERROR: Cannot specify both -B and -L'
        raise SystemExit

    if opt.bothMode or not opt.liveMode:
        logPort = DAQPort.CATCHALL
    else:
        logPort = None

    if opt.bothMode or opt.liveMode:
        livePort = DAQPort.I3LIVE
    else:
        livePort = None

    configDir = join(metaDir, 'config')
    logDir    = join(' ', 'mnt', 'data', 'pdaq', 'log').strip()
    logDirFallBack = join(metaDir, 'log')
    dashDir   = join(metaDir, 'dash')

    clusterConfig = ClusterConfig(metaDir, opt.clusterConfigName, opt.doList)

    spadeDir  = clusterConfig.logDirForSpade
    # Assume non-fully-qualified paths are relative to metaproject top dir:
    if not isabs(spadeDir):
        spadeDir = join(metaDir, spadeDir)

    if not exists(spadeDir) and not opt.dryRun: mkdir(spadeDir)

    copyDir   = clusterConfig.logDirCopies
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
                    print "Problem making log dir: '%s' (%s)" % (logDir, strerror)
                    print "Using fallback for logDir: %s" % (logDirFallBack)
                logDir = logDirFallBack
                if not exists(logDir): mkdir(logDir)
    else:
        system('rm -f %s' % join(logDir, 'catchall.log'))

    if not opt.force:
        # connect to CnCServer
        cncrpc = RPCClient('localhost', DAQPort.CNCSERVER)

        # Get the number of active runsets from CnCServer
        try:
            numSets = int(cncrpc.rpc_num_sets())
        except:
            numSets = None

        if numSets is not None and numSets > 0:
            daqrpc = RPCClient("localhost", DAQPort.DAQRUN)
            try:
                state  = daqrpc.rpc_run_state()
            except:
                state = "DEAD"

            deadStates = ("DEAD", "ERROR", "STOPPED")
            if not state in deadStates:
                if numSets == 1:
                    plural = ''
                else:
                    plural = 's'
                print >>sys.stderr, 'Found %d %s runset%s' % \
                    (numSets, state.lower(), plural)
                print >>sys.stderr, \
                    'To force a restart, rerun with the --force option'
                raise SystemExit

    if opt.verbose:
        print "Version: %(filename)s %(revision)s %(date)s %(time)s " \
              "%(author)s %(release)s %(repo_rev)s" % get_version_info(SVN_ID)
        print "CONFIG: %s" % clusterConfig.configName
        print "NODES:"
        for node in clusterConfig.nodes:
            print "  %s(%s)" % (node.hostName, node.locName),
            for comp in node.comps:
                print "%s-%d " % (comp.compName, comp.compID),
            print

    if not opt.skipKill:
        try:
            activeConfig = ClusterConfig(metaDir, None, False, False, True)
            doKill(True, opt.dryRun, dashDir, opt.verbose, activeConfig,
                   opt.killWith9)
        except ConfigNotSpecifiedException:
            if opt.killOnly: print >>sys.stderr, 'DAQ is not currently active'
    if not opt.killOnly:
        doLaunch(True, opt.dryRun, opt.verbose, clusterConfig, dashDir,
                 configDir, logDir, spadeDir, copyDir, logPort, livePort,
                 eventCheck=opt.eventCheck)
