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

    def test_good(self):
        timer = MockIntervalTimer(RateTask.name)

        task_mgr = MockTaskManager()
        task_mgr.add_interval_timer(timer)

        comp = MockComponent("fooHub", 1)

        runset = MockRunSet([comp, ])

        logger = MockLogger("logger")

        tsk = RateTask(task_mgr, runset, logger)

        logger.add_expected_regexp(r"\t\d+ physics events \(\d+\.\d+ Hz\), "
                                   r"\d+ moni events, \d+ SN events, "
                                   r"\d+ tcals")

        timer.trigger()
        left = tsk.check()
        self.assertEqual(timer.wait_secs(), left,
                         "Expected %d seconds, not %d" %
                         (timer.wait_secs(), left))

        tsk.wait_until_finished()

        logger.check_status(4)

        tsk.close()


if __name__ == '__main__':
    unittest.main()
