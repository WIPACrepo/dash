#!/usr/bin/env python

"""
Example use of DAQRunIface - starting and monitoring runs
John Jacobsen, jacobsen@npxdesigns.com
Started November, 2006
"""

import optparse
import os
import re
import sys
from BaseRun import FlasherShellScript
from cncrun import CnCRun
from datetime import datetime
from locate_pdaq import find_pdaq_trunk
from utils.Machineid import Machineid

# add meta-project python dir to Python library search path
metaDir = find_pdaq_trunk()
sys.path.append(os.path.join(metaDir, 'src', 'main', 'python'))
from SVNVersionInfo import get_version_info

SVN_ID = "$Id: ExpControlSkel.py 14380 2013-04-01 22:08:36Z mnewcomb $"


class DOMArgumentException(Exception):
    pass


def updateStatus(oldStatus, newStatus):
    "Show any changes in status on stdout"
    if oldStatus != newStatus:
        print "%s: %s -> %s" % (datetime.now(), oldStatus, newStatus)
    return newStatus


def setLastRunNum(runFile, runNum):
    with open(runFile, 'w') as fd:
        print >>fd, runNum


def getLastRunNum(runFile):
    try:
        with open(runFile, 'r') as f:
            ret = f.readline()
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
            self.pos = args[1]
            self.bright = args[2]
            self.window = args[3]
            self.delay = args[4]
            self.mask = args[5]
            self.rate = args[6]
            self.mbid = None
        elif len(args) == 6:
            self.string = None
            self.pos = None
            self.mbid = args[0]
            self.bright = args[1]
            self.window = args[2]
            self.delay = args[3]
            self.mask = args[4]
            self.rate = args[5]
        else:
            raise DOMArgumentException()

    def flasherInfo(self):
        if self.mbid is not None:
            return (self.mbid, self.bright, self.window,
                    self.delay, self.mask, self.rate)
        elif self.string is not None and self.pos is not None:
            return (self.string, self.pos, self.bright, self.window,
                    self.delay, self.mask, self.rate)
        else:
            raise DOMArgumentException()

    def flasherHash(self):
        if self.mbid is not None:
            return {"MBID": self.mbid,
                    "brightness": self.bright,
                    "window": self.window,
                    "delay": self.delay,
                    "mask": str(self.mask),
                    "rate": self.rate}
        elif self.string is not None and self.pos is not None:
            return {"stringHub": self.string,
                    "domPosition": self.pos,
                    "brightness": self.bright,
                    "window": self.window,
                    "delay": self.delay,
                    "mask": str(self.mask),
                    "rate": self.rate}
        else:
            raise DOMArgumentException()


class SubRun:
    FLASH = 1
    DELAY = 2

    def __init__(self, type, duration, id):
        self.type = type
        self.duration = duration
        self.id = id
        self.domlist = []

    def addDOM(self, d):
        #self.domlist.append(SubRunDOM(string, pos,  bright, window, delay,
        #                              mask, rate))
        raise NotImplementedError(("source for SubRunDOM class"
                                   "parameters not known"))

    def __str__(self):
        typ = "FLASHER"
        if self.type == SubRun.DELAY:
            typ = "DELAY"

        s = "SubRun ID=%d TYPE=%s DURATION=%d\n" % (self.id,
                                                    typ,
                                                    self.duration)
        if self.type == SubRun.FLASH:
            for m in self.domlist:
                s += "%s\n" % m
        return s

    def flasherInfo(self):
        if self.type != SubRun.FLASH:
            return None

        return [d.flasherInfo() for d in self.domlist]

    def flasherDictList(self):
        return [d.flasherHash() for d in self.domlist]


def main():
    "Main program"
    ver_info = "%(filename)s %(revision)s %(date)s %(time)s %(author)s "\
               "%(release)s %(repo_rev)s" % get_version_info(SVN_ID)
    usage = "%prog [options]\nversion: " + ver_info
    p = optparse.OptionParser(usage=usage, version=ver_info)

    p.add_option("-C", "--cluster-desc", type="string", dest="clusterDesc",
                 action="store", default=None,
                 help="Cluster description name.")
    p.add_option("-c", "--config-name",  type="string", dest="runConfig",
                 action="store", default=None,
                 help="Run configuration name")
    p.add_option("-d", "--duration-seconds", type="string", dest="duration",
                 action="store", default="300",
                 help="Run duration (in seconds)")
    p.add_option("-f", "--flasher-script", type="string", dest="flasherScript",
                 action="store", default=None,
                 help="Name of flasher script")
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
    p.add_option("-m", "--no-host-check", dest="nohostcheck", default=False,
                 help="Disable checking the host type for run permission")
    opt, args = p.parse_args()

    if not opt.nohostcheck:
        hostid = Machineid()
        if(not (hostid.is_control_host() or
           (hostid.is_unknown_host() and hostid.is_unknown_cluster()))):
            # to run daq launch you should either be a control host or
            # a totally unknown host
            raise SystemExit("Are you sure you are running ExpControlSkel "
                             "on the correct host?")

    if opt.runConfig is None:
        raise SystemExit("You must specify a run configuration ( -c option )")

    if opt.flasherScript is None:
        flashData = None
    else:
        with open(opt.flasherScript, "r") as fd:
            flashData = FlasherShellScript.parse(fd)

    cnc = CnCRun(showCmd=opt.showCmd, showCmdOutput=opt.showCmdOut)

    clusterCfg = cnc.getActiveClusterConfig()
    if clusterCfg is None:
        raise SystemExit("Cannot determine cluster configuration")

    duration = getDurationFromString(opt.duration)

    for r in xrange(opt.numRuns):
        run = cnc.createRun(None, opt.runConfig, clusterDesc=opt.clusterDesc,
                            flashData=flashData)
        run.start(duration)

        try:
            try:
                run.wait()
            except KeyboardInterrupt:
                print "Run interrupted by user"
                break
        finally:
            print >>sys.stderr, "Stopping run..."
            run.finish()

if __name__ == "__main__":
    main()
