#!/usr/bin/env python

import unittest
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet, RunSetException, listComponentRanges
from scmversion import get_scmversion_str

CAUGHT_WARNING = False

from DAQMocks import MockClusterConfig, MockComponent, MockLogger, \
     RunXMLValidator


class FakeLogger(object):
    def __init__(self):
        pass

    def stopServing(self):
        pass


class FakeTaskManager(object):
    def __init__(self):
        pass

    def reset(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class FakeRunConfig(object):
    def __init__(self, name):
        self.__name = name

    def basename(self):
        return self.__name

    def hasDOM(self, mbid):
        return True


class FakeCluster(object):
    def __init__(self, descName):
        self.__descName = descName

    def descName(self):
        return self.__descName


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

    def createTaskManager(self, dashlog, liveMoniClient, runDir, runCfg,
                          moniType):
        return FakeTaskManager()

    @classmethod
    def cycleComponents(self, compList, configDir, daqDataDir, logger, logPort,
                        livePort, verbose, killWith9, eventCheck,
                        checkExists=True):
        pass

    def queueForSpade(self, runData, duration):
        pass


class TestRunSet(unittest.TestCase):
    def __buildClusterConfig(self, compList, baseName):
        jvmPath = "java-" + baseName
        jvmArgs = "args=" + baseName

        clusterCfg = MockClusterConfig("CC-" + baseName)
        for c in compList:
            clusterCfg.addComponent(c.fullName(), jvmPath, jvmArgs,
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
            self.failUnless(c in statDict, 'Could not find ' + str(c))
            self.assertEqual(statDict[c], expState,
                             "Component %s: %s != expected %s" %
                             (c, statDict[c], expState))

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

        runConfig = FakeRunConfig("XXXrunSubXXX")

        cluCfg = FakeCluster("cluster-foo")

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

        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        stopCaller = "stopRun"

        logger.addExpectedRegexp("Could not stop run .* (%s)" % stopCaller)

        expState = "running"

        try:
            stopErr = runset.stopRun(stopCaller)
        except RunSetException as ve:
            if not "is not running" in str(ve):
                raise
            stopErr = False

        self.failIf(stopErr, "stopRun() encountered error")

        for comp in compList:
            if comp.isSource():
                comp.addBeanData("stringhub", "LatestFirstChannelHitTime", 10)
                comp.addBeanData("stringhub", "NumberOfNonZombies", 1)

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        domList = [('53494d550101', 0, 1, 2, 3, 4),
                   ['1001', '22', 1, 2, 3, 4, 5],
                   ('a', 0, 1, 2, 3, 4)]

        data = [domList[0], ['53494d550122', ] + domList[1][2:]]

        subrunNum = -1

        logger.addExpectedExact("Subrun %d: flashing DOM (%s)" %
                                (subrunNum, data))

        try:
            runset.subrun(subrunNum, data)
            if expectError is not None:
                self.fail("subrun should not have succeeded")
        except RunSetException as ve:
            if expectError is None:
                raise
            if not str(ve).endswith(expectError):
                self.fail("Expected subrun to fail with \"%s\", not \"%s\"" %
                          (expectError, str(ve)))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        for comp in compList:
            if comp.isSource():
                comp.addBeanData("stringhub", "EarliestLastChannelHitTime", 10)

        self.__stopRun(runset, runNum, runConfig, cluCfg, components=compList,
                       logger=logger)

    def __runTests(self, compList, runNum, hangType=None):
        logger = MockLogger('foo#0')

        num = 1
        for c in compList:
            c.setOrder(num)
            num += 1

        runConfig = FakeRunConfig("XXXrunCfgXXX")

        expId = RunSet.ID.peekNext()

        cluCfg = FakeCluster("cluster-foo")

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

            logger.addExpectedExact("RunSet #%d (%s): Waiting for %s %s" %
                                    (expId, expState, expState, cfgWaitStr))
            i += 1

        runset.configure()

        expState = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id(), expState))

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        expState = "ready"
        if len(compList) > 0:
            self.failUnless(self.__isCompListConfigured(compList),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(compList),
                        'Components should not be running')

        self.__checkStatus(runset, compList, expState)
        logger.checkStatus(10)

        logger.addExpectedRegexp("Could not stop run .*")

        self.assertRaises(RunSetException, runset.stopRun, ("RunTest"))
        logger.checkStatus(10)

        expState = "running"

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        expState = "stopping"

        for comp in compList:
            if comp.isSource():
                comp.addBeanData("stringhub", "EarliestLastChannelHitTime", 10)

        self.__stopRun(runset, runNum, runConfig, cluCfg, components=compList,
                       logger=logger, hangType=hangType)

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

    def __sortCmp(self, x, y):
        if y.order() is None:
            return -1
        elif x.order() is None:
            return 1
        else:
            return y.order() - x.order()

    def __startRun(self, runset, runNum, runConfig, cluCfg,
                   runOptions=RunOption.MONI_TO_NONE, versionInfo=None,
                   spadeDir="/tmp", copyDir=None, logDir=None,
                   components=None, logger=None):

        global CAUGHT_WARNING
        if not LIVE_IMPORT and not CAUGHT_WARNING:
            CAUGHT_WARNING = True
            logger.addExpectedRegexp(r"^Cannot import IceCube Live.*")

        if components is not None:
            for comp in components:
                if comp.isSource():
                    bean = "stringhub"
                    for fld in ("LatestFirstChannelHitTime",
                                "NumberOfNonZombies"):
                        try:
                            comp.getSingleBeanField(bean, fld)
                        except:
                            comp.addBeanData(bean, fld, 10)

        if versionInfo is None:
            versionInfo = {"filename": "fName",
                           "revision": "1234",
                           "date": "date",
                           "time": "time",
                           "author": "author",
                           "release": "rel",
                           "repo_rev": "1repoRev",
                           }

        expState = "running"

        logger.addExpectedExact("Starting run #%d on \"%s\"" %
                                (runNum, cluCfg.descName()))
        logger.addExpectedExact("Version info: " +
                                get_scmversion_str(info=versionInfo))

        logger.addExpectedExact("Run configuration: %s" % runConfig.basename())
        logger.addExpectedExact("Cluster: %s" % cluCfg.descName())

        logger.addExpectedExact("Starting run %d..." % runNum)

        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        runset.startRun(runNum, cluCfg, runOptions, versionInfo,
                        spadeDir, copyDir, logDir)
        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))

        if components is not None and len(components) > 0:
            self.failUnless(self.__isCompListConfigured(components),
                            'Components should be configured')
            self.failUnless(self.__isCompListRunning(components, runNum),
                            'Components should not be running')

        self.__checkStatus(runset, components, expState)
        logger.checkStatus(10)

    def __stopRun(self, runset, runNum, runConfig, cluCfg, components=None,
                  logger=None, hangType=0):
        expState = "stopping"

        compList = components
        if compList is not None:
            compList.sort(lambda x, y: self.__sortCmp(y, x))

        hangStr = None
        hangList = []
        if hangType > 0:
            for c in components:
                if c.isHanging():
                    hangList.append(c.fullName())
            hangStr = ", ".join(hangList)

        if hangType > 0:
            if len(hangList) < len(components):
                logger.addExpectedExact(("RunSet #%d run#%d (%s):" +
                                         " Waiting for %s %s") %
                                        (runset.id(), runNum, expState,
                                         expState, hangStr))
            if len(hangList) == 1:
                plural = ""
            else:
                plural = "s"
            logger.addExpectedExact(("RunSet #%d run#%d (%s):" +
                                     " Forcing %d component%s to stop: %s") %
                                    (runset.id(), runNum, "forcingStop",
                                     len(hangList), plural, hangStr))
            if hangType > 1:
                logger.addExpectedExact("FORCED_STOP failed for " + hangStr)

        logger.addExpectedExact("Reset duration")

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")

        expState = "ready"

        if hangType > 1:
            expState = "forcingStop"
            logger.addExpectedExact("Run terminated WITH ERROR.")
            logger.addExpectedExact(("RunSet #%d run#%d (%s):" +
                                     " Could not stop %s") %
                                    (runset.id(), runNum, expState, hangStr))
        else:
            logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        if hangType < 2:
            self.failIf(runset.stopRun("Test1"), "stopRun() encountered error")
            expState = "ready"
        else:
            try:
                if not runset.stopRun("Test2"):
                    self.fail("stopRun() should have failed")
            except RunSetException as rse:
                expMsg = "RunSet #%d run#%d (%s): Could not stop %s" % \
                         (runset.id(), runNum, expState, hangStr)
                self.assertEqual(str(rse), expMsg,
                                 ("For hangType %d expected exception %s," +
                                  " not %s") % (hangType, expMsg, rse))
            expState = "error"

        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id(), runNum, expState))
        self.assertFalse(runset.stopping(), "RunSet #%d is still stopping")

        RunXMLValidator.validate(self, runNum, runConfig.basename(),
                                 cluCfg.descName(), None, None, 0, 0, 0, 0,
                                 hangType > 1)

        if len(components) > 0:
            self.failUnless(self.__isCompListConfigured(components),
                            'Components should be configured')
            self.failIf(self.__isCompListRunning(components),
                        'Components should not be running')

        if hangType == 0:
            self.__checkStatus(runset, components, expState)
        logger.checkStatus(10)

    def setUp(self):
        RunXMLValidator.setUp()

    def tearDown(self):
        RunXMLValidator.tearDown()

    def testEmpty(self):
        self.__runTests([], 1)

    def testSet(self):
        compList = self.__buildCompList(("foo", "bar"))
        compList[0].setConfigureWait(1)

        self.__runTests(compList, 2)

    def testSubrunGood(self):
        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))

        self.__runSubrun(compList, 3)

    def testSubrunOneBad(self):

        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))
        compList[1].setBadHub()

        self.__runSubrun(compList, 4, expectError="on %s" %
                         compList[1].fullName())

    def testSubrunBothBad(self):

        compList = self.__buildCompList(("fooHub", "barHub", "bazBuilder"))
        compList[0].setBadHub()
        compList[1].setBadHub()

        self.__runSubrun(compList, 5, expectError="on any string hubs")

    def testStopHang(self):
        hangType = 1

        compList = self.__buildCompList(("foo", "bar"))
        compList[1].setHangType(hangType)

        RunSet.TIMEOUT_SECS = 5

        self.__runTests(compList, 6, hangType=hangType)

    def testForcedStopHang(self):
        hangType = 2

        compList = self.__buildCompList(("foo", "bar"))
        compList[1].setHangType(hangType)

        RunSet.TIMEOUT_SECS = 5

        self.__runTests(compList, 7, hangType=hangType)

    def testRestartFailCluCfg(self):
        compList = self.__buildCompList(("sleepy", "sneezy", "happy", "grumpy",
                                         "doc", "dopey", "bashful"))

        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        baseName = "failCluCfg"

        clusterCfg = self.__buildClusterConfig(compList[1:], baseName)

        logger.addExpectedExact(("Cannot restart %s: Not found" +
                                 " in cluster config %s") %
                                (compList[0].fullName(), clusterCfg))

        cycleList = compList[1:]
        cycleList.sort()

        errMsg = None
        for c in cycleList:
            if errMsg is None:
                errMsg = "Cycling components " + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
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

        longList.sort()

        errMsg = None
        for c in longList:
            if errMsg is None:
                errMsg = "Cycling components " + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
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
                errMsg = "Cycling components " + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
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
                errMsg = "Cycling components " + c.fullName()
            else:
                errMsg += ", " + c.fullName()
        if errMsg is not None:
            logger.addExpectedExact(errMsg)

        runset.restartAllComponents(clusterCfg, None, None, None, None,
                                    False, False, False)

    def testShortStopWithoutStart(self):
        compList = self.__buildCompList(("one", "two", "three"))
        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        compStr = "one#1, two#2, three#3"

        logger.addExpectedRegexp("Could not stop run .* RunSetException.*")
        logger.addExpectedExact("Failed to transition to ready: idle[%s]" %
                                compStr)
        logger.addExpectedExact("RunSet #%d (error): Could not stop idle[%s]" %
                                (runset.id(), compStr))

        try:
            self.failIf(runset.stopRun("ShortStop"),
                        "stopRun() encountered error")
            self.fail("stopRun() on new runset should throw exception")
        except Exception as ex:
            if str(ex) != "RunSet #%d is not running" % runset.id():
                raise

    def testShortStopNormal(self):
        compList = self.__buildCompList(("one", "two", "three"))
        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        runset.configure()

        runNum = 100
        cluCfg = FakeCluster("foo-cluster")

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        self.__stopRun(runset, runNum, runConfig, cluCfg, components=compList,
                       logger=logger)

    def testShortStopHang(self):
        compList = self.__buildCompList(("one", "two", "three"))
        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        runset.configure()

        runNum = 100
        cluCfg = FakeCluster("bar-cluster")

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        hangType = 2
        for c in compList:
            c.setHangType(hangType)

        RunSet.TIMEOUT_SECS = 5

        self.__stopRun(runset, runNum, runConfig, cluCfg, components=compList,
                       logger=logger, hangType=hangType)

    def testBadStop(self):
        compList = self.__buildCompList(("first", "middle", "middle",
                                         "middle", "middle", "last"))
        runConfig = FakeRunConfig("XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        runset = MyRunSet(MyParent(), runConfig, compList, logger)

        runset.configure()

        runNum = 543
        cluCfg = FakeCluster("bogusCluster")

        self.__startRun(runset, runNum, runConfig, cluCfg,
                        components=compList, logger=logger)

        for comp in compList:
            comp.setStopFail()

        RunSet.TIMEOUT_SECS = 5

        compStr = "first#1, middle#2-5, last#6"

        logger.addExpectedExact("Reset duration")

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        logger.addExpectedExact(("RunSet #1 run#%d (forcingStop):" +
                                 " Forcing 6 components to stop: %s") %
                                 (runNum, compStr))
        logger.addExpectedExact("STOP_RUN failed for " + compStr)
        logger.addExpectedExact("Failed to transition to ready: stopping[%s]" %
                                compStr)

        stopErrMsg = ("RunSet #%d run#%d (error): Could not stop" +
                      " stopping[%s]") % (runset.id(), runNum, compStr)
        logger.addExpectedExact(stopErrMsg)

        try:
            try:
                runset.stopRun("BadStop")
            except RunSetException as rse:
                self.assertEqual(str(rse), stopErrMsg,
                                 "Expected exception %s, not %s" %
                                 (rse, stopErrMsg))
        finally:
            RunXMLValidator.validate(self, runNum, runConfig.basename(),
                                     cluCfg.descName(), None, None, 0, 0, 0,
                                     0, False)

    def testListCompRanges(self):

        compNames = ("fooHub", "barHub", "fooHub", "fooHub", "fooHub",
                     "barHub", "barHub", "zabTrigger", "fooHub", "fooHub",
                     "barHub", "bazBuilder")

        compList = []

        nextNum = 1
        for name in compNames:
            if name.endswith("Hub"):
                num = nextNum
            else:
                num = 0
            c = MockComponent(name, num)
            c.setOrder(nextNum)
            compList.append(c)

            nextNum += 1

        str = listComponentRanges(compList)

        expStr = "fooHub#1,3-5,9-10, barHub#2,6-7,11, zabTrigger, bazBuilder"
        self.assertEqual(str, expStr,
                         "Expected legible list \"%s\", not \"%s\"" %
                         (expStr, str))


if __name__ == '__main__':
    unittest.main()
