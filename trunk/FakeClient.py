#!/usr/bin/env python

from __future__ import print_function

import os
import socket
import sys
import threading
import time

from DAQConst import DAQPort
from DAQRPC import RPCClient, RPCServer


class UnknownMethodHandler(object):
    def __init__(self, name, area):
        self.__name = name
        self.__area = area

    def _dispatch(self, method, params):
        errmsg = "%s %s: Unknown method %s params %s" % \
            (self.__name, self.__area, method, params)
        print("!!! " + errmsg)
        raise Exception(errmsg)


class PortNumber(object):
    NEXT_PORT = 12000

    @classmethod
    def next_number(cls):
        port = cls.NEXT_PORT
        cls.NEXT_PORT += 1
        return port

    @classmethod
    def set_first(cls, number):
        cls.NEXT_PORT = number


class Engine(object):
    def __init__(self, name):
        self.__name = name

        self.__channels = []

    def add_channel(self, chan):
        self.__channels.append(chan)

    @property
    def channels(self):
        return self.__channels[:]

    @property
    def connection_tuple(self):
        return (self.name, self.description_char, self.port)

    @property
    def description_char(self):
        raise NotImplementedError("Unimplemented")

    @property
    def name(self):
        return self.__name

    @property
    def num_channels(self):
        return len(self.__channels)

    @property
    def port(self):
        return -1

    def remove_channel(self, chan):
        self.__channels.remove(chan)
        print("Engine[%s] removed %s" % (self.__name, chan))

    @property
    def state(self):
        return "unknown"


class InputOutputThread(threading.Thread):
    def __init__(self):
        self.__queue_flag = threading.Condition()
        self.__queue = []

        super(InputOutputThread, self).__init__(name=str(self))

    def pull(self):
        # try to get data from the queue
        self.__queue_flag.acquire()
        try:
            if len(self.__queue) == 0:
                return None

            # return the next block of data
            return self.__queue.pop(0)
        finally:
            self.__queue_flag.release()

    def push(self, data):
        self.__queue_flag.acquire()
        try:
            self.__queue.append(data)
        finally:
            self.__queue_flag.release()


class InputChannel(InputOutputThread):
    def __init__(self, conn, addr, engine):
        self.__conn = conn
        self.__fromhost = socket.getfqdn(addr[0])
        self.__engine = engine

        self.__running = False

        super(InputChannel, self).__init__()
        self.setDaemon(True)

    def __str__(self):
        return "%s<<%s" % (self.__engine.name, self.__fromhost)

    def close(self):
        self.__running = False

    def run(self):
        self.__running = True
        while self.__running:
            try:
                data = self.__conn.recv(1024)
            except socket.timeout:
                data = None
            if data is None:
                break
            self.push(data)
        self.__conn.close()
        self.__engine.remove_channel(self)
        self.__running = False

    def stop(self):
        self.__running = False


class InputEngine(Engine):
    def __init__(self, name, optional, port=None):
        self.__optional = optional
        if port is not None:
            self.__port = port
        else:
            self.__port = PortNumber.next_number()

        self.__sock = None

        super(InputEngine, self).__init__(name)

    def __str__(self):
        if self.__optional:
            optstr = " (optional)"
        else:
            optstr = ""
        return "%s<<%d%s" % (self.name, self.__port, optstr)

    def accept_loop(self):
        while True:
            try:
                conn, addr = self.__sock.accept()
            except socket.timeout:
                break
            chan = self.create_channel(conn, addr)
            self.add_channel(chan)
            chan.start()

    def create_channel(self, conn, addr):
        return InputChannel(conn, addr, self)

    @property
    def description_char(self):
        if self.__optional:
            return "I"
        return "i"

    @property
    def port(self):
        return self.__port

    def start(self):
        try:
            self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.__sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except socket.error:
            self.__sock = None
            raise

        try:
            self.__sock.bind(("", self.__port))
        except socket.error:
            self.__sock.close()
            self.__sock = None
            raise Exception("%s cannot bind to port %s" %
                            (self.name, self.__port, ))

        try:
            self.__sock.listen(1)
        except socket.error:
            self.__sock.close()
            self.__sock = None
            raise Exception("%s cannot listen on port %s" %
                            (self.name, self.__port, ))

        thrd = threading.Thread(name=self.name + "Thread",
                                target=self.accept_loop)
        thrd.setDaemon(True)
        thrd.start()


class OutputChannel(InputOutputThread):
    def __init__(self, host, port, engine, path=None):
        self.__host = host
        self.__port = port
        self.__engine = engine
        self.__path = path

        self.__running = False

        try:
            self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.__sock.connect((self.__host, self.__port))
        except socket.error as err:
            self.__sock = None
            raise Exception("Cannot connect to %s:%d: %s" %
                            (self.__host, self.__port, err))

        super(OutputChannel, self).__init__()
        self.setDaemon(True)

    def __str__(self):
        return ">>%s" % (self.__engine.name)

    def __write_from_queue(self):
        while self.__running:
            data = self.pull()
            if data is None:
                continue

            try:
                self.__sock.send(data)
            except:
                import traceback
                traceback.print_exc()
            # written += len(data)

    def __write_from_file(self):
        with open(self.__path, "rb") as fin:
            print("%s reading from %s" % (self, self.__path))
            while self.__running:
                try:
                    data = fin.read(256)
                    if data is None or len(data) == 0:
                        break

                    self.__sock.send(data)
                    # written += len(data)
                except:
                    import traceback
                    traceback.print_exc()

    def close(self):
        self.__engine.remove_channel(self)
        self.__sock.close()
        self.__sock = None

    def run(self):
        self.__running = True
        written = 0
        if self.__path is not None:
            self.__write_from_file()
        else:
            self.__write_from_queue()
        self.close()
        self.__running = False
        print("Ended %s thread (wrote %d bytes)" % (self.__engine, written))

    def stop(self):
        self.__running = False


class OutputEngine(Engine):
    def __init__(self, name, optional):
        self.__optional = optional

        super(OutputEngine, self).__init__(name)

    def __str__(self):
        if self.__optional:
            optstr = " (optional)"
        else:
            optstr = ""
        return "%s>>%s" % (self.name, optstr)

    def connect(self, host, port, path=None):
        try:
            chan = OutputChannel(host, port, self, path=path)
            self.add_channel(chan)
            chan.start()
        except:
            import traceback
            traceback.print_exc()

    @property
    def description_char(self):
        if self.__optional:
            return "O"
        return "o"

    def start(self):
        pass


class BeanValue(object):
    def __init__(self, name, value, delta):
        self.__name = name
        self.__value = value
        self.__delta = delta

    @classmethod
    def __update_recursive(cls, name, value, delta):
        if delta is None:
            return value, value

        if isinstance(delta, numbers.Number) and \
           isinstance(value, numbers.Number):
            return value, value + delta

        if (isinstance(delta, list) or isinstance(delta, tuple)) and \
           (isinstance(value, list) or isinstance(value, tuple)) and \
           len(delta) == len(value):
            rtnval = value[:]
            newlist = []
            for idx, val in enumerate(value):
                _, newval = cls.__update_recursive(name, val, delta[idx])
                newlist.append(newval)
            if isinstance(value, list):
                return rtnval, newlist
            else:
                return rtnval, tuple(newlist)

        print("Not updating %s: value %s<%s> != delta" \
            " %s<%s>" % (name, value, type(value).__name__, delta,
                         type(delta).__name__), file=sys.stderr)
        return value, delta

    def get(self):
        return self.__value

    def update(self):
        rtnval, newval = self.__update_recursive(self.__name, self.__value,
                                                 self.__delta)
        self.__value = newval
        return rtnval


class FakeMBeanData(object):
    RADAR_DOM = "123456789abc"
    __BEAN_DATA = {
        "stringHub": {
            "DataCollectorMonitor-00A": {
                "MainboardId": (RADAR_DOM, None),
                },
            "sender": {
                "NumHitsReceived": (0, 10),
                "NumReadoutRequestsReceived": (0, 2),
                "NumReadoutsSent": (0, 2),
                },
            "stringhub": {
                "NumberOfActiveChannels": (0, 0),
                "NumberOfActiveAndTotalChannels": ((0, 0), None),
                "NumberOfNonZombies": (60, 60),
                "LatestFirstChannelHitTime": (12345, 67890),
                "TotalLBMOverflows": (0, 0),
                },
            },
        "inIceTrigger": {
            "stringHit": {
                "RecordsReceived": (0, 10),
                },
            "trigger": {
                "RecordsSent": (0, 2),
                },
            },
        "globalTrigger": {
            "trigger": {
                "RecordsReceived": (0, 2),
                },
            "glblTrig": {
                "RecordsSent": (0, 2),
                },
            },
        "eventBuilder": {
            "backEnd": {
                "DiskAvailable": (2048, None),
                "EventData": ((0, 1), (None, 3, 10000000000)),
                "FirstEventTime": (0, None),
                "GoodTimes": ((0, 0), None),
                "NumBadEvents": (0, None),
                "NumEventsSent": (0, 1),
                "NumReadoutsReceived": (0, 2),
                "NumTriggerRequestsReceived": (0, 2),
                "NumEventsDispatched": (0, 5),
                },
            },
        "secondaryBuilders": {
            "moniBuilder": {
                "DiskAvailable": (2048, None),
                "NumDispatchedData": (0, 100),
                },
            "snBuilder": {
                "DiskAvailable": (2048, None),
                "NumDispatchedData": (0, 100),
                },
            "tcalBuilder": {
                "DiskAvailable": (2048, None),
                "NumDispatchedData": (0, 100),
                },
            }}

    @classmethod
    def create_dict(cls, name):
        bean_dict = {}
        if name not in cls.__BEAN_DATA:
            raise FakeClientException("No bean data for %s" % (name, ))
        else:
            for bean in cls.__BEAN_DATA[name]:
                bean_dict[bean] = {}
                for fld in cls.__BEAN_DATA[name][bean]:
                    bean_data = cls.__BEAN_DATA[name][bean][fld]
                    beanval = BeanValue("%s.%s.%s" % (name, bean, fld),
                                        bean_data[0], bean_data[1])
                    bean_dict[bean][fld] = beanval

        return bean_dict


class FakeClientException(Exception):
    pass


class FakeClient(object):
    NEXT_PREFIX = 1

    def __init__(self, name, num, conn_list, mbean_dict=None,
                 numeric_prefix=False, quiet=False):
        if not numeric_prefix:
            self.__name = name
        else:
            self.__name = str(self.NEXT_PREFIX) + name
            self.NEXT_PREFIX += 1

        self.__num = num
        self.__connections = self.__build_engines(conn_list)
        if mbean_dict is not None:
            self.__mbean_dict = mbean_dict
        else:
            self.__mbean_dict = FakeMBeanData.create_dict(self.__name)

        self.__cmd_port = PortNumber.next_number()
        self.__mbean_port = PortNumber.next_number()

        self.__run_num = 0
        self.__num_evts = 0

        self.__state = "idle"
        self.__registered = True

        self.__quiet = quiet

        self.__src_id = None
        self.__cnc = None
        self.__mbean = None

    def __str__(self):
        return "%s#%d" % (self.__name, self.__num)

    @classmethod
    def __build_engines(cls, conn_list):
        engines = []
        for conn in conn_list:
            if conn[1] == "i" or conn[1] == "I":
                engines.append(InputEngine(conn[0], conn[1] == "I"))
            elif conn[1] == "o" or conn[1] == "O":
                engines.append(OutputEngine(conn[0], conn[1] == "O"))
            else:
                raise Exception("Unknown connection \"%s\" type \"%s\"" %
                                (conn[0], conn[1]))
        return engines

    def __commit_subrun(self, subrun_num, latest_time):
        if not self.__quiet:
            print("CommitSubrun %s num %d time %s" % (self, subrun_num,
                                                      latest_time))
        return "CommitSubrun"

    def __configure(self, cfg_name=None):
        self.__state = "ready"
        return self.__state

    def __connect(self, conn_list=None):
        if conn_list is not None:
            for desc in conn_list:
                found = False
                for conn in self.__connections:
                    if conn.name == desc["type"]:
                        path = self.__get_output_data_path()
                        conn.connect(desc["host"], desc["port"], path=path)
                        found = True
                if not found:
                    raise Exception("Cannot find \"%s\" output engine \"%s\"" %
                                    self.fullname, desc["type"])

        else:
            print("No connections for %s" % (self, ), file=sys.stderr)

        self.__state = "connected"
        return self.__state

    def __get_mbean_attributes(self, bean, attr_list):
        val_dict = {}
        for attr in attr_list:
            val_dict[attr] = self.__get_mbean_value(bean, attr)
        return val_dict

    def __get_mbean_value(self, bean, attr):
        if bean not in self.__mbean_dict:
            raise Exception("Unknown %s MBean \"%s\"" % (self, bean))

        if attr not in self.__mbean_dict[bean]:
            raise Exception("Unknown %s MBean \"%s\" attribute \"%s\"" %
                            (self, bean, attr))

        self.__mbean_dict[bean][attr].update()

        val = self.__mbean_dict[bean][attr].get()
        if val is None:
            return ''

        return val

    def __get_events(self, subrun_num):
        if not self.__quiet:
            print("GetEvents %s subrun %d" % (self, subrun_num))
        self.__num_evts += 1
        return self.__num_evts

    def __get_output_data_path(self):
        if self.__name == "inIceTrigger":
            cname = "iit"
        elif self.__name == "iceTopTrigger":
            cname = "itt"
        elif self.__name == "globalTrigger":
            cname = "glbl"
        else:
            return None

        rchash = "rc217a0bdc2d0253e61c99794f4a3dae80"
        run = 120151
        hubs = 40
        hits = 1000

        fullname = "%s-%s-r%d-h%d-p%d.dat" % \
                   (rchash, cname, run, hubs, hits)

        path = os.path.join(os.environ["HOME"], "prj", "simplehits", fullname)

        if not os.path.exists(path):
            print("%s cannot read data from %s" % (self, path), file=sys.stderr)
            return None

        return path

    def __get_run_data(self, run_num):
        if not self.__quiet:
            print("GetRunData %s run %d" % (self, run_num))
        return (long(1), long(2), long(3), long(4), long(5))

    def __get_run_number(self):
        return self.__run_num

    def __get_source_id(self):
        if self.__name == "inIceTrigger":
            return 4000 + self.__num
        elif self.__name == "iceTopTrigger":
            return 5000 + self.__num
        elif self.__name == "globalTrigger":
            return 6000 + self.__num
        elif self.__name == "eventBuilder":
            return 7000 + self.__num
        elif self.__name == "tcalBuilder":
            return 8000 + self.__num
        elif self.__name == "moniBuilder":
            return 9000 + self.__num
        elif self.__name == "snBuilder":
            return 11000 + self.__num
        elif self.__name == "stringHub" or self.__name == "icetopHub":
            return 12000 + self.__num
        elif self.__name == "secondaryBuilders":
            return 14000 + self.__num

    def __get_state(self):
        return self.__state

    def __get_version_info(self):
        return '$Id: filename revision date time author xxx'

    def __list_connections(self):
        conn_list = []
        for conn in self.__connections:
            conn_list.append(conn.connection_tuple)
        return conn_list

    def __list_conn_states(self):
        state_list = []
        for conn in self.__connections:
            state_list.append({
                "type": conn.name,
                "numChan": conn.num_channels,
                "state": conn.state,
            })

        return state_list

    def __list_mbean_getters(self, bean):
        if bean not in self.__mbean_dict:
            raise Exception("Unknown MBean \"%s\" for %s" % (bean, self))

        return list(self.__mbean_dict[bean].keys())

    def __list_mbeans(self):
        return list(self.__mbean_dict.keys())

    def __log_to(self, log_host, log_port, live_host, live_port):
        if not self.__quiet:
            print("LogTo %s LOG %s:%d LIVE %s:%d" % \
                (self, log_host, log_port, live_host, live_port))
        return False

    def __prepare_subrun(self, subrun_num):
        if not self.__quiet:
            print("PrepareSubrun %s num %d" % (self, subrun_num))
        return "PrepareSubrun"

    def __reset(self):
        self.__state = "idle"
        if not self.__quiet:
            print("Reset %s" % self)
        return self.__state

    def __reset_logging(self):
        if not self.__quiet:
            print("ResetLogging %s" % self)
        return "ResetLogging"

    def __set_first_good_time(self, first_time):
        if not self.__quiet:
            print("SetFirstGoodTime %s -> %s" % (self, first_time))
        return "SetFirstGoodTime"

    def __start_run(self, run_num):
        if not self.__quiet:
            print("StartRun %s" % self)
        self.start_run(run_num)
        self.__state = "running"
        return self.__state

    def __start_subrun(self, data):
        if not self.__quiet:
            print("StartSubrun %s data %s" % (self, data))
        return 123456789L

    def __stop_run(self):
        if not self.__quiet:
            print("StopRun %s" % self)
        self.stop_run()
        self.__state = "ready"
        return False

    def __switch_to_new_run(self, new_num):
        if not self.__quiet:
            print("SwitchToNewRun %s new num %s" % (self, new_num))
        self.switch_run(new_num)
        self.__run_num = new_num
        return "SwitchToNewRun"

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def get_output_connector(self, name):
        for conn in self.__connections:
            if conn.name == name:
                return conn
        return None

    def monitor_server(self):
        while self.__registered:
            if self.__cnc is None:
                break

            try:
                self.__cnc.rpc_ping()
            except socket.error as err:
                if err[0] == 61 or err[0] == 111:
                    self.__cnc = None
                else:
                    raise

            time.sleep(1)

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    def register(self):
        self.__cnc.rpc_component_register(self.__name, self.__num, 'localhost',
                                          self.__cmd_port, self.__mbean_port,
                                          self.__list_connections())
        self.__registered = True

    @property
    def source_id(self):
        if self.__src_id is None:
            self.__src_id = self.__get_source_id()
        return self.__src_id

    def start(self):
        rpc_srvr = RPCServer(self.__cmd_port)
        rpc_srvr.register_function(self.__commit_subrun, 'xmlrpc.commitSubrun')
        rpc_srvr.register_function(self.__configure, 'xmlrpc.configure')
        rpc_srvr.register_function(self.__connect, 'xmlrpc.connect')
        rpc_srvr.register_function(self.__get_events, 'xmlrpc.getEvents')
        rpc_srvr.register_function(self.__get_run_data, 'xmlrpc.getRunData')
        rpc_srvr.register_function(self.__get_run_number,
                                   'xmlrpc.getRunNumber')
        rpc_srvr.register_function(self.__get_state, 'xmlrpc.getState')
        rpc_srvr.register_function(self.__get_version_info,
                                   'xmlrpc.getVersionInfo')
        rpc_srvr.register_function(self.__list_conn_states,
                                   'xmlrpc.listConnectorStates')
        rpc_srvr.register_function(self.__log_to, 'xmlrpc.logTo')
        rpc_srvr.register_function(self.__prepare_subrun,
                                   'xmlrpc.prepareSubrun')
        rpc_srvr.register_function(self.__start_subrun, 'xmlrpc.startSubrun')
        rpc_srvr.register_function(self.__switch_to_new_run,
                                   'xmlrpc.switchToNewRun')
        rpc_srvr.register_function(self.__reset, 'xmlrpc.reset')
        rpc_srvr.register_function(self.__reset_logging, 'xmlrpc.resetLogging')
        rpc_srvr.register_function(self.__set_first_good_time,
                                   'xmlrpc.setFirstGoodTime')
        rpc_srvr.register_function(self.__start_run, 'xmlrpc.startRun')
        rpc_srvr.register_function(self.__stop_run, 'xmlrpc.stopRun')

        handler = UnknownMethodHandler(self.fullname, "Cmds")
        rpc_srvr.register_instance(handler)

        tname = "RealXML*%s#%d" % (self.__name, self.__num)
        thrd = threading.Thread(name=tname, target=rpc_srvr.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        self.__mbean = RPCServer(self.__mbean_port)
        self.__mbean.register_function(self.__get_mbean_value, 'mbean.get')
        self.__mbean.register_function(self.__list_mbeans, 'mbean.listMBeans')
        self.__mbean.register_function(self.__get_mbean_attributes,
                                       'mbean.getAttributes')
        self.__mbean.register_function(self.__list_mbean_getters,
                                       'mbean.listGetters')

        handler = UnknownMethodHandler(self.fullname, "Beans")
        self.__mbean.register_instance(handler)

        tname = "RealMBean*%s#%d" % (self.__name, self.__num)
        thrd = threading.Thread(name=tname, target=self.__mbean.serve_forever,
                                args=())
        thrd.setDaemon(True)
        thrd.start()

        self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)

        for conn in self.__connections:
            conn.start()

    def start_run(self, run_num):
        print("%s not starting run#%s" % (self, run_num), file=sys.stderr)

    def stop_run(self):
        print("%s not stopping run" % (self, ), file=sys.stderr)

    def switch_run(self, run_num):
        print("%s not switching to run#%s" % (self, run_num), file=sys.stderr)
