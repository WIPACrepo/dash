#!/usr/bin/env python

import datetime, unittest

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
        rptTimer = MockIntervalTimer("ActiveReport")
        domTimer = MockIntervalTimer("ActiveDOM")

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(rptTimer)
        taskMgr.addIntervalTimer(domTimer)

        numActive = 12
        numTotal = 20
        numLBM = 2

        foo = MockComponent("fooHub", 1)
        foo.addBeanData("stringhub", "NumberOfActiveAndTotalChannels",
                        (numActive, numTotal))
        foo.addBeanData("stringhub", "TotalLBMOverflows", numLBM)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = ActiveDOMsTask(taskMgr, runset, logger, live)

        live.addExpected("activeDOMs", numActive,  Prio.ITS)
        live.addExpected("expectedDOMs", numTotal,  Prio.ITS)

        rptTimer.trigger()
        left = tsk.check()
        self.assertEqual(rptTimer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (rptTimer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)

        live.addExpected("stringDOMsInfo", {'1' : (numActive, numTotal)},
                         Prio.EMAIL)
        live.addExpected("LBMOverflows", {'1' : numLBM},
                         Prio.ITS)

        domTimer.trigger()
        left = tsk.check()
        self.assertEqual(rptTimer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (rptTimer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)

        tsk.close()

    def testNoLive(self):
        rptTimer = MockIntervalTimer("ActiveReport")
        domTimer = MockIntervalTimer("ActiveDOM")

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(rptTimer)
        taskMgr.addIntervalTimer(domTimer)

        numActive = 12
        numTotal = 20
        numLBM = 2

        foo = MockComponent("fooHub", 1)
        foo.addBeanData("stringhub", "NumberOfActiveAndTotalChannels",
                        (numActive, numTotal))
        foo.addBeanData("stringhub", "TotalLBMOverflows", numLBM)

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

if __name__ == '__main__':
    unittest.main()
