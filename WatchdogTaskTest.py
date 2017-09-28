#!/usr/bin/env python

import unittest

from WatchdogTask import WatchdogRule, WatchdogTask

from DAQMocks import MockComponent, MockIntervalTimer, MockLogger, \
     MockRunSet, MockTaskManager


class BadMatchRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        pass

    def matches(self, comp):
        raise Exception("FAIL")


class BadInitRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        raise Exception("FAIL")

    def matches(self, comp):
        return comp.name == "foo"


class BarRule(WatchdogRule):
    def __init__(self, checkVal):
        self.__checkVal = checkVal

    def initData(self, data, thisComp, components):
        if self.__checkVal:
            data.addInputValue(thisComp, "barBean", "barFld")

    def matches(self, comp):
        return comp.name == "bar"


class FooRule(WatchdogRule):
    def __init__(self, testIn=True, testOut=True, testThresh=True):
        self.__testIn = testIn
        self.__testOut = testOut
        self.__testThresh = testThresh

    def initData(self, data, thisComp, components):
        bar = None
        for c in components:
            if c.name == "bar":
                bar = c
                break
        if bar is None:
            raise Exception("Cannot find \"bar\" component")

        if self.__testIn:
            data.addInputValue(bar, "inBean", "inFld")
        if self.__testOut:
            data.addOutputValue(bar, "outBean", "outFld")
        if self.__testThresh:
            data.addThresholdValue("threshBean", "threshFld", 10)

    def matches(self, comp):
        return comp.name == "foo"


class WatchdogTaskTest(unittest.TestCase):
    def __runFooTest(self, testIn, testOut, testThresh, addBarBeans=False):
        foo = MockComponent("foo", 1)
        foo.setOrder(1)
        foo.mbean.addData("inBean", "inFld", 0)
        foo.mbean.addData("outBean", "outFld", 0)
        foo.mbean.addData("threshBean", "threshFld", 0)

        bar = MockComponent("bar", 0)
        bar.setOrder(2)
        if addBarBeans:
            bar.mbean.addData("barBean", "barFld", 0)

        runset = MockRunSet([foo, bar, ])

        rules = (FooRule(testIn, testOut, testThresh),
                 BarRule(addBarBeans))
        self.__runTest(runset, rules, testIn, testOut, testThresh, False)

    def __runTest(self, runset, rules, testIn, testOut, testThresh, testBoth):
        timer = MockIntervalTimer(WatchdogTask.NAME)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        logger = MockLogger("logger")

        #from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(taskMgr, runset, logger, rules=rules)

        timer.trigger()
        tsk.check()
        tsk.waitUntilFinished()

        endVal = WatchdogTask.HEALTH_METER_FULL
        if not testThresh:
            endVal += 1

        for i in range(0, endVal):
            #print "== Check %d" % i
            health = WatchdogTask.HEALTH_METER_FULL - i
            if testThresh:
                health -= 1
            timer.trigger()

            if testThresh:
                logger.addExpectedRegexp("Watchdog reports threshold" +
                                         " components:.*")
            if i > 0:
                if testIn:
                    logger.addExpectedRegexp("Watchdog reports starved" +
                                             " components:.*")
                if (testOut and not testIn) or (testOut and testBoth):
                    logger.addExpectedRegexp("Watchdog reports stagnant" +
                                             " components:.*")
                if testIn or testOut or testThresh:
                    if health <= 0:
                        logger.addExpectedExact("Run is not healthy, stopping")
                    elif health % WatchdogTask.NUM_HEALTH_MSGS == 0:
                        logger.addExpectedExact("Run is unhealthy" +
                                                " (%d checks left)" % health)

            tsk.check()
            tsk.waitUntilFinished()

            logger.checkStatus(4)

        if testIn or testOut or testThresh:
            self.assertTrue(taskMgr.hasError(),
                            "TaskManager is not error state")

        tsk.close()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testUnknownComp(self):
        timer = MockIntervalTimer(WatchdogTask.NAME)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        foo = MockComponent("foo", 1)
        foo.setOrder(1)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        logger.addExpectedExact("Couldn't create watcher for unknown" +
                                " component %s#%d" % (foo.name, foo.num))

        WatchdogTask(taskMgr, runset, logger, period=None, rules=())

        logger.checkStatus(1)

    def testBadMatchRule(self):
        timer = MockIntervalTimer(WatchdogTask.NAME)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        foo = MockComponent("foo", 1)
        foo.setOrder(1)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        logger.addExpectedRegexp("Couldn't create watcher for component" +
                                 " %s#%d: .*" % (foo.name, foo.num))

        WatchdogTask(taskMgr, runset, logger, rules=(BadMatchRule(), ))

        logger.checkStatus(1)

    def testBadInitRule(self):
        foo = MockComponent("foo", 1)
        foo.setOrder(1)
        foo.mbean.addData("inBean", "inFld", 0)
        foo.mbean.addData("outBean", "outFld", 0)
        foo.mbean.addData("threshBean", "threshFld", 0)

        runset = MockRunSet([foo, ])

        rules = (BadInitRule(), )

        timer = MockIntervalTimer(WatchdogTask.NAME)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        logger = MockLogger("logger")

        #from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(taskMgr, runset, logger, rules=rules)

        logger.checkStatus(5)

        for i in range(1, 4):
            logger.addExpectedRegexp("Initialization failure #%d for %s %s.*" %
                                     (i, foo.fullname, str(rules[0])))

            timer.trigger()
            tsk.check()
            tsk.waitUntilFinished()

            logger.checkStatus(5)

    def testFooInputUnhealthy(self):
        self.__runFooTest(True, False, False)

    def testFooOutputUnhealthy(self):
        self.__runFooTest(False, True, False)

    def testFooThresholdUnhealthy(self):
        self.__runFooTest(False, False, True)

    def testFooAllUnhealthy(self):
        self.__runFooTest(True, True, True)

    def testFooUnhealthyWithBar(self):
        self.__runFooTest(True, False, False, addBarBeans=True)

    def testStandard(self):
        hub = MockComponent("stringHub", 0, 1)
        hub.mbean.addData("sender", "NumHitsReceived", 0)
        hub.mbean.addData("sender", "NumReadoutRequestsReceived", 0)
        hub.mbean.addData("sender", "NumReadoutsSent", 0)

        iit = MockComponent("inIceTrigger", 0, 1)
        iit.mbean.addData("stringHit", "RecordsReceived", 0)
        iit.mbean.addData("trigger", "RecordsSent", 0)

        gt = MockComponent("globalTrigger", 0, 1)
        gt.mbean.addData("trigger", "RecordsReceived", 0)
        gt.mbean.addData("glblTrig", "RecordsSent", 0)

        eb = MockComponent("eventBuilder", 0, 1)
        eb.mbean.addData("backEnd", "NumReadoutsReceived", 0)
        eb.mbean.addData("backEnd", "NumTriggerRequestsReceived", 0)
        eb.mbean.addData("backEnd", "NumEventsDispatched", 0)
        eb.mbean.addData("backEnd", "NumEventsSent", 0)
        eb.mbean.addData("backEnd", "NumBadEvents", 0)
        eb.mbean.addData("backEnd", "DiskAvailable", 0)

        sb = MockComponent("secondaryBuilders", 0, 1)
        sb.mbean.addData("snBuilder", "NumDispatchedData", 0)
        sb.mbean.addData("snBuilder", "DiskAvailable", 0)
        sb.mbean.addData("moniBuilder", "NumDispatchedData", 0)
        #sb.mbean.addData("tcalBuilder", "NumDispatchedData", 0)

        compList = [hub, iit, gt, eb, sb, ]

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runset = MockRunSet(compList)

        self.__runTest(runset, None, True, True, True, True)

if __name__ == '__main__':
    unittest.main()
