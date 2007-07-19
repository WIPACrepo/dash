#!/usr/bin/env python

"""
Example use of DAQRunIface - starting and monitoring runs
John Jacobsen, jacobsen@npxdesigns.com
Started November, 2006
"""

from DAQRunIface import DAQRunIface
from os.path import join, exists
from os import environ
from datetime import *
from sys import argv
from re import search
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

def showXML(daqruniface):
    try:
        print daqruniface.getSummary()
    except KeyboardInterrupt, k: raise
    except Exception, e:
        print "getSummary failed: %s" % e

class FlashingDOM:
    def __init__(self, bright, window, delay, mask, rate):
        self.bright = bright
        self.window = window
        self.delay  = delay
        self.mask   = mask
        self.rate   = rate
    def __str__(self): return "%d %d %d %s %d" % (self.bright, self.window, self.delay,
                                                  self.mask, self.rate)
        
class SubRun:
    FLASH = 1
    DELAY = 2
    def __init__(self, type, duration, id):
        self.type     = type
        self.duration = duration
        self.id       = id
        self.domdict  = {}
        
    def addDOM(self, mbid, bright, window, delay, mask, rate):
        self.domdict[ mbid ] = FlashingDOM(bright, window, delay, mask, rate)
        
    def __str__(self):
        type = "FLASHER"
        if self.type == SubRun.DELAY: type = "DELAY"
        s = "SubRun ID=%d TYPE=%s DURATION=%d\n" % (self.id, type, self.duration)
        if self.type == SubRun.FLASH:
            for m in self.domdict.keys():
                s += "DOM %s: %s\n" % (m, self.domdict[m])
        return s

    def flasherInfo(self):
        if self.type != SubRun.FLASH: return None
        l = []
        for d in self.domdict.keys():
            l.append((d,
                      self.domdict[d].bright,
                      self.domdict[d].window,
                      self.domdict[d].delay,
                      self.domdict[d].mask,
                      self.domdict[d].rate))
        return l
        
class SubRunSet:
    def __init__(self, fileName):
        self.subruns = []
        id = 0
        sr = None
        for l in open(fileName).readlines():
            # Look for bare "delay lines"
            m = search(r'delay (\d+)', l)
            if m:
                t = int(m.group(1))
                self.subruns.append(SubRun(SubRun.DELAY, t, id))
                id += 1
                sr = None
                continue
            
            m = search(r'flash (\d+)', l)
            if m:
                t = int(m.group(1))
                sr = SubRun(SubRun.FLASH, t, id)
                self.subruns.append(sr)
                id += 1
            m = search('(\S+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\d+)', l)
            if m and sr:
                mbid   = m.group(1)
                bright = int(m.group(2))
                window = int(m.group(3))
                delay  = int(m.group(4))
                mask   = int(m.group(5), 16)
                rate   = int(m.group(6))
                sr.addDOM(mbid, bright, window, delay, mask, rate)
                
    def __str__(self):
        s = ""
        for l in self.subruns:
            s += str(l)+"\n"
        return s

    def next(self):
        try:
            return self.subruns.pop(0)
        except IndexError:
            return None

def main():
    "Main program"
    p = optparse.OptionParser()
    p.add_option("-c", "--config-name",      action="store", type="string", dest="configName")
    p.add_option("-d", "--duration-seconds", action="store", type="int",    dest="duration")
    p.add_option("-f", "--flasher-run",      action="store", type="string", dest="flasherRun")
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
                   flasherRun  = None,
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

    # Check for valid flasher input file
    if opt.flasherRun and not exists(opt.flasherRun):
        print "Flasher file '%s' doesn't exist!" % opt.flasherRun
        raise SystemExit
    
    # Check for valid confuration name
    if not daqiface.isValidConfig(opt.configName):
        print "Run configuration %s does not exist or is not valid!" % opt.configName
        raise SystemExit

    subRunNumber = 0
    sleeptime    = 0.4
    xmlIval      = 5
    state        = None
    txml         = datetime.now()
    runNum       = startRunNum
    startTime    = None
    lastStateChg = None
    thisSubRun   = None
    subRunSet    = None

    try:
        while True:
            tnow = datetime.now()

            if state == None: # Get a well-defined state (probably STOPPED)
                state = updateStatus(state, daqiface.getState())
                
            if opt.showXML and (not txml or tnow-txml > timedelta(seconds=xmlIval)):
                showXML(daqiface)
                txml = tnow

            if state == "STOPPED": # Try to start run
                if runNum >= startRunNum + opt.numRuns: break
                subRunSet = None # Reset state of subruns
                print "Starting run %d..." % runNum
                setLastRunNum(runFile, runNum)
                try:
                    daqiface.start(runNum, opt.configName)
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
                
                doStop = False
                if not startTime or tnow-startTime > timedelta(seconds=opt.duration):
                    doStop = True

                if opt.flasherRun:
                    if lastStateChg == None: lastStateChg = tnow
                    # Prep subruns 
                    if subRunSet == None:
                        subRunSet = SubRunSet(opt.flasherRun)
                        thisSubRun = subRunSet.next()
                        if thisSubRun.type == SubRun.FLASH:
                            status = daqiface.flasher(thisSubRun.id, thisSubRun.flasherInfo())
                            if status == 0: print "WARNING: flasher op failed, check pDAQ logs!"
                        else:
                            pass # Don't explicitly send signal if first transition
                                 # is a delay
                    # Handle transitions            
                    dt = tnow - lastStateChg
                    if dt > timedelta(seconds=thisSubRun.duration):
                        print "-- subrun state change --"
                        thisSubRun = subRunSet.next()
                        if thisSubRun == None:
                            doStop = True
                        elif thisSubRun.type == SubRun.FLASH:
                            status = daqiface.flasher(thisSubRun.id, thisSubRun.flasherInfo())
                            if status == 0: print "WARNING: flasher op failed, check pDAQ logs!"
                        else:
                            status = daqiface.flasher(thisSubRun.id, [])
                            if status == 0: print "WARNING: flasher op failed, check pDAQ logs!"
                        lastStateChg = tnow

                if doStop:
                    try:
                        daqiface.stop()
                        state = updateStatus(state, daqiface.getState())
                        continue
                    except Exception, e:
                        print "Failed transition: %s" % e
                        state = "ERROR"
                    time.sleep(1)

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
            time.sleep(1)
            state = updateStatus(state, daqiface.getState())
            if state == "STOPPED": break
            if state != "STOPPING": daqiface.stop()
    print "Done."

    if opt.showXML:
        showXML(daqiface)
            
    daqiface.release()
    
if __name__ == "__main__": main()
