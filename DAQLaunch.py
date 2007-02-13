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
from os.path import abspath, isabs, join

from GetIP import getIP
from locate_pdaq import find_pdaq_trunk

# add 'cluster-config' to Python library search path
#
metaDir = find_pdaq_trunk()
sys.path.append(join(metaDir, 'cluster-config'))

from ClusterConfig import *
from ParallelShell import *

class HostNotFoundForComponent      (Exception): pass
class JavaClassNotFoundForComponent (Exception): pass
class RunScriptNotFoundForComponent (Exception): pass
class SubProjectNotFoundForComponent(Exception): pass

def findHost(component, compID, clusterConfig):
    "Find host name where component:compID runs"
    for node in clusterConfig.nodes:
        for comp in node.comps:
            if comp.compName == component and comp.compID == compID: return node.hostName
    raise HostNotFoundForComponent(component+":"+compID)

def killJavaProcesses(dryRun, clusterConfig, verbose, killWith9):
    classDict = \
            { "eventBuilder"      : "icecube.daq.eventBuilder.EBComponent",
              "SecondaryBuilders" : "icecube.daq.secBuilder.SBComponent",
              "inIceTrigger"      : "icecube.daq.trigger.component.IniceTriggerComponent",
              "iceTopTrigger"     : "icecube.daq.trigger.component.IcetopTriggerComponent",
              "globalTrigger"     : "icecube.daq.trigger.component.GlobalTriggerComponent",
              "amandaTrigger"     : "icecube.daq.trigger.component.AmandaTriggerComponent",
              "StringHub"         : "icecube.daq.stringhub"
            }

    parallel = ParallelShell()
    for node in clusterConfig.nodes:
        for comp in node.comps:
            if not classDict.has_key(comp.compName):
                raise JavaClassNotFoundForComponent(comp.compName)
            javaClass = classDict[ comp.compName ]
            if killWith9: niner = "-9"
            else:         niner = ""
            if node.hostName == "localhost": # Just kill it
                cmd = "pkill %s -fu %s %s" % (niner, environ["USER"], javaClass)
                if verbose: print cmd
                parallel.add(cmd)
                if not killWith9:
                    cmd = "sleep 2; pkill -9 -fu %s %s" % (environ["USER"], javaClass)
                    if verbose: print cmd
                    parallel.add(cmd)
            else:                            # Have to ssh to kill
                cmd = "ssh %s pkill %s -f %s" % (node.hostName, niner, javaClass)
                parallel.add(cmd)
                if not killWith9:
                    cmd = "sleep 2; ssh %s pkill -9 -f %s" % (node.hostName, javaClass)
                    parallel.add(cmd)

    if not dryRun:
        parallel.start()
        parallel.wait()

def startJavaProcesses(dryRun, clusterConfig, dashDir, logPort, cncPort, verbose):
    runScriptDict = { "eventBuilder"      : "run-eb",
                      "SecondaryBuilders" : "run-sb",
                      "inIceTrigger"      : "run-iitrig",
                      "iceTopTrigger"     : "run-ittrig",
                      "globalTrigger"     : "run-gltrig",
                      "StringHub"         : "run-hub",
                      "amandaTrigger"     : "run-amtrig"
                    }
    subProjectDict = { "eventBuilder"      : "eventBuilder-prod",
                       "SecondaryBuilders" : "secondaryBuilders",
                       "inIceTrigger"      : "trigger",
                       "iceTopTrigger"     : "trigger",
                       "globalTrigger"     : "trigger",
                       "amandaTrigger"     : "trigger",
                       "StringHub"         : "StringHub"
                     }


    myIP = getIP()
    parallel = ParallelShell()
    for node in clusterConfig.nodes:
        for comp in node.comps:
            if not runScriptDict.has_key(comp.compName):
                raise RunScriptNotFoundForComponent(comp.compName)
            if not subProjectDict.has_key(comp.compName):
                raise SubProjectNotFoundForComponent(comp.compName)
            switches = ""
            if verbose:
                switches += "--verbose "
            else:
                switches += "2>&1 > /dev/null "

            if comp.compName == "StringHub":
                switches += "--id %d " % comp.compID

            switches += "-d %s " % comp.logLevel
            switches += "-c %s " % subProjectDict[comp.compName]
            switches += "-s %s " % runScriptDict [comp.compName]
            if node.hostName == "localhost": # Just run it
                switches += "--cnc localhost:%d " % cncPort
                switches += "--log localhost:%d " % logPort
                cmd = "%s/StartComponent.py %s" % (dashDir, switches)
                if verbose: print cmd
                parallel.add(cmd)
            else:                            # Have to ssh to run it
                switches += "--cnc %s:%d " % (myIP, cncPort)
                switches += "--log %s:%d " % (myIP, logPort)
                if comp.compName == "StringHub":
                    cmd = "echo \"cd %s; ./dash/StartComponent.py %s \" | ssh -T %s" \
                          % (metaDir, switches, node.hostName)
                else:
                    cmd = "ssh %s \'cd %s && ./dash/StartComponent.py %s \' " \
                          % (node.hostName, metaDir, switches)

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
    if verbose and not dryRun: print "DONE."
    
def doLaunch(doDAQRun, dryRun, verbose, clusterConfig, dashDir,
             configDir, logDir, spadeDir, logPort, cncPort):
    "Launch components"
    # Start DAQRun
    if doDAQRun:
        daqRun = join(dashDir, 'DAQRun.py')
        options = "-r -f -c %s -l %s -s %s" % (configDir, logDir, spadeDir)
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

    startJavaProcesses(dryRun, clusterConfig, dashDir, logPort, cncPort, verbose)
    if verbose and not dryRun: print "DONE."
    
def getDeployedClusterConfig(clusterFile):
    "Get cluster configuration name persisted in clusterFile"
    try:
        f = open(clusterFile, "r")
        ret = f.readline()
        f.close()
        return ret.rstrip('\r\n')
    except:
        return None

def cyclePDAQ(dashDir, clusterConfig, configDir, logDir, spadeDir, logPort, cncPort):
    "Completely cycle pDAQ except for DAQRun - can be used by DAQRun when cycling"
    "pDAQ in an attempt to wipe the slate clean after a failure"
    doKill(False, False, dashDir, False, clusterConfig, False)
    doLaunch(False, False, False, clusterConfig, dashDir,
             configDir, logDir, spadeDir, logPort, cncPort)

def main():
    p = optparse.OptionParser()
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

    readClusterConfig = getDeployedClusterConfig(join(metaDir, 'cluster-config', '.config'))
    
    # Choose configuration
    configToUse = "sim-localhost"
    if readClusterConfig:
        configToUse = readClusterConfig
    if opt.clusterConfigName:
        configToUse = opt.clusterConfigName

    configDir = join(metaDir, 'config')
    logDir    = join(metaDir, 'log')
    dashDir   = join(metaDir, 'dash')
    clusterConfigDir = join(metaDir, 'cluster-config', 'src', 'main', 'xml')

    if opt.doList: showConfigs(clusterConfigDir); raise SystemExit

    # Get/parse cluster configuration
    clusterConfig = deployConfig(clusterConfigDir, configToUse)

    spadeDir  = clusterConfig.logDirForSpade
    # Assume non-fully-qualified paths are relative to metaproject top dir:
    if not isabs(spadeDir): 
        spadeDir = join(metaDir, spadeDir)

    if not exists(spadeDir) and not opt.dryRun: mkdir(spadeDir)
    
    if not exists(logDir):
        if not opt.dryRun: mkdir(logDir)
    else:
        system('rm -f %s' % join(logDir, 'catchall.log'))
    
    if opt.verbose:
        print "CONFIG: %s" % configToUse
        print "NODES:"
        for node in clusterConfig.nodes:
            print "  %s(%s)" % (node.hostName, node.locName),
            for comp in node.comps:
                print "%s-%d " % (comp.compName, comp.compID),
            print

    if not opt.skipKill: doKill(True, opt.dryRun, dashDir, opt.verbose,
                                clusterConfig, opt.killWith9)
    if not opt.killOnly: doLaunch(True, opt.dryRun, opt.verbose, clusterConfig,
                                  dashDir, configDir, logDir,
                                  spadeDir, opt.logPort, opt.cncPort)

if __name__ == "__main__": main()
