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
    lastState    = None

    try:
        for runNumber in xrange(startRunNum, opt.numRuns+startRunNum):
            # Start run
            print "Starting run %d" % runNumber
            setLastRunNum(runFile, runNumber)
            try:
                daqiface.start(runNumber, configName)
                while 1:
                    status = daqiface.getState()
                    lastState = updateStatus(lastState, status)
                    if status == "ERROR" : daqiface.recover()
                    if status == "RUNNING" or status == "STOPPED" : break
                    time.sleep(sleeptime)
            except KeyboardInterrupt, k:
                print "\nKeyboard interrupt before start."
                raise SystemExit
            except Exception, e:
                print "Run start failed: %s" % e
                daqiface.recover() # If recovery throws an exception then we're hosed
                continue

            if status == "STOPPED": continue # Restart if we had an error

            # Monitor run
            tstart   = datetime.now()
            txml     = None
            hadError = False
            while True:
                tnow = datetime.now()
                if tnow-tstart > timedelta(seconds=opt.duration): break
                try:
                    status = daqiface.getState()
                except KeyboardInterrupt, k: raise
                except Exception, e:
                    print "Get status failed: %s" % e
                    daqiface.recover()
                    hadError = True
                    break

                lastState = updateStatus(lastState, status)
                if(status == "ERROR"): break
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

            if hadError: continue # Restart run if something failed

            # Stop run, do error recovery if needed
            try:
                status = daqiface.getState()
            except KeyboardInterrupt, k: raise
            except Exception, e:
                print "Get status failed: %s" % e
                daqiface.recover()
                continue

            lastState = updateStatus(lastState, status)
            if(status == "ERROR"):
                daqiface.recover()
                continue
            else:
                try:
                    daqiface.stop()
                except KeyboardInterrupt, k: raise
                except Exception, e:
                    print "Stop operation failed: %s" % e
                    daqiface.recover()
                    continue

            while 1:
                try:
                    status = daqiface.getState()
                except KeyboardInterrupt, k: raise
                except Exception, e:
                    print "Get state failed: %s" % e
                    daqiface.recover()
                    continue
                lastState = updateStatus(lastState, status)
                if status == "STOPPED": break
                if status == "ERROR" :
                    daqiface.recover()
                    continue

                time.sleep(sleeptime)
    except KeyboardInterrupt, k:
        daqiface.stop()
        raise SystemExit
    
    daqiface.release()
    
if __name__ == "__main__": main()
