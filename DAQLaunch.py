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
from os.path import abspath, isabs, join, basename

from GetIP import getIP
from SVNVersionInfo import getVersionInfo

SVN_ID = "$Id: DAQLaunch.py 2146 2007-10-17 01:37:59Z ksb $"
SVN_URL = "$URL: http://code.icecube.wisc.edu/daq/projects/dash/trunk/DAQLaunch.py $"

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

class HostNotFoundForComponent   (Exception): pass
class ExecJarNotFoundForComponent(Exception): pass
class JVMArgsNotFoundForComponent(Exception): pass
class ComponentNotFoundInDatabase(Exception): pass

componentDB = { "eventBuilder"      : \
                    { "ejar"     : "eventBuilder-prod-1.0.0-SNAPSHOT-comp.jar",
                      "jvm_args" : "-Xmx1024m",
                    },
                "SecondaryBuilders" : \
                    { "ejar"     : "secondaryBuilders-1.0.0-SNAPSHOT-comp.jar",
                      "jvm_args" : "",
                    },
                "inIceTrigger"      : \
                    { "ejar"     : "trigger-1.0.0-SNAPSHOT-iitrig.jar",
                      "jvm_args" : "-Xmx1600m",
                    },
                "simpleTrigger"      : \
                    { "ejar"     : "trigger-1.0.0-SNAPSHOT-simptrig.jar",
                      "jvm_args" : "-Xmx4500m",
                    },
                "iceTopTrigger"     : \
                    { "ejar"     : "trigger-1.0.0-SNAPSHOT-ittrig.jar",
                      "jvm_args" : "-Xmx1600m ",
                    },
                "globalTrigger"     : \
                    { "ejar"     : "trigger-1.0.0-SNAPSHOT-gtrig.jar",
                      "jvm_args" : "-Xmx1600m",
                    },
                "amandaTrigger"     : \
                    { "ejar"     : "trigger-1.0.0-SNAPSHOT-amtrig.jar",
                      "jvm_args" : "-Xmx1600m",
                    },
                "StringHub"         : \
                    { "ejar"     : "StringHub-1.0.0-SNAPSHOT-comp.jar",
                      "jvm_args" : "-Xmx350m -Dicecube.daq.bindery.StreamBinder.prescale=1",
                    },
              }

def getJVMArgs(compName):
    if not componentDB.has_key(compName):
        raise ComponentNotFoundInDatabase(compName)

    if not componentDB[compName].has_key("jvm_args"):
        raise JVMArgsNotFoundForComponent(compName)

    return componentDB[compName]["jvm_args"]

def getExecJar(compName):
    if not componentDB.has_key(compName):
        raise ComponentNotFoundInDatabase(compName)

    if not componentDB[compName].has_key("ejar"):
        raise ExecJarNotFoundForComponent(compName)

    return componentDB[compName]["ejar"]

def findHost(component, compID, clusterConfig):
    "Find host name where component:compID runs"
    for node in clusterConfig.nodes:
        for comp in node.comps:
            if comp.compName == component and comp.compID == compID: return node.hostName
    raise HostNotFoundForComponent(component+":"+compID)

def killJavaProcesses(dryRun, clusterConfig, verbose, killWith9):
    parallel = ParallelShell(dryRun=dryRun, verbose=verbose, trace=verbose)
    for node in clusterConfig.nodes:
        for comp in node.comps:
            killPat = getExecJar(comp.compName)
            if killWith9: niner = "-9"
            else:         niner = ""
            if node.hostName == "localhost": # Just kill it
                cmd = "pkill %s -fu %s %s" % (niner, environ["USER"], killPat)
                if verbose: print cmd
                parallel.add(cmd)
                if not killWith9:
                    cmd = "sleep 2; pkill -9 -fu %s %s" % (environ["USER"], killPat)
                    if verbose: print cmd
                    parallel.add(cmd)
            else:                            # Have to ssh to kill
                cmd = "ssh %s pkill %s -f %s" % (node.hostName, niner, killPat)
                parallel.add(cmd)
                if not killWith9:
                    cmd = "sleep 2; ssh %s pkill -9 -f %s" % (node.hostName, killPat)
                    parallel.add(cmd)

    if not dryRun:
        parallel.start()
        parallel.wait()

def startJavaProcesses(dryRun, clusterConfig, configDir, dashDir, logPort, cncPort, verbose):
    parallel = ParallelShell(dryRun=dryRun, verbose=verbose, trace=verbose)

    # The dir where all the "executable" jar files are
    binDir = join(metaDir, 'target', 'pDAQ-1.0.0-SNAPSHOT-dist.dir', 'bin')

    # What is used when not verbose
    quietStr = " < /dev/null 2>&1 > /dev/null"

    for node in clusterConfig.nodes:
        myIP = getIP(node.hostName)
        for comp in node.comps:
            execJar = join(binDir, getExecJar(comp.compName))

            javaCmd = "java"
            jvmArgs = getJVMArgs(comp.compName)
            switches = "-g %s" % configDir
            switches += " -c %s:%d" % (myIP, cncPort)
            switches += " -l %s:%d,%s" % (myIP, logPort, comp.logLevel)
            if not verbose:
                switches += quietStr

            if comp.compName == "StringHub":
                #javaCmd = "/usr/java/jdk1.5.0_07/bin/java"
                jvmArgs += " -Dicecube.daq.stringhub.componentId=%d" % comp.compID
                #switches += " -M 10"

            if node.hostName == "localhost": # Just run it
                cmd = "%s %s -jar %s %s &" % (javaCmd, jvmArgs, execJar, switches)
            else:                            # Have to ssh to run it
                cmd = """ssh -n %s \'sh -c \"%s %s -jar %s %s &\" %s &\'""" \
                      % (node.hostName, javaCmd, jvmArgs, execJar, switches, not verbose and quietStr or "")

            if verbose: print cmd
            parallel.add(cmd)

    if verbose and not dryRun: parallel.showAll()
    if not dryRun:
        parallel.start()
        parallel.wait()
                        
def doKill(doDAQRun, dryRun, dashDir, verbose, clusterConfig, killWith9):
    "Kill pDAQ python and java components in clusterConfig"
    if verbose: print "COMMANDS:"
    if doDAQRun:
        # Kill DAQRun
        daqRun = join(dashDir, 'DAQRun.py')
        cmd = daqRun + ' -k'
        if verbose: print cmd
        if not dryRun: system(cmd)
        
    # Kill CnCServer
    cncServer = join(dashDir, 'CnCServer.py')
    cmd = cncServer + ' -k'
    if verbose: print cmd
    if not dryRun: system(cmd)

    killJavaProcesses(dryRun, clusterConfig, verbose, killWith9)
    if verbose and not dryRun: print "DONE with killing Java Processes."

    # clear the active configuration
    clusterConfig.clearActiveConfig()
    
def doLaunch(doDAQRun, dryRun, verbose, clusterConfig, dashDir,
             configDir, logDir, spadeDir, copyDir, logPort, cncPort):
    "Launch components"
    # Start DAQRun
    if doDAQRun:
        daqRun = join(dashDir, 'DAQRun.py')
        options = "-r -f -c %s -l %s -s %s -u %s" % \
            (configDir, logDir, spadeDir, clusterConfig.configName)
        if copyDir: options += " -a %s" % copyDir
        if verbose:
            cmd = "%s %s -n &" % (daqRun, options)
            print cmd
            if not dryRun:
                system(cmd)
                sleep(5) # Fixme - this is a little kludgy, but CnCServer
                         # won't log correctly if DAQRun isn't started.

        else:
            cmd = "%s %s" % (daqRun, options)
            if not dryRun: system(cmd)

    # Start CnCServer
    cncServer = join(dashDir, 'CnCServer.py')
    if verbose:
        cmd = "%s -l localhost:9001 &" % cncServer
        print cmd
        if not dryRun: system(cmd)
    else:
        cmd = "%s -l localhost:9001 -d" % cncServer
        if not dryRun: system(cmd)

    startJavaProcesses(dryRun, clusterConfig, configDir, dashDir, logPort, cncPort, verbose)
    if verbose and not dryRun: print "DONE with starting Java Processes."

    # remember the active configuration
    clusterConfig.writeCacheFile(True)
    
def cyclePDAQ(dashDir, clusterConfig, configDir, logDir, spadeDir, copyDir, logPort, cncPort):
    "Completely cycle pDAQ except for DAQRun - can be used by DAQRun when cycling"
    "pDAQ in an attempt to wipe the slate clean after a failure"
    doKill(False, False, dashDir, False, clusterConfig, False)
    doLaunch(False, False, False, clusterConfig, dashDir,
             configDir, logDir, spadeDir, copyDir, logPort, cncPort)

def main():
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s %(release)s %(repo_rev)s" % getVersionInfo(SVN_ID, SVN_URL)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-c", "--config-name",  action="store", type="string",
                 dest="clusterConfigName",
                 help="Cluster configuration name, subset of deployed configuration.")
    p.add_option("-k", "--kill-only",    action="store_true", dest="killOnly",
                 help="Kill pDAQ components, don't restart")
    p.add_option("-l", "--list-configs", action="store_true", dest="doList",
                 help="List available configs")
    p.add_option("-o", "--log-port",     action="store", type="int", dest="logPort",
                 help="Port for default/catchall logging")
    p.add_option("-r", "--cnc-port",     action="store", type="int", dest="cncPort",
                 help="RPC Port for CnC Server")
    p.add_option("-n", "--dry-run",      action="store_true",        dest="dryRun",
                 help="\"Dry run\" only, don't actually do anything")
    p.add_option("-s", "--skip-kill",    action="store_true",        dest="skipKill",
                 help="Don't kill anything, just launch")
    p.add_option("-v", "--verbose",      action="store_true",        dest="verbose",
                 help="Log output for all components to terminal")
    p.add_option("-9", "--kill-kill",    action="store_true",        dest="killWith9",
                 help="just kill everything with extreme (-9) prejudice")
    p.set_defaults(clusterConfigName = None,
                   dryRun            = False,
                   verbose           = False,
                   doList            = False,
                   logPort           = 9001,
                   cncPort           = 8080,
                   skipKill          = False,
                   killWith9         = False,
                   killOnly          = False)
    opt, args = p.parse_args()

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
    
    if opt.verbose:
        print "Version: %(filename)s %(revision)s %(date)s %(time)s %(author)s %(release)s %(repo_rev)s" % getVersionInfo(SVN_ID, SVN_URL)
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
    if not opt.killOnly: doLaunch(True, opt.dryRun, opt.verbose, clusterConfig,
                                  dashDir, configDir, logDir,
                                  spadeDir, copyDir, opt.logPort, opt.cncPort)

if __name__ == "__main__": main()
