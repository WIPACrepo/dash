#!/usr/bin/env python

import shutil, sys, tempfile, time, unittest

from ActiveDOMsTask import ActiveDOMsTask
from CnCServer import CnCServer, CnCServerException
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQMocks import MockClusterConfig, MockIntervalTimer, MockLogger, \
    MockRunConfigFile, SocketReader
from LiveImports import LIVE_IMPORT
from MonitorTask import MonitorTask
from RadarTask import RadarTask, RadarThread
from RateTask import RateTask
from RunOption import RunOption
from RunSet import RunSet, RunSetException
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask

ACTIVE_WARNING = False

class MockComponentLogger(MockLogger):
    def __init__(self, name):
        super(MockComponentLogger, self).__init__(name)

    def stopServing(self): pass

class MockConn(object):
    def __init__(self, connName, descrCh):
        self.__name = connName
        self.__descrCh = descrCh

    def __repr__(self):
        if self.isInput():
            return "->%s" % self.type

        return "%s->" % self.type

    def isInput(self): return self.__descrCh == "i" or self.__descrCh == "I"
    def isOptional(self): return self.__descrCh == "I" or self.__descrCh == "O"

    def name(self): return self.__name

class MockComponent(object):
    def __init__(self, name, num=0, conn=None):
        self.__name = name
        self.__num = num
        self.__conn = conn
        self.__state = "idle"
        self.__order = None
        self.__beanData = {}

    def __str__(self):
        if self.__num == 0 and not self.isSource():
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def __repr__(self): return str(self)

    def checkBeanField(self, beanName, fieldName): pass

    def close(self): pass

    def configure(self, runCfg):
        self.__state = "ready"

    def connect(self, map=None):
        self.__state = "connected"

    def connectors(self):
        if self.__conn is None:
            return []
        return self.__conn[:]

    def fileName(self): return "%s-%s" % (self.__name, self.__num)

    def fullName(self): return "%s#%s" % (self.__name, self.__num)

    def getBeanFields(self, beanName):
        if not self.__beanData.has_key(beanName):
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))

        return self.__beanData[beanName].keys()

    def getBeanNames(self):
        return self.__beanData.keys()

    def getMultiBeanFields(self, beanName, fieldList):
        if not self.__beanData.has_key(beanName):
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))

        valMap = {}
        for f in fieldList:
            if not self.__beanData[beanName].has_key(f):
                raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                                 (str(self), beanName, f))

            valMap[f] = self.__beanData[beanName][f]

        return valMap

    def getSingleBeanField(self, beanName, fieldName):
        if not self.__beanData.has_key(beanName):
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), beanName))
        if not self.__beanData[beanName].has_key(fieldName):
            raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                             (str(self), beanName, fieldName))

        return self.__beanData[beanName][fieldName]

    def isBuilder(self): return self.__name.lower().endswith("builder")

    def isComponent(self, name, num=-1):
        return self.__name == name and (num < 0 or self.__num == num)

    def isSource(self): return self.__name.lower().endswith("hub")
    def logTo(self, host, port, liveHost, livePort): pass
    def name(self): return self.__name
    def num(self): return self.__num
    def order(self): return self.__order

    def reset(self):
        self.__state = "idle"

    def resetLogging(self): pass

    def setBeanData(self, beanName, fieldName, value):
        if not self.__beanData.has_key(beanName):
            self.__beanData[beanName] = {}
        self.__beanData[beanName][fieldName] = value

    def setOrder(self, order): self.__order = order

    def startRun(self, runCfg):
        self.__state = "running"

    def stopRun(self):
        self.__state = "ready"

    def state(self): return self.__state

class MostlyTaskManager(TaskManager):
    WAITSECS = 0.25

    TIMERS = {}

    def __init__(self, runset, dashlog, liveMoniClient, runDir, moniType):
        super(MostlyTaskManager, self).__init__(runset, dashlog, liveMoniClient,
                                                runDir, moniType)

    def createIntervalTimer(self, name, period):
        if not self.TIMERS.has_key(name):
            self.TIMERS[name] = MockIntervalTimer(name, self.WAITSECS)

        return self.TIMERS[name]

    def getTimer(self, name):
        if not self.TIMERS.has_key(name):
            return None

        return self.TIMERS[name]

class MyRunSet(RunSet):
    FAIL_STATE = "fail"

    def __init__(self, parent, runConfig, compList, logger):
        self.__taskMgr = None
        self.__failReset = None

        super(MyRunSet, self).__init__(parent, runConfig, compList, logger)

    def createComponentLog(self, runDir, comp, host, port, liveHost, livePort,
                           quiet=True):
        return MockComponentLogger(str(comp))

    def createDashLog(self):
        if self.__dashLog is None:
            raise Exception("dashLog has not been set")

        return self.__dashLog

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir=None, logDir=None):
        return super(MyRunSet, self).createRunData(runNum, clusterConfigName,
                                                   runOptions, versionInfo,
                                                   spadeDir, copyDir, logDir,
                                                   True)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        return None

    def createTaskManager(self, dashlog, liveMoniClient, runDir, moniType):
        self.__taskMgr = MostlyTaskManager(self, dashlog, liveMoniClient,
                                           runDir, moniType)
        return self.__taskMgr

    def cycleComponents(self, compList, configDir, dashDir, logPort, livePort,
                        verbose, killWith9, eventCheck, checkExists=True):
        pass

    def getTaskManager(self):
        return self.__taskMgr

    def setDashLog(self, dashLog):
        self.__dashLog = dashLog

    def queueForSpade(self, duration):
        pass

    def reset(self):
        if self.__failReset is not None:
            return [(self.__failReset, self.FAIL_STATE), ]
        return []

    def setUnresetComponent(self, comp):
        self.__failReset = comp

class MostlyCnCServer(CnCServer):
    def __init__(self, clusterConfigObject=None, copyDir=None,
                 runConfigDir=None, spadeDir=None):
        self.__clusterConfig = clusterConfigObject
        self.__logServer = None

        super(MostlyCnCServer, self).__init__(copyDir=copyDir,
                                              runConfigDir=runConfigDir,
                                              spadeDir=spadeDir,
                                              forceRestart=False,
                                              testOnly=True)

    def createRunset(self, runConfig, compList, logger):
        return MyRunSet(self, runConfig, compList, logger)

    def getClusterConfig(self):
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
    RADAR_DOM = "737d355af587"

    BEAN_DATA = { "stringHub" :
                      { "DataCollectorMonitor-00A" :
                            { "MainboardId" : RADAR_DOM,
                              "HitRate" : 0.0,
                              },
                        "sender" :
                            { "NumHitsReceived" : 0,
                              "NumReadoutRequestsReceived" : 0,
                              "NumReadoutsSent" : 0,
                              },
                        "stringhub" :
                            { "NumberOfActiveChannels" : 0,
                              },
                        },
                  "inIceTrigger" :
                      { "stringHit" :
                            { "RecordsReceived" : 0,
                              },
                        "trigger" :
                            { "RecordsSent" : 0 },
                        },
                  "globalTrigger" :
                      { "trigger" :
                            { "RecordsReceived" : 0,
                              },
                        "glblTrig" :
                            { "RecordsSent" : 0 },
                        },
                  "eventBuilder" :
                      { "backEnd" :
                            { "DiskAvailable" : 2048,
                              "EventData" : 0,
                              "FirstEventTime" : 0,
                              "NumBadEvents" : 0,
                              "NumEventsSent" : 0,
                              "NumReadoutsReceived" : 0,
                              "NumTriggerRequestsReceived" : 0,
                              }
                        },
                  "extraComp" : {},
                  }

    def __addLiveMoni(self, comps, liveMoni, compName, compNum, beanName,
                      fieldName, isJSON=False):

        if not LIVE_IMPORT:
            return

        for c in comps:
            if c.name() == compName and c.num() == compNum:
                val = c.getSingleBeanField(beanName, fieldName)
                var = "%s-%d*%s+%s" % (compName, compNum, beanName, fieldName)
                if isJSON:
                    liveMoni.addExpectedLiveMoni(var, val, "json")
                else:
                    liveMoni.addExpectedLiveMoni(var, val)
                return

        raise Exception("Unknown component %s-%d" % (compName, compNum))

    def __addRunStartMoni(self, liveMoni, firstTime, runNum):

        if not LIVE_IMPORT:
            return

        data = { "runnum": runNum }
        liveMoni.addExpectedLiveMoni("runstart", data, "json")

    def __addRunStopMoni(self, liveMoni, lastTime, numEvts, runNum):

        if not LIVE_IMPORT:
            return

        data = { "events" : numEvts, "runnum": runNum }
        liveMoni.addExpectedLiveMoni("runstop", data, "json")

    def __checkActiveDOMsTask(self, comps, rs, liveMoni):
        if not LIVE_IMPORT:
            return

        timer = rs.getTaskManager().getTimer(ActiveDOMsTask.NAME)

        numDOMs = 22

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                           "NumberOfActiveChannels", numDOMs)

        liveMoni.addExpectedLiveMoni("activeDOMs", numDOMs)

        timer.trigger()

        self.__waitForEmptyLog(liveMoni, "Didn't get active DOM message")

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

        self.__addLiveMoni(comps, liveMoni, "stringHub", 21, "stringhub",
                           "NumberOfActiveChannels")
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

        timer.trigger()

        self.__waitForEmptyLog(liveMoni, "Didn't get moni messages")

    def __checkRadarTask(self, comps, rs, liveMoni):
        if not LIVE_IMPORT:
            return

        timer = rs.getTaskManager().getTimer(RadarTask.NAME)

        hitRate = 12.34

        jsonStr = "[[\"%s\", %s]]" % (self.RADAR_DOM, hitRate)
        liveMoni.addExpectedLiveMoni("radarDOMs", jsonStr,
                                     "json")

        self.__setBeanData(comps, "stringHub", self.HUB_NUMBER,
                           "DataCollectorMonitor-00A",
                           "HitRate", hitRate)
        timer.trigger()

        self.__waitForEmptyLog(liveMoni, "Didn't get radar message")

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

        duration = self.__computeDuration(firstTime, payTime)
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % self.__computeRateHz(1, numEvts, duration)

        dashLog.addExpectedExact(("	%d physics events%s, 0 moni events," +
                                  " 0 SN events, 0 tcals") % (numEvts, hzStr))

        if liveMoni is not None:
            self.__addRunStartMoni(liveMoni, firstTime, runNum)

        timer.trigger()

        self.__waitForEmptyLog(dashLog, "Didn't get second rate message")

    def __checkWatchdogTask(self, comps, rs, dashLog):
        timer = rs.getTaskManager().getTimer(WatchdogTask.NAME)

        self.__setBeanData(comps, "eventBuilder", 0, "backEnd", "DiskAvailable",
                           0)

        timer.trigger()

        time.sleep(MostlyTaskManager.WAITSECS * 2.0)

        dashLog.addExpectedRegexp("Watchdog reports threshold components.*")
        dashLog.addExpectedExact("Run is unhealthy (%d checks left)" %
                                 (WatchdogTask.HEALTH_METER_FULL - 1))

        timer.trigger()

        self.__waitForEmptyLog(dashLog, "Didn't get watchdog message")

    def __computeDuration(self, startTime, curTime):
        domTicksPerSec = 10000000000
        return (curTime - startTime) / domTicksPerSec

    def __computeRateHz(self, startEvts, curEvts, duration):
        return float(curEvts - startEvts) / float(duration)

    def __loadBeanData(cls, compList):
        for c in compList:
            if not cls.BEAN_DATA.has_key(c.name()):
                raise Exception("No bean data found for %s" % str(c))

            for b in cls.BEAN_DATA[c.name()]:
                if len(cls.BEAN_DATA[c.name()][b]) == 0:
                    c.setBeanData(b, "xxx", 0)
                else:
                    for f in cls.BEAN_DATA[c.name()][b]:
                        c.setBeanData(b, f, cls.BEAN_DATA[c.name()][b][f])

    __loadBeanData = classmethod(__loadBeanData)

    def __loadRadarDOMMap(cls):
        RadarThread.DOM_MAP[cls.RADAR_DOM] = cls.HUB_NUMBER
    __loadRadarDOMMap = classmethod(__loadRadarDOMMap)

    def __runDirect(self, failReset):
        self.__copyDir = tempfile.mkdtemp()
        self.__runConfigDir = tempfile.mkdtemp()
        self.__spadeDir = tempfile.mkdtemp()

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
            cluCfg.addComponent(comp.fullName(), "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=cluCfg)

        self.__loadBeanData(comps)

        nameList = []
        for c in comps:
            self.__cnc.add(c)
            if c.name() != "stringHub" and c.name() != "extraComp":
                nameList.append(str(c))

        domList = [MockRunConfigFile.createDOM(self.RADAR_DOM), ]

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create(nameList, domList)

        logger = MockLogger("main")
        logger.addExpectedExact("Loading run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        rs = self.__cnc.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                                   forceRestart=False, strict=False)

        logger.checkStatus(5)

        dashLog = MockLogger("dashLog")
        rs.setDashLog(dashLog)

        runNum = 321

        logger.addExpectedExact("Starting run #%d with \"%s\"" %
                                (runNum, cluCfg.configName()))

        dashLog.addExpectedRegexp(r"Version info: \S+ \d+ \S+ \S+ \S+ \S+" +
                                  " \d+\S+")
        dashLog.addExpectedExact("Run configuration: %s" % runConfig)
        dashLog.addExpectedExact("Cluster configuration: %s" %
                                 cluCfg.configName())

        dashLog.addExpectedExact("Starting run %d..." % runNum)

        global ACTIVE_WARNING
        if not LIVE_IMPORT and not ACTIVE_WARNING:
            ACTIVE_WARNING = True
            dashLog.addExpectedExact("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        versionInfo = {"filename": "fName",
                       "revision": "1234",
                       "date": "date",
                       "time": "time",
                       "author": "author",
                       "release": "rel",
                       "repo_rev": "1repoRev",
                       }

        rs.startRun(runNum, cluCfg.configName(), RunOption.MONI_TO_NONE,
                    versionInfo, "/tmp")

        logger.checkStatus(5)
        dashLog.checkStatus(5)

        numEvts = 1000
        payTime = 50000000001
        firstTime = 1

        self.__checkRateTask(comps, rs, None, dashLog, numEvts, payTime,
                             firstTime, runNum)

        numMoni = 0
        numSN = 0
        numTcals = 0

        duration = self.__computeDuration(firstTime, payTime)
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % self.__computeRateHz(0, numEvts, duration)

        dashLog.addExpectedExact("%d physics events collected in %d seconds%s" %
                                 (numEvts, duration, hzStr))
        dashLog.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcals))
        dashLog.addExpectedExact("Run terminated SUCCESSFULLY.")

        self.failIf(rs.stopRun(), "stopRun() encountered error")

        logger.checkStatus(5)
        dashLog.checkStatus(5)

        if failReset:
            rs.setUnresetComponent(comps[0])
            logger.addExpectedExact("Restarting %s (state '%s' after reset)" %
                                    (comps[0], MyRunSet.FAIL_STATE))
            logger.addExpectedExact("Cycling components [%s]" % comps[0])
        try:
            self.__cnc.returnRunset(rs, logger)
            if failReset:
                self.fail("returnRunset should not have succeeded")
        except RunSetException:
            if not failReset: raise

        logger.checkStatus(5)
        dashLog.checkStatus(5)

    def __setBeanData(cls, comps, compName, compNum, beanName, fieldName,
                      value):
        setData = False
        for c in comps:
            if c.name() == compName and c.num() == compNum:
                c.setBeanData(beanName, fieldName, value)
                setData = True
                break

        if not setData:
            raise Exception("Could not find component %s#%d" %
                            (compName, compNum))

    __setBeanData = classmethod(__setBeanData)

    def __waitForEmptyLog(self, log, errMsg):
        for i in range(5):
            if log.isEmpty():
                break
            time.sleep(0.25)
        log.checkStatus(1)
    __waitForEmptyLog = classmethod(__waitForEmptyLog)

    def setUp(self):
        self.__cnc = None

        self.__copyDir = None
        self.__runConfigDir = None
        self.__spadeDir = None

    def tearDown(self):
        if self.__cnc is not None:
            self.__cnc.closeServer()

        if self.__copyDir is not None:
            shutil.rmtree(self.__copyDir, ignore_errors=True)
        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)
        if self.__spadeDir is not None:
            shutil.rmtree(self.__spadeDir, ignore_errors=True)

    def testEmptyRunset(self):
        self.__runConfigDir = tempfile.mkdtemp()

        self.__cnc = MostlyCnCServer()

        nameList = []

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create(nameList, [])

        logger = MockLogger("main")
        logger.addExpectedExact("Loading run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        self.assertRaises(CnCServerException, self.__cnc.makeRunset,
                          self.__runConfigDir, runConfig, 0, logger,
                          forceRestart=False, strict=False)

    def testMissingComponent(self):
        self.__runConfigDir = tempfile.mkdtemp()

        self.__cnc = MostlyCnCServer()

        domList = [MockRunConfigFile.createDOM(self.RADAR_DOM), ]

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create([], domList)

        logger = MockLogger("main")
        logger.addExpectedExact("Loading run configuration \"%s\"" % runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        self.assertRaises(CnCServerException, self.__cnc.makeRunset,
                          self.__runConfigDir, runConfig, 0, logger,
                          forceRestart=False, strict=False)

    def testRunDirect(self):
        self.__runDirect(False)

    def testFailReset(self):
        self.__runDirect(True)

    def testRunIndirect(self):
        self.__copyDir = tempfile.mkdtemp()
        self.__runConfigDir = tempfile.mkdtemp()
        self.__spadeDir = tempfile.mkdtemp()

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
            cluCfg.addComponent(comp.fullName(), "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=cluCfg,
                                     copyDir=self.__copyDir,
                                     runConfigDir=self.__runConfigDir,
                                     spadeDir=self.__spadeDir)

        catchall = self.__cnc.getLogServer()

        self.__loadBeanData(comps)

        self.__loadRadarDOMMap()

        nameList = []
        for c in comps:
            self.__cnc.add(c)
            if c.name() != "stringHub" and c.name() != "extraComp":
                nameList.append(str(c))

        runCompList = []
        for c in comps:
            if c.isSource() or c.name() == "extraComp": continue
            runCompList.append(c.fullName())

        domList = [MockRunConfigFile.createDOM(self.RADAR_DOM), ]

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create(runCompList, domList)

        catchall.addExpectedText("Loading run configuration \"%s\"" %
                                 runConfig)
        catchall.addExpectedText("Loaded run configuration \"%s\"" % runConfig)
        catchall.addExpectedTextRegexp(r"Built runset #\d+: .*")

        rsId = self.__cnc.rpc_runset_make(runConfig)

        rs = self.__cnc.findRunset(rsId)
        self.failIf(rs is None, "Could not find runset #%d" % rsId)

        time.sleep(1)

        if catchall: catchall.checkStatus(5)

        dashLog = MockLogger("dashLog")
        rs.setDashLog(dashLog)

        liveMoni = SocketReader("liveMoni", DAQPort.I3LIVE, 99)
        liveMoni.startServing()

        runNum = 345

        catchall.addExpectedText("Starting run #%d with \"%s\"" %
                                 (runNum, cluCfg.configName()))

        dashLog.addExpectedRegexp(r"Version info: \S+ \d+ \S+ \S+ \S+ \S+" +
                                  " \d+\S+")
        dashLog.addExpectedExact("Run configuration: %s" % runConfig)
        dashLog.addExpectedExact("Cluster configuration: %s" %
                                 cluCfg.configName())

        dashLog.addExpectedExact("Starting run %d..." % runNum)

        global ACTIVE_WARNING
        if not LIVE_IMPORT and not ACTIVE_WARNING:
            ACTIVE_WARNING = True
            dashLog.addExpectedExact("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        self.__cnc.rpc_runset_start_run(rsId, runNum, RunOption.MONI_TO_LIVE)

        if catchall: catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        numEvts = 5
        payTime = 50000000001
        firstTime = 1

        self.__checkRateTask(comps, rs, liveMoni, dashLog, numEvts, payTime,
                             firstTime, runNum)
        self.__checkMonitorTask(comps, rs, liveMoni)
        self.__checkActiveDOMsTask(comps, rs, liveMoni)
        self.__checkWatchdogTask(comps, rs, dashLog)
        self.__checkRadarTask(comps, rs, liveMoni)

        if catchall: catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        numMoni = 0
        numSN = 0
        numTcals = 0

        duration = self.__computeDuration(firstTime, payTime)
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % self.__computeRateHz(0, numEvts, duration)

        dashLog.addExpectedExact("%d physics events collected in %d seconds%s" %
                                 (numEvts, duration, hzStr))
        dashLog.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcals))
        dashLog.addExpectedExact("Run terminated SUCCESSFULLY.")

        self.__addRunStopMoni(liveMoni, payTime, numEvts, runNum)

        self.__cnc.rpc_runset_stop_run(rsId)

        time.sleep(1)

        if catchall: catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        self.__cnc.rpc_runset_break(rsId)

        if catchall: catchall.checkStatus(5)
        dashLog.checkStatus(5)
        liveMoni.checkStatus(5)

        catchall.stopServing()
        liveMoni.stopServing()

if __name__ == '__main__':
    unittest.main()
