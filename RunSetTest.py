#!/usr/bin/env python

import numbers
import unittest

from ComponentManager import ComponentManager
from DAQLog import LogSocketServer
from DAQTime import PayloadTime
from LiveImports import LIVE_IMPORT, Prio
from RunOption import RunOption
from RunSet import ConnectionException, RunSet, RunSetException
from locate_pdaq import set_pdaq_config_dir
from scmversion import get_scmversion_str

from DAQMocks import MockClusterConfig, MockComponent, MockLogger

CAUGHT_WARNING = True


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


class FakeRunConfig(object):
    def __init__(self, cfgdir, name):
        self.__cfgdir = cfgdir
        self.__name = name

    @property
    def basename(self):
        return self.__name

    def hasDOM(self, mbid):
        return True


class FakeCluster(object):
    def __init__(self, desc_name):
        self.__desc_name = desc_name

    @property
    def description(self):
        return self.__desc_name


class MyParent(object):
    def __init__(self):
        pass

    def save_catchall(self, run_dir):
        pass


class FakeMoniClient(object):
    def __init__(self):
        self.__expected = []

    def __compare_dicts(self, name, xvalue, value):
        for key in xvalue:
            if key not in value:
                raise AssertionError("Moni message \"%s\" value is missing"
                                     " field \"%s\"" % (name, key))

            self.__compare_values("%s.%s" % (name, key), xvalue[key],
                                  value[key])

        for key in value:
            if key not in xvalue:
                raise AssertionError("Moni message \"%s\" value has extra"
                                     " field \"%s\"" % (name, key))

    def __compare_lists(self, name, xvalue, value):
        raise NotImplementedError()

    def __compare_values(self, name, xvalue, value):
        if not isinstance(value, type(xvalue)):
            raise AssertionError("Expected moni message \"%s\" value type %s"
                                 ", not %s" % (name, type(xvalue).__name__,
                                               type(value).__name__))
        if isinstance(value, dict):
            self.__compare_dicts(name, xvalue, value)
        elif isinstance(value, list):
            self.__compare_lists(name, xvalue, value)
        elif xvalue != value:
            raise AssertionError("Expected moni message \"%s\" value %s<%s>"
                                 ", not %s<%s>" %
                                 (name, xvalue, type(xvalue).__name__,
                                  value, type(value).__name__))

    def add_moni(self, name, value, prio=Prio.ITS, time=None):
        self.__expected.append((name, value, prio, time))

    def send_moni(self, name, value, prio=Prio.ITS, time=None):
        if len(self.__expected) == 0:
            raise AssertionError("Received unexpected moni message \"%s\":"
                                 " %s" % (name, value))
        (xname, xvalue, xprio, _) = self.__expected.pop(0)
        if xname != name:
            raise AssertionError("Expected moni message \"%s\", not \"%s\"" %
                                 (xname, name))
        if xprio != prio:
            raise AssertionError("Expected moni message \"%s\" prio %s"
                                 ", not %s" % (name, xprio, prio))
        self.__compare_values(name, xvalue, value)


class FakeRunData(object):
    def __init__(self, run_num, run_cfg, clu_cfg, version_info, moni_client):
        self.__run_number = run_num
        self.__run_config = run_cfg
        self.__cluster_config = clu_cfg
        self.__version_info = version_info
        self.__moni_client = moni_client

        self.__logger = None
        self.__finished = False

    @property
    def cluster_configuration(self):
        return self.__cluster_config

    def connect_to_live(self):
        pass

    def error(self, logmsg):
        if self.__logger is None:
            raise Exception("Mock logger has not been set")
        self.__logger.error(logmsg)

    @property
    def finished(self):
        return self.__finished

    def info(self, logmsg):
        if self.__logger is None:
            raise Exception("Mock logger has not been set")
        self.__logger.info(logmsg)

    @property
    def is_destroyed(self):
        return self.__logger is not None

    @property
    def is_error_enabled(self):
        return self.__logger.is_error_enabled

    @property
    def log_directory(self):
        return None

    @property
    def release(self):
        return self.__version_info["release"]

    @property
    def repo_revision(self):
        return self.__version_info["repo_rev"]

    def reset(self):
        pass

    @property
    def revision_date(self):
        return self.__version_info["date"]

    @property
    def revision_time(self):
        return self.__version_info["time"]

    @property
    def run_configuration(self):
        return self.__run_config

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

    @property
    def subrun_number(self, num):
        pass

    @subrun_number.setter
    def subrun_number(self, num):
        pass

    def set_mock_logger(self, logger):
        self.__logger = logger

    def stop_tasks(self):
        pass


class MyRunSet(RunSet):
    def __init__(self, parent, run_config, comp_list, logger, moni_client):
        self.__run_config = run_config
        self.__logger = logger
        self.__moni_client = moni_client

        super(MyRunSet, self).__init__(parent, run_config, comp_list, logger)

    @classmethod
    def create_component_log(cls, run_dir, comp, host, port, quiet=True):
        return FakeLogger(port)

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, spade_dir, copy_dir=None, log_dir=None):
        fake = FakeRunData(run_num, self.__run_config, cluster_config,
                           version_info, self.__moni_client)
        fake.set_mock_logger(self.__logger)
        return fake

    @classmethod
    def cycle_components(cls, comp_list, config_dir, daq_data_dir, logger,
                         log_port, live_port, verbose=False, kill_with_9=False,
                         event_check=False, check_exists=True):
        pass

    def final_report(self, comps, run_data, had_error=False, switching=False):
        show_rates = True
        if show_rates:
            num_evts = 0
            num_moni = 0
            num_sn = 0
            num_tcal = 0
            num_secs = 0

            if num_secs == 0:
                hz_str = ""
            else:
                hz_str = " (%.2f Hz)" % (float(num_evts) / float(num_secs), )

            self.__logger.error("%d physics events collected in %d seconds%s" %
                                (num_evts, num_secs, hz_str))
            self.__logger.error("%d moni events, %d SN events, %d tcals" %
                                (num_moni, num_sn, num_tcal))

        if switching:
            verb = "switched"
        else:
            verb = "terminated"
        if had_error:
            result = "WITH ERROR"
        else:
            result = "SUCCESSFULLY"
        self.__logger.error("Run %s %s." % (verb, result))

    def finish_setup(self, run_data, start_time):
        run_data.error("Version info: %s %s %s %s" %
                       (run_data.release,
                        run_data.repo_revision,
                        run_data.revision_date,
                        run_data.revision_time))
        run_data.error("Run configuration: %s" %
                       (run_data.run_configuration.basename, ))
        run_data.error("Cluster: %s" %
                       (run_data.cluster_configuration.description, ))

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

    @staticmethod
    def report_good_time(run_data, name, pay_time):
        pass


class TestRunSet(unittest.TestCase):
    def __add_hub_mbeans(self, comp_list):
        for comp in comp_list:
            if comp.is_source:
                bean = "stringhub"
                for fld in ("EarliestLastChannelHitTime",
                            "LatestFirstChannelHitTime",
                            "NumberOfNonZombies"):
                    try:
                        comp.mbean.get(bean, fld)
                    except:
                        comp.mbean.addData(bean, fld, 1)

    def __add_moni_run_update(self, runset, moni_client, run_num):
        ec_dict = runset.get_event_counts(run_num)
        run_update = {
            "version": 0,
            "run": run_num,
            "subrun": 0,
        }
        for stream in ("physics", "moni", "sn", "tcal"):
            for fld in ("Events", "Time"):
                key = stream + fld
                if key in ec_dict:
                    if fld != "Time":
                        run_update[key] = ec_dict[key]
                    elif isinstance(ec_dict[key], numbers.Number):
                        dttm = PayloadTime.toDateTime(ec_dict[key])
                        run_update[key] = str(dttm)
                    else:
                        run_update[key] = str(ec_dict[key])
        moni_client.add_moni("run_update", run_update)

    def __build_cluster_config(self, comp_list, base_name):
        jvm_path = "java-" + base_name
        jvm_args = "args=" + base_name

        cluster_cfg = MockClusterConfig("CC-" + base_name)
        for comp in comp_list:
            cluster_cfg.add_component(comp.fullname, jvm_path, jvm_args,
                                      "host-" + comp.fullname)

        return cluster_cfg

    def __build_comp_list(self, name_list):
        comp_list = []

        num = 1
        for name in name_list:
            comp = MockComponent(name, num)
            comp.order = num
            comp_list.append(comp)
            num += 1

        return comp_list

    def __build_comp_string(self, name_list):
        comp_str = None

        prev = None
        prev_num = None
        for idx, name in enumerate(name_list + (None, )):
            if prev is not None and prev_num is not None:
                if prev == name:
                    continue

                if prev_num == idx:
                    new_str = "%s#%d" % (prev, prev_num)
                else:
                    new_str = "%s#%d-%d" % (prev, prev_num, idx)

                if comp_str is None:
                    comp_str = new_str
                else:
                    comp_str += ", " + new_str

            prev = name
            prev_num = idx + 1

        return comp_str

    def __check_status(self, runset, comp_list, exp_state):
        stat_dict = runset.status()
        self.assertEqual(len(stat_dict), len(comp_list))
        for comp in comp_list:
            self.assertTrue(comp in stat_dict, 'Could not find ' + str(comp))
            self.assertEqual(stat_dict[comp], exp_state,
                             "Component %s: %s != expected %s" %
                             (comp, stat_dict[comp], exp_state))

    def __check_status_dict(self, runset, comp_list, exp_state_dict):
        stat_dict = runset.status()
        self.assertEqual(len(stat_dict), len(comp_list))
        for comp in comp_list:
            self.assertTrue(comp in stat_dict, 'Could not find ' + str(comp))
            self.assertEqual(stat_dict[comp], exp_state_dict[comp],
                             "Component %s: %s != expected %s" %
                             (comp, stat_dict[comp], exp_state_dict[comp]))

    def __is_comp_list_configured(self, comp_list):
        for comp in comp_list:
            if not comp.isConfigured:
                return False

        return True

    def __is_comp_list_running(self, comp_list, run_num=-1):
        for comp in comp_list:
            if comp.run_number is None:
                return False
            if comp.run_number != run_num:
                return False

        return True

    def __run_subrun(self, comp_list, run_num, moni_client, expect_error=None):
        logger = MockLogger('LOG')

        num = 1
        for comp in comp_list:
            comp.order = num
            num += 1

        run_config = FakeRunConfig(None, "XXXrunSubXXX")

        clu_cfg = FakeCluster("cluster-foo")

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        exp_state = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, exp_state))

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        runset.configure()

        exp_state = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, exp_state))

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        if len(comp_list) > 0:
            self.assertTrue(self.__is_comp_list_configured(comp_list),
                            'Components should be configured')
            self.assertFalse(self.__is_comp_list_running(comp_list),
                             "Components should not be running")

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        exp_state = "running"

        try:
            stop_err = runset.stop_run("StopSubrun", timeout=0)
        except RunSetException as vex:
            if "is not running" not in str(vex):
                raise
            stop_err = False

        self.assertFalse(stop_err, "stop_run() encountered error")

        for comp in comp_list:
            if comp.is_source:
                comp.mbean.addData("stringhub", "LatestFirstChannelHitTime",
                                   10)
                comp.mbean.addData("stringhub", "NumberOfNonZombies", 1)

        self.__start_run(runset, run_num, run_config, clu_cfg,
                         components=comp_list, logger=logger)

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        dom_list = [('53494d550101', 0, 1, 2, 3, 4),
                    ['1001', '22', 1, 2, 3, 4, 5],
                    ('a', 0, 1, 2, 3, 4)]

        data = [dom_list[0], ['53494d550122', ] + dom_list[1][2:]]

        subrun_num = -1

        logger.addExpectedExact("Subrun %d: flashing DOM (%s)" %
                                (subrun_num, data))

        try:
            runset.subrun(subrun_num, data)
            if expect_error is not None:
                self.fail("subrun should not have succeeded")
        except RunSetException as vex:
            if expect_error is None:
                raise
            if not str(vex).endswith(expect_error):
                self.fail("Expected subrun to fail with \"%s\", not \"%s\"" %
                          (expect_error, str(vex)))

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        for comp in comp_list:
            if comp.is_source:
                comp.mbean.addData("stringhub", "EarliestLastChannelHitTime",
                                   10)

        self.__stop_run(runset, run_num, run_config, clu_cfg, moni_client,
                        components=comp_list, logger=logger)

    def __run_tests(self, comp_list, run_num, hang_type=None):
        logger = MockLogger('foo#0')

        num = 1
        sources = 0
        for comp in comp_list:
            comp.order = num
            if comp.is_source:
                sources += 1
            num += 1

        run_config = FakeRunConfig(None, "XXXrunCfgXXX")

        exp_id = RunSet.ID_SOURCE.peek_next()

        clu_cfg = FakeCluster("cluster-foo")

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        exp_state = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, exp_state))

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        exp_state = "configuring"

        i = 0
        while True:
            cfg_wait_str = None
            for comp in comp_list:
                if comp.getConfigureWait() > i:
                    if cfg_wait_str is None:
                        cfg_wait_str = comp.fullname
                    else:
                        cfg_wait_str += ', ' + comp.fullname

            if cfg_wait_str is None:
                break

            logger.addExpectedExact("RunSet #%d (%s): Waiting for %s %s" %
                                    (exp_id, exp_state, exp_state, cfg_wait_str))
            i += 1

        runset.configure()

        exp_state = "ready"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, exp_state))

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        if len(comp_list) > 0:
            self.assertTrue(self.__is_comp_list_configured(comp_list),
                            'Components should be configured')
            self.assertFalse(self.__is_comp_list_running(comp_list),
                             "Components should not be running")

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        self.assertRaises(RunSetException, runset.stop_run, ("RunTest"))
        logger.checkStatus(10)

        exp_state = "running"

        try:
            success = self.__start_run(runset, run_num, run_config, clu_cfg,
                                       components=comp_list, logger=logger)
            if sources == 0:
                if not success:
                    return
                self.fail("Should not be able to start a run with no sources")
        except RunSetException as rse:
            if sources != 0:
                raise
            estr = str(rse)
            if estr.find("Could not get runset") < 0 or \
               estr.find("latest first time") < 0:
                self.fail("Unexpected exception during start: " + str(rse))
            return

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

        exp_state = "stopping"

        for comp in comp_list:
            if comp.is_source:
                comp.mbean.addData("stringhub", "EarliestLastChannelHitTime",
                                   10)

        self.__stop_run(runset, run_num, run_config, clu_cfg, moni_client,
                        components=comp_list, logger=logger, hang_type=hang_type)

        exp_state = "ready"

        if hang_type != 2:
            self.__check_status(runset, comp_list, exp_state)
        else:
            exp_state_dict = {}
            for comp in comp_list:
                if comp.name == "foo":
                    exp_state_dict[comp] = exp_state
                else:
                    exp_state_dict[comp] = "forcingStop"
            self.__check_status_dict(runset, comp_list, exp_state_dict)
        logger.checkStatus(10)

        runset.reset()

        exp_state = "idle"

        self.assertEqual(str(runset), 'RunSet #%d (%s)' %
                         (runset.id, exp_state))

        if len(comp_list) > 0:
            self.assertFalse(self.__is_comp_list_configured(comp_list),
                             "Components should be configured")
            self.assertFalse(self.__is_comp_list_running(comp_list),
                             "Components should not be running")

        self.__check_status(runset, comp_list, exp_state)
        logger.checkStatus(10)

    def __start_run(self, runset, run_num, run_config, clu_cfg,
                    run_options=RunOption.MONI_TO_NONE, version_info=None,
                    spade_dir="/tmp", copy_dir=None, log_dir=None,
                    components=None, logger=None):
        global CAUGHT_WARNING

        if not LIVE_IMPORT and not CAUGHT_WARNING:
            CAUGHT_WARNING = True
            logger.addExpectedRegexp(r"^Cannot import IceCube Live.*")

        has_source = False
        if components is not None:
            for comp in components:
                if comp.is_source:
                    has_source = True
                    bean = "stringhub"
                    for fld in ("LatestFirstChannelHitTime",
                                "NumberOfNonZombies"):
                        try:
                            comp.mbean.get(bean, fld)
                        except:
                            comp.mbean.addData(bean, fld, 10)

        if version_info is None:
            version_info = {
                "filename": "fName",
                "revision": "1234",
                "date": "date",
                "time": "time",
                "author": "author",
                "release": "rel",
                "repo_rev": "1repoRev",
            }

        exp_state = "running"

        logger.addExpectedExact("Starting run #%d on \"%s\"" %
                                (run_num, clu_cfg.description))

        if has_source:
            logger.addExpectedExact("Version info: " +
                                    get_scmversion_str(info=version_info))
            logger.addExpectedExact("Run configuration: %s" %
                                    run_config.basename)
            logger.addExpectedExact("Cluster: %s" % clu_cfg.description)

            logger.addExpectedExact("Starting run %d..." % run_num)

            logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
            logger.addExpectedRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        try:
            runset.start_run(run_num, clu_cfg, run_options, version_info,
                             spade_dir, copy_dir, log_dir)
            self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                             (runset.id, run_num, exp_state))
        except ConnectionException as cex:
            if not str(cex).endswith("no sources found!"):
                raise
            return False

        if components is not None and len(components) > 0:
            self.assertTrue(self.__is_comp_list_configured(components),
                            'Components should be configured')
            self.assertTrue(self.__is_comp_list_running(components, run_num),
                            'Components should not be running')

        self.__check_status(runset, components, exp_state)
        logger.checkStatus(10)

        return True

    def __stop_run(self, runset, run_num, run_config, clu_cfg, moni_client,
                   components=None, logger=None, hang_type=None):
        exp_state = "stopping"

        # default to type 0
        if hang_type is None:
            hang_type = 0

        comp_list = components
        if comp_list is not None:
            comp_list.sort(key=lambda x: x.order)

        if hang_type == 0:
            stop_name = "TestRunSet"
        elif hang_type == 1:
            stop_name = "TestHang1"
        elif hang_type == 2:
            stop_name = "TestHang2"
        else:
            stop_name = "Test"
        logger.addExpectedExact("Stopping the run (%s)" % stop_name)

        hang_str = None
        force_str = None
        if hang_type > 0:
            hang_list = []
            force_list = []
            for comp in components:
                if comp.isHanging:
                    extra = "(ERROR)"
                    hang_list.append(comp.fullname + extra)
                    force_list.append(comp.fullname)
            hang_str = ", ".join(hang_list)
            force_str = ", ".join(force_list)

            if len(hang_list) < len(components):
                logger.addExpectedExact("RunSet #%d run#%d (%s):"
                                        " Waiting for %s %s" %
                                        (runset.id, run_num, exp_state,
                                         exp_state, hang_str))

            if len(force_list) == 1:
                plural = ""
            else:
                plural = "s"
            logger.addExpectedExact("RunSet #%d run#%d (%s):"
                                    " Forcing %d component%s to stop: %s" %
                                    (runset.id, run_num, "forcingStop",
                                     len(hang_list), plural, force_str))
            if hang_type > 1:
                logger.addExpectedExact("ForcedStop failed for " + force_str)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")

        exp_state = "ready"

        if hang_type > 1:
            exp_state = "forcingStop"
            logger.addExpectedExact("Run terminated WITH ERROR.")
            logger.addExpectedExact("RunSet #%d run#%d (%s):"
                                    " Could not stop %s" %
                                    (runset.id, run_num, exp_state, force_str))
        else:
            logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        logger.addExpectedExact("Not logging to file so cannot queue to"
                                " SPADE")

        self.__add_moni_run_update(runset, moni_client, run_num)

        if hang_type < 2:
            self.assertFalse(runset.stop_run(stop_name, timeout=0),
                             "stop_run() encountered error")
            exp_state = "ready"
        else:
            try:
                if not runset.stop_run(stop_name, timeout=0):
                    self.fail("stop_run() should have failed")
            except RunSetException as rse:
                exp_msg = "RunSet #%d run#%d (%s): Could not stop %s" % \
                         (runset.id, run_num, exp_state, force_str)
                self.assertEqual(str(rse), exp_msg,
                                 ("For hang_type %d expected exception %s," +
                                  " not %s") % (hang_type, exp_msg, rse))
            exp_state = "error"

        self.assertEqual(str(runset), 'RunSet #%d run#%d (%s)' %
                         (runset.id, run_num, exp_state))
        self.assertFalse(runset.stopping(), "RunSet #%d is still stopping")

        if len(components) > 0:
            self.assertTrue(self.__is_comp_list_configured(components),
                            "Components should be configured")
            self.assertFalse(self.__is_comp_list_running(components),
                             "Components should not be running")

        if hang_type == 0:
            self.__check_status(runset, components, exp_state)
        logger.checkStatus(10)

    def setUp(self):
        set_pdaq_config_dir("src/test/resources/config", override=True)

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        # create the leapsecond alertstamp file so we don't get superfluous
        # log messages
        RunSet.is_leapsecond_silenced()

    def tearDown(self):
        set_pdaq_config_dir(None, override=True)

    def test_empty(self):
        self.__run_tests([], 1)

    def test_set(self):
        comp_list = self.__build_comp_list(("foo", "bar"))
        comp_list[0].setConfigureWait(1)

        self.__run_tests(comp_list, 2)

    def test_subrun_good(self):
        comp_list = self.__build_comp_list(("fooHub", "barHub", "bazBuilder"))

        moni_client = FakeMoniClient()

        self.__run_subrun(comp_list, 3, moni_client)

    def test_subrun_one_bad(self):

        comp_list = self.__build_comp_list(("fooHub", "barHub", "bazBuilder"))
        comp_list[1].setBadHub()

        moni_client = FakeMoniClient()

        self.__run_subrun(comp_list, 4, moni_client, expect_error="on %s" %
                          comp_list[1].fullname)

    def test_subrun_both_bad(self):

        comp_list = self.__build_comp_list(("fooHub", "barHub", "bazBuilder"))
        comp_list[0].setBadHub()
        comp_list[1].setBadHub()

        moni_client = FakeMoniClient()

        self.__run_subrun(comp_list, 5, moni_client,
                          expect_error="on any string hubs")

    def test_stop_hang(self):
        hang_type = 1

        comp_list = self.__build_comp_list(("foo", "bar"))
        comp_list[1].set_hang_type(hang_type)

        RunSet.TIMEOUT_SECS = 5

        self.__run_tests(comp_list, 6, hang_type=hang_type)

    def test_forced_stop_hang(self):
        hang_type = 2

        comp_list = self.__build_comp_list(("foo", "bar"))
        comp_list[1].set_hang_type(hang_type)

        RunSet.TIMEOUT_SECS = 5

        self.__run_tests(comp_list, 7, hang_type=hang_type)

    def test_restart_fail_clu_cfg(self):
        comp_list = self.__build_comp_list(("sleepy", "sneezy", "happy",
                                            "grumpy", "doc", "dopey",
                                            "bashful"))

        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        base_name = "failCluCfg"

        cluster_cfg = self.__build_cluster_config(comp_list[1:], base_name)

        logger.addExpectedExact(("Cannot restart %s: Not found" +
                                 " in cluster config %s") %
                                (comp_list[0].fullname, cluster_cfg))

        cycle_list = sorted(comp_list[1:])

        errmsg = None
        for comp in cycle_list:
            if errmsg is None:
                errmsg = "Cycling components " + comp.fullname
            else:
                errmsg += ", " + comp.fullname
        if errmsg is not None:
            logger.addExpectedExact(errmsg)

        runset.restart_components(comp_list[:], cluster_cfg, None, None, None,
                                  None, verbose=False, kill_with_9=False,
                                  event_check=False)

    def test_restart_extra_comp(self):
        comp_list = self.__build_comp_list(("sleepy", "sneezy", "happy",
                                            "grumpy", "doc", "dopey",
                                            "bashful"))

        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        extra_comp = MockComponent("queen", 10)

        long_list = comp_list[:]
        long_list.append(extra_comp)

        base_name = "failCluCfg"

        cluster_cfg = self.__build_cluster_config(long_list, base_name)

        logger.addExpectedExact("Cannot remove component %s from RunSet #%d" %
                                (extra_comp.fullname, runset.id))

        long_list.sort()

        errmsg = None
        for comp in long_list:
            if errmsg is None:
                errmsg = "Cycling components " + comp.fullname
            else:
                errmsg += ", " + comp.fullname
        if errmsg is not None:
            logger.addExpectedExact(errmsg)

        runset.restart_components(long_list, cluster_cfg, None, None, None,
                                  None, verbose=False, kill_with_9=False,
                                  event_check=False)

    def test_restart(self):
        comp_list = self.__build_comp_list(("sleepy", "sneezy", "happy",
                                            "grumpy", "doc", "dopey",
                                            "bashful"))

        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        cluster_cfg = self.__build_cluster_config(comp_list, "restart")

        errmsg = None
        for comp in comp_list:
            if errmsg is None:
                errmsg = "Cycling components " + comp.fullname
            else:
                errmsg += ", " + comp.fullname
        if errmsg is not None:
            logger.addExpectedExact(errmsg)

        runset.restart_components(comp_list[:], cluster_cfg, None, None, None,
                                  None, verbose=False, kill_with_9=False,
                                  event_check=False)

    def test_restart_all(self):
        comp_list = self.__build_comp_list(("sleepy", "sneezy", "happy",
                                            "grumpy", "doc", "dopey",
                                            "bashful"))

        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        cluster_cfg = self.__build_cluster_config(comp_list, "restartAll")

        errmsg = None
        for comp in comp_list:
            if errmsg is None:
                errmsg = "Cycling components " + comp.fullname
            else:
                errmsg += ", " + comp.fullname
        if errmsg is not None:
            logger.addExpectedExact(errmsg)

        runset.restart_all_components(cluster_cfg, None, None, None, None,
                                      verbose=False, kill_with_9=False,
                                      event_check=False)

    def test_short_stop_without_start(self):
        comp_list = self.__build_comp_list(("one", "two", "three"))
        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        comp_str = "one#1, two#2, three#3"

        stop_name = "ShortStop"
        logger.addExpectedExact("Stopping the run (%s)" % stop_name)

        logger.addExpectedRegexp("Could not stop run .* RunSetException.*")
        logger.addExpectedExact("Failed to transition to ready: idle[%s]" %
                                comp_str)
        logger.addExpectedExact("RunSet #%d (error): Could not stop idle[%s]" %
                                (runset.id, comp_str))

        try:
            self.assertFalse(runset.stop_run(stop_name, timeout=0),
                             "stop_run() encountered error")
            self.fail("stop_run() on new runset should throw exception")
        except Exception as ex:
            if str(ex) != "RunSet #%d is not running" % runset.id:
                raise

    def test_short_stop_normal(self):
        comp_list = self.__build_comp_list(("oneHub", "two", "three"))
        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        runset.configure()

        run_num = 100
        clu_cfg = FakeCluster("foo-cluster")

        self.__add_hub_mbeans(comp_list)

        self.__start_run(runset, run_num, run_config, clu_cfg,
                         components=comp_list, logger=logger)

        self.__stop_run(runset, run_num, run_config, clu_cfg, moni_client,
                        components=comp_list, logger=logger)

    def test_short_stop_hang(self):
        comp_list = self.__build_comp_list(("oneHub", "two", "three"))
        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        runset.configure()

        run_num = 100
        clu_cfg = FakeCluster("bar-cluster")

        self.__add_hub_mbeans(comp_list)

        self.__start_run(runset, run_num, run_config, clu_cfg,
                         components=comp_list, logger=logger)

        hang_type = 2
        for comp in comp_list:
            comp.set_hang_type(hang_type)

        RunSet.TIMEOUT_SECS = 5

        self.__stop_run(runset, run_num, run_config, clu_cfg, moni_client,
                        components=comp_list, logger=logger, hang_type=hang_type)

    def test_bad_stop(self):
        comp_names = ("firstHub", "middle", "middle", "middle", "middle",
                      "last")
        comp_list = self.__build_comp_list(comp_names)
        run_config = FakeRunConfig(None, "XXXrunCfgXXX")
        logger = MockLogger('foo#0')

        moni_client = FakeMoniClient()

        runset = MyRunSet(MyParent(), run_config, comp_list, logger, moni_client)

        runset.configure()

        run_num = 543
        clu_cfg = FakeCluster("bogusCluster")

        self.__add_hub_mbeans(comp_list)

        self.__start_run(runset, run_num, run_config, clu_cfg,
                         components=comp_list, logger=logger)

        for comp in comp_list:
            comp.setStopFail()

        RunSet.TIMEOUT_SECS = 5

        comp_str = self.__build_comp_string(comp_names)

        stop_name = "BadStop"
        logger.addExpectedExact("Stopping the run (%s)" % stop_name)

        logger.addExpectedExact("0 physics events collected in 0 seconds")
        logger.addExpectedExact("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedExact("Run terminated SUCCESSFULLY.")

        logger.addExpectedExact("Not logging to file so cannot queue to"
                                " SPADE")

        logger.addExpectedExact(("RunSet #1 run#%d (forcingStop):" +
                                 " Forcing 6 components to stop: %s") %
                                (run_num, comp_str))
        logger.addExpectedExact("StopRun failed for " + comp_str)
        logger.addExpectedExact("Failed to transition to ready: stopping[%s]" %
                                comp_str)

        stop_errmsg = ("RunSet #%d run#%d (error): Could not stop" +
                        " stopping[%s]") % (runset.id, run_num, comp_str)
        logger.addExpectedExact(stop_errmsg)

        self.__add_moni_run_update(runset, moni_client, run_num)

        try:
            try:
                runset.stop_run(stop_name, timeout=0)
            except RunSetException as rse:
                self.assertEqual(str(rse), stop_errmsg,
                                 "Expected exception %s, not %s" %
                                 (rse, stop_errmsg))
        finally:
            pass

    def test_list_comp_ranges(self):

        comp_names = ("fooHub", "barHub", "fooHub", "fooHub", "fooHub",
                      "barHub", "barHub", "zabTrigger", "fooHub", "fooHub",
                      "barHub", "bazBuilder")

        comp_list = []

        next_num = 1
        for name in comp_names:
            if name.endswith("Hub"):
                num = next_num
            else:
                num = 0
            comp = MockComponent(name, num)
            comp.order = next_num
            comp_list.append(comp)

            next_num += 1

        compstr = ComponentManager.format_component_list(comp_list)

        exp_str = "fooHub#1,3-5,9-10, barHub#2,6-7,11, zabTrigger, bazBuilder"
        self.assertEqual(compstr, exp_str,
                         "Expected legible list \"%s\", not \"%s\"" %
                         (exp_str, compstr))


if __name__ == '__main__':
    unittest.main()
