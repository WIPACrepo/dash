#!/usr/bin/env python

#
# DAQ launch script - assumes deployment has occurred already.
# Run from an "experiment control" node - localhost/laptop or spXsX-expcont
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

import sys
from os import environ, mkdir, system
from time import sleep
from os.path import abspath, isabs, join
import optparse
from locate_pdaq import find_pdaq_trunk

# add 'cluster-config' to Python library search path
#
metaDir = find_pdaq_trunk()
sys.path.append(join(metaDir, 'cluster-config'))

from ClusterConfig import *
from ParallelShell import *
from GetIP import getIP

class HostNotFoundForComponent      (Exception): pass
class JavaClassNotFoundForComponent (Exception): pass
class RunScriptNotFoundForComponent (Exception): pass
class SubProjectNotFoundForComponent(Exception): pass

def findHost(component, compID, clusterConfig):
    for node in clusterConfig.nodes:
        for comp in node.comps:
            if comp.compName == component and comp.compID == compID: return node.hostName
    raise HostNotFoundForComponent(component+":"+compID)

def killJavaProcesses(dryRun, clusterConfig, verbose, killWith9):
    classDict = { "eventBuilder"      : "icecube.daq.eventBuilder.EBComponent",
                  "SecondaryBuilders" : "icecube.daq.secBuilder.SBComponent",
                  "inIceTrigger"      : "icecube.daq.trigger.component.IniceTriggerComponent",
                  "globalTrigger"     : "icecube.daq.trigger.component.GlobalTriggerComponent",
                  "StringHub"         : "icecube.daq.stringhub"
                }

    parallel = ParallelShell()
    for node in clusterConfig.nodes:
        for comp in node.comps:
            if verbose: print "Killing %s:%d on %s..." % (comp.compName,
                                                          comp.compID,
                                                          node.hostName)
            if not classDict.has_key(comp.compName): raise JavaClassNotFoundForComponent(comp.compName)
            javaClass = classDict[ comp.compName ]
            if killWith9: niner = "-9"
            else:         niner = ""
            if node.hostName == "localhost": # Just kill it
                parallel.add("pkill %s -fu %s %s" % (niner, environ["USER"], javaClass))
                if not killWith9: parallel.add("sleep 2; pkill -9 -fu %s %s" % (environ["USER"], javaClass))
            else:                            # Have to ssh to kill
                parallel.add("ssh %s pkill %s -f %s" % (node.hostName, niner, javaClass))
                if not killWith9: parallel.add("sleep 2; ssh %s pkill -9 -f %s" % (node.hostName, javaClass))

    if verbose and not dryRun: parallel.showAll()
    if not dryRun:
        parallel.start()
        parallel.wait()
    if verbose: print "Done."; parallel.showAll()

def startJavaProcesses(dryRun, realHubs, clusterConfig, dashDir, logPort, cncPort, verbose):
    runScriptDict = { "eventBuilder"      : "run-eb",
                      "SecondaryBuilders" : "run-sb",
                      "inIceTrigger"      : "run-iitrig",
                      "globalTrigger"     : "run-gltrig",
                      "StringHub"         : "run-hub"
                    }
    subProjectDict = { "eventBuilder"      : "eventBuilder-prod",
                       "SecondaryBuilders" : "secondaryBuilders",
                       "inIceTrigger"      : "trigger",
                       "globalTrigger"     : "trigger",
                       "StringHub"         : "StringHub"
                     }


    myIP = getIP()
    parallel = ParallelShell()
    for node in clusterConfig.nodes:
        for comp in node.comps:
            if verbose: print "Starting %s:%d on %s..." % (comp.compName,
                                                           comp.compID,
                                                           node.hostName)
            if not runScriptDict.has_key(comp.compName):  raise RunScriptNotFoundForComponent(comp.compName)
            if not subProjectDict.has_key(comp.compName): raise SubProjectNotFoundForComponent(comp.compName)
            if verbose:
                verboseSwitch = "--verbose"
                devNull       = ""
            else:
                verboseSwitch = ""
                devNull       = "2>&1 > /dev/null"
            realArg = ''
            if comp.compName == "StringHub":
                idStr = "--id %d" % comp.compID
                if realHubs: realArg = '--real-hub'
            else:
                idStr = ""
            if node.hostName == "localhost": # Just run it
                cmd = "%s/StartComponent.py -c %s -s %s --cnc localhost:%d --log localhost:%d %s %s %s %s"  \
                      % (dashDir, subProjectDict[comp.compName], runScriptDict[comp.compName],
                         cncPort, logPort, idStr, verboseSwitch, devNull, realArg)
                if verbose: print cmd
                parallel.add(cmd)
            else:                            # Have to ssh to run it
                if comp.compName == "StringHub":
                    cmd = "echo \"cd %s; ./dash/StartComponent.py -c %s -s %s --cnc %s:%d --log %s:%d %s %s %s \" | ssh -T %s"  \
                          % (metaDir, subProjectDict[comp.compName], runScriptDict[comp.compName],
                             myIP, cncPort, myIP, logPort, idStr, devNull, realArg, node.hostName)
                else:
                    cmd = "ssh %s \'cd %s && ./dash/StartComponent.py -c %s -s %s --cnc %s:%d --log %s:%d %s %s \'"  \
                          % (node.hostName, metaDir, subProjectDict[comp.compName], runScriptDict[comp.compName],
                             myIP, cncPort, myIP, logPort, idStr, devNull)

                if verbose: print cmd
                parallel.add(cmd)
    if verbose and not dryRun: parallel.showAll()
    if not dryRun:
        parallel.start()
        parallel.wait()
    if verbose: print "Done."; parallel.showAll()                        
                        
def doKill(dryRun, dashDir, verbose, clusterConfig, killWith9):
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
    
def doLaunch(dryRun, verbose, realHubs, clusterConfig, dashDir,
             configDir, logDir, spadeDir, logPort, cncPort):
    # Start DAQRun
    daqRun = join(dashDir, 'DAQRun.py')
    if verbose:
        cmd = "%s -c %s -l %s -s %s -n &" % (daqRun, configDir, logDir, spadeDir)
        # Fixme - this is a little kludgy, but CnCServer won't log correctly if DAQRun isn't started.
        print cmd
        if not dryRun:
            system(cmd)
            sleep(5)
    else:
        cmd = "%s -c %s -l %s -s %s" % (daqRun, configDir, logDir, spadeDir)
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

    startJavaProcesses(dryRun, realHubs, clusterConfig, dashDir, logPort, cncPort, verbose)
            
def main():
    p = optparse.OptionParser()
    p.add_option("-R", "--real-hubs",    action="store_true",           dest="realHubs")
    p.add_option("-c", "--config-name",  action="store", type="string", dest="clusterConfigName")
    p.add_option("-k", "--kill-only",    action="store_true",           dest="killOnly")
    p.add_option("-l", "--list-configs", action="store_true",           dest="doList",
                 help="List available configs")
    p.add_option("-o", "--log-port",     action="store", type="int",    dest="logPort")
    p.add_option("-n", "--dry-run",      action="store_true",           dest="dryRun")
    p.add_option("-r", "--cnc-port",     action="store", type="int",    dest="cncPort")
    p.add_option("-s", "--skip-kill",    action="store_true",           dest="skipKill")
    p.add_option("-v", "--verbose",      action="store_true",           dest="verbose")
    p.add_option("-9", "--kill-kill",    action="store_true",           dest="killWith9",
                 help="just kill everything dead")
    p.set_defaults(clusterConfigName = "sim-localhost",
                   realHubs   = False,
                   dryRun     = False,
                   verbose    = False,
                   doList     = False,
                   logPort    = 9001,
                   cncPort    = 8080,
                   skipKill   = False,
                   killWith9  = False,
                   killOnly   = False)
    opt, args = p.parse_args()

    configDir = join(metaDir, 'config')
    logDir    = join(metaDir, 'log')
    dashDir   = join(metaDir, 'dash')
    clusterConfigDir = join(metaDir, 'cluster-config', 'src', 'main', 'xml')

    if opt.doList: showConfigs(clusterConfigDir); raise SystemExit

    clusterConfig    = deployConfig(clusterConfigDir, opt.clusterConfigName)
    spadeDir  = clusterConfig.logDirForSpade
    if not isabs(spadeDir): # Assume non-fully-qualified paths are relative to metaproject top dir
        spadeDir = join(metaDir, spadeDir)

    if not exists(spadeDir) and not opt.dryRun: mkdir(spadeDir)
    
    if not exists(logDir):
        if not opt.dryRun: mkdir(logDir)
    else:
        system('rm -f %s' % join(logDir, 'catchall.log'))
    
    if opt.verbose:
        print "NODES:"
        for node in clusterConfig.nodes:
            print "  %s(%s)" % (node.hostName, node.locName),
            for comp in node.comps:
                print "%s:%d " % (comp.compName, comp.compID),
            print

    if not opt.skipKill: doKill(opt.dryRun, dashDir, opt.verbose, clusterConfig, opt.killWith9)
    if not opt.killOnly: doLaunch(opt.dryRun, opt.verbose, opt.realHubs, clusterConfig,
                                  dashDir, configDir, logDir, spadeDir, opt.logPort, opt.cncPort)

if __name__ == "__main__": main()
