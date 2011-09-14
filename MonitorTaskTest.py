#!/usr/bin/env python

import datetime
import os
import socket
import tempfile
import unittest

from LiveImports import Prio
from MonitorTask import MonitorTask
from RunOption import RunOption

from DAQMocks import MockComponent, MockIntervalTimer, MockLiveMoni, \
     MockLogger, MockRunSet, MockTaskManager


class BadComponent(MockComponent):
    def __init__(self, name, num=0):
        super(BadComponent, self).__init__(name, num)

        self.__raiseSocketError = False
        self.__raiseException = False

    def __str__(self):
        sstr = super(BadComponent, self).__str__()
        if self.__raiseSocketError:
            sstr += "^sockErr"
        if self.__raiseException:
            sstr += "^exc"
        return sstr

    def getSingleBeanField(self, beanName, fieldName):
        if self.__raiseSocketError:
            self.__raiseSocketError = False
            raise socket.error(123, "Connection refused")
        if self.__raiseException:
            self.__raiseException = False
            raise Exception("Mock exception")
        return super(BadComponent, self).getSingleBeanField(beanName,
                                                            fieldName)

    def raiseException(self):
        self.__raiseException = True

    def raiseSocketError(self):
        self.__raiseSocketError = True


class BadCloseThread(object):
    def __init__(self):
        super(BadCloseThread, self).__init__()

        self.__closed = False

    def close(self):
        self.__closed = True
        raise Exception("Forced exception")

    def isAlive(self):
        return True

    def isClosed(self):
        return self.__closed


class BadMonitorTask(MonitorTask):
    def __init__(self, taskMgr, runset, logger, live, rundir, runOpts):
        super(BadMonitorTask, self).__init__(taskMgr, runset, logger, live,
                                             rundir, runOpts)

    @classmethod
    def createThread(cls, comp, runDir, live, runOptions, dashlog):
        return BadCloseThread()


class MonitorTaskTest(unittest.TestCase):
    __temp_dir = None

    def __createStandardComponents(self):
        foo = MockComponent("foo", 1)
        foo.addBeanData("fooB", "fooF", 12)
        foo.addBeanData("fooB", "fooG", "abc")

        bar = MockComponent("bar", 0)
        bar.addBeanData("barB", "barF", 7)

        return [foo, bar, ]

    def __createStandardObjects(self):
        timer = MockIntervalTimer("Monitoring")
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

        #from DAQMocks import LogChecker; LogChecker.DEBUG = True

        for i in range(-1, 5):
            if RunOption.isMoniToLive(runOpt):
                for c in compList:
                    for b in c.getBeanNames():
                        for f in c.getBeanFields(b):
                            live.addExpected(c.fileName() + "*" + b + "+" + f,
                                             c.getSingleBeanField(b, f),
                                             Prio.ITS)

            for c in compList:
                if isinstance(c, BadComponent):
                    if raiseSocketError:
                        if i == 3:
                            errMsg = ("ERROR: Not monitoring %s:" +
                                      " Connect failed %d times") % \
                                      (c.fullName(), i)
                            logger.addExpectedExact(errMsg)
                        elif i >= 0 and i < 3:
                            c.raiseSocketError()
                    elif i > 0 and raiseException:
                        errMsg = "Ignoring %s:.*: Exception.*$" % c.fullName()
                        logger.addExpectedRegexp(errMsg)
                        c.raiseException()

            timer.trigger()
            left = tsk.check()
            self.assertEqual(timer.waitSecs(), left,
                             "Expected %d seconds, not %d" %
                             (timer.waitSecs(), left))

            tsk.waitUntilFinished()

            logger.checkStatus(4)

        tsk.close()

        self.__validateFiles(runOpt, compList)

        logger.checkStatus(4)

    def __validateFiles(self, runOpt, compList):
        files = os.listdir(self.__temp_dir)
        if not RunOption.isMoniToFile(runOpt):
            self.failIf(len(files) > 0, "Found unexpected monitoring files: " +
                        str(files))
            return

        self.failUnless(len(files) == len(compList),
                        "Expected %d files, not %d" %
                        (len(compList), len(files)))

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
        foo.addBeanData("fooB", "fooF", 12)
        foo.addBeanData("fooB", "fooG", "abc")

        bar = BadComponent("bar", 0)
        bar.addBeanData("barB", "barF", 7)

        compList = [foo, bar, ]
        self.__runTest(compList, timer, taskMgr, logger, live,
                       RunOption.MONI_TO_BOTH, raiseSocketError=True)

    def testException(self):
        (timer, taskMgr, logger, live) = self.__createStandardObjects()

        foo = MockComponent("foo", 1)
        foo.addBeanData("fooB", "fooF", 12)
        foo.addBeanData("fooB", "fooG", "abc")

        bar = BadComponent("bar", 0)
        bar.addBeanData("barB", "barF", 7)

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
        except Exception, ex:
            if not str(ex).endswith("Forced exception"):
                raise ex
        self.failUnless(tsk.numOpen() == 0, "%d threads were not closed" %
                        tsk.numOpen())

if __name__ == '__main__':
    unittest.main()
