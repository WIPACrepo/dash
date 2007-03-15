#!/usr/bin/env python

"""
Example use of DAQRunIface - starting and monitoring runs
John Jacobsen, jacobsen@npxdesigns.com
Started November, 2006
"""

from DAQRunIface import DAQRunIface
from os.path import join
from os import environ
from datetime import *
from sys import argv
import optparse
import time

def updateStatus(oldStatus, newStatus):
    "Show any changes in status on stdout"
    if oldStatus != newStatus:
        print "%s: %s -> %s" % (datetime.now(), oldStatus, newStatus)
    return newStatus

def setLastRunNum(runFile, runNum):
    fd = open(runFile, 'w')
    print >>fd, runNum
    fd.close()
    
def getLastRunNum(runFile):
    try:
        f = open(runFile, "r")
        ret = f.readline()
        f.close()
        return int(ret.rstrip('\r\n'))
    except:
        return None

def main():
    "Main program"
    p = optparse.OptionParser()
    p.add_option("-c", "--config-name", action="store", type="string",      dest="configName")
    p.add_option("-d", "--duration-seconds", action="store", type="int",    dest="duration")
    p.add_option("-n", "--num-runs",         action="store", type="int",    dest="numRuns")
    p.add_option("-p", "--remote-port",      action="store", type="int",    dest="portNum")
    p.add_option("-r", "--remote-node",      action="store", type="string", dest="nodeName")
    p.add_option("-s", "--starting-run",     action="store", type="int",    dest="startRunNum",
                 help="Run number to start with")
    
    p.add_option("-x", "--show-status-xml",  action="store_true",           dest="showXML")
    p.set_defaults(nodeName    = "localhost",
                   numRuns     = 10000000,
                   portNum     = 9000,
                   duration    = 300,
                   showXML     = False,
                   startRunNum = None,
                   configName  = "hub1001sim")
    opt, args = p.parse_args()

    runFile = join(environ[ "HOME" ], ".last_pdaq_run")
    
    startRunNum = 1
    lastRunNum = getLastRunNum(runFile)
    if lastRunNum != None: startRunNum = lastRunNum + 1
    if opt.startRunNum: startRunNum = opt.startRunNum

    if startRunNum < 1: raise Exception("Starting run number must be > 0, got %s!" % startRunNum);
    
    # Connect to DAQ run server
    daqiface     = DAQRunIface(opt.nodeName, opt.portNum)

    subRunNumber = 0
    configName   = opt.configName
    sleeptime    = 0.4
    xmlIval      = 10
    state        = None
    txml         = None
    runNum       = startRunNum
    startTime    = None

    try:
        while True:
            if state == None: # Get a well-defined state
                state = updateStatus(state, daqiface.getState())
            if state == "STOPPED": # Try to start run
                if runNum >= startRunNum + opt.numRuns: raise SystemExit
                print "Starting run %d..." % runNum
                setLastRunNum(runFile, runNum)
                try:
                    daqiface.start(runNum, configName)
                    startTime = datetime.now()
                    runNum += 1
                    state = updateStatus(state, daqiface.getState())
                except Exception, e:
                    print "Failed transition: %s" % e
                    state = "ERROR"
            if state == "STARTING" or state == "RECOVERING" or state == "STOPPING":
                time.sleep(1)
                state = updateStatus(state, daqiface.getState())
            if state == "RUNNING":
                tnow = datetime.now()
                if not startTime or tnow-startTime > timedelta(seconds=opt.duration):
                    try:
                        daqiface.stop()
                        state = updateStatus(state, daqiface.getState())
                        continue
                    except Exception, e:
                        print "Failed transition: %s" % e
                        state = "ERROR"
                    time.sleep(1)

                if opt.showXML and (not txml or tnow-txml > timedelta(seconds=xmlIval)):
                    try:
                        print daqiface.getSummary()
                    except KeyboardInterrupt, k: raise
                    except Exception, e:
                        print "getSummary failed: %s" % e
                        daqiface.recover()
                        hadError = True
                        break
                    txml = tnow

                time.sleep(sleeptime)
                state = updateStatus(state, daqiface.getState())

            if state == "ERROR":
                try:
                    daqiface.recover()
                    state = updateStatus(state, daqiface.getState())
                except Exception, e:
                    print "Failed transition: %s" % e
                    raise SystemExit
    except KeyboardInterrupt:
        print "\nInterrupted... sending stop signal..."
        daqiface.stop()
        while True:
            state = updateStatus(state, daqiface.getState())
            time.sleep(sleeptime)
            if state == "STOPPED": break
    print "Done."

    daqiface.release()
    
if __name__ == "__main__": main()
