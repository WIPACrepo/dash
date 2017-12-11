#!/usr/bin/env python

import os
import socket
import sys
import threading
import time
import xmlrpclib

from DAQConst import DAQPort
from DAQRPC import RPCClient, RPCServer


class UnknownMethodHandler(object):
    def __init__(self, name, area):
        self.__name = name
        self.__area = area

    def _dispatch(self, method, params):
        errMsg = "%s %s: Unknown method %s params %s" % \
            (self.__name, self.__area, method, params)
        print "!!! " + errMsg
        raise Exception(errMsg)


class PortNumber(object):
    NEXT_PORT = 12000

    @classmethod
    def next_number(cls):
        p = cls.NEXT_PORT
        cls.NEXT_PORT += 1
        return p

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
        print "Engine[%s] removed %s" % (self.__name, chan)

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

    def stop(self):
        self.__running = False


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
            optStr = " (optional)"
        else:
            optStr = ""
        return "%s<<%d%s" % (self.name, self.__port, optStr)

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

        t = threading.Thread(name=self.name + "Thread",
                             target=self.accept_loop)
        t.setDaemon(True)
        t.start()


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
            #written += len(data)

    def __write_from_file(self):
        with open(self.__path, "rb") as fd:
            print "%s reading from %s" % (self, self.__path)
            while self.__running:
                try:
                    data = fd.read(256)
                    if data is None or len(data) == 0:
                        break

                    self.__sock.send(data)
                    #written += len(data)
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
        print "Ended %s thread (wrote %d bytes)" % (self.__engine, written)


class OutputEngine(Engine):
    def __init__(self, name, optional):
        self.__optional = optional

        super(OutputEngine, self).__init__(name)

    def __str__(self):
        if self.__optional:
            optStr = " (optional)"
        else:
            optStr = ""
        return "%s>>%s" % (self.name, optStr)

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


class FakeClientException(Exception):
    pass


class FakeClient(object):
    NEXT_PREFIX = 1

    def __init__(self, name, num, connList, mbeanDict, numeric_prefix=False,
                 quiet=False):
        if not numeric_prefix:
            self.__name = name
        else:
            self.__name = str(self.NEXT_PREFIX) + name
            self.NEXT_PREFIX += 1

        self.__num = num
        self.__connections = self.__build_engines(connList)
        self.__mbeanDict = mbeanDict.copy()

        self.__cmdPort = PortNumber.next_number()
        self.__mbeanPort = PortNumber.next_number()

        self.__runNum = 0
        self.__numEvts = 0

        self.__state = "idle"
        self.__registered = True

        self.__quiet = quiet

    def __str__(self):
        return "%s#%d" % (self.__name, self.__num)

    @classmethod
    def __build_engines(cls, connList):
        engines = []
        for c in connList:
            if c[1] == "i" or c[1] == "I":
                engines.append(InputEngine(c[0], c[1] == "I"))
            elif c[1] == "o" or c[1] == "O":
                engines.append(OutputEngine(c[0], c[1] == "O"))
            else:
                raise Exception("Unknown connection \"%s\" type \"%s\"" %
                                (c[0], c[1]))
        return engines

    def __commit_subrun(self, subrunNum, latestTime):
        if not self.__quiet:
            print "CommitSubrun %s num %d time %s" % (self, subrunNum,
                                                      latestTime)
        return "CommitSubrun"

    def __configure(self, cfgName=None):
        self.__state = "ready"
        return self.__state

    def __connect(self, connList=None):
        if connList is not None:
            for cd in connList:
                found = False
                for e in self.__connections:
                    if e.name == cd["type"]:
                        path = self.__get_output_data_path()
                        e.connect(cd["host"], cd["port"], path=path)
                        found = True
                if not found:
                    raise Exception("Cannot find \"%s\" output engine \"%s\"" %
                                    self.fullname, cd["type"])

        else:
            print >>sys.stderr, "No connections for %s" % (self, )

        self.__state = "connected"
        return self.__state

    def __get_mbean_attributes(self, bean, attrList):
        valDict = {}
        for attr in attrList:
            valDict[attr] = self.__get_mbean_value(bean, attr)
        return valDict

    def __get_mbean_value(self, bean, attr):
        if bean not in self.__mbeanDict:
            raise Exception("Unknown %s MBean \"%s\"" % (self, bean))

        if attr not in self.__mbeanDict[bean]:
            raise Exception("Unknown %s MBean \"%s\" attribute \"%s\"" %
                            (self, bean, attr))

        self.__mbeanDict[bean][attr].update()

        val = self.__mbeanDict[bean][attr].get()
        if val is None:
            return ''

        return val

    def __get_events(self, subrunNum):
        if not self.__quiet:
            print "GetEvents %s subrun %d" % (self, subrunNum)
        self.__numEvts += 1
        return self.__numEvts

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
            print >>sys.stderr, "%s cannot read data from %s" % (self, path)
            return None

        return path

    def __get_run_data(self, runNum):
        if not self.__quiet:
            print "GetRunData %s run %d" % (self, runNum)
        return (long(1), long(2), long(3), long(4), long(5))

    def __get_run_number(self):
        return self.__runNum

    def __get_state(self):
        return self.__state

    def __get_version_info(self):
        return '$Id: filename revision date time author xxx'

    def __list_connections(self):
        connList = []
        for conn in self.__connections:
            connList.append(conn.connection_tuple)
        return connList

    def __list_conn_states(self):
        stateList = []
        for conn in self.__connections:
            stateList.append({
                "type": conn.name,
                "numChan": conn.num_channels,
                "state": conn.state,
            })

        return stateList

    def __list_mbean_getters(self, bean):
        if bean not in self.__mbeanDict:
            raise Exception("Unknown MBean \"%s\" for %s" % (bean, self))

        return self.__mbeanDict[bean].keys()

    def __list_mbeans(self):
        return self.__mbeanDict.keys()

    def __log_to(self, logHost, logPort, liveHost, livePort):
        if not self.__quiet:
            print "LogTo %s LOG %s:%d LIVE %s:%d" % \
                (self, logHost, logPort, liveHost, livePort)
        return False

    def __prepare_subrun(self, subrunNum):
        if not self.__quiet:
            print "PrepareSubrun %s num %d" % (self, subrunNum)
        return "PrepareSubrun"

    def __reset(self):
        self.__state = "idle"
        if not self.__quiet:
            print "Reset %s" % self
        return self.__state

    def __reset_logging(self):
        if not self.__quiet:
            print "ResetLogging %s" % self
        return "ResetLogging"

    def __set_first_good_time(self, firstTime):
        if not self.__quiet:
            print "SetFirstGoodTime %s -> %s" % (self, firstTime)
        return "SetFirstGoodTime"

    def __start_run(self, runNum):
        if not self.__quiet:
            print "StartRun %s" % self
        self.start_run(runNum)
        self.__state = "running"
        return self.__state

    def __start_subrun(self, data):
        if not self.__quiet:
            print "StartSubrun %s data %s" % (self, data)
        return 123456789L

    def __stop_run(self):
        if not self.__quiet:
            print "StopRun %s" % self
        self.stop_run()
        self.__state = "ready"
        return False

    def __switch_to_new_run(self, newNum):
        if not self.__quiet:
            print "SwitchToNewRun %s newNum %s" % (self, newNum)
        self.switch_run(newNum)
        self.__runNum = newNum
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
                                          self.__cmdPort, self.__mbeanPort,
                                          self.__list_connections())
        self.__registered = True

    def start(self):
        self.__cmd = RPCServer(self.__cmdPort)
        self.__cmd.register_function(self.__commit_subrun,
                                     'xmlrpc.commitSubrun')
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__get_events, 'xmlrpc.getEvents')
        self.__cmd.register_function(self.__get_run_data, 'xmlrpc.getRunData')
        self.__cmd.register_function(self.__get_run_number,
                                     'xmlrpc.getRunNumber')
        self.__cmd.register_function(self.__get_state, 'xmlrpc.getState')
        self.__cmd.register_function(self.__get_version_info,
                                     'xmlrpc.getVersionInfo')
        self.__cmd.register_function(self.__list_conn_states,
                                     'xmlrpc.listConnectorStates')
        self.__cmd.register_function(self.__log_to, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__prepare_subrun,
                                     'xmlrpc.prepareSubrun')
        self.__cmd.register_function(self.__start_subrun, 'xmlrpc.startSubrun')
        self.__cmd.register_function(self.__switch_to_new_run,
                                     'xmlrpc.switchToNewRun')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__reset_logging,
                                     'xmlrpc.resetLogging')
        self.__cmd.register_function(self.__set_first_good_time,
                                     'xmlrpc.setFirstGoodTime')
        self.__cmd.register_function(self.__start_run, 'xmlrpc.startRun')
        self.__cmd.register_function(self.__stop_run, 'xmlrpc.stopRun')

        handler = UnknownMethodHandler(self.fullname, "Cmds")
        self.__cmd.register_instance(handler)

        tName = "RealXML*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__cmd.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__mbean = RPCServer(self.__mbeanPort)
        self.__mbean.register_function(self.__get_mbean_value, 'mbean.get')
        self.__mbean.register_function(self.__list_mbeans, 'mbean.listMBeans')
        self.__mbean.register_function(self.__get_mbean_attributes,
                                       'mbean.getAttributes')
        self.__mbean.register_function(self.__list_mbean_getters,
                                       'mbean.listGetters')

        handler = UnknownMethodHandler(self.fullname, "Beans")
        self.__mbean.register_instance(handler)

        tName = "RealMBean*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__mbean.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)

        for c in self.__connections:
            c.start()

    def start_run(self, run_num):
        print >>sys.stderr, "%s not starting run#%s" % (self, run_num)

    def stop_run(self):
        print >>sys.stderr, "%s not stopping run" % (self, )

    def switch_run(self, run_num):
        print >>sys.stderr, "%s not switching to run#%s" % (self, run_num)
