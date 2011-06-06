#!/usr/bin/env python

import unittest

from WatchdogTask import WatchdogRule, WatchdogTask

from DAQMocks import MockLogger

class MockTimer(object):
    def __init__(self, period):
        self.__period = period
        self.__timeLeft = period

    def reset(self):
        self.__timeLeft = self.__period

    def setTimeLeft(self, val):
        self.__timeLeft = val

    def timeLeft(self):
        return self.__timeLeft

class MockTaskManager(object):
    def __init__(self, timer):
        self.__timer = timer
        self.__error = False

    def createIntervalTimer(self, name, period):
        return self.__timer

    def hasError(self):
        return self.__error

    def setError(self):
        self.__error = True

class MockComponent(object):
    def __init__(self, name, num, order, beans=None):
        self.__name = name
        self.__num = num
        self.__order = order
        self.__beans = beans

    def __str__(self):
        if self.__num == 0:
            return self.__name
        return "Mock:%s#%d" % (self.__name, self.__num)

    def checkBeanField(self, beanName, fldName):
        if self.__beans is None:
            raise Exception("No beans available for \"%s\"" % self.fullName())
        if not self.__beans.has_key(beanName):
            raise Exception("Unknown \"%s\" bean \"%s\"" %
                            (self.fullName(), beanName))
        if not self.__beans[beanName].has_key(fldName):
            raise Exception("Unknown \"%s\" bean \"%s\" field \"%s\"" %
                            (self.fullName(), beanName, fldName))
        return self.__beans[beanName][fldName]

    def fullName(self): return "%s#%d" % (self.__name, self.__num)

    def getSingleBeanField(self, beanName, fldName):
        return self.checkBeanField(beanName, fldName)

    def getMultiBeanFields(self, beanName, fldList):
        results = {}
        for f in fldList:
            results[f] = self.checkBeanField(beanName, f)
        return results

    def isSource(self): return self.__name.find("Hub") > 0
    def isBuilder(self): return self.__name.find("Builder") > 0
    def name(self): return self.__name
    def num(self): return self.__num
    def order(self): return self.__order

class MockRunSet(object):
    def __init__(self, compList):
        self.__compList = compList[:]

    def components(self):
        return self.__compList[:]

class BadMatchRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        pass

    def matches(self, comp):
        raise Exception("FAIL")

class BadInitRule(WatchdogRule):
    def initData(self, data, thisComp, components):
        raise Exception("FAIL")

    def matches(self, comp):
        return comp.name() == "foo"

class BarRule(WatchdogRule):
    def __init__(self, checkVal):
        self.__checkVal = checkVal

    def initData(self, data, thisComp, components):
        if self.__checkVal:
            data.addInputValue(thisComp, "barBean", "barFld")

    def matches(self, comp):
        return comp.name() == "bar"

class FooRule(WatchdogRule):
    def __init__(self, testIn=True, testOut=True, testThresh=True):
        self.__testIn = testIn
        self.__testOut = testOut
        self.__testThresh = testThresh

    def initData(self, data, thisComp, components):
        bar = None
        for c in components:
            if c.name() == "bar":
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
        return comp.name() == "foo"

class WatchdogTaskTest(unittest.TestCase):
    def __runFooTest(self, testIn, testOut, testThresh, barBeans=None):
        fooBeans = {"inBean" : {"inFld" : 0},
                    "outBean" : {"outFld" : 0},
                    "threshBean" : {"threshFld" : 0},
                    }

        foo = MockComponent("foo", 1, 1, beans=fooBeans)
        bar = MockComponent("bar", 0, 1, beans=barBeans)
        runset = MockRunSet([foo, bar, ])

        rules=(FooRule(testIn, testOut, testThresh),
               BarRule(barBeans is not None))
        self.__runTest(runset, rules, testIn, testOut, testThresh, False)

    def __runTest(self, runset, rules, testIn, testOut, testThresh, testBoth):
        timer = MockTimer(1)
        taskMgr = MockTaskManager(timer)

        logger = MockLogger("logger")

        #from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(taskMgr, runset, logger, rules=rules)

        timer.setTimeLeft(0)
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
            timer.setTimeLeft(0)

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
            self.failUnless(taskMgr.hasError(),
                            "TaskManager is not error state")

        tsk.close()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testUnknownComp(self):
        timer = MockTimer(1)
        taskMgr = MockTaskManager(timer)

        foo = MockComponent("foo", 1, 1)
        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        logger.addExpectedExact("Couldn't create watcher for unknown" +
                                " component %s#%d" % (foo.name(), foo.num()))

        tsk = WatchdogTask(taskMgr, runset, logger, period=None, rules=())

        logger.checkStatus(1)

    def testBadMatchRule(self):
        timer = MockTimer(1)
        taskMgr = MockTaskManager(timer)

        foo = MockComponent("foo", 1, 1)
        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        logger.addExpectedRegexp("Couldn't create watcher for component" +
                                 " %s#%d: .*" % (foo.name(), foo.num()))

        tsk = WatchdogTask(taskMgr, runset, logger,
                           rules=(BadMatchRule(), ))

        logger.checkStatus(1)

    def testBadInitRule(self):
        timer = MockTimer(1)
        taskMgr = MockTaskManager(timer)

        fooBeans = {"inBean" : {"inFld" : 0},
                    "outBean" : {"outFld" : 0},
                    "threshBean" : {"threshFld" : 0},
                    }

        foo = MockComponent("foo", 1, 1, beans=fooBeans)
        runset = MockRunSet([foo, ])

        rules = (BadInitRule(), )

        timer = MockTimer(1)
        taskMgr = MockTaskManager(timer)

        logger = MockLogger("logger")

        #from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(taskMgr, runset, logger, rules=rules)

        logger.checkStatus(5)

        for i in range(1, 4):
            logger.addExpectedExact("Initialization failure #%d for %s %s" %
                                    (i, foo.fullName(), str(rules[0])))

            timer.setTimeLeft(0)
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
        barBeans = {"barBean" : {"barFld" : 0}, }
        self.__runFooTest(True, False, False, barBeans)

    def testStandard(self):
        stringBeans = {"sender" : {"NumHitsReceived" : 0,
                                   "NumReadoutRequestsReceived" : 0,
                                   "NumReadoutsSent" : 0,
                                   },
                       }
        hub = MockComponent("stringHub", 0, 1, beans=stringBeans)

        iiTrigBeans = {"stringHit" : {"RecordsReceived" : 0,
                                      },
                       "trigger" : {"RecordsSent" : 0,
                                    },
                       }
        iit = MockComponent("inIceTrigger", 0, 1, beans=iiTrigBeans)

        gTrigBeans = {"trigger" : {"RecordsReceived" : 0,
                                    },
                       "glblTrig" : {"RecordsSent" : 0,
                                     },
                      }
        gt = MockComponent("globalTrigger", 0, 1, beans=gTrigBeans)

        evtBldrBeans = {"backEnd" : {"NumReadoutsReceived" : 0,
                                     "NumTriggerRequestsReceived" : 0,
                                     "NumEventsSent" : 0,
                                     "NumBadEvents" : 0,
                                     "DiskAvailable" : 0,
                                     },
                        }
        eb = MockComponent("eventBuilder", 0, 1, beans=evtBldrBeans)

        secBldrBeans = {"snBuilder" : {"TotalDispatchedData" : 0,
                                       "DiskAvailable" : 0,
                                     },
                        "moniBuilder" : {"TotalDispatchedData" : 0,
                                     },
                        #"tcalBuilder" : {"TotalDispatchedData" : 0,
                        #             },
                        }
        sb = MockComponent("secondaryBuilders", 0, 1, beans=secBldrBeans)

        runset = MockRunSet([hub, iit, gt, eb, sb, ])

        self.__runTest(runset, None, True, True, True, True)

if __name__ == '__main__':
    unittest.main()
