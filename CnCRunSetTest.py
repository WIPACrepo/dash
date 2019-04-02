#!/usr/bin/env python

import copy
import shutil
import tempfile
import time
import unittest

from locate_pdaq import set_pdaq_config_dir
from ActiveDOMsTask import ActiveDOMsTask
from ComponentManager import ComponentManager
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
from RunSet import RunData, RunSet, RunSetException
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask


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
        if beanName not in self.__beanData:
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))
        if fieldName not in self.__beanData[beanName]:
            raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                             (str(self), beanName, fieldName))

        return self.__beanData[beanName][fieldName]

    def getAttributes(self, beanName, fieldList):
        if beanName not in self.__beanData:
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))

        valMap = {}
        for f in fieldList:
            if f not in self.__beanData[beanName]:
                raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                                 (str(self), beanName, f))

            valMap[f] = self.__beanData[beanName][f]

        return valMap

    def getBeanNames(self):
        return []

    def getDictionary(self):
        return copy.deepcopy(self.__beanData)

    def reload(self):
        pass

    def setData(self, beanName, fieldName, value):
        if beanName not in self.__beanData:
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
            raise SystemExit("No connectors for %s" % str(self))
        return self.__conn[:]

    def createMBeanClient(self):
        return self.__mbean

    @property
    def filename(self):
        return "/dev/null"

    @property
    def fullname(self):
        return "%s#%s" % (self.__name, self.__num)

    def getRunData(self, runnum):
        if self.__num == 0:
            if self.__name.startswith("event"):
                evtData = self.__mbean.get("backEnd", "EventData")
                numEvts = int(evtData[1])
                lastTime = int(evtData[2])

                val = self.__mbean.get("backEnd", "FirstEventTime")
                firstTime = int(val)

                good = self.__mbean.get("backEnd", "GoodTimes")
                firstGood = int(good[0])
                lastGood = int(good[1])

                return (numEvts, firstTime, lastTime, firstGood, lastGood)
        raise SystemExit("Cannot return run data for \"%s\"" %
                         (self.fullname, ))

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

    def createIntervalTimer(self, name, period):
        if name not in self.TIMERS:
            self.TIMERS[name] = MockIntervalTimer(name, self.WAITSECS)

        return self.TIMERS[name]

    def getTimer(self, name):
        if name not in self.TIMERS:
            raise SystemExit("Unknown timer \"%s\"" % (name, ))

        return self.TIMERS[name]


class FakeMoniClient(object):
    def __init__(self):
        pass

    def close(self):
        pass

    def sendMoni(self, name, data, prio=None, time=None):
        pass


class MostlyRunData(RunData):
    def __init__(self, runSet, runNumber, clusterConfig, runConfig,
                 runOptions, versionInfo, spadeDir, copyDir, logDir,
                 dashlog=None):
        self.__dashlog = dashlog

        self.__taskMgr = None

        super(MostlyRunData, self).__init__(runSet, runNumber, clusterConfig,
                                            runConfig, runOptions,
                                            versionInfo, spadeDir, copyDir,
                                            logDir)

    def create_dash_log(self):
        if self.__dashlog is None:
            raise Exception("dashLog has not been set")

        return self.__dashlog

    def create_moni_client(self, port):
        return FakeMoniClient()

    def create_task_manager(self, runset):
        self.__taskMgr = MostlyTaskManager(runset, self.__dashlog,
                                           self.moni_client,
                                           self.run_directory,
                                           self.run_configuration,
                                           self.run_options)
        return self.__taskMgr

    @property
    def task_manager(self):
        return self.__taskMgr


class MyRunSet(RunSet):
    FAIL_STATE = "fail"

    def __init__(self, parent, runConfig, compList, logger):
        self.__runConfig = runConfig

        self.__rundata = None
        self.__dashlog = None
        self.__failReset = None

        super(MyRunSet, self).__init__(parent, runConfig, compList, logger)

    @staticmethod
    def create_component_log(runDir, comp, host, port, liveHost, livePort,
                             quiet=True):
        return MockComponentLogger(str(comp))

    def create_run_data(self, runNum, clusterConfig, runOptions, versionInfo,
                        spadeDir, copyDir=None, logDir=None):
        rd = MostlyRunData(self, runNum, clusterConfig, self.__runConfig,
                           runOptions, versionInfo, spadeDir, copyDir, logDir,
                           dashlog=self.__dashlog)
        self.__rundata = rd
        return rd

    @classmethod
    def cycle_components(cls, compList, configDir, daqDataDir, logger, logPort,
                         livePort, verbose, killWith9, eventCheck,
                         checkExists=True):
        compStr = ComponentManager.format_component_list(compList)
        logger.error("Cycling components %s" % compStr)

    def getTaskManager(self):
        if self.__rundata is None:
            raise SystemExit("RunData cannot be None")
        return self.__rundata.task_manager

    def reset(self):
        if self.__failReset is not None:
            return (self.__failReset, )
        return {}

    def set_dash_log(self, logger):
        if self.__rundata is not None:
            raise SystemExit("RunData cannot be set")
        self.__dashlog = logger

    def setUnresetComponent(self, comp):
        self.__failReset = comp


class MostlyCnCServer(CnCServer):
    def __init__(self, clusterConfigObject=None, copyDir=None,
                 defaultLogDir=None, runConfigDir=None, daqDataDir=None,
                 spadeDir=None):
        self.__clusterConfig = clusterConfigObject
        self.__logServer = None

        super(MostlyCnCServer, self).__init__(copyDir=copyDir,
                                              defaultLogDir=defaultLogDir,
                                              runConfigDir=runConfigDir,
                                              daqDataDir=daqDataDir,
                                              spadeDir=spadeDir,
                                              forceRestart=False,
                                              testOnly=True)

    def createRunset(self, runConfig, compList, logger):
        return MyRunSet(self, runConfig, compList, logger)

    def cycle_components(self, compList, runConfigDir, daqDataDir, logger,
                         logPort, livePort, verbose=False, killWith9=False,
                         eventCheck=False):
        MyRunSet.cycle_components(compList, runConfigDir, daqDataDir, logger,
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


class CnCRunSetTest(unittest.TestCase):
    HUB_NUMBER = 21
    EXAMPLE_DOM = 0x737d355af587

    BEAN_DATA = {
        "stringHub": {
            "DataCollectorMonitor-00A": {
                "MainboardId": "%012x" % EXAMPLE_DOM,
            },
            "sender": {
                "NumHitsReceived": 0,
                "NumReadoutRequestsReceived": 0,
                "NumReadoutsSent": 0,
            },
            "stringhub": {
                "NumberOfActiveAndTotalChannels": 0,
                "TotalLBMOverflows": 0,
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
                "EventData": (0, 0, 0),
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

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                           "NumberOfActiveAndTotalChannels",
                           (numDOMs, numTotal))

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                           "TotalLBMOverflows",
                           20)

        liveMoni.addExpectedLiveMoni("activeDOMs", numDOMs)
        liveMoni.addExpectedLiveMoni("expectedDOMs", numTotal)

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

        self.__setBeanData(comps, "eventBuilder", 0, "backEnd", "EventData",
                           [runNum, 0, 0])

        dashLog.addExpectedRegexp(r"\s+0 physics events, 0 moni events," +
                                  r" 0 SN events, 0 tcals")

        timer.trigger()

        self.__waitForEmptyLog(dashLog, "Didn't get rate message")

        self.__setBeanData(comps, "eventBuilder", 0, "backEnd", "EventData",
                           [runNum, numEvts, payTime])
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

    def __checkWatchdogTask(self, comps, rs, dashLog, liveMoni,
                            unhealthy=False):
        timer = rs.getTaskManager().getTimer(WatchdogTask.NAME)

        self.__setBeanData(comps, "eventBuilder", 0, "backEnd",
                           "DiskAvailable", 0)

        if unhealthy:
            dashLog.addExpectedRegexp("Watchdog reports starved components.*")
            dashLog.addExpectedRegexp("Watchdog reports threshold components.*")

        timer.trigger()

        time.sleep(MostlyTaskManager.WAITSECS * 2.0)

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
            if c.name not in cls.BEAN_DATA:
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
        self.__logDir = tempfile.mkdtemp()

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
        rs.set_dash_log(dashLog)

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

        versionInfo = {
            "filename": "fName",
            "revision": "1234",
            "date": "date",
            "time": "time",
            "author": "author",
            "release": "rel",
            "repo_rev": "1repoRev",
        }

        rs.start_run(runNum, cluCfg, RunOption.MONI_TO_NONE, versionInfo,
                     spade_dir=self.__spadeDir, log_dir=self.__logDir)

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

        dashLog.addExpectedExact("%d physics events collected in %d"
                                 " seconds%s" % (numEvts, duration, hzStr))

        numMoni = 0
        numSN = 0
        numTcal = 0

        dashLog.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcal))
        dashLog.addExpectedExact("Run terminated SUCCESSFULLY.")

        dashLog.addExpectedExact("Not logging to file so cannot queue to"
                                 " SPADE")

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER,
                           "stringhub", "EarliestLastChannelHitTime", 20)

        self.assertFalse(rs.stop_run(stopName), "stop_run() encountered error")

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
        for _ in range(5):
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
        self.__logDir = None

        set_pdaq_config_dir(None, override=True)

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

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
        if self.__logDir is not None:
            shutil.rmtree(self.__logDir, ignore_errors=True)

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
        self.__logDir = tempfile.mkdtemp()

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
                                     defaultLogDir=self.__logDir,
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
        self.assertFalse(rs is None, "Could not find runset #%d" % rsId)

        time.sleep(1)

        if catchall:
            catchall.checkStatus(5)

        dashLog = MockLogger("dashLog")
        rs.set_dash_log(dashLog)

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

        for idx in range(5):
            self.__checkWatchdogTask(comps, rs, dashLog, liveMoni,
                                     unhealthy=(idx >= 3))

        if catchall:
            catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        duration = self.__computeDuration(firstTime, payTime)
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % self.__computeRateHz(0, numEvts, duration)

        dashLog.addExpectedExact("%d physics events collected in %d"
                                 " seconds%s" % (numEvts, duration, hzStr))

        numMoni = 0
        numSN = 0
        numTcal = 0

        dashLog.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcal))
        dashLog.addExpectedExact("Run terminated SUCCESSFULLY.")

        dashLog.addExpectedExact("Not logging to file so cannot queue to"
                                 " SPADE")

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
