#!/usr/bin/env python

import unittest

from ActiveDOMsTask import ActiveDOMsTask
from LiveImports import Prio

from DAQMocks import MockComponent, MockIntervalTimer, MockLiveMoni, \
     MockLogger, MockRunSet, MockTaskManager


class ActiveDOMsTaskTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testGood(self):
        rptTimer = MockIntervalTimer(ActiveDOMsTask.REPORT_NAME)
        domTimer = MockIntervalTimer(ActiveDOMsTask.NAME)

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(rptTimer)
        taskMgr.addIntervalTimer(domTimer)

        numActive = 12
        numTotal = 20
        numLBM = 2
        hit_rate = 50.0
        hit_rate_lc = 25.0

        foo = MockComponent("fooHub", 1)
        foo.addBeanData("stringhub", "NumberOfActiveAndTotalChannels",
                        (numActive, numTotal))
        foo.addBeanData("stringhub", "TotalLBMOverflows", numLBM)
        foo.addBeanData("stringhub", "HitRate", hit_rate)
        foo.addBeanData("stringhub", "HitRateLC", hit_rate_lc)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = ActiveDOMsTask(taskMgr, runset, logger, live)

        data = {
            "activeDOMs": numActive,
            "expectedDOMs": numTotal,
            "missingDOMs": numTotal - numActive,
            "total_rate": hit_rate,
            "total_ratelc": hit_rate_lc,
        }

        for key in data:
            live.addExpected(key, data[key], Prio.EMAIL)

        live.addExpected("dom_update", data, Prio.ITS)

        rptTimer.trigger()
        left = tsk.check()
        self.assertEqual(rptTimer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (rptTimer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)
        live.hasAllMoni()

        live.addExpected("stringDOMsInfo", {'1': (numActive, numTotal)},
                         Prio.EMAIL)
        live.addExpected("stringRateInfo", {'1': 50},
                         Prio.EMAIL)
        live.addExpected("stringRateLCInfo", {'1': 25},
                         Prio.EMAIL)
        live.addExpected("LBMOverflows", {'1': numLBM},
                         Prio.ITS)
        live.addExpected("activeDOMs", numActive,  Prio.ITS)
        live.addExpected("expectedDOMs", numTotal,  Prio.ITS)
        live.addExpected("missingDOMs", numTotal - numActive,  Prio.ITS)
        live.addExpected("total_rate", hit_rate, Prio.ITS)
        live.addExpected("total_ratelc", hit_rate_lc, Prio.ITS)

        domTimer.trigger()
        left = tsk.check()
        self.assertEqual(rptTimer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (rptTimer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)
        live.hasAllMoni()

        tsk.close()

    def testNoLive(self):
        rptTimer = MockIntervalTimer(ActiveDOMsTask.REPORT_NAME)
        domTimer = MockIntervalTimer(ActiveDOMsTask.NAME)

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(rptTimer)
        taskMgr.addIntervalTimer(domTimer)

        numActive = 12
        numTotal = 20
        numLBM = 2
        hit_rate = 50.0
        hit_rate_lc = 25.0

        foo = MockComponent("fooHub", 1)
        foo.addBeanData("stringhub", "NumberOfActiveAndTotalChannels",
                        (numActive, numTotal))
        foo.addBeanData("stringhub", "TotalLBMOverflows", numLBM)
        foo.addBeanData("stringhub", "HitRate", hit_rate)
        foo.addBeanData("stringhub", "HitRateLC", hit_rate_lc)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        live = None

        tsk = ActiveDOMsTask(taskMgr, runset, logger, live)

        rptTimer.trigger()
        left = tsk.check()
        self.assertEqual(tsk.MAX_TASK_SECS, left,
                         "Expected %d seconds, not %d" %
                         (tsk.MAX_TASK_SECS, left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)

        domTimer.trigger()
        left = tsk.check()
        self.assertEqual(tsk.MAX_TASK_SECS, left,
                         "Expected %d seconds, not %d" %
                         (tsk.MAX_TASK_SECS, left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)

        tsk.reset()

        tsk.close()

    def testFail(self):
        rptTimer = MockIntervalTimer(ActiveDOMsTask.REPORT_NAME)
        domTimer = MockIntervalTimer(ActiveDOMsTask.NAME)

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(rptTimer)
        taskMgr.addIntervalTimer(domTimer)

        numActive = 12
        numTotal = 20
        numLBM = 2
        hit_rate = 50.0
        hit_rate_lc = 25.0

        foo = MockComponent("fooHub", 1)
        foo.addBeanData("stringhub", "NumberOfActiveAndTotalChannels",
                        (numActive, numTotal))
        foo.addBeanData("stringhub", "TotalLBMOverflows", numLBM)
        foo.addBeanData("stringhub", "HitRate", hit_rate)
        foo.addBeanData("stringhub", "HitRateLC", hit_rate_lc)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = ActiveDOMsTask(taskMgr, runset, logger, live)

        live.addExpected("activeDOMs", numActive,  Prio.EMAIL)
        live.addExpected("expectedDOMs", numTotal,  Prio.EMAIL)
        live.addExpected("missingDOMs", numTotal - numActive,  Prio.EMAIL)
        live.addExpected("total_rate", hit_rate, Prio.EMAIL)
        live.addExpected("total_ratelc", hit_rate_lc, Prio.EMAIL)

        rptTimer.trigger()
        left = tsk.check()
        self.assertEqual(rptTimer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (rptTimer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)
        live.hasAllMoni()

        live.addExpected("stringDOMsInfo", {'1': (numActive, numTotal)},
                         Prio.EMAIL)
        live.addExpected("stringRateInfo", {'1': 50},
                         Prio.EMAIL)
        live.addExpected("stringRateLCInfo", {'1': 25},
                         Prio.EMAIL)
        live.addExpected("LBMOverflows", {'1': numLBM},
                         Prio.ITS)

        foo.setBeanData("stringhub", "NumberOfActiveAndTotalChannels",
                        Exception("Simulated error"))

        live.addExpected("activeDOMs", numActive,  Prio.ITS)
        live.addExpected("expectedDOMs", numTotal,  Prio.ITS)
        live.addExpected("missingDOMs", numTotal - numActive,  Prio.EMAIL)
        live.addExpected("total_rate", hit_rate, Prio.ITS)
        live.addExpected("total_ratelc", hit_rate_lc, Prio.ITS)

        domTimer.trigger()
        left = tsk.check()
        self.assertEqual(rptTimer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (rptTimer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)
        live.hasAllMoni()

        tsk.close()

if __name__ == '__main__':
    unittest.main()
