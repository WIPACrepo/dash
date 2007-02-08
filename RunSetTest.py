#!/usr/bin/env python

import unittest
from CnCServer import RunSet

class MockLogger(object):
    def __init__(self, host, port):
        pass

    def write_ts(self, s):
        pass

class MockComponent:
    def __init__(self, name, num):
        self.name = name
        self.num = num
        self.connected = False
        self.configured = False
        self.runNum = None
        self.cmdOrder = 0

    def __str__(self):
        if self.configured:
            cfgStr = ' [Configured]'
        else:
            cfgStr = ''
        return self.name + cfgStr

    def configure(self, configName=None):
        if not self.connected:
            self.connected = True
        self.configured = True
        return 'OK'

    def connect(self, conn=None):
        self.connected = True
        return 'OK'

    def getState(self):
        if not self.connected:
            return 'idle'
        if not self.configured:
            return 'connected'
        if not self.runNum:
            return 'ready'

        return 'running'

    def isComponent(self, name, num):
        return self.name == name

    def logTo(self, logIP, logPort):
        pass

    def reset(self):
        self.connected = False
        self.configured = False
        self.runNum = None

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
        set = RunSet(compList, MockLogger('foo', 0))
        self.assertEqual(str(set), 'RunSet #' + str(set.id))

        self.checkStatus(set, compList, 'idle')

        logList = []
        for c in compList:
            logList.append([c.name, 0, 666, 'info'])
        set.configureLogging('localhost', logList)

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

        self.checkStatus(set, compList, 'ready')

        self.assertRaises(ValueError, set.stopRun)

        set.startRun(runNum)
        self.assertEqual(str(set), 'RunSet #' + str(set.id) +
                         ' run#' + str(runNum))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.checkStatus(set, compList, 'running')

        set.stopRun()
        self.assertEqual(str(set), 'RunSet #' + str(set.id))

        if len(compList) > 0:
            self.failUnless(self.isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(set, compList, 'ready')

        set.reset()
        self.assertEqual(str(set), 'RunSet #' + str(set.id))

        if len(compList) > 0:
            self.failIf(self.isCompListConfigured(compList),
                        'Components should be configured')
            self.failIf(self.isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(set, compList, 'idle')

    def testEmpty(self):
        self.runTests([], 1)

    def testSet(self):
        compList = [MockComponent('foo', 1), MockComponent('bar', 2)]
        self.runTests(compList, 2)

if __name__ == '__main__':
    unittest.main()
