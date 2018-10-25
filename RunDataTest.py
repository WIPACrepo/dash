#!/usr/bin/env python

from __future__ import print_function

import os
import shutil
import tempfile
import unittest

from xml.etree import ElementTree

from DAQMocks import MockComponent, MockLogger
from DAQTime import PayloadTime

from RunOption import RunOption
from RunSet import RunData, RunSetException


class TinyClusterConfig(object):
    def __init__(self, description):
        self.__description = description

    @property
    def description(self):
        return self.__description


class TinyMoniClient(object):
    def __init__(self, run_number, num_events=None, num_moni=None, num_sn=None,
                 num_tcal=None, had_error=False):
        self.__run_number = run_number
        self.__num_events = num_events
        self.__num_moni = num_moni
        self.__num_sn = num_sn
        self.__num_tcal = num_tcal
        self.__status = "UNKNOWN" if had_error is None else "FAIL" \
                        if had_error else "SUCCESS"
        self.__exception = None

    def __check_count(self, name, moni_dict, expected, none_is_zero=False):
        if expected is None:
            if not none_is_zero:
                raise Exception("Count for %s not set" % (name, ))
            expected = 0
        if not none_is_zero:
            key = "count"
        elif name == "events":
            key = "physicsEvents"
        else:
            key = name + "Events"
        if key in moni_dict:
            actual = moni_dict[key]
        else:
            if not none_is_zero:
                raise Exception("Value for %s not set in moni_dict %s" %
                                (key, moni_dict))
            actual = 0

        if actual != expected:
            raise Exception("Expected #%s %s, not %s" %
                            (name, expected, actual))

    def sendMoni(self, name, value, prio=None, time=None):
        if self.__exception is not None:
            raise self.__exception

        if name == "event_count_update":
            if self.__run_number is None:
                raise Exception("Run number not set for \"%s\"" % (name, ))
            if value["stream"] == "physicsEvents":
                self.__check_count("events", value, self.__num_events)
            elif value["stream"] == "moniEvents":
                self.__check_count("moni", value, self.__num_moni)
            elif value["stream"] == "snEvents":
                self.__check_count("sn", value, self.__num_sn)
            elif value["stream"] == "tcalEvents":
                self.__check_count("tcal", value, self.__num_tcal)
            if not isinstance(value, dict):
                raise Exception("Expected dict value, not %s" %
                                (type(value).__name__, ))

        elif name == "run_update":
            if self.__run_number is None:
                raise Exception("Run number not set for \"%s\"" % (name, ))
            self.__check_count("events", value, self.__num_events,
                               none_is_zero=True)
            self.__check_count("moni", value, self.__num_moni,
                               none_is_zero=True)
            self.__check_count("sn", value, self.__num_sn,
                               none_is_zero=True)
            self.__check_count("tcal", value, self.__num_tcal,
                               none_is_zero=True)
        elif name == "runstop":
            if self.__run_number is None:
                raise Exception("Run number not set for \"%s\"" % (name, ))
            elif self.__num_events is None or \
               self.__status is None:
                raise Exception("Quantities not set for \"%s\"" % (name, ))

            if value["runnum"] != self.__run_number:
                raise Exception("Expected \"%s\" run number %s, not %s" %
                                (name, self.__run_number, value["runnum"]))
            if value["events"] != self.__num_events:
                raise Exception("Expected \"%s\" #events %s, not %s" %
                                (name, self.__num_events, value["events"]))
            if value["status"] != self.__status:
                raise Exception("Expected \"%s\" #events %s, not %s" %
                                (name, self.__num_events, value["events"]))
        else:
            raise Exception("Unknown monitoring quantity \"%s\"" % (name, ))

    def set_exception(self, exc):
        self.__exception = exc


class TinyRunConfig(object):
    def __init__(self, basename):
        self.__basename = basename

    @property
    def basename(self):
        return self.__basename


class TinyRunSet(object):
    def __init__(self):
        self.__run_dir = None
        self.__comps = []
        self.__running = False
        self.__first_good_time = None

    def add(self, name, num):
        self.__comps.append(MockComponent(name, num))

    def components(self):
        for comp in self.__comps:
            yield comp

    def create_run_dir(self, log_dir, run_num):
        tmp_dir = os.path.join(log_dir, "tstrun%05d" % run_num)
        os.mkdir(tmp_dir)
        self.__run_dir = tmp_dir
        return self.__run_dir

    def get_first_event_time(self, evt_bldr, run_data):
        return run_data.first_physics_time

    @property
    def isRunning(self):
        return self.__running

    def report_good_time(self, run_data, name, ticks):
        if name != "firstGoodTime":
            raise Exception("Unexpected good-time name \"%s\"" % (name, ))
        if run_data.first_physics_time != ticks:
            raise Exception("Expected first time <%s>%s, not <%s>%s" %
                            (type(run_data.first_physics_time).__name__,
                             run_data.first_physics_time,
                             type(ticks).__name__, ticks))

    @property
    def run_directory(self):
        return self.__run_dir

    def set_running(self, val):
        self.__running = val == True


class MyRunData(RunData):
    def __init__(self, run_set, run_number, cluster_config, run_config,
                 run_options, version_info, spade_dir, copy_dir, log_dir):
        self.__dashlog = MockLogger("dash")

        self.__dashlog.addExpectedRegexp(r"Version info: \S+ \S+ \S+ \S+")
        self.__dashlog.addExpectedExact("Run configuration: %s" %
                                        (run_config.basename, ))
        self.__dashlog.addExpectedExact("Cluster: %s" %
                                        (cluster_config.description, ))

        super(MyRunData, self).__init__(run_set, run_number, cluster_config,
                                        run_config, run_options, version_info,
                                        spade_dir, copy_dir, log_dir)

    def create_dash_log(self):
        return self.__dashlog

    def create_moni_client(self, port):
        if self.__moni_client is not None:
            return self.__moni_client

        print("Creating real MoniClient")
        return super(MyRunData, self).create_moni_client()

    @property
    def dashlog(self):
        return self.__dashlog

    def set_moni_client(self, moni_client):
        self.__moni_client = moni_client


class RunDataTest(unittest.TestCase):
    TOP_DIR = None

    TICKS_PER_SEC = 10000000000

    def __add_components(self, runset, comp_names=None):
        if comp_names is None:
            comp_names = ("fooHub", "fooTrigger", "eventBuilder",
                          "secondaryBuilders")
        for name in comp_names:
            if isinstance(name, tuple):
                runset.add(name[0], name[1])
            else:
                runset.add(name, 1)
        return runset

    def __build_standard_runset(self):
        runset = TinyRunSet()
        self.__add_components(runset)
        return runset

    def __calculate_rate(self, first_evts, last_evts, first_tick, last_tick):
        if first_tick is None or last_tick is None:
            raise Exception("First/last time is None")

        if first_tick == last_tick:
            return 0.0

        num_evts = last_evts - first_evts
        tick_seconds = (last_tick - first_tick) / 1E10
        if tick_seconds == 0.0:
            return 0.0

        return num_evts / tick_seconds

    def __create_directories(self):
        self.TOP_DIR = tempfile.mkdtemp()

        # create JADE directory
        spade_dir = os.path.join(self.TOP_DIR, "spade")
        os.mkdir(spade_dir)

        # create log directory
        log_dir = os.path.join(self.TOP_DIR, "log")
        os.mkdir(log_dir)

        return spade_dir, log_dir

    def __fake_version(self, release, repo_rev, repo_date, repo_time):
        return {
            "release": release,
            "repo_rev": repo_rev,
            "date": repo_date,
            "time": repo_time,
        }

    def __format_xml_time(self, daq_tick):
        return str(PayloadTime.toDateTime(daq_tick))

    def __set_mbean_values(self, runset, run_number, num_evts, evt_time,
                           num_moni, moni_time, num_sn, sn_time, num_tcal,
                           tcal_time, bad_data=False):
        for comp in runset.components():
            if comp.name == "eventBuilder":
                comp.mbean.addData("backEnd", "EventData",
                                   [run_number, num_evts, evt_time])
            elif comp.name == "secondaryBuilders":
                comp.mbean.addData("moniBuilder", "EventData",
                                   [run_number, num_moni, moni_time])
                comp.mbean.addData("snBuilder", "EventData",
                                   [run_number, num_sn, sn_time])
                comp.mbean.addData("tcalBuilder", "EventData",
                                   [run_number, num_tcal, tcal_time])

    def __validate_dict(self, result, valid, skip_wall_time=False):
        self.assertTrue(isinstance(result, dict),
                        "Result should be a dict, not %s" %
                        type(result).__name__)

        for key, val in valid.items():
            self.assertTrue(key in result, "No entry for \"%s\" in %s" %
                            (key, result))

            if skip_wall_time and key == "wallTime":
                continue

            self.assertEqual(result[key], val,
                             "Expected \"%s\" value %s, not %s" %
                             (key, val, result[key]))

    def __validate_result(self, result, num_evts, first_time, evt_time,
                          num_moni, moni_time, num_sn, sn_time, num_tcal,
                          tcal_time):
        self.assertTrue(isinstance(result, list) or isinstance(result, tuple),
                        "Result should be a list/tuple, not %s" %
                        type(result).__name__)

        self.assertEqual(len(result), 10,
                         "Expected 10 values, not %d" % len(result))
        self.assertEqual(num_evts, result[0],
                         "Expected %s events, not %s" % (num_evts, result[0]))
        self.assertEqual(evt_time, result[3],
                         "Expected event time %s, not %s" %
                         (evt_time, result[3]))
        self.assertEqual(num_moni, result[4],
                         "Expected %s moni, not %s" % (num_moni, result[4]))
        self.assertEqual(moni_time, result[5],
                         "Expected moni time %s, not %s" %
                         (moni_time, result[5]))
        self.assertEqual(num_sn, result[6],
                         "Expected %s SN, not %s" % (num_sn, result[6]))
        self.assertEqual(sn_time, result[7],
                         "Expected SN time %s, not %s" %
                         (sn_time, result[7]))
        self.assertEqual(num_tcal, result[8],
                         "Expected %s tcal, not %s" % (num_tcal, result[8]))
        self.assertEqual(tcal_time, result[9],
                         "Expected tcal time %s, not %s" %
                         (tcal_time, result[9]))

    def __validate_xml(self, path, value_dict):
        self.assertTrue(path is not None, "No path returned")
        self.assertTrue(os.path.exists(path),
                        "Bad run.xml path \"%s\"" % (path, ))

        tree = ElementTree.parse(path)
        root = tree.getroot()
        for elem in root:
            self.assertTrue(elem.tag in value_dict,
                            "Cannot find <%s>" % elem.tag)
            self.assertEqual(elem.text, value_dict[elem.tag],
                             "Bad value for <%s>" % (elem.tag, ))

    def setUp(self):
        if os.path.exists("run.xml"):
            raise Exception("Found existing run.xml file; aborting")

    def tearDown(self):
        if self.TOP_DIR is not None:
            shutil.rmtree(self.TOP_DIR)
        if os.path.exists("run.xml"):
            raise Exception("Test created a run.xml file; aborting")

    def testInitNoAppender(self):
        try:
            RunData(None, None, None, None, 0x0, None, None, None, None)
        except RunSetException as rse:
            if str(rse).find("No appenders") < 0:
                raise

        try:
            RunData(None, None, None, None, RunOption.LOG_TO_NONE, None, None,
                    None, None)
        except RunSetException as rse:
            if str(rse).find("No appenders") < 0:
                raise

    def testInitFileAppenderNoLogDir(self):
        try:
            RunData(None, None, None, None, RunOption.LOG_TO_FILE, None, None,
                    None, None)
        except RunSetException as rse:
            if str(rse).find("Log directory not specified for") < 0:
                raise

    def testInitFileAppender(self):
        runset = TinyRunSet()
        run_num = 666
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_FILE
        version_info = None
        spade_dir, log_dir = self.__create_directories()

        rd = RunData(runset, run_num, clu_cfg, run_cfg, run_options,
                     version_info, spade_dir, None, log_dir)

        dash_path = os.path.join(runset.run_directory, "dash.log")
        if not os.path.exists(dash_path):
            self.fail("dash.log was not created")

    def testInitLiveAppender(self):
        runset = None
        run_num = None
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        _ = RunData(runset, run_num, clu_cfg, run_cfg, run_options,
                    version_info, spade_dir, None, log_dir)

    def testInitLiveAppenderBadSpadeDir(self):
        runset = None
        run_num = None
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = "/bad/spade/path"
        log_dir = None

        try:
            RunData(runset, run_num, clu_cfg, run_cfg, run_options,
                    version_info, spade_dir, None, log_dir)
        except RunSetException as rse:
            errmsg = "SPADE directory %s does not exist" % (spade_dir, )
            if str(rse).find(errmsg) < 0:
                raise

    def testDestroy(self):
        runset = None
        run_num = None
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        rdata.destroy()

    def testGetEventCountsNoData(self):
        runset = self.__build_standard_runset()
        run_num = None
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        result = rdata.get_event_counts(run_num, runset)

        valid = {
            "physicsEvents": 0,
            "eventPayloadTicks": None,
            "wallTime": None,
            "moniEvents": 0,
            "moniTime": None,
            "snEvents": 0,
            "snTime": None,
            "tcalEvents": 0,
            "tcalTime": None,
        }
        self.__validate_dict(result, valid)

    def testGetEventCountsRunning(self):
        runset = self.__build_standard_runset()
        run_num = 123456
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        runset.set_running(True)

        num_evts = 100
        evt_time = 20 * self.TICKS_PER_SEC
        num_moni = 23
        moni_time = 100 * self.TICKS_PER_SEC
        num_sn = 45
        sn_time = 40 * self.TICKS_PER_SEC
        num_tcal = 67
        tcal_time = 70 * self.TICKS_PER_SEC

        # we'll need the first time to be set
        rdata.set_first_physics_time(10 * self.TICKS_PER_SEC)

        self.__set_mbean_values(runset, run_num, num_evts, evt_time, num_moni,
                                moni_time, num_sn, sn_time, num_tcal,
                                tcal_time)

        result = rdata.get_event_counts(run_num, runset)

        valid = {
            "physicsEvents": num_evts,
            "eventPayloadTicks": evt_time,
            "wallTime": None,
            "moniEvents": num_moni,
            "moniTime": moni_time,
            "snEvents": num_sn,
            "snTime": sn_time,
            "tcalEvents": num_tcal,
            "tcalTime": tcal_time,
        }
        self.__validate_dict(result, valid, skip_wall_time=True)

    def testRate(self):
        run_num = None
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(None, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        rate = rdata.rate
        self.assertEqual(rate, 0.0, "Expected rate %s not %s" % (0.0, rate))

        first_evts = 1
        first_pay_time = 9 * self.TICKS_PER_SEC

        last_saved = None
        for idx in (1, 2):
            num_evts = 123 * idx
            evt_time = 20 * self.TICKS_PER_SEC * idx
            num_moni = 234 * idx
            moni_time = 10 * self.TICKS_PER_SEC * idx
            num_sn = 345 * idx
            sn_time = 30 * self.TICKS_PER_SEC * idx
            num_tcal = 456 * idx
            tcal_time = 40 * self.TICKS_PER_SEC * idx

            wall_time = 50 * self.TICKS_PER_SEC * idx
            last_pay_time = first_pay_time + (99 * self.TICKS_PER_SEC * idx)

            result = rdata.update_event_counts(num_evts, wall_time,
                                               first_pay_time, last_pay_time,
                                               num_moni, moni_time,
                                               num_sn, sn_time, num_tcal,
                                               tcal_time, add_rate=True)

            exp_rate = self.__calculate_rate(first_evts, num_evts,
                                             first_pay_time, last_pay_time)

            rate = rdata.rate
            self.assertAlmostEqual(rate, exp_rate,
                                   msg="Expected rate#%d %s, not %s" %
                                   (idx, exp_rate, rate))

    def testReportFirstGoodTime(self):
        runset = TinyRunSet()
        run_num = None
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        # start without any components
        rdata.dashlog.addExpectedRegexp(r"Cannot find eventBuilder in .*$")
        rdata.report_first_good_time(runset)

        # another attempt without a known first time
        self.__add_components(runset)
        rdata.dashlog.addExpectedRegexp(r"Couldn't find first good time for ")
        rdata.report_first_good_time(runset)

        # this should finally succeed
        first_tick = 100 * self.TICKS_PER_SEC
        rdata.set_first_physics_time(first_tick)
        rdata.report_first_good_time(runset)

    def testReportRunStopBad(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 123
        first_pay_time = 10 * self.TICKS_PER_SEC
        last_pay_time = 20 * self.TICKS_PER_SEC
        had_error = False

        # start without monitoring client
        rdata.dashlog.addExpectedExact("Cannot report run stop,"
                                       " no moni client!")
        rdata.report_run_stop(num_evts, first_pay_time, last_pay_time,
                              had_error)

        # add monitoring client
        moni_client = TinyMoniClient(run_num, num_evts, had_error=had_error)
        rdata.set_moni_client(moni_client)
        rdata.connect_to_live()

        # set sendMoni() exception
        moni_client.set_exception(Exception("Expected"))

        rdata.dashlog.addExpectedRegexp(r"Failed to send .*: .* in .*$")
        rdata.report_run_stop(num_evts, first_pay_time, last_pay_time,
                              had_error)

    def testReportRunStopHadError(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 123
        first_pay_time = 10 * self.TICKS_PER_SEC
        last_pay_time = 20 * self.TICKS_PER_SEC
        had_error = True

        moni_client = TinyMoniClient(run_num, num_evts, had_error=had_error)
        rdata.set_moni_client(moni_client)
        rdata.connect_to_live()

        rdata.report_run_stop(num_evts, first_pay_time, last_pay_time,
                              had_error)

    def testReportRunStopUnsetError(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 123
        first_pay_time = 10 * self.TICKS_PER_SEC
        last_pay_time = 20 * self.TICKS_PER_SEC
        had_error = None

        moni_client = TinyMoniClient(run_num, num_evts, had_error=had_error)
        rdata.set_moni_client(moni_client)
        rdata.connect_to_live()

        rdata.report_run_stop(num_evts, first_pay_time, last_pay_time,
                              had_error)

    def testSendCountUpdatesEmpty(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        moni_data = {}
        prio = None

        rdata.send_count_updates(moni_data, prio)

    def testSendCountUpdatesBadData(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        moni_data = {
            "snEvents": 17,
            "snTime": None,  # intentionally set to None
        }
        prio = None

        rdata.dashlog.addExpectedRegexp(r"Bad sn data provided by .*$")
        rdata.send_count_updates(moni_data, prio)

    def testSendCountUpdates(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 100
        evt_time = 20 * self.TICKS_PER_SEC
        num_moni = 23
        moni_time = 100 * self.TICKS_PER_SEC
        num_sn = 45
        sn_time = 40 * self.TICKS_PER_SEC
        num_tcal = 67
        tcal_time = 70 * self.TICKS_PER_SEC

        moni_data = {
            "physicsEvents": num_evts,
            "eventPayloadTicks": evt_time,
            "moniEvents": num_moni,
            "moniTime": moni_time,
            "snEvents": num_sn,
            "snTime": sn_time,
            "tcalEvents": num_tcal,
            "tcalTime": tcal_time,
        }
        prio = None

        # first update does nothing (not enough history)
        rdata.send_count_updates(moni_data, prio)

        for key, val in moni_data.items():
            if key.endswith("Events"):
                moni_data[key] = val + int(val / 2)
            elif key.endswith("Time") or key.endswith("Ticks"):
                moni_data[key] = val + 10 * self.TICKS_PER_SEC
            else:
                raise Exception("Bad monitoring dictionary key \"%s\"" %
                                (key, ))

        # add monitoring client
        moni_client = TinyMoniClient(run_num,
                                     moni_data["physicsEvents"] - num_evts,
                                     moni_data["moniEvents"] - num_moni,
                                     moni_data["snEvents"] - num_sn,
                                     moni_data["tcalEvents"] - num_tcal)
        rdata.set_moni_client(moni_client)
        rdata.connect_to_live()

        rdata.send_count_updates(moni_data, prio)

    def testSendEventCounts(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        # add monitoring client
        moni_client = TinyMoniClient(run_num)
        rdata.set_moni_client(moni_client)
        rdata.connect_to_live()

        rdata.dashlog.addExpectedExact("Using system time for initial event"
                                       " counts (no event times available)")
        rdata.send_event_counts(runset)


    def testSendMoni(self):
        runset = TinyRunSet()
        run_num = 98765
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 777

        # add monitoring client
        moni_client = TinyMoniClient(run_num, num_evts)
        rdata.set_moni_client(moni_client)
        rdata.connect_to_live()

        moni_dict = {
            "runnum": run_num,
            "events": num_evts,
            "status": "SUCCESS",
        }

        rdata.send_moni("runstop", moni_dict)

    def testWriteRunXML(self):
        runset = None
        run_num = 123456
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = self.__fake_version("testWriteRunXML", "repo:rev",
                                           "repoDate", "repo_time")
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        # set up some values
        num_evts = 111
        num_moni = 222
        num_sn = 333
        num_tcal = 444
        first_time = 555
        last_time = 666
        first_good = 777
        last_good = 888
        had_error = False

        # build dictionary which will be used to validate the XML output
        value_dict = {
            "Cluster": clu_cfg.description,
            "Config": run_cfg.basename,
            "EndTime": self.__format_xml_time(last_time),
            "Events": str(num_evts),
            "FirstGoodTime": self.__format_xml_time(first_good),
            "LastGoodTime": self.__format_xml_time(last_good),
            "Moni": str(num_moni),
            "Release": version_info["release"],
            "Revision": version_info["repo_rev"],
            "SN": str(num_sn),
            "StartTime": self.__format_xml_time(first_time),
            "Tcal": str(num_tcal),
            "TermCondition": "ERROR" if had_error else "Success",
            "run": str(run_num),
        }

        try:
            path = rdata.write_run_xml(num_evts, num_moni, num_sn, num_tcal,
                                       first_time, last_time, first_good,
                                       last_good, had_error)
            self.__validate_xml(path, value_dict)
        finally:
            if path is not None:
                os.unlink(path)
            elif os.path.exists("run.xml"):
                os.unlink("run.xml")

    def testUpdateCountsAndRate(self):
        runset = self.__build_standard_runset()
        run_num = 666777
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 100
        evt_time = 20 * self.TICKS_PER_SEC
        num_moni = 23
        moni_time = 100 * self.TICKS_PER_SEC
        num_sn = 45
        sn_time = 40 * self.TICKS_PER_SEC
        num_tcal = 67
        tcal_time = 70 * self.TICKS_PER_SEC

        # we'll need the first time to be set
        rdata.set_first_physics_time(10 * self.TICKS_PER_SEC)

        self.__set_mbean_values(runset, run_num, num_evts, evt_time, num_moni,
                                moni_time, num_sn, sn_time, num_tcal,
                                tcal_time)

        rdata.update_counts_and_rate(runset)

    def testUpdateCountsAndRateNoFirstTime(self):
        runset = self.__build_standard_runset()
        run_num = 666777
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 100
        evt_time = 20 * self.TICKS_PER_SEC
        num_moni = 23
        moni_time = 100 * self.TICKS_PER_SEC
        num_sn = 45
        sn_time = 40 * self.TICKS_PER_SEC
        num_tcal = 67
        tcal_time = 70 * self.TICKS_PER_SEC

        self.__set_mbean_values(runset, run_num, num_evts, evt_time, num_moni,
                                moni_time, num_sn, sn_time, num_tcal,
                                tcal_time)

        rdata.dashlog.addExpectedExact("Cannot get first event time (None)")

        result = rdata.update_counts_and_rate(runset)
        self.__validate_result(result, num_evts, None, evt_time,
                               num_moni, moni_time, num_sn, sn_time, num_tcal,
                               tcal_time)

    def testUpdateCountsAndRateNoData(self):
        runset = self.__build_standard_runset()
        run_num = 666777
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        for comp in runset.components():
            if comp.name == "eventBuilder":
                comp.mbean.addData("backEnd", "EventData", None)
            elif comp.name == "secondaryBuilders":
                for stream in ("moni", "sn", "tcal"):
                    comp.mbean.addData(stream + "Builder", "EventData", None)

        err_comps = ("eventBuilder", "secondaryBuilders", "secondaryBuilders",
                     "secondaryBuilders", )
        for cname in err_comps:
            rdata.dashlog.addExpectedRegexp(r"Cannot get event data for %s.*" %
                                            (cname, ))

        result = rdata.update_counts_and_rate(runset)
        self.__validate_result(result, 0, None, None, 0, None, 0, None, 0, None)

    def testUpdateCountsAndRateWrongData(self):
        runset = self.__build_standard_runset()
        run_num = 666777
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        for comp in runset.components():
            if comp.name == "eventBuilder":
                comp.mbean.addData("backEnd", "EventData", 17)
            elif comp.name == "secondaryBuilders":
                for stream in ("moni", "sn", "tcal"):
                    comp.mbean.addData(stream + "Builder", "EventData", 34)

        err_comps = ("eventBuilder", "secondaryBuilders", "secondaryBuilders",
                     "secondaryBuilders", )
        for cname in err_comps:
            rdata.dashlog.addExpectedRegexp(r"Got bad event data .*")

        result = rdata.update_counts_and_rate(runset)

    def testUpdateCountsAndRateShortData(self):
        runset = self.__build_standard_runset()
        run_num = 666777
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        for comp in runset.components():
            if comp.name == "eventBuilder":
                comp.mbean.addData("backEnd", "EventData", [1, 2])
            elif comp.name == "secondaryBuilders":
                for stream in ("moni", "sn", "tcal"):
                    comp.mbean.addData(stream + "Builder", "EventData", [3, 4])

        err_comps = ("eventBuilder", "secondaryBuilders", "secondaryBuilders",
                     "secondaryBuilders", )
        for cname in err_comps:
            rdata.dashlog.addExpectedRegexp(r"Got bad event data .*")

        result = rdata.update_counts_and_rate(runset)

    def testUpdateCountsAndRateWrongRun(self):
        runset = self.__build_standard_runset()
        run_num = 666777
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 100
        evt_time = 20 * self.TICKS_PER_SEC
        num_moni = 23
        moni_time = 100 * self.TICKS_PER_SEC
        num_sn = 45
        sn_time = 40 * self.TICKS_PER_SEC
        num_tcal = 67
        tcal_time = 70 * self.TICKS_PER_SEC

        rdata.set_first_physics_time(10 * self.TICKS_PER_SEC)

        # bad run number
        bad_num = run_num + 3

        self.__set_mbean_values(runset, bad_num, num_evts, evt_time,
                                num_moni, moni_time, num_sn, sn_time,
                                num_tcal, tcal_time)

        rdata.dashlog.addExpectedExact("Ignoring secondaryBuilders counts"
                                       " (run#%d != run#%d)" %
                                       (bad_num, run_num))
        rdata.dashlog.addExpectedExact("Ignoring eventBuilder counts"
                                       " (run#%d != run#%d)" %
                                       (bad_num, run_num))

        result = rdata.update_counts_and_rate(runset)

    def testUpdateEventCounts(self):
        runset = None
        run_num = None
        clu_cfg = TinyClusterConfig("xxxCluCfg")
        run_cfg = TinyRunConfig("xxxRunCfg")
        run_options = RunOption.LOG_TO_LIVE
        version_info = None
        spade_dir = None
        log_dir = None

        rdata = MyRunData(runset, run_num, clu_cfg, run_cfg, run_options,
                          version_info, spade_dir, None, log_dir)

        num_evts = 123
        evt_time = 20 * self.TICKS_PER_SEC
        num_moni = 234
        moni_time = 10 * self.TICKS_PER_SEC
        num_sn = 345
        sn_time = 30 * self.TICKS_PER_SEC
        num_tcal = 456
        tcal_time = 40 * self.TICKS_PER_SEC

        wall_time = 50 * self.TICKS_PER_SEC
        first_pay_time = evt_time - (1 * self.TICKS_PER_SEC)
        last_pay_time = evt_time + (999 * self.TICKS_PER_SEC)

        result = rdata.update_event_counts(num_evts, wall_time, first_pay_time,
                                           last_pay_time, num_moni, moni_time,
                                           num_sn, sn_time, num_tcal,
                                           tcal_time, add_rate=True)
        good_pair = (
            (num_evts, "number of events"),
            (wall_time, "wall time"),
            (first_pay_time, "first payload time"),
            (last_pay_time, "last payload time"),
            (num_moni, "number of monitoring payloads"),
            (moni_time, "monitoring time"),
            (num_sn, "number of supernova payloads"),
            (sn_time, "supernova time"),
            (num_tcal, "number of time calibration payloads"),
            (tcal_time, "time calibration time"),
        )

        self.assertEqual(len(result), len(good_pair),
                         "Bad number of returned values")

        for idx in range(len(result)):
            self.assertEqual(result[idx], good_pair[idx][0],
                             "Bad %s (expected %s, got %s)" %
                             (good_pair[idx][1], good_pair[idx][0],
                              result[idx]))


if __name__ == '__main__':
    unittest.main()
