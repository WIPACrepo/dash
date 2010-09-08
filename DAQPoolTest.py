#!/usr/bin/env python

import shutil, tempfile, unittest
from CnCServer import DAQPool
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet, ConnectionException

from DAQMocks import MockComponent, MockLogger, MockRunConfigFile

ACTIVE_WARNING = False

class FakeLogger(object):
    def __init__(self): pass
    def stopServing(self): pass

class FakeTaskManager(object):
    def __init__(self): pass
    def reset(self): pass
    def start(self): pass
    def stop(self): pass

class MyRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger):
        self.__logDict = {}

        super(MyRunSet, self).__init__(parent, runConfig, compList, logger)

    def createComponentLog(self, runDir, c, host, port, liveHost, livePort,
                           quiet=True):
        return FakeLogger()

    def createDashLog(self):
        return self.getLog("dashLog")

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir=None, logDir=None):
        return super(MyRunSet, self).createRunData(runNum, clusterConfigName,
                                                   runOptions, versionInfo,
                                                   spadeDir, copyDir, logDir,
                                                   True)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        return None

    def createTaskManager(self, dashlog, liveMoniClient, runDir, moniType):
        return FakeTaskManager()

    def getLog(self, name):
        if not self.__logDict.has_key(name):
            self.__logDict[name] = MockLogger(name)

        return self.__logDict[name]

    def queueForSpade(self, duration):
        pass

class MyDAQPool(DAQPool):
    def __init__(self):
        super(MyDAQPool, self).__init__()

    def createRunset(self, runConfig, compList, logger):
        return MyRunSet(self, runConfig, compList, logger)

    def returnRunsetComponents(self, rs, verbose=False, killWith9=True,
                               eventCheck=False):
        rs.returnComponents(self, None, None, None, None, None, None, None,
                            None)

class TestDAQPool(unittest.TestCase):
    def __checkRunsetState(self, runset, expState):
        for c in runset.components():
            self.assertEquals(c.state(), expState,
                              "Comp %s state should be %s, not %s" %
                              (c.name(), expState, c.state()))

    def __createRunConfigFile(self, compList):
        rcFile = MockRunConfigFile(self.__runConfigDir)

        runCompList = []
        for c in compList:
            runCompList.append(c.fullName())

        return rcFile.create(runCompList, [])

    def setUp(self):
        self.__runConfigDir = None

    def tearDown(self):
        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)

    def testEmpty(self):
        mgr = DAQPool()

        runset = mgr.findRunset(1)
        self.failIf(runset is not None, 'Found set in empty manager')

        mgr.remove(MockComponent('foo', 0))

    def testAddRemove(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)
        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numUnused(), len(compList))
        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)
        self.assertEqual(mgr.numComponents(), 0)

    def testBuildReturnSet(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 1234)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)
        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedRegexp("Built runset #\d+: .*")

        runset = mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                                forceRestart=False, strict=False)

        self.assertEqual(mgr.numComponents(), 0)

        found = mgr.findRunset(runset.id())
        self.failIf(found is None, "Couldn't find runset #%d" % runset.id())

        mgr.returnRunset(runset)

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMissingOneOutput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = DAQPool()

        compList = []

        inputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp.addInput(inputName, 123)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 456)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                           forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException, ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise ce

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMissingMultiOutput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = DAQPool()

        compList = []

        inputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addInput(inputName, 123)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput(inputName, 456)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                           forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException, ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise ce

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiOutput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = DAQPool()

        compList = []

        inputName = "yyy"

        comp = MockComponent('fooHub', 0)
        comp.addInput('xxx', 123)
        comp.addInput(inputName, 456)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 789)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                           forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException, ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise ce

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMissingOneInput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = DAQPool()

        compList = []

        outputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 123)
        comp.addOutput(outputName)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                           forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException, ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise ce

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingInput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        compList.append(comp)

        outputName = "xxx"

        comp = MockComponent('bar', 0)
        comp.addOutput('xxx')
        comp.addOutput('yyy')
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                           forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException, ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise ce

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiInput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = DAQPool()

        compList = []

        outputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp.addOutput(outputName)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 123)
        comp.addOutput(outputName)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                           forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException, ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise ce

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMultiMissing(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = DAQPool()

        compList = []

        outputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addInput(outputName, 123)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addOutput(outputName)
        compList.append(comp)

        comp = MockComponent('feeHub', 0)
        comp.addInput(outputName, 456)
        compList.append(comp)

        comp = MockComponent('baz', 0)
        comp.addOutput(outputName)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                           forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException, ce:
            if str(ce).find("Found 2 %s inputs for 2 outputs" % outputName) < 0:
                raise ce

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMultiInput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('conn')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('conn', 123)
        compList.append(comp)

        comp = MockComponent('baz', 0)
        comp.addInput('conn', 456)
        compList.append(comp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedRegexp("Built runset #\d+: .*")

        runset = mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                                forceRestart=False, strict=False)

        self.assertEqual(mgr.numComponents(), 0)

        found = mgr.findRunset(runset.id())
        self.failIf(found is None, "Couldn't find runset #%d" % runset.id())

        mgr.returnRunset(runset)

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testStartRun(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        a = MockComponent('aHub', 0)
        a.addOutput('ab')

        b = MockComponent('b', 0)
        b.addInput('ab', 123)
        b.addOutput('bc')

        c = MockComponent('c', 0)
        c.addInput('bc', 456)

        compList = [c, a, b]

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedRegexp("Built runset #\d+: .*")

        runset = mgr.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                                forceRestart=False, strict=False)

        self.assertEqual(mgr.numComponents(), 0)
        self.assertEqual(runset.size(), len(compList))

        self.__checkRunsetState(runset, 'ready')

        clusterName = "cluster-foo"

        dashLog = runset.getLog("dashLog")
        dashLog.addExpectedRegexp(r"Version info: \S+ \d+ \S+ \S+ \S+ \S+" +
                                  r" \d+\S*")
        dashLog.addExpectedExact("Run configuration: %s" % runConfig)
        dashLog.addExpectedExact("Cluster configuration: %s" % clusterName)

        self.__checkRunsetState(runset, 'ready')

        runNum = 1
        moniType = RunOption.MONI_TO_NONE

        logger.addExpectedExact("Starting run #%d with \"%s\"" %
                                (runNum, clusterName))

        dashLog.addExpectedExact("Starting run %d..." % runNum)

        global ACTIVE_WARNING
        if not LIVE_IMPORT and not ACTIVE_WARNING:
            ACTIVE_WARNING = True
            dashLog.addExpectedExact("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        versionInfo = {"filename": "fName",
                       "revision": "1234",
                       "date": "date",
                       "time": "time",
                       "author": "author",
                       "release": "rel",
                       "repo_rev": "1repoRev",
                       }

        spadeDir = "/tmp"
        copyDir = None

        runset.startRun(runNum, clusterName, moniType, versionInfo, spadeDir,
                        copyDir)

        self.__checkRunsetState(runset, 'running')

        numEvts = 0
        numSecs = 0
        numMoni = 0
        numSN = 0
        numTcals = 0

        dashLog.addExpectedExact("%d physics events collected in %d seconds" %
                                 (numEvts, numSecs))
        dashLog.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                 (numMoni, numSN, numTcals))
        dashLog.addExpectedExact("Run terminated SUCCESSFULLY.")

        runset.stopRun()

        self.__checkRunsetState(runset, 'ready')

        mgr.returnRunset(runset)

        self.assertEqual(runset.id(), None)
        self.assertEqual(runset.configured(), False)
        self.assertEqual(runset.runNumber(), None)

        self.assertEqual(mgr.numComponents(), len(compList))
        self.assertEqual(runset.size(), 0)

        logger.checkStatus(10)

if __name__ == '__main__':
    unittest.main()
