#!/usr/bin/env python

import time
import unittest

from LiveImports import Prio
from RunOption import RunOption
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask

from DAQMocks import MockIntervalTimer, MockLiveMoni, MockLogger, MockRunSet


class MockTMComponent(object):
    BEANBAG = {
        "stringHub": {
            "stringhub": {
                "NumberOfActiveChannels": 2,
                "NumberOfActiveAndTotalChannels": [1, 2],
                "TotalLBMOverflows": 20,
                "HitRate": 50.,
                "HitRateLC": 25.0
            },
            "sender": {
                "NumHitsReceived": 0,
                "NumReadoutRequestsReceived": 0,
                "NumReadoutsSent": 0,
            },
        },
        "iceTopTrigger": {
            "icetopHit": {
                "RecordsReceived": 0
            },
            "trigger": {
                "RecordsSent": 0
            },
        },
        "inIceTrigger": {
            "stringHit": {
                "RecordsReceived": 0
            },
            "trigger": {
                "RecordsSent": 0
            },
        },
        "globalTrigger": {
            "trigger": {
                "RecordsReceived": 0
            },
            "glblTrig": {
                "RecordsSent": 0
            },
        },
        "eventBuilder": {
            "backEnd": {
                "DiskAvailable": 2560,
                "NumBadEvents": 0,
                "NumEventsDispatched": 0,
                "NumEventsSent": 0,
                "NumReadoutsReceived": 0,
                "NumTriggerRequestsReceived": 0,
                "NumBytesWritten": 0
            },
        },
        "secondaryBuilders": {
            "moniBuilder": {
                "TotalDispatchedData": 0
            },
            "snBuilder": {
                "TotalDispatchedData": 0,
                "DiskAvailable": 0,
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
        if not self.__name in self.BEANBAG:
            raise Exception("No bean data found for %s" % self)

        data = {}
        for b in self.BEANBAG[self.__name]:
            if not b in data:
                data[b] = {}
            for f in self.BEANBAG[self.__name][b]:
                data[b][f] = self.BEANBAG[self.__name][b][f]

        return data

    def addBeanData(self, beanName, fieldName, value):
        if self.checkBeanField(beanName, fieldName):
            raise Exception("Value for %c bean %s field %s already exists" %
                            (self, beanName, fieldName))

        if not beanName in self.__beanData:
            self.__beanData[beanName] = {}
        self.__beanData[beanName][fieldName] = value

    def checkBeanField(self, beanName, fieldName):
        return beanName in self.__beanData and \
            fieldName in self.__beanData[beanName]

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

    def reloadBeanInfo(self):
        pass

    def name(self):
        return self.__name

    def num(self):
        return self.__num

    def order(self):
        return self.__order

    def reset(self):
        self.__updatedRates = False

    def setOrder(self, num):
        self.__order = num

    def updateRates(self):
        self.__updatedRates = True

    def wasUpdated(self):
        return self.__updatedRates


class MockRunConfig(object):
    def __init__(self):
        pass

    def monitorPeriod(self):
        return None

    def watchdogPeriod(self):
        return None


class MyTaskManager(TaskManager):
    def __init__(self, runset, dashlog, live, runDir, runCfg, moniType):
        self.__timerDict = {}
        super(MyTaskManager, self).__init__(runset, dashlog, live, runDir,
                                            runCfg, moniType)

    def createIntervalTimer(self, name, period):
        timer = MockIntervalTimer(name)
        self.__timerDict[name] = timer
        return timer

    def triggerTimers(self):
        for k in self.__timerDict:
            self.__timerDict[k].trigger()


class TaskManagerTest(unittest.TestCase):
    def __loadExpected(self, live, compList, hitRate):

        # add monitoring data
        live.addExpected("stringHub-1*sender+NumHitsReceived",
                         0, Prio.ITS)
        live.addExpected("stringHub-1*sender+NumReadoutRequestsReceived",
                         0, Prio.ITS)
        live.addExpected("stringHub-1*sender+NumReadoutsSent", 0, Prio.ITS)
        live.addExpected("stringHub-1*stringhub+NumberOfActiveChannels",
                         2, Prio.ITS)
        live.addExpected("stringHub-1*stringhub+TotalLBMOverflows",
                         20, Prio.ITS)
        live.addExpected("stringHub-1*stringhub+HitRate", 50, Prio.ITS)
        live.addExpected("stringHub-1*stringhub+HitRateLC", 25, Prio.ITS)
        live.addExpected(
            "stringHub-1*stringhub+NumberOfActiveAndTotalChannels",
            [1, 2], Prio.ITS)

        live.addExpected("iceTopTrigger-0*icetopHit+RecordsReceived",
                         0, Prio.ITS)
        live.addExpected("iceTopTrigger-0*trigger+RecordsSent", 0, Prio.ITS)
        live.addExpected("inIceTrigger-0*stringHit+RecordsReceived",
                         0, Prio.ITS)
        live.addExpected("inIceTrigger-0*trigger+RecordsSent", 0, Prio.ITS)
        live.addExpected("globalTrigger-0*trigger+RecordsReceived",
                         0, Prio.ITS)

        live.addExpected("globalTrigger-0*glblTrig+RecordsSent",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumTriggerRequestsReceived",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumReadoutsReceived",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumEventsSent",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumEventsDispatched",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumBadEvents",
                         0, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+DiskAvailable",
                         2560, Prio.ITS)
        live.addExpected("eventBuilder-0*backEnd+NumBytesWritten",
                         0, Prio.ITS)

        live.addExpected("secondaryBuilders-0*moniBuilder+TotalDispatchedData",
                         0, Prio.ITS)
        live.addExpected("secondaryBuilders-0*snBuilder+TotalDispatchedData",
                         0, Prio.ITS)
        live.addExpected("secondaryBuilders-0*snBuilder+DiskAvailable",
                         0, Prio.ITS)

        # add activeDOM data
        live.addExpected("activeDOMs", 1, Prio.ITS)
        live.addExpected("expectedDOMs", 2, Prio.ITS)
        live.addExpected("missingDOMs", 1, Prio.ITS)
        live.addExpected("total_rate", 50, Prio.ITS)
        live.addExpected("total_ratelc", 25, Prio.ITS)
        live.addExpected("LBMOverflows", {"1": 20},
                         Prio.ITS)
        live.addExpected("stringDOMsInfo", {"1": (1, 2)},
                         Prio.EMAIL)

        live.addExpected("dom_update", {"expectedDOMs": 2, "total_ratelc": 25.0,
                                        "total_rate": 50.0, "activeDOMs": 1,
                                        "missingDOMs": 1},
                         Prio.ITS)

    def setUp(self):
        self.__firstTime = True

    def tearDown(self):
        self.__firstTime = False

    def testNotRun(self):
        compList = [MockTMComponent("stringHub", 1),
                    MockTMComponent("stringHub", 6),
                    MockTMComponent("inIceTrigger", 0),
                    MockTMComponent("iceTopTrigger", 0),
                    MockTMComponent("globalTrigger", 0),
                    MockTMComponent("eventBuilder", 0),
                    MockTMComponent("secondaryBuilders", 0)]

        orderNum = 1
        for c in compList:
            c.setOrder(orderNum)

        runset = MockRunSet(compList)
        #runset.startRunning()

        dashlog = MockLogger("dashlog")

        live = MockLiveMoni()

        runCfg = MockRunConfig()

        rst = MyTaskManager(runset, dashlog, live, None, runCfg,
                            RunOption.MONI_TO_LIVE)
        rst.start()

        for _ in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread:
                break

            time.sleep(0.1)

        runset.stopRunning()
        rst.stop()

        self.failIf(c.wasUpdated(), "Rate thread was updated")
        self.failUnless(live.hasAllMoni(), "Monitoring data was not sent")

    def testRunOnce(self):
        compList = [MockTMComponent("stringHub", 1),
                    MockTMComponent("inIceTrigger", 0),
                    MockTMComponent("iceTopTrigger", 0),
                    MockTMComponent("globalTrigger", 0),
                    MockTMComponent("eventBuilder", 0),
                    MockTMComponent("secondaryBuilders", 0)]

        orderNum = 1
        for c in compList:
            c.setOrder(orderNum)

        runset = MockRunSet(compList)
        runset.startRunning()

        dashlog = MockLogger("dashlog")

        live = MockLiveMoni()

        runCfg = MockRunConfig()

        hitRate = 12.34

        self.__loadExpected(live, compList, hitRate)

        rst = MyTaskManager(runset, dashlog, live, None, runCfg,
                            RunOption.MONI_TO_LIVE)

        dashlog.addExpectedExact(("\t%d physics events (%.2f Hz)," +
                                  " %d moni events, %d SN events, %d tcals") %
                                 runset.getRates())

        rst.triggerTimers()
        rst.start()

        for _ in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread:
                break

            time.sleep(0.1)

        self.failUnless(c.wasUpdated(), "Rate thread was not updated")
        self.failUnless(live.hasAllMoni(), "Monitoring data was not sent")

        runset.stopRunning()
        rst.stop()

    def testRunTwice(self):
        compList = [MockTMComponent("stringHub", 1),
                    MockTMComponent("inIceTrigger", 0),
                    MockTMComponent("iceTopTrigger", 0),
                    MockTMComponent("globalTrigger", 0),
                    MockTMComponent("eventBuilder", 0),
                    MockTMComponent("secondaryBuilders", 0)]

        orderNum = 1
        for c in compList:
            c.setOrder(orderNum)

        runset = MockRunSet(compList)
        runset.startRunning()

        dashlog = MockLogger("dashlog")

        live = MockLiveMoni()

        runCfg = MockRunConfig()

        hitRate = 12.34

        rst = MyTaskManager(runset, dashlog, live, None, runCfg,
                            RunOption.MONI_TO_LIVE)

        self.__loadExpected(live, compList, hitRate)

        dashlog.addExpectedExact(("\t%d physics events (%.2f Hz)," +
                                  " %d moni events, %d SN events, %d tcals") %
                                 runset.getRates())

        rst.triggerTimers()

        rst.start()

        for _ in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread:
                break

            time.sleep(0.1)

        self.__loadExpected(live, compList, hitRate)
        dashlog.addExpectedExact("Watchdog reports threshold components:\n" +
                                 "    secondaryBuilders" +
                                 " snBuilder.DiskAvailable below 1024" +
                                 " (value=0)")
        dashlog.addExpectedExact("Run is unhealthy (%d checks left)" %
                                 (WatchdogTask.HEALTH_METER_FULL - 1))
        dashlog.addExpectedExact(("\t%d physics events (%.2f Hz)," +
                                  " %d moni events, %d SN events, %d tcals") %
                                 runset.getRates())

        rst.triggerTimers()

        for i in range(20):
            waitForThread = False
            for c in compList:
                if not c.wasUpdated():
                    waitForThread = True
                if not live.hasAllMoni():
                    waitForThread = True

            if not waitForThread:
                break

            time.sleep(0.1)

        self.failUnless(c.wasUpdated(), "Rate thread was not updated")
        self.failUnless(live.hasAllMoni(), "Monitoring data was not sent")

        runset.stopRunning()
        rst.stop()

if __name__ == '__main__':
    unittest.main()
