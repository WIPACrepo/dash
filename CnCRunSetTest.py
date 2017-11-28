#!/usr/bin/env python

import shutil
import tempfile
import time
import unittest

from locate_pdaq import set_pdaq_config_dir
from ActiveDOMsTask import ActiveDOMsTask
from ComponentManager import listComponentRanges
from CnCExceptions import CnCServerException, MissingComponentException
from CnCServer import CnCServer
from DAQConst import DAQPort
from DAQMocks import MockClusterConfig, MockDefaultDomGeometryFile, \
    MockIntervalTimer, MockLeapsecondFile, MockLogger, MockRunConfigFile, \
    RunXMLValidator, SocketReader
from DAQTime import PayloadTime
from LiveImports import LIVE_IMPORT
from MonitorTask import MonitorTask
from RateTask import RateTask
from RunOption import RunOption
from RunSet import RunSet, RunSetException
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask

ACTIVE_WARNING = False


class MockComponentLogger(MockLogger):
    def __init__(self, name):
        super(MockComponentLogger, self).__init__(name)

    def stopServing(self):
        pass


class MockLoggerPlusPorts(MockLogger):
    def __init__(self, name, logPort, livePort):
        super(MockLoggerPlusPorts, self).__init__(name)
        self.__logPort = logPort
        self.__livePort = livePort

    @property
    def livePort(self):
        return self.__livePort

    @property
    def logPort(self):
        return self.__logPort


class MockConn(object):
    def __init__(self, connName, descrCh):
        self.__name = connName
        self.__descrCh = descrCh

    def __repr__(self):
        if self.isInput:
            return "->%s(%s)" % (self.__descrCh, self.__name)

        return "%s->(%s)" % (self.__descrCh, self.__name)

    @property
    def isInput(self):
        return self.__descrCh == "i" or self.__descrCh == "I"

    @property
    def isOptional(self):
        return self.__descrCh == "I" or self.__descrCh == "O"

    @property
    def name(self):
        return self.__name


class MockMBeanClient(object):
    def __init__(self):
        self.__beanData = {}

    def check(self, beanName, fieldName):
        pass

    def get(self, beanName, fieldName):
        if not beanName in self.__beanData:
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))
        if not fieldName in self.__beanData[beanName]:
            raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                             (str(self), beanName, fieldName))

        return self.__beanData[beanName][fieldName]

    def getBeanFields(self, beanName):
        if not beanName in self.__beanData:
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))

        return self.__beanData[beanName].keys()

    def getBeanNames(self):
        return self.__beanData.keys()

    def getAttributes(self, beanName, fieldList):
        if not beanName in self.__beanData:
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))

        valMap = {}
        for f in fieldList:
            if not f in self.__beanData[beanName]:
                raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                                 (str(self), beanName, f))

            valMap[f] = self.__beanData[beanName][f]

        return valMap

    def reload(self):
        pass

    def setData(self, beanName, fieldName, value):
        if not beanName in self.__beanData:
            self.__beanData[beanName] = {}
        self.__beanData[beanName][fieldName] = value

class MockComponent(object):
    def __init__(self, name, num=0, conn=None):
        self.__name = name
        self.__num = num
        self.__conn = conn
        self.__state = "idle"
        self.__order = None

        self.__mbean = MockMBeanClient()

    def __str__(self):
        if self.__num == 0 and not self.isSource:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def __repr__(self):
        return str(self)

    def close(self):
        pass

    def configure(self, runCfg):
        self.__state = "ready"

    def connect(self, map=None):
        self.__state = "connected"

    def connectors(self):
        if self.__conn is None:
            return []
        return self.__conn[:]

    def createMBeanClient(self):
        return self.__mbean

    @property
    def filename(self):
        return "%s-%s" % (self.__name, self.__num)

    @property
    def fullname(self):
        return "%s#%s" % (self.__name, self.__num)

    def getRunData(self, runnum):
        if self.__num == 0:
            if self.__name.startswith("event"):
                evtData = self.__mbean.get("backEnd", "EventData")
                numEvts = int(evtData[0])
                lastTime = long(evtData[1])

                val = self.__mbean.get("backEnd", "FirstEventTime")
                firstTime = long(val)

                good = self.__mbean.get("backEnd", "GoodTimes")
                firstGood = long(good[0])
                lastGood = long(good[1])

                return (numEvts, firstTime, lastTime, firstGood, lastGood)
            elif self.__name.startswith("secondary"):
                for bldr in ("tcalBuilder", "snBuilder", "moniBuilder"):
                    val = self.__mbean.get(bldr, "NumDispatchedData")
                    if bldr == "tcalBuilder":
                        numTcal = long(val)
                    elif bldr == "snBuilder":
                        numSN = long(val)
                    elif bldr == "moniBuilder":
                        numMoni = long(val)

                return (numTcal, numSN, numMoni)
        return (None, None, None)

    @property
    def is_dying(self):
        return False

    @property
    def isBuilder(self):
        return self.__name.lower().endswith("builder")

    def isComponent(self, name, num=-1):
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def isReplayHub(self):
        return False

    @property
    def isSource(self):
        return self.__name.lower().endswith("hub")

    def logTo(self, host, port, liveHost, livePort):
        pass

    @property
    def mbean(self):
        return self.__mbean

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    def order(self):
        return self.__order

    def reset(self):
        self.__state = "idle"

    def resetLogging(self):
        pass

    def setFirstGoodTime(self, payTime):
        pass

    def setLastGoodTime(self, payTime):
        pass

    def setOrder(self, order):
        self.__order = order

    def startRun(self, runCfg):
        self.__state = "running"

    def stopRun(self):
        self.__state = "ready"

    @property
    def state(self):
        return self.__state


class MostlyTaskManager(TaskManager):
    WAITSECS = 0.25

    TIMERS = {}

    def __init__(self, runset, dashlog, liveMoniClient, runDir, runCfg,
                 moniType):
        super(MostlyTaskManager, self).__init__(runset, dashlog,
                                                liveMoniClient,
                                                runDir, runCfg, moniType)

    def createIntervalTimer(self, name, period):
        if not name in self.TIMERS:
            self.TIMERS[name] = MockIntervalTimer(name, self.WAITSECS)

        return self.TIMERS[name]

    def getTimer(self, name):
        if not name in self.TIMERS:
            return None

        return self.TIMERS[name]


class MyRunSet(RunSet):
    FAIL_STATE = "fail"

    def __init__(self, parent, runConfig, compList, logger):
        self.__taskMgr = None
        self.__failReset = None
        self.__dashLog = None

        super(MyRunSet, self).__init__(parent, runConfig, compList, logger)

    @staticmethod
    def createComponentLog(runDir, comp, host, port, liveHost, livePort,
                           quiet=True):
        return MockComponentLogger(str(comp))

    def createDashLog(self):
        if self.__dashLog is None:
            raise Exception("dashLog has not been set")

        return self.__dashLog

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir=None, logDir=None, testing=True):
        return super(MyRunSet, self).createRunData(runNum, clusterConfigName,
                                                   runOptions, versionInfo,
                                                   spadeDir, copyDir, logDir,
                                                   True)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        return None

    def createTaskManager(self, dashlog, liveMoniClient, runDir, runCfg,
                          moniType):
        self.__taskMgr = MostlyTaskManager(self, dashlog, liveMoniClient,
                                           runDir, runCfg, moniType)
        return self.__taskMgr

    @classmethod
    def cycleComponents(cls, compList, configDir, daqDataDir, logger, logPort,
                        livePort, verbose, killWith9, eventCheck,
                        checkExists=True):
        compStr = listComponentRanges(compList)
        logger.error("Cycling components %s" % compStr)

    def getTaskManager(self):
        return self.__taskMgr

    def setDashLog(self, dashLog):
        self.__dashLog = dashLog

    def queueForSpade(self, runData, duration):
        pass

    def reset(self):
        if self.__failReset is not None:
            return (self.__failReset, )
        return {}

    def setUnresetComponent(self, comp):
        self.__failReset = comp


class MostlyCnCServer(CnCServer):
    def __init__(self, clusterConfigObject=None, copyDir=None,
                 runConfigDir=None, daqDataDir=None, spadeDir=None):
        self.__clusterConfig = clusterConfigObject
        self.__logServer = None

        super(MostlyCnCServer, self).__init__(copyDir=copyDir,
                                              runConfigDir=runConfigDir,
                                              daqDataDir=daqDataDir,
                                              spadeDir=spadeDir,
                                              forceRestart=False,
                                              testOnly=True)

    def createRunset(self, runConfig, compList, logger):
        return MyRunSet(self, runConfig, compList, logger)

    def cycleComponents(self, compList, runConfigDir, daqDataDir, logger,
                        logPort, livePort, verbose=False, killWith9=False,
                        eventCheck=False):
        MyRunSet.cycleComponents(compList, runConfigDir, daqDataDir, logger,
                                 logPort, livePort, verbose=verbose,
                                 killWith9=killWith9, eventCheck=eventCheck)

    def getClusterConfig(self, runConfig=None):
        return self.__clusterConfig

    def getLogServer(self):
        return self.__logServer

    def openLogServer(self, port, logDir):
        if self.__logServer is None:
            self.__logServer = SocketReader("catchall", port)

        self.__logServer.addExpectedText("Start of log at" +
                                         " LOG=log(localhost:%d)" % port)

        return self.__logServer

    def saveCatchall(self, runDir):
        pass

    def startLiveThread(self):
        return None


class CnCRunSetTest(unittest.TestCase):
    HUB_NUMBER = 21
    EXAMPLE_DOM = 0x737d355af587

    BEAN_DATA = {
        "stringHub": {
            "DataCollectorMonitor-00A": {
                "MainboardId": "%012x" % EXAMPLE_DOM,
                "HitRate": 0.0,
            },
            "sender": {
                "NumHitsReceived": 0,
                "NumReadoutRequestsReceived": 0,
                "NumReadoutsSent": 0,
            },
            "stringhub": {
                "NumberOfActiveAndTotalChannels": 0,
                "TotalLBMOverflows": 0,
                "HitRate": 0,
                "HitRateLC": 0,
                "LatestFirstChannelHitTime": -1,
                "EarliestLastChannelHitTime": -1,
                "NumberOfNonZombies": 60,
            },
        },
        "inIceTrigger": {
            "stringHit": {
                "RecordsReceived": 0,
            },
            "trigger": {
                "RecordsSent": 0,
            },
        },
        "globalTrigger": {
            "trigger": {
                "RecordsReceived": 0,
            },
            "glblTrig": {
                "RecordsSent": 0,
            },
        },
        "eventBuilder": {
            "backEnd": {
                "DiskAvailable": 2048,
                "EventData": (0, 0),
                "FirstEventTime": 0,
                "GoodTimes": (0, 0),
                "NumBadEvents": 0,
                "NumEventsDispatched": 0,
                "NumEventsSent": 0,
                "NumReadoutsReceived": 0,
                "NumTriggerRequestsReceived": 0,
            }
        },
        "extraComp": {
        },
    }

    def __addLiveMoni(self, comps, liveMoni, compName, compNum, beanName,
                      fieldName, isJSON=False):

        if not LIVE_IMPORT:
            return

        for c in comps:
            if c.name == compName and c.num == compNum:
                val = c.mbean.get(beanName, fieldName)
                var = "%s-%d*%s+%s" % (compName, compNum, beanName, fieldName)
                if isJSON:
                    liveMoni.addExpectedLiveMoni(var, val, "json")
                else:
                    liveMoni.addExpectedLiveMoni(var, val)
                return

        raise Exception("Unknown component %s-%d" % (compName, compNum))

    def __addRunStartMoni(self, liveMoni, runNum, release, revision, started):

        if not LIVE_IMPORT:
            return

        data = {"runnum": runNum,
                "release": release,
                "revision": revision,
                "started": True}
        liveMoni.addExpectedLiveMoni("runstart", data, "json")

    def __addRunStopMoni(self, liveMoni, firstTime, lastTime, numEvts, runNum):

        if not LIVE_IMPORT:
            return

        data = {
            "runnum": runNum,
            "runstart": str(PayloadTime.toDateTime(firstTime)),
            "events": numEvts,
            "status": "SUCCESS"
        }
        liveMoni.addExpectedLiveMoni("runstop", data, "json")

    def __checkActiveDOMsTask(self, comps, rs, liveMoni):
        if not LIVE_IMPORT:
            return

        timer = rs.getTaskManager().getTimer(ActiveDOMsTask.NAME)

        numDOMs = 22
        numTotal = 60
        #totalOverflows = 20
        hitRate = 50.
        hitRateLC = 25.

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                           "NumberOfActiveAndTotalChannels",
                           (numDOMs, numTotal))

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                           "TotalLBMOverflows",
                           20)

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                           "HitRateLC",
                           hitRateLC)
        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                           "HitRate",
                           hitRate)

        liveMoni.addExpectedLiveMoni("activeDOMs", numDOMs)
        liveMoni.addExpectedLiveMoni("expectedDOMs", numTotal)
        liveMoni.addExpectedLiveMoni("total_rate", hitRate)
        liveMoni.addExpectedLiveMoni("total_ratelc", hitRateLC)

        timer.trigger()

        self.__waitForEmptyLog(liveMoni, "Didn't get active DOM message")

        liveMoni.checkStatus(5)

    def __checkMonitorTask(self, comps, rs, liveMoni):
        timer = rs.getTaskManager().getTimer(MonitorTask.NAME)

        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "sender", "NumHitsReceived")
        self.__addLiveMoni(comps, liveMoni, "inIceTrigger", 0, "stringHit",
                           "RecordsReceived")
        self.__addLiveMoni(comps, liveMoni, "inIceTrigger", 0, "trigger",
                           "RecordsSent")
        self.__addLiveMoni(comps, liveMoni, "globalTrigger", 0, "trigger",
                           "RecordsReceived")
        self.__addLiveMoni(comps, liveMoni, "globalTrigger", 0, "glblTrig",
                           "RecordsSent")
        self.__addLiveMoni(comps, liveMoni, "eventBuilder", 0, "backEnd",
                           "NumTriggerRequestsReceived")
        self.__addLiveMoni(comps, liveMoni, "eventBuilder", 0, "backEnd",
                           "NumReadoutsReceived")
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "sender", "NumReadoutRequestsReceived")
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "sender", "NumReadoutsSent")
        self.__addLiveMoni(comps, liveMoni, "eventBuilder", 0, "backEnd",
                           "NumEventsSent")

        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "stringhub", "NumberOfActiveAndTotalChannels")
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "stringhub", "TotalLBMOverflows")
        self.__addLiveMoni(comps, liveMoni, "eventBuilder", 0, "backEnd",
                           "DiskAvailable")
        self.__addLiveMoni(comps, liveMoni, "eventBuilder", 0, "backEnd",
                           "NumBadEvents")
        self.__addLiveMoni(comps, liveMoni, "eventBuilder", 0, "backEnd",
                           "EventData", True)
        self.__addLiveMoni(comps, liveMoni, "eventBuilder", 0, "backEnd",
                           "FirstEventTime", False)
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "DataCollectorMonitor-00A", "MainboardId")
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "DataCollectorMonitor-00A", "HitRate")

        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "stringhub", "HitRateLC")
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "stringhub", "HitRate")

        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "stringhub", "EarliestLastChannelHitTime")
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "stringhub", "LatestFirstChannelHitTime")
        self.__addLiveMoni(comps, liveMoni, "stringHub", self.HUB_NUMBER,
                           "stringhub", "NumberOfNonZombies")

        timer.trigger()

        self.__waitForEmptyLog(liveMoni, "Didn't get moni messages")

        liveMoni.checkStatus(5)

    def __checkRateTask(self, comps, rs, liveMoni, dashLog, numEvts, payTime,
                        firstTime, runNum):
        timer = rs.getTaskManager().getTimer(RateTask.NAME)

        dashLog.addExpectedRegexp(r"\s+0 physics events, 0 moni events," +
                                  r" 0 SN events, 0 tcals")

        timer.trigger()

        self.__waitForEmptyLog(dashLog, "Didn't get rate message")

        self.__setBeanData(comps, "eventBuilder", 0, "backEnd", "EventData",
                           [numEvts, payTime])
        self.__setBeanData(comps, "eventBuilder", 0, "backEnd",
                           "FirstEventTime", firstTime)
        self.__setBeanData(comps, "eventBuilder", 0, "backEnd",
                           "GoodTimes", (firstTime, payTime))

        duration = self.__computeDuration(firstTime, payTime)
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % self.__computeRateHz(1, numEvts, duration)

        dashLog.addExpectedExact(("	%d physics events%s, 0 moni events," +
                                  " 0 SN events, 0 tcals") % (numEvts, hzStr))

        timer.trigger()

        self.__waitForEmptyLog(dashLog, "Didn't get second rate message")

        dashLog.checkStatus(5)
        if liveMoni is not None:
            liveMoni.checkStatus(5)

    def __checkWatchdogTask(self, comps, rs, dashLog, liveMoni):
        timer = rs.getTaskManager().getTimer(WatchdogTask.NAME)

        self.__setBeanData(comps, "eventBuilder", 0, "backEnd",
                           "DiskAvailable", 0)

        timer.trigger()

        time.sleep(MostlyTaskManager.WAITSECS * 2.0)

        dashLog.addExpectedRegexp("Watchdog reports threshold components.*")
        #dashLog.addExpectedExact("Run is unhealthy (%d checks left)" %
        #                         (WatchdogTask.HEALTH_METER_FULL - 1))

        timer.trigger()

        self.__waitForEmptyLog(dashLog, "Didn't get watchdog message")

        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

    def __computeDuration(self, startTime, curTime):
        domTicksPerSec = 10000000000
        return (curTime - startTime) / domTicksPerSec

    def __computeRateHz(self, startEvts, curEvts, duration):
        return float(curEvts - startEvts) / float(duration)

    @classmethod
    def __loadBeanData(cls, compList):
        for c in compList:
            if not c.name in cls.BEAN_DATA:
                raise Exception("No bean data found for %s" % str(c))

            for b in cls.BEAN_DATA[c.name]:
                if len(cls.BEAN_DATA[c.name][b]) == 0:
                    c.mbean.setData(b, "xxx", 0)
                else:
                    for f in cls.BEAN_DATA[c.name][b]:
                        c.mbean.setData(b, f, cls.BEAN_DATA[c.name][b][f])

    def __runDirect(self, failReset):
        self.__copyDir = tempfile.mkdtemp()
        self.__runConfigDir = tempfile.mkdtemp()
        self.__spadeDir = tempfile.mkdtemp()

        set_pdaq_config_dir(self.__runConfigDir)

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"), )),
                 MockComponent("extraComp")]

        cluCfg = MockClusterConfig("clusterFoo")
        for comp in comps:
            cluCfg.addComponent(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=cluCfg)

        self.__loadBeanData(comps)

        nameList = []
        for c in comps:
            self.__cnc.add(c)
            if c.name != "stringHub" and c.name != "extraComp":
                nameList.append(str(c))

        hubDomDict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.createDOM(self.EXAMPLE_DOM, 1, "Example",
                                         "X123"), ],
        }

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create(nameList, hubDomDict)

        MockDefaultDomGeometryFile.create(self.__runConfigDir, hubDomDict)

        leapFile = MockLeapsecondFile(self.__runConfigDir)
        leapFile.create()

        logger = MockLogger("main")
        logger.addExpectedExact("Loading run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        runNum = 321
        daqDataDir = None

        rs = self.__cnc.makeRunset(self.__runConfigDir, runConfig, runNum, 0,
                                   logger, daqDataDir, forceRestart=False,
                                   strict=False)

        logger.checkStatus(5)

        dashLog = MockLogger("dashLog")
        rs.setDashLog(dashLog)

        logger.addExpectedExact("Starting run #%d on \"%s\"" %
                                (runNum, cluCfg.description))

        dashLog.addExpectedRegexp(r"Version info: \S+ \S+ \S+ \S+")
        dashLog.addExpectedExact("Run configuration: %s" % runConfig)
        dashLog.addExpectedExact("Cluster: %s" % cluCfg.description)

        dashLog.addExpectedExact("Starting run %d..." % runNum)

        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER,
                           "stringhub", "LatestFirstChannelHitTime", 10)

        global ACTIVE_WARNING
        if not LIVE_IMPORT and not ACTIVE_WARNING:
            ACTIVE_WARNING = True
            dashLog.addExpectedExact("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        versionInfo = {
            "filename": "fName",
            "revision": "1234",
            "date": "date",
            "time": "time",
            "author": "author",
            "release": "rel",
            "repo_rev": "1repoRev",
        }

        rs.startRun(runNum, cluCfg, RunOption.MONI_TO_NONE, versionInfo,
                    "/tmp")

        logger.checkStatus(5)
        dashLog.checkStatus(5)

        numEvts = 1000
        payTime = 50000000001
        firstTime = 1

        self.__checkRateTask(comps, rs, None, dashLog, numEvts, payTime,
                             firstTime, runNum)

        stopName = "RunDirect"
        dashLog.addExpectedExact("Stopping the run (%s)" % stopName)

        duration = self.__computeDuration(firstTime, payTime)
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % self.__computeRateHz(0, numEvts, duration)

        dashLog.addExpectedExact(("%d physics events collected "
                                  "in %d seconds%s") % \
                                     (numEvts,
                                      duration,
                                      hzStr))

        numMoni = 0
        numSN = 0
        numTcal = 0

        dashLog.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcal))
        dashLog.addExpectedExact("Run terminated SUCCESSFULLY.")

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER,
                           "stringhub", "EarliestLastChannelHitTime", 20)

        self.failIf(rs.stopRun(stopName), "stopRun() encountered error")

        logger.checkStatus(5)
        dashLog.checkStatus(5)

        if failReset:
            rs.setUnresetComponent(comps[0])
            logger.addExpectedExact("Cycling components %s#%d" %
                                    (comps[0].name, comps[0].num))
        try:
            self.__cnc.returnRunset(rs, logger)
            if failReset:
                self.fail("returnRunset should not have succeeded")
        except RunSetException:
            if not failReset:
                raise

        logger.checkStatus(5)
        dashLog.checkStatus(5)

        RunXMLValidator.validate(self, runNum, runConfig, cluCfg.description,
                                 None, None, numEvts, numMoni, numSN, numTcal,
                                 False)

    @staticmethod
    def __setBeanData(comps, compName, compNum, beanName, fieldName,
                      value):
        setData = False
        for c in comps:
            if c.name == compName and c.num == compNum:
                if setData:
                    raise Exception("Found multiple components for %s" %
                                    c.fullname)

                c.mbean.setData(beanName, fieldName, value)
                setData = True

        if not setData:
            raise Exception("Could not find component %s#%d" %
                            (compName, compNum))

    @staticmethod
    def __waitForEmptyLog(log, errMsg):
        for i in range(5):
            if log.isEmpty:
                break
            time.sleep(0.25)
        log.checkStatus(1)

    def setUp(self):
        self.__cnc = None

        self.__copyDir = None
        self.__runConfigDir = None
        self.__daqDataDir = None
        self.__spadeDir = None

        set_pdaq_config_dir(None, override=True)

        RunXMLValidator.setUp()

    def tearDown(self):
        if self.__cnc is not None:
            self.__cnc.closeServer()

        if self.__copyDir is not None:
            shutil.rmtree(self.__copyDir, ignore_errors=True)
        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)
        if self.__daqDataDir is not None:
            shutil.rmtree(self.__daqDataDir, ignore_errors=True)
        if self.__spadeDir is not None:
            shutil.rmtree(self.__spadeDir, ignore_errors=True)

        RunXMLValidator.tearDown()

    def testEmptyRunset(self):
        self.__runConfigDir = tempfile.mkdtemp()
        self.__daqDataDir = tempfile.mkdtemp()

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"), )),
                 MockComponent("extraComp")]

        cluCfg = MockClusterConfig("clusterFoo")
        for comp in comps:
            cluCfg.addComponent(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=cluCfg,
                                     runConfigDir=self.__runConfigDir)

        nameList = []

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create(nameList, {})
        runNum = 123

        logger = MockLogger("main")
        logger.addExpectedExact("Loading run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Cycling components %s#%d" %
                                (comps[0].name, comps[0].num))

        self.assertRaises(CnCServerException, self.__cnc.makeRunset,
                          self.__runConfigDir, runConfig, runNum, 0, logger,
                          self.__daqDataDir, forceRestart=False, strict=False)

    def testMissingComponent(self):
        self.__runConfigDir = tempfile.mkdtemp()

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"), )),
                 MockComponent("extraComp")]

        cluCfg = MockClusterConfig("clusterMissing")
        for comp in comps:
            cluCfg.addComponent(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=cluCfg)

        hubDomDict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.createDOM(self.EXAMPLE_DOM, 1, "Example",
                                         "X123"), ],
        }

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create([], hubDomDict)

        MockDefaultDomGeometryFile.create(self.__runConfigDir, hubDomDict)

        runNum = 456

        logger = MockLoggerPlusPorts("main", 10101, 20202)
        logger.addExpectedExact("Loading run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Cycling components %s#%d" %
                                (comps[0].name, comps[0].num))

        self.assertRaises(MissingComponentException, self.__cnc.makeRunset,
                          self.__runConfigDir, runConfig, runNum, 0, logger,
                          self.__daqDataDir, forceRestart=False, strict=False)

    def testRunDirect(self):
        self.__runDirect(False)

    def testFailReset(self):
        self.__runDirect(True)

    def testRunIndirect(self):
        self.__copyDir = tempfile.mkdtemp()
        self.__runConfigDir = tempfile.mkdtemp()
        self.__spadeDir = tempfile.mkdtemp()

        set_pdaq_config_dir(self.__runConfigDir)

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"),)),
                 MockComponent("extraComp")]

        cluCfg = MockClusterConfig("clusterFoo")
        for comp in comps:
            cluCfg.addComponent(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=cluCfg,
                                     copyDir=self.__copyDir,
                                     runConfigDir=self.__runConfigDir,
                                     daqDataDir=self.__daqDataDir,
                                     spadeDir=self.__spadeDir)

        catchall = self.__cnc.getLogServer()

        self.__loadBeanData(comps)

        nameList = []
        for c in comps:
            self.__cnc.add(c)
            if c.name != "stringHub" and c.name != "extraComp":
                nameList.append(str(c))

        runCompList = []
        for c in comps:
            if c.isSource or c.name == "extraComp":
                continue
            runCompList.append(c.fullname)

        hubDomDict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.createDOM(self.EXAMPLE_DOM, 1, "Example",
                                         "X123"), ],
        }

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create(runCompList, hubDomDict)

        MockDefaultDomGeometryFile.create(self.__runConfigDir, hubDomDict)

        leapFile = MockLeapsecondFile(self.__runConfigDir)
        leapFile.create()

        catchall.addExpectedText("Loading run configuration \"%s\"" %
                                 runConfig)
        catchall.addExpectedText("Loaded run configuration \"%s\"" % runConfig)
        catchall.addExpectedTextRegexp(r"Built runset #\d+: .*")

        liveMoni = SocketReader("liveMoni", DAQPort.I3LIVE, 99)
        liveMoni.startServing()

        runNum = 345

        rsId = self.__cnc.rpc_runset_make(runConfig, runNum)

        if catchall:
            catchall.checkStatus(5)
        liveMoni.checkStatus(5)

        rs = self.__cnc.findRunset(rsId)
        self.failIf(rs is None, "Could not find runset #%d" % rsId)

        time.sleep(1)

        if catchall:
            catchall.checkStatus(5)

        dashLog = MockLogger("dashLog")
        rs.setDashLog(dashLog)

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER,
                           "stringhub", "LatestFirstChannelHitTime", 10)
        if LIVE_IMPORT:
            data = {"runnum": runNum, "subrun": 0}
            liveMoni.addExpectedLiveMoni("firstGoodTime", data, "json")

        (rel, rev) = self.__cnc.getRelease()
        self.__addRunStartMoni(liveMoni, runNum, rel, rev, True)

        catchall.addExpectedText("Starting run #%d on \"%s\"" %
                                 (runNum, cluCfg.description))

        dashLog.addExpectedRegexp(r"Version info: \S+ \S+ \S+ \S+")
        dashLog.addExpectedExact("Run configuration: %s" % runConfig)
        dashLog.addExpectedExact("Cluster: %s" % cluCfg.description)

        dashLog.addExpectedExact("Starting run %d..." % runNum)

        catchall.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        catchall.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        global ACTIVE_WARNING
        if not LIVE_IMPORT and not ACTIVE_WARNING:
            ACTIVE_WARNING = True
            dashLog.addExpectedExact("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        self.__cnc.rpc_runset_start_run(rsId, runNum, RunOption.MONI_TO_LIVE)

        if catchall:
            catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        numEvts = 5
        payTime = 50000000001
        firstTime = 1

        self.__checkRateTask(comps, rs, liveMoni, dashLog, numEvts, payTime,
                             firstTime, runNum)
        self.__checkMonitorTask(comps, rs, liveMoni)
        self.__checkActiveDOMsTask(comps, rs, liveMoni)
        self.__checkWatchdogTask(comps, rs, dashLog, liveMoni)

        if catchall:
            catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        duration = self.__computeDuration(firstTime, payTime)
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % self.__computeRateHz(0, numEvts, duration)

        dashLog.addExpectedExact(("%d physics events collected "
                                  "in %d seconds%s") % \
                                     (numEvts,
                                      duration,
                                      hzStr))

        numMoni = 0
        numSN = 0
        numTcal = 0

        dashLog.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcal))
        dashLog.addExpectedExact("Run terminated SUCCESSFULLY.")

        self.__addRunStopMoni(liveMoni, firstTime, payTime, numEvts, runNum)

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER,
                           "stringhub", "EarliestLastChannelHitTime", 20)
        if LIVE_IMPORT:
            data = {"runnum": runNum}
            liveMoni.addExpectedLiveMoni("lastGoodTime", data, "json")

        self.__cnc.rpc_runset_stop_run(rsId)

        time.sleep(1)

        if catchall:
            catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        RunXMLValidator.validate(self, runNum, runConfig, cluCfg.description,
                                 None, None, numEvts, numMoni, numSN, numTcal,
                                 False)

        self.__cnc.rpc_runset_break(rsId)

        if catchall:
            catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        catchall.stopServing()
        liveMoni.stopServing()

if __name__ == '__main__':
    unittest.main()
