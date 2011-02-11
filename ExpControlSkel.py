#!/usr/bin/env python

"""
Example use of DAQRunIface - starting and monitoring runs
John Jacobsen, jacobsen@npxdesigns.com
Started November, 2006
"""

import optparse, os, re, sys
from cncrun import CnCRun
import time
from datetime import datetime

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if os.environ.has_key("PDAQ_HOME"):
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()

# add meta-project python dir to Python library search path
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID = "$Id: ExpControlSkel.py 12653 2011-02-11 22:10:30Z mnewcomb $"

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

# stolen from live/misc/util.py
def getDurationFromString(s):
    """
    Return duration in seconds based on string <s>
    """
    m = re.search('^(\d+)$', s)
    if m:
        return int(m.group(1))
    m = re.search('^(\d+)s(?:ec(?:s)?)?$', s)
    if m:
        return int(m.group(1))
    m = re.search('^(\d+)m(?:in(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 60
    m = re.search('^(\d+)h(?:r(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 3600
    m = re.search('^(\d+)d(?:ay(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 86400
    raise ValueError('String "%s" is not a known duration format.  Try'
                     '30sec, 10min, 2days etc.' % s)

class SubRunDOM(object):
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
        #self.domlist.append(SubRunDOM(string, pos,  bright, window, delay,
        #                              mask, rate))
        raise NotImplementedError("source for SubRunDOM class parameters not known")


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
    """This class is not instantiated anywhere, and had some import errors
    in it.  It's probably not been used in a long time.  Consider removing
    this if no one uses it for a while longer.
    2/11/2011
    """
    def __init__(self, fileName):
        self.subruns = []
        num = 0
        sr = None
        for l in open(fileName).readlines():
            # Look for bare "delay lines"
            m = re.search(r'delay (\d+)', l)
            if m:
                t = int(m.group(1))
                self.subruns.append(SubRun(SubRun.DELAY, t, num))
                num += 1
                sr = None
                continue

            m = re.search(r'flash (\d+)', l)
            if m:
                t = int(m.group(1))
                sr = SubRun(SubRun.FLASH, t, num)
                self.subruns.append(sr)
                num += 1
            m6 = re.search('^\s*(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s*$', l)
            m7 = re.search('^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\d+)\s*$', l)
            if m7 and sr:
                string = int(m7.group(1))
                pos    = int(m7.group(2))
                bright = int(m7.group(3))
                window = int(m7.group(4))
                delay  = int(m7.group(5))
                mask   = int(m7.group(6), 16)
                rate   = int(m7.group(7))
                sr.addDOM(string, pos,  bright, window, delay, mask, rate)
            elif m6 and sr:
                mbid   = m6.group(1)
                bright = int(m6.group(2))
                window = int(m6.group(3))
                delay  = int(m6.group(4))
                mask   = int(m6.group(5), 16)
                rate   = int(m6.group(6))
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
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s "\
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-c", "--config-name",  type="string", dest="runConfig",
                 action="store", default=None,
                 help="Run configuration name")
    p.add_option("-d", "--duration-seconds", type="string", dest="duration",
                 action="store", default="300",
                 help="Run duration (in seconds)")
    p.add_option("-f", "--flasher-run", type="string", dest="flasherRun",
                 action="store", default=None,
                 help="Name of flasher run configuration file")
    p.add_option("-n", "--num-runs", type="int", dest="numRuns",
                 action="store", default=10000000,
                 help="Number of runs")
    p.add_option("-r", "--remote-host", type="string", dest="remoteHost",
                 action="store", default="localhost",
                 help="Name of host on which CnCServer is running")
    p.add_option("-s", "--showCommands", dest="showCmd",
                 action="store_true", default=False,
                 help="Show the commands used to deploy and/or run")
    p.add_option("-x", "--showCommandOutput", dest="showCmdOut",
                 action="store_true", default=False,
                 help="Show the output of the deploy and/or run commands")
    opt, args = p.parse_args()

    cnc = CnCRun(showCmd=opt.showCmd, showCmdOutput=opt.showCmdOut)

    clusterCfg = cnc.getActiveClusterConfig()
    if clusterCfg is None:
        raise SystemExit("Cannot determine cluster configuration")

    duration = getDurationFromString(opt.duration)

    for r in range(opt.numRuns):
        run = cnc.createRun(None, opt.runConfig, flashName=opt.flasherRun)
        if opt.flasherRun is None:
            run.start(duration)
        else:
            #run.start(duration, flashTimes, flashPause, False)
            raise SystemExit("flasher runs with ExpControSkel not implemented")
        
        try:
            try:
                run.wait()
            except KeyboardInterrupt:
                print "Run interrupted by user"
                break
        finally:
            print >>sys.stderr, "Stopping run..."
            run.finish()

if __name__ == "__main__": main()
