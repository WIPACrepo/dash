#!/usr/bin/env python

import datetime, sys, time, unittest

from LiveImports import Prio
from RadarTask import RadarThread
from RunOption import RunOption
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask

from DAQMocks import MockIntervalTimer

class MockComponent(object):
    BEANBAG = {
        "stringHub" :
            { "stringhub" :
                  { "NumberOfActiveChannels" : 2 },
              "sender" :
                  { "NumHitsReceived" : 0,
                    "NumReadoutRequestsReceived" : 0,
                    "NumReadoutsSent" : 0,
                    },
              },
        "iceTopTrigger" :
            { "icetopHit" :
                  { "RecordsReceived" : 0 },
              "trigger" :
                  { "RecordsSent" : 0 },
              },
        "inIceTrigger" :
            { "stringHit" :
                  { "RecordsReceived" : 0 },
              "trigger" :
                  { "RecordsSent" : 0 },
              },
        "globalTrigger" :
            { "trigger" :
                  { "RecordsReceived" : 0 },
              "glblTrig" :
                  { "RecordsSent" : 0 },
              },
        "eventBuilder" :
            { "backEnd" :
                  { "DiskAvailable" : 2560,
                    "NumBadEvents" : 0,
                    "NumEventsSent" : 0,
                    "NumReadoutsReceived" : 0,
                    "NumTriggerRequestsReceived" : 0,
                    },
              },
        "secondaryBuilders" :
            { "moniBuilder" :
                  { "TotalDispatchedData" : 0 },
              "snBuilder" :
                  { "TotalDispatchedData" : 0,
                    "DiskAvailable" : 0,
                    },
              }
        }

    def __init__(self, name, num):
        self.__name = name
        self.__num = num

        self.__order = None
        self.__updatedRates = False

        self.__beanData = self.__createBeanData()

    def __str__(self):
        return self.fullName()

    def __createBeanData(self):
        if not self.BEANBAG.has_key(self.__name):
            raise Exception("No bean data found for %s" % self)

        data = {}
        for b in self.BEANBAG[self.__name]:
            if not data.has_key(b):
                data[b] = {}
            for f in self.BEANBAG[self.__name][b]:
                data[b][f] = self.BEANBAG[self.__name][b][f]

        return data

    def addBeanData(self, beanName, fieldName, value):
        if self.checkBeanField(beanName, fieldName):
            raise Exception("Value for %c bean %s field %s already exists" %
                            (self, beanName, fieldName))

        if not self.__beanData.has_key(beanName):
            self.__beanData[beanName] = {}
        self.__beanData[beanName][fieldName] = value

    def checkBeanField(self, beanName, fieldName):
        return self.__beanData.has_key(beanName) and \
            self.__beanData[beanName].has_key(fieldName)

    def fileName(self):
        return "%s-%d" % (self.__name, self.__num)

    def getBeanFields(self, beanName):
        return self.__beanData[beanName].keys()

    def getBeanNames(self):
        return self.__beanData.keys()

    def fullName(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def getMultiBeanFields(self, beanName, fieldList):
        rtnMap = {}
        for f in fieldList:
            rtnMap[f] = self.getSingleBeanField(beanName, f)
        return rtnMap

    def getSingleBeanField(self, beanName, fieldName):
        if not self.checkBeanField(beanName, fieldName):
            raise Exception("No %s data for bean %s field %s" %
                            (self, beanName, fieldName))

        return self.__beanData[beanName][fieldName]

    def isBuilder(self):
        return self.__name.lower().endswith("builder")

    def isSource(self):
        return self.__name.lower().endswith("hub")

    def name(self): return self.__name
    def num(self): return self.__num
    def order(self): return self.__order

    def reset(self):
        self.__updatedRates = False

    def setOrder(self, num):
        self.__order = num

    def updateRates(self): self.__updatedRates = True

    def wasUpdated(self): return self.__updatedRates

class MockLiveMoni(object):
    def __init__(self):
        self.__expMoni = {}

    def addExpected(self, var, val, prio):
        if not self.__expMoni.has_key(var):
            self.__expMoni[var] = []
        self.__expMoni[var].append((val, prio))

    def hasAllMoni(self):
        return len(self.__expMoni) == 0

    def sendMoni(self, var, val, prio, time=datetime.datetime.now()):
        if not self.__expMoni.has_key(var):
            raise Exception(("Unexpected live monitor data" +
                             " (var=%s, val=%s, prio=%d)") % (var, val, prio))

        expData = self.__expMoni[var].pop(0)
        if len(self.__expMoni[var]) == 0:
            del self.__expMoni[var]

        if val != expData[0] or prio != expData[1]:
            raise Exception(("Expected live monitor data (var=%s, val=%s," +
                             " prio=%d), not (var=%s, val=%s, prio=%d)") %
                            (var, expData[0], expData[1], var, val, prio))

        return True

class MockLog(object):
    LEVEL_ERROR = "ERROR"

    def __init__(self):
        self.__expMsgs = {}

    def __verifyMsg(self, level, msg):
        if not self.__expMsgs.has_key(level):
            raise Exception("Unexpected %s message: %s" % (level, msg))

        expMsg = self.__expMsgs[level].pop(0)
        if len(self.__expMsgs[level]) == 0:
            del self.__expMsgs[level]

        if msg != expMsg:
            raise Exception("Expected %s message \"%s\", not \"%s\"" %
                            (level, expMsg, msg))

    def addExpected(self, level, msg):
        if not self.__expMsgs.has_key(level):
            self.__expMsgs[level] = []
        self.__expMsgs[level].append(msg)

    def error(self, msg):
        self.__verifyMsg(self.LEVEL_ERROR, msg)

class MockRunSet(object):
    def __init__(self, comps):
        self.__comps = comps
        self.__running = False

    def components(self): return self.__comps[:]
    def isRunning(self): return self.__running
    def startRunning(self): self.__running = True
    def stopRunning(self): self.__running = False

    def updateRates(self):
        for c in self.__comps:
            c.updateRates()

class MyTaskManager(TaskManager):
    def __init__(self, runset, dashlog, live, runDir, moniType):
        self.__timerDict = {}
        super(MyTaskManager, self).__init__(runset, dashlog, live, runDir,
                                             moniType)

    def createIntervalTimer(self, name, period):
        timer = MockIntervalTimer(name)
        self.__timerDict[name] = timer
        return timer

    def triggerTimers(self):
        for k in self.__timerDict:
            self.__timerDict[k].trigger()

class TaskManagerTest(unittest.TestCase):
    def __addRadarDOMData(self, compList, radarString, radarDOM, hitRate):
        for c in compList:
            if c.isSource() and c.num() == radarString:
                c.addBeanData("DataCollectorMonitor-XXX", "MainboardId",
                              radarDOM)
                c.addBeanData("DataCollectorMonitor-XXX", "HitRate", hitRate)

    def __loadExpected(self, live, compList, radarString, radarDOM, hitRate):

        radarName = "stringHub-%d" % radarString

        # add monitoring data
        live.addExpected("stringHub-1*sender+NumHitsReceived",
                         0, Prio.ITS)
        live.addExpected("stringHub-1*sender+NumReadoutRequestsReceived",
                         0, Prio.ITS)
        live.addExpected("stringHub-1*sender+NumReadoutsSent", 0, Prio.ITS)
        live.addExpected("stringHub-1*stringhub+NumberOfActiveChannels",
                         2, Prio.ITS)
        live.addExpected(radarName + "*sender+NumHitsReceived", 0, Prio.ITS)
        live.addExpected(radarName + "*sender+NumReadoutRequestsReceived",
                         0, Prio.ITS)
        live.addExpected(radarName + "*sender+NumReadoutsSent", 0, Prio.ITS)
        live.addExpected(radarName + "*stringhub+NumberOfActiveChannels",
                         2, Prio.ITS)
        live.addExpected("iceTopTrigger-0*icetopHit+RecordsReceived",
                         0, Prio.ITS)
        live.addExpected("iceTopTrigger-0*trigger+RecordsSent", 0, Prio.ITS)
        live.addExpected("inIceTrigger-0*stringHit+RecordsReceived",
                         0, Prio.ITS)
        live.addExpected("inIceTrigger-0*trigger+RecordsSent", 0, Prio.ITS)
        live.addExpected("globalTrigger-0*trigger+RecordsReceived", 0, Prio.ITS)
        live.addExpected("globalTrigger-0*glblTrig+RecordsSent", 0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumTriggerRequestsReceived",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumReadoutsReceived",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumEventsSent", 0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumBadEvents", 0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+DiskAvailable", 2560, Prio.ITS)
        live.addExpected("secondaryBuilders-0*moniBuilder+TotalDispatchedData",
                         0, Prio.ITS)
        live.addExpected("secondaryBuilders-0*snBuilder+TotalDispatchedData",
                         0, Prio.ITS)
        live.addExpected("secondaryBuilders-0*snBuilder+DiskAvailable",
                         0, Prio.ITS)

        # add activeDOM data
        live.addExpected("activeDOMs", 4, Prio.ITS)
        live.addExpected("activeStringDOMs", {"1":2, "%d" % radarString :2},
                         Prio.ITS)

        # add radar DOM data
        if self.__firstTime:
            self.__addRadarDOMData(compList, radarString, radarDOM, hitRate)
            self.__firstTime = False
        live.addExpected(radarName + "*DataCollectorMonitor-XXX+MainboardId",
                         radarDOM, Prio.ITS)
        live.addExpected(radarName + "*DataCollectorMonitor-XXX+HitRate",
                         hitRate, Prio.ITS)
        live.addExpected("radarDOMs", [(radarDOM, hitRate), ], Prio.EMAIL)

    def setUp(self):
        self.__firstTime = True

    def tearDown(self):
        self.__firstTime = False

    def testNotRun(self):
        compList = [MockComponent("stringHub", 1),
                    MockComponent("stringHub", 6),
                    MockComponent("inIceTrigger", 0),
                    MockComponent("iceTopTrigger", 0),
                    MockComponent("globalTrigger", 0),
                    MockComponent("eventBuilder", 0),
                    MockComponent("secondaryBuilders", 0)]

        orderNum = 1
        for c in compList:
            c.setOrder(orderNum)

        runset = MockRunSet(compList)
        #runset.startRunning()

        dashlog = MockLog()

        live = MockLiveMoni()

        rst = MyTaskManager(runset, dashlog, live, None,
                            RunOption.MONI_TO_LIVE)
        rst.start()

        for i in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread: break

            time.sleep(0.1)

        runset.stopRunning()
        rst.stop()

        self.failIf(c.wasUpdated(), "Rate thread was updated")
        self.failUnless(live.hasAllMoni(), "Monitoring data was not sent")

    def testRunOnce(self):
        radarDOM = RadarThread.DOM_MAP.keys()[0]
        radarString = RadarThread.DOM_MAP[radarDOM]

        compList = [MockComponent("stringHub", 1),
                    MockComponent("stringHub", radarString),
                    MockComponent("inIceTrigger", 0),
                    MockComponent("iceTopTrigger", 0),
                    MockComponent("globalTrigger", 0),
                    MockComponent("eventBuilder", 0),
                    MockComponent("secondaryBuilders", 0)]

        orderNum = 1
        for c in compList:
            c.setOrder(orderNum)

        runset = MockRunSet(compList)
        runset.startRunning()

        dashlog = MockLog()

        live = MockLiveMoni()

        hitRate = 12.34

        self.__loadExpected(live, compList, radarString, radarDOM, hitRate)

        rst = MyTaskManager(runset, dashlog, live, None,
                            RunOption.MONI_TO_LIVE)
        rst.triggerTimers()
        rst.start()

        for i in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread: break

            time.sleep(0.1)

        self.failUnless(c.wasUpdated(), "Rate thread was not updated")
        self.failUnless(live.hasAllMoni(), "Monitoring data was not sent")

        runset.stopRunning()
        rst.stop()

    def testRunTwice(self):
        radarDOM = RadarThread.DOM_MAP.keys()[0]
        radarString = RadarThread.DOM_MAP[radarDOM]

        compList = [MockComponent("stringHub", 1),
                    MockComponent("stringHub", radarString),
                    MockComponent("inIceTrigger", 0),
                    MockComponent("iceTopTrigger", 0),
                    MockComponent("globalTrigger", 0),
                    MockComponent("eventBuilder", 0),
                    MockComponent("secondaryBuilders", 0)]

        orderNum = 1
        for c in compList:
            c.setOrder(orderNum)

        runset = MockRunSet(compList)
        runset.startRunning()

        dashlog = MockLog()

        live = MockLiveMoni()

        hitRate = 12.34

        rst = MyTaskManager(runset, dashlog, live, None,
                            RunOption.MONI_TO_LIVE)

        self.__loadExpected(live, compList, radarString, radarDOM, hitRate)
        rst.triggerTimers()

        rst.start()

        for i in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread: break

            time.sleep(0.1)

        self.__loadExpected(live, compList, radarString, radarDOM, hitRate)
        dashlog.addExpected(MockLog.LEVEL_ERROR,
                            "Watchdog reports threshold components:\n" +
                            "    secondaryBuilders snBuilder.DiskAvailable" +
                            " below 1024 (value=0)")
        dashlog.addExpected(MockLog.LEVEL_ERROR,
                            "Run is unhealthy (%d checks left)" %
                            (WatchdogTask.HEALTH_METER_FULL - 1))

        rst.triggerTimers()

        for i in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread: break

            time.sleep(0.1)

        self.failUnless(c.wasUpdated(), "Rate thread was not updated")
        self.failUnless(live.hasAllMoni(), "Monitoring data was not sent")

        runset.stopRunning()
        rst.stop()

if __name__ == '__main__':
    unittest.main()
