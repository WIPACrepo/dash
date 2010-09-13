#!/usr/bin/env python

import unittest
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet, RunSetException

CAUGHT_WARNING = False

from DAQMocks import MockComponent, MockLogger

class FakeLogger(object):
    def __init__(self): pass
    def stopServing(self): pass

class FakeTaskManager(object):
    def __init__(self): pass
    def reset(self): pass
    def start(self): pass
    def stop(self): pass

class FakeRunConfig(object):
    def __init__(self, name):
        self.__name = name

    def basename(self): return self.__name

    def hasDOM(self, mbid):
        return True

class MyParent(object):
    def __init__(self):
        pass

    def saveCatchall(self, runDir):
        pass

class MyRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger):
        self.__dashLog = logger

        super(MyRunSet, self).__init__(parent, runConfig, compList, logger)

    def createComponentLog(self, runDir, c, host, port, liveHost, livePort,
                           quiet=True):
        return FakeLogger()

    def createDashLog(self):
        return self.__dashLog

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir=None, logDir=None):
        return super(MyRunSet, self).createRunData(runNum, clusterConfigName,
                                                   runOptions, versionInfo,
                                                   spadeDir, copyDir,
                                                   logDir, True)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        return None

    def createTaskManager(self, dashlog, liveMoniClient, runDir, moniType):
        return FakeTaskManager()

    def queueForSpade(self, duration):
        pass
        
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

    def __runSubrun(self, compList, runNum, spadeDir="/tmp", copyDir=None,
                    expectError=None):
        logger = MockLogger('LOG')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runConfig = FakeRunConfig("XXXrunSubXXX")

        clusterName = "cluster-foo"

        logger.addExpectedExact("Starting run #%d with \"%s\"" %
                                (runNum, clusterName))

        logger.addExpectedExact("Run configuration: %s" % runConfig.basename())

        parent = MyParent()
        runset = MyRunSet(parent, runConfig, compList, logger)

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.checkStatus(runset, compList, expState)

        runset.configure()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.checkStatus(runset, compList, expState)

        logger.addExpectedRegexp(r"Version info: \S+ \d+ \S+ \S+ \S+ \S+" +
                                  r" \d+\S*")
        logger.addExpectedExact("Cluster configuration: %s" % clusterName)

        logDir = "/tmp"

        #runset.startLogging(logDir, 123, clusterName)

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, expState)

        try:
            runset.stopRun()
        except RunSetException, ve:
            if not "is not running" in str(ve):
                raise ve

        logger.addExpectedExact("Starting run %d..." % runNum)

        versionInfo = {"filename": "fName",
                       "revision": "1234",
                       "date": "date",
                       "time": "time",
                       "author": "author",
                       "release": "rel",
                       "repo_rev": "1repoRev",
                       }

        expState = "running"

        runset.startRun(runNum, clusterName, RunOption.MONI_TO_NONE,
                        versionInfo, spadeDir, copyDir, logDir)
        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.__isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.checkStatus(runset, compList, expState)

        domList = [('53494d550101', 0, 1, 2, 3, 4),
                   ['1001', '22', 1, 2, 3, 4, 5],
                   ('a', 0, 1, 2, 3, 4)]

        data = [domList[0], ['53494d550122', ] + domList[1][2:]]

        subrunNum = -1

        logger.addExpectedExact("Subrun %d: flashing DOMs (%s)" %
                                (subrunNum, data))

        try:
            runset.subrun(subrunNum, data)
            if expectError is not None:
                self.fail("subrun should not have succeeded")
        except RunSetException, ve:
            if expectError is None:
                raise
            if not str(ve).endswith(expectError):
                self.fail("Expected subrun to fail with \"%s\", not \"%s\"" %
                          (expectError, str(ve)))

        self.checkStatus(runset, compList, expState)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        expState = "ready"

        runset.stopRun()
        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, expState)

    def __runTests(self, compList, runNum):
        logger = MockLogger('foo#0')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runConfig = FakeRunConfig("XXXrunCfgXXX")

        expId = RunSet.ID.peekNext()

        expState = "configuring"

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

            logger.addExpectedExact(("RunSet #%d (%s): Waiting for" +
                                     " configuring: %s") %
                                    (expId, expState, cfgWaitStr))
            i += 1

        clusterName = "cluster-foo"

        logger.addExpectedExact("Starting run #%d with \"%s\"" %
                                (runNum, clusterName))

        logger.addExpectedExact("Run configuration: %s" % runConfig.basename())

        spadeDir = "/tmp"
        copyDir = None

        parent = MyParent()
        runset = MyRunSet(parent, runConfig, compList, logger)

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.checkStatus(runset, compList, expState)

        runset.configure()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.checkStatus(runset, compList, expState)

        global CAUGHT_WARNING
        if not LIVE_IMPORT and not CAUGHT_WARNING:
            CAUGHT_WARNING = True
            logger.addExpectedRegexp(r"^Cannot import IceCube Live.*")

        logger.addExpectedRegexp(r"Version info: \S+ \d+ \S+ \S+ \S+ \S+" +
                                  r" \d+\S*")
        logger.addExpectedExact("Cluster configuration: %s" % clusterName)

        logger.addExpectedExact("Starting run %d..." % runNum)

        logDir = "/tmp"

        runName = 'xxx'

        expState = "ready"
        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, expState)

        self.assertRaises(RunSetException, runset.stopRun)

        versionInfo = {"filename": "fName",
                       "revision": "1234",
                       "date": "date",
                       "time": "time",
                       "author": "author",
                       "release": "rel",
                       "repo_rev": "1repoRev",
                       }

        expState = "running"

        runset.startRun(runNum, clusterName, RunOption.MONI_TO_NONE,
                        versionInfo, spadeDir, copyDir, logDir)
        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.__isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.checkStatus(runset, compList, expState)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        runset.stopRun()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, expState)

        runset.reset()

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        if len(compList) > 0:
            self.failIf(self.__isCompListConfigured(compList),
                        'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.checkStatus(runset, compList, expState)

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

        self.__runSubrun(compList, 3, expectError="on %s" % compList[1].fullName())

    def testSubrunBothBad(self):
        runNum = 4

        compList = []
        compList.append(MockComponent("fooHub", 1))
        compList.append(MockComponent("barHub", 2))
        compList.append(MockComponent("bazBuilder", 3))

        compList[0].setBadHub()
        compList[1].setBadHub()

        self.__runSubrun(compList, 3, expectError="on any string hubs")

if __name__ == '__main__':
    unittest.main()
