#!/usr/bin/env python
"Text ActiveDOMTask"

import unittest

from ActiveDOMsTask import ActiveDOMsTask
from LiveImports import Prio

from DAQMocks import MockComponent, MockIntervalTimer, MockLiveMoni, \
     MockLogger, MockRunSet, MockTaskManager


class ActiveDOMsTaskTest(unittest.TestCase):
    "Test ActiveDOMsTask methods"
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_good(self):
        "Test the basic functionality"
        rpt_timer = MockIntervalTimer(ActiveDOMsTask.REPORT_NAME)
        dom_timer = MockIntervalTimer(ActiveDOMsTask.name)

        task_mgr = MockTaskManager()
        task_mgr.addIntervalTimer(rpt_timer)
        task_mgr.addIntervalTimer(dom_timer)

        num_active = 12
        num_total = 20
        num_lbm = 2

        hub = MockComponent("fooHub", 1)
        hub.mbean.addData("stringhub", "NumberOfActiveAndTotalChannels",
                          (num_active, num_total))
        hub.mbean.addData("stringhub", "TotalLBMOverflows", num_lbm)

        runset = MockRunSet([hub, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = ActiveDOMsTask(task_mgr, runset, logger, live)

        data = {
            "activeDOMs": num_active,
            "expectedDOMs": num_total,
            "missingDOMs": num_total - num_active,
        }

        for key in data:
            live.addExpected(key, data[key], Prio.EMAIL)

        live.addExpected("dom_update", data, Prio.ITS)

        rpt_timer.trigger()
        left = tsk.check()
        self.assertEqual(rpt_timer.wait_secs(), left,
                         "Expected %d seconds, not %d" %
                         (rpt_timer.wait_secs(), left))

        tsk.wait_until_finished()

        logger.checkStatus(4)
        live.hasAllMoni()

        live.addExpected("stringRateInfo", {'1': 50}, Prio.EMAIL)
        live.addExpected("stringRateLCInfo", {'1': 25}, Prio.EMAIL)
        live.addExpected("missingDOMs", num_total - num_active, Prio.ITS)

        lbmo_dict = {
            "runNumber": runset.run_number(),
            "early_lbm": True,
            "count": 2,
        }
        live.addExpected("LBMOcount", lbmo_dict, Prio.ITS)

        dom_timer.trigger()
        left = tsk.check()
        self.assertEqual(rpt_timer.wait_secs(), left,
                         "Expected %d seconds, not %d" %
                         (rpt_timer.wait_secs(), left))

        tsk.wait_until_finished()

        logger.checkStatus(4)
        live.hasAllMoni()

        # things will be subtly different for the second report

        live.addExpected("dom_update", data, Prio.EMAIL)

        lbmo_dict = {
            "runNumber": runset.run_number(),
            "early_lbm": False,
            "count": 0,
            "recordingStartTime": "XXX",
            "recordingStopTime": "XXX",
        }
        live.addExpected("LBMOcount", lbmo_dict, Prio.ITS,
                         match_dict_values=False)

        dom_timer.trigger()
        left = tsk.check()
        self.assertEqual(rpt_timer.wait_secs(), left,
                         "Expected %d seconds, not %d" %
                         (rpt_timer.wait_secs(), left))

        tsk.wait_until_finished()

        logger.checkStatus(4)
        tsk.close()

    def test_no_live(self):
        "Check that things work without I3Live"
        rpt_timer = MockIntervalTimer(ActiveDOMsTask.REPORT_NAME)
        dom_timer = MockIntervalTimer(ActiveDOMsTask.name)

        task_mgr = MockTaskManager()
        task_mgr.addIntervalTimer(rpt_timer)
        task_mgr.addIntervalTimer(dom_timer)

        num_active = 12
        num_total = 20
        num_lbm = 2

        hub = MockComponent("fooHub", 1)
        hub.mbean.addData("stringhub", "NumberOfActiveAndTotalChannels",
                          (num_active, num_total))
        hub.mbean.addData("stringhub", "TotalLBMOverflows", num_lbm)

        runset = MockRunSet([hub, ])

        logger = MockLogger("logger")
        live = None

        tsk = ActiveDOMsTask(task_mgr, runset, logger, live)

        rpt_timer.trigger()
        left = tsk.check()
        self.assertEqual(tsk.MAX_TASK_SECS, left,
                         "Expected %d seconds, not %d" %
                         (tsk.MAX_TASK_SECS, left))

        tsk.wait_until_finished()

        logger.checkStatus(4)

        dom_timer.trigger()
        left = tsk.check()
        self.assertEqual(tsk.MAX_TASK_SECS, left,
                         "Expected %d seconds, not %d" %
                         (tsk.MAX_TASK_SECS, left))

        tsk.wait_until_finished()

        logger.checkStatus(4)

        tsk.reset()

        tsk.close()

    def test_fail(self):
        "Check that bad NumberOfActiveAndTotalChannels data is handled"
        rpt_timer = MockIntervalTimer(ActiveDOMsTask.REPORT_NAME)
        dom_timer = MockIntervalTimer(ActiveDOMsTask.name)

        task_mgr = MockTaskManager()
        task_mgr.addIntervalTimer(rpt_timer)
        task_mgr.addIntervalTimer(dom_timer)

        num_active = 12
        num_total = 20
        num_lbm = 2

        hub = MockComponent("fooHub", 1)
        hub.mbean.addData("stringhub", "NumberOfActiveAndTotalChannels",
                          (num_active, num_total))
        hub.mbean.addData("stringhub", "TotalLBMOverflows", num_lbm)

        runset = MockRunSet([hub, ])

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = ActiveDOMsTask(task_mgr, runset, logger, live)

        live.addExpected("missingDOMs", num_total - num_active, Prio.EMAIL)

        rpt_timer.trigger()
        left = tsk.check()
        self.assertEqual(rpt_timer.wait_secs(), left,
                         "Expected %d seconds, not %d" %
                         (rpt_timer.wait_secs(), left))

        tsk.wait_until_finished()

        logger.checkStatus(4)
        live.hasAllMoni()

        hub.mbean.setData("stringhub", "NumberOfActiveAndTotalChannels",
                          Exception("Simulated error"))
        logger.addExpectedRegexp(r".*Simulated error.*")

        dom_timer.trigger()
        left = tsk.check()
        self.assertEqual(rpt_timer.wait_secs(), left,
                         "Expected %d seconds, not %d" %
                         (rpt_timer.wait_secs(), left))

        tsk.wait_until_finished()

        logger.checkStatus(4)
        live.hasAllMoni()

        tsk.close()


if __name__ == '__main__':
    unittest.main()
