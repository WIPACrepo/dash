#!/usr/bin/env python

"""
Example use of DAQRunIface - starting and monitoring runs
John Jacobsen, jacobsen@npxdesigns.com
Started November, 2006
"""

import re
import sys
from BaseRun import FlasherScript
from cncrun import CnCRun
from datetime import datetime
from utils.Machineid import Machineid

SVN_ID = "$Id: ExpControlSkel.py 15762 2015-09-15 17:01:14Z dglo $"


class DOMArgumentException(Exception):
    pass


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


class SubRun(object):
    FLASH = 1
    DELAY = 2

    def __init__(self, runtype, duration, runid):
        self.type = runtype
        self.duration = duration
        self.id = runid
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


def add_arguments(parser, config_as_arg=False):
    parser.add_argument("-C", "--cluster-desc", dest="clusterDesc",
                        help="Cluster description name.")
    if config_as_arg:
        parser.add_argument("-c", "--config-name", dest="runConfig",
                            required=True,
                            help="REQUIRED: Configuration name")
    else:
        parser.add_argument("-c", dest="minusC",
                            action="store_true", default=False,
                            help="Ignored, run config is a positional param")
        parser.add_argument("runConfig",
                            help="Run configuration name")
    parser.add_argument("-d", "--duration-seconds", dest="duration",
                        default="8h",
                        help="Run duration (in seconds)")
    parser.add_argument("-f", "--flasher-script", dest="flasherScript",
                        help="Name of flasher script")
    parser.add_argument("-l", dest="duration",
                        default="8h",
                        help="Run duration (in seconds)")
    parser.add_argument("-n", "--num-runs", type=int, dest="numRuns",
                        default=10000000,
                        help="Number of runs")
    parser.add_argument("-r", "--remote-host", dest="remoteHost",
                        default="localhost",
                        help="Name of host on which CnCServer is running")
    parser.add_argument("-R", "--runsPerRestart", type=int,
                        dest="runsPerRestart",
                        default=1,
                        help="Number of runs per restart")
    parser.add_argument("-s", "--showCommands", dest="showCmd",
                        action="store_true", default=False,
                        help="Show the commands used to deploy and/or run")
    parser.add_argument("-x", "--showCommandOutput", dest="showCmdOut",
                        action="store_true", default=False,
                        help=("Show the output of the deploy and/or"
                              " run commands"))
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        default=False,
                        help=("Disable checking the host type for"
                              " run permission"))


# stolen from live/misc/util.py
def getDurationFromString(s):
    """
    Return duration in seconds based on string <s>
    """
    m = re.search(r'^(\d+)$', s)
    if m:
        return int(m.group(1))
    m = re.search(r'^(\d+)s(?:ec(?:s)?)?$', s)
    if m:
        return int(m.group(1))
    m = re.search(r'^(\d+)m(?:in(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r'^(\d+)h(?:r(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 3600
    m = re.search(r'^(\d+)d(?:ay(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 86400
    raise ValueError('String "%s" is not a known duration format.  Try'
                     '30sec, 10min, 2days etc.' % s)


def updateStatus(oldStatus, newStatus):
    "Show any changes in status on stdout"
    if oldStatus != newStatus:
        print "%s: %s -> %s" % (datetime.now(), oldStatus, newStatus)
    return newStatus


def daqrun(args):
    if not args.nohostcheck:
        hostid = Machineid()
        if not (hostid.is_control_host() or
                (hostid.is_unknown_host() and hostid.is_unknown_cluster())):
            # to run daq launch you should either be a control host or
            # a totally unknown host
            raise SystemExit("Are you sure you are running ExpControlSkel "
                             "on the correct host?")

    if args.runConfig is None:
        raise SystemExit("You must specify a run configuration ( -c option )")

    if args.flasherScript is None:
        flashData = None
    else:
        flashData = FlasherScript.parse(args.flasherScript)

    cnc = CnCRun(showCmd=args.showCmd, showCmdOutput=args.showCmdOut)

    clusterCfg = cnc.getActiveClusterConfig()
    if clusterCfg is None:
        raise SystemExit("Cannot determine cluster configuration")

    duration = getDurationFromString(args.duration)

    n = 0
    while n < args.numRuns:
        run = cnc.createRun(None, args.runConfig, clusterDesc=args.clusterDesc,
                            flashData=flashData)
        run.start(duration, numRuns=args.runsPerRestart)

        try:
            try:
                run.wait()
            except KeyboardInterrupt:
                print "Run interrupted by user"
                break
        finally:
            print >>sys.stderr, "Stopping run..."
            run.finish()

        n += args.runsPerRestart


if __name__ == "__main__":
    "Main program"
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    daqrun(args)
