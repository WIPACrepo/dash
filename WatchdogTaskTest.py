#!/usr/bin/env python

import unittest

from WatchdogTask import WatchdogRule, WatchdogTask

from DAQMocks import MockComponent, MockIntervalTimer, MockLogger, \
     MockRunSet, MockTaskManager


class BadMatchRule(WatchdogRule):
    def init_data(self, data, thisComp, components):
        pass

    def matches(self, comp):
        raise Exception("FAIL")


class BadInitRule(WatchdogRule):
    def init_data(self, data, thisComp, components):
        raise Exception("FAIL")

    def matches(self, comp):
        return comp.name == "foo"


class BarRule(WatchdogRule):
    def __init__(self, checkVal):
        self.__checkVal = checkVal

    def init_data(self, data, thisComp, components):
        if self.__checkVal:
            data.add_input_value(thisComp, "barBean", "barFld")

    def matches(self, comp):
        return comp.name == "bar"


class FooRule(WatchdogRule):
    def __init__(self, testIn=True, testOut=True, testThresh=True):
        self.__testIn = testIn
        self.__testOut = testOut
        self.__testThresh = testThresh

    def init_data(self, data, thisComp, components):
        foo = None
        for c in components:
            if c.name == "foo":
                foo = c
                break
        if foo is None:
            raise Exception("Cannot find \"foo\" component")

        if self.__testIn:
            data.add_input_value(foo, "inBean", "inFld")
        if self.__testOut:
            data.add_output_value(foo, "outBean", "outFld")
        if self.__testThresh:
            data.add_threshold_value("threshBean", "threshFld", 10)

    def matches(self, comp):
        return comp.name == "foo"


class WatchdogTaskTest(unittest.TestCase):
    def __buildFoo(self):
        foo = MockComponent("foo", 1)
        foo.order = 1
        foo.mbean.addData("inBean", "inFld", 0)
        foo.mbean.addData("outBean", "outFld", 0)
        foo.mbean.addData("threshBean", "threshFld", 0)
        return foo

    def __buildBar(self, addBarBeans=False):
        bar = MockComponent("bar", 0)
        bar.order = 2
        if addBarBeans:
            bar.mbean.addData("barBean", "barFld", 0)

        return bar

    def __buildRunset(self, addBarBeans=False):
        comps = (self.__buildFoo(), self.__buildBar(addBarBeans=addBarBeans))

        return MockRunSet(comps)

    def __runTest(self, runset, rules, testIn, testOut, testThresh, testBoth):
        timer = MockIntervalTimer(WatchdogTask.name)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        logger = MockLogger("logger")

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(taskMgr, runset, logger, rules=rules)

        timer.trigger()
        tsk.check()
        tsk.wait_until_finished()

        endVal = WatchdogTask.HEALTH_METER_FULL
        if not testThresh:
            endVal += 1

        for i in range(0, endVal):
            health = WatchdogTask.HEALTH_METER_FULL - i
            if testThresh:
                health -= 1
            timer.trigger()

            if testThresh:
                logger.addExpectedRegexp(r"Watchdog reports threshold"
                                         r" components:.*")
            if i > 0:
                if testIn:
                    logger.addExpectedRegexp(r"Watchdog reports starved"
                                             r" components:.*")
                if (testOut and not testIn) or (testOut and testBoth):
                    logger.addExpectedRegexp(r"Watchdog reports stagnant"
                                             r" components:.*")
                if testIn or testOut or testThresh:
                    if health <= 0:
                        logger.addExpectedExact("Run is not healthy, stopping")
                    elif health % WatchdogTask.NUM_HEALTH_MSGS == 0:
                        logger.addExpectedExact("Run is unhealthy" +
                                                " (%d checks left)" % health)

            tsk.check()
            tsk.wait_until_finished()

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
        timer = MockIntervalTimer(WatchdogTask.name)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        foo = MockComponent("foo", 1)
        foo.order = 1

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        logger.addExpectedExact("Couldn't create watcher for unknown" +
                                " component %s#%d" % (foo.name, foo.num))

        WatchdogTask(taskMgr, runset, logger, period=None, rules=())

        logger.checkStatus(1)

    def testBadMatchRule(self):
        timer = MockIntervalTimer(WatchdogTask.name)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        foo = MockComponent("foo", 1)
        foo.order = 1

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        logger.addExpectedRegexp(r"Couldn't create watcher for component"
                                 r" %s#%d: .*" % (foo.name, foo.num))

        WatchdogTask(taskMgr, runset, logger, rules=(BadMatchRule(), ))

        logger.checkStatus(1)

    def testBadInitRule(self):

        foo = self.__buildFoo()

        rules = (BadInitRule(), )

        timer = MockIntervalTimer(WatchdogTask.name)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        logger = MockLogger("logger")

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(taskMgr, MockRunSet((foo, )), logger, rules=rules)

        logger.checkStatus(5)

        for i in range(1, 4):
            logger.addExpectedRegexp(r"Initialization failure #%d for"
                                     r" %s %s.*" %
                                     (i, foo.fullname, str(rules[0])))

            timer.trigger()
            tsk.check()
            tsk.wait_until_finished()

            logger.checkStatus(5)

    def testFooInputUnhealthy(self):
        testIn = True
        testOut = False
        testThresh = False
        addBarBeans = False

        runset = self.__buildRunset(addBarBeans=addBarBeans)

        rules = (FooRule(testIn, testOut, testThresh), BarRule(addBarBeans))

        self.__runTest(runset, rules, testIn, testOut, testThresh, False)

    def testFooOutputUnhealthy(self):
        testIn = False
        testOut = True
        testThresh = False
        addBarBeans = False

        runset = self.__buildRunset(addBarBeans=addBarBeans)

        rules = (FooRule(testIn, testOut, testThresh), BarRule(addBarBeans))

        self.__runTest(runset, rules, testIn, testOut, testThresh, False)

    def testFooThresholdUnhealthy(self):
        testIn = False
        testOut = False
        testThresh = True
        addBarBeans = False

        runset = self.__buildRunset(addBarBeans=addBarBeans)

        rules = (FooRule(testIn, testOut, testThresh), BarRule(addBarBeans))

        self.__runTest(runset, rules, testIn, testOut, testThresh, False)

    def testFooAllUnhealthy(self):
        testIn = True
        testOut = True
        testThresh = True
        addBarBeans = False

        runset = self.__buildRunset(addBarBeans=addBarBeans)

        rules = (FooRule(testIn, testOut, testThresh), BarRule(addBarBeans))

        self.__runTest(runset, rules, testIn, testOut, testThresh, False)

    def testFooUnhealthyWithBar(self):
        testIn = True
        testOut = False
        testThresh = False
        addBarBeans = True

        runset = self.__buildRunset(addBarBeans=addBarBeans)

        rules = (FooRule(testIn, testOut, testThresh), BarRule(addBarBeans))

        self.__runTest(runset, rules, testIn, testOut, testThresh, False)

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
        # sb.mbean.addData("tcalBuilder", "NumDispatchedData", 0)

        compList = [hub, iit, gt, eb, sb, ]

        num = 1
        for c in compList:
            c.order = num
            num += 1

        runset = MockRunSet(compList)

        self.__runTest(runset, None, True, True, True, True)

    def testLongStartup(self):
        timer = MockIntervalTimer(WatchdogTask.name)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        logger = MockLogger("logger")

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        foo = self.__buildFoo()

        rules = (FooRule(True, False, False), )

        max_health = WatchdogTask.HEALTH_METER_FULL + 6

        tsk = WatchdogTask(taskMgr, MockRunSet((foo, )), logger,
                           initial_health=max_health, rules=rules)

        timer.trigger()
        tsk.check()
        tsk.wait_until_finished()

        for health in range(max_health - 1, 0, -1):
            if health <= WatchdogTask.HEALTH_METER_FULL:
                logger.addExpectedRegexp(r"Watchdog reports starved"
                                         r" components:.*")
                if health < WatchdogTask.HEALTH_METER_FULL and \
                   ((health - 1) % WatchdogTask.NUM_HEALTH_MSGS) == 0:
                    if health - 1 == 0:
                        logger.addExpectedExact("Run is not healthy, stopping")
                    else:
                        logger.addExpectedRegexp(r"Run is unhealthy"
                                                 r" \(\d+ checks left\)")

            timer.trigger()

            tsk.check()
            tsk.wait_until_finished()

            logger.checkStatus(5)

if __name__ == '__main__':
    unittest.main()
