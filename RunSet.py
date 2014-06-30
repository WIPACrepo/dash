#!/usr/bin/env python

import datetime
import os
import threading
import time
import sys

import SpadeQueue

from CnCThread import CnCThread
from CompOp import ComponentOperation, ComponentOperationGroup, Result
from ComponentManager import ComponentManager, listComponentRanges
from DAQClient import DAQClientState
from DAQConfig import DOMNotInConfigException
from DAQConst import DAQPort
from DAQLog import DAQLog, FileAppender, LiveSocketAppender, LogSocketServer
from DAQRPC import RPCClient
from DAQTime import PayloadTime
from LiveImports import LIVE_IMPORT, MoniClient, MoniPort, Prio
from RunOption import RunOption
from RunSetDebug import RunSetDebug
from RunSetState import RunSetState
from RunStats import RunStats
from TaskManager import TaskManager
from UniqueID import UniqueID
from utils import ip
from utils.DashXMLLog import DashXMLLog, DashXMLLogException
from leapseconds import leapseconds

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class RunSetException(Exception):
    pass


class ConnectionException(RunSetException):
    pass


class InvalidSubrunData(RunSetException):
    pass


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
            outStr = None
            for outComp in self.__outList + self.__optOutList:
                if outStr is None:
                    outStr = ''
                else:
                    outStr += ', '
                outStr += str(outComp)
            raise ConnectionException('No inputs found for %s outputs (%s)' %
                                      (self.__type, outStr))

        # if there are no outputs, throw an error
        if outLen == 0:
            inStr = None
            for inPair in self.__inList + self.__optInList:
                if inStr is None:
                    inStr = ''
                else:
                    inStr += ', '
                inStr += str(inPair[1])
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


class GoodTimeThread(CnCThread):
    """
    A thread which queries all hubs for either the latest first hit time
    or the earliest last hit time
    """

    # bean field name holding the number of non-zombie hubs
    NONZOMBIE_FIELD = "NumberOfNonZombies"
    # maximum number of attempts to get the time from all hubs
    MAX_ATTEMPTS = 20

    def __init__(self, srcSet, otherSet, data, log, quickSet=False,
                 threadName=None):
        """
        Create the thread

        srcSet - list of sources (stringHubs) in the runset
        otherSet - list of non-sources in the runset
        data - RunData for the run
        log - log file for the runset
        quickSet - True if time should be passed on as quickly as possible
        threadName - thread name
        """
        self.__srcSet = srcSet
        self.__otherSet = otherSet
        self.__data = data
        self.__log = log
        self.__quickSet = quickSet

        self.__timeDict = {}
        self.__badComps = {}

        self.__goodTime = None
        self.__finalTime = None

        self.__stopped = False

        super(GoodTimeThread, self).__init__(threadName, log)

    def _run(self):
        "Gather good hit time data from all hubs"
        try:
            complete = False
            for i in range(self.MAX_ATTEMPTS):
                complete = self.__fetchTime()
                if complete or self.__stopped:
                    # we're done, break out of the loop
                    break
                time.sleep(0.1)
        except:
            self.__log.error("Couldn't find %s: %s" %
                             (self.moniname(), exc_string()))

        self.__finalTime = self.__goodTime

        if len(self.__badComps) > 0:
            self.__log.error("Couldn't find %s for %s" %
                             (self.moniname(),
                              listComponentRanges(self.__badComps.keys())))

        if self.__goodTime is None:
            goodVal = "unknown"
        else:
            goodVal = self.__goodTime
        self.__data.reportGoodTime(self.moniname(), goodVal)

    def __fetchTime(self):
        """
        Query all hubs which haven't yet reported a time
        """
        tGroup = ComponentOperationGroup(ComponentOperation.GET_GOOD_TIME)
        for c in self.__srcSet:
            if not c in self.__timeDict:
                tGroup.start(c, self.__log,
                             (self.NONZOMBIE_FIELD, self.beanfield()))

        if self.waitForAll():
            # if we don't need results as soon as possible,
            # wait for all threads to finish
            tGroup.wait()
            tGroup.reportErrors(self.__log, "getGoodTimes")

        complete = True
        updated = False

        # wait for up to half a second for a result
        sleepSecs = 0.1
        sleepReps = 5

        for i in xrange(sleepReps):
            hanging = False
            complete = True

            rList = tGroup.results()
            for c in self.__srcSet:
                if self.__stopped:
                    # run has been stopped, don't bother checking anymore
                    break

                if c in self.__timeDict:
                    # already have a time for this hub
                    continue

                result = rList[c]
                if result is None or \
                    result == ComponentOperation.RESULT_HANGING:
                    # still waiting for results
                    complete = False
                    hanging = True
                    continue

                if result == ComponentOperation.RESULT_ERROR:
                    # component operation failed
                    self.__badComps[c] = 1
                    continue

                if self.__badComps.has_key(c):
                    # got a result from a component which previously failed
                    del self.__badComps[c]

                numDoms = result[self.NONZOMBIE_FIELD]
                if numDoms == 0:
                    # this string has no usable DOMs, record illegal time
                    self.__log.error("No usable DOMs on %s for %s" %
                                     (c.fullName(), self.moniname()))
                    self.__timeDict[c] = -1L
                    continue

                if not result.has_key(self.beanfield()):
                    val = None
                else:
                    val = result[self.beanfield()]
                if val is None or val <= 0L:
                    # No results yet, need to poll again
                    complete = False
                    continue

                self.__timeDict[c] = val
                if self.__goodTime is None or \
                    self.isBetter(self.__goodTime, val):
                    # got new good time, tell the builders
                    self.__goodTime = val
                    updated = True

            if complete:
                # quit if we've got all the results
                break

            if not hanging and not self.waitForAll():
                # quit if all threads are done or if we don't need to wait
                break

            # wait a bit more for the threads to finish
            time.sleep(sleepSecs)

        if updated:
            try:
                self.__notifyComponents(self.__goodTime)
            except:
                self.__log.error("Cannot send %s to builders: %s" %
                                 (self.moniname(), exc_string()))

        return complete

    def __notifyComponents(self, goodTime):
        "Send latest good time to the builders"
        for c in self.__otherSet:
            if c.isBuilder() or c.isComponent("globalTrigger"):
                self.notifyComponent(c, goodTime)

    def beanfield(self):
        "Return the name of the 'stringhub' MBean field"
        raise NotImplementedError("Unimplemented")

    def logError(self, msg):
        self.__log.error(msg)

    def finished(self):
        "Return True if the thread has finished"
        return self.__finalTime is not None

    def isBetter(self, oldval, newval):
        "Return True if 'newval' is better than 'oldval'"
        raise NotImplementedError("Unimplemented")

    def moniname(self):
        "Return the name of the value sent to I3Live"
        raise NotImplementedError("Unimplemented")

    def notifyComponent(self, comp, goodTime):
        "Notify the builder of the good time"
        raise NotImplementedError("Unimplemented")

    def stop(self):
        self.__stopped = True

    def time(self):
        "Return the time marking the start or end of good data taking"
        return self.__finalTime

    def waitForAll(self):
        "Wait for all threads to finish before checking results?"
        raise NotImplementedError("Unimplemented")


class FirstGoodTimeThread(GoodTimeThread):
    def __init__(self, srcSet, otherSet, data, log):
        """
        Create the thread

        srcSet - list of sources (stringHubs) in the runset
        otherSet - list of non-sources in the runset
        data - RunData for the run
        log - log file for the runset
        """
        super(FirstGoodTimeThread, self).__init__(srcSet, otherSet, data, log,
                                                  threadName="FirstGoodTime")

    def beanfield(self):
        "Return the name of the 'stringhub' MBean field"
        return "LatestFirstChannelHitTime"

    def isBetter(self, oldval, newval):
        "Return True if 'newval' is better than 'oldval'"
        return oldval is None or (newval is not None and oldval < newval)

    def moniname(self):
        "Return the name of the value sent to I3Live"
        return "firstGoodTime"

    def notifyComponent(self, comp, payTime):
        "Notify the builder of the good time"
        if payTime is None:
            self.logError("Cannot set first good time to None")
        else:
            comp.setFirstGoodTime(payTime)

    def waitForAll(self):
        "Wait for all threads to finish before checking results?"
        return True


class LastGoodTimeThread(GoodTimeThread):
    def __init__(self, srcSet, otherSet, data, log):
        """
        Create the thread

        srcSet - list of sources (stringHubs) in the runset
        otherSet - list of non-sources in the runset
        data - RunData for the run
        log - log file for the runset
        """
        super(LastGoodTimeThread, self).__init__(srcSet, otherSet, data, log,
                                                 threadName="LastGoodTime",
                                                 quickSet=True)

    def beanfield(self):
        "Return the name of the 'stringhub' MBean field"
        return "EarliestLastChannelHitTime"

    def isBetter(self, oldval, newval):
        "Return True if 'newval' is better than 'oldval'"
        return oldval is None or (newval is not None and oldval > newval)

    def moniname(self):
        "Return the name of the value sent to I3Live"
        return "lastGoodTime"

    def notifyComponent(self, comp, payTime):
        "Notify the builder of the good time"
        if payTime is None:
            self.logError("Cannot set last good time to None")
        else:
            comp.setLastGoodTime(payTime)

    def waitForAll(self):
        "Wait for all threads to finish before checking results?"
        return False


class RunData(object):
    def __init__(self, runSet, runNumber, clusterConfig, runConfig,
                 runOptions, versionInfo, spadeDir, copyDir, logDir, testing):
        """
        RunData constructor
        runSet - run set which uses this data
        runNum - current run number
        clusterConfig - current cluster configuration
        runConfig - current run configuration
        runOptions - logging/monitoring options
        versionInfo - release and revision info
        spadeDir - directory where SPADE files are written
        copyDir - directory where a copy of the SPADE files is kept
        logDir - top-level logging directory
        testing - True if this is called from a unit test
        """
        self.__runNumber = runNumber
        self.__subrunNumber = 0
        self.__clusterConfig = clusterConfig
        self.__runConfig = runConfig
        self.__runOptions = runOptions
        self.__versionInfo = versionInfo
        self.__spadeDir = spadeDir
        self.__copyDir = copyDir
        self.__testing = testing

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

        if self.__spadeDir is not None and not os.path.exists(self.__spadeDir):
            raise RunSetException("SPADE directory %s does not exist" %
                                  self.__spadeDir)

        if not testing:
            self.__dashlog = self.__createDashLog()
        else:
            self.__dashlog = runSet.createDashLog()

        self.__dashlog.error(("Version info: %(filename)s %(revision)s" +
                              " %(date)s %(time)s %(author)s %(release)s" +
                              " %(repo_rev)s") % versionInfo)
        self.__dashlog.error("Run configuration: %s" % runConfig.basename())
        self.__dashlog.error("Cluster: %s" % clusterConfig.descName())

        self.__taskMgr = None
        self.__liveMoniClient = None

        self.__runStats = RunStats()
        self.__sendCount = 0

        self.__firstPayTime = -1

        self.__spadeThread = None

    def __str__(self):
        return "Run#%d %s" % (self.__runNumber, self.__runStats)

    def __calculateDuration(self, firstTime, lastTime, hadError):
        if firstTime is None:
            errMsg = "Starting time is not set"
        elif lastTime is None:
            errMsg = "Ending time is not set"
        elif lastTime < firstTime:
            errMsg = "Ending time %s is before starting time %s" % \
                (lastTime, firstTime)
        else:
            errMsg = None

        if errMsg is not None:
            self.__dashlog.error(errMsg)
            return -1

        return (lastTime - firstTime) / 10000000000

    def __createDashLog(self):
        log = DAQLog(level=DAQLog.ERROR)

        if RunOption.isLogToFile(self.__runOptions):
            if self.__runDir is None:
                raise RunSetException("Run directory has not been specified")
            app = FileAppender("dashlog", os.path.join(self.__runDir,
                                                       "dash.log"))
            log.addAppender(app)

        if RunOption.isLogToLive(self.__runOptions):
            app = LiveSocketAppender("localhost", DAQPort.I3LIVE_ZMQ,
                                     priority=Prio.EMAIL)
            log.addAppender(app)

        return log

    def __createLiveMoniClient(self):
        if LIVE_IMPORT:
            moniClient = MoniClient("pdaq", "localhost", MoniPort)
        else:
            moniClient = None
            if not RunSet.LIVE_WARNING:
                RunSet.LIVE_WARNING = True
                self.__dashlog.error("Cannot import IceCube Live code, so" +
                                    " per-string active DOM stats wil not" +
                                    " be reported")

        return moniClient

    def __getRateData(self, comps):
        nEvts = 0
        wallTime = -1
        lastPayTime = -1
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
                    wallTime = datetime.datetime.utcnow()
                    lastPayTime = long(evtData[1])

                if nEvts > 0 and self.__firstPayTime <= 0:
                    val = self.getSingleBeanField(c, "backEnd",
                                                  "FirstEventTime")
                    if type(val) == Result:
                        msg = "Cannot get first event time (%s)" % val
                        self.__dashlog.error(msg)
                    else:
                        self.__firstPayTime = val
                        self.__reportEventStart()

            if c.isComponent("secondaryBuilders"):
                for bldr in ("moni", "sn", "tcal"):
                    val = self.getSingleBeanField(c, bldr + "Builder",
                                                  "TotalDispatchedData")
                    if type(val) == Result:
                        msg = "Cannot get %sBuilder dispatched data (%s)" % \
                            (bldr, val)
                        self.__dashlog.error(msg)
                        num = 0
                        time = None
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

        return (nEvts, wallTime, self.__firstPayTime, lastPayTime, nMoni,
                moniTime, nSN, snTime, nTCal, tcalTime)

    def __reportEventStart(self):
        if self.__liveMoniClient is not None:
            try:
                fulltime = PayloadTime.toDateTime(self.__firstPayTime,
                                                  high_precision=True)
            except TypeError, err:
                msg = "Cannot report first time %s<%s>, prevTime is %s<%s>" % \
                            (self.__firstPayTime, type(self.__firstPayTime),
                             PayloadTime.PREV_TIME, type(PayloadTime.PREV_TIME))
                self.__dashlog.error(msg)
                return

            data = {"runnum": self.__runNumber,
                    "time" : str(fulltime)}

            try:
                monitime = PayloadTime.toDateTime(self.__firstPayTime)
            except TypeError, err:
                msg = "Cannot set moni time %s<%s>, prevTime is %s<%s>" % \
                            (self.__firstPayTime, type(self.__firstPayTime),
                             PayloadTime.PREV_TIME, type(PayloadTime.PREV_TIME))
                self.__dashlog.error(msg)
                return

            self.__sendMoni("eventstart", data, prio=Prio.SCP, time=monitime)

    def __reportRunStop(self, numEvts, firstPayTime, lastPayTime, hadError):
        if self.__liveMoniClient is not None:
            firstDT = PayloadTime.toDateTime(firstPayTime, high_precision=True)
            lastDT = PayloadTime.toDateTime(lastPayTime, high_precision=True)

            if hadError is None:
                status = "UNKNOWN"
            elif hadError:
                status = "FAIL"
            else:
                status = "SUCCESS"

            data = {"runnum": self.__runNumber,
                    "runstart": str(firstDT),
                    "runstop": str(lastDT),
                    "events": numEvts,
                    "status": status}

            monitime = PayloadTime.toDateTime(lastPayTime)
            self.__sendMoni("runstop", data, prio=Prio.SCP, time=monitime)

    def __sendMoni(self, name, value, prio=None, time=None):
        try:
            self.__liveMoniClient.sendMoni(name, value, prio=prio, time=time)
        except:
            self.__dashlog.error("Failed to send %s=%s: %s" %
                                 (name, value, exc_string()))

    def __sendOldCounts(self, moniData):
        """
        send unamalgamated messages until I3Live converts to new format
        """
        if moniData["eventPayloadTicks"] is not None:
            payTime = moniData["eventPayloadTicks"]
            monitime = PayloadTime.toDateTime(payTime)
            self.__sendMoni("physicsEvents", moniData["physicsEvents"],
                            prio=Prio.ITS, time=monitime)
        if moniData["wallTime"] is not None:
            self.__sendMoni("walltimeEvents", moniData["physicsEvents"],
                            prio=Prio.EMAIL, time=moniData["wallTime"])
        if moniData["moniTime"] is not None:
            self.__sendMoni("moniEvents", moniData["moniEvents"],
                            prio=Prio.EMAIL, time=moniData["moniTime"])
        if moniData["snTime"] is not None:
            self.__sendMoni("snEvents", moniData["snEvents"],
                            prio=Prio.EMAIL, time=moniData["snTime"])
        if moniData["tcalTime"] is not None:
            self.__sendMoni("tcalEvents", moniData["tcalEvents"],
                            prio=Prio.EMAIL, time=moniData["tcalTime"])

    def __writeRunXML(self, numEvts, numMoni, numSN, numTcal, firstTime,
                      lastTime, firstGood, lastGood, duration, hadError):

        xmlLog = DashXMLLog(dir_name=self.__runDir)
        path = xmlLog.getPath()
        if os.path.exists(path):
            self.__dashlog.error("Run xml log file \"%s\" already exists!" %
                                 path)
            return

        xmlLog.setVersionInfo(self.__versionInfo["release"],
                              self.__versionInfo["repo_rev"])
        xmlLog.setRun(self.__runNumber)
        xmlLog.setConfig(self.__runConfig.basename())
        xmlLog.setCluster(self.__clusterConfig.descName())
        xmlLog.setStartTime(PayloadTime.toDateTime(firstTime))
        xmlLog.setEndTime(PayloadTime.toDateTime(lastTime))
        xmlLog.setFirstGoodTime(PayloadTime.toDateTime(firstGood))
        xmlLog.setLastGoodTime(PayloadTime.toDateTime(lastGood))
        xmlLog.setEvents(numEvts)
        xmlLog.setMoni(numMoni)
        xmlLog.setSN(numSN)
        xmlLog.setTcal(numTcal)
        xmlLog.setTermCond(hadError)

        # write the xml log file to disk
        try:
            xmlLog.writeLog()
        except DashXMLLogException:
            self.__dashlog.error("Could not write run xml log file \"%s\"" %
                                 xmlLog.getPath())

    def clone(self, runSet, newRun):
        return RunData(runSet, newRun, self.__clusterConfig,
                       self.__runConfig, self.__runOptions, self.__versionInfo,
                       self.__spadeDir, self.__copyDir, self.__logDir,
                       self.__testing)

    def connectToI3Live(self):
        self.__liveMoniClient = self.__createLiveMoniClient()

    def destroy(self):
        savedEx = None
        try:
            self.stop()
        except:
            savedEx = sys.exc_info()

        if self.__liveMoniClient:
            try:
                self.__liveMoniClient.close()
            except:
                if not savedEx:
                    savedEx = sys.exc_info()
            self.__liveMoniClient = None

        if self.__dashlog:
            try:
                self.__dashlog.close()
            except:
                if not savedEx:
                    savedEx = sys.exc_info()
            self.__dashlog = None

        if savedEx:
            raise savedEx[0], savedEx[1], savedEx[2]

    def error(self, msg):
        self.__dashlog.error(msg)

    def finalReport(self, comps, hadError, switching=False):
        (numEvts, firstTime, lastTime, firstGood, lastGood, numMoni, numSN,
         numTcal) = self.getRunData(comps)

        # set end-of-run statistics
        time = datetime.datetime.utcnow()
        (numEvts, numMoni, numSN, numTcal, startPayTime, lastTime) = \
            self.__runStats.updateEventCounts((numEvts, time, firstTime,
                                               lastTime, numMoni, time,
                                               numSN, time, numTcal, time))
        if startPayTime is not None:
            # starting payload time is more accurate, use it if available
            firstTime = startPayTime

        if numEvts is None or numEvts <= 0:
            if numEvts is None:
                self.__dashlog.error("Reset numEvts and duration")
                numEvts = 0
            else:
                self.__dashlog.error("Reset duration")
            duration = 0
        else:
            duration = self.__calculateDuration(firstTime, lastTime, hadError)
            if duration is None or duration < 0:
                hadError = True
                duration = 0
                self.__dashlog.error("Cannot calculate duration")

        self.__writeRunXML(numEvts, numMoni, numSN, numTcal, firstTime,
                           lastTime, firstGood, lastGood, duration, hadError)

        self.__reportRunStop(numEvts, firstTime, lastTime, hadError)

        if switching:
            self.reportGoodTime("lastGoodTime", lastTime)

        # report rates
        if duration == 0:
            rateStr = ""
        else:
            rateStr = " (%2.2f Hz)" % (float(numEvts) / float(duration))
        self.__dashlog.error("%d physics events collected in %d seconds%s" %
                             (numEvts, duration, rateStr))

        if numMoni is None and numSN is None and numTcal is None:
            self.__dashlog.error("!! secondary stream data is not available !!")
        else:
            if numMoni is None:
                numMoni = 0
            if numSN is None:
                numSN = 0
            if numTcal is None:
                numTcal = 0
            self.__dashlog.error("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcal))

        # report run status
        if not switching:
            endType = "terminated"
        else:
            endType = "switched"
        if hadError:
            errType = "WITH ERROR"
        else:
            errType = "SUCCESSFULLY"
        self.__dashlog.error("Run %s %s." % (endType, errType))

        return duration

    def finishSetup(self, runSet, startTime):
        """Called after starting a run regardless of
        a switchrun or a normal run start

        tells I3Live that we're starting a run
        """

        self.leapsecondsChecks()

        if self.__liveMoniClient is not None:
            self.reportRunStartClass(self.__liveMoniClient, self.__runNumber,
                                     self.__versionInfo["release"],
                                     self.__versionInfo["repo_rev"], True,
                                     time=startTime)

        self.__taskMgr = runSet.createTaskManager(self.__dashlog,
                                                  self.__liveMoniClient,
                                                  self.__runDir,
                                                  self.__runConfig,
                                                  self.__runOptions)
        self.__taskMgr.start()

    def firstPayTime(self):
        return self.__firstPayTime

    def getEventCounts(self, comps, updateCounts=True):
        "Return monitoring data for the run"
        monDict = {}

        if updateCounts:
            self.__runStats.updateEventCounts(self.__getRateData(comps), True)
        (numEvts, wallTime, payTime, numMoni, moniTime, numSN, snTime,
         numTcal, tcalTime) = self.__runStats.monitorData()

        monDict["physicsEvents"] = numEvts
        if wallTime is None or numEvts == 0:
            monDict["wallTime"] = None
            monDict["eventPayloadTicks"] = None
        else:
            monDict["wallTime"] = str(wallTime)
            monDict["eventPayloadTicks"] = payTime
        monDict["moniEvents"] = numMoni
        if moniTime is None:
            monDict["moniTime"] = None
        else:
            monDict["moniTime"] = str(moniTime)
        monDict["snEvents"] = numSN
        if snTime is None:
            monDict["snTime"] = None
        else:
            monDict["snTime"] = str(snTime)
        monDict["tcalEvents"] = numTcal
        if tcalTime is None:
            monDict["tcalTime"] = None
        else:
            monDict["tcalTime"] = str(tcalTime)

        return monDict

    def getMultiBeanFields(self, comp, bean, fldList):
        tGroup = ComponentOperationGroup(ComponentOperation.GET_MULTI_BEAN)
        tGroup.start(comp, self.__dashlog, (bean, fldList))
        tGroup.wait(10)

        r = tGroup.results()
        if not r.has_key(comp):
            result = ComponentOperation.RESULT_ERROR
        else:
            result = r[comp]

        return result

    def getRunData(self, comps):
        nEvts = 0
        firstTime = 0
        lastTime = 0
        firstGood = 0
        lastGood = 0
        nMoni = 0
        nSN = 0
        nTCal = 0

        bldrs = []

        tGroup = ComponentOperationGroup(ComponentOperation.GET_RUN_DATA)
        for c in comps:
            if c.isComponent("eventBuilder") or \
                c.isComponent("secondaryBuilders"):
                tGroup.start(c, self.__dashlog, (self.__runNumber, ))
                bldrs.append(c)
        tGroup.wait()
        tGroup.reportErrors(self.__dashlog, "getRunData")

        r = tGroup.results()
        for c in bldrs:
            result = r[c]
            if result == ComponentOperation.RESULT_HANGING or \
                result == ComponentOperation.RESULT_ERROR or \
                result is None:
                self.__dashlog.error("Cannot get run data for %s: %s" %
                                     (c.fullName(), result))
            elif type(result) is not list and type(result) is not tuple:
                self.__dashlog.error("Bogus run data for %s: %s" %
                                     (c.fullName(), result))
            elif c.isComponent("eventBuilder"):
                expNum = 5
                if len(result) == expNum:
                    (nEvts, firstTime, lastTime, firstGood, lastGood) = result
                else:
                    self.__dashlog.error(("Expected %d run data values from" +
                                          " %s, got %d (%s)") %
                                         (expNum, c.fullName(), len(result),
                                          str(result)))
            elif c.isComponent("secondaryBuilders"):
                expNum = 3
                if len(result) == expNum:
                    (nTCal, nSN, nMoni) = result
                else:
                    self.__dashlog.error(("Expected %d run data values from" +
                                          " %s, got %d (%s)") %
                                         (expNum, c.fullName(), len(result),
                                          str(result)))

        return (nEvts, firstTime, lastTime, firstGood, lastGood, nMoni, nSN,
                nTCal)

    def getSingleBeanField(self, comp, bean, fldName):
        tGroup = ComponentOperationGroup(ComponentOperation.GET_SINGLE_BEAN)
        tGroup.start(comp, self.__dashlog, (bean, fldName))
        tGroup.wait(3, reps=10)

        r = tGroup.results()
        if not r.has_key(comp):
            result = ComponentOperation.RESULT_ERROR
        else:
            result = r[comp]

        return result

    def info(self, msg):
        self.__dashlog.info(msg)

    def isErrorEnabled(self):
        return self.__dashlog.isErrorEnabled()

    def isInfoEnabled(self):
        return self.__dashlog.isInfoEnabled()

    def isWarnEnabled(self):
        return self.__dashlog.isWarnEnabled()

    def leapsecondsChecks(self):
        ls = leapseconds.getInstance()

        ls.reload_check(self.__liveMoniClient, self.__dashlog)

        # sends an alert off to live if the nist leapsecond
        # file is about to expire
        # will send a message to stderr if the liveMoniClient
        # is None
        ls.expiry_check(self.__liveMoniClient)

    def queueForSpade(self, duration):
        if self.__logDir is None:
            self.__dashlog.error(("Not logging to file "
                                  "so cannot queue to SPADE"))
            return

        if self.__spadeDir is not None:
            if self.__spadeThread is not None:
                if self.__spadeThread.is_alive():
                    try:
                        self.__spadeThread.join(0.001)
                    except:
                        pass
                if self.__spadeThread.is_alive():
                    self.__dashlog.error("Previous SpadeQueue thread is" +
                                         " still running!!!")

            thrd = threading.Thread(target=SpadeQueue.queueForSpade,
                                    args=(self.__dashlog, self.__spadeDir,
                                          self.__copyDir, self.__logDir,
                                          self.__runNumber))
            thrd.start()

            self.__spadeThread = thrd

    def reportGoodTime(self, name, payTime):
        if self.__liveMoniClient is None:
            #self.__dashlog.error("Not reporting %s; no moni client" % name)
            pass
        else:
            try:
                fulltime = PayloadTime.toDateTime(payTime, high_precision=True)
            except:
                fulltime = None
                self.__dashlog.error("Cannot report %s: Bad value '%s'" %
                                     (name, payTime))
            if fulltime is not None:
                data = {"runnum": self.__runNumber,
                        "subrun": self.__subrunNumber,
                        "time": str(fulltime)}

                monitime = PayloadTime.toDateTime(payTime)
                self.__sendMoni(name, data, prio=Prio.SCP, time=monitime)

    @classmethod
    def reportRunStartClass(self, moniClient, runNum, release, revision,
                            started, time=datetime.datetime.now()):
        """
        This is a class method because failed runsets must be reported to
        I3Live, but only successful runsets initialize RunData
        moniClient - connection to I3Live
        runNum - run number for started run
        release - pDAQ software release name
        revision - pDAQ software SVN revision
        started - False if the run failed to start due to error
        time - date/time run was started
        """
        data = {"runnum": runNum,
                "release": release,
                "revision": revision,
                "started": started}
        moniClient.sendMoni("runstart", data, prio=Prio.SCP, time=time)

    def reset(self):
        if self.__taskMgr is not None:
            self.__taskMgr.reset()

    def runDirectory(self):
        return self.__runDir

    def runNumber(self):
        return self.__runNumber

    def sendEventCounts(self, comps, updateCounts=True):
        "Report run monitoring quantities"
        if self.__liveMoniClient is not None:
            moniData = self.getEventCounts(comps, updateCounts)

            # send every 5th set of data over ITS
            if self.__sendCount % 5 == 0:
                prio = Prio.ITS
            else:
                prio = Prio.EMAIL
            self.__sendCount += 1

            value = {
                "run": self.__runNumber,
                "subrun": self.__subrunNumber,
                "version": 0,
            }

            # if we don't have a DAQ time, use system time but complain
            if moniData["eventPayloadTicks"] is not None:
                time = PayloadTime.toDateTime(moniData["eventPayloadTicks"])
            else:
                time = datetime.datetime.utcnow()
                self.__dashlog.error("Using system time for initial event" +
                                     " counts (no event times available)")

            # fill in counts and times
            value["physicsEvents"] = moniData["physicsEvents"]
            if moniData["wallTime"] is not None:
                value["wallTime"] = moniData["wallTime"]
            for src in ("moni", "sn", "tcal"):
                eventKey = src + "Events"
                timeKey = src + "Time"
                if moniData[timeKey] is not None and moniData[timeKey] >= 0:
                    value[eventKey] = moniData[eventKey]
                    value[timeKey] = moniData[timeKey]

            self.__sendMoni("run_update", value, prio=prio, time=time)

            # send old data until I3Live handles the 'run_update' data
            self.__sendOldCounts(moniData)

    def setDebugBits(self, debugBits):
        if self.__taskMgr is not None:
            self.__taskMgr.setDebugBits(debugBits)

    def setSubrunNumber(self, num):
        self.__subrunNumber = num

    def stop(self):
        if self.__taskMgr is not None:
            self.__taskMgr.stop()

    def subrunNumber(self):
        return self.__subrunNumber

    def updateRates(self, comps):
        rateData = self.__getRateData(comps)
        self.__runStats.updateEventCounts(rateData, True)

        rate = self.__runStats.rate()

        (wallTime, numEvts, numMoni, numSN, numTcal) = \
                  self.__runStats.currentData()

        return (numEvts, rate, numMoni, numSN, numTcal)

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

    STATE_DEAD = DAQClientState.DEAD
    STATE_HANGING = DAQClientState.HANGING

    # number of seconds between "Waiting for ..." messages during stopRun()
    #
    WAIT_MSG_PERIOD = 5

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

        # make sure components are in a known order
        self.__set.sort()

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

    def __attemptToStop(self, srcSet, otherSet, newState, srcOp, timeoutSecs):
        self.__state = newState

        if self.__runData.isErrorEnabled() and \
               srcOp == ComponentOperation.FORCED_STOP:
            fullSet = srcSet + otherSet
            plural = len(fullSet) == 1 and "s" or ""
            if len(fullSet) == 1:
                plural = ""
            else:
                plural = "s"
            self.__runData.error('%s: Forcing %d component%s to stop: %s' %
                                 (str(self), len(fullSet), plural,
                                  listComponentRanges(fullSet)))

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

        msgSecs = None
        curSecs = time.time()
        endSecs = curSecs + timeoutSecs

        while (len(srcSet) > 0 or len(otherSet) > 0) and curSecs < endSecs:
            msgSecs = self.__stopComponents(srcSet, otherSet, connDict,
                                            msgSecs)
            curSecs = time.time()
            self.__logDebug(RunSetDebug.STOP_RUN,
                            "STOPPING WAITCHK - %d secs, %d comps",
                            endSecs - curSecs, len(srcSet) + len(otherSet))

    def __badStateString(self, badStates):
        badList = []
        for state in badStates:
            compStr = listComponentRanges(badStates[state])
            badList.append(state + "[" + compStr + "]")
        return ", ".join(badList)

    def __buildStartSets(self):
        """
        Return two lists of components.  The first list contains all the
        sources.  The second contains the other components, sorted in
        reverse order, from builders backward.
        """
        srcSet = []
        otherSet = []

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
        otherSet.sort(self.__sortCmp)

        return srcSet, otherSet

    def __checkState(self, newState, components=None):
        """
        If component states match 'newState', set state to 'newState' and
        return an empty list.
        Otherwise, set state to ERROR and return a dictionary of states
        and corresponding lists of components.
        """

        if components is None:
            components = self.__set

        tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
        for c in components:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        states = tGroup.results()

        stateDict = {}
        for c in components:
            if states.has_key(c):
                stateStr = str(states[c])
            else:
                stateStr = self.STATE_DEAD
            if stateStr != newState:
                if not stateStr in stateDict:
                    stateDict[stateStr] = []
                stateDict[stateStr].append(c)

        if len(stateDict) == 0:
            self.__state = newState
        else:
            msg = "Failed to transition to %s:" % newState
            for stateStr in stateDict:
                compStr = listComponentRanges(stateDict[stateStr])
                msg += " %s[%s]" % (stateStr, compStr)

            if self.__runData is not None:
                self.__runData.error(msg)
            else:
                self.__logger.error(msg)

            self.__state = RunSetState.ERROR

        return stateDict

    def __checkStoppedComponents(self, waitList):
        if len(waitList) > 0:
            try:
                waitStr = listComponentRanges(waitList)
                errStr = '%s: Could not stop %s' % (self, waitStr)
                self.__runData.error(errStr)
            except:
                errStr = "%s: Could not stop components (?)" % str(self)
            self.__state = RunSetState.ERROR
            raise RunSetException(errStr)

        badStates = self.__checkState(RunSetState.READY)
        if len(badStates) > 0:
            try:
                msg = "%s: Could not stop %s" % \
                    (self, self.__badStateString(badStates))
                self.__runData.error(msg)
            except Exception as ex:
                msg = "%s: Components in bad states: %s" % (self, ex)
            self.__state = RunSetState.ERROR
            raise RunSetException(msg)

    def __finishRun(self, comps, runData, hadError, switching=False):
        duration = runData.finalReport(comps, hadError, switching=switching)

        self.__parent.saveCatchall(runData.runDirectory())

        return duration

    def __getReplayHubs(self):
        "Return the list of replay hubs in this runset"
        replayHubs = []
        for c in self.__set:
            if c.isReplayHub():
                replayHubs.append(c)
        return replayHubs

    @classmethod
    def __getRunDirectoryPath(cls, logDir, runNum):
        return os.path.join(logDir, "daqrun%05d" % runNum)

    def __internalInitReplay(self, replayHubs):
        tGroup = ComponentOperationGroup(ComponentOperation.GET_REPLAY_TIME)
        for c in replayHubs:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "getReplayTime")

        # find earliest first hit
        firsttime = None
        r = tGroup.results()
        for c in replayHubs:
            result = r[c]
            if result == ComponentOperation.RESULT_HANGING or \
                result == ComponentOperation.RESULT_ERROR:
                self.__logger.error("Cannot get first replay time for %s: %s" %
                                     (c.fullName(), result))
                continue
            elif result < 0:
                self.__logger.error("Got bad replay time for %s: %s" %
                                     (c.fullName(), result))
                continue
            elif firsttime is None or result < firsttime:
                firsttime = result

        if firsttime is None:
            raise RunSetException("Couldn't find first replay time")

        # calculate offset
        yrsecs = 60 * 60 * 24 * 365
        walltime = long((time.time() % yrsecs) * 10000000000.0)
        offset = walltime - firsttime

        # set offset on all replay hubs
        tGroup = ComponentOperationGroup(ComponentOperation.SET_REPLAY_OFFSET)
        for c in replayHubs:
            tGroup.start(c, self.__logger, (offset, ))
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "setReplayOffset")

    @staticmethod
    def __listComponentsAndConnections(compList, connDict=None):
        compStr = None
        for c in compList:
            if compStr is None:
                compStr = ''
            else:
                compStr += ', '
            if connDict is None or not connDict.has_key(c):
                compStr += c.fullName()
            else:
                compStr += c.fullName() + connDict[c]
        return compStr

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

    def __reportFirstGoodTime(self, runData):
        ebComp = None
        for c in self.__set:
            if c.isComponent("eventBuilder"):
                ebComp = c
                break

        if ebComp is None:
            runData.error("Cannot find eventBuilder in %s" % str(self))
            return

        firstTime = None
        for i in xrange(5):
            val = runData.getSingleBeanField(ebComp, "backEnd",
                                             "FirstEventTime")
            if type(val) != Result:
                firstTime = val
                break
            time.sleep(0.1)
        if firstTime is None:
            runData.error("Couldn't find first good time" +
                             " for switched run %d" % runData.runNumber())
        else:
            runData.reportGoodTime("firstGoodTime", firstTime)

    def __sortCmp(self, x, y):
        if y.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(y))
            return -1
        elif x.order() is None:
            self.__logger.error('Comp %s cmdOrder is None' % str(x))
            return 1
        else:
            return y.order() - x.order()

    def __startComponents(self, quiet):
        liveHost = None
        livePort = None

        tGroup = ComponentOperationGroup(ComponentOperation.CONFIG_LOGGING)

        host = ip.getLocalIpAddr()

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP initLogs")
        port = DAQPort.RUNCOMP_BASE
        for c in self.__set:
            if c in self.__compLog:
                try:
                    self.__compLog[c].stopServing()
                    self.__logger.error("Closed previous log for %s" % c)
                except:
                    self.__logger.error(("Could not close previous log" +
                                         " for %s: %s") % (c, exc_string()))
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

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP bldSet")
        srcSet, otherSet = self.__buildStartSets()

        self.__state = RunSetState.STARTING

        # start non-sources
        #
        self.__startSet("NonHubs", otherSet)

        # start sources
        #
        self.__startSet("Hubs", srcSet)

        # start thread to find latest first time from hubs
        #
        goodThread = FirstGoodTimeThread(srcSet[:], otherSet[:],
                                         self.__runData, self.__runData)
        goodThread.start()

        for i in xrange(20):
            if not goodThread.isAlive():
                break
            time.sleep(0.5)

        if goodThread.isAlive():
            raise RunSetException("Could not get runset#%d latest first time" %
                                  self.__id)

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP done")

    def __startSet(self, setName, components):
        """
        Start a set of components and verify that they are running
        """
        rstart = datetime.datetime.now()
        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP start" + setName)
        tGroup = ComponentOperationGroup(ComponentOperation.START_RUN)
        opData = (self.__runData.runNumber(), )
        for c in components:
            tGroup.start(c, self.__runData, opData)
        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP wait" + setName)
        tGroup.wait()
        tGroup.reportErrors(self.__runData, "start" + setName)

        self.__logDebug(RunSetDebug.START_RUN,
                        "STARTCOMP wait" + setName + "Chg")
        self.__waitForStateChange(self.__runData, RunSetState.RUNNING, 30,
                                  components)

        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP chk" + setName)
        badStates = self.__checkState(RunSetState.RUNNING, components)
        self.__logDebug(RunSetDebug.START_RUN, "STARTCOMP bad%sStates %s",
                        (setName, badStates))
        if len(badStates) > 0:
            raise RunSetException(("Could not start runset#%d run#%d" +
                                   " %s components: %s") %
                                  (self.__id, self.__runData.runNumber(),
                                   setName, self.__badStateString(badStates)))
        rend = datetime.datetime.now() - rstart
        rsecs = float(rend.seconds) + (float(rend.microseconds) / 1000000.0)
        self.__logger.error("Waited %.3f seconds for %s" % (rsecs, setName))

    def __stopComponents(self, srcSet, otherSet, connDict, msgSecs):
        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING WAITCHK top")
        tGroup = ComponentOperationGroup(ComponentOperation.GET_STATE)
        for c in srcSet:
            tGroup.start(c, self.__logger, ())
        for c in otherSet:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()

        changed = False

        # remove stopped components from appropriate dictionary
        #
        states = tGroup.results()
        for set in (srcSet, otherSet):
            copy = set[:]
            for c in copy:
                if states.has_key(c):
                    stateStr = str(states[c])
                else:
                    stateStr = self.STATE_DEAD
                if stateStr != self.__state and stateStr != self.STATE_HANGING:
                    set.remove(c)
                    if c in connDict:
                        del connDict[c]
                    changed = True
                else:
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
        elif len(srcSet) > 0 or len(otherSet) > 0:
            #
            # one or more components must have stopped
            #
            newSecs = time.time()
            if msgSecs is None or \
                   newSecs < (msgSecs + self.WAIT_MSG_PERIOD):
                waitStr = \
                    self.__listComponentsAndConnections(srcSet + otherSet,
                                                        connDict)
                self.__runData.info('%s: Waiting for %s %s' %
                                    (str(self), self.__state, waitStr))
                msgSecs = newSecs

        return msgSecs

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
        otherSet.sort(lambda x, y: self.__sortCmp(y, x))

        # start thread to find earliest last time from hubs
        #
        goodThread = LastGoodTimeThread(srcSet[:], otherSet[:],
                                        self.__runData, self.__runData)
        goodThread.start()

        try:
            timeout = 20
            for i in range(0, 2):
                if self.__runData is None:
                    break

                self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING phase %d", i)
                if i == 0:
                    self.__attemptToStop(srcSet, otherSet,
                                         RunSetState.STOPPING,
                                         ComponentOperation.STOP_RUN,
                                         int(timeout * .75))
                else:
                    self.__attemptToStop(srcSet, otherSet,
                                         RunSetState.FORCING_STOP,
                                         ComponentOperation.FORCED_STOP,
                                         int(timeout * .25))
                if len(srcSet) == 0 and len(otherSet) == 0:
                    break
        finally:
            # detector has stopped, no need to get last good time
            try:
                goodThread.stop()
            except:
                # ignore problems stopping goodThread
                pass

        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING reset")
        if self.__runData is not None:
            self.__runData.reset()
        self.__logDebug(RunSetDebug.STOP_RUN, "STOPPING reset done")

        return srcSet + otherSet

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
                    except DOMNotInConfigException:
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
                except DOMNotInConfigException:
                    not_found.append("Pos %s-%s" % (string, pos))
                    continue
            else:
                raise InvalidSubrunData("Bad subrun arguments %s" %
                                        str(args))
            doms.append(args)
        return (doms, not_found)

    def __waitForStateChange(self, logger, stateName, timeoutSecs=TIMEOUT_SECS,
                             components=None):
        """
        Wait for state change, with a timeout of timeoutSecs (renewed each time
        any component changes state).  Raise a ValueError if the state change
        fails.
        """
        if components is None:
            waitList = self.__set[:]
        else:
            waitList = components[:]

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
                if stateStr == stateName and stateStr != self.STATE_HANGING:
                    newList.remove(c)

            # if one or more components changed state...
            #
            if len(waitList) == len(newList):
                time.sleep(1)
            else:
                waitList = newList
                if len(waitList) > 0:
                    waitStr = listComponentRanges(waitList)
                    logger.info('%s: Waiting for %s %s' %
                                (str(self), self.__state, waitStr))

                # reset timeout
                #
                endSecs = time.time() + timeoutSecs

        if len(waitList) > 0:
            waitStr = listComponentRanges(waitList)
            raise RunSetException(("Still waiting for %d components to" +
                                   " leave %s (%s)") %
                                  (len(waitList), self.__state, waitStr))

    def buildConnectionMap(self):
        "Validate and fill the map of connections for each component"
        self.__logDebug(RunSetDebug.START_RUN, "BldConnMap TOP")
        connDict = {}

        for comp in self.__set:
            for n in comp.connectors():
                if not n.name() in connDict:
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
                                listComponentRanges(waitList)))

            time.sleep(1)

        self.__waitForStateChange(self.__logger, RunSetState.READY, 60)

        badStates = self.__checkState(RunSetState.READY)
        if len(badStates) > 0:
            msg = "Could not configure %s" % self.__badStateString(badStates)
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
            self.__waitForStateChange(self.__logger, RunSetState.CONNECTED, 20)
        except:
            # give up after 20 seconds
            pass

        badStates = self.__checkState(RunSetState.CONNECTED)

        if errMsg is None and len(badStates) != 0:
            errMsg = "Could not connect %s" % self.__badStateString(badStates)

        if errMsg:
            raise RunSetException(errMsg)

        self.__logDebug(RunSetDebug.START_RUN, "RSConn DONE")

    @staticmethod
    def createComponentLog(runDir, comp, host, port, liveHost, livePort,
                           quiet=True):
        if not os.path.exists(runDir):
            raise RunSetException("Run directory \"%s\" does not exist" %
                                  runDir)

        logName = os.path.join(runDir, "%s-%d.log" % (comp.name(), comp.num()))
        sock = LogSocketServer(port, comp.fullName(), logName, quiet=quiet)
        sock.startServing()

        return sock

    def createRunData(self, runNum, clusterConfig, runOptions, versionInfo,
                      spadeDir, copyDir, logDir, testing=False):
        return RunData(self, runNum, clusterConfig, self.__cfg,
                       runOptions, versionInfo, spadeDir, copyDir, logDir,
                       testing)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        if not os.path.exists(logDir):
            raise RunSetException("Log directory \"%s\" does not exist" %
                                  logDir)

        runDir = self.__getRunDirectoryPath(logDir, runNum)
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

    def createTaskManager(self, dashlog, liveMoniClient, runDir, runConfig,
                          runOptions):
        return TaskManager(self, dashlog, liveMoniClient, runDir, runConfig,
                           runOptions)

    @classmethod
    def cycleComponents(self, compList, configDir, daqDataDir, logger,
                        logPort, livePort, verbose, killWith9, eventCheck,
                        checkExists=True):

        # sort list into a predictable order for unit tests
        #
        compStr = listComponentRanges(compList)
        logger.error("Cycling components %s" % compStr)

        dryRun = False
        ComponentManager.killComponents(compList, dryRun, verbose, killWith9)
        ComponentManager.startComponents(compList, dryRun, verbose, configDir,
                                         daqDataDir, logger.logPort(),
                                         logger.livePort(), eventCheck,
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

    def debugBits(self):
        return self.__debugBits

    def getEventCounts(self):
        "Return monitoring data for the run"
        if self.__runData is None:
            return {}

        # only update event counts while RunSet is taking data
        updateCounts = self.__state == RunSetState.RUNNING
        return self.__runData.getEventCounts(self.__set, updateCounts)

    def id(self):
        return self.__id

    def initReplayHubs(self):
        "Initialize all replay hubs"
        self.__logDebug(RunSetDebug.START_RUN, "RSInitReplay TOP")
        replayHubs = self.__getReplayHubs()
        if len(replayHubs) == 0:
            return

        prevState = self.__state
        self.__state = RunSetState.INIT_REPLAY

        try:
            self.__internalInitReplay(replayHubs)
        finally:
            self.__state = prevState

    def isDestroyed(self):
        return self.__state == RunSetState.DESTROYED

    def isReady(self):
        return self.__state == RunSetState.READY

    def isRunning(self):
        return self.__state == RunSetState.RUNNING

    def logToDash(self, msg):
        "Used when the runset needs to add a log message to dash.log"
        if self.__runData is not None:
            self.__runData.error(msg)
        else:
            self.__logger.error(msg)

    def queueForSpade(self, duration):
        if self.__runData is None:
            self.__logger.error("No run data; cannot queue for SPADE")
            return

        self.__runData.queueForSpade(duration)

    @classmethod
    def getRunSummary(cls, logDir, runNum):
        runDir = cls.__getRunDirectoryPath(logDir, runNum)
        if not os.path.exists(runDir):
            raise RunSetException("No run directory found for run %d" % runNum)

        return DashXMLLog.parse(runDir)

    def reportRunStartFailure(self, runNum, release, revision):
        try:
            moniClient = MoniClient("pdaq", "localhost", DAQPort.I3LIVE)
        except:
            self.__logger.error("Cannot create temporary client: " +
                                exc_string())
            return

        try:
            RunData.reportRunStartClass(moniClient, runNum, release, revision,
                                        False)
        finally:
            try:
                moniClient.close()
            except:
                self.__logger.error("Could not close temporary client: " +
                                    exc_string())

    def reset(self):
        "Reset all components in the runset back to the idle state"
        self.__state = RunSetState.RESETTING

        tGroup = ComponentOperationGroup(ComponentOperation.RESET_COMP)
        for c in self.__set:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "reset")

        try:
            self.__waitForStateChange(self.__logger, RunSetState.IDLE, 60)
        except:
            # give up after 60 seconds
            pass

        badStates = self.__checkState(RunSetState.IDLE)

        self.__configured = False
        self.__runData = None

        return badStates

    def resetLogging(self):
        "Reset logging for all components in the runset"
        tGroup = ComponentOperationGroup(ComponentOperation.RESET_LOGGING)
        for c in self.__set:
            tGroup.start(c, self.__logger, ())
        tGroup.wait()
        tGroup.reportErrors(self.__logger, "resetLogging")

    def restartAllComponents(self, clusterConfig, configDir, daqDataDir,
                             logPort, livePort, verbose, killWith9,
                             eventCheck):
        # restarted components are removed from self.__set, so we need to
        # pass in a copy of self.__set, because we'll need self.__set intact
        self.restartComponents(self.__set[:], clusterConfig, configDir,
                               daqDataDir, logPort, livePort, verbose,
                               killWith9, eventCheck)

    def restartComponents(self, compList, clusterConfig, configDir, daqDataDir,
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
                                    (comp.fullName(),
                                     clusterConfig.configName()))
            else:
                try:
                    self.__set.remove(comp)
                except ValueError:
                    self.__logger.error(("Cannot remove component %s from" +
                                         " RunSet #%d") %
                                        (comp.fullName(), self.__id))

                # clean up active log thread
                if comp in self.__compLog:
                    try:
                        self.__compLog[comp].stopServing()
                    except:
                        pass

                try:
                    comp.close()
                except:
                    self.__logger.error("Close failed for %s: %s" %
                                        (comp.fullName(), exc_string()))

        self.cycleComponents(cluCfgList, configDir, daqDataDir, self.__logger,
                             logPort, livePort, verbose, killWith9, eventCheck)

    def returnComponents(self, pool, clusterConfig, configDir, daqDataDir,
                         logPort, livePort, verbose, killWith9, eventCheck):
        badStates = self.reset()

        badComps = []
        if len(badStates) > 0:
            self.__logger.error("Restarting %s after reset" %
                                self.__badStateString(badStates))
            for state in badStates:
                badComps += badStates[state]
            self.restartComponents(badComps, clusterConfig, configDir,
                                   daqDataDir, logPort, livePort, verbose,
                                   killWith9, eventCheck)

        # transfer components back to pool
        #
        while len(self.__set) > 0:
            comp = self.__set[0]
            del self.__set[0]
            if not comp in badComps:
                pool.add(comp)
            else:
                self.__logger.error("Not returning unexpected component %s" %
                                    comp.fullName())

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
            self.__runData.sendEventCounts(self.__set,
                                           self.__state == RunSetState.RUNNING)

    def setDebugBits(self, debugBit):
        if debugBit == 0:
            self.__debugBits = 0
        else:
            self.__debugBits |= debugBit

        if self.__runData is not None:
            self.__runData.setDebugBits(self.__debugBits)

    def setError(self):
        self.__logDebug(RunSetDebug.STOP_RUN, "SetError %s", self.__runData)
        if self.__state == RunSetState.RUNNING:
            try:
                self.stopRun(hadError=True)
            except:
                pass

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
            if c in allComps:
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
                if not c in allComps:
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

    def startRun(self, runNum, clusterConfig, runOptions, versionInfo,
                 spadeDir, copyDir=None, logDir=None, quiet=True):
        "Start all components in the runset"
        self.__logger.error("Starting run #%d on \"%s\"" %
                            (runNum, clusterConfig.descName()))
        self.__logDebug(RunSetDebug.START_RUN, "STARTING %d - %s",
                        runNum, clusterConfig.descName())
        if not self.__configured:
            raise RunSetException("RunSet #%d is not configured" % self.__id)
        if not self.__state == RunSetState.READY:
            raise RunSetException("Cannot start runset from state \"%s\"" %
                                  self.__state)

        self.__logDebug(RunSetDebug.START_RUN, "STARTING creRunData")
        self.__runData = self.createRunData(runNum, clusterConfig,
                                            runOptions, versionInfo,
                                            spadeDir, copyDir, logDir)
        self.__runData.setDebugBits(self.__debugBits)

        # record the earliest possible start time
        #
        startTime = datetime.datetime.now()

        self.__runData.connectToI3Live()
        self.__logDebug(RunSetDebug.START_RUN, "STARTING startComps")
        self.__startComponents(quiet)
        self.__logDebug(RunSetDebug.START_RUN, "STARTING finishSetup")
        self.__runData.finishSetup(self, startTime)
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
        waitList = []
        try:
            waitList = self.__stopRunInternal(hadError)
        except:
            hadError = True
            self.__logger.error("Could not stop run %s: %s" %
                                (self, exc_string()))
            raise
        finally:
            self.__stopping = False
            if len(waitList) > 0:
                hadError = True
            if self.__runData is not None:
                try:
                    duration = self.__finishRun(self.__set, self.__runData,
                                                hadError)
                except:
                    duration = 0
                    self.__logger.error("Could not finish run for %s: %s" %
                                        (self, exc_string()))
                try:
                    self.__stopLogging()
                except:
                    self.__logger.error("Could not stop logs for %s: %s" %
                                        (self, exc_string()))
                try:
                    self.__runData.sendEventCounts(self.__set, False)
                except:
                    self.__logger.error("Could not send event counts" +
                                        " for %s: %s" % (self, exc_string()))

                # NOTE: ALL FILES MUST BE WRITTEN OUT BEFORE THIS POINT
                # THIS IS WHERE EVERYTHING IS PUT IN A TARBALL FOR SPADE
                try:
                    self.queueForSpade(duration)
                except:
                    self.__logger.error("Could not queue SPADE files" +
                                        " for %s: %s" % (self, exc_string()))

                self.__checkStoppedComponents(waitList)

        return hadError

    def stopping(self):
        return self.__stopping

    def subrun(self, id, data):
        "Start a subrun with all components in the runset"
        if self.__runData is None or self.__state != RunSetState.RUNNING:
            raise RunSetException("RunSet #%d is not running" % self.__id)

        if len(data) > 0:
            try:
                (newData, missingDoms) = self.__validateSubrunDOMs(data)
                if len(missingDoms) > 0:
                    if len(missingDoms) > 1:
                        sStr = "s"
                    else:
                        sStr = ""
                    self.__runData.warn(("Subrun %d: ignoring missing" +
                                         " DOM%s %s") % (id, sStr,
                                                         missingDoms))

                # newData has any missing DOMs deleted and any string/position
                # pairs converted to mainboard IDs
                data = newData
            except InvalidSubrunData as inv:
                raise RunSetException("Subrun %d: invalid argument list (%s)" %
                                      (id, inv))

            if len(missingDoms) > 1:
                sStr = "s"
            else:
                sStr = ""
            self.__runData.error("Subrun %d: flashing DOM%s (%s)" %
                                 (id, sStr, str(data)))
        else:
            self.__runData.error("Subrun %d: stopping flashers" % id)
        for c in self.__set:
            if c.isBuilder():
                c.prepareSubrun(id)

        self.__runData.setSubrunNumber(-id)

        hubs = []
        tGroup = ComponentOperationGroup(ComponentOperation.START_SUBRUN)
        for c in self.__set:
            if c.isSource():
                tGroup.start(c, self.__runData, (data, ))
                hubs.append(c)
        tGroup.wait(20)
        tGroup.reportErrors(self.__runData, "startSubrun")

        badComps = []

        latestTime = None
        r = tGroup.results()
        for c in hubs:
            result = r[c]
            if result is None or \
                result == ComponentOperation.RESULT_HANGING or \
                result == ComponentOperation.RESULT_ERROR:
                badComps.append(c)
            elif latestTime is None or result > latestTime:
                latestTime = result

        if latestTime is None:
            raise RunSetException("Couldn't start subrun on any string hubs")

        if len(badComps) > 0:
            raise RunSetException("Couldn't start subrun on %s" %
                                  listComponentRanges(badComps))

        for c in self.__set:
            if c.isBuilder():
                c.commitSubrun(id, latestTime)

        self.__runData.setSubrunNumber(id)

    def subrunEvents(self, subrunNumber):
        "Get the number of events in the specified subrun"
        for c in self.__set:
            if c.isBuilder():
                return c.subrunEvents(subrunNumber)

        raise RunSetException('RunSet #%d does not contain an event builder' %
                              self.__id)

    @staticmethod
    def switchComponentLog(sock, runDir, comp):
        if not os.path.exists(runDir):
            raise RunSetException("Run directory \"%s\" does not exist" %
                                  runDir)

        logName = os.path.join(runDir, "%s-%d.log" % (comp.name(), comp.num()))
        sock.setOutput(logName)

    def switchRun(self, newNum):
        "Switch all components in the runset to a new run"
        if self.__runData is None or self.__state != RunSetState.RUNNING:
            raise RunSetException("RunSet #%d is not running" % self.__id)

        # get list of all builders
        #
        bldrs = []
        for c in self.__set:
            if c.isBuilder():
                bldrs.append(c)
        if len(bldrs) == 0:
            raise RunSetException("Cannot find any builders in runset#%d" %
                                  self.__id)

        # stop monitoring, watchdog, etc.
        #
        self.__runData.stop()

        # create new run data object
        #
        newData = self.__runData.clone(self, newNum)
        newData.connectToI3Live()

        newData.error("Switching to run %d..." % newNum)

        # switch logs to new daqrun directory before switching components
        #
        for c in self.__compLog:
            self.switchComponentLog(self.__compLog[c], newData.runDirectory(),
                                    c)

        # get lists of sources and of non-sources sorted back to front
        #
        srcSet, otherSet = self.__buildStartSets()

        # record the earliest possible start time
        #
        startTime = datetime.datetime.now()

        # switch non-sources to new run
        # NOTE: sources are not currently switched
        #
        for c in otherSet:
            c.switchToNewRun(newNum)

        # wait for builders to finish switching
        #
        for _ in xrange(240):
            for c in bldrs:
                num = c.getRunNumber()
                if num == newNum:
                    bldrs.remove(c)

            if len(bldrs) == 0:
                break

            time.sleep(0.25)

        # if there's a problem...
        #
        if len(bldrs) > 0:
            bStr = []
            for c in bldrs:
                bStr.append(c.fullName())
            raise RunSetException("Still waiting for %s to finish switching" %
                                  (bStr))

        # switch to new run data
        #
        oldData = self.__runData
        self.__runData = newData

        savedEx = None

        # finish new run data setup
        #
        try:
            newData.finishSetup(self, startTime)
        except:
            savedEx = sys.exc_info()

        try:
            duration = self.__finishRun(self.__set, oldData, False,
                                        switching=True)

            oldData.sendEventCounts(self.__set, False)

            # NOTE: ALL FILES MUST BE WRITTEN OUT BEFORE THIS POINT
            # THIS IS WHERE EVERYTHING IS PUT IN A TARBALL FOR SPADE
            self.queueForSpade(duration)
        except:
            if not savedEx:
                savedEx = sys.exc_info()

        try:
            self.__reportFirstGoodTime(newData)
        except:
            if not savedEx:
                savedEx = sys.exc_info()

        if savedEx:
            raise savedEx[0], savedEx[1], savedEx[2]

    def updateRates(self):
        if self.__runData is None:
            return None
        return self.__runData.updateRates(self.__set)

if __name__ == "__main__":
    pass
