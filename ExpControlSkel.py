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
from re import search
import optparse
import time
import sys

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info


SVN_ID = "$Id: ExpControlSkel.py 3516 2008-09-30 22:14:06Z dglo $"

class DOMArgumentException(Exception): pass

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
    except KeyboardInterrupt: raise
    except Exception, e:
        print "getSummary failed: %s" % e

class DOM:
    def __init__(self, *args):
        if len(args) == 7:
            self.string = args[0]
            self.pos    = args[1]
            self.bright = args[2]
            self.window = args[3]
            self.delay  = args[4]
            self.mask   = args[5]
            self.rate   = args[6]
            self.mbid   = None
        elif len(args) == 6:
            self.string = None
            self.pos    = None
            self.mbid   = args[0]
            self.bright = args[1]
            self.window = args[2]
            self.delay  = args[3]
            self.mask   = args[4]
            self.rate   = args[5]
        else:
            raise DOMArgumentException()
        
    def flasherInfo(self):
        if self.mbid != None:
            return (self.mbid, self.bright, self.window, self.delay, self.mask, self.rate)
        elif self.string != None and self.pos != None:
            return (self.string, self.pos, self.bright, self.window, self.delay, self.mask, self.rate)
        else:
            raise DOMArgumentException()

    def flasherHash(self):
        if self.mbid != None:
            return {"MBID"        : self.mbid,
                    "brightness"  : self.bright,
                    "window"      : self.window,
                    "delay"       : self.delay,
                    "mask"        : str(self.mask),
                    "rate"        : self.rate }
        elif self.string != None and self.pos != None:
            return {"stringHub"   : self.string,
                    "domPosition" : self.pos,
                    "brightness"  : self.bright,
                    "window"      : self.window,
                    "delay"       : self.delay,
                    "mask"        : str(self.mask),
                    "rate"        : self.rate }
        else:
            raise DOMArgumentException()
                    
class SubRun:
    FLASH = 1
    DELAY = 2
    def __init__(self, type, duration, id):
        self.type     = type
        self.duration = duration
        self.id       = id
        self.domlist  = []
        
    def addDOM(self, d):
        self.domlist.append(d)
        
    def __str__(self):
        typ = "FLASHER"
        if self.type == SubRun.DELAY: typ = "DELAY"
        s = "SubRun ID=%d TYPE=%s DURATION=%d\n" % (self.id, typ, self.duration)
        if self.type == SubRun.FLASH:
            for m in self.domlist:
                s += "%s\n" % m
        return s

    def flasherInfo(self):
        if self.type != SubRun.FLASH: return None
        return [d.flasherInfo() for d in self.domlist]

    def flasherDictList(self):
        return [d.flasherHash() for d in self.domlist]
                
class SubRunSet:
    def __init__(self, fileName):
        self.subruns = []
        num = 0
        sr = None
        for l in open(fileName).readlines():
            # Look for bare "delay lines"
            m = search(r'delay (\d+)', l)
            if m:
                t = int(m.group(1))
                self.subruns.append(SubRun(SubRun.DELAY, t, num))
                num += 1
                sr = None
                continue
            
            m = search(r'flash (\d+)', l)
            if m:
                t = int(m.group(1))
                sr = SubRun(SubRun.FLASH, t, num)
                self.subruns.append(sr)
                num += 1
            m6 = search('^\s*(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s*$', l)
            m7 = search('^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s*$', l)
            if m7 and sr:
                string = int(m7.group(1))
                pos    = int(m7.group(2))
                bright = int(m7.group(3))
                window = int(m7.group(4))
                delay  = int(m7.group(5))
                mask   = int(m7.group(6), 16)
                rate   = int(m7.group(7))
                sr.addDOM(DOM(string, pos,  bright, window, delay, mask, rate))
            elif m6 and sr:
                mbid   = m6.group(1)
                bright = int(m6.group(2))
                window = int(m6.group(3))
                delay  = int(m6.group(4))
                mask   = int(m6.group(5), 16)
                rate   = int(m6.group(6))
                sr.addDOM(DOM(mbid, bright, window, delay, mask, rate))
                
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
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s "\
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

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
                            print str(thisSubRun.flasherDictList())
                            status = daqiface.flasher(thisSubRun.id, thisSubRun.flasherDictList())
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
                            print str(thisSubRun.flasherDictList())
                            status = daqiface.flasher(thisSubRun.id, thisSubRun.flasherDictList())
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
