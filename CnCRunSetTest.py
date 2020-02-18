#!/usr/bin/env python

import copy
import shutil
import tempfile
import time
import unittest

from ActiveDOMsTask import ActiveDOMsTask
from ComponentManager import ComponentManager
from CnCExceptions import CnCServerException, MissingComponentException
from CnCServer import CnCServer
from DAQConst import DAQPort
from DAQLog import LogSocketServer
from DAQMocks import MockClusterConfig, MockDefaultDomGeometryFile, \
    MockIntervalTimer, MockLeapsecondFile, MockLogger, MockRunConfigFile, \
    RunXMLValidator, SocketReader
from DAQTime import PayloadTime
from LiveImports import LIVE_IMPORT
from MonitorTask import MonitorTask
from RateTask import RateTask
from RunOption import RunOption
from RunSet import RunData, RunSet, RunSetException
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask
from i3helper import Comparable
from locate_pdaq import set_pdaq_config_dir


class MockComponentLogger(MockLogger):
    def __init__(self, name, port):
        if port is None:
            port = LogSocketServer.next_log_port

        self.__port = port

        super(MockComponentLogger, self).__init__(name)

    @property
    def port(self):
        return self.__port

    def stop_serving(self):
        pass


class MockLoggerPlusPorts(MockLogger):
    def __init__(self, name, log_port, live_port):
        super(MockLoggerPlusPorts, self).__init__(name)
        self.__log_port = log_port
        self.__live_port = live_port

    @property
    def live_port(self):
        return self.__live_port

    @property
    def log_port(self):
        return self.__log_port


class MockConn(object):
    def __init__(self, conn_name, descr_char):
        self.__name = conn_name
        self.__descr_char = descr_char

    def __repr__(self):
        if self.is_input:
            return "->%s(%s)" % (self.__descr_char, self.__name)

        return "%s->(%s)" % (self.__descr_char, self.__name)

    @property
    def is_input(self):
        return self.__descr_char == "i" or self.__descr_char == "I"

    @property
    def is_optional(self):
        return self.__descr_char == "I" or self.__descr_char == "O"

    @property
    def name(self):
        return self.__name


class MockMBeanClient(object):
    def __init__(self):
        self.__bean_data = {}

    def check(self, bean_name, field_name):
        pass

    def get(self, bean_name, field_name):
        if bean_name not in self.__bean_data:
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), bean_name))
        if field_name not in self.__bean_data[bean_name]:
            raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                             (str(self), bean_name, field_name))

        return self.__bean_data[bean_name][field_name]

    def get_attributes(self, bean_name, field_list):
        if bean_name not in self.__bean_data:
            raise ValueError("Unknown %s bean \"%s\"" % (str(self), bean_name))

        val_map = {}
        for fld in field_list:
            if fld not in self.__bean_data[bean_name]:
                raise ValueError("Unknown %s bean \"%s\" field \"%s\"" %
                                 (str(self), bean_name, fld))

            val_map[fld] = self.__bean_data[bean_name][fld]

        return val_map

    def get_bean_names(self):
        return []

    def get_dictionary(self):
        return copy.deepcopy(self.__bean_data)

    def reload(self):
        pass

    def set_data(self, bean_name, field_name, value):
        if bean_name not in self.__bean_data:
            self.__bean_data[bean_name] = {}
        self.__bean_data[bean_name][field_name] = value


class MockComponent(Comparable):
    def __init__(self, name, num=0, conn=None):
        self.__name = name
        self.__num = num
        self.__conn = conn
        self.__state = "idle"
        self.__order = None

        self.__mbean = MockMBeanClient()

    def __str__(self):
        if self.__num == 0 and not self.is_source:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def __repr__(self):
        return str(self)

    def close(self):
        pass

    @property
    def compare_tuple(self):
        return (self.__name, self.__num)

    def configure(self, run_cfg):
        self.__state = "ready"

    def connect(self, conn_map=None):
        self.__state = "connected"

    def connectors(self):
        if self.__conn is None:
            raise SystemExit("No connectors for %s" % str(self))
        return self.__conn[:]

    def create_mbean_client(self):
        return self.__mbean

    @property
    def filename(self):
        return "/dev/null"

    @property
    def fullname(self):
        return "%s#%s" % (self.__name, self.__num)

    def get_run_data(self, run_num):
        if self.__num == 0:
            if self.__name.startswith("event"):
                evt_data = self.__mbean.get("backEnd", "EventData")
                num_evts = int(evt_data[1])
                last_time = int(evt_data[2])

                val = self.__mbean.get("backEnd", "FirstEventTime")
                first_time = int(val)

                good = self.__mbean.get("backEnd", "GoodTimes")
                first_good = int(good[0])
                last_good = int(good[1])

                return (num_evts, first_time, last_time, first_good, last_good)
        raise SystemExit("Cannot return run data for \"%s\"" %
                         (self.fullname, ))

    @property
    def is_dying(self):
        return False

    @property
    def is_builder(self):
        return self.__name.lower().endswith("builder")

    def is_component(self, name, num=-1):
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def is_replay_hub(self):
        return False

    @property
    def is_source(self):
        return self.__name.lower().endswith("hub")

    def log_to(self, host, port, live_host, live_port):
        pass

    @property
    def mbean(self):
        return self.__mbean

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    @property
    def order(self):
        return self.__order

    @order.setter
    def order(self, order):
        self.__order = order

    def reset(self):
        pass

    def reset_logging(self):
        pass

    def set_first_good_time(self, pay_time):
        pass

    def set_last_good_time(self, pay_time):
        pass

    def start_run(self, run_cfg):
        self.__state = "running"

    def stop_run(self):
        self.__state = "ready"

    @property
    def state(self):
        return self.__state


class MostlyTaskManager(TaskManager):
    WAITSECS = 0.25

    TIMERS = {}

    def create_interval_timer(self, name, period):
        if name not in self.TIMERS:
            self.TIMERS[name] = MockIntervalTimer(name, self.WAITSECS)

        return self.TIMERS[name]

    def get_timer(self, name):
        if name not in self.TIMERS:
            raise SystemExit("Unknown timer \"%s\"" % (name, ))

        return self.TIMERS[name]


class FakeMoniClient(object):
    def __init__(self):
        pass

    def close(self):
        pass

    def sendMoni(self, name, data, prio=None, time=None):
        pass


class MostlyRunData(RunData):
    def __init__(self, runSet, run_number, clusterConfig, run_config,
                 runOptions, version_info, spade_dir, copy_dir, log_dir,
                 dashlog=None):
        self.__dashlog = dashlog

        self.__taskmgr = None

        super(MostlyRunData, self).__init__(runSet, run_number, clusterConfig,
                                            run_config, runOptions,
                                            version_info, spade_dir, copy_dir,
                                            log_dir)

    def create_dash_log(self):
        if self.__dashlog is None:
            raise Exception("dashLog has not been set")

        return self.__dashlog

    def create_moni_client(self, port):
        return FakeMoniClient()

    def create_task_manager(self, runset):
        self.__taskmgr = MostlyTaskManager(runset, self.__dashlog,
                                           self.moni_client,
                                           self.run_directory,
                                           self.run_configuration,
                                           self.run_options)
        return self.__taskmgr

    @property
    def task_manager(self):
        return self.__taskmgr


class MyRunSet(RunSet):
    FAIL_STATE = "fail"

    def __init__(self, parent, run_config, comp_list, logger):
        self.__run_config = run_config

        self.__rundata = None
        self.__dashlog = None
        self.__fail_reset = None

        super(MyRunSet, self).__init__(parent, run_config, comp_list, logger)

    @classmethod
    def create_component_log(cls, run_dir, comp, port, quiet=True):
        return MockComponentLogger(str(comp), port)

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, spade_dir, copy_dir=None, log_dir=None):
        rdt = MostlyRunData(self, run_num, cluster_config, self.__run_config,
                            run_options, version_info, spade_dir, copy_dir,
                            log_dir, dashlog=self.__dashlog)
        self.__rundata = rdt
        return rdt

    @classmethod
    def cycle_components(cls, comp_list, config_dir, daq_data_dir, logger,
                         verbose=False, kill_with_9=False, event_check=False,
                         check_exists=True):
        comp_str = ComponentManager.format_component_list(comp_list)
        logger.error("Cycling components %s" % comp_str)

    @property
    def task_manager(self):
        if self.__rundata is None:
            raise SystemExit("RunData cannot be None")
        return self.__rundata.task_manager

    def reset(self):
        if self.__fail_reset is not None:
            return (self.__fail_reset, )
        return {}

    def set_dash_log(self, logger):
        if self.__rundata is not None:
            raise SystemExit("RunData cannot be set")
        self.__dashlog = logger

    def set_unreset_component(self, comp):
        self.__fail_reset = comp


class MostlyCnCServer(CnCServer):
    def __init__(self, clusterConfigObject=None, copy_dir=None,
                 default_log_dir=None, run_config_dir=None, daq_data_dir=None,
                 spade_dir=None):
        self.__cluster_config = clusterConfigObject
        self.__log_server = None

        super(MostlyCnCServer, self).__init__(copy_dir=copy_dir,
                                              default_log_dir=default_log_dir,
                                              run_config_dir=run_config_dir,
                                              daq_data_dir=daq_data_dir,
                                              spade_dir=spade_dir,
                                              force_restart=False,
                                              test_only=True)

    def create_runset(self, run_config, comp_list, logger):
        return MyRunSet(self, run_config, comp_list, logger)

    def cycle_components(self, comp_list, run_config_dir, daq_data_dir, logger,
                         verbose=False, kill_with_9=False, event_check=False):
        MyRunSet.cycle_components(comp_list, run_config_dir, daq_data_dir,
                                  logger, verbose=verbose,
                                  kill_with_9=kill_with_9,
                                  event_check=event_check)

    def get_cluster_config(self, run_config=None):
        return self.__cluster_config

    def get_log_server(self):
        return self.__log_server

    def open_log_server(self, port, log_dir):
        if self.__log_server is None:
            self.__log_server = SocketReader("catchall", port)

        self.__log_server.add_expected_text("Start of log at"
                                            " LOG=log(localhost:%d)" % port)

        return self.__log_server

    def save_catchall(self, run_dir):
        pass


class CnCRunSetTest(unittest.TestCase):
    HUB_NUMBER = 21
    EXAMPLE_DOM = 0x737d355af587

    BEAN_DATA = {
        "stringHub": {
            "DataCollectorMonitor-00A": {
                "MainboardId": "%012x" % EXAMPLE_DOM,
            },
            "sender": {
                "NumHitsReceived": 0,
                "NumReadoutRequestsReceived": 0,
                "NumReadoutsSent": 0,
            },
            "stringhub": {
                "NumberOfActiveAndTotalChannels": 0,
                "TotalLBMOverflows": 0,
                "LatestFirstChannelHitTime": -1,
                "EarliestLastChannelHitTime": -1,
                "NumberOfNonZombies": 60,
            },
        },
        "inIceTrigger": {
            "stringHit": {
                "RecordsReceived": 0,
            },
            "trigger": {
                "RecordsSent": 0,
            },
        },
        "globalTrigger": {
            "trigger": {
                "RecordsReceived": 0,
            },
            "glblTrig": {
                "RecordsSent": 0,
            },
        },
        "eventBuilder": {
            "backEnd": {
                "DiskAvailable": 2048,
                "EventData": (0, 0, 0),
                "FirstEventTime": 0,
                "GoodTimes": (0, 0),
                "NumBadEvents": 0,
                "NumEventsDispatched": 0,
                "NumEventsSent": 0,
                "NumReadoutsReceived": 0,
                "NumTriggerRequestsReceived": 0,
            }
        },
        "extraComp": {
        },
    }

    def __add_live_moni(self, comps, live_moni, comp_name, comp_num, bean_name,
                        field_name, is_json=False):

        if not LIVE_IMPORT:
            return

        for comp in comps:
            if comp.name == comp_name and comp.num == comp_num:
                val = comp.mbean.get(bean_name, field_name)
                var = "%s-%d*%s+%s" % (comp_name, comp_num, bean_name,
                                       field_name)
                if is_json:
                    live_moni.add_expected_live_moni(var, val, "json")
                else:
                    live_moni.add_expected_live_moni(var, val)
                return

        raise Exception("Unknown component %s-%d" % (comp_name, comp_num))

    @classmethod
    def __add_run_start_moni(cls, live_moni, run_num, release, revision,
                             started):

        if not LIVE_IMPORT:
            return

        data = {"runnum": run_num,
                "release": release,
                "revision": revision,
                "started": True}
        live_moni.add_expected_live_moni("runstart", data, "json")

    @classmethod
    def __add_run_stop_moni(cls, live_moni, first_time, last_time, num_evts,
                            run_num):

        if not LIVE_IMPORT:
            return

        data = {
            "runnum": run_num,
            "runstart": str(PayloadTime.to_date_time(first_time)),
            "events": num_evts,
            "status": "SUCCESS"
        }
        live_moni.add_expected_live_moni("runstop", data, "json")

    def __check_active_doms_task(self, comps, runset, live_moni):
        if not LIVE_IMPORT:
            return

        timer = runset.task_manager.get_timer(ActiveDOMsTask.name)

        num_doms = 22
        num_total = 60

        self.__set_bean_data(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                             "NumberOfActiveAndTotalChannels",
                             (num_doms, num_total))

        self.__set_bean_data(comps, "stringHub", self.HUB_NUMBER, "stringhub",
                             "TotalLBMOverflows",
                             20)

        live_moni.add_expected_live_moni("activeDOMs", num_doms)
        live_moni.add_expected_live_moni("expectedDOMs", num_total)

        timer.trigger()

        self.__wait_for_empty_log(live_moni)

        live_moni.check_status(5)

    def __check_monitor_task(self, comps, runset, live_moni):
        timer = runset.task_manager.get_timer(MonitorTask.name)

        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "sender", "NumHitsReceived")
        self.__add_live_moni(comps, live_moni, "inIceTrigger", 0, "stringHit",
                             "RecordsReceived")
        self.__add_live_moni(comps, live_moni, "inIceTrigger", 0, "trigger",
                             "RecordsSent")
        self.__add_live_moni(comps, live_moni, "globalTrigger", 0, "trigger",
                             "RecordsReceived")
        self.__add_live_moni(comps, live_moni, "globalTrigger", 0, "glblTrig",
                             "RecordsSent")
        self.__add_live_moni(comps, live_moni, "eventBuilder", 0, "backEnd",
                             "NumTriggerRequestsReceived")
        self.__add_live_moni(comps, live_moni, "eventBuilder", 0, "backEnd",
                             "NumReadoutsReceived")
        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "sender", "NumReadoutRequestsReceived")
        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "sender", "NumReadoutsSent")
        self.__add_live_moni(comps, live_moni, "eventBuilder", 0, "backEnd",
                             "NumEventsSent")

        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "stringhub", "NumberOfActiveAndTotalChannels")
        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "stringhub", "TotalLBMOverflows")
        self.__add_live_moni(comps, live_moni, "eventBuilder", 0, "backEnd",
                             "DiskAvailable")
        self.__add_live_moni(comps, live_moni, "eventBuilder", 0, "backEnd",
                             "NumBadEvents")
        self.__add_live_moni(comps, live_moni, "eventBuilder", 0, "backEnd",
                             "EventData", True)
        self.__add_live_moni(comps, live_moni, "eventBuilder", 0, "backEnd",
                             "FirstEventTime", False)
        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "DataCollectorMonitor-00A", "MainboardId")

        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "stringhub", "EarliestLastChannelHitTime")
        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "stringhub", "LatestFirstChannelHitTime")
        self.__add_live_moni(comps, live_moni, "stringHub", self.HUB_NUMBER,
                             "stringhub", "NumberOfNonZombies")

        timer.trigger()

        self.__wait_for_empty_log(live_moni)

        live_moni.check_status(5)

    def __check_rate_task(self, comps, runset, live_moni, dash_log, num_evts,
                          pay_time, first_time, run_num):
        timer = runset.task_manager.get_timer(RateTask.name)

        self.__set_bean_data(comps, "eventBuilder", 0, "backEnd", "EventData",
                             [run_num, 0, 0])

        dash_log.add_expected_regexp(r"\s+0 physics events, 0 moni events,"
                                     r" 0 SN events, 0 tcals")

        timer.trigger()

        self.__wait_for_empty_log(dash_log)

        self.__set_bean_data(comps, "eventBuilder", 0, "backEnd", "EventData",
                             [run_num, num_evts, pay_time])
        self.__set_bean_data(comps, "eventBuilder", 0, "backEnd",
                             "FirstEventTime", first_time)
        self.__set_bean_data(comps, "eventBuilder", 0, "backEnd",
                             "GoodTimes", (first_time, pay_time))

        duration = self.__compute_duration(first_time, pay_time)
        if duration <= 0:
            hz_str = ""
        else:
            hz_str = " (%2.2f Hz)" % \
              self.__compute_rate_hz(1, num_evts, duration)

        dash_log.add_expected_exact("	%d physics events%s, 0 moni events,"
                                    " 0 SN events, 0 tcals" %
                                    (num_evts, hz_str))

        timer.trigger()

        self.__wait_for_empty_log(dash_log)

        dash_log.check_status(5)
        if live_moni is not None:
            live_moni.check_status(5)

    def __check_watchdog_task(self, comps, runset, dash_log, live_moni,
                              unhealthy=False):
        timer = runset.task_manager.get_timer(WatchdogTask.name)

        self.__set_bean_data(comps, "eventBuilder", 0, "backEnd",
                             "DiskAvailable", 0)

        if unhealthy:
            dash_log.add_expected_regexp("Watchdog reports starved"
                                         " components.*")
            dash_log.add_expected_regexp("Watchdog reports threshold"
                                         " components.*")

        timer.trigger()

        time.sleep(MostlyTaskManager.WAITSECS * 2.0)

        self.__wait_for_empty_log(dash_log)

        dash_log.check_status(5)
        live_moni.check_status(5)

    @classmethod
    def __compute_duration(cls, start_time, cur_time):
        dom_ticks_per_sec = 10000000000
        return (cur_time - start_time) / dom_ticks_per_sec

    @classmethod
    def __compute_rate_hz(cls, start_evts, cur_evts, duration):
        return float(cur_evts - start_evts) / float(duration)

    @classmethod
    def __load_bean_data(cls, comp_list):
        for comp in comp_list:
            if comp.name not in cls.BEAN_DATA:
                raise Exception("No bean data found for %s" % str(comp))

            for bean in cls.BEAN_DATA[comp.name]:
                if len(cls.BEAN_DATA[comp.name][bean]) == 0:
                    comp.mbean.set_data(bean, "xxx", 0)
                else:
                    for fld in cls.BEAN_DATA[comp.name][bean]:
                        comp.mbean.set_data(bean, fld,
                                            cls.BEAN_DATA[comp.name][bean][fld])

    def __run_direct(self, fail_reset):
        self.__copy_dir = tempfile.mkdtemp()
        self.__run_config_dir = tempfile.mkdtemp()
        self.__spade_dir = tempfile.mkdtemp()
        self.__log_dir = tempfile.mkdtemp()

        set_pdaq_config_dir(self.__run_config_dir)

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"), )),
                 MockComponent("extraComp")]

        clu_cfg = MockClusterConfig("clusterFoo")
        for comp in comps:
            clu_cfg.add_component(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=clu_cfg)

        self.__load_bean_data(comps)

        name_list = []
        for comp in comps:
            self.__cnc.add(comp)
            if comp.name != "stringHub" and comp.name != "extraComp":
                name_list.append(str(comp))

        hub_dom_dict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.create_dom(self.EXAMPLE_DOM, 1, "Example",
                                          "X123"), ],
        }

        rc_file = MockRunConfigFile(self.__run_config_dir)
        run_config = rc_file.create(name_list, hub_dom_dict)

        MockDefaultDomGeometryFile.create(self.__run_config_dir, hub_dom_dict)

        leap_file = MockLeapsecondFile(self.__run_config_dir)
        leap_file.create()

        logger = MockLogger("main")
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_regexp(r"Built runset #\d+: .*")

        run_num = 321
        daq_data_dir = None

        runset = self.__cnc.make_runset(self.__run_config_dir, run_config,
                                        run_num, 0, logger, daq_data_dir,
                                        force_restart=False, strict=False)

        logger.check_status(5)

        dash_log = MockLogger("dashLog")
        runset.set_dash_log(dash_log)

        logger.add_expected_exact("Starting run #%d on \"%s\"" %
                                  (run_num, clu_cfg.description))

        dash_log.add_expected_regexp(r"Version info: \S+ \S+ \S+ \S+")
        dash_log.add_expected_exact("Run configuration: %s" % run_config)
        dash_log.add_expected_exact("Cluster: %s" % clu_cfg.description)

        dash_log.add_expected_exact("Starting run %d..." % run_num)

        logger.add_expected_regexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.add_expected_regexp(r"Waited \d+\.\d+ seconds for Hubs")

        self.__set_bean_data(comps, "stringHub", self.HUB_NUMBER,
                             "stringhub", "LatestFirstChannelHitTime", 10)

        version_info = {
            "filename": "fName",
            "revision": "1234",
            "date": "date",
            "time": "time",
            "author": "author",
            "release": "rel",
            "repo_rev": "1repoRev",
        }

        runset.start_run(run_num, clu_cfg, RunOption.MONI_TO_NONE,
                         version_info, spade_dir=self.__spade_dir,
                         log_dir=self.__log_dir)

        logger.check_status(5)
        dash_log.check_status(5)

        num_evts = 1000
        pay_time = 50000000001
        first_time = 1

        self.__check_rate_task(comps, runset, None, dash_log, num_evts,
                               pay_time, first_time, run_num)

        stop_name = "RunDirect"
        dash_log.add_expected_exact("Stopping the run (%s)" % stop_name)

        duration = self.__compute_duration(first_time, pay_time)
        if duration <= 0:
            hz_str = ""
        else:
            hz_str = " (%2.2f Hz)" % \
              self.__compute_rate_hz(0, num_evts, duration)

        dash_log.add_expected_exact("%d physics events collected in %d"
                                    " seconds%s" %
                                    (num_evts, duration, hz_str))

        num_moni = 0
        num_sn = 0
        num_tcal = 0

        dash_log.add_expected_exact("%d moni events, %d SN events, %d tcals" %
                                    (num_moni, num_sn, num_tcal))
        dash_log.add_expected_exact("Run terminated SUCCESSFULLY.")

        dash_log.add_expected_exact("Not logging to file so cannot queue to"
                                    " SPADE")

        self.__set_bean_data(comps, "stringHub", self.HUB_NUMBER,
                             "stringhub", "EarliestLastChannelHitTime", 20)

        self.assertFalse(runset.stop_run(stop_name),
                         "stop_run() encountered error")

        logger.check_status(5)
        dash_log.check_status(5)

        if fail_reset:
            runset.set_unreset_component(comps[0])
            logger.add_expected_exact("Cycling components %s#%d" %
                                      (comps[0].name, comps[0].num))
        try:
            self.__cnc.return_runset(runset, logger)
            if fail_reset:
                self.fail("return_runset should not have succeeded")
        except RunSetException:
            if not fail_reset:
                raise

        logger.check_status(5)
        dash_log.check_status(5)

        RunXMLValidator.validate(self, run_num, run_config, clu_cfg.description,
                                 None, None, num_evts, num_moni, num_sn,
                                 num_tcal, False)

    @staticmethod
    def __set_bean_data(comps, comp_name, comp_num, bean_name, field_name,
                        value):
        set_data = False
        for comp in comps:
            if comp.name == comp_name and comp.num == comp_num:
                if set_data:
                    raise Exception("Found multiple components for %s" %
                                    comp.fullname)

                comp.mbean.set_data(bean_name, field_name, value)
                set_data = True

        if not set_data:
            raise Exception("Could not find component %s#%d" %
                            (comp_name, comp_num))

    @staticmethod
    def __wait_for_empty_log(log):
        for _ in range(5):
            if log.is_empty:
                break
            time.sleep(0.25)
        log.check_status(1)

    def setUp(self):
        self.__cnc = None

        self.__copy_dir = None
        self.__run_config_dir = None
        self.__daq_data_dir = None
        self.__spade_dir = None
        self.__log_dir = None

        set_pdaq_config_dir(None, override=True)

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        RunXMLValidator.setUp()

    def tearDown(self):
        if self.__cnc is not None:
            self.__cnc.close_server()

        if self.__copy_dir is not None:
            shutil.rmtree(self.__copy_dir, ignore_errors=True)
        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)
        if self.__daq_data_dir is not None:
            shutil.rmtree(self.__daq_data_dir, ignore_errors=True)
        if self.__spade_dir is not None:
            shutil.rmtree(self.__spade_dir, ignore_errors=True)
        if self.__log_dir is not None:
            shutil.rmtree(self.__log_dir, ignore_errors=True)

        RunXMLValidator.tearDown()

    def test_empty_runset(self):
        self.__run_config_dir = tempfile.mkdtemp()
        self.__daq_data_dir = tempfile.mkdtemp()

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"), )),
                 MockComponent("extraComp")]

        clu_cfg = MockClusterConfig("clusterFoo")
        for comp in comps:
            clu_cfg.add_component(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=clu_cfg,
                                     run_config_dir=self.__run_config_dir)

        name_list = []

        rc_file = MockRunConfigFile(self.__run_config_dir)
        run_config = rc_file.create(name_list, {})
        run_num = 123

        logger = MockLogger("main")
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Cycling components %s#%d" %
                                  (comps[0].name, comps[0].num))

        self.assertRaises(CnCServerException, self.__cnc.make_runset,
                          self.__run_config_dir, run_config, run_num, 0,
                          logger, self.__daq_data_dir, force_restart=False,
                          strict=False)

    def test_missing_component(self):
        self.__run_config_dir = tempfile.mkdtemp()

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"), )),
                 MockComponent("extraComp")]

        clu_cfg = MockClusterConfig("clusterMissing")
        for comp in comps:
            clu_cfg.add_component(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=clu_cfg)

        hub_dom_dict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.create_dom(self.EXAMPLE_DOM, 1, "Example",
                                          "X123"), ],
        }

        rc_file = MockRunConfigFile(self.__run_config_dir)
        run_config = rc_file.create([], hub_dom_dict)

        MockDefaultDomGeometryFile.create(self.__run_config_dir, hub_dom_dict)

        run_num = 456

        logger = MockLoggerPlusPorts("main", 10101, 20202)
        logger.add_expected_exact("Loading run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Loaded run configuration \"%s\"" %
                                  run_config)
        logger.add_expected_exact("Cycling components %s#%d" %
                                  (comps[0].name, comps[0].num))

        self.assertRaises(MissingComponentException, self.__cnc.make_runset,
                          self.__run_config_dir, run_config, run_num, 0,
                          logger, self.__daq_data_dir, force_restart=False,
                          strict=False)

    def test_run_direct(self):
        self.__run_direct(False)

    def test_fail_reset(self):
        self.__run_direct(True)

    def test_run_indirect(self):
        self.__copy_dir = tempfile.mkdtemp()
        self.__run_config_dir = tempfile.mkdtemp()
        self.__spade_dir = tempfile.mkdtemp()
        self.__log_dir = tempfile.mkdtemp()

        set_pdaq_config_dir(self.__run_config_dir)

        comps = [MockComponent("stringHub", self.HUB_NUMBER,
                               (MockConn("stringHit", "o"), )),
                 MockComponent("inIceTrigger",
                               conn=(MockConn("stringHit", "i"),
                                     MockConn("trigger", "o"))),
                 MockComponent("globalTrigger",
                               conn=(MockConn("trigger", "i"),
                                     MockConn("glblTrig", "o"))),
                 MockComponent("eventBuilder",
                               conn=(MockConn("glblTrig", "i"),)),
                 MockComponent("extraComp")]

        clu_cfg = MockClusterConfig("clusterFoo")
        for comp in comps:
            clu_cfg.add_component(comp.fullname, "java", "", "localhost")

        self.__cnc = MostlyCnCServer(clusterConfigObject=clu_cfg,
                                     copy_dir=self.__copy_dir,
                                     default_log_dir=self.__log_dir,
                                     run_config_dir=self.__run_config_dir,
                                     daq_data_dir=self.__daq_data_dir,
                                     spade_dir=self.__spade_dir)

        catchall = self.__cnc.get_log_server()

        self.__load_bean_data(comps)

        name_list = []
        for comp in comps:
            self.__cnc.add(comp)
            if comp.name != "stringHub" and comp.name != "extraComp":
                name_list.append(str(comp))

        run_comp_list = []
        for comp in comps:
            if comp.is_source or comp.name == "extraComp":
                continue
            run_comp_list.append(comp.fullname)

        hub_dom_dict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.create_dom(self.EXAMPLE_DOM, 1, "Example",
                                          "X123"), ],
        }

        rc_file = MockRunConfigFile(self.__run_config_dir)
        run_config = rc_file.create(run_comp_list, hub_dom_dict)

        MockDefaultDomGeometryFile.create(self.__run_config_dir, hub_dom_dict)

        leap_file = MockLeapsecondFile(self.__run_config_dir)
        leap_file.create()

        catchall.add_expected_text("Loading run configuration \"%s\"" %
                                   run_config)
        catchall.add_expected_text("Loaded run configuration \"%s\"" %
                                   run_config)
        catchall.add_expected_text_regexp(r"Built runset #\d+: .*")

        live_moni = SocketReader("live_moni", DAQPort.I3LIVE, 99)
        live_moni.start_serving()

        run_num = 345

        rs_id = self.__cnc.rpc_runset_make(run_config, run_num)

        if catchall:
            catchall.check_status(5)
        live_moni.check_status(5)

        runset = self.__cnc.find_runset(rs_id)
        self.assertFalse(runset is None, "Could not find runset #%d" % rs_id)

        time.sleep(1)

        if catchall:
            catchall.check_status(5)

        dash_log = MockLogger("dashLog")
        runset.set_dash_log(dash_log)

        self.__set_bean_data(comps, "stringHub", self.HUB_NUMBER,
                             "stringhub", "LatestFirstChannelHitTime", 10)
        if LIVE_IMPORT:
            data = {"runnum": run_num, "subrun": 0}
            live_moni.add_expected_live_moni("firstGoodTime", data, "json")

        (rel, rev) = self.__cnc.release
        self.__add_run_start_moni(live_moni, run_num, rel, rev, True)

        catchall.add_expected_text("Starting run #%d on \"%s\"" %
                                   (run_num, clu_cfg.description))

        dash_log.add_expected_regexp(r"Version info: \S+ \S+ \S+ \S+")
        dash_log.add_expected_exact("Run configuration: %s" % run_config)
        dash_log.add_expected_exact("Cluster: %s" % clu_cfg.description)

        dash_log.add_expected_exact("Starting run %d..." % run_num)

        catchall.add_expected_text_regexp(r"Waited \d+\.\d+ seconds"
                                          r" for NonHubs")
        catchall.add_expected_text_regexp(r"Waited \d+\.\d+ seconds"
                                          r" for Hubs")

        self.__cnc.rpc_runset_start_run(rs_id, run_num, RunOption.MONI_TO_LIVE)

        if catchall:
            catchall.check_status(5)
        dash_log.check_status(5)
        live_moni.check_status(5)

        num_evts = 5
        pay_time = 50000000001
        first_time = 1

        self.__check_rate_task(comps, runset, live_moni, dash_log, num_evts,
                               pay_time, first_time, run_num)
        self.__check_monitor_task(comps, runset, live_moni)
        self.__check_active_doms_task(comps, runset, live_moni)

        for idx in range(5):
            self.__check_watchdog_task(comps, runset, dash_log, live_moni,
                                       unhealthy=(idx >= 3))

        if catchall:
            catchall.check_status(5)
        dash_log.check_status(5)
        live_moni.check_status(5)

        duration = self.__compute_duration(first_time, pay_time)
        if duration <= 0:
            hz_str = ""
        else:
            hz_str = " (%2.2f Hz)" % \
              self.__compute_rate_hz(0, num_evts, duration)

        dash_log.add_expected_exact("%d physics events collected in %d"
                                    " seconds%s" %
                                    (num_evts, duration, hz_str))

        num_moni = 0
        num_sn = 0
        num_tcal = 0

        dash_log.add_expected_exact("%d moni events, %d SN events, %d tcals" %
                                    (num_moni, num_sn, num_tcal))
        dash_log.add_expected_exact("Run terminated SUCCESSFULLY.")

        dash_log.add_expected_exact("Not logging to file so cannot queue to"
                                    " SPADE")

        self.__add_run_stop_moni(live_moni, first_time, pay_time, num_evts,
                                 run_num)

        self.__set_bean_data(comps, "stringHub", self.HUB_NUMBER,
                             "stringhub", "EarliestLastChannelHitTime", 20)
        if LIVE_IMPORT:
            data = {"runnum": run_num}
            live_moni.add_expected_live_moni("lastGoodTime", data, "json")

        self.__cnc.rpc_runset_stop_run(rs_id)

        time.sleep(1)

        if catchall:
            catchall.check_status(5)
        dash_log.check_status(5)
        live_moni.check_status(5)

        RunXMLValidator.validate(self, run_num, run_config,
                                 clu_cfg.description, None, None, num_evts,
                                 num_moni, num_sn, num_tcal, False)

        self.__cnc.rpc_runset_break(rs_id)

        if catchall:
            catchall.check_status(5)
        dash_log.check_status(5)
        live_moni.check_status(5)

        catchall.stop_serving()
        live_moni.stop_serving()


if __name__ == '__main__':
    unittest.main()
