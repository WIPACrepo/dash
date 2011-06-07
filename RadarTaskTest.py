#!/usr/bin/env python

import datetime, unittest

from RadarTask import RadarTask, RadarThread
from LiveImports import Prio

from DAQMocks import MockComponent, MockIntervalTimer, MockLiveMoni, \
     MockLogger, MockRunSet, MockTaskManager

class RadarTaskTest(unittest.TestCase):
    def setUp(self):
        pass

    def tearDown(self):
        pass

    def testGood(self):
        timer = MockIntervalTimer("Radar")

        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        hitRate = 123

        compList = []

        hub = MockComponent("foo", 0)
        compList.append(hub)

        for mbid in RadarThread.DOM_MAP.keys():
            hub = MockComponent("stringHub", RadarThread.DOM_MAP[mbid])
            hub.addBeanData("DataCollectorMonitor-01A", "MainboardId", "xxx")
            hub.addBeanData("DataCollectorMonitor-23B", "MainboardId", mbid)
            hub.addBeanData("DataCollectorMonitor-23B", "HitRate", hitRate)
            hub.addBeanData("AAAAA", "ZZZZ", "extra")
            compList.append(hub)

        hub = MockComponent("bar", 0)
        compList.append(hub)

        runset = MockRunSet(compList)

        logger = MockLogger("logger")
        live = MockLiveMoni()

        tsk = RadarTask(taskMgr, runset, logger, live)

        liveVals = []
        for mbid in RadarThread.DOM_MAP.keys():
            liveVals.append((mbid, hitRate))

        live.addExpected("radarDOMs", liveVals, Prio.EMAIL)

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
