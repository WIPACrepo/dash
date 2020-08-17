#!/usr/bin/env python

from __future__ import print_function

import datetime
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import unittest
try:
    import xmlrpc.client as rpcclient
except ImportError:
    import xmlrpclib as rpcclient

from CnCServer import CnCServer, Connector
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQLog import LogSocketServer
from DAQRPC import RPCServer
from LiveImports import Prio, LIVE_IMPORT, SERVICE_NAME
from RunOption import RunOption
from RunSet import RunData, RunSet
from TaskManager import MonitorTask, RateTask, TaskManager, WatchdogTask
from i3helper import Comparable
from locate_pdaq import set_pdaq_config_dir
from scmversion import get_scmversion_str

try:
    from DAQLive import DAQLive
except SystemExit:
    class DAQLive(object):
        SERVICE_NAME = 'dead'

from DAQMocks \
    import MockClusterConfig, MockCnCLogger, MockIntervalTimer, \
    MockLeapsecondFile, MockLogger, RunXMLValidator, SocketReader, \
    SocketReaderFactory, SocketWriter


class LiveStub(object):
    def close(self):
        raise NotImplementedError()


class BeanData(object):
    def __init__(self, remote_comp, bean, field, watch_type, val=0,
                 increasing=True):
        self.__remote_comp = remote_comp
        self.__bean = bean
        self.__field = field
        self.__watch_type = watch_type
        self.__value = val
        self.__increasing = increasing

    def __str__(self):
        if self.__increasing:
            updown = '^'
        else:
            updown = 'v'
        return '%s.%s.%s<%s>%s%s' % \
            (self.__remote_comp, self.__bean, self.__field, self.__watch_type,
             str(self.__value), updown)

    @property
    def value(self):
        return self.__value

    @value.setter
    def value(self, val):
        self.__value = val


class DAQMBeans(object):
    INPUT = 'i'
    OUTPUT = 'o'
    STATIC = 's'
    THRESHOLD = 't'

    TEMPLATE = {
        'stringHub': (
            ('dom', 'sender', 'NumHitsReceived', INPUT, 0),
            ('eventBuilder', 'sender', 'NumReadoutRequestsReceived', INPUT, 0),
            ('eventBuilder', 'sender', 'NumReadoutsSent', OUTPUT, 0),
            ('stringHub', 'stringhub', 'NumberOfActiveChannels', THRESHOLD, 0),
            ('stringHub', 'stringhub', 'NumberOfNonZombies', STATIC, 10),
            ('stringHub', 'stringhub', 'LatestFirstChannelHitTime', INPUT, 1),
            ('stringHub', 'stringhub', 'EarliestLastChannelHitTime', INPUT, 1),
        ),
        'inIceTrigger': (
            ('stringHub', 'stringHit', 'RecordsReceived', INPUT, 0),
            ('globalTrigger', 'trigger', 'RecordsSent', OUTPUT, 0),
        ),
        'simpleTrigger': (
            ('stringHub', 'stringHit', 'RecordsReceived', INPUT, 0),
            ('globalTrigger', 'trigger', 'RecordsSent', OUTPUT, 0),
        ),
        'iceTopTrigger': (
            ('stringHub', 'stringHit', 'RecordsReceived', INPUT, 0),
            ('globalTrigger', 'trigger', 'RecordsSent', OUTPUT, 0),
        ),
        'amandaTrigger': (
            ('globalTrigger', 'trigger', 'RecordsSent', OUTPUT, 0),
        ),
        'globalTrigger': (
            ('inIceTrigger', 'trigger', 'RecordsReceived', INPUT, 0),
            ('simpleTrigger', 'trigger', 'RecordsReceived', INPUT, 0),
            ('iceTopTrigger', 'trigger', 'RecordsReceived', INPUT, 0),
            ('amandaTrigger', 'trigger', 'RecordsReceived', INPUT, 0),
            ('eventBuilder', 'glblTrig', 'RecordsSent', OUTPUT, 0),
        ),
        'eventBuilder': (
            ('stringHub', 'backEnd', 'NumReadoutsReceived', INPUT, 0),
            ('globalTrigger', 'backEnd', 'NumTriggerRequestsReceived',
             INPUT, 0),
            ('dispatch', 'backEnd', 'NumEventsSent', STATIC, 0),
            ('dispatch', 'backEnd', 'NumEventsDispatched', STATIC, 0),
            ('eventBuilder', 'backEnd', 'DiskAvailable', THRESHOLD, 1024,
             True),
            ('eventBuilder', 'backEnd', 'EventData', OUTPUT, [0, 0, 0]),
            ('eventBuilder', 'backEnd', 'FirstEventTime', OUTPUT, 0, True),
            ('eventBuilder', 'backEnd', 'GoodTimes', OUTPUT, (0, 0), True),
            ('eventBuilder', 'backEnd', 'NumBadEvents', THRESHOLD, 0, False),
        ),
        'secondaryBuilders': (
            ('secondaryBuilders', 'snBuilder', 'DiskAvailable',
             THRESHOLD, 1024, True),
            ('dispatch', 'moniBuilder', 'NumDispatchedData', OUTPUT, 0),
            ('dispatch', 'moniBuilder', 'EventData', OUTPUT, (0, 0, 0)),
            ('dispatch', 'snBuilder', 'NumDispatchedData', OUTPUT, 0),
            ('dispatch', 'snBuilder', 'EventData', OUTPUT, (0, 0, 0)),
            ('dispatch', 'tcalBuilder', 'NumDispatchedData', OUTPUT, 0),
            ('dispatch', 'tcalBuilder', 'EventData', OUTPUT, (0, 0, 0)),
        ),
    }

    LOCK = threading.Lock()
    BEANS = {}

    @classmethod
    def __build_component_beans(cls, master_list, comp_name):
        if comp_name not in master_list:
            raise Exception('Unknown component %s' % comp_name)

        mbeans = {}

        bean_tuples = master_list[comp_name]
        for tup in bean_tuples:
            if tup[1] not in mbeans:
                mbeans[tup[1]] = {}

            if len(tup) == 5:
                mbeans[tup[1]][tup[2]] = BeanData(tup[0], tup[1], tup[2],
                                                  tup[3], tup[4])
            elif len(tup) == 6:
                mbeans[tup[1]][tup[2]] = BeanData(tup[0], tup[1], tup[2],
                                                  tup[3], tup[4], tup[5])
            else:
                raise Exception('Bad bean tuple %s' % str(tup))

        return mbeans

    @classmethod
    def build(cls, comp_name):
        with cls.LOCK:
            if comp_name not in cls.BEANS:
                cls.BEANS[comp_name] = \
                  cls.__build_component_beans(cls.TEMPLATE, comp_name)
            return cls.BEANS[comp_name]

    @classmethod
    def clear(cls):
        with cls.LOCK:
            for key in list(cls.BEANS.keys()):
                del cls.BEANS[key]


class MostlyTaskManager(TaskManager):
    WAITSECS = 0.25

    TIMERS = {}

    def create_interval_timer(self, name, period):
        if name not in self.TIMERS:
            self.TIMERS[name] = MockIntervalTimer(name, self.WAITSECS)

        return self.TIMERS[name]

    def trigger_timer(self, name):
        if name not in self.TIMERS:
            raise Exception("Unknown timer \"%s\"" % name)

        self.TIMERS[name].trigger()


class FakeMoniClient(object):
    def __init__(self):
        pass

    # fake version of Live's DefaultMoniClient.sendMoni
    def sendMoni(self, name, data, prio=None,  # pylint: disable=invalid-name
                 time=None):  # pylint: disable=redefined-outer-name
        pass


class MostlyRunData(RunData):
    def __init__(self, run_set, run_number, cluster_config, run_config,
                 run_options, version_info, spade_dir, copy_dir, log_dir,
                 appender=None):
        self.__appender = appender

        self.__dashlog = None
        self.__task_mgr = None

        super(MostlyRunData, self).__init__(run_set, run_number,
                                            cluster_config, run_config,
                                            run_options, version_info,
                                            spade_dir, copy_dir, log_dir)

    def create_dash_log(self):
        self.__dashlog = MockCnCLogger("dash", appender=self.__appender,
                                       quiet=True, extra_loud=False)
        return self.__dashlog

    def create_moni_client(self, port):
        return FakeMoniClient()

    def create_task_manager(self, runset):
        self.__task_mgr = MostlyTaskManager(runset, self.__dashlog,
                                            self.moni_client,
                                            self.run_directory,
                                            self.run_configuration,
                                            self.run_options)
        return self.__task_mgr

    def get_event_counts(self, run_num, run_set):
        num_evts = None
        last_pay_time = None
        num_moni = None
        num_sn = None
        num_tcal = None

        for comp in run_set.components:
            if comp.name == "eventBuilder":
                evt_data = comp.mbean.get("backEnd", "EventData")
                num_evts = evt_data[1]
                last_pay_time = int(evt_data[2])
            elif comp.name == "secondaryBuilders":
                for stream in ("moni", "sn", "tcal"):
                    val = comp.mbean.get(stream + "Builder", "EventData")
                    if stream == "moni":
                        num_moni = val[1]
                        moni_ticks = val[2]
                    elif stream == "sn":
                        num_sn = val[1]
                        sn_ticks = val[2]
                    elif stream == "tcal":
                        num_tcal = val[1]
                        tcal_ticks = val[2]

        return {
            "physicsEvents": num_evts,
            "wallTime": None,
            "eventPayloadTicks": last_pay_time,
            "moniEvents": num_moni,
            "moniTime": moni_ticks,
            "snEvents": num_sn,
            "snTime": sn_ticks,
            "tcalEvents": num_tcal,
            "tcalTime": tcal_ticks,
        }

    @property
    def log_directory(self):
        return None

    @property
    def task_manager(self):
        return self.__task_mgr


class MostlyRunSet(RunSet):
    LOGFACTORY = SocketReaderFactory()
    LOGDICT = {}

    def __init__(self, parent, run_config, runset, logger, dash_appender=None):
        self.__run_config = run_config
        self.__dash_appender = dash_appender

        self.__run_data = None

        if len(self.LOGDICT) > 0:  # pylint: disable=len-as-condition
            raise Exception("Found %d open runset logs" % len(self.LOGDICT))

        super(MostlyRunSet, self).__init__(parent, run_config, runset, logger)

    @classmethod
    def close_all_logs(cls):
        for k in list(cls.LOGDICT.keys()):
            cls.LOGDICT[k].stop_serving()
            del cls.LOGDICT[k]

    @classmethod
    def create_component_log(cls, run_dir, comp, port, quiet=True):
        if comp.fullname in cls.LOGDICT:
            return cls.LOGDICT[comp.fullname]

        if port is not None:
            log = cls.LOGFACTORY.create_log(comp.fullname, port,
                                            expect_start_msg=True)
        else:
            while True:
                port = LogSocketServer.next_log_port

                try:
                    log = cls.LOGFACTORY.create_log(comp.fullname, port,
                                                    expect_start_msg=True)
                    break
                except socket.error:
                    pass

        cls.LOGDICT[comp.fullname] = log

        log.add_expected_regexp(r'Hello from \S+#\d+')
        log.add_expected_text_regexp(r'Version info: \S+ \S+ \S+ \S+')

        comp.log_to("localhost", port, None, None)

        return log

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, spade_dir, copy_dir, log_dir):
        self.__run_data = MostlyRunData(self, run_num, cluster_config,
                                        self.__run_config, run_options,
                                        version_info, spade_dir, copy_dir,
                                        log_dir, appender=self.__dash_appender)
        return self.__run_data

    def create_run_dir(self, log_dir, run_num, backup_existing=True):
        pass

    @classmethod
    def get_component_log(cls, comp):
        if comp.fullname in cls.LOGDICT:
            return cls.LOGDICT[comp.fullname]
        return None

    @property
    def task_manager(self):
        if self.__run_data is None:
            return None
        return self.__run_data.task_manager


class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbean_port, connectors,
                 appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbean_port, connectors,
                                              quiet=True)

    def create_logger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet)


class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, cluster_config_object, log_port, live_port, copy_dir,
                 default_log_dir, run_config_dir, daq_data_dir, spade_dir):
        self.__cluster_config = cluster_config_object
        self.__live_only = log_port is None and live_port is not None
        self.__log_server = None
        self.__runset = None
        self.__dash_appender = None

        if log_port is None:
            log_host = None
        else:
            log_host = 'localhost'
        if live_port is None:
            live_host = None
        else:
            live_host = 'localhost'

        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              copy_dir=copy_dir,
                                              default_log_dir=default_log_dir,
                                              run_config_dir=run_config_dir,
                                              daq_data_dir=daq_data_dir,
                                              spade_dir=spade_dir,
                                              log_host=log_host,
                                              log_port=log_port,
                                              live_host=live_host,
                                              live_port=live_port,
                                              force_restart=False, quiet=True)

    def create_client(self, name, num, host, port, mbean_port, connectors):
        if self.__live_only:
            appender = None
        else:
            key = '%s#%d' % (name, num)
            if key not in MostlyCnCServer.APPENDERS:
                MostlyCnCServer.APPENDERS[key] = MockLogger('Mock-%s' % key)
            appender = MostlyCnCServer.APPENDERS[key]

        return MostlyDAQClient(name, num, host, port, mbean_port, connectors,
                               appender)

    def create_cnc_logger(self, quiet):
        key = 'server'
        if key not in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = \
                MockLogger('Mock-%s' % key,
                           depth=IntegrationTest.NUM_COMPONENTS)

        return MockCnCLogger(key, appender=MostlyCnCServer.APPENDERS[key],
                             quiet=quiet)

    def get_cluster_config(self, run_config=None):
        return self.__cluster_config

    def create_runset(self, run_config, comp_list, logger):
        self.__runset = MostlyRunSet(self, run_config, comp_list, logger,
                                     dash_appender=self.__dash_appender)
        return self.__runset

    def get_log_server(self):
        return self.__log_server

    def monitor_loop(self):
        pass

    def open_log_server(self, port, log_dir):
        self.__log_server = SocketReader("CnCDefault", port)

        msg = "Start of log at LOG=log(localhost:%d)" % port
        self.__log_server.add_expected_text(msg)
        msg = get_scmversion_str(info=self.version_info())
        self.__log_server.add_expected_text(msg)

        return self.__log_server

    def runset(self, num=None):
        return self.__runset

    def save_catchall(self, run_dir):
        pass

    def set_dash_appender(self, dash_appender):
        self.__dash_appender = dash_appender

    def start_live_thread(self):
        return None


class RealComponent(Comparable):
    # Component order, used in the __get_order() method
    COMP_ORDER = {
        'stringHub': (50, 50),
        'amandaTrigger': (0, 13),
        'iceTopTrigger': (2, 12),
        'inIceTrigger': (4, 11),
        'globalTrigger': (10, 10),
        'eventBuilder': (30, 2),
        'secondaryBuilders': (32, 0),
    }

    def __init__(self, name, num, cmd_port, mbean_port, hs_dir, hs_interval,
                 hs_max_files, jvm_path, jvm_server, jvm_heap_init,
                 jvm_heap_max, jvm_args, jvm_extra_args):
        self.__id = None
        self.__name = name
        self.__num = num
        self.__hs_dir = hs_dir
        self.__hs_interval = hs_interval
        self.__hs_max_files = hs_max_files
        self.__jvm_path = jvm_path
        self.__jvm_server = jvm_server
        self.__jvm_heap_init = jvm_heap_init
        self.__jvm_heap_max = jvm_heap_max
        self.__jvm_args = jvm_args
        self.__jvm_extra_args = jvm_extra_args

        self.__state = 'FOO'
        self.__launch_order = None

        self.__logger = None
        self.__liver = None

        self.__comp_list = None
        self.__connections = None

        self.__mbean_data = None
        self.__run_data = None

        self.__first_good_time = None
        self.__last_good_time = None

        self.__version = {'filename': name, 'revision': '1', 'date': 'date',
                          'time': 'time', 'author': 'author', 'release': 'rel',
                          'repo_rev': '1234'}

        self.__cmd = RPCServer(cmd_port)
        self.__cmd.register_function(self.__commit_subrun,
                                     'xmlrpc.commitSubrun')
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__get_run_data, 'xmlrpc.getRunData')
        self.__cmd.register_function(self.__get_state, 'xmlrpc.getState')
        self.__cmd.register_function(self.__log_to, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__prepare_subrun,
                                     'xmlrpc.prepareSubrun')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__reset_logging,
                                     'xmlrpc.resetLogging')
        self.__cmd.register_function(self.__set_first_good_time,
                                     'xmlrpc.setFirstGoodTime')
        self.__cmd.register_function(self.__set_last_good_time,
                                     'xmlrpc.setLastGoodTime')
        self.__cmd.register_function(self.__start_run, 'xmlrpc.startRun')
        self.__cmd.register_function(self.__start_subrun, 'xmlrpc.startSubrun')
        self.__cmd.register_function(self.__stop_run, 'xmlrpc.stopRun')

        t_name = "RealXML*%s#%d" % (self.__name, self.__num)
        thrd = threading.Thread(name=t_name, target=self.__cmd.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        self.__mbean = RPCServer(mbean_port)
        self.__mbean.register_function(self.__get_attributes,
                                       'mbean.getAttributes')
        self.__mbean.register_function(self.__get_mbean_value, 'mbean.get')
        self.__mbean.register_function(self.__list_getters,
                                       'mbean.listGetters')
        self.__mbean.register_function(self.__list_mbeans, 'mbean.listMBeans')

        t_name = "RealMBean*%s#%d" % (self.__name, self.__num)
        thrd = threading.Thread(name=t_name, target=self.__mbean.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        self.__cnc = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        return '%s#%d' % (self.__name, self.__num)

    def __commit_subrun(self, rid, latest_time):
        self.__log('Commit subrun %d: %s' % (rid, str(latest_time)))
        return 'COMMIT'

    def __configure(self, cfg_name=None):  # pylint: disable=unused-argument
        if self.__logger is None and self.__liver is None:
            raise Exception('No logging for %s' % (str(self)))

        self.__state = 'ready'
        return 'CFG'

    def __connect(self, conn_list=None):
        if self.__comp_list is None:
            raise Exception("No component list for %s" % str(self))

        tmp_dict = {}
        if conn_list is not None:
            for cdict in conn_list:
                for comp in self.__comp_list:
                    if comp.is_component(cdict["compName"], cdict["compNum"]):
                        tmp_dict[comp] = 1
                        break

        self.__connections = list(tmp_dict.keys())

        self.__state = 'connected'
        return 'CONN'

    @classmethod
    def __fix_value(cls, obj):
        if isinstance(obj, dict):
            for key, val in list(obj.items()):
                obj[key] = cls.__fix_value(val)
        elif isinstance(obj, list):
            for idx, val in enumerate(obj):
                obj[idx] = cls.__fix_value(val)
        elif isinstance(obj, tuple):
            new_obj = []
            for val in obj:
                new_obj.append(cls.__fix_value(val))
            obj = tuple(new_obj)
        elif isinstance(obj, int):
            if obj < rpcclient.MININT or obj > rpcclient.MAXINT:
                return str(obj)
        return obj

    def __get_attributes(self, bean, fld_list):
        if self.__mbean_data is None:
            self.__mbean_data = DAQMBeans.build(self.__name)

        attrs = {}
        for fld in fld_list:
            attrs[fld] = self.__mbean_data[bean][fld].value
        return attrs

    def __get_mbean_value(self, bean, fld):
        if self.__mbean_data is None:
            self.__mbean_data = DAQMBeans.build(self.__name)

        val = self.__mbean_data[bean][fld].value

        return self.__fix_value(val)

    def __get_run_data(self, run_num):  # pylint: disable=unused-argument
        if self.__run_data is None:
            raise Exception("RunData has not been set")
        return self.__fix_value(self.__run_data)

    @classmethod
    def __get_start_order(cls, name):
        if name not in cls.COMP_ORDER:
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name][1]

    def __get_state(self):
        return self.__state

    def __list_getters(self, bean):
        if self.__mbean_data is None:
            self.__mbean_data = DAQMBeans.build(self.__name)

        k = sorted(self.__mbean_data[bean].keys())
        return k

    def __list_mbeans(self):
        if self.__mbean_data is None:
            self.__mbean_data = DAQMBeans.build(self.__name)

        k = sorted(self.__mbean_data.keys())
        return k

    def __log(self, msg):
        if self.__logger is None and self.__liver is None:
            raise Exception('No logging for %s' % (str(self)))
        if self.__logger is not None:
            self.__logger.write(msg)
        if self.__liver is not None:
            now = datetime.datetime.utcnow()
            self.__liver.write('%s(log:str) %d [%s] %s' %
                               (SERVICE_NAME, Prio.DEBUG, now, msg))

    def __log_to(self, log_host, log_port, live_host, live_port):
        if log_host == '':
            log_host = None
        if log_port == 0:
            log_port = None

        # close old logger before opening new logger
        if self.__logger is not None:
            self.__logger.close()
        if log_host is not None and log_port is not None:
            self.__logger = SocketWriter(log_host, log_port)
        else:
            self.__logger = None

        if live_host == '':
            live_host = None
        if live_port == 0:
            live_port = None
        if live_host is not None and live_port is not None:
            self.__liver = SocketWriter(live_host, live_port)
        else:
            self.__liver = None

        self.__log('Hello from %s' % str(self))
        return 'OK'

    def __prepare_subrun(self, rid):
        self.__log('Prep subrun %d' % rid)
        return 'PREP'

    def __reset(self):
        self.__state = 'idle'
        return 'RESET'

    def __reset_logging(self):
        if self.__logger is not None:
            self.__logger.close()
            self.__logger = None

        return 'RLOG'

    def __set_first_good_time(self, pay_time):
        self.__first_good_time = pay_time
        return "OK"

    def __set_last_good_time(self, pay_time):
        self.__last_good_time = pay_time
        return "OK"

    def __start_run(self, run_num, dom_mode):
        if self.__connections is None:
            print("Component %s has no connections" % str(self),
                  file=sys.stderr)
        elif self.__name != "eventBuilder":
            for conn in self.__connections:
                if conn.state != 'running':
                    print("Comp %s is running before %s" %
                          (str(conn), str(self)), file=sys.stderr)

        self.__state = 'running'
        return 'RUN#%d' % run_num

    def __start_subrun(self, data):
        self.__log('Start subrun %s' % str(data))
        return int(time.time())

    def __stop_run(self):
        self.__log('Stop %s' % str(self))

        if self.__connections is None:
            print("Component %s has no connections" % str(self),
                  file=sys.stderr)
        elif self.__name != "eventBuilder":
            for conn in self.__connections:
                if conn.state == 'stopped':
                    print("Comp %s is stopped before %s" %
                          (str(conn), str(self)), file=sys.stderr)

        self.__state = 'ready'
        return 'STOP'

    def add_i3live_monitoring(self, live_log, use_mbean_data=True):
        if self.__mbean_data is None:
            self.__mbean_data = DAQMBeans.build(self.__name)

        bean_keys = sorted(self.__mbean_data.keys())
        for bean in bean_keys:
            for fld in self.__mbean_data[bean]:
                name = '%s-%d*%s+%s' % (self.__name, self.__num, bean, fld)

                val = None
                if not use_mbean_data and bean == "backEnd":
                    if fld == "EventData":
                        val = [None, 2, 10000000000]
                    elif fld == "FirstEventTime":
                        val = 1000
                    elif fld == "GoodTimes":
                        val = [1000, 10000000000]
                    elif fld == "NumEventsSent":
                        val = 2
                    elif fld == "NumEventsDispatched":
                        val = 2
                if val is None:
                    val = self.__mbean_data[bean][fld].value

                if bean == "backEnd" and fld == "EventData":
                    fldtype = "json"
                else:
                    fldtype = None

                live_log.add_expected_live_moni(name, val, fldtype)

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

    @property
    def compare_key(self):
        "Return the keys to be used by the Comparable methods"
        return (self.launch_order, self.num)

    def connect_to_cnc(self):
        self.__cnc = rpcclient.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER)

    @property
    def fullname(self):
        if self.__num == 0 and not self.__name.lower().endswith("hub"):
            return self.__name

        return "%s#%d" % (self.__name, self.__num)

    @property
    def mbean_port(self):
        return self.__mbean.portnum

    @property
    def state(self):
        return self.__get_state()

    @property
    def hitspool_directory(self):
        return self.__hs_dir

    @property
    def hitspool_interval(self):
        return self.__hs_interval

    @property
    def hitspool_max_files(self):
        return self.__hs_max_files

    def is_component(self, name, num=-1):
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def jvm_args(self):
        return self.__jvm_args

    @property
    def jvm_extra_args(self):
        return self.__jvm_extra_args

    @property
    def jvm_heap_init(self):
        return self.__jvm_heap_init

    @property
    def jvm_heap_max(self):
        return self.__jvm_heap_max

    @property
    def jvm_path(self):
        return self.__jvm_path

    @property
    def jvm_server(self):
        return self.__jvm_server

    @property
    def launch_order(self):
        if self.__launch_order is None:
            if self.__name not in self.COMP_ORDER:
                raise Exception('Unknown component type %s' % self.__name)
            self.__launch_order = self.COMP_ORDER[self.__name][0]

        return self.__launch_order

    def log_to(self, log_host, log_port, live_host, live_port):
        return self.__log_to(log_host, log_port, live_host, live_port)

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    @property
    def order(self):
        if self.__name not in self.COMP_ORDER:
            raise Exception('Unknown component type %s' % self.__name)
        return self.COMP_ORDER[self.__name][0]

    def register(self, conn_list):
        reg = self.__cnc.rpc_component_register(self.__name, self.__num,
                                                'localhost',
                                                self.__cmd.portnum,
                                                self.__mbean.portnum,
                                                conn_list)
        if not isinstance(reg, dict):
            raise Exception('Expected registration to return dict, not %s' %
                            str(type(reg)))

        num_elems = 6
        if len(reg) != num_elems:
            raise Exception(('Expected registration to return %d-element' +
                             ' dictionary, not %d') % (num_elems, len(reg)))

        self.__id = reg["id"]

        self.__log_to(reg["logIP"], reg["logPort"], reg["liveIP"],
                      reg["livePort"])

    def set_component_list(self, comp_list):
        self.__comp_list = comp_list

    def set_mbean(self, bean, fld, val):
        if self.__mbean_data is None:
            self.__mbean_data = DAQMBeans.build(self.__name)

        self.__mbean_data[bean][fld].value = val

    def set_run_data(self, val0, val1, val2, val3, val4, val5=None):
        if val5 is None:
            self.__run_data = (int(val0), int(val1), int(val2), int(val3),
                               int(val4))
        else:
            self.__run_data = (int(val0), int(val1), int(val2), int(val3),
                               int(val4), int(val5))

    @property
    def start_order(self):
        if self.__name not in self.COMP_ORDER:
            raise Exception('Unknown component type %s' % self.__name)
        return self.COMP_ORDER[self.__name][1]


class IntegrationTest(unittest.TestCase):
    CLUSTER_CONFIG = 'deadConfig'
    CLUSTER_DESC = 'non-cluster'
    CONFIG_SOURCE = os.path.abspath('src/test/resources/config')
    CONFIG_NAME = 'simpleConfig'
    COPY_DIR = 'bogus'
    DATA_DIR = '/tmp'
    SPADE_DIR = '/tmp'
    CONFIG_DIR = None
    LOG_DIR = None
    LIVEMONI_ENABLED = False

    NUM_COMPONENTS = 9

    @classmethod
    def __check_active_threads(cls):
        reps = 5
        for num in range(reps):
            if threading.activeCount() < 2:
                break

            need_hdr = True
            for thrd in threading.enumerate():
                if thrd.name == "MainThread":
                    continue

                if need_hdr:
                    print("---- Active threads #%d" %
                          (reps - num), file=sys.stderr)
                    need_hdr = False
                print("  %s" % thrd, file=sys.stderr)

            time.sleep(1)

        if threading.activeCount() > 1:
            print("tearDown exiting with %d active threads" %
                  threading.activeCount(), file=sys.stderr)

    def __create_components(self):
        hs_dir = "/mnt/data/nowhere"
        hs_interval = 15.0
        hs_max_files = 18000

        # Note that these jvm_path/jvmArg values needs to correspond to
        # what would be used by the config in 'sim-localhost'
        jvm_path = 'java'
        jvm_server = True
        jvm_heap_init = None
        jvm_heap_max = "512m"
        jvm_args = None
        jvm_extra = None
        comps = [('stringHub', 1001, 9111, 9211, hs_dir, hs_interval,
                  hs_max_files, jvm_path, jvm_server, jvm_heap_init,
                  jvm_heap_max, jvm_args, jvm_extra),
                 ('stringHub', 1002, 9112, 9212, hs_dir, hs_interval,
                  hs_max_files, jvm_path, jvm_server,
                  jvm_heap_init, jvm_heap_max, jvm_args, jvm_extra),
                 ('stringHub', 1003, 9113, 9213, hs_dir, hs_interval,
                  hs_max_files, jvm_path, jvm_server,
                  jvm_heap_init, jvm_heap_max, jvm_args, jvm_extra),
                 ('stringHub', 1004, 9114, 9214, hs_dir, hs_interval,
                  hs_max_files, jvm_path, jvm_server,
                  jvm_heap_init, jvm_heap_max, jvm_args, jvm_extra),
                 ('stringHub', 1005, 9115, 9215, hs_dir, hs_interval,
                  hs_max_files, jvm_path, jvm_server,
                  jvm_heap_init, jvm_heap_max, jvm_args, jvm_extra),
                 ('inIceTrigger', 0, 9117, 9217, None, None, None, jvm_path,
                  jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
                  jvm_extra),
                 ('globalTrigger', 0, 9118, 9218, None, None, None, jvm_path,
                  jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
                  jvm_extra),
                 ('eventBuilder', 0, 9119, 9219, None, None, None, jvm_path,
                  jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
                  jvm_extra),
                 ('secondaryBuilders', 0, 9120, 9220, None, None, None,
                  jvm_path, jvm_server, jvm_heap_init, jvm_heap_max, jvm_args,
                  jvm_extra)]

        if len(comps) != IntegrationTest.NUM_COMPONENTS:
            raise Exception("Expected %d components, not %d" %
                            (IntegrationTest.NUM_COMPONENTS, len(comps)))

        for cval in comps:
            comp = RealComponent(cval[0], cval[1], cval[2], cval[3], cval[4],
                                 cval[5], cval[6], cval[7], cval[8], cval[9],
                                 cval[10], cval[11], cval[12])

            if self.__comp_list is None:
                self.__comp_list = []
            self.__comp_list.append(comp)
            comp.set_component_list(self.__comp_list)

        self.__comp_list.sort()

    def __create_live_objects(self, live_port):
        num_comps = IntegrationTest.NUM_COMPONENTS * 2
        log = self.__log_factory.create_log('liveMoni', DAQPort.I3LIVE, False,
                                            depth=num_comps)

        log.add_expected_text('Connecting to DAQRun')
        log.add_expected_text('Started %s service on port %d' %
                              (SERVICE_NAME, live_port))

        self.__live = LiveStub(live_port)

        return (self.__live, log)

    @classmethod
    def __create_loggers(cls, run_options, live_run_only):
        if not RunOption.is_log_to_file(run_options) and not live_run_only:
            appender = None
        else:
            appender = MockLogger('main',
                                  depth=IntegrationTest.NUM_COMPONENTS)

        dash_log = MockLogger("dash")
        return (appender, dash_log)

    def __create_run_objects(self, run_options, live_run_only=False):

        (appender, dash_log) = \
            self.__create_loggers(run_options, live_run_only)

        self.__create_components()

        clu_cfg = MockClusterConfig(IntegrationTest.CLUSTER_CONFIG,
                                    IntegrationTest.CLUSTER_DESC)
        for comp in self.__comp_list:
            clu_cfg.add_component(comp.fullname, comp.jvm_path, comp.jvm_args,
                                  "localhost")

        if RunOption.is_log_to_file(run_options) or live_run_only:
            log_port = DAQPort.CATCHALL
        else:
            log_port = None
        if RunOption.is_log_to_live(run_options) and not live_run_only:
            live_port = DAQPort.I3LIVE
        else:
            live_port = None

        self.__cnc = MostlyCnCServer(clu_cfg, log_port, live_port,
                                     self.COPY_DIR, self.LOG_DIR,
                                     self.CONFIG_DIR, self.DATA_DIR,
                                     self.SPADE_DIR)
        self.__cnc.set_dash_appender(dash_log)

        return (self.__cnc, appender, dash_log)

    def __force_monitoring(self, cnc, live_moni):
        task_mgr = cnc.runset().task_manager

        if live_moni is not None:
            live_moni.set_check_depth(32)
            for comp in self.__comp_list:
                comp.add_i3live_monitoring(live_moni)

        task_mgr.trigger_timer(MonitorTask.name)
        time.sleep(MostlyTaskManager.WAITSECS)
        task_mgr.wait_for_tasks()

        if live_moni is not None:
            self.__wait_for_empty_log(live_moni, "Didn't get moni messages")

    def __force_rate(self, cnc, dash_log, run_num):
        task_mgr = cnc.runset().task_manager

        self.__set_bean_data("eventBuilder", 0, "backEnd", "EventData",
                             [run_num, 0, 0])
        self.__set_bean_data("eventBuilder", 0, "backEnd", "FirstEventTime", 0)
        self.__set_bean_data("eventBuilder", 0, "backEnd", "GoodTimes", [0, 0])
        for bldr in ("moni", "sn", "tcal"):
            self.__set_bean_data("secondaryBuilders", 0, bldr + "Builder",
                                 "EventData", [run_num, 0, 0])

        dash_log.add_expected_regexp(r"\s*0 physics events, 0 moni events," +
                                     r" 0 SN events, 0 tcals")

        task_mgr.trigger_timer(RateTask.name)
        time.sleep(MostlyTaskManager.WAITSECS)
        task_mgr.wait_for_tasks()

        self.__wait_for_empty_log(dash_log, "Didn't get rate message")

        num_evts = 5
        first_time = 5000
        cur_time = 20000000000 + first_time

        self.__set_bean_data("eventBuilder", 0, "backEnd", "EventData",
                             [run_num, num_evts, cur_time])
        self.__set_bean_data("eventBuilder", 0, "backEnd", "FirstEventTime",
                             first_time)
        self.__set_bean_data("eventBuilder", 0, "backEnd", "GoodTimes",
                             [first_time, cur_time])

        duration = (cur_time - first_time) / 10000000000
        if duration <= 0:
            hz_str = ""
        else:
            hz_str = " (%2.2f Hz)" % (float(num_evts - 1) / float(duration))

        dash_log.add_expected_exact("	%d physics events%s, 0 moni events,"
                                    " 0 SN events, 0 tcals" %
                                    (num_evts, hz_str))

        task_mgr.trigger_timer(RateTask.name)
        time.sleep(MostlyTaskManager.WAITSECS)
        task_mgr.wait_for_tasks()

        self.__wait_for_empty_log(dash_log, "Didn't get second rate message")

    def __force_watchdog(self, cnc, dash_log):
        task_mgr = cnc.runset().task_manager

        self.__set_bean_data("eventBuilder", 0, "backEnd", "DiskAvailable", 0)

        for idx in range(5):
            if idx >= 3:
                dash_log.add_expected_regexp(r"Watchdog reports starved"
                                             r" components.*")
                dash_log.add_expected_regexp(r"Watchdog reports stagnant"
                                             r" components.*")
                dash_log.add_expected_regexp(r"Watchdog reports threshold"
                                             r" components.*")

            task_mgr.trigger_timer(WatchdogTask.name)
            time.sleep(MostlyTaskManager.WAITSECS)
            task_mgr.wait_for_tasks()

    @classmethod
    def __get_connection_list(cls, name):
        if name == 'stringHub':
            conn_list = [
                ('moniData', Connector.OUTPUT, -1),
                ('rdoutData', Connector.OUTPUT, -1),
                ('rdoutReq', Connector.INPUT, -1),
                ('snData', Connector.OUTPUT, -1),
                ('tcalData', Connector.OUTPUT, -1),
                ('stringHit', Connector.OUTPUT, -1),
            ]
        elif name == 'inIceTrigger':
            conn_list = [
                ('stringHit', Connector.INPUT, -1),
                ('trigger', Connector.OUTPUT, -1),
            ]
        elif name == 'globalTrigger':
            conn_list = [
                ('glblTrig', Connector.OUTPUT, -1),
                ('trigger', Connector.INPUT, -1),
            ]
        elif name == 'eventBuilder':
            conn_list = [
                ('glblTrig', Connector.INPUT, -1),
                ('rdoutData', Connector.INPUT, -1),
                ('rdoutReq', Connector.OUTPUT, -1),
            ]
        elif name == 'secondaryBuilders':
            conn_list = [
                ('moniData', Connector.INPUT, -1),
                ('snData', Connector.INPUT, -1),
                ('tcalData', Connector.INPUT, -1),
            ]
        else:
            raise Exception('Cannot get connection list for %s' % name)

        return conn_list

    def __register_components(self, live_log, log_server, live_run_only):
        for comp in self.__comp_list:
            if log_server is not None:
                log_server.add_expected_text("Registered %s" %
                                             (comp.fullname, ))
                log_server.add_expected_exact('Hello from %s' % (comp, ))
            if live_log is not None and not live_run_only:
                live_log.add_expected_text('Registered %s' % (comp.fullname, ))
                live_log.add_expected_text('Hello from %s' % (comp, ))
            comp.register(self.__get_connection_list(comp.name))

    def __run_test(self, live, cnc, live_log, appender, dash_log, run_options,
                   live_run_only):

        try:
            self.__test_body(live, cnc, live_log, appender, dash_log,
                             run_options, live_run_only)
        finally:
            time.sleep(0.4)

            cnc.close_server()

    def __set_bean_data(self, comp_name, comp_num, bean_name, field_name,
                        value):
        set_data = False
        for comp in self.__comp_list:
            if comp.name == comp_name and comp.num == comp_num:
                comp.set_mbean(bean_name, field_name, value)
                set_data = True
                break

        if not set_data:
            raise Exception("Could not find component %s#%d" %
                            (comp_name, comp_num))

    def __set_run_data(self, num_evts, start_evt_time, last_evt_time,
                       first_good, last_good, num_tcal, tcal_ticks, num_sn,
                       sn_ticks, num_moni, moni_ticks):
        for comp in self.__comp_list:
            if comp.name == "eventBuilder":
                comp.set_run_data(num_evts, start_evt_time, last_evt_time,
                                  first_good, last_good)
            elif comp.name == "secondaryBuilders":
                comp.set_run_data(num_tcal, tcal_ticks, num_sn, sn_ticks,
                                  num_moni, moni_ticks)

    def __test_body(self, live, cnc, live_log, appender, dash_log,
                    run_options, live_run_only):
        for comp in self.__comp_list:
            comp.connect_to_cnc()

        log_server = cnc.get_log_server()

        runlog_info = False

        if live_log:
            live_log.check_status(10)
        if appender:
            appender.check_status(10)
        if dash_log:
            dash_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        self.__register_components(live_log, log_server, live_run_only)

        time.sleep(0.4)

        if live_log:
            live_log.check_status(10)
        if appender:
            appender.check_status(10)
        if log_server:
            log_server.check_status(10)

        set_id = RunSet.ID_SOURCE.peek_next()
        run_num = 654
        config_name = IntegrationTest.CONFIG_NAME

        if live_log:
            live_log.add_expected_text('Starting run %d - %s' %
                                       (run_num, config_name))

        if runlog_info:
            if live_log:
                live_log.add_expected_text('Loading run configuration "%s"' %
                                           config_name)
                live_log.add_expected_text('Loaded run configuration "%s"' %
                                           config_name)

            for dtyp in ('in-ice', 'icetop'):
                msg = 'Configuration includes detector %s' % dtyp
                if live_log:
                    live_log.add_expected_text(msg)

            for comp in self.__comp_list:
                msg = 'Component list will require %s#%d' % \
                    (comp.name, comp.num)
                if live_log:
                    live_log.add_expected_text(msg)

        for lstr in ("Loading", "Loaded"):
            msg = '%s run configuration "%s"' % (lstr, config_name)
            if live_log and not live_run_only:
                live_log.add_expected_text(msg)
            if log_server:
                log_server.add_expected_text(msg)

        msg = r'Built runset #\d+: .*'
        if live_log and not live_run_only:
            live_log.add_expected_text_regexp(msg)
        if log_server:
            log_server.add_expected_text_regexp(msg)

        msg = 'Created Run Set #%d' % set_id
        if live_log:
            live_log.add_expected_text(msg)

        msg_list = [
            ('Version info: ' +
             get_scmversion_str(info=cnc.version_info())),
            'Starting run %d...' % run_num,
            'Run configuration: %s' % config_name
        ]
        if runlog_info:
            msg_list.append('Created logger for CnCServer')

        if live_log:
            for msg in msg_list:
                live_log.add_expected_text(msg)

            live_log.add_expected_regexp(r"Waited \d+\.\d+ seconds"
                                         r" for NonHubs")
            live_log.add_expected_regexp(r"Waited \d+\.\d+ seconds"
                                         r" for Hubs")

        if dash_log:
            dash_log.add_expected_regexp(r'Version info: \S+ \S+ \S+ \S+')
            dash_log.add_expected_exact('Run configuration: %s' % config_name)
            dash_log.add_expected_exact("Cluster: " +
                                        IntegrationTest.CLUSTER_DESC)

        if live_log:
            keys = self.__comp_list[:]
            keys.sort(key=lambda x: x.start_order)

            for comp in keys:
                live_log.add_expected_text('Hello from %s' % str(comp))
                re_fmt = r'Version info: %s \S+ \S+ \S+'
                live_log.add_expected_text_regexp(re_fmt % comp.name)

        if runlog_info:
            msg = 'Configuring run set...'
            if appender and not live_run_only:
                appender.add_expected_exact(msg)
            if live_log:
                live_log.add_expected_text(msg)

            if RunOption.is_moni_to_file(run_options):
                run_dir = os.path.join(IntegrationTest.LOG_DIR,
                                       str(run_num))
                for comp in self.__comp_list:
                    msg = ("Creating moni output file %s/%s-%d.moni"
                           " (remote is localhost:%d)") % \
                           (run_dir, comp.name, comp.num, comp.mbean_port)
                    if appender and not live_run_only:
                        appender.add_expected_exact(msg)
                    if live_log:
                        live_log.add_expected_text(msg)

        msg = "Starting run #%d on \"%s\"" % \
            (run_num, IntegrationTest.CLUSTER_DESC)
        if live_log and not live_run_only:
            live_log.add_expected_text(msg)
        if log_server:
            log_server.add_expected_text(msg)

        if dash_log:
            dash_log.add_expected_exact("Starting run %d..." % run_num)

        if log_server:
            log_server.add_expected_text_regexp(r"Waited \d+\.\d+ seconds"
                                                r" for NonHubs")
            log_server.add_expected_text_regexp(r"Waited \d+\.\d+ seconds"
                                                r" for Hubs")

        if live_log:
            for comp in self.__comp_list:
                live_log.add_expected_text('Start #%d on %s' %
                                           (run_num, str(comp)))

        msg = 'Started run %d on run set %d' % (run_num, set_id)
        if live_log:
            live_log.add_expected_text(msg)

        start_evt_time = 1001

        if live_log:
            live_log.add_expected_text_regexp(r"DAQ state is RUNNING after" +
                                              r" \d+ seconds")
            live_log.add_expected_text('Started run %d' % run_num)

        if live is not None:
            live.starting({'runNumber': run_num, 'runConfig': config_name})
        else:
            new_id = cnc.rpc_runset_make(config_name, run_num)
            self.assertEqual(set_id, new_id,
                             "Expected to create runset #%d, not #%d" %
                             (set_id, new_id))
            cnc.rpc_runset_start_run(set_id, run_num, RunOption.LOG_TO_FILE)

        self.__wait_for_state(cnc, set_id, "running")

        if live_log:
            live_log.check_status(10)
        if appender:
            appender.check_status(500)
        if dash_log:
            dash_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        if RunOption.is_moni_to_live(run_options):
            # monitoring values can potentially come in any order
            live_log.set_check_depth(32)
            for comp in self.__comp_list:
                comp.add_i3live_monitoring(live_log)

        if live_log:
            active_dom_map = {}
            for comp in self.__comp_list:
                if comp.is_component("stringHub"):
                    active_dom_map[str(comp.num)] = 0
            live_log.add_expected_live_moni("activeDOMs", 0)
            live_log.add_expected_live_moni("expectedDOMs", 0)
            live_log.add_expected_live_moni("activeStringDOMs", active_dom_map,
                                            "json")
        self.__force_monitoring(cnc, live_log)

        if live_log:
            live_log.check_status(10)
        if appender:
            appender.check_status(500)
        if dash_log:
            dash_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        self.__force_rate(cnc, dash_log, run_num)

        if live_log:
            live_log.check_status(10)
        if appender:
            appender.check_status(500)
        if dash_log:
            dash_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        self.__force_watchdog(cnc, dash_log)

        if live_log:
            live_log.check_status(10)
        if appender:
            appender.check_status(500)
        if dash_log:
            dash_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        if RunOption.is_moni_to_live(run_options):
            live_log.set_check_depth(5)

        sub_run_id = 1

        if live_log:
            live_log.add_expected_text('Starting subrun %d.%d' %
                                       (run_num, sub_run_id))

        dom_list = [['53494d550101', 0, 1, 2, 3, 4],
                    ['1001', '22', 1, 2, 3, 4, 5],
                    ('a', 0, 1, 2, 3, 4)]

        raw_flash_list = []
        rpc_flash_list = []
        for i in range(len(dom_list)):
            if i == 0:
                raw_flash_list.append(dom_list[0])

                data = []
                data += dom_list[0][:]
                rpc_flash_list.append(data)
            elif i == 1:
                data = ['53494d550122', ]
                data += dom_list[1][2:]
                raw_flash_list.append(data)
                rpc_flash_list.append(data)
            else:
                break

        msg = "Subrun %d: ignoring missing DOM ['#%s']" % \
              (sub_run_id, dom_list[2][0])
        if dash_log:
            dash_log.add_expected_exact(msg)

        fmt = 'Subrun %d: flashing DOM (%%s)' % sub_run_id
        if dash_log:
            dash_log.add_expected_exact(fmt % str(rpc_flash_list))

        for comp in self.__comp_list:
            if not appender or live_run_only:
                clog = None
            else:
                clog = MostlyRunSet.get_component_log(comp)
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (comp.name, comp.num))

            if comp.name == 'eventBuilder':
                msg = 'Prep subrun %d' % sub_run_id
                if clog:
                    clog.add_expected_exact(msg)
                if live_log:
                    live_log.add_expected_text(msg)

            if comp.name == 'stringHub':
                msg = 'Start subrun %s' % str(rpc_flash_list)
                if clog:
                    clog.add_expected_exact(msg)
                if live_log:
                    live_log.add_expected_text(msg)

            if comp.name == 'eventBuilder':
                pat_str = r'Commit subrun %d: \d+' % sub_run_id
                if clog:
                    clog.add_expected_regexp(pat_str)
                if live_log:
                    live_log.add_expected_text_regexp(pat_str)

        if live is not None:
            live.subrun(sub_run_id, dom_list)
        else:
            cnc.rpc_runset_subrun(set_id, sub_run_id, dom_list)

        if dash_log:
            dash_log.check_status(10)
        if appender:
            appender.check_status(10)
        if live_log:
            live_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        sub_run_id += 1

        if live_log:
            live_log.add_expected_text('Stopping subrun %d.%d' %
                                       (run_num, sub_run_id))

        msg = 'Subrun %d: stopping flashers' % sub_run_id
        if dash_log:
            dash_log.add_expected_exact(msg)

        for comp in self.__comp_list:
            if not appender or live_run_only:
                clog = None
            else:
                clog = MostlyRunSet.get_component_log(comp)
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (comp.name, comp.get_number()))

            if comp.name == 'eventBuilder':
                msg = 'Prep subrun %d' % sub_run_id
                if clog:
                    clog.add_expected_exact(msg)
                if live_log:
                    live_log.add_expected_text(msg)

            if comp.name == 'stringHub':
                msg = 'Start subrun %s' % str([])
                if clog:
                    clog.add_expected_exact(msg)
                if live_log:
                    live_log.add_expected_text(msg)

            if comp.name == 'eventBuilder':
                pat_str = r'Commit subrun %d: \d+' % sub_run_id
                if clog:
                    clog.add_expected_regexp(pat_str)
                if live_log:
                    live_log.add_expected_text_regexp(pat_str)

        if live is not None:
            live.subrun(sub_run_id, [])
        else:
            cnc.rpc_runset_subrun(set_id, sub_run_id, [])

        if dash_log:
            dash_log.check_status(10)
        if appender:
            appender.check_status(10)
        if live_log:
            live_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        if live_log:
            live_log.add_expected_text('Stopping run %d' % run_num)

        dom_ticks_per_sec = 10000000000

        num_evts = 17
        num_moni = 222
        moni_ticks = 0
        num_sn = 51
        sn_ticks = 0
        num_tcal = 93
        tcal_ticks = 0
        last_evt_time = start_evt_time + (dom_ticks_per_sec * 3)

        self.__set_bean_data("eventBuilder", 0, "backEnd", "NumEventsSent",
                             num_evts)
        self.__set_bean_data("eventBuilder", 0, "backEnd",
                             "NumEventsDispatched", num_evts)
        self.__set_bean_data("eventBuilder", 0, "backEnd", "EventData",
                             [run_num, num_evts, last_evt_time])
        self.__set_bean_data("eventBuilder", 0, "backEnd", "FirstEventTime",
                             start_evt_time)
        self.__set_bean_data("eventBuilder", 0, "backEnd", "GoodTimes",
                             (start_evt_time, last_evt_time))
        self.__set_bean_data("secondaryBuilders", 0, "moniBuilder",
                             "NumDispatchedData", num_moni)
        self.__set_bean_data("secondaryBuilders", 0, "moniBuilder",
                             "EventData", (run_num, num_moni, moni_ticks))
        self.__set_bean_data("secondaryBuilders", 0, "snBuilder",
                             "NumDispatchedData", num_sn)
        self.__set_bean_data("secondaryBuilders", 0, "snBuilder",
                             "EventData", (run_num, num_sn, sn_ticks))
        self.__set_bean_data("secondaryBuilders", 0, "tcalBuilder",
                             "NumDispatchedData", num_tcal)
        self.__set_bean_data("secondaryBuilders", 0, "tcalBuilder",
                             "EventData", (run_num, num_tcal, tcal_ticks))

        self.__set_run_data(num_evts, start_evt_time, last_evt_time,
                            start_evt_time, last_evt_time, num_tcal,
                            tcal_ticks, num_sn, sn_ticks, num_moni, moni_ticks)

        msg = 'Stopping run %d' % run_num
        if live_log:
            live_log.add_expected_text(msg)

        for comp in self.__comp_list:
            if not appender or live_run_only:
                clog = None
            else:
                clog = MostlyRunSet.get_component_log(comp)
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (comp.name, comp.num))

            msg = 'Stop %s#%d' % (comp.name, comp.num)
            if clog:
                clog.add_expected_exact(msg)
            if live_log:
                live_log.add_expected_text(msg)

        pat_str = (r'%d physics events collected in -?\d+ seconds' +
                   r'(\s+\(-?\d+\.\d+ Hz\))?') % num_evts
        dash_log.add_expected_regexp(pat_str)
        if live_log:
            live_log.add_expected_text_regexp(pat_str)

        msg = '%d moni events, %d SN events, %d tcals' % \
            (num_moni, num_sn, num_tcal)
        dash_log.add_expected_exact(msg)
        if live_log:
            live_log.add_expected_text(msg)

        if runlog_info:
            msg = 'Stopping component logging'
            if appender and not live_run_only:
                appender.add_expected_exact(msg)
            if live_log:
                live_log.add_expected_text(msg)

            pat_str = 'RPC Call stats:.*'
            if appender and not live_run_only:
                appender.add_expected_regexp(pat_str)
            if live_log:
                live_log.add_expected_text_regexp(pat_str)

        msg = 'Run terminated SUCCESSFULLY.'
        dash_log.add_expected_exact(msg)
        if live_log:
            live_log.add_expected_text(msg)

        dash_log.add_expected_exact("Not logging to file so cannot queue to"
                                    " SPADE")

        if live_log:
            live_log.add_expected_text_regexp(r"DAQ state is STOPPED after"
                                              r" \d+ seconds")
            live_log.add_expected_text('Stopped run %d' % run_num)

        if live is not None:
            live.stopping()
        else:
            cnc.rpc_runset_stop_run(set_id)

        self.__wait_for_state(cnc, set_id, "ready")

        if dash_log:
            dash_log.check_status(10)
        if appender:
            appender.check_status(10)
        if live_log:
            live_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        cnc.update_rates(set_id)

        moni = cnc.rpc_runset_monitor_run(set_id, run_num)
        self.assertFalse(moni is None, 'rpc_run_monitoring returned None')
        self.assertFalse(len(moni) == 0, 'rpc_run_monitoring returned no data')
        self.assertEqual(num_evts, moni['physicsEvents'],
                         'Expected %d physics events, not %d' %
                         (num_evts, moni['physicsEvents']))
        self.assertEqual(num_moni, moni['moniEvents'],
                         'Expected %d moni events, not %d' %
                         (num_moni, moni['moniEvents']))
        self.assertEqual(num_sn, moni['snEvents'],
                         'Expected %d sn events, not %d' %
                         (num_sn, moni['snEvents']))
        self.assertEqual(num_tcal, moni['tcalEvents'],
                         'Expected %d tcal events, not %d' %
                         (num_tcal, moni['tcalEvents']))

        if dash_log:
            dash_log.check_status(10)
        if appender:
            appender.check_status(10)
        if live_log:
            live_log.check_status(10)
        if log_server:
            log_server.check_status(10)

        RunXMLValidator.validate(self, run_num, config_name,
                                 IntegrationTest.CLUSTER_DESC, None, None,
                                 num_evts, num_moni, num_sn, num_tcal, False)

        if runlog_info:
            msg = 'Breaking run set...'
            if live_log and not live_run_only:
                live_log.add_expected_text(msg)

        if live is not None:
            live.release()
        else:
            cnc.rpc_runset_break(set_id)

        if dash_log:
            dash_log.check_status(10)
        if appender:
            appender.check_status(10)
        if live_log:
            live_log.check_status(10)
        if log_server:
            log_server.check_status(10)

    @staticmethod
    def __wait_for_empty_log(log, errmsg):  # pylint: disable=unused-argument
        for _ in range(5):
            if log.is_empty:
                break
            time.sleep(0.25)
        log.check_status(1)

    def __wait_for_state(self, cnc, set_id, exp_state):
        num_tries = 0
        state = 'unknown'
        while num_tries < 500:
            state = cnc.rpc_runset_state(set_id)
            if state == exp_state:
                break
            time.sleep(0.1)
            num_tries += 1
        self.assertEqual(exp_state, state, 'Should be %s, not %s' %
                         (exp_state, state))

    def setUp(self):
        if sys.version_info < (2, 7):
            self.setUpClass()

        MostlyCnCServer.APPENDERS.clear()
        DAQMBeans.clear()

        self.__log_factory = SocketReaderFactory()

        IntegrationTest.LOG_DIR = tempfile.mkdtemp()

        DAQLive.STATE_WARNING = False

        self.__live = None
        self.__cnc = None
        self.__comp_list = None

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        RunXMLValidator.setUp()

    @classmethod
    def setUpClass(cls):
        cls.CONFIG_DIR = tempfile.mkdtemp()

        # make a copy of the config files so we can add a NIST leapsecond file
        if not os.path.isdir(cls.CONFIG_DIR):
            raise OSError("Cannot find temporary directory \"%s\"" %
                          (cls.CONFIG_DIR, ))
        os.rmdir(cls.CONFIG_DIR)
        shutil.copytree(cls.CONFIG_SOURCE, cls.CONFIG_DIR)

        # generate a mock NIST leapseconds file
        MockLeapsecondFile(cls.CONFIG_DIR).create()

        set_pdaq_config_dir(cls.CONFIG_DIR, override=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.CONFIG_DIR, ignore_errors=True)
        cls.CONFIG_DIR = None

        set_pdaq_config_dir(None, override=True)

    def tearDown(self):
        try:
            self.__log_factory.tearDown()
        except:  # pylint: disable=bare-except
            traceback.print_exc()

        if self.__comp_list is not None and \
          len(self.__comp_list) > 0:  # pylint: disable=len-as-condition
            for comp in self.__comp_list:
                comp.close()
        if self.__cnc is not None:
            self.__cnc.close_server()
        if self.__live is not None:
            self.__live.close()

        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].check_status(10)

        MostlyRunSet.close_all_logs()

        shutil.rmtree(IntegrationTest.LOG_DIR, ignore_errors=True)
        IntegrationTest.LOG_DIR = None

        self.__check_active_threads()

        RunXMLValidator.tearDown()

        if sys.version_info < (2, 7):
            self.tearDownClass()

    def test_finish_in_main(self):
        run_options = RunOption.MONI_TO_FILE

        (cnc, appender, dash_log) = \
            self.__create_run_objects(run_options)

        thrd = threading.Thread(name="MainFinish", target=cnc.run, args=())
        thrd.setDaemon(True)
        thrd.start()

        self.__run_test(None, cnc, None, appender, dash_log, run_options,
                        False)

    def test_cnc_in_main(self):
        run_options = RunOption.MONI_TO_FILE

        (cnc, appender, dash_log) = self.__create_run_objects(run_options)

        thrd = threading.Thread(name="CnCFinish", target=self.__run_test,
                                args=(None, cnc, None, appender, dash_log,
                                      run_options, False))
        thrd.setDaemon(True)
        thrd.start()

        cnc.run()

    def test_live_finish_in_main(self):
        print("Not running testLiveFinishInMain")
        return
        # from DAQMocks import LogChecker; LogChecker.DEBUG = True
        if not LIVE_IMPORT:
            print('Skipping I3Live-related test')
            return

        live_port = 9751

        run_options = RunOption.LOG_TO_LIVE | RunOption.MONI_TO_FILE

        (cnc, appender, dash_log) = \
          self.__create_run_objects(run_options, True)

        thrd = threading.Thread(name="LiveFinish", target=cnc.run, args=())
        thrd.setDaemon(True)
        thrd.start()

        (live, live_log) = self.__create_live_objects(live_port)

        self.__run_test(live, cnc, live_log, appender, dash_log, run_options,
                        True)

    def test_z_all_live_finish_in_main(self):
        print("Not running testZAllLiveFinishInMain")
        return
        # from DAQMocks import LogChecker; LogChecker.DEBUG = True
        if not LIVE_IMPORT:
            print('Skipping I3Live-related test')
            return

        live_port = 9751

        if IntegrationTest.LIVEMONI_ENABLED:
            moni_type = RunOption.MONI_TO_LIVE
        else:
            moni_type = RunOption.MONI_TO_NONE

        run_options = RunOption.LOG_TO_LIVE | moni_type

        (cnc, appender, dash_log) = self.__create_run_objects(run_options)

        (live, live_log) = self.__create_live_objects(live_port)

        live_log.add_expected_text_regexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        thrd = threading.Thread(name="AllLiveFinish", target=cnc.run, args=())
        thrd.setDaemon(True)
        thrd.start()

        live_log.check_status(100)

        self.__run_test(live, cnc, live_log, appender, dash_log, run_options,
                        False)

    def test_z_both_finish_in_main(self):
        print("Not running testZBothFinishInMain")
        return
        if not LIVE_IMPORT:
            print('Skipping I3Live-related test')
            return

        live_port = 9751

        if IntegrationTest.LIVEMONI_ENABLED:
            moni_type = RunOption.MONI_TO_BOTH
        else:
            moni_type = RunOption.MONI_TO_FILE

        run_options = RunOption.LOG_TO_BOTH | moni_type

        (cnc, appender, dash_log) = self.__create_run_objects(run_options)

        (live, live_log) = self.__create_live_objects(live_port)

        pat_str = r'\S+ \S+ \S+ \S+ \S+ \S+ \S+'
        live_log.add_expected_text_regexp(pat_str)

        thrd = threading.Thread(name="BothLiveFinish", target=cnc.run, args=())
        thrd.setDaemon(True)
        thrd.start()

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True
        self.__run_test(live, cnc, live_log, appender, dash_log, run_options,
                        False)


if __name__ == '__main__':
    unittest.main()
