#!/usr/bin/env python

import datetime, os, socket, time

import SpadeQueue

from CnCThread import CnCThread
from CompOp import ComponentOperation, ComponentOperationGroup, Result
from DAQConfig import DOMNotInConfigException
from DAQConst import DAQPort
from DAQLaunch import killJavaComponents, startJavaComponents
from DAQLog import DAQLog, FileAppender, LiveSocketAppender, LogSocketServer
from DAQRPC import RPCClient
from LiveImports import MoniClient, Prio
from RunOption import RunOption
from RunSetDebug import RunSetDebug
from RunSetState import RunSetState
from RunStats import PayloadTime, RunStats
from TaskManager import TaskManager
from UniqueID import UniqueID

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class RunSetException(Exception): pass
class ConnectionException(RunSetException): pass
class InvalidSubrunData(RunSetException): pass

class Connection(object):
    """
    Component connection data to be passed to a component
    conn - connection description
    comp - component
    """

    def __init__(self, conn, comp):
        """
        Connection constructor
        conn - connection description
        comp - component
        """
        self.conn = conn
        self.comp = comp

    def __str__(self):
        "String description"
        frontStr = '%s:%s#%d@%s' % \
            (self.conn.name(), self.comp.name(), self.comp.num(),
             self.comp.host())
        if not self.conn.isInput():
            return frontStr
        return '%s:%d' % (frontStr, self.conn.port())

    def map(self):
        connDict = {}
        connDict['type'] = self.conn.name()
        connDict['compName'] = self.comp.name()
        connDict['compNum'] = self.comp.num()
        connDict['host'] = self.comp.host()
        connDict['port'] = self.conn.port()
        return connDict

class ConnTypeEntry(object):
    """
    Temporary class used to build the connection map for a runset
    type - connection type
    inList - list of [input connection, component] entries
    outList - list of output connections
    """
    def __init__(self, type):
        """
        ConnTypeEntry constructor
        type - connection type
        """
        self.__type = type
        self.__inList = []
        self.__optInList = []
        self.__outList = []
        self.__optOutList = []

    def __str__(self):
        return '%s in#%d out#%d' % (self.__type, len(self.__inList),
                                    len(self.__outList))

    def add(self, conn, comp):
        "Add a connection and component to the appropriate list"
        if conn.isInput():
             if conn.isOptional():
                 self.__optInList.append([conn, comp])
             else:
                 self.__inList.append([conn, comp])
        else:
             if conn.isOptional():
                 self.__optOutList.append(comp)
             else:
                 self.__outList.append(comp)

    def buildConnectionMap(self, connMap):
        "Validate and fill the map of connections for each component"

        inLen = len(self.__inList) + len(self.__optInList)
        outLen = len(self.__outList) + len(self.__optOutList)

        # if there are no inputs and no required outputs (or no required
        # inputs and no outputs), we're done
        if (outLen == 0 and len(self.__inList) == 0) or \
               (inLen == 0 and len(self.__outList) == 0):
            return

        # if there are no inputs, throw an error
        if inLen == 0:
            outStr = ''
            for outComp in self.__outList + self.__optOutList:
                if len(outStr) == 0:
                    outStr = str(outComp)
                else:
                    outStr += ', ' + str(outComp)
            raise ConnectionException('No inputs found for %s outputs (%s)' %
                                      (self.__type, outStr))

        # if there are no outputs, throw an error
        if outLen == 0:
            inStr = ''
            for inPair in self.__inList + self.__optInList:
                if len(inStr) == 0:
                    inStr = str(inPair[1])
                else:
                    inStr += ', ' + str(inPair[1])
            raise ConnectionException('No outputs found for %s inputs (%s)' %
                                      (self.__type, inStr))

        # if there are multiple inputs and outputs, throw an error
        if inLen > 1 and outLen > 1:
            raise ConnectionException('Found %d %s inputs for %d outputs' %
                                      (inLen, self.__type, outLen))

        # at this point there is either a single input or a single output

        if inLen == 1:
            if len(self.__inList) == 1:
                inObj = self.__inList[0]
            else:
                inObj = self.__optInList[0]
            inConn = inObj[0]
            inComp = inObj[1]

            for outComp in self.__outList + self.__optOutList:
                entry = Connection(inConn, inComp)

                if not connMap.has_key(outComp):
                    connMap[outComp] = []
                connMap[outComp].append(entry)
        else:
            if len(self.__outList) == 1:
                outComp = self.__outList[0]
            else:
                outComp = self.__optOutList[0]

            for inConn, inComp in self.__inList + self.__optInList:
                entry = Connection(inConn, inComp)

                if not connMap.has_key(outComp):
                    connMap[outComp] = []
                connMap[outComp].append(entry)

class SubrunThread(CnCThread):
    "A thread which starts the subrun in an individual stringHub"

    def __init__(self, comp, data, log):
        self.__comp = comp
        self.__data = data
        self.__log = log
        self.__time = None

        super(SubrunThread, self).__init__(comp.fullName() + ":subrun", log)

    def _run(self):
        tStr = self.__comp.startSubrun(self.__data)
        if tStr is not None:
            try:
                self.__time = long(tStr)
            except ValueError:
                self.__log.error(("Component %s startSubrun returned bad" +
                                  " value \"%s\"") %
                                 (str(self.__comp), tStr))
                self.__time = 0

    def comp(self):
        return self.__comp

    def finished(self):
        return self.__time is not None

    def fullName(self):
        return self.__comp.fullName()

    def time(self):
        return self.__time

class RunData(object):
    def __init__(self, runSet, runNumber, clusterConfigName, runConfigName,
                 runOptions, versionInfo, spadeDir, copyDir, logDir, testing):
        """
        RunData constructor
        runSet - run set which uses this data
        runNum - current run number
        clusterConfigName - current cluster configuration file name
        runOptions - logging/monitoring options
        versionInfo - release and revision info
        spadeDir - directory where SPADE files are written
        copyDir - directory where a copy of the SPADE files is kept
        logDir - top-level logging directory
        testing - True if this is called from a unit test
        """
        self.__runNumber = runNumber
        self.__runOptions = runOptions

        if not RunOption.isLogToFile(self.__runOptions):
            self.__logDir = None
            self.__runDir = None
        else:
            if logDir is None:
                raise RunSetException("Log directory not specified for" +
                                      " file logging")

            self.__logDir = logDir
            self.__runDir = runSet.createRunDir(self.__logDir,
                                                self.__runNumber)

        self.__spadeDir = spadeDir
        self.__copyDir = copyDir

        if not os.path.exists(self.__spadeDir):
            raise RunSetException("SPADE directory %s does not exist" %
                                  self.__spadeDir)

        if not testing:
            self.__dashlog = self.__createDashLog()
        else:
            self.__dashlog = runSet.createDashLog()

        self.__dashlog.error(("Version info: %(filename)s %(revision)s" +
                              " %(date)s %(time)s %(author)s %(release)s" +
                              " %(repo_rev)s") % versionInfo)
        self.__dashlog.error("Run configuration: %s" % runConfigName)
        self.__dashlog.error("Cluster configuration: %s" % clusterConfigName)

        self.__taskMgr = None
        self.__liveMoniClient = None

        self.__runStats = RunStats()

        self.__firstPayTime = -1

    def __str__(self):
        return "Run#%d %s" % (self.__runNumber, self.__runStats)

    def __getRateData(self, comps):
        nEvts = 0
        evtTime = -1
        payloadTime = -1
        nMoni = 0
        moniTime = -1
        nSN = 0
        snTime = -1
        nTCal = 0
        tcalTime = -1

        for c in comps:
            if c.isComponent("eventBuilder"):
                evtData = self.getSingleBeanField(c, "backEnd", "EventData")
                if type(evtData) == Result:
                    self.__dashlog.error("Cannot get event data (%s)" %
                                         evtData)
                elif type(evtData) == list or type(evtData) == tuple:
                    nEvts = int(evtData[0])
                    evtTime = datetime.datetime.utcnow()
                    payloadTime = long(evtData[1])

                if nEvts > 0 and self.__firstPayTime <= 0:
                    val = self.getSingleBeanField(c, "backEnd",
                                                  "FirstEventTime")
                    if type(val) == Result:
                        msg = "Cannot get first event time (%s)" % val
                        self.__dashlog.error(msg)
                    else:
                        self.__firstPayTime = val
                        self.__reportRunStart()

            if c.isComponent("secondaryBuilders"):
                for bldr in ("moni", "sn", "tcal"):
                    val = self.getSingleBeanField(c, bldr + "Builder",
                                                  "TotalDispatchedData")
                    if type(val) == Result:
                        msg = "Cannot get %sBuilder dispatched data (%s)" % \
                            (bldr, val)
                        self.__dashlog.error(msg)
                    else:
                        num = int(val)
                        time = datetime.datetime.utcnow()

                        if bldr == "moni":
                            nMoni = num
                            moniTime = time
                        elif bldr == "sn":
                            nSN = num
                            snTime = time
                        elif bldr == "tcal":
                            nTCal = num
                            tcalTime = time

        return (nEvts, evtTime, self.__firstPayTime, payloadTime, nMoni,
                moniTime, nSN, snTime, nTCal, tcalTime)

    def __createDashLog(self):
        log = DAQLog(level=DAQLog.ERROR)

        if RunOption.isLogToFile(self.__runOptions):
            if self.__runDir is None:
                raise RunSetException("Run directory has not been specified")
            app = FileAppender("dashlog", os.path.join(self.__runDir,
                                                       "dash.log"))
            log.addAppender(app)

        if RunOption.isLogToLive(self.__runOptions):
            app = LiveSocketAppender("localhost", DAQPort.I3LIVE,
                                     priority=Prio.ITS)
            log.addAppender(app)

        return log

    def __reportRunStart(self):
        if self.__liveMoniClient is not None:
            time = PayloadTime.toDateTime(self.__firstPayTime)
            data = { "runnum" : self.__runNumber }
            self.__liveMoniClient.sendMoni("runstart", data, prio=Prio.SCP,
                                           time=time)

    def __reportRunStop(self, numEvts, lastPayTime):
        if self.__liveMoniClient is not None:
            time = PayloadTime.toDateTime(lastPayTime)
            data = { "events" : numEvts, "runnum" : self.__runNumber }
            self.__liveMoniClient.sendMoni("runstop", data, prio=Prio.SCP,
                                           time=time)

    def destroy(self):
        self.stop()
        if self.__liveMoniClient is not None:
            self.__liveMoniClient.close()
        self.__dashlog.close()

    def error(self, msg):
        self.__dashlog.error(msg)

    def finishSetup(self, runSet):
        self.__liveMoniClient = MoniClient("pdaq", "localhost", DAQPort.I3LIVE)
        if str(self.__liveMoniClient).startswith("BOGUS"):
            self.__liveMoniClient = None
            if not RunSet.LIVE_WARNING:
                RunSet.LIVE_WARNING = True
                self.__dashlog.error("Cannot import IceCube Live code, so" +
                                    " per-string active DOM stats wil not" +
                                    " be reported")

        self.__taskMgr = runSet.createTaskManager(self.__dashlog,
                                                  self.__liveMoniClient,
                                                  self.__runDir,
                                                  self.__runOptions)
        self.__taskMgr.start()

    def getEventCounts(self, state, comps):
        "Return monitoring data for the run"
        monDict = {}

        if state == RunSetState.RUNNING:
            self.__runStats.updateEventCounts(self.__getRateData(comps), True)
        (numEvts, evtTime, payTime, numMoni, moniTime, numSN, snTime,
         numTcal, tcalTime) = self.__runStats.monitorData()

        monDict["physicsEvents"] = numEvts
        monDict["eventTime"] = str(evtTime)
        monDict["eventPayloadTime"] = str(payTime)
        monDict["moniEvents"] = numMoni
        monDict["moniTime" ] = str(moniTime)
        monDict["snEvents"] = numSN
        monDict["snTime" ] = str(snTime)
        monDict["tcalEvents"] = numTcal
        monDict["tcalTime" ] = str(tcalTime)

        return monDict

    def getSingleBeanField(self, comp, bean, fldName):
        tGroup = ComponentOperationGroup(ComponentOperation.GET_SINGLE_BEAN)
        tGroup.start(comp, self.__dashlog, (bean, fldName))
        tGroup.wait(10)

        r = tGroup.results()
        if not r.has_key(comp):
            result = ComponentOperation.RESULT_ERROR
        else:
            result = r[comp]

        return result

    def info(self, msg):
        self.__dashlog.info(msg)

    def queueForSpade(self, duration):
        if self.__logDir is None:
            self.__dashlog.error("Not logging to file so cannot queue to SPADE")
            return

        SpadeQueue.queueForSpade(self.__dashlog, self.__spadeDir,
                                 self.__copyDir, self.__runDir,
                                 self.__runNumber, datetime.datetime.now(),
                                 duration)

    def reportRates(self, comps):
        try:
            (numEvts, numMoni, numSN, numTcal, duration, lastTime) = \
                self.__runStats.stop(self.__getRateData(comps))
        except:
            (numEvts, numMoni, numSN, numTcal, duration, lastTime) = \
                (0, 0, 0, 0, 0, 0)
            self.__dashlog.error("Could not get event count: " + exc_string())
            return -1

        self.__reportRunStop(numEvts, lastTime)

        if duration == 0:
            rateStr = ""
        else:
            rateStr = " (%2.2f Hz)" % (float(numEvts) / float(duration))
        self.__dashlog.error(("%d physics events collected in %d " +
                              "seconds%s") % (numEvts, duration, rateStr))
        self.__dashlog.error("%d moni events, %d SN events, %d tcals" %
                             (numMoni, numSN, numTcal))
        return duration

    def reset(self):
        if self.__taskMgr is not None:
            self.__taskMgr.reset()

    def runDirectory(self):
        return self.__runDir

    def runNumber(self):
        return self.__runNumber

    def sendEventCounts(self, state, comps):
        "Report run monitoring quantities"
        moniData = self.getEventCounts(state, comps)
        if False:
            # send entire dictionary using JSON
            self.__liveMoniClient.sendMoni("eventRates", moniData, Prio.ITS)
        else:
            # send discrete messages for each type of event
            self.__liveMoniClient.sendMoni("physicsEvents",
                                           moniData["physicsEvents"],
                                           Prio.ITS,
                                           moniData["eventPayloadTime"])
            self.__liveMoniClient.sendMoni("walltimeEvents",
                                           moniData["physicsEvents"],
                                           Prio.EMAIL, moniData["eventTime"])
            self.__liveMoniClient.sendMoni("moniEvents", moniData["moniEvents"],
                                           Prio.EMAIL, moniData["moniTime"])
            self.__liveMoniClient.sendMoni("snEvents", moniData["snEvents"],
                                           Prio.EMAIL, moniData["snTime"])
            self.__liveMoniClient.sendMoni("tcalEvents",
                                           moniData["tcalEvents"],
                                           Prio.EMAIL, moniData["tcalTime"])

    def setDebugBits(self, debugBits):
        if self.__taskMgr is not None:
            self.__taskMgr.setDebugBits(debugBits)

    def stop(self):
        if self.__taskMgr is not None:
            self.__taskMgr.stop()

    def updateRates(self, comps):
        self.__runStats.updateEventCounts(self.__getRateData(comps), True)

        rateStr = ""
        rate = self.__runStats.rate()
        if rate == 0.0:
            rateStr = ""
        else:
            rateStr = " (%2.2f Hz)" % rate

        (evtTime, numEvts, numMoni, numSN, numTcal) = \
            self.__runStats.currentData()

        self.__dashlog.error(("\t%s physics events%s, %s moni events," +
                              " %s SN events, %s tcals")  %
                             (numEvts, rateStr, numMoni, numSN, numTcal))

    def warn(self, msg):
        self.__dashlog.warn(msg)

class RunSet(object):
    "A set of components to be used in one or more runs"

    # next runset ID
    #
    ID = UniqueID()

    # number of seconds to wait after stopping components seem to be
    # hung before forcing remaining components to stop
    #
    TIMEOUT_SECS = RPCClient.TIMEOUT_SECS - 5

    # True if we've printed a warning about the failed IceCube Live code import
    LIVE_WARNING = False

    STATE_DEAD = "DEAD"

    def __init__(self, parent, cfg, set, logger):
        """
        RunSet constructor:
        parent - main server
        cfg - parsed run configuration file data
        set - list of components
        logger - logging object

        Class attributes:
        id - unique runset ID
        configured - true if this runset has been configured
        runNumber - run number (if assigned)
        state - current state of this set of components
        """
        self.__parent = parent
        self.__cfg = cfg
        self.__set = set
        self.__logger = logger

        self.__id = RunSet.ID.next()

        self.__configured = False
        self.__state = RunSetState.IDLE
        self.__runData = None
        self.__compLog = {}
        self.__stopping = False

        self.__debugBits = 0x0

    def __repr__(self):
        return str(self)

    def __str__(self):
        "String description"
        if self.__id is None:
            setStr = "DESTROYED RUNSET"
        else:
            setStr = 'RunSet #%d' % self.__id
        if self.__runData is not None:
            setStr += ' run#%d' % self.__runData.runNumber()
        setStr += " (%s)" % self.__state
        return setStr

    def __badStateString(self, badList):
        badStr = []
        for b in badList:
            badStr.append(b[0].fullName() + ":" + b[1])
        return str(badStr)

    def __checkState(self, newState):
        """
        If component states match 'newState', set state to 'newState' and
        return an empty list.
        Otherwise, set state to ERROR and return a list of component/state
        pairs.
        """
        slst = []

        tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
        for c in self.__set:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        states = tGroup.results()
        for c in self.__set:
            if states.has_key(c):
                stateStr = str(states[c])
            else:
                stateStr = self.STATE_DEAD
            if stateStr != newState:
                slst.append((c, stateStr))

        if len(slst) == 0:
            self.__state = newState
        else:
            msg = "Failed to transition to %s: %s" % (newState, slst)
            if self.__runData is not None:
                self.__runData.error(msg)
            else:
                self.__logger.error(msg)
            self.__state = RunSetState.ERROR

        return slst

    def __getHostAddr(self, remoteAddr=None):
        """
        Adapted from
        http://mail.python.org/pipermail/python-list/2005-January/300454.html
        """

        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        dummyAddr = "192.168.123.123"
        dummyPort = 56

        if remoteAddr is None:
            remoteAddr = dummyAddr
        else:
            try:
                socket.getaddrinfo(remoteAddr, dummyPort)
            except socket.gaierror:
                remoteAddr = dummyAddr

        s.connect((remoteAddr, dummyPort))
        addr = s.getsockname()[0]
        s.close()
        return addr

    def __listComponentsCommaSep(cls, compList):
        """
        Concatenate a list of components into a string showing names and IDs
        """
        compStr = None
        for c in compList:
            if compStr == None:
                compStr = ''
            else:
                compStr += ', '
            compStr += c.fullName()
        return compStr
    __listComponentsCommaSep = classmethod(__listComponentsCommaSep)

    def __logDebug(self, debugBit, *args):
        if (self.__debugBits & debugBit) != debugBit:
            return

        if self.__runData is not None:
            logger = self.__runData
        else:
            logger = self.__logger

        if len(args) == 1:
            logger.error(args[0])
        else:
            logger.error(args[0] % args[1:])

    def __startComponents(self, quiet):
        liveHost = None
        livePort = None

        tGroup = ComponentOperationGroup(ComponentOperation.CONFIG_LOGGING)

        host = self.__getHostAddr()

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP initLogs")
        port = DAQPort.RUNCOMP_BASE
        for c in self.__set:
            self.__compLog[c] = \
                self.createComponentLog(self.__runData.runDirectory(), c,
                                        host, port, liveHost, livePort,
                                        quiet=quiet)
            tGroup.start(c, self.__runData, (host, port, liveHost, livePort))

            port += 1

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP waitLogs")
        tGroup.wait()
        tGroup.reportErrors(self.__runData, "startLogging")

        self.__runData.error("Starting run %d..." % self.__runData.runNumber())

        srcSet = []
        otherSet = []

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP bldSet")
        failStr = None
        for c in self.__set:
            if c.order() is not None:
                if c.isSource():
                    srcSet.append(c)
                else:
                    otherSet.append(c)
            else:
                if not failStr:
                    failStr = 'No order set for ' + str(c)
                else:
                    failStr += ', ' + str(c)
        if failStr:
            raise RunSetException(failStr)

        self.__state = RunSetState.STARTING

        # start non-sources in order (back to front)
        #
        otherSet.sort(self.sortCmp)
        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP startOther")
        for c in otherSet:
            c.startRun(self.__runData.runNumber())

        # start sources in parallel
        #
        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP startSrcs")
        tGroup = ComponentOperationGroup(ComponentOperation.START_RUN)
        opData = (self.__runData.runNumber(), )
        for c in srcSet:
            tGroup.start(c, self.__runData, opData)
        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP waitSrcs")
        tGroup.wait()
        tGroup.reportErrors(self.__runData, "startRun")

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP waitStChg")
        self.__waitForStateChange(self.__runData, 30)

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP chkRunning")
        badList = self.__checkState(RunSetState.RUNNING)
        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP badList %s", badList)
        if len(badList) > 0:
            raise RunSetException(("Could not start runset#%d run#%d" +
                                   " components: %s") %
                                  (self.__id, self.__runData.runNumber(),
                                   self.__badStateString(badList)))

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP done")

    def __stopLogging(self):
        self.resetLogging()
        tGroup = ComponentOperationGroup(ComponentOperation.STOP_LOGGING)
        for c in self.__set:
            tGroup.start(c, self.__logger, self.__compLog)
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "stopLogging")

    def __stopRunInternal(self, hadError=False):
        """
        Stop all components in the runset
        Return True if an error is encountered while stopping.
        """
        if self.__runData is None:
            raise RunSetException("RunSet #%d is not running" % self.__id)

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING %s", self.__runData)
        self.__runData.stop()

        srcSet = []
        otherSet = []

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING buildSets")
        for c in self.__set:
            if c.isSource():
                srcSet.append(c)
            else:
                otherSet.append(c)

        # stop from front to back
        #
        otherSet.sort(lambda x, y: self.sortCmp(y, x))

        for i in range(0, 2):
            self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING phase %d", i)
            if i == 0:
                self.__state = RunSetState.STOPPING
                srcOp = ComponentOperation.STOP_RUN
                timeoutSecs = int(RunSet.TIMEOUT_SECS * .75)
            else:
                self.__state = RunSetState.FORCING_STOP
                srcOp = ComponentOperation.FORCED_STOP
                timeoutSecs = int(RunSet.TIMEOUT_SECS * .25)

            if i == 1:
                self.__runData.error('%s: Forcing %d components to stop: %s' %
                                    (str(self), len(waitList),
                                     self.__listComponentsCommaSep(waitList)))

            # stop sources in parallel
            #
            self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING SRC create *%d",
                            len(srcSet))
            tGroup = ComponentOperationGroup(srcOp)
            for c in srcSet:
                tGroup.start(c, self.__runData, ())
            tGroup.wait()
            tGroup.reportErrors(self.__runData, self.__state)
            self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING SRC done")

            # stop non-sources in order
            #
            for c in otherSet:
                self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING OTHER %s", c)
                tGroup = ComponentOperationGroup(srcOp)
                tGroup.start(c, self.__runData, ())
                tGroup.wait()
                tGroup.reportErrors(self.__runData, self.__state)
                self.__logDebug(RunSetDebug.STOP_RUN,
                                "STOPPING OTHER %s done", c)

            connDict = {}

            waitList = srcSet + otherSet

            msgSecs = None
            curSecs = time.time()
            endSecs = curSecs + timeoutSecs

            # number of seconds between "Waiting for ..." messages
            #
            waitMsgPeriod = 5

            while len(waitList) > 0 and curSecs < endSecs:
                self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING WAITCHK top")
                newList = waitList[:]
                tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
                for c in waitList:
                    tGroup.start(c, self.__logger, ())
                tGroup.wait()
                states = tGroup.results()
                for c in waitList:
                    if states.has_key(c):
                        stateStr = str(states[c])
                    else:
                        stateStr = self.STATE_DEAD
                    if stateStr != self.__state:
                        newList.remove(c)
                        if c in connDict:
                            del connDict[c]

                changed = False

                # if any components have changed state...
                #
                if len(waitList) != len(newList):
                    waitList = newList
                    changed = True

                # ...or if any component's engines have changed state...
                #
                for c in waitList:
                    csStr = c.getNonstoppedConnectorsString()
                    if not c in connDict:
                        connDict[c] = csStr
                    elif connDict[c] != csStr:
                        connDict[c] = csStr
                        changed = True

                if not changed:
                    #
                    # hmmm ... we may be hanging
                    #
                    time.sleep(1)
                else:
                    #
                    # one or more components must have stopped
                    #
                    if len(waitList) > 0:
                        newSecs = time.time()
                        if msgSecs is None or \
                               newSecs < (msgSecs + waitMsgPeriod):
                            waitStr = None
                            for c in waitList:
                                if waitStr is None:
                                    waitStr = ''
                                else:
                                    waitStr += ', '
                                waitStr += c.fullName() + connDict[c]

                            self.__runData.info('%s: Waiting for %s %s' %
                                                (str(self), self.__state,
                                                 waitStr))
                            msgSecs = newSecs

                curSecs = time.time()
                self.__logDebug(RunSetDebug.STOP_RUN,
                                "STOPPING WAITCHK - %d secs, %d comps",
                                endSecs - curSecs, len(waitList))

            # if the components all stopped normally, don't force-stop them
            #
            if len(waitList) == 0:
                break

        if len(waitList) > 0:
            hadError = True

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING reset")
        self.__runData.reset()
        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING reset done")

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING report")
        duration = self.__runData.reportRates(self.__set)
        if duration < 0:
            hadError = True
        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING report done")

        if hadError:
            self.__runData.error("Run terminated WITH ERROR.")
        else:
            self.__runData.error("Run terminated SUCCESSFULLY.")

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING saveCatchall")
        self.__parent.saveCatchall(self.__runData.runDirectory())

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING queueSpade")
        self.queueForSpade(duration)

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING stopLog")
        self.__stopLogging()
        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING stopLog done")

        if len(waitList) > 0:
            self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING rptZombies")
            waitStr = None
            for c in waitList:
                if waitStr is None:
                    waitStr = ''
                else:
                    waitStr += ', '
                waitStr += c.fullName() + connDict[c]

            errStr = '%s: Could not stop %s' % (str(self), waitStr)
            self.__runData.error(errStr)
            self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING rptZombies done")
            raise RunSetException(errStr)

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING chkReady")
        badList = self.__checkState(RunSetState.READY)
        if len(badList) > 0:
            self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING raiseError")
            msg = "Could not stop %s" % self.__badStateString(badList)
            self.__runData.error(msg)
            raise RunSetException(msg)

        return hadError

    def __validateSubrunDOMs(self, subrunData):
        """
        Check that all DOMs in the subrun are valid.
        Convert (string, position) pairs in argument lists to mainboard IDs
        """
        doms = []
        not_found = []
        for args in subrunData:
            # Look for (dommb, f0, ..., f4) or (name, f0, ..., f4)
            if len(args) == 6:
                domid = args[0]
                if not self.__cfg.hasDOM(domid):
                    # Look by DOM name
                    try:
                        args[0] = self.__cfg.getIDbyName(domid)
                    except DOMNotInConfigException, e:
                        not_found.append("#" + domid)
                        continue
            # Look for (str, pos, f0, ..., f4)
            elif len(args) == 7:
                try:
                    pos = int(args[1])
                    string = int(args.pop(0))
                except ValueError:
                    msg = "Bad DOM '%s-%s' in %s (need integers)!" % \
                        (string, pos, args)
                    raise InvalidSubrunData(msg)
                try:
                    args[0] = self.__cfg.getIDbyStringPos(string, pos)
                except DOMNotInConfigException, e:
                    not_found.append("Pos %s-%s" % (string, pos))
                    continue
            else:
                raise InvalidSubrunData("Bad subrun arguments %s" %
                                        str(args))
            doms.append(args)
        return (doms, not_found)

    def __waitForStateChange(self, logger, timeoutSecs=TIMEOUT_SECS):
        """
        Wait for state change, with a timeout of timeoutSecs (renewed each time
        any component changes state).  Raise a ValueError if the state change
        fails.
        """
        waitList = self.__set[:]

        endSecs = time.time() + timeoutSecs
        while len(waitList) > 0 and time.time() < endSecs:
            newList = waitList[:]
            tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
            for c in waitList:
                tGroup.start(c, self.__logger, ())
            tGroup.wait()
            states = tGroup.results()
            for c in waitList:
                if states.has_key(c):
                    stateStr = str(states[c])
                else:
                    stateStr = self.STATE_DEAD
                if stateStr != self.__state:
                    newList.remove(c)

            # if one or more components changed state...
            #
            if len(waitList) == len(newList):
                time.sleep(1)
            else:
                waitList = newList
                if len(waitList) > 0:
                    waitStr = self.__listComponentsCommaSep(waitList)
                    logger.info('%s: Waiting for %s %s' %
                                       (str(self), self.__state, waitStr))

                # reset timeout
                #
                endSecs = time.time() + timeoutSecs

        if len(waitList) > 0:
            waitStr = self.__listComponentsCommaSep(waitList)
            raise RunSetException(("Still waiting for %d components to" +
                                   " leave %s (%s)") %
                                  (len(waitList), self.__state, waitStr))

    def buildConnectionMap(self):
        "Validate and fill the map of connections for each component"
        self.__logDebug(RunSetDebug.START_RUN, "BldConnMap TOP")
        connDict = {}

        for comp in self.__set:
            for n in comp.connectors():
                if not connDict.has_key(n.name()):
                    connDict[n.name()] = ConnTypeEntry(n.name())
                connDict[n.name()].add(n, comp)

        connMap = {}

        for k in connDict:
            # XXX - this can raise ConnectionException
            connDict[k].buildConnectionMap(connMap)

        self.__logDebug(RunSetDebug.START_RUN, "BldConnMap DONE")
        return connMap

    def components(self):
        return self.__set[:]

    def configName(self):
        return self.__cfg.basename()

    def configure(self):
        "Configure all components in the runset"
        self.__logDebug(RunSetDebug.START_RUN, "RSConfig TOP")
        self.__state = RunSetState.CONFIGURING

        data = (self.configName(), )
        tGroup = ComponentOperationGroup(ComponentOperation.CONFIG_COMP)
        for c in self.__set:
            tGroup.start(c, self.__logger, data)
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "configure")

        for i in range(60):
            waitList = []
            tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
            for c in self.__set:
                tGroup.start(c, self.__logger, ())
            tGroup.wait()
            states = tGroup.results()
            for c in self.__set:
                if states.has_key(c):
                    stateStr = str(states[c])
                else:
                    stateStr = self.STATE_DEAD
                if stateStr != RunSetState.CONFIGURING and \
                        stateStr != RunSetState.READY:
                    waitList.append(c)

            if len(waitList) == 0:
                break
            self.__logger.info('%s: Waiting for %s: %s' %
                               (str(self), self.__state,
                                self.__listComponentsCommaSep(waitList)))

            time.sleep(1)

        self.__waitForStateChange(self.__logger, 60)

        badList = self.__checkState(RunSetState.READY)
        if len(badList) > 0:
            msg = "Could not configure %s" % self.__badStateString(badList)
            self.__logger.error(msg)
            raise RunSetException(msg)

        self.__configured = True
        self.__logDebug(RunSetDebug.START_RUN, "RSConfig DONE")

    def configured(self):
        return self.__configured

    def connect(self, connMap, logger):
        self.__logDebug(RunSetDebug.START_RUN, "RSConn TOP")

        self.__state = RunSetState.CONNECTING

        # connect all components
        #
        errMsg = None
        tGroup = ComponentOperationGroup(ComponentOperation.CONNECT)
        for c in self.__set:
            tGroup.start(c, self.__logger, connMap)
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "connect")

        try:
            self.__waitForStateChange(self.__logger, 20)
        except:
            # give up after 20 seconds
            pass

        badList = self.__checkState(RunSetState.CONNECTED)

        if errMsg is None and len(badList) != 0:
            errMsg = "Could not connect %s" % str(badList)

        if errMsg:
            raise RunSetException(errMsg)

        self.__logDebug(RunSetDebug.START_RUN, "RSConn DONE")

    def createComponentLog(cls, runDir, comp, host, port, liveHost, livePort,
                           quiet=True):
        if not os.path.exists(runDir):
            raise RunSetException("Run directory \"%s\" does not exist" %
                                  runDir)

        logName = os.path.join(runDir, "%s-%d.log" % (comp.name(), comp.num()))
        sock = LogSocketServer(port, comp.fullName(), logName, quiet=quiet)
        sock.startServing()

        return sock
    createComponentLog = classmethod(createComponentLog)

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir, logDir, testing=False):
        return RunData(self, runNum, clusterConfigName, self.__cfg.basename(),
                       runOptions, versionInfo, spadeDir, copyDir, logDir,
                       testing)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        if not os.path.exists(logDir):
            raise RunSetException("Log directory \"%s\" does not exist" %
                                  logDir)

        runDir = os.path.join(logDir, "daqrun%05d" % runNum)
        if not os.path.exists(runDir):
            os.makedirs(runDir)
        elif not backupExisting:
            if not os.path.isdir(runDir):
                raise RunSetException("\"%s\" is not a directory" % runDir)
        else:
            # back up existing run directory to daqrun#####.1 (or .2, etc.)
            #
            n = 1
            while True:
                bakDir = "%s.%d" % (runDir, n)
                if not os.path.exists(bakDir):
                    os.rename(runDir, bakDir)
                    break
                n += 1
            os.mkdir(runDir, 0755)

        return runDir

    def createTaskManager(self, dashlog, liveMoniClient, runDir, runOptions):
        return TaskManager(self, dashlog, liveMoniClient, runDir, runOptions)

    def cycleComponents(self, compList, configDir, dashDir, logPort, livePort,
                        verbose, killWith9, eventCheck, checkExists=True):
        dryRun = False
        killJavaComponents(compList, dryRun, verbose, killWith9)
        startJavaComponents(compList, dryRun, configDir, dashDir, logPort,
                            livePort, verbose, eventCheck,
                            checkExists=checkExists)

    def destroy(self, ignoreComponents=False):
        if not ignoreComponents and len(self.__set) > 0:
            raise RunSetException('RunSet #%d is not empty' % self.__id)

        if self.__runData is not None:
            self.__runData.destroy()

        self.__id = None
        self.__configured = False
        self.__state = RunSetState.DESTROYED
        self.__runData = None

    def events(self, subrunNumber):
        "Get the number of events in the specified subrun"
        for c in self.__set:
            if c.isBuilder():
                return c.events(subrunNumber)

        raise RunSetException('RunSet #%d does not contain an event builder' %
                              self.__id)

    def debugBits(self):
        return self.__debugBits

    def getEventCounts(self):
        "Return monitoring data for the run"
        if self.__runData is None:
            return {}

        return self.__runData.getEventCounts(self.__state, self.__set)

    def id(self):
        return self.__id

    def isDestroyed(self):
        return self.__state == RunSetState.DESTROYED

    def isReady(self):
        return self.__state == RunSetState.READY

    def isRunning(self):
        return self.__state == RunSetState.RUNNING

    def logToDash(self, msg):
        "Used when CnCServer needs to add a log message to dash.log"
        if self.__runData is not None:
            self.__runData.error(msg)
        else:
            self.__logger.error(msg)

    def queueForSpade(self, duration):
        if self.__runData is None:
            self.__logger.error("No run data; cannot queue for SPADE")
            return

        self.__runData.queueForSpade(duration)

    def reset(self):
        "Reset all components in the runset back to the idle state"
        self.__state = RunSetState.RESETTING

        tGroup = ComponentOperationGroup(ComponentOperation.RESET_COMP)
        for c in self.__set:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "reset")

        try:
            self.__waitForStateChange(self.__logger, 60)
        except:
            # give up after 60 seconds
            pass

        badList = self.__checkState(RunSetState.IDLE)

        self.__configured = False
        self.__runData = None

        return badList

    def resetLogging(self):
        "Reset logging for all components in the runset"
        tGroup = ComponentOperationGroup(ComponentOperation.RESET_LOGGING)
        for c in self.__set:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "resetLogging")

    def restartAllComponents(self, clusterConfig, configDir, dashDir, logPort,
                             livePort, verbose, killWith9, eventCheck):
        # restarted components are removed from self.__set, so we need to
        # pass in a copy of self.__set
        self.restartComponents(self.__set[:], clusterConfig, configDir,
                               dashDir, logPort, livePort, verbose, killWith9,
                               eventCheck)

    def restartComponents(self, compList, clusterConfig, configDir, dashDir,
                          logPort, livePort, verbose, killWith9, eventCheck):
        """
        Remove all components in 'compList' (and which are found in
        'clusterConfig') from the runset and restart them
        """
        cluCfgList = []
        for comp in compList:
            found = False
            for node in clusterConfig.nodes():
                for nodeComp in node.components():
                    if comp.name().lower() == nodeComp.name().lower() and \
                            comp.num() == nodeComp.id():
                        cluCfgList.append(nodeComp)
                        found = True

            if not found:
                self.__logger.error(("Cannot restart component %s: Not found" +
                                     " in cluster config \"%s\"") %
                                    (comp, clusterConfig.configName()))
            else:
                try:
                    self.__set.remove(comp)
                except ValueError:
                    self.__logger.error(("Cannot remove component %s from" +
                                         " RunSet #%d") % (comp, self.__id))
                try:
                    comp.close()
                except:
                    self.__logger.error("Close failed for %s: %s" %
                                        (comp, exc_string()))

        self.__logger.error("Cycling components %s" % cluCfgList)
        self.cycleComponents(cluCfgList, configDir, dashDir, logPort, livePort,
                             verbose, killWith9, eventCheck)

    def returnComponents(self, pool, clusterConfig, configDir, dashDir,
                         logPort, livePort, verbose, killWith9, eventCheck):
        badPairs = self.reset()

        badComps = []
        if len(badPairs) > 0:
            for pair in badPairs:
                self.__logger.error("Restarting %s (state '%s' after reset)" %
                                    (pair[0], pair[1]))
                badComps.append(pair[0])
            self.restartComponents(badComps, clusterConfig, configDir, dashDir,
                                   logPort, livePort, verbose, killWith9,
                                   eventCheck)

        # transfer components back to pool
        #
        while len(self.__set) > 0:
            comp = self.__set[0]
            del self.__set[0]
            if not comp in badComps:
                pool.add(comp)
            else:
                self.__logger.error("Not returning unexpected component %s" %
                                    comp)

        # raise exception if one or more components could not be reset
        #
        if len(badComps) > 0:
            raise RunSetException('Could not reset %s' % str(badComps))

    def runNumber(self):
        if self.__runData is None:
            return None

        return self.__runData.runNumber()

    def sendEventCounts(self):
        "Report run monitoring quantities"
        if self.__runData is not None:
            self.__runData.sendEventCounts(self.__state, self.__set)

    def setDebugBits(self, debugBit):
        if debugBit == 0:
            self.__debugBits = 0
        else:
            self.__debugBits |= debugBit

        if self.__runData is not None:
            self.__runData.setDebugBits(self.__debugBits)

    def setError(self):
        self.__logDebug(RunSetDebug.STOP_RUN, "SetError %s", self.__runData)
        try:
            if self.__state == RunSetState.RUNNING:
                self.stopRun(hadError=True)
        except:
            pass

        self.__state = RunSetState.ERROR

    def setOrder(self, connMap, logger):
        "set the order in which components are started/stopped"
        self.__logDebug(RunSetDebug.START_RUN, "RSOrder TOP")

        # build initial lists of source components
        #
        allComps = {}
        curLevel = []
        for c in self.__set:
            # complain if component has already been added
            #
            if allComps.has_key(c):
                logger.error('Found multiple instances of %s' % str(c))
                continue

            # clear order
            #
            c.setOrder(None)

            # add component to the list
            #
            allComps[c] = 1

            # if component is a source, save it to the initial list
            #
            if c.isSource():
                curLevel.append(c)

        if len(curLevel) == 0:
            raise RunSetException("No sources found")

        # walk through detector, setting order number for each component
        #
        level = 1
        while len(allComps) > 0 and len(curLevel) > 0 and \
                level < len(self.__set) + 2:
            tmp = {}
            for c in curLevel:

                # if we've already ordered this component, skip it
                #
                if not allComps.has_key(c):
                    continue

                del allComps[c]

                c.setOrder(level)

                if not connMap.has_key(c):
                    if c.isSource():
                        logger.warn('No connection map entry for %s' % str(c))
                else:
                    for m in connMap[c]:
                        # XXX hack -- ignore source->builder links
                        if not c.isSource() or not m.comp.isBuilder():
                            tmp[m.comp] = 1

            curLevel = tmp.keys()
            level += 1

        if len(allComps) > 0:
            errStr = 'Unordered:'
            for c in allComps:
                errStr += ' ' + str(c)
            logger.error(errStr)

        for c in self.__set:
            failStr = None
            if not c.order():
                if not failStr:
                    failStr = 'No order set for ' + str(c)
                else:
                    failStr += ', ' + str(c)
            if failStr:
                raise RunSetException(failStr)

        self.__logDebug(RunSetDebug.START_RUN, "RSOrder DONE")

    def size(self):
        return len(self.__set)

    def sortCmp(self, x, y):
        if y.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(y))
            return -1
        elif x.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(x))
            return 1
        else:
            return y.order()-x.order()

    def startRun(self, runNum, clusterConfigName, runOptions, versionInfo,
                 spadeDir, copyDir=None, logDir=None, quiet=True):
        "Start all components in the runset"
        self.__logger.error("Starting run #%d with \"%s\"" %
                            (runNum, clusterConfigName))
        self.__logDebug(RunSetDebug.START_RUN, "STARTING %d - %s",
                        runNum, clusterConfigName)
        if not self.__configured:
            raise RunSetException("RunSet #%d is not configured" % self.__id)
        if not self.__state == RunSetState.READY:
            raise RunSetException("Cannot start runset from state \"%s\"" %
                                  self.__state)

        self.__logDebug(RunSetDebug.START_RUN, "STARTING creRunData")
        self.__runData = self.createRunData(runNum, clusterConfigName,
                                            runOptions, versionInfo,
                                            spadeDir, copyDir, logDir)
        self.__runData.setDebugBits(self.__debugBits)
        self.__logDebug(RunSetDebug.START_RUN, "STARTING startComps")
        self.__startComponents(quiet)
        self.__logDebug(RunSetDebug.START_RUN, "STARTING finishSetup")
        self.__runData.finishSetup(self)
        self.__logDebug(RunSetDebug.START_RUN, "STARTING done")

    def state(self):
        return self.__state

    def status(self):
        """
        Return a dictionary of components in the runset
        and their current state
        """
        tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
        for c in self.__set:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        states = tGroup.results()

        setStats = {}
        for c in self.__set:
            if states.has_key(c):
                setStats[c] = str(states[c])
            else:
                setStats[c] = self.STATE_DEAD

        return setStats

    def stopRun(self, hadError=False):
        """
        Stop all components in the runset
        Return True if an error is encountered while stopping.
        """
        if self.__stopping:
            msg = "Ignored extra stopRun() call"
            if self.__runData is not None:
                self.__runData.error(msg)
            elif self.__logger is not None:
                self.__logger.error(msg)
            return False

        self.__stopping = True
        try:
            try:
                hadError = self.__stopRunInternal(hadError)
            except:
                self.__logger.error("Could not stop run: " + exc_string())
                raise
        finally:
            self.__stopping = False

        return hadError

    def subrun(self, id, data):
        "Start a subrun with all components in the runset"
        if self.__runData is None or self.__state != RunSetState.RUNNING:
            raise RunSetException("RunSet #%d is not running" % self.__id)

        if len(data) > 0:
            try:
                (newData, missingDoms) = self.__validateSubrunDOMs(data)
                if len(missingDoms) > 0:
                    self.__runData.warn(("Subrun %d: will ignore missing" +
                                         " DOMs %s") % (id, missingDoms))

                # newData has any missing DOMs deleted and any string/position
                # pairs converted to mainboard IDs
                data = newData
            except InvalidSubrunData, inv:
                raise RunSetException("Subrun %d: invalid argument list (%s)" %
                                      (id, inv))

            self.__runData.error("Subrun %d: flashing DOMs (%s)" %
                                 (id, str(data)))
        else:
            self.__runData.error("Subrun %d: Got command to stop flashers" % id)
        for c in self.__set:
            if c.isBuilder():
                c.prepareSubrun(id)

        shThreads = []
        for c in self.__set:
            if c.isSource():
                thread = SubrunThread(c, data, self.__runData)
                thread.start()
                shThreads.append(thread)

        badComps = []

        latestTime = None
        while len(shThreads) > 0:
            time.sleep(0.1)
            for thread in shThreads:
                if not thread.isAlive():
                    if not thread.finished():
                        badComps.append(thread.comp())
                    elif latestTime is None or thread.time() > latestTime:
                        latestTime = thread.time()
                    shThreads.remove(thread)

        if latestTime is None:
            raise RunSetException("Couldn't start subrun on any string hubs")

        if len(badComps) > 0:
            raise RunSetException("Couldn't start subrun on %s" %
                                  self.__listComponentsCommaSep(badComps))

        for c in self.__set:
            if c.isBuilder():
                c.commitSubrun(id, repr(latestTime))

    def updateRates(self):
        if self.__runData is not None:
            self.__runData.updateRates(self.__set)

if __name__ == "__main__": pass
