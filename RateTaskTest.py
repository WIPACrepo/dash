#!/usr/bin/env python

import datetime
import unittest

from RateTask import RateTask
from LiveImports import Prio

from DAQMocks import MockComponent, MockIntervalTimer, \
     MockLogger, MockRunSet, MockTaskManager


class RateTaskTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testGood(self):
        timer = MockIntervalTimer("Rate")

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        foo = MockComponent("fooHub", 1)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")

        tsk = RateTask(taskMgr, runset, logger)

        logger.addExpectedRegexp(r"\t\d+ physics events \(\d+\.\d+ Hz\), \d+ moni" +
                                 r" events, \d+ SN events, \d+ tcals")

        timer.trigger()
        left = tsk.check()
        self.assertEqual(timer.waitSecs(), left,
                         "Expected %d seconds, not %d" %
                         (timer.waitSecs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)

        tsk.close()

if __name__ == '__main__':
    unittest.main()
