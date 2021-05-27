#!/usr/bin/env python

import shutil
import tempfile
import unittest
from locate_pdaq import set_pdaq_config_dir
from CnCServer import DAQPool
from DAQClient import DAQClientState
from DAQLog import LogSocketServer
from RunOption import RunOption
from RunSet import RunData, RunSet, ConnectionException

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
    def __init__(self, desc_name):
        self.__desc_name = desc_name

    @property
    def description(self):
        return self.__desc_name


class MockRunData(object):
    def __init__(self, run_num, logger):
        self.__run_number = run_num
        self.__logger = logger

        self.__finished = False

    def connect_to_live(self):
        pass

    @property
    def dom_mode(self):
        return RunData.DOMMODE_NORMAL

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

    def set_finished(self):
        self.__finished = True

    def stop_tasks(self):
        pass


class MyRunSet(RunSet):
    def __init__(self, parent, run_config, comp_list, logger):
        self.__logger = logger
        self.__log_dict = {}

        super(MyRunSet, self).__init__(parent, run_config, comp_list, logger)

    @classmethod
    def create_component_log(cls, run_dir, comp, port, quiet=True):
        return FakeLogger(port)

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, jade_dir, copy_dir=None, log_dir=None):
        return MockRunData(run_num, self.get_log("dashLog"))

    def final_report(self, comps, run_data, had_error=False, switching=False):
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

    def get_log(self, name):
        if name not in self.__log_dict:
            self.__log_dict[name] = MockLogger(name)

        return self.__log_dict[name]

    @staticmethod
    def report_good_time(run_data, name, pay_time):
        pass


class MyDAQPool(DAQPool):
    def create_runset(self, run_config, comp_list, logger):
        return MyRunSet(self, run_config, comp_list, logger)

    def get_cluster_config(self, run_config=None):
        raise NotImplementedError("Unimplemented")

    def return_runset_components(self, runset, verbose=False,
                                 kill_with_9=True, event_check=False):
        runset.return_components(self, None, None, None, verbose=verbose,
                                 kill_with_9=kill_with_9,
                                 event_check=event_check)

    def save_catchall(self, run_dir):
        pass


class TestDAQPool(unittest.TestCase):
    def __check_runset_state(self, runset, exp_state):
        for comp in runset.components:
            self.assertEqual(comp.state, exp_state,
                             "Comp %s state should be %s, not %s" %
                             (comp.name, exp_state, comp.state))

    def __create_run_config_file(self, comp_list):
        rcfile = MockRunConfigFile(self.__run_config_dir)

        run_comp_list = []
        for comp in comp_list:
            run_comp_list.append(comp.fullname)

        return rcfile.create(run_comp_list, {})

    def setUp(self):
        self.__run_config_dir = None

        set_pdaq_config_dir(None, override=True)

    def tearDown(self):
        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)

        set_pdaq_config_dir(None, override=True)

    def test_empty(self):
        mgr = DAQPool()

        runset = mgr.find_runset(1)
        self.assertFalse(runset is not None, 'Found set in empty manager')

        mgr.remove(MockComponent('foo', 0))

    def test_add_remove(self):
        mgr = DAQPool()

        comp_list = []

        comp = MockComponent('foo', 0)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp_list.append(comp)

        self.assertEqual(mgr.num_unused, 0)
        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_unused, len(comp_list))
        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_unused, 0)
        self.assertEqual(mgr.num_components, 0)

    def test_build_return_set(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        comp = MockComponent('fooHub', 0)
        comp.add_mock_output('aaa')
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_input('aaa', 1234)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)
        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_regexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = mgr.make_runset(self.__run_config_dir, run_config, 0, 0,
                                 logger, daq_data_dir, force_restart=False,
                                 strict=False)

        self.assertEqual(mgr.num_components, 0)

        found = mgr.find_runset(runset.id)
        self.assertFalse(found is None, "Couldn't find runset #%d" % runset.id)

        mgr.return_runset(runset, logger)

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_missing_one_output(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        input_name = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.add_mock_output('aaa')
        comp.add_mock_input(input_name, 123)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_input('aaa', 456)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as cex:
            exp_str = "No outputs found for %s inputs" % input_name
            if str(cex).find(exp_str) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_missing_multi_output(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        input_name = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.add_mock_input(input_name, 123)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_input(input_name, 456)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as cex:
            exp_str = "No outputs found for %s inputs" % input_name
            if str(cex).find(exp_str) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_match_plus_missing_multi_output(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        input_names = ["xxx", "yyy"]
        output_name = "aaa"

        input_names.sort()

        comp = MockComponent('fooHub', 0)
        comp.add_mock_input(input_names[0], 123)
        comp.add_mock_input(input_names[1], 456)
        comp.add_mock_output(output_name)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_input(output_name, 789)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as cex:
            if str(cex).find("No outputs found for %s inputs" %
                             input_names[0]) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_missing_one_input(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        output_name = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.add_mock_output('aaa')
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_input('aaa', 123)
        comp.add_mock_output(output_name)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as cex:
            if str(cex).find("No inputs found for %s outputs" %
                             output_name) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_match_plus_missing_input(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        comp = MockComponent('fooHub', 0)
        comp_list.append(comp)

        output_name = "xxx"

        comp = MockComponent('bar', 0)
        comp.add_mock_output('xxx')
        comp.add_mock_output('yyy')
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as cex:
            if str(cex).find("No inputs found for %s outputs" %
                             output_name) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_match_plus_missing_multi_input(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        output_name = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.add_mock_output('aaa')
        comp.add_mock_output(output_name)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_input('aaa', 123)
        comp.add_mock_output(output_name)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as cex:
            if str(cex).find("No inputs found for %s outputs" %
                             output_name) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_multi_missing(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        output_name = "xxx"

        comp = MockComponent('fooHub', 0)
        comp.add_mock_input(output_name, 123)
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_output(output_name)
        comp_list.append(comp)

        comp = MockComponent('feeHub', 0)
        comp.add_mock_input(output_name, 456)
        comp_list.append(comp)

        comp = MockComponent('baz', 0)
        comp.add_mock_output(output_name)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)

        daq_data_dir = None

        try:
            mgr.make_runset(self.__run_config_dir, run_config, 0, 0, logger,
                            daq_data_dir, force_restart=False, strict=False)
            self.fail("make_runset should not succeed")
        except ConnectionException as cex:
            if str(cex).find("Found 2 %s inputs for 2 outputs" %
                             (output_name, )) < 0:
                raise

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_build_multi_input(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        comp = MockComponent('fooHub', 0)
        comp.add_mock_output('conn')
        comp_list.append(comp)

        comp = MockComponent('bar', 0)
        comp.add_mock_input('conn', 123)
        comp_list.append(comp)

        comp = MockComponent('baz', 0)
        comp.add_mock_input('conn', 456)
        comp_list.append(comp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_regexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = mgr.make_runset(self.__run_config_dir, run_config, 0, 0,
                                 logger, daq_data_dir, force_restart=False,
                                 strict=False)

        self.assertEqual(mgr.num_components, 0)

        found = mgr.find_runset(runset.id)
        self.assertFalse(found is None, "Couldn't find runset #%d" % runset.id)

        mgr.return_runset(runset, logger)

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            mgr.remove(comp)

        self.assertEqual(mgr.num_components, 0)

        logger.check_status(10)

    def test_start_run(self):
        self.__run_config_dir = tempfile.mkdtemp()
        set_pdaq_config_dir(self.__run_config_dir, override=True)

        mgr = MyDAQPool()

        acomp = MockComponent('aHub', 0)
        acomp.add_mock_output('ab')

        bcomp = MockComponent('b', 0)
        bcomp.add_mock_input('ab', 123)
        bcomp.add_mock_output('bc')

        ccomp = MockComponent('eventBuilder', 0)
        ccomp.add_mock_input('bc', 456)

        comp_list = [ccomp, acomp, bcomp]

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        MockLeapsecondFile(self.__run_config_dir).create()

        run_config = self.__create_run_config_file(comp_list)

        logger = MockLogger('main')
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_regexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = mgr.make_runset(self.__run_config_dir, run_config, 0, 0,
                                 logger, daq_data_dir, force_restart=False,
                                 strict=False)

        self.assertEqual(mgr.num_components, 0)
        self.assertEqual(runset.size(), len(comp_list))

        self.__check_runset_state(runset, 'ready')

        cluster_cfg = FakeCluster("cluster-foo")

        self.__check_runset_state(runset, 'ready')

        run_num = 1
        moni_type = RunOption.MONI_TO_NONE

        logger.add_expected_exact("Starting run #%d on \"%s\"" %
                                  (run_num, cluster_cfg.description))

        dash_log = runset.get_log("dashLog")

        dash_log.add_expected_exact("Starting run %d..." % run_num)

        logger.add_expected_regexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.add_expected_regexp(r"Waited \d+\.\d+ seconds for Hubs")

        acomp.mbean.add_mock_data("stringhub", "LatestFirstChannelHitTime", 10)
        acomp.mbean.add_mock_data("stringhub", "NumberOfNonZombies", 1)

        version_info = {
            "filename": "fName",
            "revision": "1234",
            "date": "date",
            "time": "time",
            "author": "author",
            "release": "rel",
            "repo_rev": "1repoRev",
        }

        jade_dir = "/tmp"
        copy_dir = None

        runset.start_run(run_num, cluster_cfg, moni_type, version_info,
                         jade_dir, copy_dir)

        self.__check_runset_state(runset, 'running')
        dash_log.check_status(10)

        num_evts = 1
        # num_moni = 0
        # num_sn = 0
        # num_tcal = 0

        first_time = 12345678
        last_time = 23456789

        ccomp.mbean.add_mock_data("backEnd", "FirstEventTime", first_time)
        ccomp.mbean.add_mock_data("backEnd", "EventData",
                                  (run_num, num_evts, last_time))
        ccomp.mbean.add_mock_data("backEnd", "GoodTimes",
                                  (first_time, last_time))

        mon_dict = runset.get_event_counts(run_num)
        self.assertEqual(mon_dict["physicsEvents"], num_evts)

        dash_log.add_expected_exact("Not logging to file so cannot queue to"
                                    " JADE")

        stop_name = "TestStartRun"
        dash_log.add_expected_exact("Stopping the run (%s)" % stop_name)

        logger.add_expected_exact("MockRun final report")

        acomp.mbean.add_mock_data("stringhub", "EarliestLastChannelHitTime",
                                  10)

        self.assertFalse(runset.stop_run(stop_name),
                         "stop_run() encountered error")

        self.__check_runset_state(runset, 'ready')
        dash_log.check_status(10)

        mgr.return_runset(runset, logger)

        self.assertEqual(runset.id, None)
        self.assertEqual(runset.configured(), False)
        self.assertEqual(runset.run_number(), None)

        self.assertEqual(mgr.num_components, len(comp_list))
        self.assertEqual(runset.size(), 0)

        logger.check_status(10)
        dash_log.check_status(10)

    def test_monitor_clients(self):
        self.__run_config_dir = tempfile.mkdtemp()

        mgr = MyDAQPool()

        comp_list = []

        foo_hub = MockComponent('fooHub', 0)
        foo_hub.add_mock_output('conn')
        comp_list.append(foo_hub)

        barcomp = MockComponent('bar', 0)
        barcomp.add_mock_input('conn', 123)
        comp_list.append(barcomp)

        bazcomp = MockComponent('baz', 0)
        bazcomp.add_mock_input('conn', 456)
        comp_list.append(bazcomp)

        self.assertEqual(mgr.num_components, 0)

        for comp in comp_list:
            mgr.add(comp)

        self.assertEqual(mgr.num_components, len(comp_list))

        for comp in comp_list:
            comp.set_monitor_state("idle")

        cnt = mgr.monitor_clients()
        self.assertEqual(cnt, len(comp_list))

        for comp in comp_list:
            self.assertEqual(comp.monitor_count, 1)

        foo_hub.set_monitor_state(DAQClientState.DEAD)
        bazcomp.set_monitor_state(DAQClientState.MISSING)

        self.assertEqual(mgr.num_components, len(comp_list))

        cnt = mgr.monitor_clients()

        self.assertEqual(cnt, 1)
        self.assertEqual(mgr.num_components, 2)

        for comp in comp_list:
            self.assertEqual(comp.monitor_count, 2)


if __name__ == '__main__':
    unittest.main()
