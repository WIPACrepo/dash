#!/usr/bin/env python

import unittest

from RateTask import RateTask

from DAQMocks import MockComponent, MockIntervalTimer, \
     MockLogger, MockRunSet, MockTaskManager


class RateTaskTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testGood(self):
        timer = MockIntervalTimer(RateTask.NAME)

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        foo = MockComponent("fooHub", 1)

        runset = MockRunSet([foo, ])

        logger = MockLogger("logger")

        tsk = RateTask(taskMgr, runset, logger)

        logger.addExpectedRegexp((r"\t\d+ physics events \(\d+\.\d+ Hz\), "
                                  r"\d+ moni events, \d+ SN events, "
                                  r"\d+ tcals"))

        timer.trigger()
        left = tsk.check()
        self.assertEqual(timer.wait_secs(), left,
                         "Expected %d seconds, not %d" %
                         (timer.wait_secs(), left))

        tsk.waitUntilFinished()

        logger.checkStatus(4)

        tsk.close()


if __name__ == '__main__':
    unittest.main()
