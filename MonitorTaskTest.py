#!/usr/bin/env python

import os
import tempfile
import unittest
import shutil

from DAQClient import BeanTimeoutException
from LiveImports import Prio
from MonitorTask import MonitorTask
from RunOption import RunOption

from DAQMocks import MockComponent, MockIntervalTimer, MockLiveMoni, \
     MockLogger, MockMBeanClient, MockRunSet, MockTaskManager


class BadMBeanClient(MockMBeanClient):
    def __init__(self, compName):
        self.__raiseSocketError = False
        self.__raiseException = False

        super(BadMBeanClient, self).__init__(compName)

    def clearConditions(self):
        self.__raiseSocketError = False
        self.__raiseException = False

    def get(self, beanName, fieldName):
        if self.__raiseSocketError:
            self.__raiseSocketError = False
            raise BeanTimeoutException("Mock exception")
        if self.__raiseException:
            self.__raiseException = False
            raise Exception("Mock exception")
        return super(BadMBeanClient, self).get(beanName, fieldName)

    def get_dictionary(self):
        if self.__raiseSocketError:
            self.__raiseSocketError = False
            raise BeanTimeoutException("Mock exception")
        if self.__raiseException:
            self.__raiseException = False
            raise Exception("Mock exception")
        return super(BadMBeanClient, self).get_dictionary()

    def raiseException(self):
        self.__raiseException = True

    def raiseSocketError(self):
        self.__raiseSocketError = True


class BadComponent(MockComponent):
    def __init__(self, name, num=0):
        super(BadComponent, self).__init__(name, num)

    def _create_mbean_client(self):
        return BadMBeanClient(self.fullname)


class BadCloseThread(object):
    def __init__(self):
        super(BadCloseThread, self).__init__()

        self.__closed = False

    def close(self):
        self.__closed = True
        raise Exception("Forced exception")

    def isAlive(self):
        return True

    @property
    def isClosed(self):
        return self.__closed


class BadMonitorTask(MonitorTask):
    def __init__(self, task_mgr, runset, logger, live, rundir, runOpts):
        super(BadMonitorTask, self).__init__(task_mgr, runset, logger, live,
                                             rundir, runOpts)

    @classmethod
    def create_thread(cls, comp, rundir, live, run_options, dashlog):
        return BadCloseThread()


class MonitorTaskTest(unittest.TestCase):
    __temp_dir = None

    def __createStandardComponents(self):
        foo = MockComponent("foo", 1)
        foo.mbean.addData("fooB", "fooF", 12)
        foo.mbean.addData("fooB", "fooG", "abc")

        bar = MockComponent("bar", 0)
        bar.mbean.addData("barB", "barF", 7)

        return [foo, bar, ]

    def __createStandardObjects(self):
        timer = MockIntervalTimer(MonitorTask.name)
        taskMgr = MockTaskManager()
        taskMgr.addIntervalTimer(timer)

        logger = MockLogger("logger")
        live = MockLiveMoni()

        return (timer, taskMgr, logger, live)

    def __runTest(self, compList, timer, taskMgr, logger, live, runOpt,
                  raiseSocketError=False, raiseException=False):
        runset = MockRunSet(compList)

        tsk = MonitorTask(taskMgr, runset, logger, live, self.__temp_dir,
                          runOpt)

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        for i in range(-1, 5):
            if RunOption.is_moni_to_live(runOpt):
                for c in compList:
                    if isinstance(c, BadComponent):
                        c.mbean.clearConditions()
                    for b in c.mbean.get_bean_names():
                        for f in c.mbean.get_bean_fields(b):
                            live.addExpected(c.filename + "*" + b + "+" + f,
                                             c.mbean.get(b, f),
                                             Prio.ITS)

            for c in compList:
                if isinstance(c, BadComponent):
                    if raiseSocketError:
                        if i == 3:
                            errMsg = ("ERROR: Not monitoring %s:" +
                                      " Connect failed %d times") % \
                                      (c.fullname, i)
                            logger.addExpectedExact(errMsg)
                        elif i >= 0 and i < 3:
                            c.mbean.raiseSocketError()
                    elif i > 0 and raiseException:
                        errMsg = "Ignoring %s:(.*:)? Exception.*$" % c.fullname
                        logger.addExpectedRegexp(errMsg)
                        c.mbean.raiseException()

            timer.trigger()
            left = tsk.check()
            self.assertEqual(timer.wait_secs(), left,
                             "Expected %d seconds, not %d" %
                             (timer.wait_secs(), left))

            tsk.wait_until_finished()

            logger.checkStatus(4)

        tsk.close()

        self.__validateFiles(runOpt, compList)

        logger.checkStatus(4)

    def __validateFiles(self, runOpt, compList):
        files = os.listdir(self.__temp_dir)
        if not RunOption.is_moni_to_file(runOpt):
            self.assertFalse(len(files) > 0,
                             "Found unexpected monitoring files: " +
                             str(files))
            return

        expFiles = len(compList)
        if MonitorTask.MONITOR_CNCSERVER:
            # if monitoring CnCServer, there should be a cncServer.moni file
            expFiles += 1

        self.assertTrue(len(files) == expFiles,
                        "Expected %d files, not %d: %s" %
                        (expFiles, len(files), files))

    def setUp(self):
        self.__temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        try:
            shutil.rmtree(self.__temp_dir)
        except:
            pass  # ignore errors

    def testBadRunOpt(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        compList = self.__createStandardComponents()

        self.__runTest(compList, timer, taskMgr, logger, live, 0)

    def testGoodNone(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        compList = self.__createStandardComponents()

        self.__runTest(compList, timer, taskMgr, logger, live,
                       RunOption.MONI_TO_NONE)

    def testGoodFile(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        compList = self.__createStandardComponents()

        self.__runTest(compList, timer, taskMgr, logger, live,
                       RunOption.MONI_TO_FILE)

    def testGoodLive(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        compList = self.__createStandardComponents()

        self.__runTest(compList, timer, taskMgr, logger, live,
                       RunOption.MONI_TO_LIVE)

    def testGoodBoth(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        compList = self.__createStandardComponents()

        self.__runTest(compList, timer, taskMgr, logger, live,
                       RunOption.MONI_TO_BOTH)

    def testSocketError(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        foo = MockComponent("foo", 1)
        foo.mbean.addData("fooB", "fooF", 12)
        foo.mbean.addData("fooB", "fooG", "abc")

        bar = BadComponent("bar", 0)
        bar.mbean.addData("barB", "barF", 7)

        compList = [foo, bar, ]
        self.__runTest(compList, timer, taskMgr, logger, live,
                       RunOption.MONI_TO_BOTH, raiseSocketError=True)

    def testException(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        foo = MockComponent("foo", 1)
        foo.mbean.addData("fooB", "fooF", 12)
        foo.mbean.addData("fooB", "fooG", "abc")

        bar = BadComponent("bar", 0)
        bar.mbean.addData("barB", "barF", 7)

        compList = [foo, bar, ]
        self.__runTest(compList, timer, taskMgr, logger, live,
                       RunOption.MONI_TO_BOTH, raiseException=True)

    def testFailedClose(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        compList = self.__createStandardComponents()
        runset = MockRunSet(compList)

        tsk = BadMonitorTask(taskMgr, runset, logger, live, self.__temp_dir,
                             RunOption.MONI_TO_LIVE)
        timer.trigger()
        tsk.check()

        try:
            tsk.close()
        except Exception as ex:
            if not str(ex).endswith("Forced exception"):
                raise
        self.assertTrue(tsk.open_threads == 0,
                        "%d threads were not closed" % (tsk.open_threads, ))


if __name__ == '__main__':
    unittest.main()
