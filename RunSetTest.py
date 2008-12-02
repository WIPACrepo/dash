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

    def isCompListConfigured(self, compList):
        for c in compList:
            if not c.isConfigured():
                return False

        return True
        
    def isCompListRunning(self, compList, runNum=-1):
        for c in compList:
            if c.runNum is None:
                return False
            if c.runNum != runNum:
                return False

        return True

    def runTests(self, compList, runNum):
        logger = MockLogger('foo#0')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runset = RunSet(compList, logger)
        self.assertEqual(str(runset), 'RunSet #' + str(runset.id))

        self.checkStatus(runset, compList, 'idle')

        logList = []
        for c in compList:
            logList.append([c.name, c.num, 666, 'info'])
        runset.configureLogging('localhost', logList)

        if len(compList) > 0:
            self.failIf(self.isCompListConfigured(compList),
                        'Components should not be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.assertRaises(ValueError, runset.startRun, 1)
        self.assertRaises(ValueError, runset.stopRun)

        i = 0
        while True:
            cfgWaitStr = None
            for c in compList:
                if c.getConfigureWait() > i:
                    if cfgWaitStr is None:
                        cfgWaitStr = c.getName()
                    else:
                        cfgWaitStr += ', ' + c.getName()

            if cfgWaitStr is None:
                break

            logger.addExpectedExact('RunSet #%d: Waiting for configuring: %s' %
                                    (runset.id, cfgWaitStr))
            i += 1

        runset.configure('xxx')
        self.assertEqual(str(runset), 'RunSet #' + str(runset.id))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'ready')

        self.assertRaises(ValueError, runset.stopRun)

        runset.startRun(runNum)
        self.assertEqual(str(runset), 'RunSet #' + str(runset.id) +
                         ' run#' + str(runNum))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.checkStatus(runset, compList, 'running')

        runset.stopRun()
        self.assertEqual(str(runset), 'RunSet #' + str(runset.id))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'ready')

        runset.reset()
        self.assertEqual(str(runset), 'RunSet #' + str(runset.id))

        if len(compList) > 0:
            self.failIf(self.isCompListConfigured(compList),
                        'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, 'idle')

        logger.checkStatus(10)

    def testEmpty(self):
        self.runTests([], 1)

    def testSet(self):
        compList = []
        compList.append(MockComponent('foo', 1))
        compList.append(MockComponent('bar', 2))
        compList[0].setConfigureWait(2)

        self.runTests(compList, 2)

if __name__ == '__main__':
    unittest.main()
