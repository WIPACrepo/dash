#!/usr/bin/env python
#
# Sort all log files from a run, screen out some noise

from __future__ import print_function

import argparse
import os
import re
import sys

from ClusterDescription import ClusterDescription
from DAQTime import DAQDateTime, PayloadTime
from utils.DashXMLLog import DashXMLLog


class LogParseException(Exception):
    "Log parsing exception"
    pass


class LogLevel(object):
    "Translate between string and integer log levels"
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
        return cmp(self.__level, other.level)

    def __repr__(self):
        val = None
        if self.__level == -1:
            val = ""
        elif self.__level == 0:
            val = "-"
        elif self.__level == 1:
            val = "TRACE"
        elif self.__level == 2:
            val = "DEBUG"
        elif self.__level == 3:
            val = "INFO"
        elif self.__level == 4:
            val = "WARN"
        elif self.__level == 5:
            val = "ERROR"
        elif self.__level == 6:
            val = "FATAL"

        if val is None:
            val = "???%s???" % (self.__level, )

        return val

    def __str__(self):
        return repr(self)

    @property
    def level(self):
        return self.__level

    @property
    def value(self):
        "Return the numeric value of this log level"
        return self.__level

class LogLine(object):
    "A single log line"

    def __init__(self, component, class_name, log_level, date, text):
        self.__component = component
        self.__class_name = class_name
        self.__log_level = LogLevel(log_level)
        self.__date = date
        self.__text = text

    def __cmp__(self, other):
        val = cmp(self.__date, other.date)
        if val == 0:
            val = cmp(self.__log_level, other.log_level)
            if val == 0:
                val = cmp(self.__component, other.component)
                if val == 0:
                    val = cmp(self.__class_name, other.class_name)

        return val

    def __repr__(self):
        "Return a formatted log line"
        rtnstr = str(self.__component)
        if self.__class_name is not None:
            rtnstr += " " + str(self.__class_name)
        rtnstr += " %s [%s] %s" % (self.__log_level, self.__date, self.__text)
        return rtnstr

    def __str__(self):
        "Return a formatted log line"
        return repr(self)

    def append(self, line):
        "Append a line of text"
        self.__text += "\n" + line

    @property
    def class_name(self):
        "Return the class name from this log line"
        return self.__class_name

    @property
    def component(self):
        "Return the name of the component which logged this line"
        return self.__component

    @property
    def date(self):
        "Return the date from this log line"
        return self.__date

    @property
    def log_level(self):
        "Return the log leve from this log line as a LogLevel object"
        return self.__log_level

    @property
    def text(self):
        "Return the text from this log line"
        return self.__text

    @text.setter
    def text(self, text):
        "Overwrite the text for this log line"
        self.__text = text


class BadLine(LogLine):
    "Bad log line"
    def __init__(self, text):
        super(BadLine, self).__init__("??", None, "ERROR",
                                      DAQDateTime(0, 0, 0, 0, 0, 0, 0), text)


class BaseLog(object):
    "Base class for log file parsers"

    DATE_STR = r"(\d+-\d+-\d+ \d+:\d+:\d+\.\d+)"
    LINE_PAT = re.compile(r"^(\S+)\s+(\S+)\s+(\S+)\s+\[" + DATE_STR +
                          r"\]\s+(.*)$")
    DASH_PAT = re.compile(r"^(\S+)\s+\[" + DATE_STR + r"\]\s+(.*)$")

    LOGSTART_PAT = re.compile(r"Start of log at .*$")
    OLDVERS_PAT = re.compile(r"Version info: \S+ \S+ \S+ \S+Z? \S+ (\S+)"
                             r" (\S+)")
    LOGVERS_PAT = re.compile(r"Version info: (\S+) (\S+) \S+ \S+Z?")

    def __init__(self, file_name):
        self.__file_name = file_name
        self.__rel_name = None
        self.__rel_nums = None

    def __str__(self):
        return self.__file_name

    def __got_version_info(self, lobj):
        match = self.LOGVERS_PAT.match(lobj.text)
        if match is not None:
            (self.__rel_name, self.__rel_nums) = match.groups()
            return True

        match = self.OLDVERS_PAT.match(lobj.text)
        if match is not None:
            (self.__rel_name, self.__rel_nums) = match.groups()
            return True

        return False

    def __parse_line(self, line):
        match = self.LINE_PAT.match(line)
        if match is not None:
            (component, class_name, log_level, date_str, text) = match.groups()
        else:
            match = self.DASH_PAT.match(line)
            if match is not None:
                (component, date_str, text) = match.groups()
                (class_name, log_level) = ("-", "-")
            else:
                return None

        try:
            date = PayloadTime.fromString(date_str)
        except ValueError:
            return BadLine(line)

        return LogLine(component, class_name, log_level, date, text)

    def _is_noise(self, _):
        """Return True if this line is "noise" and should be ignored"""
        raise Exception("Unimplemented for " + self.__file_name)

    def _is_start(self, lobj):
        match = self.LOGSTART_PAT.match(lobj.text)
        if match is not None:
            return True

        return False

    def cleanup(self, lobj):
        "Clean up the log line"
        pass

    def parse(self, path, verbose=False):
        "Parse a log file"
        log = []
        with open(path, 'r') as fin:
            prevobj = None
            for line in fin:
                line = line.rstrip()
                if line == "":
                    continue

                lobj = self.__parse_line(line)
                if lobj is not None:
                    if self.__got_version_info(lobj):
                        if verbose:
                            log.append(lobj)
                    elif verbose or (not self._is_start(lobj) and
                                     not self._is_noise(lobj)):
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
    "Parser for catchall.log files"

    CYCLE_PAT = re.compile(r"Cycling components \[(.*)\]$")
    CYCLE_PAT2 = re.compile(r"Cycling components \w[\w#\-, ]+$")
    LOGLINE_PAT = re.compile(r"(\S+) (\S+)" +
                             r" (\d+-\d+-\d+ \d+:\d+:\d+Z)" +
                             r" (\S+) (\S+) (\S+)$")
    REG_PAT = re.compile(r"Registered (\S+)$")
    SHUTHOOK_PAT = re.compile(r"ShutdownHook: moving temp file for (\S+)")

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        for pat in (self.CYCLE_PAT, self.CYCLE_PAT2, self.LOGLINE_PAT,
                    self.REG_PAT, self.SHUTHOOK_PAT):
            match = pat.match(lobj.text)
            if match is not None:
                return True

        return False


class CnCServerLog(BaseLog):
    "Parser for CnCServer log files"

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        return False


class DashLog(BaseLog):
    "Parser for dash.log files"

    RATES_PAT = re.compile(r"\d+ physics events(\s+\(\d+\.\d+ Hz\))?," +
                           r" \d+ moni events, \d+ SN events, \d+ tcals")

    def __init__(self, file_name, hide_rates=False):
        super(DashLog, self).__init__(file_name)

        self.__hide_rates = hide_rates

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        if self.__hide_rates:
            match = self.RATES_PAT.match(lobj.text)
            if match is not None:
                return True

        return False


class EventBuilderLog(BaseLog):
    "Parser for eventBuilder log files"

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        return False


class GlobalTriggerLog(BaseLog):
    "Parser for globalTrigger log files"

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        return False


class LocalTriggerLog(BaseLog):
    "Parser for inIceTrigger/iceTopTrigger log files"

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        return False


class SecondaryBuildersLog(BaseLog):
    "Parser for secondaryBuilders log files"

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        return False


class StringHubLog(BaseLog):
    "Parser for stringHub log files"

    def __init__(self, file_name, show_tcal=False, hide_sn_gaps=False,
                 show_lbmdebug=False):
        super(StringHubLog, self).__init__(file_name)

        self.__show_tcal = show_tcal
        self.__hide_sn_gaps = hide_sn_gaps
        self.__show_lbmdebug = show_lbmdebug

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        if not self.__show_tcal and \
            (lobj.text.startswith("Wild TCAL") or
             lobj.text.find("Got IO exception") >= 0 or
             lobj.text.find("Ignoring tcal error") >= 0):
            return True

        if not self.__show_lbmdebug and \
            (lobj.text.startswith("HISTORY:") or
             lobj.text.find("data collection stats") >= 0):
            return True

        if self.__hide_sn_gaps and \
                lobj.text.startswith("Gap or overlap in SN rec"):
            return True

        return False

    def cleanup(self, lobj):
        "Clean up the log line"
        if lobj.text.find("Got IO exception") >= 0 and \
                lobj.text.find("TCAL read failed") > 0:
            lobj.set_text("TCAL read failed")
        elif lobj.text.find("Ignoring tcal error") >= 0 and \
             lobj.text.find("TCAL read failed") > 0:
            lobj.set_text("TCAL read failed")


class ReplayHubLog(BaseLog):
    "Parser for replayHub log files"

    def _is_noise(self, lobj):
        """Return True if this line is "noise" and should be ignored"""
        return False


class LogSorter(object):
    "Sort all the log files from a single run"

    def __init__(self, run_dir=None, run_num=None):
        self.__run_dir = run_dir
        self.__run_num = run_num

    def __process_dir(self, dir_name, verbose=False, show_tcal=False,
                      hide_rates=False, hide_sn_gaps=False,
                      show_lbmdebug=False):
        log = None
        for entry in os.listdir(dir_name):
            # ignore MBean output files and run summary files
            if entry.endswith(".moni") or entry == "run.xml" or \
              entry == "logs-queued":
                continue

            path = os.path.join(dir_name, entry)

            if not os.path.isfile(path):
                continue

            flog = self.__process_file(path, verbose=verbose,
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

    @classmethod
    def __process_file(cls, path, verbose=False, show_tcal=False,
                       hide_rates=False, hide_sn_gaps=False,
                       show_lbmdebug=False):
        file_name = os.path.basename(path)

        log = None
        if not file_name.endswith(".log"):
            return [BadLine("Ignoring \"%s\"" % path), ]
        elif file_name.startswith("stringHub-"):
            log = StringHubLog(file_name, show_tcal=show_tcal,
                               hide_sn_gaps=hide_sn_gaps,
                               show_lbmdebug=show_lbmdebug)
        elif file_name.startswith("inIceTrigger-") or \
                file_name.startswith("iceTopTrigger-"):
            log = LocalTriggerLog(file_name)
        elif file_name.startswith("globalTrigger-"):
            log = GlobalTriggerLog(file_name)
        elif file_name.startswith("eventBuilder-"):
            log = EventBuilderLog(file_name)
        elif file_name.startswith("secondaryBuilders-"):
            log = SecondaryBuildersLog(file_name)
        elif file_name.startswith("catchall"):
            log = CatchallLog(file_name)
        elif file_name.startswith("cncserver"):
            log = CnCServerLog(file_name)
        elif file_name.startswith("replayHub-"):
            log = ReplayHubLog(file_name)
        elif file_name.startswith("dash"):
            log = DashLog(file_name, hide_rates=hide_rates)
        elif file_name.startswith("combined") or \
                file_name.startswith(".combined"):
            return None
        else:
            return [BadLine("Unknown log file \"%s\"" % path), ]

        return log.parse(path, verbose)

    def dump_run(self, out, verbose=False, show_tcal=False, hide_rates=False,
                 hide_sn_gaps=False, show_lbmdebug=False):
        "Print a summary of the run"
        try:
            run_xml = DashXMLLog.parse(self.__run_dir)
        except:
            run_xml = None

        if run_xml is None:
            cond = ""
        else:
            if run_xml.getTermCond():
                cond = "ERROR"
            else:
                cond = "SUCCESS"

            if run_xml.getEndTime() is None or run_xml.getStartTime() is None:
                secs = 0
            else:
                delta = run_xml.getEndTime() - run_xml.getStartTime()
                secs = float(delta.seconds) + \
                       (float(delta.microseconds) / 1000000.0)

        if cond == "ERROR":
            print("-v-v-v-v-v-v-v-v-v-v ERROR v-v-v-v-v-v-v-v-v-v-", file=out)
        if run_xml is not None:
            print("Run %s: %s, %d evts, %s secs" % \
                (run_xml.getRun(), cond, run_xml.getEvents(), secs), file=out)
            print("    %s" % run_xml.getConfig(), file=out)
            print("    from %s to %s" % \
                (run_xml.getStartTime(), run_xml.getEndTime()), file=out)
        log = sorted(self.__process_dir(self.__run_dir, verbose=verbose,
                                        show_tcal=show_tcal,
                                        hide_rates=hide_rates,
                                        hide_sn_gaps=hide_sn_gaps,
                                        show_lbmdebug=show_lbmdebug))
        for line in log:
            print(str(line), file=out)
        if cond == "ERROR":
            print("-^-^-^-^-^-^-^-^-^-^ ERROR ^_^_^_^_^_^_^_^_^_^_", file=out)


def add_arguments(parser):
    "Add all arguments"

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
    parser.add_argument("run_number", nargs="+")


def get_dir_and_runnum(top_dir, sub_dir):
    "Return path to log files and run number for the log files"

    digits_pat = re.compile(r"^.*(\d+)$")
    for i in range(100):
        if i == 0:
            fullpath = os.path.join(top_dir, sub_dir)
        elif i == 1:
            fullpath = sub_dir
        elif i == 2:
            try:
                num = int(sub_dir)
                fullpath = os.path.join(top_dir, "daqrun%05d" % num)
            except:
                continue
        elif i == 3:
            try:
                num = int(sub_dir)
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
                match = digits_pat.match(filename)
                if match is not None:
                    numstr = match.group(1)
                else:
                    numstr = filename
            try:
                return(fullpath, int(numstr))
            except:
                pass

    return (None, None)


def sort_logs(args):
    if args.rundir is not None:
        run_dir = args.rundir
    else:
        cdesc = ClusterDescription()
        run_dir = cdesc.daq_log_dir

    for arg in args.run_number:
        (path, run_num) = get_dir_and_run_num(run_dir, arg)
        if path is None or run_num is None:
            print("Bad run number \"%s\"" % arg, file=sys.stderr)
            continue

        lsrt = LogSorter(path, run_num)
        lsrt.dump_run(sys.stdout, verbose=args.verbose,
                      show_tcal=args.show_tcal, hide_rates=args.hide_rates,
                      hide_sn_gaps=args.hide_sn_gaps,
                      show_lbmdebug=args.show_lbmdebug)


def main():
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    sort_logs(args)


if __name__ == "__main__":
    main()
