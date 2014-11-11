#!/usr/bin/env python

import unittest

from TriggerCountTask import TriggerCountTask
from LiveImports import Prio

from DAQMocks import MockComponent, MockIntervalTimer, MockLiveMoni, \
     MockLogger, MockRunSet, MockTaskManager


class MockGlobalTrigger(MockComponent):
    def __init__(self):
        self.__moniCounts = None

        super(MockGlobalTrigger, self).__init__("globalTrigger")

    def setMoniCounts(self, mcdict):
        self.__moniCounts = mcdict

    def getMoniCounts(self):
        return self.__moniCounts

class TriggerCountTaskTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testGood(self):
        timer = MockIntervalTimer(TriggerCountTask.NAME)

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        foo = MockComponent("fooHub", 1)
        gtrig = MockGlobalTrigger()

        runset = MockRunSet([foo, gtrig, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = TriggerCountTask(taskMgr, runset, logger, live)

        timer.trigger()
        left = tsk.check()
        self.assertEqual(timer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (timer.waitSecs(), left))

        tsk.waitUntilFinished()

        rate_dict = {"sourceid": 1,
                     "configid": 2,
                     "trigid": 3,
                     "runNumber": 4,
                     "recordingStartTime": 5,
                     "recordingStopTime": 6,
                     "value": 7,
                     "version": 0,
        }
        gtrig.setMoniCounts(rate_dict)
        live.addExpected("trigger_rate", rate_dict, 444)
        logger.checkStatus(4)

        tsk.close()

if __name__ == '__main__':
    unittest.main()
