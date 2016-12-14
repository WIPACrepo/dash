#!/usr/bin/env python

import os
import socket
import sys
import threading
import time
import xmlrpclib

from DAQConst import DAQPort
from DAQRPC import RPCServer


class UnknownMethodHandler(object):
    def __init__(self, name, area):
        self.__name = name
        self.__area = area

    def _dispatch(self, method, params):
        errMsg = "%s %s: Unknown method %s params %s" % \
            (self.__name, self.__area, method, params)
        print "!!! " + errMsg
        raise Exception(errMsg)


class Engine(object):
    def __init__(self, name):
        self.__name = name

        self.__channels = []

    def addChannel(self, chan):
        self.__channels.append(chan)

    def channels(self):
        return len(self.__channels)

    def connectionTuple(self):
        return (self.name, self.descriptionChar(), self.port)

    def descriptionChar(self):
        raise NotImplementedError("Unimplemented")

    @property
    def name(self):
        return self.__name

    @property
    def port(self):
        return -1

    def removeChannel(self, chan):
        self.__channels.remove(chan)
        print "Removed %s" % chan

    @property
    def state(self):
        return "unknown"


class InputChannel(threading.Thread):
    def __init__(self, conn, addr, engine):
        self.__conn = conn
        self.__fromhost = socket.getfqdn(addr[0])
        self.__engine = engine

        self.__running = False

        super(InputChannel, self).__init__(name=str(self))
        self.setDaemon(True)

    def __str__(self):
        return "%s<<%s" % (self.__engine.name, self.__fromhost)

    def close(self):
        self.__running = False

    def processData(self, data):
        pass

    def run(self):
        self.__running = True
        while self.__running:
            data = self.__conn.recv(1024)
            if not data:
                break
            self.processData(data)
        self.__conn.close()
        self.__engine.removeChannel(self)
        self.__running = False


class InputEngine(Engine):
    def __init__(self, name, optional, port=None):
        self.__optional = optional
        if port is not None:
            self.__port = port
        else:
            self.__port = FakeClient.nextPortNumber()

        self.__sock = None

        super(InputEngine, self).__init__(name)

    def __str__(self):
        if self.__optional:
            optStr = " (optional)"
        else:
            optStr = ""
        return "%s<<%d%s" % (self.name, self.__port, optStr)

    def acceptLoop(self):
        while True:
            conn, addr = self.__sock.accept()
            chan = self.createChannel(conn, addr)
            self.addChannel(chan)
            chan.start()

    def createChannel(self, conn, addr):
        return InputChannel(conn, addr, self)

    def descriptionChar(self):
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
            self.__sock.listen(1)
        except socket.error:
            self.__sock.close()
            self.__sock = None
            raise

        t = threading.Thread(name=self.name + "Thread",
                             target=self.acceptLoop)
        t.setDaemon(True)
        t.start()


class OutputChannel(threading.Thread):
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

        super(OutputChannel, self).__init__(name=str(self))
        self.setDaemon(True)

    def __str__(self):
        return ">>%s" % (self.__engine.name)

    def close(self):
        self.__engine.removeChannel(self)
        self.__sock.close()
        self.__sock = None

    def run(self):
        self.__running = True
        written = 0
        if self.__path is not None:
            with open(self.__path, "rb") as fd:
                print "Writing %s for %s" % (self.__path, self)
                while self.__running:
                    try:
                        data = fd.read(256)
                        if data is None or len(data) == 0:
                            break

                        self.__sock.send(data)
                        written += len(data)
                    except:
                        import traceback
                        traceback.print_exc()
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
            self.addChannel(chan)
            chan.start()
        except:
            import traceback
            traceback.print_exc()

    def descriptionChar(self):
        if self.__optional:
            return "O"
        return "o"

    def start(self):
        pass


class FakeClientException(Exception):
    pass


class FakeClient(object):
    NEXT_PORT = 12000
    NEXT_PREFIX = 1

    def __init__(self, name, num, connList, mbeanDict, create=True,
                 createXmlRpcServer=False, addNumericPrefix=False,
                 quiet=False):
        if not addNumericPrefix:
            self.__name = name
        else:
            self.__name = str(self.NEXT_PREFIX) + name
            self.NEXT_PREFIX += 1

        self.__num = num
        self.__connections = self.__buildEngines(connList)
        self.__mbeanDict = mbeanDict.copy()

        self.__cmdPort = self.nextPortNumber()
        self.__mbeanPort = self.nextPortNumber()

        self.__runNum = 0
        self.__numEvts = 0

        self.__state = "idle"
        self.__registered = True

        self.__quiet = quiet

    def __str__(self):
        return "%s#%d" % (self.__name, self.__num)

    @classmethod
    def __buildEngines(cls, connList):
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

    def __commitSubrun(self, subrunNum, latestTime):
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
                        path = self.__getOutputDataPath()
                        e.connect(cd["host"], cd["port"], path=path)
                        found = True
                if not found:
                    raise Exception("Cannot find \"%s\" output engine \"%s\"" %
                                    self.fullname, cd["type"])

        self.__state = "connected"
        return self.__state

    def __getMBeanAttributes(self, bean, attrList):
        valDict = {}
        for attr in attrList:
            valDict[attr] = self.__getMBeanValue(bean, attr)
        return valDict

    def __getMBeanValue(self, bean, attr):
        if not bean in self.__mbeanDict:
            raise Exception("Unknown %s MBean \"%s\"" % (self, bean))

        if not attr in self.__mbeanDict[bean]:
            raise Exception("Unknown %s MBean \"%s\" attribute \"%s\"" %
                            (self, bean, attr))

        self.__mbeanDict[bean][attr].update()

        val = self.__mbeanDict[bean][attr].get()
        if val is None:
            return ''

        return val

    def __getEvents(self, subrunNum):
        if not self.__quiet:
            print "GetEvents %s subrun %d" % (self, subrunNum)
        self.__numEvts += 1
        return self.__numEvts

    def __getOutputDataPath(self):
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
            print >>sys.stderr, "Cannot write %s for %s" % (path, self)
            return None

        return path

    def __getRunData(self, runNum):
        if not self.__quiet:
            print "GetRunData %s run %d" % (self, runNum)
        return (long(1), long(2), long(3), long(4), long(5))

    def __getRunNumber(self):
        return self.__runNum

    def __getState(self):
        return self.__state

    def __getVersionInfo(self):
        return '$Id: filename revision date time author xxx'

    def __listConnections(self):
        connList = []
        for conn in self.__connections:
            connList.append(conn.connectionTuple())
        return connList

    def __listConnStates(self):
        stateList = []
        for conn in self.__connections:
            stateList.append({"type": conn.name, "numChan": conn.channels(),
                              "state": conn.state})

        return stateList

    def __listMBeanGetters(self, bean):
        if not bean in self.__mbeanDict:
            raise Exception("Unknown MBean \"%s\" for %s" % (bean, self))

        return self.__mbeanDict[bean].keys()

    def __listMBeans(self):
        return self.__mbeanDict.keys()

    def __logTo(self, logHost, logPort, liveHost, livePort):
        if not self.__quiet:
            print "LogTo %s LOG %s:%d LIVE %s:%d" % \
                (self, logHost, logPort, liveHost, livePort)
        return False

    def __prepareSubrun(self, subrunNum):
        if not self.__quiet:
            print "PrepareSubrun %s num %d" % (self, subrunNum)
        return "PrepareSubrun"

    def __reset(self):
        self.__state = "idle"
        if not self.__quiet:
            print "Reset %s" % self
        return self.__state

    def __resetLogging(self):
        if not self.__quiet:
            print "ResetLogging %s" % self
        return "ResetLogging"

    def __setFirstGoodTime(self, firstTime):
        if not self.__quiet:
            print "SetFirstGoodTime %s -> %s" % (self, firstTime)
        return "SetFirstGoodTime"

    def __startRun(self, runNum):
        self.__state = "running"
        return self.__state

    def __startSubrun(self, data):
        if not self.__quiet:
            print "StartSubrun %s data %s" % (self, data)
        return 123456789L

    def __stopRun(self):
        if not self.__quiet:
            print "StopRun %s" % self
        self.__state = "ready"
        return False

    def __switchToNewRun(self, newNum):
        if not self.__quiet:
            print "SwitchToNewRun %s newNum %s" % (self, newNum)
        self.__runNum = newNum
        return "SwitchToNewRun"

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def getOutputConnector(self, name):
        for conn in self.__connections:
            if conn.name == name:
                return conn
        return None

    def monitorServer(self):
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

    @classmethod
    def nextPortNumber(cls):
        p = cls.NEXT_PORT
        cls.NEXT_PORT += 1
        return p

    def register(self):
        self.__cnc.rpc_component_register(self.__name, self.__num, 'localhost',
                                          self.__cmdPort, self.__mbeanPort,
                                          self.__listConnections())
        self.__registered = True

    def start(self):
        self.__cmd = RPCServer(self.__cmdPort)
        self.__cmd.register_function(self.__commitSubrun,
                                     'xmlrpc.commitSubrun')
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__getEvents, 'xmlrpc.getEvents')
        self.__cmd.register_function(self.__getRunData, 'xmlrpc.getRunData')
        self.__cmd.register_function(self.__getRunNumber, 'xmlrpc.getRunNumber')
        self.__cmd.register_function(self.__getState, 'xmlrpc.getState')
        self.__cmd.register_function(self.__getVersionInfo,
                                     'xmlrpc.getVersionInfo')
        self.__cmd.register_function(self.__listConnStates,
                                     'xmlrpc.listConnectorStates')
        self.__cmd.register_function(self.__logTo, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__prepareSubrun,
                                     'xmlrpc.prepareSubrun')
        self.__cmd.register_function(self.__startSubrun, 'xmlrpc.startSubrun')
        self.__cmd.register_function(self.__switchToNewRun,
                                     'xmlrpc.switchToNewRun')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__resetLogging,
                                     'xmlrpc.resetLogging')
        self.__cmd.register_function(self.__setFirstGoodTime,
                                     'xmlrpc.setFirstGoodTime')
        self.__cmd.register_function(self.__startRun, 'xmlrpc.startRun')
        self.__cmd.register_function(self.__stopRun, 'xmlrpc.stopRun')

        handler = UnknownMethodHandler(self.fullname, "Cmds")
        self.__cmd.register_instance(handler)

        tName = "RealXML*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__cmd.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__mbean = RPCServer(self.__mbeanPort)
        self.__mbean.register_function(self.__getMBeanValue, 'mbean.get')
        self.__mbean.register_function(self.__listMBeans, 'mbean.listMBeans')
        self.__mbean.register_function(self.__getMBeanAttributes,
                                       'mbean.getAttributes')
        self.__mbean.register_function(self.__listMBeanGetters,
                                       'mbean.listGetters')

        handler = UnknownMethodHandler(self.fullname, "Beans")
        self.__mbean.register_instance(handler)

        tName = "RealMBean*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__mbean.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER, verbose=False)

        for c in self.__connections:
            c.start()
