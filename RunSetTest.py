#!/usr/bin/env python

import unittest
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet, RunSetException

CAUGHT_WARNING = False

from DAQMocks import MockClusterConfig, MockComponent, MockLogger

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

    def cycleComponents(self, compList, configDir, dashDir, logPort, livePort,
                        verbose, killWith9, eventCheck, checkExists=True):
        pass

    def queueForSpade(self, duration):
        pass
        
class TestRunSet(unittest.TestCase):
    def __buildClusterConfig(self, compList, baseName):
        jvm = "java-" + baseName
        jvmArgs = "args=" + baseName

        clusterCfg = MockClusterConfig("CC-" + baseName)
        for c in compList:
            clusterCfg.addComponent(c.fullName(), jvm, jvmArgs,
                                       "host-" + c.fullName())

        return clusterCfg

    def __buildCompList(self, nameList):
        compList = []

        num = 1
        for name in nameList:
            c = MockComponent(name, num)
            c.setOrder(num)
            compList.append(c)
            num += 1

        return compList

    def __checkStatus(self, runset, compList, expState):
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

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        runset.configure()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        logDir = "/tmp"

        #runset.startLogging(logDir, 123, clusterName)

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        logger.addExpectedRegexp("Could not stop run: .*")

        try:
            stopErr = runset.stopRun()
        except RunSetException, ve:
            if not "is not running" in str(ve):
                raise ve
            stopErr = False

        self.failIf(stopErr, "stopRun() encountered error")

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

        logger.addExpectedExact("Starting run #%d with \"%s\"" %
                                (runNum, clusterName))

        logger.addExpectedExact("Run configuration: %s" % runConfig.basename())

        logger.addExpectedRegexp(r"Version info: \S+ \d+ \S+ \S+ \S+ \S+" +
                                  r" \d+\S*")
        logger.addExpectedExact("Cluster configuration: %s" % clusterName)

        runset.startRun(runNum, clusterName, RunOption.MONI_TO_NONE,
                        versionInfo, spadeDir, copyDir, logDir)
        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.__isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

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

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        expState = "ready"

        self.failIf(runset.stopRun(), "stopRun() encountered error")

        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

    def __runTests(self, compList, runNum):
        logger = MockLogger('foo#0')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runConfig = FakeRunConfig("XXXrunCfgXXX")

        expId = RunSet.ID.peekNext()

        clusterName = "cluster-foo"

        spadeDir = "/tmp"
        copyDir = None

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

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

            logger.addExpectedExact("RunSet #%d (%s): Waiting for %s: %s" %
                                    (expId, expState, expState, cfgWaitStr))
            i += 1

        runset.configure()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        logDir = "/tmp"

        runName = 'xxx'

        expState = "ready"
        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        logger.addExpectedRegexp("Could not stop run: .*")

        self.assertRaises(RunSetException, runset.stopRun)
        logger.checkStatus(10)

        versionInfo = {"filename": "fName",
                       "revision": "1234",
                       "date": "date",
                       "time": "time",
                       "author": "author",
                       "release": "rel",
                       "repo_rev": "1repoRev",
                       }

        expState = "running"

        global CAUGHT_WARNING
        if not LIVE_IMPORT and not CAUGHT_WARNING:
            CAUGHT_WARNING = True
            logger.addExpectedRegexp(r"^Cannot import IceCube Live.*")

        logger.addExpectedExact("Starting run #%d with \"%s\"" %
                                (runNum, clusterName))

        logger.addExpectedRegexp(r"Version info: \S+ \d+ \S+ \S+ \S+ \S+" +
                                  r" \d+\S*")
        logger.addExpectedExact("Cluster configuration: %s" % clusterName)

        logger.addExpectedExact("Run configuration: %s" % runConfig.basename())

        logger.addExpectedExact("Starting run %d..." % runNum)

        runset.startRun(runNum, clusterName, RunOption.MONI_TO_NONE,
                        versionInfo, spadeDir, copyDir, logDir)
        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failUnless(self.__isCompListRunning(compList, runNum),
                            'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        self.failIf(runset.stopRun(), "stopRun() encountered error")

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        runset.reset()

        expState = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        if len(compList) > 0:
            self.failIf(self.__isCompListConfigured(compList),
                        'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

    def testEmpty(self):
        self.__runTests([], 1)

    def testSet(self):
        compList = self.__buildCompList(("foo", "bar"))
        compList[0].setConfigureWait(2)

        self.__runTests(compList, 2)

    def testSubrunGood(self):
        runNum = 3

        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))

        self.__runSubrun(compList, 3)

    def testSubrunOneBad(self):
        runNum = 4

        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))
        compList[1].setBadHub()

        self.__runSubrun(compList, 3, expectError="on %s" %
                         compList[1].fullName())

    def testSubrunBothBad(self):
        runNum = 4

        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))
        compList[0].setBadHub()
        compList[1].setBadHub()

        self.__runSubrun(compList, 3, expectError="on any string hubs")

    def testRestartFailCluCfg(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        baseName = "failCluCfg"

        clusterCfg = self.__buildClusterConfig(compList[1:], baseName)

        logger.addExpectedExact(("Cannot restart component %s: Not found" +
                                 " in cluster config \"%s\"") %
                                (compList[0].fullName(),
                                 clusterCfg.configName()))

        errMsg = None
        for c in compList[1:]:
            if errMsg is None:
                errMsg = "Cycling components [" + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
            errMsg += "]"
            logger.addExpectedExact(errMsg)

        runset.restartComponents(compList[:], clusterCfg, None, None, None,
                                 None, False, False, False)

    def testRestartExtraComp(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        extraComp = MockComponent("queen", 10)

        longList = compList[:]
        longList.append(extraComp)

        baseName = "failCluCfg"

        clusterCfg = self.__buildClusterConfig(longList, baseName)

        logger.addExpectedExact("Cannot remove component %s from RunSet #%d" %
                                (extraComp.fullName(), runset.id()))

        errMsg = None
        for c in longList:
            if errMsg is None:
                errMsg = "Cycling components [" + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
            errMsg += "]"
            logger.addExpectedExact(errMsg)

        runset.restartComponents(longList, clusterCfg, None, None, None,
                                 None, False, False, False)

    def testRestart(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        clusterCfg = self.__buildClusterConfig(compList, "restart")

        errMsg = None
        for c in compList:
            if errMsg is None:
                errMsg = "Cycling components [" + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
            errMsg += "]"
            logger.addExpectedExact(errMsg)

        runset.restartComponents(compList[:], clusterCfg, None, None, None,
                                 None, False, False, False)

    def testRestartAll(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        clusterCfg = self.__buildClusterConfig(compList, "restartAll")

        errMsg = None
        for c in compList:
            if errMsg is None:
                errMsg = "Cycling components [" + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
            errMsg += "]"
            logger.addExpectedExact(errMsg)

        runset.restartAllComponents(clusterCfg, None, None, None, None,
                                    False, False, False)

if __name__ == '__main__':
    unittest.main()
