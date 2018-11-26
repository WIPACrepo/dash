#!/usr/bin/env python

from __future__ import print_function

import logging
import os
import re
import socket
import sys

from ANSIEscapeCode import ANSIEscapeCode
from ClusterDescription import ClusterDescription
from DAQConst import DAQPort
from DAQRPC import RPCClient
from DAQTime import PayloadTime
from LogSorter import BaseLog
from exc_string import exc_string
from utils.DashXMLLog import DashXMLLog, DashXMLLogException


def add_arguments(parser):
    parser.add_argument("-c", "--use-cnc", dest="use_cnc",
                        action="store_true", default=False,
                        help="Query CnCServer for run details")
    parser.add_argument("-C", "--show-cluster-config", dest="show_clucfg",
                        action="store_true", default=False,
                        help="Include non-standard cluster configurations")
    parser.add_argument("-D", "--log-directory", dest="log_directory",
                        default="/mnt/data/pdaq/log",
                        help="Directory where 'daqrunXXXXXX' directories"
                        " are stored")
    parser.add_argument("-n", "--no-color", dest="no_color",
                        action="store_true", default=False,
                        help="Do not add color to output")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print run details")
    parser.add_argument(dest="files", nargs="*")


class DashLog2RunXML(BaseLog):
    DATE_STR = r"(\d+-\d+-\d+ \d+:\d+:\d+\.\d+)"
    DASH_PAT = re.compile(r"^\S+\s+\[" + DATE_STR + r"\]\s+(.*)$")

    LOGVERS_PAT = re.compile(r"Version info: (\S+) (\S+) \S+ \S+Z?")
    OLDVERS_PAT = re.compile(r"Version info: \S+ \S+ \S+ \S+Z? \S+ (\S+) (\S+)")

    RATES_PAT = re.compile(r"(\d+) physics events(\s+\(\d+\.\d+ Hz\))?," +
                           r" (\d+) moni events, (\d+) SN events, (\d+) tcals")

    def __init__(self):
        pass

    @classmethod
    def parse(cls, dashpath):
        has_version = False
        has_config = False
        has_cluster = False
        has_runnum = False

        phys_evts = None
        moni_evts = None
        sn_evts = None
        tcal_evts = None
        end_time = None

        dirname = os.path.dirname(dashpath)
        if not os.path.exists(os.path.join(dirname, "run.xml")):
            xmlname = "run.xml"
        else:
            xmlname = "fake.xml"

        runxml = DashXMLLog(dirname, file_name=xmlname)
        runxml.setFirstGoodTime(0)
        runxml.setLastGoodTime(0)
        runxml.setTermCond(None)

        with open(dashpath, "r") as rdr:
            for line in rdr:
                dmatch = cls.DASH_PAT.match(line)
                if dmatch is None:
                    # ignore irrelevant lines
                    continue

                dash_date = dmatch.group(1)
                dash_text = dmatch.group(2)

                if not has_version:
                    match = cls.LOGVERS_PAT.match(dash_text)
                    if match is not None:
                        runxml.setVersionInfo(match.group(1), match.group(2))
                        has_version = True
                        continue

                    match = cls.OLDVERS_PAT.match(dash_text)
                    if match is not None:
                        runxml.setVersionInfo(match.group(1), match.group(2))
                        has_version = True
                        continue

                if not has_config:
                    target = "Run configuration: "
                    idx = dash_text.find(target)
                    if idx >= 0:
                        runxml.setConfig(dash_text[idx + len(target):])
                        has_config = True
                        if not has_version:
                            logging.error("Missing \"Version Info\" line"
                                          " from %s" % (filename, ))
                        continue

                if not has_cluster:
                    target = "Cluster: "
                    idx = dash_text.find(target)
                    if idx >= 0:
                        runxml.setCluster(dash_text[idx + len(target):])
                        has_cluster = True
                        if not has_config:
                            logging.error("Missing \"Run Configuration\" line"
                                          " from %s" % (filename, ))
                        continue

                if not has_runnum:
                    target = "Starting run "
                    idx = dash_text.find(target)
                    if idx < 0:
                        target = "Switching to run "
                        idx = dash_text.find(target)
                    if idx >= 0:
                        numstr = dash_text[idx + len(target):]
                        numidx = 0
                        while numstr[numidx - 1] == '.':
                            numidx -= 1
                        if numidx < 0:
                            numstr = numstr[:numidx]

                        runxml.setRun(numstr)
                        runxml.setStartTime(dash_date)
                        has_runnum = True
                        if not has_cluster:
                            logging.error("Missing \"Cluster\" line"
                                          " from %s" % (filename, ))
                        continue

                if dash_text.endswith(" tcals"):
                    match = cls.RATES_PAT.match(dash_text)
                    if match is not None:
                        phys_evts = match.group(1)
                        moni_evts = match.group(3)
                        sn_evts = match.group(4)
                        tcal_evts = match.group(5)
                        end_time = dash_date
                        continue

                if dash_text.find("Run terminated") >= 0:
                    cond = dash_text.find("ERROR") > 0
                    runxml.setTermCond(cond)
                    continue

        if phys_evts is not None:
            runxml.setEvents(phys_evts)
            runxml.setMoni(moni_evts)
            runxml.setSN(sn_evts)
            runxml.setTcal(tcal_evts)
            runxml.setEndTime(end_time)

        return runxml

    @classmethod
    def from_summary(cls, summary):
        runxml = DashXMLLog()

        runxml.setRun(summary["num"])
        runxml.setConfig(summary["config"])
        runxml.setStartTime(summary["startTime"])
        runxml.setEndTime(summary["endTime"])
        runxml.setEvents(summary["numEvents"])
        runxml.setMoni(summary["numMoni"])
        runxml.setSN(summary["numSN"])
        runxml.setTcal(summary["numTcal"])
        if summary["result"] is None:
            termcond = None
        else:
            termcond = summary["result"] == "SUCCESS"
        runxml.setTermCond(termcond)

        return runxml


class Sum(object):
    def __init__(self, logdir):
        self.__logdir = logdir
        self.__dryRun = False
        self.__cnc = None

    def __compute_duration_and_rate(self, runxml, verbose=False):
        rate = ""
        duration = "???"

        xml_start_time = runxml.getStartTime()
        xml_end_time = runxml.getEndTime()
        if xml_start_time is not None and xml_end_time is not None:
            timediff = xml_end_time - xml_start_time
            if timediff.days >= 0:
                total = timediff.seconds
                if timediff.days > 0:
                    total += timediff.days * 60 * 60 * 24

                dtotal = total
                dsec = dtotal % 60
                dtotal = int(dtotal / 60)
                dmin = dtotal % 60
                dtotal = int(dtotal / 60)
                dhrs = dtotal % 24
                days = int(dtotal / 24)

                if days == 0:
                    duration = "%02d:%02d:%02d" % (dhrs, dmin, dsec)
                else:
                    duration = "%d:%02d:%02d:%02d" % (days, dhrs, dmin, dsec)

                if verbose:
                    evts = runxml.getEvents()
                    if evts is None:
                        rate = ""
                    else:
                        rate = "%.02f" % (float(evts) / float(total), )

        return duration, rate

    def __get_run_xml(self, runNum, use_cnc=True):
        cnc = None
        if use_cnc:
            try:
                tmp = self.cnc_connection()
                cnc = tmp
            except ValueError:
                pass

            if cnc is not None:
                try:
                    summary = cnc.rpc_run_summary(runNum)
                    return DashLog2RunXML.from_summary(summary)
                except DashXMLLogException:
                    pass

        try:
            return self.__read_daq_run_dir(runNum)
        except:
            # couldn't find any details about this run!
            return None

    def __read_daq_run_dir(self, runNum):
        rundir = os.path.join(self.__logdir, "daqrun%05d" % runNum)
        if not os.path.isdir(rundir):
            raise ValueError("Cannot see run %d data" % runNum)

        xmlpath = os.path.join(rundir, "run.xml")
        if os.path.exists(xmlpath):
            runxml = DashXMLLog.parse(rundir)
        else:
            dashpath = os.path.join(rundir, "dash.log")
            if os.path.exists(dashpath):
                runxml = DashLog2RunXML.parse(dashpath)
            else:
                logging.error("Cannot construct fake run.xml file for run %d",
                              runNum)
                return None

        return runxml

    def cnc_connection(self, abortOnFail=True):
        if self.__cnc is None:
            self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)
            try:
                self.__cnc.rpc_ping()
            except socket.error as err:
                if err[0] == 61 or err[0] == 111:
                    self.__cnc = None
                else:
                    raise

        if self.__cnc is None and abortOnFail:
            raise ValueError("Cannot connect to CnCServer")

        return self.__cnc

    def log_info(self, msg):
        print(msg)

    def report(self, runNum, std_clucfg=None, no_color=False,
                  use_cnc=False, verbose=False):
        if self.__dryRun:
            return

        runxml = self.__get_run_xml(runNum, use_cnc=use_cnc)
        if runxml is None:
            return

        duration, rate = self.__compute_duration_and_rate(runxml,
                                                          verbose=verbose)

        timestr = str(runxml.getStartTime())
        idx = timestr.find(".")
        if idx > 0:
            timestr = timestr[:idx]

        cond = runxml.getTermCond()
        if cond is None:
            color = ANSIEscapeCode.FG_WHITE + ANSIEscapeCode.BG_BLUE
            status = "RUNNING"
        elif cond:
            color = ANSIEscapeCode.FG_RED + ANSIEscapeCode.BG_WHITE
            status = "FAILED"
        else:
            color = ANSIEscapeCode.FG_GREEN + ANSIEscapeCode.BG_WHITE
            status = "SUCCESS"
        if not no_color:
            status = color + status + ANSIEscapeCode.OFF

        run = runxml.getRun()
        if run is None:
            run = "???"

        if not verbose:
            if std_clucfg is None:
                cfgstr = runxml.getConfig()
            else:
                cfgstr = runxml.getCluster()
                if cfgstr is None or len(cfgstr) == 0:
                    cfgstr = std_clucfg

            self.log_info("Run %s  %s  %8.8s  %-27.27s : %s" %
                          (run, timestr, duration, cfgstr, status))
            return

        # get cluster config
        cluster = strip_clucfg(runxml.getCluster())

        if std_clucfg is None:
            cfgstr = runxml.getConfig()
            cfgfmt = "%-27.27s"
        else:
            # get config, make sure cluster config is visible
            config = runxml.getConfig()
            if len(config) + len(cluster) + 2 > 35:
                config = config[:35-(len(cluster) + 2)]

            cfgstr = "%s(%s)" % (config, cluster, )
            cfgfmt = "%-35.35s"

        (rel, rev) = runxml.getVersionInfo()
        if rel is None:
            relstr = ""
        else:
            if rev is None:
                relstr = str(rel)
            else:
                relstr = "%s_%s" % (rel, rev)

        self.log_info(("Run %d  %s  %8.8s  %7s  " + cfgfmt + "  %s : %s") %
                      (run, timestr, duration, rate, cfgstr, relstr, status))


def strip_clucfg(cluster):
    """
    Strip away "-cluster" and/or ".cfg" suffix from cluster config name
    """
    if cluster.endswith(".cfg"):
        cluster = cluster[:-4]
    if cluster.endswith("-cluster"):
        cluster = cluster[:-8]
    return cluster


def summarize(args):
    if not args.show_clucfg:
        std_clucfg = None
    else:
        clu_name = ClusterDescription.getClusterFromHostName()
        std_clucfg = strip_clucfg(clu_name)

    if len(args.files) > 0:
        files = args.files[:]
    else:
        files = []
        for d in os.listdir(args.log_directory):
            if d.startswith("daqrun"):
                files.append(d)
        if len(files) == 0:
            raise SystemExit("No 'daqrun' directories found in \"%s\"" %
                             (args.log_directory, ))
    files.sort()

    summary = Sum(args.log_directory)

    for arg in files:
        if arg.find("/") >= 0:
            arg = os.path.basename(arg)

        if arg.startswith("daqrun"):
            arg = arg[6:]

        try:
            num = int(arg)
        except:
            logging.error("Bad run number \"%s\"", arg)
            continue

        try:
            summary.report(num, std_clucfg=std_clucfg, no_color=args.no_color,
                           verbose=args.verbose, use_cnc=args.use_cnc)
        except:
            import traceback; traceback.print_exc()
            logging.error("Bad run %d: %s: %s", num, sys.exc_info()[0],
                          sys.exc_info()[1])


if __name__ == "__main__":
    import argparse

    argp = argparse.ArgumentParser()
    add_arguments(argp)
    args = argp.parse_args()

    summarize(args)
