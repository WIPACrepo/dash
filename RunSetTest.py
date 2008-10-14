#!/usr/bin/env python

import unittest
from CnCServer import RunSet

class MockLogger(object):
    def __init__(self, host, port):
        self.expMsgs = []

    def __checkMsg(self, msg):
        if len(self.expMsgs) == 0:
            raise Exception('Unexpected log message: %s' % msg)
        if self.expMsgs[0] != msg:
            raise Exception('Expected log message "%s", not "%s"' %
                            (self.expMsgs[0], msg))
        del self.expMsgs[0]

    def addExpected(self, msg):
        self.expMsgs.append(msg)

    def checkEmpty(self):
        if len(self.expMsgs) != 0:
            raise Exception("Didn't receive %d expected log messages: %s" %
                            (len(self.expMsgs), str(self.expMsgs)))

    def logmsg(self, msg):
        self.__checkMsg(msg)

    def write_ts(self, s):
        self.__checkMsg(s)

class MockComponent:
    def __init__(self, name, num):
        self.name = name
        self.num = num
        self.connected = False
        self.configured = False
        self.configWait = 0;
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

    def getName(self):
        if self.num == 0 and self.name[-3:].lower() != 'hub':
            return self.name
        return '%s#%d' % (self.name, self.num)

    def getState(self):
        if not self.connected:
            return 'idle'
        if not self.configured or self.configWait > 0:
            if self.configured and self.configWait > 0:
                self.configWait -= 1
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

    def setConfigureWait(self, waitNum):
        self.configWait = waitNum

    def startRun(self, runNum):
        if not self.configured:
            raise Exception, self.name + ' has not been configured'

        self.runNum = runNum

    def stopRun(self):
        if self.runNum is None:
            raise Exception, self.name + ' is not running'

        self.runNum = None

class TestRunSet(unittest.TestCase):
    def checkStatus(self, runset, compList, expState):
        statDict = runset.status()
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
        logger = MockLogger('foo', 0)

        runset = RunSet(compList, logger)
        self.assertEqual(str(runset), 'RunSet #' + str(runset.id))

        self.checkStatus(runset, compList, 'idle')

        logList = []
        for c in compList:
            logList.append([c.name, 0, 666, 'info'])
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
            cfgWaitNum = 0
            for c in compList:
                if c.configWait > i:
                    cfgWaitNum += 1

            if cfgWaitNum == 0:
                break

            cfgDict = { 'connected' : cfgWaitNum }
            logger.addExpected('Waiting for %d components to start configuring: %s' %
                               (cfgWaitNum, str(cfgDict)))
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

        logger.checkEmpty()

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
