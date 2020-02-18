#!/usr/bin/env python

from __future__ import print_function

import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import unittest

try:
    from xmlrpclib import ServerProxy
except ModuleNotFoundError:
    from xmlrpc.client import ServerProxy

from CnCExceptions import CnCServerException
from CnCServer import CnCServer
from Component import Component
from ComponentManager import ComponentManager
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQLog import LogSocketServer
from DAQRPC import RPCServer
from RunOption import RunOption
from RunSet import RunSet
from locate_pdaq import set_pdaq_config_dir

from DAQMocks \
    import MockClusterConfig, MockCnCLogger, MockDefaultDomGeometryFile, \
    MockLeapsecondFile, MockLogger, MockRunConfigFile, SocketReaderFactory, \
    SocketWriter


class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbean_port, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbean_port, connectors,
                                              quiet=True)

    def create_logger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet)


class FakeLogger(object):
    def __init__(self, port):
        if port is None:
            port = LogSocketServer.next_log_port

        self.__port = port

    def __str__(self):
        return "FakeLogger@%s" % (self.__port, )

    @property
    def port(self):
        return self.__port

    def stop_serving(self):
        pass


class FakeRunData(object):
    def __init__(self, run_num, run_cfg, clu_cfg, dashlog=None):
        self.__run_number = run_num
        self.__run_config = run_cfg
        self.__cluster_config = clu_cfg
        self.__dashlog = dashlog

        self.__finished = False

    def clone(self, parent, new_num):
        return FakeRunData(new_num, self.__run_config, self.__cluster_config,
                           dashlog=self.__dashlog)

    @property
    def cluster_configuration(self):
        return self.__cluster_config

    def connect_to_live(self):
        pass

    def destroy(self):
        pass

    def error(self, logmsg):
        if self.__dashlog is None:
            raise Exception("Mock logger has not been set")
        self.__dashlog.error(logmsg)

    @property
    def finished(self):
        return self.__finished

    @property
    def is_error_enabled(self):
        return self.__dashlog.is_error_enabled

    @property
    def log_directory(self):
        return None

    def report_first_good_time(self, runset):
        pass

    def reset(self):
        pass

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

    def set_finished(self):
        self.__finished = True

    def stop_tasks(self):
        pass

    def update_counts_and_rate(self, run_set):
        pass


class MostlyRunSet(RunSet):
    LOGFACTORY = SocketReaderFactory()
    LOGDICT = {}

    def __init__(self, parent, run_config, cluster_config, components,
                 catchall, dashlog):
        self.__run_config = run_config
        self.__cluster_config = cluster_config
        self.__catchall = catchall
        self.__dashlog = dashlog
        self.__log_dict = {}

        super(MostlyRunSet, self).__init__(parent, run_config, components,
                                           catchall)

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

        comp.log_to("localhost", port, None, None)

        return log

    def create_run_data(self, run_num, cluster_config, run_options,
                        version_info, spade_dir, copy_dir=None, log_dir=None):
        return FakeRunData(run_num, self.__run_config, cluster_config,
                           dashlog=self.__dashlog)

    def cycle_components(self, comp_list, config_dir, daq_data_dir, logger,
                         verbose=False, kill_with_9=False, event_check=False,
                         check_exists=True):
        logger.error("Cycling components %s" %
                     (ComponentManager.format_component_list(comp_list), ))

    def final_report(self, comps, run_data, had_error=False, switching=False):
        num_evts = 600
        num_moni = 0
        num_sn = 0
        num_tcal = 0
        num_secs = 6

        self.__dashlog.error("%d physics events collected in %d seconds"
                             " (%.2f Hz)" % (num_evts, num_secs,
                                             float(num_evts) / float(num_secs)))
        self.__dashlog.error("%d moni events, %d SN events, %d tcals" %
                             (num_moni, num_sn, num_tcal))

        if switching:
            verb = "switched"
        else:
            verb = "terminated"
        if had_error:
            result = "WITH ERROR"
        else:
            result = "SUCCESSFULLY"
        self.__dashlog.error("Run %s %s." % (verb, result))

    def finish_setup(self, run_data, start_time):
        run_data.error('Version info: BRANCH 0:0 unknown unknown')
        run_data.error("Run configuration: %s" %
                       (run_data.run_configuration.basename, ))
        run_data.error("Cluster: %s" %
                       (run_data.cluster_configuration.description, ))

    @staticmethod
    def report_good_time(run_data, name, pay_time):
        pass

    @staticmethod
    def switch_component_log(sock, run_dir, comp):
        pass


class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, cluster_config_object, copy_dir=None,
                 run_config_dir=None, daq_data_dir=None, spade_dir=None,
                 log_host='localhost', log_port=-1, log_factory=None,
                 dashlog=None, force_restart=False):

        self.__cluster_config = cluster_config_object
        self.__log_factory = log_factory
        self.__dashlog = dashlog

        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              copy_dir=copy_dir,
                                              run_config_dir=run_config_dir,
                                              daq_data_dir=daq_data_dir,
                                              spade_dir=spade_dir,
                                              log_host=log_host,
                                              log_port=log_port,
                                              force_restart=force_restart,
                                              quiet=True)

    def create_client(self, name, num, host, port, mbean_port, connectors):
        key = '%s#%d' % (name, num)
        key = 'server'
        if key not in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = MockLogger('Mock-%s' % key)

        return MostlyDAQClient(name, num, host, port, mbean_port, connectors,
                               MostlyCnCServer.APPENDERS[key])

    def create_cnc_logger(self, quiet):
        key = 'server'
        if key not in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = MockLogger('Mock-%s' % key)

        return MockCnCLogger(key, appender=MostlyCnCServer.APPENDERS[key],
                             quiet=quiet)

    def create_runset(self, run_config, comp_list, logger):
        return MostlyRunSet(self, run_config, self.__cluster_config, comp_list,
                            logger, self.__dashlog)

    def get_cluster_config(self, run_config=None):
        return self.__cluster_config

    def monitor_loop(self):
        pass

    def open_log_server(self, port, log_dir):
        if MostlyRunSet.LOGFACTORY is None:
            raise Exception("MostlyRunSet log factory has not been set")
        return MostlyRunSet.LOGFACTORY.create_log("catchall", port,
                                                  expect_start_msg=False,
                                                  start_server=False)

    def save_catchall(self, run_dir):
        pass

    def start_live_thread(self):
        return None


class RealComponent(Component):
    def __init__(self, name, num, catchall_host, catchall_port, verbose=False):
        super(RealComponent, self).__init__(name, num, host="localhost")

        self.__log_socket = SocketWriter(catchall_host, catchall_port)

        self.__id = None
        self.__state = "UNKNOWN"
        self.__run_number = None

        self.__daqlog = None
        self.__livelog = None
        self.__bean_data = {}
        self.__event_counts = None

        #self.__connections = []

        self.__cmd = self.__create_cmd_server()
        self.__mbean = self.__create_mbean_server()

        self.__cnc = ServerProxy('http://localhost:%d' %
                                 DAQPort.CNCSERVER, verbose=verbose)

    def __create_cmd_server(self):
        for _ in range(4):
            try:
                cmd_srvr = RPCServer(LogSocketServer.next_log_port)
            except socket.error as serr:
                if serr[0] != 98:
                    raise
                # previous unit test's server may not be closed yet; try again
                continue

        cmd_srvr.register_function(self.__cmd_configure, 'xmlrpc.configure')
        cmd_srvr.register_function(self.__cmd_connect, 'xmlrpc.connect')
        cmd_srvr.register_function(self.__cmd_get_run_number,
                                   'xmlrpc.getRunNumber')
        cmd_srvr.register_function(self.__cmd_get_state, 'xmlrpc.getState')
        cmd_srvr.register_function(self.__cmd_log_to, 'xmlrpc.logTo')
        cmd_srvr.register_function(self.__cmd_reset, 'xmlrpc.reset')
        cmd_srvr.register_function(self.__cmd_reset_logging,
                                   'xmlrpc.resetLogging')
        cmd_srvr.register_function(self.__cmd_set_first_good_time,
                                   'xmlrpc.setFirstGoodTime')
        cmd_srvr.register_function(self.__cmd_set_last_good_time,
                                   'xmlrpc.setLastGoodTime')
        cmd_srvr.register_function(self.__cmd_start_run, 'xmlrpc.startRun')
        cmd_srvr.register_function(self.__cmd_stop_run, 'xmlrpc.stopRun')
        cmd_srvr.register_function(self.__cmd_switch_to_new_run,
                                   'xmlrpc.switchToNewRun')

        tname = "RPCSrvr*" + str(self.fullname)
        thrd = threading.Thread(name=tname, target=cmd_srvr.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        return cmd_srvr

    def __create_mbean_server(self):
        for _ in range(4):
            try:
                mbean_srvr = RPCServer(LogSocketServer.next_log_port)
            except socket.error as serr:
                if serr[0] != 98:
                    raise
                # previous unit test's server may not be closed yet; try again
                continue

        mbean_srvr.register_function(self.__mbean_get_value, 'mbean.get')
        mbean_srvr.register_function(self.__mbean_list, 'mbean.listMBeans')
        mbean_srvr.register_function(self.__mbean_get_attributes,
                                     'mbean.getAttributes')
        mbean_srvr.register_function(self.__mbean_list_getters,
                                     'mbean.listGetters')

        tname = "MBeanSrvr*" + str(self.fullname)
        thrd = threading.Thread(name=tname, target=mbean_srvr.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        return mbean_srvr

    def __cmd_configure(self, cfg_name):
        self.__log_socket.write("Config %s#%s with %s" %
                                (self.name, self.num, cfg_name))

        self.__state = "ready"
        return "CONFIGURED"

    def __cmd_connect(self, conn_list=None):
        try:
            return self.__cmd_connect_internal(conn_list)
        except:
            traceback.print_exc()
            raise

    def __cmd_connect_internal(self, conn_list=None):
        #if conn_list is not None:
        #    for cdict in conn_list:
        #        self.__connections.append(cdict)

        self.__state = "connected"
        return "CONNECTED"

    def __cmd_get_run_number(self):
        return self.__run_number

    def __cmd_get_state(self):
        return self.__state

    def __cmd_log_to(self, log_host, log_port, live_host, live_port):
        if log_host is not None:
            self.__daqlog = MockLogger("DAQLog(%s)" % (self.fullname, ))
            #self.__daqlog.error("Howdy from %s" % (self.fullname, ))
        if live_host is not None:
            self.__livelog = MockLogger("LiveLog(%s)" % (self.fullname, ))
        return "LOGGING"

    def __cmd_reset(self):
        self.__state = "idle"
        return "IGNORED"

    def __cmd_reset_logging(self):
        if self.__daqlog is not None:
            self.__daqlog.check_status(100)
            self.__daqlog.close()
            self.__daqlog = None

        if self.__livelog is not None:
            self.__livelog.check_status(100)
            self.__livelog.close()
            self.__livelog = None

        return "RESETLOG"

    def __cmd_set_first_good_time(self, first_time):
        return "SetFGT"

    def __cmd_set_last_good_time(self, last_time):
        print("Not setting %s LastGoodTime to %s" %
              (self.fullname, last_time), file=sys.stderr)
        return "SetLGT"

    def __cmd_start_run(self, run_number):
        self.__run_number = run_number
        self.__state = "running"
        return "RUNNING"

    def __cmd_stop_run(self):
        self.__log("Stop %s" % (self.fullname, ))

        self.__state = "ready"
        return "STOPPED"

    def __cmd_switch_to_new_run(self, new_number):
        self.__log("Switch %s to run#%d" % (self.fullname, new_number))

        self.__run_number = new_number
        self.__state = "running"
        return "SWITCHED"

    def __log(self, msg):
        if self.__daqlog is None and self.__livelog is None:
            self.__log_socket.write(msg)
        else:
            if self.__daqlog is not None:
                self.__daqlog.write(msg)
            if self.__livelog is not None:
                self.__livelog.write(msg)

    def __mbean_get_attributes(self, bean, attr_list):
        values = {}
        for attr in attr_list:
            values[attr] = self.__mbean_get_value(bean, attr)
        return values

    def __mbean_get_value(self, bean, attr):
        if bean in self.__bean_data:
            if attr in self.__bean_data[bean]:
                return self.__bean_data[bean][attr]

        raise Exception("Unknown %s bean/attribute \"%s.%s\"" %
                        (self.fullname, bean, attr))

    def __mbean_list(self):
        return NotImplementedError("mbean_list")

    def __mbean_list_getters(self, bean):
        return NotImplementedError("mbean_list_getters")

    def check_status(self, reps=100):
        rtnval = True
        if self.__daqlog is not None:
            rtnval &= self.__daqlog.check_status(reps)

        if self.__livelog is not None:
            rtnval &= self.__livelog.check_status(reps)

        return rtnval

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

        for lname, log in (("DAQ", self.__daqlog), ("LIVE", self.__livelog)):
            if log is not None:
                log.check_status(100)
                if not log.is_empty:
                    raise Exception("%s log for %s is not empty" %
                                    (lname, self.fullname, ))
                log.close()

        self.__daqlog = None
        self.__livelog = None

    @property
    def cmd_port(self):
        return self.__cmd.portnum

    @property
    def id(self):
        return self.__id

    @property
    def loggers(self):
        if self.__daqlog is not None:
            yield self.__daqlog
        if self.__livelog is not None:
            yield self.__livelog

    @property
    def mbean_port(self):
        return self.__mbean.portnum

    def register(self, conn_array):
        cmd_port = self.__cmd.portnum
        mbean_port = self.__mbean.portnum
        reg_data = self.__cnc.rpc_component_register(self.name, self.num,
                                                     'localhost', cmd_port,
                                                     mbean_port, conn_array)

        self.__id = reg_data["id"]
        self.__cmd_log_to(reg_data["logIP"], reg_data["logPort"],
                          reg_data["liveIP"], reg_data["livePort"])

    def set_bean_field_value(self, bean_name, fld_name, value):
        if bean_name is None:
            raise Exception("%s bean name cannot be None" % (self.fullname, ))
        if fld_name is None:
            raise Exception("%s field name cannot be None" % (self.fullname, ))

        if bean_name not in self.__bean_data:
            self.__bean_data[bean_name] = {}
        self.__bean_data[bean_name][fld_name] = value

    def set_run_data(self, val1, val2, val3, val4=None, val5=None):
        if val4 is None and val5 is None:
            self.__event_counts = (int(val1), int(val2), int(val3))
        else:
            self.__event_counts = (int(val1), int(val2), int(val3), int(val4),
                                   int(val5))

    @property
    def state(self):
        return self.__state


class RateTracker(object):
    def __init__(self, run_num, ticks_inc, evts_inc, moni_inc, sn_inc,
                 tcal_inc):
        self.__run_number = run_num
        self.__ticks_inc = ticks_inc
        self.__evts_inc = evts_inc
        self.__moni_inc = moni_inc
        self.__sn_inc = sn_inc
        self.__tcal_inc = tcal_inc

        self.__first_evt_time = None

        self.reset()

    def add_final_log_msgs(self, logger):
        num_secs = self.__num_ticks / 10000000000
        logger.add_expected_exact("%d physics events collected"
                                  " in %d seconds (%0.2f Hz)" %
                                  (self.__num_evts, num_secs,
                                   float(self.__num_evts) /
                                   float(num_secs)))
        logger.add_expected_exact("%d moni events, %d SN events, %d tcals" %
                                  (self.__num_moni, self.__num_sn,
                                   self.__num_tcal))

    def get_totals(self):
        return (self.__num_evts, self.__num_moni, self.__num_sn,
                self.__num_tcal)

    def reset(self):
        self.__first_evt_time = None
        self.__num_ticks = 0
        self.__num_evts = 0
        self.__num_moni = 0
        self.__num_sn = 0
        self.__num_tcal = 0

    def update_run_data(self, cnc, rsid, comps):
        self.__num_ticks += self.__ticks_inc
        self.__num_evts += self.__evts_inc
        self.__num_moni += self.__moni_inc
        self.__num_sn += self.__sn_inc
        self.__num_tcal += self.__tcal_inc

        if self.__first_evt_time is None:
            self.__first_evt_time = self.__num_ticks

        last_evt_time = self.__first_evt_time + self.__num_ticks

        for comp in comps:
            if comp.name == "eventBuilder":
                comp.set_run_data(self.__num_evts, self.__first_evt_time,
                                  last_evt_time, self.__first_evt_time,
                                  last_evt_time)
                comp.set_bean_field_value("backEnd", "EventData",
                                          (self.__run_number, self.__num_evts,
                                           last_evt_time))
                comp.set_bean_field_value("backEnd", "FirstEventTime",
                                          self.__first_evt_time)
                comp.set_bean_field_value("backEnd", "GoodTimes",
                                          (self.__first_evt_time, last_evt_time))
            elif comp.name == "secondaryBuilders":
                comp.set_run_data(self.__num_tcal, self.__num_sn,
                                  self.__num_moni)

        cnc.update_rates(rsid)


class CnCServerTest(unittest.TestCase):
    HUB_NUMBER = 1021
    DOM_MAINBOARD_ID = 0x53494d552101

    def setUp(self):
        self.__copy_dir = tempfile.mkdtemp()
        self.__run_config_dir = tempfile.mkdtemp()
        self.__daq_data_dir = tempfile.mkdtemp()
        self.__spade_dir = tempfile.mkdtemp()

        self.comps = []
        self.cnc = None

        MostlyCnCServer.APPENDERS.clear()

        set_pdaq_config_dir(self.__run_config_dir, override=True)

    def tearDown(self):
        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].check_status(10)

        if self.cnc is not None:
            try:
                self.cnc.close_server()
            except:
                pass

        for comp in self.comps:
            comp.close()
        del self.comps[:]

        if self.__copy_dir is not None:
            shutil.rmtree(self.__copy_dir, ignore_errors=True)
            self.__copy_dir = None
        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)
            self.__run_config_dir = None
        if self.__daq_data_dir is not None:
            shutil.rmtree(self.__daq_data_dir, ignore_errors=True)
            self.__daq_data_dir = None
        if self.__spade_dir is not None:
            shutil.rmtree(self.__spade_dir, ignore_errors=True)
            self.__spade_dir = None

        set_pdaq_config_dir(None, override=True)

    def __add_range(self, range_str, rstart, rcurrent):
        if not range_str.endswith(" "):
            range_str += ","
        if rstart == rcurrent:
            range_str += "%d" % rcurrent
        else:
            range_str += "%d-%d" % (rstart, rcurrent)
        return range_str

    def __list_components_legibly(self, comps):
        cycle_list = sorted(self.comps[:])

        comp_dict = {}
        for comp in cycle_list:
            if comp.name not in comp_dict:
                comp_dict[comp.name] = []
            comp_dict[comp.name].append(comp.num)

        str_list = []
        for name in comp_dict:
            num_list = comp_dict[name]

            if len(num_list) == 1:
                num = num_list[0]
                if num == 0:
                    str_list.append(name)
                else:
                    str_list.append("%s#%d" % (name, num))
                continue

            range_str = "name "
            rstart = None
            rcurrent = None
            for num in num_list:
                if rcurrent is None:
                    rstart = num
                    rcurrent = num
                elif rcurrent == num - 1:
                    rcurrent = num
                else:
                    range_str = self.__add_range(range_str, rstart, rcurrent)
                    rstart = num
                    rcurrent = num
                    str_list.append(self.__add_range(range_str, rstart,
                                                     rcurrent))

        return ", ".join(str_list)

    def __run_everything(self, force_restart=False, switch_run=False):
        catchall = MostlyRunSet.LOGFACTORY.create_log("master", 18999)
        dashlog = MockLogger('dashlog')

        comp_data = [('stringHub', self.HUB_NUMBER, (("hit", "o", 1), )),
                     ('inIceTrigger', 0, (("hit", "i", 2), ("trig", "o", 3), )),
                     ('eventBuilder', 0, (("trig", "i", 4), )), ]
        comp_host = 'localhost'

        clu_cfg = MockClusterConfig("clusterFoo")
        for cdata in comp_data:
            clu_cfg.add_component("%s#%d" % (cdata[0], cdata[1]), "java", "",
                                  comp_host)

        catchall.add_expected_text_regexp(r'\S+ \S+ \S+ \S+')

        self.cnc = MostlyCnCServer(cluster_config_object=clu_cfg,
                                   copy_dir=self.__copy_dir,
                                   run_config_dir=self.__run_config_dir,
                                   daq_data_dir=self.__daq_data_dir,
                                   spade_dir=self.__spade_dir,
                                   log_port=catchall.port,
                                   dashlog=dashlog,
                                   force_restart=force_restart)
        thrd = threading.Thread(name="CnCRun", target=self.cnc.run, args=())
        thrd.setDaemon(True)
        thrd.start()

        catchall.check_status(100)

        for cdata in comp_data:
            if cdata[1] == 0:
                fullname = cdata[0]
            else:
                fullname = "%s#%d" % (cdata[0], cdata[1])
            catchall.add_expected_text('Registered %s' % (fullname, ))

            comp = RealComponent(cdata[0], cdata[1], "localhost",
                                 catchall.port)
            comp.register(cdata[2])

            self.comps.append(comp)

        catchall.check_status(100)

        comp_dicts = self.cnc.rpc_component_list_dicts()
        self.assertEqual(len(self.comps), len(comp_dicts),
                         'Expected %s components, not %d' %
                         (len(self.comps), len(comp_dicts)))
        for cdict in comp_dicts:
            comp = None
            for tmp in self.comps:
                if cdict["compName"] == tmp.name and \
                  cdict["compNum"] == tmp.num:
                    comp = tmp
                    break

            self.assertTrue(comp is not None,
                            "Unknown component %s#%d" %
                            (cdict["compName"], cdict["compNum"]))
            self.assertEqual(comp_host, cdict["host"],
                             'Expected %s host %s, not %s' %
                             (comp.fullname, comp_host, cdict["host"]))
            self.assertEqual(comp.cmd_port, cdict["rpcPort"],
                             'Expected %s cmdPort %d, not %d' %
                             (comp.fullname, comp.cmd_port, cdict["rpcPort"]))
            self.assertEqual(comp.mbean_port, cdict["mbeanPort"],
                             'Expected %s mbeanPort %d, not %d' %
                             (comp.fullname, comp.mbean_port,
                              cdict["mbeanPort"]))

        run_cfg_file = MockRunConfigFile(self.__run_config_dir)

        comp_list = []
        for comp in self.comps:
            if not comp.is_hub:
                comp_list.append(comp.fullname)

        hub2dom = {
            self.HUB_NUMBER:
            [MockRunConfigFile.create_dom(self.DOM_MAINBOARD_ID, 2,
                                          "SrvrTst", "ABCDEF"), ],
        }

        run_cfg = run_cfg_file.create(comp_list, hub2dom)

        MockDefaultDomGeometryFile.create(self.__run_config_dir, hub2dom)

        leap_file = MockLeapsecondFile(self.__run_config_dir)
        leap_file.create()

        catchall.add_expected_text_regexp('Loading run configuration .*')
        catchall.add_expected_text_regexp('Loaded run configuration .*')

        for comp in self.comps:
            catchall.add_expected_exact("Config %s#%d with %s" %
                                        (comp.name, comp.num, run_cfg))

        catchall.add_expected_text_regexp(r"Built runset #\d+: .*")

        run_num = 444

        set_id = self.cnc.rpc_runset_make(run_cfg, run_num, strict=False)
        for comp in self.comps:
            self.assertEqual('ready', comp.state,
                             'Unexpected state %s for %s' %
                             (comp.state, comp.fullname))

        time.sleep(1)

        catchall.check_status(100)

        rscomps = self.cnc.rpc_runset_list(set_id)
        self.assertEqual(len(self.comps), len(rscomps),
                         "Expected one component, not %d" % len(self.comps))
        for rscomp in rscomps:
            badcomp = None
            for centry in self.comps:
                if centry.id != rscomp["id"]:
                    badcomp = centry
                    break

                comp = centry
                self.assertTrue(comp is not None,
                                "Unknown component %s#%d" %
                                (rscomp["compName"], rscomp["compNum"]))

                self.assertEqual(comp.name, rscomp["compName"],
                                 ("Component#%d name should be \"%s\","
                                  "not \"%s\"") %
                                 (comp.id, comp.name, rscomp["compName"]))
                self.assertEqual(comp.num, rscomp["compNum"],
                                 ("Component#%d \"%s\" number should be %d,"
                                  " not %d") %
                                 (comp.id, comp.fullname, comp.num,
                                  rscomp["compNum"]))
                self.assertEqual(comp_host, rscomp["host"],
                                 ("Component#%d \"%s\" host should be"
                                  " \"%s\", not \"%s\"") %
                                 (comp.id, comp.fullname, comp_host,
                                  rscomp["host"]))
                self.assertEqual(comp.cmd_port, rscomp["rpcPort"],
                                 ("Component#%d \"%s\" rpcPort should be"
                                  " \"%s\", not \"%s\"") %
                                 (comp.id, comp.fullname, comp.cmd_port,
                                  rscomp["rpcPort"]))
                self.assertEqual(comp.mbean_port, rscomp["mbeanPort"],
                                 "Component#%d \"%s\" mbeanPort should be"
                                 " \"%s\", not \"%s\"" %
                                 (comp.id, comp.fullname, comp.mbean_port,
                                  rscomp["mbeanPort"]))

        catchall.check_status(100)
        for comp in self.comps:
            comp.check_status(100)

        for comp in self.comps:
            for log in comp.loggers:
                log.add_expected_text_regexp(r"Start of log at"
                                             r" LOG=log(\S+:\d+)")
                log.add_expected_exact("Test msg")
                log.add_expected_text_regexp(r'\S+ \S+ \S+ \S+')

        catchall.add_expected_text("Starting run #%d on \"%s\"" %
                                   (run_num, clu_cfg.description))

        dashlog.add_expected_regexp(r"Version info: \S+ \S+ \S+ \S+")
        dashlog.add_expected_exact("Run configuration: %s" % (run_cfg, ))
        dashlog.add_expected_exact("Cluster: %s" % clu_cfg.description)

        moni_type = RunOption.MONI_TO_NONE

        for comp in self.comps:
            for log in comp.loggers:
                log.add_expected_exact("Start #%d on %s" %
                                       (run_num, comp.fullname))

        dashlog.add_expected_exact("Starting run %d..." % run_num)

        for comp in self.comps:
            if comp.name == "stringHub":
                comp.set_bean_field_value("stringhub",
                                          "LatestFirstChannelHitTime", 10)
                comp.set_bean_field_value("stringhub",
                                          "NumberOfNonZombies", 10)

        catchall.add_expected_text_regexp(r"Waited \d+\.\d+ seconds"
                                          r" for NonHubs")
        catchall.add_expected_text_regexp(r"Waited \d+\.\d+ seconds"
                                          r" for Hubs")

        self.assertEqual(self.cnc.rpc_runset_start_run(set_id, run_num,
                                                       moni_type), 'OK')

        catchall.check_status(100)
        dashlog.check_status(100)
        for comp in self.comps:
            comp.check_status(100)

        rate_tracker = RateTracker(run_num, 10000000000, 100, 0, 0, 0)

        if switch_run:
            for _ in range(5):
                rate_tracker.update_run_data(self.cnc, set_id, self.comps)

            for comp in self.comps:
                for log in comp.loggers:
                    log.add_expected_exact("Switch %s to run#%d" %
                                           (comp.fullname, run_num + 1))

            dashlog.add_expected_regexp(r"Version info: \S+ \S+ \S+ \S+")
            dashlog.add_expected_exact("Run configuration: %s" % (run_cfg, ))
            dashlog.add_expected_exact("Cluster: %s" % clu_cfg.description)

            new_num = run_num + 1

            dashlog.add_expected_exact("Switching to run %d..." % new_num)

            rate_tracker.update_run_data(self.cnc, set_id, self.comps)

            rate_tracker.add_final_log_msgs(dashlog)
            dashlog.add_expected_exact("Run switched SUCCESSFULLY.")

            dashlog.add_expected_exact("Not logging to file so cannot queue"
                                       " to SPADE")

            self.cnc.rpc_runset_switch_run(set_id, new_num)

            _ = rate_tracker.get_totals()

            run_num = new_num

            catchall.check_status(100)
            dashlog.check_status(100)
            for comp in self.comps:
                for log in comp.loggers:
                    log.check_status(100)

            rate_tracker.reset()

        for _ in range(5):
            rate_tracker.update_run_data(self.cnc, set_id, self.comps)

        rate_tracker.update_run_data(self.cnc, set_id, self.comps)

        for comp in self.comps:
            for log in comp.loggers:
                log.add_expected_exact("Stop %s" % comp.fullname)

        rate_tracker.add_final_log_msgs(dashlog)

        dashlog.add_expected_exact("Run terminated SUCCESSFULLY.")

        dashlog.add_expected_exact("Not logging to file so cannot queue to"
                                   " SPADE")
        for comp in self.comps:
            if comp.name == "stringHub":
                comp.set_bean_field_value("stringhub",
                                          "EarliestLastChannelHitTime", 10)

        if force_restart:
            cycle_str = self.__list_components_legibly(self.comps)
            catchall.add_expected_text("Cycling components %s" % cycle_str)

        self.assertEqual(self.cnc.rpc_runset_stop_run(set_id), 'OK')

        catchall.check_status(100)
        dashlog.check_status(100)
        for comp in self.comps:
            for log in comp.loggers:
                log.check_status(100)

        if force_restart:
            try:
                _ = self.cnc.rpc_runset_list(set_id)
                self.fail("Runset #%d should have been destroyed" % set_id)
            except CnCServerException:
                pass
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 0)
        else:
            self.assertEqual(len(self.cnc.rpc_runset_list(set_id)),
                             len(comp_data))
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 1)

            server_appender = MostlyCnCServer.APPENDERS['server']

            self.assertEqual(self.cnc.rpc_runset_break(set_id), 'OK')

            server_appender.check_status(100)

            self.assertEqual(self.cnc.rpc_component_count(), len(comp_data))
            self.assertEqual(self.cnc.rpc_runset_count(), 0)

            server_appender.check_status(100)

        catchall.check_status(100)
        for comp in self.comps:
            for log in comp.loggers:
                log.check_status(100)

        self.cnc.close_server()

    def test_everything(self):
        self.__run_everything()

    def test_everything_again(self):
        self.__run_everything()

    def test_force_restart(self):
        self.__run_everything(force_restart=True)

    def test_switch_run(self):
        self.__run_everything(switch_run=True)


if __name__ == '__main__':
    unittest.main()
