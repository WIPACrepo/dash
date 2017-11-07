#!/usr/bin/env python
#
# Sort all log files from a run, screen out some noise

import os
import re
import sys

from ClusterDescription import ClusterDescription
from DAQTime import DAQDateTime, PayloadTime
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


class BadLine(LogLine):
    def __init__(self, text):
        super(BadLine, self).__init__("??", None, "ERROR",
                                      DAQDateTime(0, 0, 0, 0, 0, 0, 0), text)


class BaseLog(object):
    DATE_STR = r"(\d+-\d+-\d+ \d+:\d+:\d+\.\d+)"
    LINE_PAT = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+\[" + DATE_STR +
                          r"\]\s+(.*)$")
    DASH_PAT = re.compile(r"^(\S+)\s+\[" + DATE_STR + r"\]\s+(.*)$")

    LOGSTART_PAT = re.compile(r"Start of log at .*$")
    OLDVERS_PAT = re.compile(r"Version info: \S+ \S+ \S+ \S+Z? \S+ (\S+)"
                             " (\S+)")
    LOGVERS_PAT = re.compile(r"Version info: (\S+) (\S+) \S+ \S+Z?")

    def __init__(self, fileName):
        self.__fileName = fileName
        self.__relName = None
        self.__relNums = None

    def __str__(self):
        return self.__fileName

    def __gotVersionInfo(self, lobj):
        m = self.LOGVERS_PAT.match(lobj.text())
        if m:
            (self.__relName, self.__relNums) = m.groups()
            return True

        m = self.OLDVERS_PAT.match(lobj.text())
        if m:
            (self.__relName, self.__relNums) = m.groups()
            return True

        return False

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
        except ValueError:
            return BadLine(line)

        return LogLine(component, className, logLevel, date, text)

    def _isNoise(self, _):
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
                    log.append(BadLine(line))

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

    def __init__(self, fileName, hide_rates=False):
        super(DashLog, self).__init__(fileName)

        self.__hideRates = hide_rates

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
    def __init__(self, fileName, show_tcal=False, hide_sn_gaps=False,
                 show_lbmdebug=False):
        super(StringHubLog, self).__init__(fileName)

        self.__showTCAL = show_tcal
        self.__hideSNGaps = hide_sn_gaps
        self.__showLBMDebug = show_lbmdebug

    def _isNoise(self, lobj):
        if not self.__showTCAL and \
            (lobj.text().startswith("Wild TCAL") or
             lobj.text().find("Got IO exception") >= 0 or
             lobj.text().find("Ignoring tcal error") >= 0):
            return True

        if not self.__showLBMDebug and \
            (lobj.text().startswith("HISTORY:") or
             lobj.text().find("data collection stats") >= 0):
            return True

        if self.__hideSNGaps and \
                lobj.text().startswith("Gap or overlap in SN rec"):
            return True

        return False

    def cleanup(self, lobj):
        if lobj.text().find("Got IO exception") >= 0 and \
                lobj.text().find("TCAL read failed") > 0:
            lobj.setText("TCAL read failed")
        elif lobj.text().find("Ignoring tcal error") >= 0 and \
             lobj.text().find("TCAL read failed") > 0:
            lobj.setText("TCAL read failed")


class ReplayHubLog(BaseLog):
    def __init__(self, fileName):
        super(ReplayHubLog, self).__init__(fileName)

    def _isNoise(self, lobj):
        return False


class LogSorter(object):
    def __init__(self, runDir=None, runNum=None):
        self.__runDir = runDir
        self.__runNum = runNum

    def __processDir(self, dirName, verbose=False, show_tcal=False,
                     hide_rates=False, hide_sn_gaps=False,
                     show_lbmdebug=False):
        log = None
        for f in os.listdir(dirName):
            # ignore MBean output files and run summary files
            if f.endswith(".moni") or f == "run.xml" or f == "logs-queued":
                continue

            path = os.path.join(dirName, f)

            if not os.path.isfile(path):
                continue

            flog = self.__processFile(path, verbose=verbose,
                                      show_tcal=show_tcal,
                                      hide_rates=hide_rates,
                                      hide_sn_gaps=hide_sn_gaps,
                                      show_lbmdebug=show_lbmdebug)
            if flog is not None:
                if log is None:
                    log = flog
                else:
                    log += flog

        return log

    def __processFile(self, path, verbose=False, show_tcal=False,
                      hide_rates=False, hide_sn_gaps=False,
                      show_lbmdebug=False):
        fileName = os.path.basename(path)

        log = None
        if not fileName.endswith(".log"):
            return [BadLine("Ignoring \"%s\"" % path), ]
        elif fileName.startswith("stringHub-"):
            log = StringHubLog(fileName, show_tcal=show_tcal,
                               hide_sn_gaps=hide_sn_gaps,
                               show_lbmdebug=show_lbmdebug)
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
        elif fileName.startswith("replayHub-"):
            log = ReplayHubLog(fileName)
        elif fileName.startswith("dash"):
            log = DashLog(fileName, hide_rates=hide_rates)
        elif fileName.startswith("combined") or \
                fileName.startswith(".combined"):
            return None
        else:
            return [BadLine("Unknown log file \"%s\"" % path), ]

        return log.parse(path, verbose)

    def dumpRun(self, out, verbose=False, show_tcal=False, hide_rates=False,
                hide_sn_gaps=False, show_lbmdebug=False):
        try:
            runXML = DashXMLLog.parse(self.__runDir)
        except:
            runXML = None

        if runXML is None:
            cond = ""
        else:
            if runXML.getTermCond():
                cond = "ERROR"
            else:
                cond = "SUCCESS"

            if runXML.getEndTime() is None or runXML.getStartTime() is None:
                secs = 0
            else:
                delta = runXML.getEndTime() - runXML.getStartTime()
                secs = float(delta.seconds) + \
                       (float(delta.microseconds) / 1000000.0)

        if cond == "ERROR":
            print >>out, "-v-v-v-v-v-v-v-v-v-v ERROR v-v-v-v-v-v-v-v-v-v-"
        if runXML is not None:
            print >>out, "Run %s: %s, %d evts, %s secs" % \
                (runXML.getRun(), cond, runXML.getEvents(), secs)
            print >>out, "    %s" % runXML.getConfig()
            print >>out, "    from %s to %s" % \
                (runXML.getStartTime(), runXML.getEndTime())
        log = self.__processDir(self.__runDir, verbose=verbose,
                                show_tcal=show_tcal, hide_rates=hide_rates,
                                hide_sn_gaps=hide_sn_gaps,
                                show_lbmdebug=show_lbmdebug)
        log.sort()
        for l in log:
            print >>out, str(l)
        if cond == "ERROR":
            print >>out, "-^-^-^-^-^-^-^-^-^-^ ERROR ^_^_^_^_^_^_^_^_^_^_"


def add_arguments(parser):
    parser.add_argument("-d", "--rundir", dest="rundir",
                        help=("Directory holding pDAQ run monitoring"
                              " and log files"))
    parser.add_argument("-l", "--show-lbm-debug", dest="show_lbmdebug",
                        action="store_true", default=False,
                        help="Show StringHub LBM debugging messages")
    parser.add_argument("-r", "--hide-rates", dest="hide_rates",
                        action="store_true", default=False,
                        help="Hide pDAQ event rate lines")
    parser.add_argument("-s", "--hide-sn-gaps", dest="hide_sn_gaps",
                        action="store_true", default=False,
                        help="Hide StringHub Supernova gap errors")
    parser.add_argument("-t", "--show-tcal", dest="show_tcal",
                        action="store_true", default=False,
                        help="Show StringHub TCAL errors")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Include superfluous log lines")
    parser.add_argument("runNumber", nargs="+")


def getDirAndRunnum(topDir, subDir):
    "Return path to log files and run number for the log files"

    DIGITS_PAT = re.compile(r"^.*(\d+)$")
    for i in xrange(100):
        if i == 0:
            fullpath = os.path.join(topDir, subDir)
        elif i == 1:
            fullpath = subDir
        elif i == 2:
            try:
                num = int(subDir)
                fullpath = os.path.join(topDir, "daqrun%05d" % num)
            except:
                continue
        elif i == 3:
            try:
                num = int(subDir)
                fullpath = "daqrun%05d" % num
            except:
                continue
        else:
            break

        if os.path.isdir(fullpath):
            filename = os.path.basename(fullpath)
            if filename.startswith("daqrun"):
                numstr = filename[6:]
            else:
                m = DIGITS_PAT.match(filename)
                if m is not None:
                    numstr = m.group(1)
                else:
                    numstr = filename
            try:
                return(fullpath, int(numstr))
            except:
                pass

    return (None, None)


def sort_logs(args):
    if args.rundir is not None:
        runDir = args.rundir
    else:
        cd = ClusterDescription()
        runDir = cd.daqLogDir

    for arg in args.runNumber:
        (path, runnum) = getDirAndRunnum(runDir, arg)
        if path is None or runnum is None:
            print >> sys.stderr, "Bad run number \"%s\"" % arg
            continue

        ls = LogSorter(path, runnum)
        ls.dumpRun(sys.stdout, verbose=args.verbose, show_tcal=args.show_tcal,
                   hide_rates=args.hide_rates, hide_sn_gaps=args.hide_sn_gaps,
                   show_lbmdebug=args.show_lbmdebug)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    sort_logs(args)
