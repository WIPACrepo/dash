#!/usr/bin/env python

#
# DAQ launch script - assumes deployment has occurred already.
# Run from an "experiment control" node - localhost/laptop or spXsX-expcont
#
# John Jacobsen, jacobsen@npxdesigns.com
# Started January, 2007

import sys
from os import system, environ
from time import sleep
from os.path import abspath
import optparse
clustConfigPath = abspath("../cluster-config")
sys.path.append(clustConfigPath)
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

def killJavaProcesses(dryRun, clusterConfig, verbose):
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
            if node.hostName == "localhost": # Just kill it
                parallel.add("pkill -fu %s %s"    % (environ["USER"], javaClass))
                parallel.add("sleep 2; pkill -9 -fu %s %s" % (environ["USER"], javaClass))
            else:                            # Have to ssh to kill
                parallel.add("ssh %s pkill -f %s" % (node.hostName, javaClass))
                parallel.add("sleep 2; ssh %s pkill -9 -f %s" % (node.hostName, javaClass))

    if verbose and not dryRun: parallel.showAll()
    if not dryRun:
        parallel.start()
        parallel.wait()
    if verbose: print "Done."; parallel.showAll()

def startJavaProcesses(dryRun, clusterConfig, dashDir, logPort, cncPort, verbose):
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
            if comp.compName == "StringHub": idStr = "--id %d" % comp.compID
            else: idStr = ""
            if node.hostName == "localhost": # Just run it
                cmd = "%s/StartComponent.py -c %s -s %s --cnc localhost:%d --log localhost:%d %s %s %s"  \
                      % (dashDir, subProjectDict[comp.compName], runScriptDict[comp.compName],
                         cncPort, logPort, idStr, verboseSwitch, devNull)
                if verbose: print cmd
                if not dryRun: system(cmd)
            else:                            # Have to ssh to run it
                cmd = "ssh %s \"%s/StartComponent.py -c %s -s %s --cnc %s:%d --log %s:%d %s %s \""  \
                      % (node.hostName, dashDir, subProjectDict[comp.compName],
                         runScriptDict[comp.compName],
                         myIP, cncPort, myIP, logPort, idStr, devNull)
                if verbose: print cmd
                if not dryRun: system(cmd)
                        
def doKill(dryRun, dashDir, verbose, clusterConfig):
    # Kill DAQRun
    cmd = "%s/DAQRun.py -k" % dashDir
    if verbose: print cmd
    if not dryRun: system(cmd)

    # Kill CnCServer
    cmd = "%s/CnCServer.py -k" % dashDir
    if verbose: print cmd
    if not dryRun: system(cmd)

    killJavaProcesses(dryRun, clusterConfig, verbose)
    
def doLaunch(dryRun, verbose, clusterConfig, dashDir,
             configDir, logDir, spadeDir, logPort, cncPort):
    # Start DAQRun
    if verbose:
        cmd = "%s/DAQRun.py -c %s -l %s -s %s -n &" % (dashDir, configDir, logDir, spadeDir)
        # Fixme - this is a little kludgy, but CnCServer won't log correctly if DAQRun isn't started.
        print cmd
        if not dryRun: system(cmd)
        sleep(5)
    else:
        cmd = "%s/DAQRun.py -c %s -l %s -s %s" % (dashDir, configDir, logDir, spadeDir)
        if not dryRun: system(cmd)

    # Start CnCServer
    if verbose:
        cmd = "%s/CnCServer.py -l localhost:9001 &" % dashDir
        print cmd
        if not dryRun: system(cmd)
    else:
        cmd = "%s/CnCServer.py -l localhost:9001 -d" % dashDir
        if not dryRun: system(cmd)

    startJavaProcesses(dryRun, clusterConfig, dashDir, logPort, cncPort, verbose)
            
def main():
    p = optparse.OptionParser()
    p.add_option("-c", "--config-name",  action="store", type="string", dest="clusterConfigName")
    p.add_option("-l", "--log-port",     action="store", type="int",    dest="logPort")
    p.add_option("-r", "--cnc-port",     action="store", type="int",    dest="cncPort")
    p.add_option("-n", "--dry-run",      action="store_true",           dest="dryRun")
    p.add_option("-s", "--skip-kill",    action="store_true",           dest="skipKill")
    p.add_option("-k", "--kill-only",    action="store_true",           dest="killOnly")
    p.add_option("-v", "--verbose",      action="store_true",           dest="verbose")
    p.set_defaults(clusterConfigName = "sim-localhost",
                   dryRun     = False,
                   verbose    = False,
                   logPort    = 9001,
                   cncPort    = 8080,
                   skipKill   = False,
                   killOnly   = False)
    opt, args = p.parse_args()

    configDir = abspath("../config")
    logDir    = abspath("../log")
    spadeDir  = abspath("../spade")
    dashDir   = abspath(".")
    clusterConfigDir = abspath("../cluster-config/src/main/xml")
    clusterConfig = deployConfig(clusterConfigDir, opt.clusterConfigName)

    if not exists(logDir):
        mkdir(logDir)
    else:
        system("rm -f %s/catchall.log" % logDir)
    
    if opt.verbose:
        print "NODES:"
        for node in clusterConfig.nodes:
            print "  %s(%s)" % (node.hostName, node.locName),
            for comp in node.comps:
                print "%s:%d " % (comp.compName, comp.compID),
            print

    if not opt.skipKill: doKill(opt.dryRun, dashDir, opt.verbose, clusterConfig)
    if not opt.killOnly: doLaunch(opt.dryRun, opt.verbose, clusterConfig,
                                  dashDir, configDir, logDir, spadeDir, opt.logPort, opt.cncPort)

if __name__ == "__main__": main()
