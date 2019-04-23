#!/usr/bin/env python

import copy
import time
import unittest

from LiveImports import Prio
from RunOption import RunOption
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask

from DAQMocks import MockIntervalTimer, MockLiveMoni, MockLogger, MockRunSet


class MockTMMBeanClient(object):
    BEANBAG = {
        "stringHub": {
            "stringhub": {
                "NumberOfActiveChannels": 2,
                "NumberOfActiveAndTotalChannels": [1, 2],
                "TotalLBMOverflows": 20,
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
                "NumDispatchedData": 0
            },
            "snBuilder": {
                "NumDispatchedData": 0,
                "DiskAvailable": 0,
            },
        }
    }

    def __init__(self, name, num):
        self.__name = name
        self.__num = num

        self.__beanData = self.__createBeanData()

    def __str__(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def __createBeanData(self):
        if self.__name not in self.BEANBAG:
            raise Exception("No bean data found for %s" % self.__name)

        data = {}
        for b in self.BEANBAG[self.__name]:
            if b not in data:
                data[b] = {}
            for f in self.BEANBAG[self.__name][b]:
                data[b][f] = self.BEANBAG[self.__name][b][f]

        return data

    def check(self, beanName, fieldName):
        return beanName in self.__beanData and \
            fieldName in self.__beanData[beanName]

    def get(self, beanName, fieldName):
        if not self.check(beanName, fieldName):
            raise Exception("No %s data for bean %s field %s" %
                            (self, beanName, fieldName))

        return self.__beanData[beanName][fieldName]

    def get_attributes(self, beanName, fieldList):
        rtnMap = {}
        for f in fieldList:
            rtnMap[f] = self.get(beanName, f)
        return rtnMap

    def get_bean_fields(self, beanName):
        return list(self.__beanData[beanName].keys())

    def get_bean_names(self):
        return list(self.__beanData.keys())

    def get_dictionary(self):
        return copy.deepcopy(self.__beanData)

    def reload(self):
        pass


class MockTMComponent(object):
    def __init__(self, name, num):
        self.__name = name
        self.__num = num

        self.__order = None
        self.__updatedRates = False

        self.__mbean = MockTMMBeanClient(name, num)

    def __str__(self):
        return self.fullname

    def create_mbean_client(self):
        return self.__mbean

    @property
    def filename(self):
        return "%s-%d" % (self.__name, self.__num)

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    @property
    def is_builder(self):
        return self.__name.lower().endswith("builder")

    @property
    def is_source(self):
        return self.__name.lower().endswith("hub")

    @property
    def mbean(self):
        return self.__mbean

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    @property
    def order(self):
        return self.__order

    def set_order(self, num):
        self.__order = num

    def updateRates(self):
        self.__updatedRates = True

    def wasUpdated(self):
        return self.__updatedRates


class MockRunConfig(object):
    def __init__(self):
        pass

    @property
    def monitorPeriod(self):
        return None

    @property
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
    def __loadExpected(self, live, compList, hitRate, first=True):

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

        live.addExpected("secondaryBuilders-0*moniBuilder+NumDispatchedData",
                         0, Prio.ITS)
        live.addExpected("secondaryBuilders-0*snBuilder+NumDispatchedData",
                         0, Prio.ITS)
        live.addExpected("secondaryBuilders-0*snBuilder+DiskAvailable",
                         0, Prio.ITS)

        # add activeDOM data
        live.addExpected("missingDOMs", 1, Prio.ITS)
        lbmo_dict = {
            "count": 20,
            "runNumber": 123456,
        }
        if first:
            lbmo_dict["early_lbm"] = True
            match = True
        else:
            lbmo_dict["early_lbm"] = False
            lbmo_dict["recordingStartTime"] = "???",
            lbmo_dict["recordingStopTime"] = "???",
            match = False
        live.addExpected("LBMOcount", lbmo_dict, Prio.ITS, match)

        dom_dict = {
            "expectedDOMs": 2,
            "activeDOMs": 1,
            "missingDOMs": 1,
        }
        live.addExpected("dom_update", dom_dict,
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
            c.set_order(orderNum)

        runset = MockRunSet(compList)

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

        self.assertFalse(c.wasUpdated(), "Rate thread was updated")
        self.assertTrue(live.hasAllMoni(), "Monitoring data was not sent")

    def testRunOnce(self):
        compList = [MockTMComponent("stringHub", 1),
                    MockTMComponent("inIceTrigger", 0),
                    MockTMComponent("iceTopTrigger", 0),
                    MockTMComponent("globalTrigger", 0),
                    MockTMComponent("eventBuilder", 0),
                    MockTMComponent("secondaryBuilders", 0)]

        orderNum = 1
        for c in compList:
            c.set_order(orderNum)

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

        self.assertTrue(c.wasUpdated(), "Rate thread was not updated")
        self.assertTrue(live.hasAllMoni(), "Monitoring data was not sent")

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
            c.set_order(orderNum)

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

        self.assertTrue(live.hasAllMoni(), "Monitoring data was not sent")

        self.__loadExpected(live, compList, hitRate, first=False)
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

        self.assertTrue(c.wasUpdated(), "Rate thread was not updated")
        self.assertTrue(live.hasAllMoni(), "Monitoring data was not sent")

        runset.stopRunning()
        rst.stop()


if __name__ == '__main__':
    unittest.main()
