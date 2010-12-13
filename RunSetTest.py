#!/usr/bin/env python

import unittest
from CnCServer import RunSet

from DAQMocks import MockComponent, MockLogger

class TestRunSet(unittest.TestCase):
    def checkStatus(self, runset, compList, expState):
        statDict = runset.status()
        self.assertEqual(len(statDict), len(compList))
        for c in compList:
            self.failUnless(statDict.has_key(c), 'Could not find ' + str(c))
            self.assertEqual(statDict[c], expState)

    def __isCompListConfigured(self, compList):
        for c in compList:
            if not c.isConfigured():
                return False

        return True
        
    def __isCompListRunning(self, compList, runNum=-1):
        for c in compList:
            if c.runNum is None:
                return False
            if c.runNum != runNum:
                return False

        return True

    def __runSubrun(self, compList, runNum, expectError=None):
        logger = MockLogger('LOG')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runset = RunSet(compList, logger)
        self.assertEqual(str(runset), 'RunSet #%d' % runset.id())

        self.checkStatus(runset, compList, 'idle')

        runset.configure('xxx')
        self.assertEqual(str(runset), 'RunSet #%d' % runset.id())

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'ready')

        self.assertRaises(ValueError, runset.stopRun)

        runset.startRun(runNum)
        self.assertEqual(str(runset), 'RunSet #%d run#%d' %
                         (runset.id(), runNum))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.__isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.checkStatus(runset, compList, 'running')

        data = 'SubRunData'
        try:
            runset.subrun(-1, data)
            if expectError is not None:
                self.fail("subrun should not have succeeded")
        except ValueError, ve:
            if expectError is None:
                raise
            if not str(ve).endswith(expectError):
                self.fail("Expected subrun to fail with \"%s\", not \"%s\"" %
                          (expectError, str(ve)))

        self.checkStatus(runset, compList, 'running')

        runset.stopRun()
        self.assertEqual(str(runset), 'RunSet #%d' % runset.id())

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'ready')

    def __runTests(self, compList, runNum):
        logger = MockLogger('foo#0')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runset = RunSet(compList, logger)
        self.assertEqual(str(runset), 'RunSet #%d' % runset.id())

        self.checkStatus(runset, compList, 'idle')

        logList = []
        for c in compList:
            logList.append([c.name(), c.num(), 666, 'info'])
        runset.configureLogging('localhost', logList)

        if len(compList) > 0:
            self.failIf(self.__isCompListConfigured(compList),
                        'Components should not be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.assertRaises(ValueError, runset.startRun, 1)
        self.assertRaises(ValueError, runset.stopRun)

        i = 0
        while True:
            cfgWaitStr = None
            for c in compList:
                if c.getConfigureWait() > i:
                    if cfgWaitStr is None:
                        cfgWaitStr = c.fullName()
                    else:
                        cfgWaitStr += ', ' + c.fullName()

            if cfgWaitStr is None:
                break

            logger.addExpectedExact('RunSet #%d: Waiting for configuring: %s' %
                                    (runset.id(), cfgWaitStr))
            i += 1

        runset.configure('xxx')
        self.assertEqual(str(runset), 'RunSet #%d' % runset.id())

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'ready')

        self.assertRaises(ValueError, runset.stopRun)

        runset.startRun(runNum)
        self.assertEqual(str(runset), 'RunSet #%d run#%d' %
                         (runset.id(), runNum))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.__isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.checkStatus(runset, compList, 'running')

        runset.stopRun()
        self.assertEqual(str(runset), 'RunSet #%d' % runset.id())

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'ready')

        runset.reset()
        self.assertEqual(str(runset), 'RunSet #%d' % runset.id())

        if len(compList) > 0:
            self.failIf(self.__isCompListConfigured(compList),
                        'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'idle')

        logger.checkStatus(10)

    def testEmpty(self):
        self.__runTests([], 1)

    def testSet(self):
        compList = []
        compList.append(MockComponent('foo', 1))
        compList.append(MockComponent('bar', 2))
        compList[0].setConfigureWait(2)

        self.__runTests(compList, 2)

    def testSubrunGood(self):
        runNum = 3

        compList = []
        compList.append(MockComponent("fooHub", 1))
        compList.append(MockComponent("barHub", 2))
        compList.append(MockComponent("bazBuilder", 3))

        self.__runSubrun(compList, 3)

    def testSubrunOneBad(self):
        runNum = 4

        compList = []
        compList.append(MockComponent("fooHub", 1))
        compList.append(MockComponent("barHub", 2))
        compList.append(MockComponent("bazBuilder", 3))

        compList[1].setBadHub()

        self.__runSubrun(compList, 3, "on %s" % compList[1].fullName())

    def testSubrunBothBad(self):
        runNum = 4

        compList = []
        compList.append(MockComponent("fooHub", 1))
        compList.append(MockComponent("barHub", 2))
        compList.append(MockComponent("bazBuilder", 3))

        compList[0].setBadHub()
        compList[1].setBadHub()

        self.__runSubrun(compList, 3, "on any string hubs")

if __name__ == '__main__':
    unittest.main()
