#!/usr/bin/env python

import shutil
import tempfile
import unittest
from locate_pdaq import set_pdaq_config_dir
from CnCServer import DAQPool
from DAQClient import DAQClientState
from DAQLog import LogSocketServer
from RunOption import RunOption
from RunSet import RunSet, ConnectionException

from DAQMocks import MockComponent, MockLeapsecondFile, MockLogger, \
    MockRunConfigFile


class FakeLogger(object):
    def __init__(self, port):
        if port is None:
            port = LogSocketServer.next_log_port

        self.__port = port

    @property
    def port(self):
        return self.__port

    def stop_serving(self):
        pass


class FakeCluster(object):
    def __init__(self, descName):
        self.__descName = descName

    @property
    def description(self):
        return self.__descName


class MockRunData(object):
    def __init__(self, run_num, clusterConfigName, runOptions, version_info,
                 spade_dir, copy_dir, log_dir, testing=True):
        self.__run_number = run_num

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
    def is_error_enabled(self):
        return self.__logger.is_error_enabled

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

    def send_event_counts(self, run_set=None):
        pass

    @property
    def set_finished(self):
        self.__finished = True

    def set_mock_logger(self, logger):
        self.__logger = logger

    def stop_tasks(self):
        pass


class MyRunSet(RunSet):
    def __init__(self, parent, run_config, comp_list, logger):
        self.__logger = logger
        self.__logDict = {}

        super(MyRunSet, self).__init__(parent, run_config, comp_list, logger)

    @classmethod
    def create_component_log(cls, run_dir, comp, host, port, quiet=True):
        return FakeLogger(port)

    def create_run_data(self, run_num, clusterConfigName, runOptions,
                        version_info, spade_dir, copy_dir=None, log_dir=None):
        mrd = MockRunData(run_num, clusterConfigName, runOptions, version_info,
                          spade_dir, copy_dir, log_dir, True)
        mrd.set_mock_logger(self.getLog("dashLog"))
        return mrd

    def final_report(self, comps, runData, had_error=False, switching=False):
        self.__logger.error("MockRun final report")

    def finish_setup(self, run_data, start_time):
        pass

    def get_event_counts(self, run_num, run_data=None):
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
        if name not in self.__logDict:
            self.__logDict[name] = MockLogger(name)

        return self.__logDict[name]

    @staticmethod
    def report_good_time(run_data, name, daq_time):
        pass


class MyDAQPool(DAQPool):
    def __init__(self):
        super(MyDAQPool, self).__init__()

    def create_runset(self, run_config, comp_list, logger):
        return MyRunSet(self, run_config, comp_list, logger)

    def return_runset_components(self, rs, verbose=False, kill_with_9=False,
                                 event_check=False):
        rs.return_components(self, None, None, None, None, None,
                             verbose=verbose, kill_with_9=kill_with_9,
                             event_check=event_check)

    def save_catchall(self, run_dir):
        pass


class TestDAQPool(unittest.TestCase):
    def __check_runset_state(self, runset, exp_state):
        for c in runset.components():
            self.assertEqual(c.state, exp_state,
                             "Comp %s state should be %s, not %s" %
                             (c.name, exp_state, c.state))

    def __createRunConfigFile(self, comp_list):
        rcFile = MockRunConfigFile(self.__run_config_dir)

        run_comp_list = []
        for c in comp_list:
            run_comp_list.append(c.fullname)

        return rcFile.create(run_comp_list, {})

    def setUp(self):
        self.__run_config_dir = None

        set_pdaq_config_dir(None, override=True)

    def tearDown(self):
        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)

        set_pdaq_config_dir(None, override=True)

    def testEmpty(self):
        mgr = DAQPool()

        runset = mgr.find_runset(1)
        self.assertFalse(runset is not None, 'Found set in empty manager')

        mgr.remove(MockComponent('foo', 0))

    def testAddRemove(self):
        mgr = DAQPool()

        comp_list = []

        comp = MockComponent('foo', 0)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp_list.append(comp)

        self.assertEqual(mgr.num_unused, 0)
        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_unused, len(comp_list))
        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_unused, 0)
        self.assertEqual(mgr.num_components, 0)

    def testBuildReturnSet(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 1234)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)
        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = mgr.make_runset(self.__run_config_dir, run_config, 0, 0,
                                 logger, daq_data_dir, force_restart=False,
                                 strict=False)

        self.assertEqual(mgr.num_components, 0)

        found = mgr.find_runset(runset.id)
        self.assertFalse(found is None, "Couldn't find runset #%d" % runset.id)

        mgr.return_runset(runset, logger)

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMissingOneOutput(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        inputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp.addInput(inputName, 123)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 456)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMissingMultiOutput(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        inputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addInput(inputName, 123)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput(inputName, 456)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No outputs found for %s inputs" % inputName) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiOutput(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        inputNames = ["xxx", "yyy"]
        outputName = "aaa"

        inputNames.sort()

        comp = MockComponent('fooHub', 0)
        comp.addInput(inputNames[0], 123)
        comp.addInput(inputNames[1], 456)
        comp.addOutput(outputName)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput(outputName, 789)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No outputs found for %s inputs" %
                            inputNames[0]) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMissingOneInput(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        outputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 123)
        comp.addOutput(outputName)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingInput(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        comp = MockComponent('fooHub', 0)
        comp_list.append(comp)

        outputName = "xxx"

        comp = MockComponent('bar', 0)
        comp.addOutput('xxx')
        comp.addOutput('yyy')
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiInput(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        outputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp.addOutput(outputName)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 123)
        comp.addOutput(outputName)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("No inputs found for %s outputs" %
                            outputName) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMultiMissing(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        outputName = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.addInput(outputName, 123)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addOutput(outputName)
        comp_list.append(comp)

        comp = MockComponent('feeHub', 0)
        comp.addInput(outputName, 456)
        comp_list.append(comp)

        comp = MockComponent('baz', 0)
        comp.addOutput(outputName)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as ce:
            if str(ce).find("Found 2 %s inputs for 2 outputs" %
                            (outputName, )) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testBuildMultiInput(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('conn')
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('conn', 123)
        comp_list.append(comp)

        comp = MockComponent('baz', 0)
        comp.addInput('conn', 456)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = mgr.make_runset(self.__run_config_dir, run_config, 0, 0,
                                 logger, daq_data_dir, force_restart=False,
                                 strict=False)

        self.assertEqual(mgr.num_components, 0)

        found = mgr.find_runset(runset.id)
        self.assertFalse(found is None, "Couldn't find runset #%d" % runset.id)

        mgr.return_runset(runset, logger)

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            mgr.remove(c)

        self.assertEqual(mgr.num_components, 0)

        logger.checkStatus(10)

    def testStartRun(self):
        self.__run_config_dir = tempfile.mkdtemp()
        set_pdaq_config_dir(self.__run_config_dir, override=True)

        mgr = MyDAQPool()

        aComp = MockComponent('aHub', 0)
        aComp.addOutput('ab')

        bComp = MockComponent('b', 0)
        bComp.addInput('ab', 123)
        bComp.addOutput('bc')

        cComp = MockComponent('eventBuilder', 0)
        cComp.addInput('bc', 456)

        comp_list = [cComp, aComp, bComp]

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        MockLeapsecondFile(self.__run_config_dir).create()

        run_config = self.__createRunConfigFile(comp_list)

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = mgr.make_runset(self.__run_config_dir, run_config, 0, 0,
                                 logger, daq_data_dir, force_restart=False,
                                 strict=False)

        self.assertEqual(mgr.num_components, 0)
        self.assertEqual(runset.size(), len(comp_list))

        self.__check_runset_state(runset, 'ready')

        clusterCfg = FakeCluster("cluster-foo")

        self.__check_runset_state(runset, 'ready')

        run_num = 1
        moniType = RunOption.MONI_TO_NONE

        logger.addExpectedExact("Starting run #%d on \"%s\"" %
                                (run_num, clusterCfg.description))

        dashLog = runset.getLog("dashLog")

        dashLog.addExpectedExact("Starting run %d..." % run_num)

        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        aComp.mbean.addData("stringhub", "LatestFirstChannelHitTime", 10)
        aComp.mbean.addData("stringhub", "NumberOfNonZombies", 1)

        version_info = {
            "filename": "fName",
            "revision": "1234",
            "date": "date",
            "time": "time",
            "author": "author",
            "release": "rel",
            "repo_rev": "1repoRev",
        }

        spade_dir = "/tmp"
        copy_dir = None

        runset.start_run(run_num, clusterCfg, moniType, version_info,
                         spade_dir, copy_dir)

        self.__check_runset_state(runset, 'running')
        dashLog.checkStatus(10)

        num_evts = 1
        num_moni = 0
        num_sn = 0
        num_tcal = 0

        firstTime = 12345678
        lastTime = 23456789

        cComp.mbean.addData("backEnd", "FirstEventTime", firstTime)
        cComp.mbean.addData("backEnd", "EventData",
                            (run_num, num_evts, lastTime))
        cComp.mbean.addData("backEnd", "GoodTimes", (firstTime, lastTime))

        monDict = runset.get_event_counts(run_num)
        self.assertEqual(monDict["physicsEvents"], num_evts)

        dashLog.addExpectedExact("Not logging to file so cannot queue to"
                                 " SPADE")

        stopName = "TestStartRun"
        dashLog.addExpectedExact("Stopping the run (%s)" % stopName)

        logger.addExpectedExact("MockRun final report")

        aComp.mbean.addData("stringhub", "EarliestLastChannelHitTime", 10)

        self.assertFalse(runset.stop_run(stopName),
                         "stop_run() encountered error")

        self.__check_runset_state(runset, 'ready')
        dashLog.checkStatus(10)

        mgr.return_runset(runset, logger)

        self.assertEqual(runset.id, None)
        self.assertEqual(runset.configured(), False)
        self.assertEqual(runset.run_number(), None)

        self.assertEqual(mgr.num_components, len(comp_list))
        self.assertEqual(runset.size(), 0)

        logger.checkStatus(10)
        dashLog.checkStatus(10)

    def testMonitorClients(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        fooHub = MockComponent('fooHub', 0)
        fooHub.addOutput('conn')
        comp_list.append(fooHub)

        barComp = MockComponent('bar', 0)
        barComp.addInput('conn', 123)
        comp_list.append(barComp)

        bazComp = MockComponent('baz', 0)
        bazComp.addInput('conn', 456)
        comp_list.append(bazComp)

        self.assertEqual(mgr.num_components, 0)

        for c in comp_list:
            mgr.add(c)

        self.assertEqual(mgr.num_components, len(comp_list))

        for c in comp_list:
            c.setMonitorState("idle")

        cnt = mgr.monitor_clients()
        self.assertEqual(cnt, len(comp_list))

        for c in comp_list:
            self.assertEqual(c.monitor_count, 1)

        fooHub.setMonitorState(DAQClientState.DEAD)
        bazComp.setMonitorState(DAQClientState.MISSING)

        self.assertEqual(mgr.num_components, len(comp_list))

        cnt = mgr.monitor_clients()

        self.assertEqual(cnt, 1)
        self.assertEqual(mgr.num_components, 2)

        for c in comp_list:
            self.assertEqual(c.monitor_count, 2)


if __name__ == '__main__':
    unittest.main()
