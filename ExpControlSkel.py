#!/usr/bin/env python

"""
Example use of DAQRunIface - starting and monitoring runs
John Jacobsen, jacobsen@npxdesigns.com
Started November, 2006
"""

from DAQRunIface import DAQRunIface
from datetime import *
from sys import argv
import optparse
import time

def updateStatus(oldStatus, newStatus):
    "Show any changes in status on stdout"
    if oldStatus != newStatus:
        print "%s: %s -> %s" % (datetime.now(), oldStatus, newStatus)
    return newStatus

def main():
    "Main program"
    p = optparse.OptionParser()
    p.add_option("-p", "--remote-port",      action="store", type="int",    dest="portNum")
    p.add_option("-r", "--remote-node",      action="store", type="string", dest="nodeName")
    p.add_option("-n", "--num-runs",         action="store", type="int",    dest="numRuns")
    p.add_option("-d", "--duration-seconds", action="store", type="int",    dest="duration")
    p.set_defaults(nodeName = "localhost",
                   numRuns  = 10000000,
                   portNum  = 9000,
                   duration = 300)
    opt, args = p.parse_args()

    
    # Connect to DAQ run server
    daqiface     = DAQRunIface(opt.nodeName, opt.portNum)

    subRunNumber = 0
    configName   = "hub1001sim"
    sleeptime    = 0.4
    lastState    = None
    try:
        for runNumber in xrange(1, opt.numRuns+1):
            # Start run
            print "Starting run %d" % runNumber
            daqiface.start(runNumber, configName)
            while 1:
                status = daqiface.getState()
                lastState = updateStatus(lastState, status)
                if status == "ERROR" :
                    daqiface.recover()
                if status == "RUNNING" or status == "STOPPED" : break
                time.sleep(sleeptime)

            if status == "STOPPED": continue # Restart if we had an error
            
            # Monitor run
            tstart = datetime.now()
            while True:
                tnow = datetime.now()
                if tnow-tstart > timedelta(seconds=opt.duration): break
                status = daqiface.getState()
                lastState = updateStatus(lastState, status)
                if(status == "ERROR"): break
                time.sleep(sleeptime)

            # Stop run, do error recovery if needed
            status = daqiface.getState()
            lastState = updateStatus(lastState, status)
            if(status == "ERROR"):
                daqiface.recover()
            else:
                daqiface.stop()
                
            while 1:
                status = daqiface.getState()
                lastState = updateStatus(lastState, status)
                if status == "STOPPED": break
                if status == "ERROR" : daqiface.recover()
                time.sleep(sleeptime)
        
    except Exception, e:
        daqiface.stop()
        print e
        raise SystemExit

    
if __name__ == "__main__": main()
