#!/usr/bin/env python

import shutil
import tempfile
import unittest
from locate_pdaq import set_pdaq_config_dir
from CnCServer import DAQPool
from DAQClient import DAQClientState
from DAQTime import PayloadTime
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet, ConnectionException

from DAQMocks import MockComponent, MockLeapsecondFile, MockLogger, \
    MockRunConfigFile


class FakeLogger(object):
    def __init__(self):
        pass

    def stopServing(self):
        pass


class FakeCluster(object):
    def __init__(self, descName):
        self.__descName = descName

    @property
    def description(self):
        return self.__descName

class MockRunData(object):
    def __init__(self, runNum, clusterConfigName, runOptions, versionInfo,
                 spadeDir, copyDir, logDir, testing=True):
        self.__run_number = runNum

        self.__logger = None
        self.__finished = False

    def connect_to_live(self):
        pass

    def error(self, logmsg):
        if self.__logger is None:
            raise Exception("Mock logger has not been set")
        self.__logger.error(logmsg)

    @property
    def finished(self):
        return self.__finished

    @property
    def has_moni_client(self):
        return True

    @property
    def isErrorEnabled(self):
        return self.__logger.isErrorEnabled

    @property
    def log_directory(self):
        return None

    def reset(self):
        pass

    @property
    def run_directory(self):
        return "/bad/path"

    @property
    def run_number(self):
        return self.__run_number

    def send_count_updates(self, moni_data, prio):
        pass

    def send_moni(self, name, value, prio=None, time=None, debug=False):
        pass

    def set_finished(self):
        self.__finished = True

    def set_mock_logger(self, logger):
        self.__logger = logger

    def stop(self):
        pass

    def stop_tasks(self):
        pass

    @property
    def subrun_number(self):
        return 0


class MyRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger):
        self.__logger = logger
        self.__logDict = {}

        super(MyRunSet, self).__init__(parent, runConfig, compList, logger)

    @classmethod
    def create_component_log(cls, runDir, comp, host, port, liveHost,
                             livePort, quiet=True):
        return FakeLogger()

    def create_run_data(self, runNum, clusterConfigName, runOptions,
                        versionInfo, spadeDir, copyDir=None, logDir=None):
        mrd = MockRunData(runNum, clusterConfigName, runOptions, versionInfo,
                          spadeDir, copyDir, logDir, True)
        mrd.set_mock_logger(self.getLog("dashLog"))
        return mrd

    def final_report(self, comps, runData, had_error=False, switching=False):
        self.__logger.error("MockRun final report")

    def finish_setup(self, run_data, start_time):
        pass

    def get_event_counts(self, comps=None, update_counts=True):
        return {
            "physicsEvents": 1,
            "eventPayloadTicks": -100,
            "wallTime": None,
            "moniEvents": 1,
            "moniTime": 99,
            "snEvents": 1,
            "snTime": 98,
            "tcalEvents": 1,
            "tcalTime": 97,
        }

    def getLog(self, name):
        if not name in self.__logDict:
            self.__logDict[name] = MockLogger(name)

        return self.__logDict[name]

    def report_good_time(self, run_data, name, daq_time):
        pass


class MyDAQPool(DAQPool):
    def __init__(self):
        super(MyDAQPool, self).__init__()

    def createRunset(self, runConfig, compList, logger):
        return MyRunSet(self, runConfig, compList, logger)

    def returnRunsetComponents(self, rs, verbose=False, killWith9=True,
                               eventCheck=False):
        rs.return_components(self, None, None, None, None, None, None, None,
                             None)

    def saveCatchall(self, runDir):
        pass


class TestDAQPool(unittest.TestCase):
    def __checkRunsetState(self, runset, expState):
        for c in runset.components():
            self.assertEqual(c.state, expState,
                             "Comp %s state should be %s, not %s" %
                             (c.name, expState, c.state))

    def __createRunConfigFile(self, compList):
        rcFile = MockRunConfigFile(self.__runConfigDir)

        runCompList = []
        for c in compList:
            runCompList.append(c.fullname)

        return rcFile.create(runCompList, {})

    def setUp(self):
        self.__runConfigDir = None

        set_pdaq_config_dir(None, override=True)

    def tearDown(self):
        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)

        set_pdaq_config_dir(None, override=True)

    def testEmpty(self):
        mgr = DAQPool()

        runset = mgr.findRunset(1)
        self.assertFalse(runset is not None, 'Found set in empty manager')

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
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        daqDataDir = None

        runset = mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                                daqDataDir, forceRestart=False, strict=False)

        self.assertEqual(mgr.numComponents(), 0)

        found = mgr.findRunset(runset.id)
        self.assertFalse(found is None, "Couldn't find runset #%d" % runset.id)

        mgr.returnRunset(runset, logger)

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMissingOneOutput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

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

        daqDataDir = None

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                           daqDataDir, forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMissingMultiOutput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

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

        daqDataDir = None

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                           daqDataDir, forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiOutput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

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

        daqDataDir = None

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                           daqDataDir, forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMissingOneInput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

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

        daqDataDir = None

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                           daqDataDir, forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingInput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

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

        daqDataDir = None

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                           daqDataDir, forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiInput(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

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

        daqDataDir = None

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                           daqDataDir, forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testBuildMultiMissing(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

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

        daqDataDir = None

        try:
            mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                           daqDataDir, forceRestart=False, strict=False)
            self.fail("makeRunset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("Found 2 %s inputs for 2 outputs" % \
                                outputName) < 0:
                raise

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
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        daqDataDir = None

        runset = mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                                daqDataDir, forceRestart=False, strict=False)

        self.assertEqual(mgr.numComponents(), 0)

        found = mgr.findRunset(runset.id)
        self.assertFalse(found is None, "Couldn't find runset #%d" % runset.id)

        mgr.returnRunset(runset, logger)

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numComponents(), 0)

        logger.checkStatus(10)

    def testStartRun(self):
        self.__runConfigDir = tempfile.mkdtemp()
        set_pdaq_config_dir(self.__runConfigDir, override=True)

        mgr = MyDAQPool()

        aComp = MockComponent('aHub', 0)
        aComp.addOutput('ab')

        bComp = MockComponent('b', 0)
        bComp.addInput('ab', 123)
        bComp.addOutput('bc')

        cComp = MockComponent('eventBuilder', 0)
        cComp.addInput('bc', 456)

        compList = [cComp, aComp, bComp]

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        MockLeapsecondFile(self.__runConfigDir).create()

        runConfig = self.__createRunConfigFile(compList)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        daqDataDir = None

        runset = mgr.makeRunset(self.__runConfigDir, runConfig, 0, 0, logger,
                                daqDataDir, forceRestart=False, strict=False)

        self.assertEqual(mgr.numComponents(), 0)
        self.assertEqual(runset.size(), len(compList))

        self.__checkRunsetState(runset, 'ready')

        clusterCfg = FakeCluster("cluster-foo")

        self.__checkRunsetState(runset, 'ready')

        runNum = 1
        moniType = RunOption.MONI_TO_NONE

        logger.addExpectedExact("Starting run #%d on \"%s\"" %
                                (runNum, clusterCfg.description))

        dashLog = runset.getLog("dashLog")
        #dashLog.addExpectedRegexp(r"MockRun finished setup")

        dashLog.addExpectedExact("Starting run %d..." % runNum)

        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        aComp.mbean.addData("stringhub", "LatestFirstChannelHitTime", 10)
        aComp.mbean.addData("stringhub", "NumberOfNonZombies", 1)

        versionInfo = {
            "filename": "fName",
            "revision": "1234",
            "date": "date",
            "time": "time",
            "author": "author",
            "release": "rel",
            "repo_rev": "1repoRev",
        }

        spadeDir = "/tmp"
        copyDir = None

        runset.start_run(runNum, clusterCfg, moniType, versionInfo, spadeDir,
                         copyDir)

        self.__checkRunsetState(runset, 'running')
        dashLog.checkStatus(10)

        numEvts = 1
        numMoni = 0
        numSN = 0
        numTcal = 0

        firstTime = 12345678L
        lastTime = 23456789L

        cComp.mbean.addData("backEnd", "FirstEventTime", firstTime)
        cComp.mbean.addData("backEnd", "EventData", (numEvts, lastTime))
        cComp.mbean.addData("backEnd", "GoodTimes", (firstTime, lastTime))

        monDict = runset.get_event_counts()
        self.assertEqual(monDict["physicsEvents"], numEvts)

        dashLog.addExpectedExact("Not logging to file so cannot queue to"
                                 " SPADE")

        stopName = "TestStartRun"
        dashLog.addExpectedExact("Stopping the run (%s)" % stopName)

        logger.addExpectedExact("MockRun final report")

        aComp.mbean.addData("stringhub", "EarliestLastChannelHitTime", 10)

        self.assertFalse(runset.stop_run(stopName),
                         "stop_run() encountered error")

        self.__checkRunsetState(runset, 'ready')
        dashLog.checkStatus(10)

        mgr.returnRunset(runset, logger)

        self.assertEqual(runset.id, None)
        self.assertEqual(runset.configured(), False)
        self.assertEqual(runset.run_number(), None)

        self.assertEqual(mgr.numComponents(), len(compList))
        self.assertEqual(runset.size(), 0)

        logger.checkStatus(10)
        dashLog.checkStatus(10)

    def testMonitorClients(self):
        self.__runConfigDir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        compList = []

        fooHub = MockComponent('fooHub', 0)
        fooHub.addOutput('conn')
        compList.append(fooHub)

        barComp = MockComponent('bar', 0)
        barComp.addInput('conn', 123)
        compList.append(barComp)

        bazComp = MockComponent('baz', 0)
        bazComp.addInput('conn', 456)
        compList.append(bazComp)

        self.assertEqual(mgr.numComponents(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numComponents(), len(compList))

        for c in compList:
            c.setMonitorState("idle")

        cnt = mgr.monitorClients()
        self.assertEqual(cnt, len(compList))

        for c in compList:
            self.assertEqual(c.monitorCount(), 1)

        fooHub.setMonitorState(DAQClientState.DEAD)
        bazComp.setMonitorState(DAQClientState.MISSING)

        self.assertEqual(mgr.numComponents(), len(compList))

        cnt = mgr.monitorClients()

        self.assertEqual(cnt, 1)
        self.assertEqual(mgr.numComponents(), 2)

        for c in compList:
            self.assertEqual(c.monitorCount(), 2)

if __name__ == '__main__':
    unittest.main()
