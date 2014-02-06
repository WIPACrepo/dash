#!/usr/bin/env python
#
# Sort all log files from a run, screen out some noise

import os
import re
import sys

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if "PDAQ_HOME" in os.environ:
    metaDir = os.environ["PDAQ_HOME"]
else:
    metaDir = None

    for p in ("pDAQ_current", "pDAQ_trunk"):
        homePDAQ = os.path.join(os.environ["HOME"], p)
        curDir = os.getcwd()
        [parentDir, baseName] = os.path.split(curDir)
        for d in [curDir, parentDir, homePDAQ]:
            # source tree has 'dash', 'src', and 'StringHub' (+ maybe 'target')
            # deployed tree has 'dash', 'src', and 'target'
            if os.path.isdir(os.path.join(d, 'dash')) and \
                    os.path.isdir(os.path.join(d, 'src')) and \
                    (os.path.isdir(os.path.join(d, 'target')) or
                     os.path.isdir(os.path.join(d, 'StringHub'))):
                metaDir = d
                break

        if metaDir is not None:
            break

    if metaDir is None:
        raise Exception("Couldn't find pDAQ trunk")

# add dash dir to Python library search path
sys.path.append(os.path.join(metaDir, 'dash'))

from ClusterDescription import ClusterDescription
from DAQTime import PayloadTime
from utils.DashXMLLog import DashXMLLog


class LogParseException(Exception):
    pass


class LogLevel(object):
    def __init__(self, level):
        if level is None or level.strip() == "":
            self.__level = -1
        else:
            lowlvl = level.strip().lower()
            if lowlvl == "-":
                self.__level = 0
            elif lowlvl == "trace":
                self.__level = 1
            elif lowlvl == "debug":
                self.__level = 2
            elif lowlvl == "info":
                self.__level = 3
            elif lowlvl == "warn":
                self.__level = 4
            elif lowlvl == "error":
                self.__level = 5
            elif lowlvl == "fatal":
                self.__level = 6
            else:
                raise ValueError("Unrecognized log level \"%s\"" % level)

    def __cmp__(self, other):
        return cmp(self.__level, other.__level)

    def __repr__(self):
        if self.__level == -1:
            return ""
        elif self.__level == 0:
            return "-"
        elif self.__level == 1:
            return "TRACE"
        elif self.__level == 2:
            return "DEBUG"
        elif self.__level == 3:
            return "INFO"
        elif self.__level == 4:
            return "WARN"
        elif self.__level == 5:
            return "ERROR"
        elif self.__level == 6:
            return "FATAL"

    def __str__(self):
        return repr(self)


class LogLine(object):
    def __init__(self, component, className, logLevel, date, text):
        self.__component = component
        self.__className = className
        self.__logLevel = LogLevel(logLevel)
        self.__date = date
        self.__text = text

    def __cmp__(self, other):
        val = cmp(self.__date, other.__date)
        if val == 0:
            val = cmp(self.__logLevel, other.__logLevel)
            if val == 0:
                val = cmp(self.__component, other.__component)
                if val == 0:
                    val = cmp(self.__className, other.__className)

        return val

    def __repr__(self):
        rtnstr = self.__component
        if self.__className is not None:
            rtnstr += " " + self.__className
        rtnstr += " " + str(self.__logLevel)
        rtnstr += " [" + str(self.__date) + "] " + self.__text
        return rtnstr

    def __str__(self):
        return repr(self)

    def append(self, line):
        self.__text += "\n" + line

    def setText(self, text):
        self.__text = text

    def text(self):
        return self.__text


class BaseLog(object):
    DATE_STR = r"(\d+-\d+-\d+ \d+:\d+:\d+\.\d+)"
    LINE_PAT = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+\[" + DATE_STR +
                          r"\]\s+(.*)$")
    DASH_PAT = re.compile(r"^(\S+)\s+\[" + DATE_STR + r"\]\s+(.*)$")

    LOGSTART_PAT = re.compile(r"Start of log at .*$")
    LOGVERS_PAT = re.compile(r"Version info: \S+ \S+ \S+ \S+Z? \S+ (\S+) (\S+)")

    def __init__(self, fileName):
        self.__fileName = fileName
        self.__relName = None
        self.__relNums = None

    def __str__(self):
        return self.__fileName

    def __gotVersionInfo(self, lobj):
        m = self.LOGVERS_PAT.match(lobj.text())
        if not m:
            return False

        (self.__relName, self.__relNums) = m.groups()
        return True

    def __parseLine(self, line):
        m = self.LINE_PAT.match(line)
        if m is not None:
            (component, className, logLevel, dateStr, text) = m.groups()
        else:
            m = self.DASH_PAT.match(line)
            if m is not None:
                (component, dateStr, text) = m.groups()
                (className, logLevel) = ("-", "-")
            else:
                return None

        try:
            date = PayloadTime.fromString(dateStr)
        except ValueError, ex:
            print "%s for \"%s\"" % (ex, line)
            return None

        return LogLine(component, className, logLevel, date, text)

    def _isNoise(self, lobj):
        raise Exception("Unimplemented for " + self.__fileName)

    def _isStart(self, lobj):
        m = self.LOGSTART_PAT.match(lobj.text())
        if m:
            return True

        return False

    def cleanup(self, lobj):
        pass

    def parse(self, path, verbose):
        log = []
        with open(path, 'r') as fd:
            prevobj = None
            for line in fd:
                line = line.rstrip()
                if len(line) == 0:
                    continue

                lobj = self.__parseLine(line)
                if lobj is not None:
                    if self.__gotVersionInfo(lobj):
                        if verbose:
                            log.append(lobj)
                    elif verbose or (not self._isStart(lobj) and
                                     not self._isNoise(lobj)):
                        log.append(lobj)

                    if prevobj is not None:
                        self.cleanup(prevobj)
                    prevobj = lobj
                elif prevobj is not None:
                    prevobj.append(line)
                else:
                    print "?? " + line

            if prevobj is not None:
                self.cleanup(prevobj)

        return log


class CatchallLog(BaseLog):
    CYCLE_PAT = re.compile(r"Cycling components \[(.*)\]$")
    CYCLE_PAT2 = re.compile(r"Cycling components \w[\w#\-, ]+$")
    LOGLINE_PAT = re.compile(r"(\S+) (\S+)" +
                             r" (\d+-\d+-\d+ \d+:\d+:\d+Z)" +
                             r" (\S+) (\S+) (\S+)$")
    REG_PAT = re.compile(r"Registered (\S+)$")
    SHUTHOOK_PAT = re.compile(r"ShutdownHook: moving temp file for (\S+)")

    def __init__(self, fileName):
        super(CatchallLog, self).__init__(fileName)

    def _isNoise(self, lobj):
        for pat in (self.CYCLE_PAT, self.CYCLE_PAT2, self.LOGLINE_PAT,
                    self.REG_PAT, self.SHUTHOOK_PAT):
            m = pat.match(lobj.text())
            if m:
                return True

        return False


class CnCServerLog(BaseLog):
    def __init__(self, fileName):
        super(CnCServerLog, self).__init__(fileName)

    def _isNoise(self, lobj):
        return False


class DashLog(BaseLog):
    RATES_PAT = re.compile(r"\d+ physics events(\s+\(\d+\.\d+ Hz\))?," +
                           r" \d+ moni events, \d+ SN events, \d+ tcals")

    def __init__(self, fileName, hideRates):
        super(DashLog, self).__init__(fileName)

        self.__hideRates = hideRates

    def _isNoise(self, lobj):
        if self.__hideRates:
            m = self.RATES_PAT.match(lobj.text())
            if m:
                return True

        return False


class EventBuilderLog(BaseLog):
    def __init__(self, fileName):
        super(EventBuilderLog, self).__init__(fileName)

    def _isNoise(self, lobj):
        return False


class GlobalTriggerLog(BaseLog):
    def __init__(self, fileName):
        super(GlobalTriggerLog, self).__init__(fileName)

    def _isNoise(self, lobj):
        return False


class LocalTriggerLog(BaseLog):
    def __init__(self, fileName):
        super(LocalTriggerLog, self).__init__(fileName)

    def _isNoise(self, lobj):
        return False


class SecondaryBuildersLog(BaseLog):
    def __init__(self, fileName):
        super(SecondaryBuildersLog, self).__init__(fileName)

    def _isNoise(self, lobj):
        return False


class StringHubLog(BaseLog):
    def __init__(self, fileName, showTCAL, hideSNGaps):
        super(StringHubLog, self).__init__(fileName)

        self.__showTCAL = showTCAL
        self.__hideSNGaps = hideSNGaps

    def _isNoise(self, lobj):
        if not self.__showTCAL and \
            (lobj.text().startswith("Wild TCAL") or
             lobj.text().find("Got IO exception") >= 0):
            return True

        if self.__hideSNGaps and \
                lobj.text().startswith("Gap or overlap in SN rec"):
            return True

        return False

    def cleanup(self, lobj):
        if lobj.text().find("Got IO exception") >= 0 and \
                lobj.text().find("TCAL read failed") > 0:
            lobj.setText("TCAL read failed")


class LogSorter(object):
    def __init__(self, dir=None, file=None, runNum=None):
        self.__dir = dir
        self.__file = file
        self.__runNum = runNum

    def __processDir(self, dirName, verbose, show_tcal, hide_rates,
                     hide_sn_gaps):
        log = None
        for f in os.listdir(dirName):
            # ignore MBean output files and run summary files
            if f.endswith(".moni") or f == "run.xml" or f == "logs-queued":
                continue

            path = os.path.join(dirName, f)

            if not os.path.isfile(path):
                continue

            flog = self.__processFile(path, verbose, show_tcal, hide_rates,
                                      hide_sn_gaps)
            if flog is not None:
                if log is None:
                    log = flog
                else:
                    log += flog

        return log

    def __processFile(self, path, verbose, show_tcal, hide_rates,
                      hide_sn_gaps):
        fileName = os.path.basename(path)

        log = None
        if not fileName.endswith(".log"):
            print "Ignoring \"%s\"" % path
        elif fileName.startswith("stringHub-"):
            log = StringHubLog(fileName, show_tcal, hide_sn_gaps)
        elif fileName.startswith("inIceTrigger-") or \
                fileName.startswith("iceTopTrigger-"):
            log = LocalTriggerLog(fileName)
        elif fileName.startswith("globalTrigger-"):
            log = GlobalTriggerLog(fileName)
        elif fileName.startswith("eventBuilder-"):
            log = EventBuilderLog(fileName)
        elif fileName.startswith("secondaryBuilders-"):
            log = SecondaryBuildersLog(fileName)
        elif fileName.startswith("catchall"):
            log = CatchallLog(fileName)
        elif fileName.startswith("cncserver"):
            log = CnCServerLog(fileName)
        elif fileName.startswith("dash"):
            log = DashLog(fileName, hide_rates)
        else:
            print >> sys.stderr, "Unknown log file \"%s\"" % path

        if log is None:
            return None

        return log.parse(path, verbose)

    def dumpRun(self, verbose, show_tcal, hide_rates, hide_sn_gaps):
        runDir = os.path.join(self.__dir, self.__file)
        try:
            runXML = DashXMLLog.parse(runDir)
        except:
            runXML = None

        if runXML is None:
            cond = ""
        else:
            if runXML.getTermCond():
                cond = "ERROR"
            else:
                cond = "SUCCESS"

            delta = runXML.getEndTime() - runXML.getStartTime()
            secs = float(delta.seconds) + \
                (float(delta.microseconds) / 1000000.0)

        if cond == "ERROR":
            print "-v-v-v-v-v-v-v-v-v-v ERROR v-v-v-v-v-v-v-v-v-v-"
        if runXML is not None:
            print "Run %s: %s, %d evts, %s secs" % \
                (runXML.getRun(), cond, runXML.getEvents(), secs)
            print "    %s" % runXML.getConfig()
            print "    from %s to %s" % \
                (runXML.getStartTime(), runXML.getEndTime())
        log = self.__processDir(runDir, verbose, show_tcal, hide_rates,
                                hide_sn_gaps)
        log.sort()
        for l in log:
            print str(l)
        if cond == "ERROR":
            print "-^-^-^-^-^-^-^-^-^-^ ERROR ^_^_^_^_^_^_^_^_^_^_"

if __name__ == "__main__":
    import optparse

    def getDirAndRunnum(arg, rundir):
        for i in xrange(100):
            if i == 0:
                fullpath = os.path.join(rundir, arg)
            elif i == 1:
                fullpath = arg
            elif i == 2:
                fullpath = os.path.join(rundir, "daqrun" + arg)
            elif i == 3:
                fullpath = "daqrun" + arg
            else:
                break

            if os.path.isdir(fullpath):
                filename = os.path.basename(fullpath)
                if filename.startswith("daqrun"):
                    numstr = filename[6:]
                else:
                    numstr = filename
                try:
                    return(os.path.dirname(fullpath), filename, int(numstr))
                except:
                    pass

        return (None, None, None)

    p = optparse.OptionParser()
    p.add_option("-d", "--rundir", dest="rundir",
                 action="store", default=None,
                 help="Directory holding pDAQ run monitoring and log files")
    p.add_option("-r", "--hide-rates", dest="hide_rates",
                 action="store_true", default=False,
                 help="Hide pDAQ event rate lines")
    p.add_option("-s", "--hide-sn-gaps", dest="hide_sn_gaps",
                 action="store_true", default=False,
                 help="Hide StringHub Supernova gap errors")
    p.add_option("-t", "--show-tcal", dest="show_tcal",
                 action="store_true", default=False,
                 help="Show StringHub TCAL errors")
    p.add_option("-v", "--verbose", dest="verbose",
                 action="store_true", default=False,
                 help="Print running commentary of program's progress")

    opt, args = p.parse_args()

    if len(args) == 0:
        raise SystemExit("Please specify one or more run numbers")

    if opt.rundir is not None:
        runDir = opt.rundir
    else:
        cd = ClusterDescription()
        runDir = cd.daqLogDir()

    for arg in args:
        (dirname, filename, runnum) = getDirAndRunnum(arg, runDir)
        if dirname is None or filename is None or runnum is None:
            p.error("Bad run number \"%s\"" % arg)
            continue

        ls = LogSorter(dirname, filename, runnum)
        ls.dumpRun(opt.verbose, opt.show_tcal, opt.hide_rates,
                   opt.hide_sn_gaps)
