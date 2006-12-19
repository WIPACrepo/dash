#!/usr/bin/env python

import unittest
from CnCServer import RunSet

class MockComponent:
    def __init__(self, name):
        self.name = name
        self.configured = False
        self.runNum = None

    def configure(self, configName=None):
        self.configured = True

    def getState(self):
        if not self.configured:
            return 'Idle'

        if not self.runNum:
            return 'Ready'

        return 'Running'

    def reset(self):
        self.configured = False

    def startRun(self, runNum):
        if not self.configured:
            raise Error, name + ' has not been configured'

        self.runNum = runNum

    def stopRun(self):
        if self.runNum is None:
            raise Error, name + ' is not running'

        self.runNum = None

class TestRunSet(unittest.TestCase):
    def checkStatus(self, set, compList, expState):
        statDict = set.status()
        self.assertEqual(len(statDict), len(compList))
        for c in compList:
            self.failUnless(statDict.has_key(c), 'Could not find ' + str(c))
            self.assertEqual(statDict[c], expState)

    def isCompListConfigured(self, compList):
        for c in compList:
            if not c.configured:
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
        set = RunSet(compList)
        self.assertEqual(str(set), 'RunSet #' + str(set.id))

        self.checkStatus(set, compList, 'Idle')

        if len(compList) > 0:
            self.failIf(self.isCompListConfigured(compList),
                        'Components should not be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.assertRaises(ValueError, set.startRun, 1)
        self.assertRaises(ValueError, set.stopRun)

        set.configure('xxx')
        self.assertEqual(str(set), 'RunSet #' + str(set.id))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(set, compList, 'Ready')

        self.assertRaises(ValueError, set.stopRun)

        set.startRun(runNum)
        self.assertEqual(str(set), 'RunSet #' + str(set.id) +
                         ' run#' + str(runNum))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.checkStatus(set, compList, 'Running')

        set.stopRun()
        self.assertEqual(str(set), 'RunSet #' + str(set.id))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(set, compList, 'Ready')

        set.reset()
        self.assertEqual(str(set), 'RunSet #' + str(set.id))

        if len(compList) > 0:
            self.failIf(self.isCompListConfigured(compList),
                        'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(set, compList, 'Idle')

    def testEmpty(self):
        self.runTests([], 1)

    def testSet(self):
        compList = [MockComponent('foo'), MockComponent('bar')]
        self.runTests(compList, 2)

if __name__ == '__main__':
    unittest.main()
