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

        foo = MockComponent("fooHub", 1)
        foo.mbean.addData("stringhub", "NumberOfActiveAndTotalChannels",
                          (numActive, numTotal))
        foo.mbean.addData("stringhub", "TotalLBMOverflows", numLBM)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = ActiveDOMsTask(taskMgr, runset, logger, live)

        data = {
            "activeDOMs": numActive,
            "expectedDOMs": numTotal,
            "missingDOMs": numTotal - numActive,
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

        live.addExpected("stringRateInfo", {'1': 50}, Prio.EMAIL)
        live.addExpected("stringRateLCInfo", {'1': 25}, Prio.EMAIL)
        live.addExpected("missingDOMs", numTotal - numActive, Prio.ITS)

        lbmo_dict = {
            "runNumber": runset.run_number(),
            "early_lbm": True,
            "count": 2,
        }
        live.addExpected("LBMOcount", lbmo_dict, Prio.ITS)

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

        foo = MockComponent("fooHub", 1)
        foo.mbean.addData("stringhub", "NumberOfActiveAndTotalChannels",
                          (numActive, numTotal))
        foo.mbean.addData("stringhub", "TotalLBMOverflows", numLBM)

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

        foo = MockComponent("fooHub", 1)
        foo.mbean.addData("stringhub", "NumberOfActiveAndTotalChannels",
                          (numActive, numTotal))
        foo.mbean.addData("stringhub", "TotalLBMOverflows", numLBM)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = ActiveDOMsTask(taskMgr, runset, logger, live)

        live.addExpected("missingDOMs", numTotal - numActive, Prio.EMAIL)

        rptTimer.trigger()
        left = tsk.check()
        self.assertEqual(rptTimer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (rptTimer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)
        live.hasAllMoni()

        foo.mbean.setData("stringhub", "NumberOfActiveAndTotalChannels",
                          Exception("Simulated error"))
        logger.addExpectedRegexp(r".*Simulated error.*")

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
