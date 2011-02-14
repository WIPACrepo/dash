#!/usr/bin/env python

import os, re, sys

DEBUG = False

class ComponentLog(object):
    VERSION_INFO = re.compile(r"^(|.*\]\s+)(Version info: )?\S+ \d+" +
                              r" \d+-\d+-\d+ \d+:\d+:\d+\S* \S+" +
                              r" (\S+) (\S+)\s*$")

    def __init__(self, fileName):
        self.__fileName = fileName
        self.__releaseName = None
        self.__releaseRev = None
        self.__logMsgs = []

    def logError(self, msg):
        if DEBUG: print >>sys.stderr, msg
        self.__logMsgs.append(msg)

    def checkInitialLogMessage(self, line):
        if line.find("Start of log at ") >= 0 or \
                line.find("Logging has been reset") >= 0:
            return True

        return False

    def checkVersionInfoMessage(self, line):
        m = self.VERSION_INFO.match(line)
        if m:
            self.__releaseName = m.group(2)
            self.__releaseRev = m.group(3)
            return True

        return False

    def fileName(self): return self.__fileName

    def parse(self, path):
        self.logError("Not parsing \"%s\"" % path)

    def report(self, fd, verbose):
        raise Exception("Unimplemented by %s" % str(type(self)))

    def reportErrors(self, fd):
        for msg in self.__logMsgs:
            print >>fd, "%s: %s" % (self.__fileName, msg)

class CatchallLog(ComponentLog):
    SRVR_PORT = re.compile(r"^(|.*\]\s+)I'm server CnCServer running" +
                           r" on port (\d+)\s*$")
    SHUTDOWN = re.compile(r"^(|.*\]\s+)ShutdownHook invoked for \S+\s*$")
    MBEAN_AGENT = re.compile(r"^(|.*\]\s+)Started MBean agent: HTML port \d+," +
                             r" XML-RPC port \d+\s*$")
    RDR_PORT = re.compile(r"^(|.*\]\s+)\S+:\S+ listening on port \d+\s*$")
    XMLRPC_PORT = re.compile(r"^(|.*\]\s+)XML-RPC on port \d+\s*$")
    OLDREG_COMP = re.compile(r"^(|.*\]\s+)Got registration for ID#(\d+)" +
                             r" (\S+) at (\S+):(\d+) M#(\d+) \[[^\]]*\]\s*$")
    NEWREG_COMP = re.compile(r"^(|.*\]\s+)Registered (\S+)\s*$")
    START_RUN = re.compile(r"^(|.*\]\s+)Starting run (\d+) \(waiting for" +
                           r" required (\d+) components to register" +
                           r" w/ CnCServer\)\s*$")
    LIST_COMP = re.compile(r"^(|.*\]\s+)ID#(\d+) (\S+) at (\S+):(\d+) M#(\d+)" +
                           r" \[[^\]]*\]\s*$")
    CREATED = re.compile(r"^(|.*\]\s+)Created Run Set #(\d+)\s*$")
    RESET_LOG = re.compile(r"^(|.*\]\s+).*Reset log to log\(\S+:\d+\)" +
                           r"\+live\(\S+:\d+\)\s*$")

    STATE_INITIAL = 0
    STATE_STARTING = 1
    STATE_BUILDING = 2
    STATE_BUILTLIST = 3
    STATE_CREATED = 4

    def __init__(self, fileName):
        self.__port = None
        super(CatchallLog, self).__init__(fileName)

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        elif val == cls.STATE_STARTING:
            return "STARTING"
        elif val == cls.STATE_BUILDING:
            return "BUILDING"
        elif val == cls.STATE_BUILTLIST:
            return "BUILTLIST"
        elif val == cls.STATE_CREATED:
            return "CREATED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if state == self.STATE_INITIAL:
                if self.checkInitialLogMessage(line) or \
                        line.find("Resetting logging") >= 0 or \
                        line.find("ShutdownHook: moving temp file for ") >= 0:
                    continue

                m = self.SRVR_PORT.match(line)
                if m:
                    self.__port = int(m.group(2))
                    continue

                m = self.SHUTDOWN.match(line)
                if m:
                    continue

                if self.checkVersionInfoMessage(line):
                    state = self.STATE_STARTING
                    continue

            elif state == self.STATE_STARTING:
                if line.find("Logging has been reset") >= 0 or \
                        line.find("Resetting logging") >= 0:
                    continue

                m = self.MBEAN_AGENT.match(line)
                if m:
                    continue

                m = self.RDR_PORT.match(line)
                if m:
                    continue

                m = self.XMLRPC_PORT.match(line)
                if m:
                    continue

                m = self.OLDREG_COMP.match(line)
                if m:
                    id = int(m.group(2))
                    comp = m.group(3)
                    addr = m.group(4)
                    rpcPort = int(m.group(5))
                    mbeanPort = int(m.group(6))
                    continue

                m = self.NEWREG_COMP.match(line)
                if m:
                    comp = m.group(1)
                    continue

                m = self.START_RUN.match(line)
                if m:
                    runNum = int(m.group(2))
                    numComps = int(m.group(3))
                    state = self.STATE_BUILDING
                    continue

            elif state == self.STATE_BUILDING:
                if line.find("Logging has been reset") >= 0 or \
                        line.find("Resetting logging") >= 0:
                    continue

                m = self.MBEAN_AGENT.match(line)
                if m:
                    continue

                m = self.RDR_PORT.match(line)
                if m:
                    continue

                m = self.XMLRPC_PORT.match(line)
                if m:
                    continue

                m = self.OLDREG_COMP.match(line)
                if m:
                    id = int(m.group(2))
                    comp = m.group(3)
                    addr = m.group(4)
                    rpcPort = int(m.group(5))
                    mbeanPort = int(m.group(6))
                    continue

                m = self.NEWREG_COMP.match(line)
                if m:
                    comp = m.group(1)
                    continue

                if line.find("Built runset with the following components:") >= 0:
                    state = self.STATE_BUILTLIST
                    continue

            elif state == self.STATE_BUILTLIST:
                m = self.LIST_COMP.match(line)
                if m:
                    id = int(m.group(2))
                    comp = m.group(3)
                    addr = m.group(4)
                    rpcPort = int(m.group(5))
                    mbeanPort = int(m.group(6))
                    continue

                m = self.CREATED.match(line)
                if m:
                    runsetNum = int(m.group(2))
                    state = self.STATE_CREATED
                    continue

            elif state == self.STATE_CREATED:
                if line.find("Logging has been reset") >= 0 or \
                        line.find("Resetting logging") >= 0:
                    continue

                m = self.RESET_LOG.match(line)
                if m:
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        pass

class CnCServerLog(ComponentLog):
    WAITCFG = re.compile(r"^(|.*\]\s+)RunSet #(\d+): Waiting for (\S+)" +
                         r" (.*)\s*$")
    WAITSTOP = re.compile(r"^(|.*\]\s+)RunSet #(\d+) run#(\d+): Waiting for (\S+)" +
                          r" (.*)\s*$")

    STATE_INITIAL = 0

    def __init__(self, fileName):
        super(CnCServerLog, self).__init__(fileName)

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if state == self.STATE_INITIAL:
                if self.checkInitialLogMessage(line):
                    continue

                m = self.WAITCFG.match(line)
                if m:
                    runsetId = int(m.group(2))
                    waitState = m.group(3)
                    continue

                m = self.WAITSTOP.match(line)
                if m:
                    runsetId = int(m.group(2))
                    run = int(m.group(3))
                    waitState = m.group(4)
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        pass

class DashLog(ComponentLog):
    START_RUN = re.compile(r"^(|.*\]\s+)Starting run (\d+)\.\.\.\s*$")
    RUN_CFG = re.compile(r"^(|.*\]\s+)Run configuration: (\S+)\s*$")
    CLU_CFG = re.compile(r"^(|.*\]\s+)Cluster configuration: (\S+)\s*$")
    STARTED = re.compile(r"^(|.*\]\s+)Started run (\d+) on run set (\d+)\s*$")
    RATELINE = re.compile(r"^(|.*\]\s+)(\d+) physics events" +
                          r"( \((\d+\.\d+) Hz\))?, (\d+) moni events," +
                          r" (\d+) SN events, (\d+) tcals\s*$")
    WATCHDOG_TIMEOUT = re.compile(r"^(|.*\]\s+)#\d+: (\S+)" +
                                  r" (inputs|outputs|threadholds):" +
                                  r" timeout\(\"timed out\"\) in" +
                                  r" .*RunWatchdog.py.*\s*$")
    WATCHDOG_RESET = re.compile(r"^(|.*\]\s+)#\d+: (\S+)" +
                                r" (inputs|outputs|threadholds):" +
                                r" error\(\"\(\d+," +
                                r" 'Connection reset by peer'\)\"\) in" +
                                r" .*RunWatchdog.py.*\s*$")
    WATCHDOG_REFUSED = re.compile(r"^(|.*\]\s+)#\d+: (\S+)" +
                                  r" (inputs|outputs|threadholds):" +
                                  r" error\(\"\(\d+," +
                                  r" 'Connection refused'\)\"\) in" +
                                  r" .*RunWatchdog.py.*\s*$")
    MONI_TIMEOUT = re.compile(r"^(|.*\]\s+)Ignoring (\S+-\d+):" +
                                  r" timeout\(\"timed out\"\) in" +
                                  r" .*DAQMoni.py.*\s*$")
    MONI_RESET = re.compile(r"^(|.*\]\s+)Ignoring (\S+-\d+):" +
                            r" error\(\"\(\d+,"
                            r" 'Connection reset by peer'\)\"\) in" +
                            r" .*DAQMoni.py.*\s*$")
    MONI_REFUSED = re.compile(r"^(|.*\]\s+)Ignoring (\S+-\d+):" +
                              r" error\(\"\(\d+,"
                              r" 'Connection refused'\)\"\) in" +
                              r" .*DAQMoni.py.*\s*$")
    STOP_RUN = re.compile(r"^(|.*\]\s+)Stopping run (\d+)\s*$")
    PHYS_TOTAL = re.compile(r"^(|.*\]\s+)(\d+) physics events collected in" +
                            r" (\d+) seconds \((\d+\.\d+) Hz\)\s*$")
    OTHER_TOTAL = re.compile(r"^(|.*\]\s+)(\d+) moni events, (\d+) SN events," +
                             r" (\d+) tcals\s*$")
    RECOVER = re.compile(r"^(|.*\]\s+)Recovering from failed run" +
                         r" (\d_)\.\.\.\s*$")
    RUN_TERM = re.compile(r"^(|.*\]\s+)Run terminated (\S+)\.\s*$")

    STATE_INITIAL = 0
    STATE_STARTING = 1
    STATE_RUNNING = 2
    STATE_STOPPING = 3
    STATE_ENDING = 4

    def __init__(self, fileName):
        super(DashLog, self).__init__(fileName)

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        elif val == cls.STATE_STARTING:
            return "STARTING"
        elif val == cls.STATE_RUNNING:
            return "RUNNING"
        elif val == cls.STATE_STOPPING:
            return "STOPPING"
        elif val == cls.STATE_ENDING:
            return "ENDING"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if state == self.STATE_INITIAL:
                if self.checkVersionInfoMessage(line):
                    continue

                m = self.START_RUN.match(line)
                if m:
                    runNum = int(m.group(2))
                    state = self.STATE_STARTING
                    continue

            if state == self.STATE_STARTING:
                m = self.RUN_CFG.match(line)
                if m:
                    runCfg = m.group(2)
                    continue

                m = self.CLU_CFG.match(line)
                if m:
                    cluCfg = m.group(2)
                    continue

                m = self.STARTED.match(line)
                if m:
                    tmpNum = int(m.group(2))
                    if runNum != tmpNum:
                        self.logError("Expected run#%d, not #%d in line \"%s\"" %
                                      (runNum, tmpNum, line))
                    runsetId = int(m.group(3))
                    state = self.STATE_RUNNING
                    continue

            if state == self.STATE_RUNNING:
                m = self.RECOVER.match(line)
                if m:
                    tmpNum = int(m.group(2))
                    if runNum != tmpNum:
                        self.logError("Expected run#%d, not #%d in line \"%s\"" %
                                      (runNum, tmpNum, line))
                        state = self.STATE_ENDING
                        continue

                m = self.RATELINE.match(line)
                if m:
                    numPhysics = float(m.group(2))
                    if m.group(4) is None:
                        rate = 0.0
                    else:
                        rate = float(m.group(4))
                    numMoni = int(m.group(5))
                    numSN = int(m.group(6))
                    numTCal = int(m.group(7))
                    continue

                m = self.STOP_RUN.match(line)
                if m:
                    tmpNum = int(m.group(2))
                    if runNum != tmpNum:
                        self.logError("Expected run#%d, not #%d in line \"%s\"" %
                                      (runNum, tmpNum, line))
                    state = self.STATE_STOPPING
                    continue

                m = self.WATCHDOG_TIMEOUT.match(line)
                if m:
                    self.logError("%s RunWatchdog timeout for %s %s" %
                                  (m.group(1).rstrip(), m.group(2), m.group(3)))
                    continue

                m = self.WATCHDOG_RESET.match(line)
                if m:
                    self.logError("%s RunWatchdog connection reset for %s %s" %
                                  (m.group(1).rstrip(), m.group(2), m.group(3)))
                    continue

                m = self.WATCHDOG_REFUSED.match(line)
                if m:
                    self.logError("%s RunWatchdog connection refused for %s %s" %
                                  (m.group(1).rstrip(), m.group(2), m.group(3)))
                    continue

                m = self.MONI_TIMEOUT.match(line)
                if m:
                    self.logError("%s Monitoring timeout for %s" %
                                  (m.group(1).rstrip(), m.group(2)))
                    continue

                m = self.MONI_RESET.match(line)
                if m:
                    self.logError("%s Monitoring connection reset for %s" %
                                  (m.group(1).rstrip(), m.group(2)))
                    continue

                m = self.MONI_REFUSED.match(line)
                if m:
                    self.logError("%s Monitoring connection refused for %s" %
                                  (m.group(1).rstrip(), m.group(2)))
                    continue

            if state == self.STATE_STOPPING:
                m = self.PHYS_TOTAL.match(line)
                if m:
                    totPhysics = int(m.group(2))
                    totTime = int(m.group(3))
                    totRate = float(m.group(4))
                    continue

                m = self.OTHER_TOTAL.match(line)
                if m:
                    totMoni = int(m.group(2))
                    totSN = int(m.group(3))
                    totTCal = int(m.group(4))
                    state = self.STATE_ENDING
                    continue

            if state == self.STATE_ENDING:
                m = self.RUN_TERM.match(line)
                if m:
                    termState = m.group(2)
                    continue

                if line.find("Doing complete rip-down and restart") >= 0:
                    state = self.STATE_INITIAL
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        pass

class EventBuilderLog(ComponentLog):
    BOUNDARY = re.compile(r"^(|.*\]\s+)called dataBoundary on (\S+)" +
                          r" with the message: Run(\S+):(\d+)\s*$")

    STATE_INITIAL = 0
    STATE_STARTING = 1
    STATE_STARTED = 2
    STATE_STOPPING = 3
    STATE_STOPPED = 4

    def __init__(self, fileName):
        self.__runNum = None

        super(EventBuilderLog, self).__init__(fileName)

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        elif val == cls.STATE_STARTING:
            return "STARTING"
        elif val == cls.STATE_STARTED:
            return "STARTED"
        elif val == cls.STATE_STOPPING:
            return "STOPPING"
        elif val == cls.STATE_STOPPED:
            return "STOPPED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if state == self.STATE_INITIAL:
                if self.checkInitialLogMessage(line) or \
                        line.find("Resetting logging") >= 0:
                    continue

                if self.checkVersionInfoMessage(line):
                    state = self.STATE_STARTING
                    continue

            elif state == self.STATE_STARTING:
                if line.find("Splicer entered STARTING state") >= 0:
                    continue

                if line.find("Splicer entered STARTED state") >= 0:
                    state = self.STATE_STARTED
                    continue

                m = self.BOUNDARY.match(line)
                if m:
                    if m.group(2) != "STARTING" or m.group(3) != "Start":
                        self.logError("Bad STARTING boundary message: %s" % line)
                    self.__runNum = int(m.group(4))
                    continue

            elif state == self.STATE_STARTED:
                if line.find("HKN1Splicer was started.") >= 0:
                    continue

                if line.find("pushing LAST_POSSIBLE_SPLICEABLE") >= 0:
                    state = self.STATE_STOPPING
                    continue

            elif state == self.STATE_STOPPING:
                if line.find("pushing LAST_POSSIBLE_SPLICEABLE") >= 0 or \
                        line.find("Splicer entered STOPPING state") >= 0:
                    continue

                if line.find("Splicer entered STOPPED state") >= 0:
                    state = self.STATE_STOPPED
                    continue

            elif state == self.STATE_STOPPED:
                if line.find("HKN1Splicer was stopped.") >= 0:
                    continue

                m = self.BOUNDARY.match(line)
                if m:
                    if m.group(2) != "STOPPED" or m.group(3) != "Stop":
                        self.logError("Bad STOPPED boundary message: %s" % line)
                    runNum = int(m.group(4))
                    if self.__runNum != runNum:
                        self.logError(("Expected data boundary run number %s," +
                                         " not %s") % \
                                            (str(self.__runNum), runNum))
                    continue

                if line.find(" was not moved to the dispatch storage") > 0:
                    continue

                if line.find("Resetting logging") >= 0:
                    state = self.STATE_INITIAL
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        pass

class GlobalTriggerLog(ComponentLog):
    TRIG_CFG = re.compile(r"^(|.*\]\s+)triggerConfig element has: (\S+).*$")
    TRIG_BLDVAL = re.compile(r"^(|.*\]\s+)(\S+) = (\S+).*$")
    BUILD_TRIG = re.compile(r"^(|.*\]\s+)Building trigger: (\S+).*$")
    LONGEST_TRIG = re.compile(r"^(|.*\]\s+)We have a new longest GT:" +
                              r" (\d+\.\d+).*$")
    TRIG_NUM = re.compile(r"^(|.*\]\s+)(\S+):  #  (\d+).*$")
    ISSUE_NUM = re.compile(r"^(|.*\]\s+)Issue # \d+ GTEventPayload .*$")
    MERGED_NUM = re.compile(r"^(|.*\]\s+)Merged GT # (\d+).*$")
    TOT_GT_EVTS = re.compile(r"^(|.*\]\s+)Total # of GT events = (\d+).*$")
    TOT_MERGED = re.compile(r"^(|.*\]\s+)Total # of merged GT events = (\d+).*$")
    TRIG_TOTAL = re.compile(r"^(|.*\]\s+)Total # of (\S+)= (\d+).*$")
    PROC_TOTAL = re.compile(r"^(|.*\]\s+)Processed (\d+) hits at \d+\.\d+" +
                            r" ms per hit.*$")

    STATE_INITIAL = 0
    STATE_CONFIG = 1
    STATE_RUNNING = 2
    STATE_STOPPING = 3
    STATE_REPORT = 4
    STATE_STOPPED = 5

    def __init__(self, fileName):
        self.__cfgName = None
        self.__longest = None
        self.__totHits = None
        self.__totGTEvts = None
        self.__merged = None
        self.__trigCnt = {}

        super(GlobalTriggerLog, self).__init__(fileName)

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        if val == cls.STATE_CONFIG:
            return "CONFIG"
        if val == cls.STATE_RUNNING:
            return "RUNNING"
        if val == cls.STATE_STOPPING:
            return "STOPPING"
        if val == cls.STATE_REPORT:
            return "REPORT"
        if val == cls.STATE_STOPPED:
            return "STOPPED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        curTrig = None

        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if state == self.STATE_INITIAL:
                if self.checkInitialLogMessage(line):
                    continue

                if self.checkVersionInfoMessage(line):
                    state = self.STATE_CONFIG
                    continue

            elif state == self.STATE_CONFIG:
                if self.__cfgName is None:
                    if line.find("loaded DOM registry") >= 0 or \
                            line.find("Getting root element of xml file") >= 0:
                        continue

                    m = self.TRIG_CFG.match(line)
                    if m:
                        self.__cfgName = m.group(2)
                        continue

                elif line.find("TriggerName set to ") >= 0 or \
                        line.find("Adding parameter ") >= 0 or \
                        line.find("Added Parameter: ") >= 0 or \
                        line.find("Adding readout ") >= 0 or \
                        line.find("Added Readout: ") >= 0:
                    continue

                elif line.find("HKN1Splicer was started") >= 0:
                    state = self.STATE_RUNNING
                    continue

                else:
                    m = self.TRIG_BLDVAL.match(line)
                    if m:
                        continue

                    m = self.BUILD_TRIG.match(line)
                    if m:
                        curTrig = m.group(2)
                        continue

            elif state == self.STATE_RUNNING:
                if line.find("Splicer contains: ") >= 0 or \
                        line.find("Total time = ") >= 0:
                    continue

                m = self.LONGEST_TRIG.match(line)
                if m:
                    self.__longest = float(m.group(2))
                    continue

                m = self.TRIG_NUM.match(line)
                if m:
                    self.__trigCnt[m.group(2)] = long(m.group(3))
                    continue

                m = self.ISSUE_NUM.match(line)
                if m:
                    continue

                m = self.MERGED_NUM.match(line)
                if m:
                    self.__merged = long(m.group(2))
                    continue

                if line.find("pushing LAST_POSSIBLE_SPLICEABLE") >= 0:
                    state = self.STATE_STOPPING
                    continue

            elif state == self.STATE_STOPPING:
                if line.find("pushing LAST_POSSIBLE_SPLICEABLE") >= 0 or \
                        len(line) == 0:
                    continue

                if line.find("Flushing InputHandler in GlobalTrigger") >= 0 or \
                        line.find("Flushing: Total count = ") >= 0 or \
                        line.find("Flushing GlobalTriggers") >= 0 or \
                        line.find("GlobalTrigger count for ") >= 0 or \
                        line.find("Flushing GlobalTriggerBag") >= 0:
                    continue

                if line.find("================================") >= 0:
                    state = self.STATE_REPORT
                    continue

                m = self.PROC_TOTAL.match(line)
                if m:
                    self.__totHits = long(m.group(2))
                    state = self.STATE_STOPPED
                    continue

            elif state == self.STATE_REPORT:
                if line.find("================================") >= 0:
                    state = self.STATE_STOPPING
                    continue

                if line.find("I3 GlobalTrigger Run Summary") >= 0 or \
                        len(line) == 0:
                    continue

                m = self.TOT_GT_EVTS.match(line)
                if m:
                    self.__totGTEvts = long(m.group(2))
                    continue

                m = self.TOT_MERGED.match(line)
                if m:
                    self.__merged = long(m.group(2))
                    continue

                m = self.TRIG_TOTAL.match(line)
                if m:
                    self.__trigCnt[m.group(2)] = long(m.group(3))
                    continue

            elif state == self.STATE_STOPPED:
                if line.find("Received Splicer STOPPED") >= 0 or \
                        line.find("HKN1Splicer was stopped") >= 0 or \
                        line.find("Resetting logging") >= 0:
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        if verbose:
            print >> fd, "Totals: Hits %s Events %s Merged %s" % \
                (str(self.__totHits), str(self.__totGTEvts), str(self.__merged))
            for k in self.__trigCnt:
                print >>fd, "  %s: %d" % (k, self.__trigCnt[k])

class LocalTriggerData(object):
    def __init__(self):
        self.__hits = []
        self.__total = None

    def addHits(self, numHits):
        self.__hits.append(numHits)

    def avgHits(self):
        if len(self.__hits) == 0:
            return 0.0

        total = 0
        for h in self.__hits:
            total += h
        return float(total) / float(len(self.__hits))

    def setTotal(self, total):
        self.__total = total

    def total(self):
        return self.__total

    def totalPct(self, total):
        if self.__total is None or total == 0.0:
            return 0.0

        return float(self.__total * 100) / total

class LocalTriggerLog(ComponentLog):
    TRIG_CFG = re.compile(r"^(|.*\]\s+)triggerConfig element has: (\S+).*$")
    TRIG_BLDVAL = re.compile(r"^(|.*\]\s+)(\S+) = (\S+).*$")
    BUILD_TRIG = re.compile(r"^(|.*\]\s+)Building trigger: (\S+).*$")
    NEW_TRIG = re.compile(r"^(|.*\]\s+)New Trigger (\d+) from (\S+)" +
                          r" includes (\d+) hits.*$")
    TRIG_CNT = re.compile(r"^(|.*\]\s+)Trigger count for (\S+) is (\d+)\s*$")
    PROC_TOTAL = re.compile(r"^(|.*\]\s+)Processed (\d+) hits at \d+\.\d+" +
                            r" ms per hit.*$")

    STATE_INITIAL = 0
    STATE_CONFIG = 1
    STATE_RUNNING = 2
    STATE_STOPPING = 3
    STATE_STOPPED = 4

    def __init__(self, fileName):
        self.__cfgName = None
        self.__trigData = {}

        super(LocalTriggerLog, self).__init__(fileName)

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        if val == cls.STATE_CONFIG:
            return "CONFIG"
        if val == cls.STATE_RUNNING:
            return "RUNNING"
        if val == cls.STATE_STOPPING:
            return "STOPPING"
        if val == cls.STATE_STOPPED:
            return "STOPPED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        curTrig = None

        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if state == self.STATE_INITIAL:
                if self.checkInitialLogMessage(line):
                    continue

                if self.checkVersionInfoMessage(line):
                    state = self.STATE_CONFIG
                    nextFound = 0
                    continue

            elif state == self.STATE_CONFIG:
                if self.__cfgName is None:
                    if line.find("loaded DOM registry") >= 0 or \
                            line.find("Getting root element of xml file") >= 0:
                        continue

                    m = self.TRIG_CFG.match(line)
                    if m:
                        self.__cfgName = m.group(2)
                        continue

                elif line.find("TriggerName set to ") >= 0 or \
                        line.find("Adding parameter ") >= 0 or \
                        line.find("Added Parameter: ") >= 0 or \
                        line.find("Adding readout ") >= 0 or \
                        line.find("Added Readout: ") >= 0:
                    continue

                elif line.find("HKN1Splicer was started") >= 0:
                    state = self.STATE_RUNNING
                    continue

                else:
                    m = self.TRIG_BLDVAL.match(line)
                    if m:
                        continue

                    m = self.BUILD_TRIG.match(line)
                    if m:
                        curTrig = m.group(2)
                        continue

            elif state == self.STATE_RUNNING:
                if line.find("pushing LAST_POSSIBLE_SPLICEABLE") >= 0:
                    continue

                if line.find("Flushing InputHandler") >= 0:
                    state = self.STATE_STOPPING
                    continue

                m = self.NEW_TRIG.match(line)
                if m:
                    num = int(m.group(2))
                    name = m.group(3)
                    numHits = int(m.group(4))
                    if not self.__trigData.has_key(name):
                        self.__trigData[name] = LocalTriggerData()
                    self.__trigData[name].setTotal(num)
                    self.__trigData[name].addHits(numHits)
                    continue

            elif state == self.STATE_STOPPING:
                if line.find("Flushing Triggers") >= 0 or \
                        line.find("Flushing: Total count = ") >= 0 or \
                        line.find("Flushing TriggerBag") >= 0:
                    continue

                m = self.TRIG_CNT.match(line)
                if m:
                    name = m.group(2)
                    cnt = int(m.group(3))
                    if not self.__trigData.has_key(name):
                        self.__trigData[name] = LocalTriggerData()
                    self.__trigData[name].setTotal(cnt)
                    continue

                m = self.PROC_TOTAL.match(line)
                if m:
                    totHits = long(m.group(2))
                    state = self.STATE_STOPPED
                    continue

            elif state == self.STATE_STOPPED:
                if line.find("Received Splicer STOPPED") >= 0 or \
                        line.find("HKN1Splicer was stopped") >= 0 or \
                        line.find("Resetting logging") >= 0:
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        if verbose:
            total = 0.0
            for k in self.__trigData.keys():
                if self.__trigData[k].total() is not None:
                    total += float(self.__trigData[k].total())

            for k in self.__trigData.keys():
                print >>fd, "%5.2f(%d): %s (%s)" % \
                    (self.__trigData[k].totalPct(total),
                     self.__trigData[k].avgHits(), k,
                     str(self.__trigData[k].total()))

class LogParseException(Exception): pass

class Builder(object):
    STATE_INITIAL = 0
    STATE_STARTING = 1
    STATE_STARTED = 2
    STATE_STOPPING = 3
    STATE_STOPPED = 4

    def __init__(self, name):
        self.__name = name
        self.__state = self.STATE_INITIAL

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        if val == cls.STATE_STARTING:
            return "STARTING"
        if val == cls.STATE_STARTED:
            return "STARTED"
        if val == cls.STATE_STOPPING:
            return "STOPPING"
        if val == cls.STATE_STOPPED:
            return "STOPPED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def __str__(self):
        return self.__name

    def __transition(self, curState, newState):
        if self.__state != curState:
            raise LogParseException("Builder %s should be in %s state, not %s" %
                                    (str(self), self.__stateString(curState),
                                     self.__stateString(self.__state)))
        self.__state = newState

    def isInitial(self):
        return self.__state == self.STATE_INITIAL

    def setStarted(self):
        self.__transition(self.STATE_STARTING, self.STATE_STARTED)

    def setStarting(self):
        self.__transition(self.STATE_INITIAL, self.STATE_STARTING)

    def setSplicerStopped(self):
        self.__transition(self.STATE_STOPPED, self.STATE_INITIAL)

    def setStopped(self):
        self.__transition(self.STATE_STOPPING, self.STATE_STOPPED)

    def setStopping(self):
        self.__transition(self.STATE_STARTED, self.STATE_STOPPING)

    def state(self): return self.__stateString(self.__state)

class SecondaryBuildersLog(ComponentLog):
    RUNNUM = re.compile(r"^(|.*\]\s+)Setting runNumber = (\d+)\s*$")
    BLDR_STATE = re.compile(r"^(|.*\]\s+)entered (\S+) (\S+) state and" +
                            r" calling dispatcher.dataBoundary()")
    SPLI_STATE = re.compile(r"^(|.*\]\s+)Splicer (\S+) entered (\S+) state")
    SPLI_HALT = re.compile(r"^(|.*\]\s+)entered stopped state. Splicer (\S+)" +
                           r" state is: 1: STOPPED")

    STATE_INITIAL = 0
    STATE_STARTING = 1
    STATE_STOPPING = 3
    STATE_STOPPED = 4

    def __init__(self, fileName):
        self.__runNum = None
        self.__builder = {}

        super(SecondaryBuildersLog, self).__init__(fileName)

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        elif val == cls.STATE_STARTING:
            return "STARTING"
        elif val == cls.STATE_STOPPING:
            return "STOPPING"
        elif val == cls.STATE_STOPPED:
            return "STOPPED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if state == self.STATE_INITIAL:
                if self.checkInitialLogMessage(line) or \
                        line.find("Resetting logging") >= 0:
                    continue

                if self.checkVersionInfoMessage(line):
                    state = self.STATE_STARTING
                    continue

            elif state == self.STATE_STARTING:
                if line.find("HKN1Splicer was started.") >= 0:
                    continue

                m = self.RUNNUM.match(line)
                if m:
                    self.__runNum = int(m.group(2))
                    continue

                m = self.BLDR_STATE.match(line)
                if m:
                    name = m.group(2)
                    bldrState = m.group(3)
                    if bldrState != "starting":
                        self.logError("Bad %s builder STARTING state: %s" %
                                      (name, line))
                        continue

                    if not self.__builder.has_key(name):
                        self.__builder[name] = Builder(name)
                    self.__builder[name].setStarting()
                    continue

                m = self.SPLI_STATE.match(line)
                if m:
                    name = m.group(2)
                    splState = m.group(3)
                    if splState != "STARTED":
                        self.logError("Bad %s splicer STARTING state: %s" %
                                      (name, line))
                        continue

                    if not self.__builder.has_key(name):
                        self.__builder[name] = Builder(name)
                    self.__builder[name].setStarted()
                    continue

                if line.find("pushing LAST_POSSIBLE_SPLICEABLE") >= 0:
                    state = self.STATE_STOPPING
                    continue

            elif state == self.STATE_STOPPING:
                if line.find("pushing LAST_POSSIBLE_SPLICEABLE") >= 0 or \
                        line.find("HKN1Splicer was stopped.") >= 0:
                    continue

                m = self.SPLI_STATE.match(line)
                if m:
                    name = m.group(2)
                    splState = m.group(3)
                    if splState != "STOPPING":
                        self.logError("Bad %s splicer STOPPING state: %s" %
                                      (name, line))
                        continue

                    if not self.__builder.has_key(name):
                        self.__builder[name] = Builder(name)
                    self.__builder[name].setStopping()
                    continue

                m = self.BLDR_STATE.match(line)
                if m:
                    name = m.group(2)
                    bldrState = m.group(3)
                    if bldrState != "stopped":
                        self.logError("Bad %s builder STOPPING state: %s" %
                                      (name, line))
                        continue

                    if not self.__builder.has_key(name):
                        self.__builder[name] = Builder(name)
                    self.__builder[name].setStopped()
                    continue

                m = self.SPLI_HALT.match(line)
                if m:
                    name = m.group(2)
                    if not self.__builder.has_key(name):
                        self.__builder[name] = Builder(name)
                    self.__builder[name].setSplicerStopped()
                    continue

                if line.find("Resetting logging") >= 0:
                    state = self.STATE_INITIAL
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        if verbose:
            for bldr in self.__builder.values():
                if not bldr.isInitial():
                    print >>fd, "%s %s" % (str(bldr), bldr.state())

class BaseDom(object):
    STATE_INITIAL = 0
    STATE_SIGCONFIG = 1
    STATE_CONFIGING = 2
    STATE_FINISHCFG = 3
    STATE_READY = 4
    STATE_SIGSTART = 5
    STATE_STARTRUN = 6
    STATE_RUNNING = 7
    STATE_STOPPING = 8
    STATE_STOPPED = 9

    def __init__(self, dcName):
        self.__card = int(dcName[0])
        self.__pair = int(dcName[1])
        if dcName[2] == "A":
            self.__abNum = 0
        else:
            self.__abNum = 1

        self.__cfgMillis = None
        self.__wildTCals = 0
        self.__tcalFails = 0
        self.__gpsFails = 0

        self.__state = self.STATE_INITIAL

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        if val == cls.STATE_SIGCONFIG:
            return "SIGCONFIG"
        if val == cls.STATE_CONFIGING:
            return "CONFIGING"
        if val == cls.STATE_FINISHCFG:
            return "FINISHCFG"
        if val == cls.STATE_READY:
            return "READY"
        if val == cls.STATE_SIGSTART:
            return "SIGSTART"
        if val == cls.STATE_STARTRUN:
            return "STARTRUN"
        if val == cls.STATE_RUNNING:
            return "RUNNING"
        if val == cls.STATE_STOPPING:
            return "STOPPING"
        if val == cls.STATE_STOPPED:
            return "STOPPED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def __str__(self):
        if self.__abNum == 0:
            abCh = "A"
        else:
            abCh = "B"
        return "Dom-%d%d%s" % (self.__card, self.__pair, abCh)

    def __transition(self, curState, newState):
        if DEBUG: print >>sys.stderr, "   %s: %s (%s) -> %s" % (str(self), self.__stateString(self.__state), self.__stateString(curState), self.__stateString(newState))
        prevState = self.__state
        self.__state = newState
        if prevState != curState:
            raise LogParseException(("DOM %s should be in %s state, not %s" +
                                     " (moving to %s)") %
                                    (str(self), self.__stateString(curState),
                                     self.__stateString(prevState),
                                     self.__stateString(newState)))

    def addGPSFailure(self):
        self.__gpsFails += 1

    def addTCalFailure(self):
        self.__tcalFails += 1

    def addWildTCal(self):
        self.__wildTCals += 1

    def getGPSFailures(self):
        return self.__gpsFails

    def getTCalFailures(self):
        return self.__tcalFails

    def getWildTCals(self):
        return self.__wildTCals

    def isStopped(self):
        return self.__state == self.STATE_STOPPED

    def setConfigSignal(self):
        self.__transition(self.STATE_INITIAL, self.STATE_SIGCONFIG)

    def setConfiguring(self):
        self.__transition(self.STATE_SIGCONFIG, self.STATE_CONFIGING)

    def setConfigFinished(self, millis):
        self.__transition(self.STATE_CONFIGING, self.STATE_FINISHCFG)
        self.__cfgMillis = millis

    def setReady(self):
        self.__transition(self.STATE_FINISHCFG, self.STATE_READY)

    def setRunning(self):
        self.__transition(self.STATE_STARTRUN, self.STATE_RUNNING)

    def setSimReady(self):
        self.__transition(self.STATE_INITIAL, self.STATE_READY)

    def setStartRun(self):
        self.__transition(self.STATE_READY, self.STATE_STARTRUN)

    def setStopping(self):
        expState = self.STATE_RUNNING
        if self.__state == self.STATE_READY or \
                self.__state == self.STATE_STOPPING:
            expState = self.__state
        self.__transition(expState, self.STATE_STOPPING)

    def setStopped(self):
        self.__transition(self.STATE_STOPPING, self.STATE_STOPPED)

    def state(self): return self.__stateString(self.__state)

class SimDom(BaseDom):
    def __init__(self, dcName):
        super(SimDom, self).__init__(dcName)

class RealDom(BaseDom):
    def __init__(self, dcName, domId, mbRel):
        self.__id = long(domId, 16)
        self.__mbRel = mbRel

        super(RealDom, self).__init__(dcName)

    def __str__(self):
        return "%12x" % self.__id

    def id(self): return self.__id

class StringHubLog(ComponentLog):
    FOUND_PAIR = re.compile(r"^(|.*\]\s+)Found powered pair on" +
                            r" \((\d+), (\d+)\)\.\s*$")
    FOUND_DOM = re.compile(r"^(|.*\]\s+)Found active DOM on" +
                           r" \((\d+), (\d+), (\S+)\)\s*$")
    FOUND_TOTAL = re.compile(r"^(|.*\]\s+)Found (\d+) active DOMs\.\s*$")
    LOAD_CFG = re.compile(r"^(|.*\]\s+)Configuring (.*) -" +
                          r" loading config from (\S+)\s*$")
    CFG_DONE = re.compile(r"^(|.*\]\s+)Configuration successfully" +
                          r" loaded.*size\(\)" +
                          " = (\d+)\s*$")
    DOM_REL = re.compile(r"^.*DataCollector-(\d\d[AB]) \S+ \[[^\]]+\]" +
                         " Found DOM (\S+) running (\S+)\s*$")
    SIMDOM_REL = re.compile(r"^.*DataCollector-(\d\d[AB]) \S+ \[[^\]]+\]" +
                         " Simulated DOM at (\S+) started at dom clock (\d+)$")
    DOM_GENERIC = re.compile(r"^.*(DataCollector|AbstractRAPCal|Driver)" +
                             r"-(\d\d[AB]) \S+ \[[^\]]+\] (.*)$")
    CONFIG_DOM = re.compile(r"^Configuring DOM on \[(\d\d[AB])\].*$")
    FINISH_CFG = re.compile(r"^Finished DOM configuration - \[(\d\d[AB])\];" +
                            r" configuration took (\d+) milliseconds.*$")
    START_RUN = re.compile(r"^Got START RUN signal \[(\d\d[AB])\].*$")

    STATE_INITIAL = 0
    STATE_FOUND = 1
    STATE_CONFIG = 2
    STATE_DCTHREAD = 3
    STATE_START = 4
    STATE_STOPPING = 5
    STATE_STOPPED = 6

    def __init__(self, fileName):
        idStr = fileName[10:-4]
        try:
            self.__hubId = int(idStr)
        except:
            raise LogParseException("Unknown hub ID \"%s\" in \"%s\"" %
                                    (idStr, fileName))

        self.__wildTCals = 0
        self.__tcalFails = 0
        self.__outOfOrder = 0
        self.__gpsNotReady = 0

        self.__domMap = {}
        self.__prevRpt = []

        super(StringHubLog, self).__init__(fileName)

    def __getCardLoc(self, num, showAB=True):
        card = int(num / 8)
        pair = int(num / 2) % 4
        if not showAB:
            return "(%d, %d)" % (card, pair)

        if num % 2 == 0:
            ab = "A"
        else:
            ab = "B"

        return "(%d, %d, %s)" % (card, pair, ab)
            
    def __getPairNumber(self, card, pair, ab):
        if ab == "A":
            abNum = 0
        else:
            abNum = 1
        return card * 8 + pair * 2 + abNum

    def __stateString(cls, val):
        if val == cls.STATE_INITIAL:
            return "INITIAL"
        if val == cls.STATE_FOUND:
            return "FOUND"
        if val == cls.STATE_CONFIG:
            return "CONFIG"
        if val == cls.STATE_DCTHREAD:
            return "DCTHREAD"
        if val == cls.STATE_START:
            return "START"
        if val == cls.STATE_STOPPING:
            return "STOPPING"
        if val == cls.STATE_STOPPED:
            return "STOPPED"

        return "??%d??" % val
    __stateString = classmethod(__stateString)

    def parse(self, path):
        nextFound = 0
        totalDOMs = 0
        loadCfg = None
        numDCThreads = 0
        inTCalException = False
        inPipeException = False

        state = self.STATE_INITIAL

        fd = open(path, "r")
        for line in fd:
            line = line.rstrip()

            if DEBUG: print >>sys.stderr, ":: " + line
            if state == self.STATE_INITIAL:
                if self.checkInitialLogMessage(line) or \
                        line.find("Resetting logging") >= 0:
                    continue

                if self.checkVersionInfoMessage(line):
                    state = self.STATE_FOUND
                    nextFound = 0
                    continue

                if line.find("Found STOP symbol in stream - shutting down"):
                    continue

            elif state == self.STATE_FOUND:
                m = self.FOUND_DOM.match(line)
                if m:
                    num = self.__getPairNumber(int(m.group(2)), int(m.group(3)),
                                               m.group(4))
                    if num == nextFound:
                        if self.__hubId < 200:
                            nextFound += 1
                        else:
                            nextFound += 2
                    else:
                        self.__prevRpt.append(("Previous DOM on %s (#%d)," +
                                               " current DOM on %s (#%d)") %
                                              (self.__getCardLoc(nextFound),
                                               nextFound, self.__getCardLoc(num),
                                               num))
                        nextFound = num + 1
                    totalDOMs += 1
                    continue

                m = self.FOUND_PAIR.match(line)
                if m:
                    num = self.__getPairNumber(int(m.group(2)), int(m.group(3)),
                                               "A")
                    if num != nextFound:
                        self.__prevRpt.append(("Previous pair on %s (#%d)," +
                                               " current pair on %s (#%d)") %
                                              (self.__getCardLoc(nextFound,
                                                                 False),
                                               nextFound,
                                               self.__getCardLoc(num, False),
                                               num))
                        nextFound = num
                    continue

                m = self.FOUND_TOTAL.match(line)
                if m:
                    num = int(m.group(2))
                    if num != totalDOMs:
                        self.logError("Found %d DOMs (should be %d)" %
                                        (num, totalDOMs))
                        totalDOMs = num
                    state = self.STATE_CONFIG
                    continue

                if line.find("Number of domConfigNodes found:") >= 0:
                    state = self.STATE_CONFIG
                    continue

            elif state == self.STATE_CONFIG:
                if line.find("Number of domConfigNodes found:") >= 0:
                    continue

                if loadCfg is None:
                    m = self.LOAD_CFG.match(line)
                    if m:
                        loadCfg = m.group(3)
                        continue
                else:
                    if line.find("XML parsing completed - took ") < 0:
                        self.logError("While loading config \"%s\", got: %s" %
                                        (loadCfg, line))
                    loadCfg = None
                    continue

                m = self.CFG_DONE.match(line)
                if m:
                    num = int(m.group(2))
                    if totalDOMs == 0:
                        totalDOMs = num
                    elif num != totalDOMs:
                        self.logError("Expected to configure %d DOMS, not %d" %
                                        (totalDOMs, num))
                    state = self.STATE_DCTHREAD
                    continue

            elif state == self.STATE_DCTHREAD:
                if DEBUG: print >>sys.stderr, "--InDCThread--"
                if line.find("Begin data collection thread") >= 0:
                    numDCThreads += 1
                    continue

                if line.find("Starting up HKN1 sorting trees") >= 0:
                    continue

                if line.find("StringHub is starting the run.") >= 0 or \
                        line.find("signalStartRun") >= 0:
                    state = self.STATE_START
                    continue

                m = self.DOM_REL.match(line)
                if m:
                    dom = RealDom(m.group(1), m.group(2), m.group(3))
                    self.__domMap[m.group(1)] = dom
                    continue

                m = self.SIMDOM_REL.match(line)
                if m:
                    dom = SimDom(m.group(1))
                    self.__domMap[m.group(2)] = dom
                    continue

                m = self.DOM_GENERIC.match(line)
                if m:
                    cardLoc = m.group(2)
                    msg = m.group(3)

                    if msg.find("Entering run loop") >= 0:
                        continue

                    if not self.__domMap.has_key(cardLoc):
                        self.logError("Got unknown card \"%s\"" % cardLoc)
                        continue

                    if msg.find("Got CONFIGURE signal") >= 0:
                        try:
                            self.__domMap[cardLoc].setConfigSignal()
                        except LogParseException, lpe:
                            self.logError(("WARNING: %s configure" +
                                             " signal: %s") %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

                    m = self.CONFIG_DOM.match(msg)
                    if m:
                        if cardLoc != m.group(1):
                            self.logError(("Got configure msg for DOM %s" +
                                             " from DataCollector %s") %
                                            (m.group(1), cardLoc))
                        try:
                            self.__domMap[cardLoc].setConfiguring()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s configuring: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

                    m = self.FINISH_CFG.match(msg)
                    if m:
                        if cardLoc != m.group(1):
                            self.logError(("Got finishCfg msg for DOM %s" +
                                             " from DataCollector %s") %
                                            (m.group(1), cardLoc))
                        try:
                            val = int(m.group(2))
                            self.__domMap[cardLoc].setConfigFinished(val)
                        except LogParseException, lpe:
                            self.logError("WARNING: %s finished cfg: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

                    if msg.find("DOM is configured") >= 0:
                        try:
                            self.__domMap[cardLoc].setReady()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s ready: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

                    if msg.find("DOM is now configured") >= 0:
                        try:
                            self.__domMap[cardLoc].setSimReady()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s ready: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

                if line.find("Data collector ensemble has been configured") >= 0:
                    state = self.STATE_START
                    continue

            elif state == self.STATE_START:
                if len(line.rstrip()) == 0:
                    continue

                if line.find("StringHub is starting the run.") >= 0 or \
                        line.find("signalStartRun") >= 0:
                    continue

                if inTCalException:
                    if line.find("STDERR-") >= 0 and \
                            (line.find(" at ") > 0 or
                             line.find("	at ") > 0):
                        continue

                    inTCalException = False
                    # stack trace is done, keep looking for matches

                if line.find("STDERR-") >= 0 and \
                        line.find("TCAL read failed") >= 0:
                    inTCalException = True
                    continue

                if inPipeException:
                    if (line.find(" at ") >= 0 or line.find("	at ") >= 0):
                        continue

                    inPipeException = False
                    # stack trace is done, keep looking for matches

                if line.find("IOException: Broken pipe") >= 0:
                    self.logError(line)
                    inPipeException = True
                    continue

                if line.find("Out-of-order sorted value") >= 0:
                    self.__outOfOrder += 1
                    continue

                if line.find("GPS not ready") >= 0:
                    self.__gpsNotReady += 1
                    continue

                m = self.DOM_GENERIC.match(line)
                if m:
                    cardLoc = m.group(2)
                    msg = m.group(3)

                    if not self.__domMap.has_key(cardLoc):
                        self.logError("Got unknown card \"%s\"" % cardLoc)
                        continue

                    if msg.find("DOM is running") >= 0:
                        try:
                            self.__domMap[cardLoc].setRunning()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s running: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

                    if msg.find("Got STOP RUN signal") >= 0 or \
                            msg.find("Stopping data collection") >= 0 or \
                            msg.find("Exited runCore() loop") >= 0:
                        try:
                            self.__domMap[cardLoc].setStopping()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s stopping: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        state = self.STATE_STOPPING
                        continue

                    if msg.find("Wild TCAL") >= 0:
                        self.__domMap[cardLoc].addWildTCal()
                        continue

                    if msg.find("TCAL read failed") >= 0:
                        self.__domMap[cardLoc].addTCalFailure()
                        continue

                    if msg.find("Failed GPS read") >= 0:
                        self.__domMap[cardLoc].addGPSFailure()
                        continue

                    m = self.START_RUN.match(msg)
                    if m:
                        if cardLoc != m.group(1):
                            self.logError(("Got start run for DOM %s" +
                                             " from DataCollector %s") %
                                            (m.group(1), cardLoc))
                        try:
                            self.__domMap[cardLoc].setStartRun()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s(%s) start run: %s" %
                                            (cardLoc, str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

            elif state == self.STATE_STOPPING:
                if len(line.rstrip()) == 0:
                    continue

                if line.find("StringHub is starting the run.") >= 0 or \
                        line.find("signalStartRun") >= 0:
                    continue

                if line.find("Found STOP symbol in stream - ") >= 0 or \
                        line.find("Stopping payload destinations") >= 0:
                    continue

                if line.find("Returning from stop.") >= 0 or \
                        line.find("Resetting logging") >= 0:
                    state = self.STATE_STOPPED
                    continue

                if inPipeException:
                    if (line.find(" at ") >= 0 or line.find("	at ") >= 0):
                        continue

                    inPipeException = False
                    # stack trace is done, keep looking for matches

                if line.find("IOException: Broken pipe") >= 0:
                    self.logError(line)
                    inPipeException = True
                    continue

                m = self.DOM_GENERIC.match(line)
                if m:
                    cardLoc = m.group(2)
                    msg = m.group(3)

                    if not self.__domMap.has_key(cardLoc):
                        self.logError("Got unknown card \"%s\"" % cardLoc)
                        continue

                    if msg.find("Got STOP RUN signal") >= 0 or \
                            msg.find("Stopping data collection") >= 0 or \
                            msg.find("Exited runCore() loop") >= 0:
                        try:
                            self.__domMap[cardLoc].setStopping()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s stopping: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

                    if msg.find("Wrote EOS to streams.") >= 0:
                        try:
                            self.__domMap[cardLoc].setStopped()
                        except LogParseException, lpe:
                            self.logError("WARNING: %s stopped: %s" %
                                            (str(self.__domMap[cardLoc]),
                                             str(lpe)))
                        continue

            elif state == self.STATE_STOPPED:
                if line.find("Found STOP symbol in stream - shutting down"):
                    continue

            self.logError("State %s: %s" % (self.__stateString(state), line))

    def report(self, fd, verbose):
        if verbose:
            if self.__gpsNotReady > 0:
                print >>fd, "%s: %d \"GPS not ready\" warnings" % \
                    (self.fileName(), self.__gpsNotReady)
            if self.__outOfOrder > 0:
                print >>fd, "%s: %d out-of-order values" % \
                    (self.fileName(), self.__outOfOrder)
            for pr in self.__prevRpt:
                print >>fd, "%s: %s" % (self.fileName(), pr)
            for dom in self.__domMap.values():
                if not dom.isStopped():
                    print >>fd, "%s: %s %s" % \
                        (self.fileName(), str(dom), dom.state())
                elif dom.getWildTCals() > 0 or dom.getTCalFailures() > 0:
                    print >>fd, "%s: %s TCals: %d wild, %d failures" % \
                        (self.fileName(), str(dom), dom.getWildTCals(),
                         dom.getTCalFailures())

def processDir(dirName, outFD, verbose):
    subdir = []

    for f in os.listdir(dirName):
        path = os.path.join(dirName, f)

        if os.path.isdir(path):
            subdir.append(path)
            continue

        if not os.path.isfile(path):
            print >>sys.stderr, "Cannot find \"%s\"" % path
            continue

        # ignore MBean output files
        if f.endswith(".moni"): continue

        processFile(path, outFD, verbose)

def processFile(path, outFD, verbose):
    fileName = os.path.basename(path)

    log = None
    if not fileName.endswith(".log"):
        print "Ignoring \"%s\"" % path
    elif fileName.startswith("stringHub-"):
        log = StringHubLog(fileName)
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
        log = DashLog(fileName)
    else:
        print >>sys.stderr, "Unknown log file \"%s\"" % path

    if log is not None:
        if verbose:
            print "=== %s" % fileName
        log.parse(path)
        log.reportErrors(outFD)
        log.report(outFD, verbose)

if __name__ == "__main__":
    verbose = False
    dirList = []
    fileList = []

    usage = False
    for arg in sys.argv[1:]:
        if arg == "-v":
            verbose = True
            continue

        if os.path.isdir(arg):
            dirList.append(arg)
            continue

        if os.path.isfile(arg):
            fileList.append(arg)
            continue

        print >>sys.stderr, "Cannot find \"%s\"" % arg
        usage = True

    if usage:
        print >>sys.stderr, "Usage: %s ( logFile | logDir )" + \
            " [ ( logFile | logDir ) ... ]"
        raise SystemExit

    for f in fileList:
        processFile(f, sys.stdout, verbose)

    for d in dirList:
        processDir(d, sys.stdout, verbose)
