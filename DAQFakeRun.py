#!/usr/bin/env python

import datetime, optparse, os, select, socket, sys, threading, time, traceback
from xmlrpclib import ServerProxy
from CnCServer import Connector
from DAQConfig import DAQConfigParser
from DAQConst import DAQPort
from DAQMocks import MockRunConfigFile
from RunOption import RunOption
from SimpleXMLRPCServer import SimpleXMLRPCServer

def getHostAddress(name):
    "Only return IPv4 addresses -- IPv6 confuses some stuff"
    if name is None or name == '':
        name = 'localhost'
    if name == 'localhost' or name == '127.0.0.1':
        hostName = socket.gethostname()
        for addrData in socket.getaddrinfo(hostName, None):
            if addrData[0] == socket.AF_INET:
                name = addrData[4][0]
                break
    return name

class FakeClientException(Exception): pass

LOUD = False

class ChannelThread(threading.Thread):
    "Faux input channel"

    TIMEOUT = 100

    def __init__(self, comp, type):
        """
        Create an input reader thread

        comp - component name
        type - connector type name
        """

        self.__running = False
        self.__clientSock = []
        self.__readList = []
        self.__errList = []

        super(ChannelThread, self).__init__(name="%s:%s:reader" % (comp, type))
        self.setDaemon(True)

    def add(self, sock):
        """
        Add an input socket to the list of channels
        
        sock - input socket
        """

        self.__clientSock.append(sock)
        self.__readList.append(sock)
        self.__errList.append(sock)

        if not self.__running:
            self.start()

    def close(self):
        "Close all input channels"
        self.__running = False

        # clear out select lists
        #
        del self.__readList[:]
        del self.__errList[:]

        # close sockets
        #
        for cs in self.__clientSock:
            try:
                cs.close()
            except:
                traceback.print_exc()
        del self.__clientSock[:]

    def numChan(self):
        return len(self.__clientSock)

    def run(self):
        "Read data from input channels (and throw it away)"
        writeList = []
        self.__running = True
        while self.__running:
            try:
                rd, rw, re = select.select(self.__readList, writeList,
                                           self.__errList, self.TIMEOUT)
            except select.error, selerr:
                if selerr[0] == socket.EBADF:
                    break
                raise
            except socket.error, sockerr:
                if sockerr.errno == socket.EBADF:
                    break
                raise

            if len(re) != 0:
                print >>sys.stderr, "Error on select"

            if len(rd) == 0:
                continue

            while True:
                try:
                    data = sock.recv(8192, socket.MSG_DONTWAIT)
                    # ignore incoming data
                    #print "%s: %s" % (self.__compName, data)
                except:
                    break # Go back to select so we don't busy-wait

        self.close()

class InputThread(threading.Thread):
    "Faux input engine"

    TIMEOUT = 100

    def __init__(self, comp, type, port):
        """
        Create an input socket server
        comp - component name
        type - connection type name
        port - socket port number
        """
        self.__sock = None
        self.__channelThread = ChannelThread(comp, type)
        self.__running = False

        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.__sock.setblocking(0)
        self.__sock.settimeout(self.TIMEOUT)
        self.__sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if LOUD:
            print >>sys.stderr, "Create %s:%s socket at port %d" % \
                (comp, type, port)
        try:
            self.__sock.bind(("", port))
        except socket.error:
            raise FakeClientException("Cannot create %s:%s socket at port %d" %
                                      (comp, type, port))
        self.__sock.listen(5)

        super(InputThread, self).__init__(name="%s:%s" % (comp, type))
        self.setDaemon(True)

    def close(self):
        "close server socket and all client sockets"

        self.__running = False

        if self.__sock is not None:
            try:
                self.__sock.close()
            except:
                traceback.print_exc()
            self.__sock = None

        if self.__channelThread is not None:
            self.__channelThread.close()
        self.__channelThread = None

    def numChan(self):
        return self.__channelThread.numChan()

    def run(self):
        "Handle input"
        self.__running = True
        while self.__running:
            try:
                (client, addr) = self.__sock.accept()
            except socket.timeout:
                continue

            if LOUD:
                print >>sys.stderr, "Got client from %s" % str(addr)
            self.__channelThread.add(client)

class ReusableXMLRPCServer(SimpleXMLRPCServer):
    "Simple XML-RPC server with a reusable socket"

    def __init__(self, port, timeout=None):
        if timeout is not None:
            self.timeout = timeout
        self.allow_reuse_address = True
        SimpleXMLRPCServer.__init__(self, ('', port), logRequests=False)

class FakeConnector(Connector):
    "Fake DAQ Connector"

    def __init__(self, name, descrChar, port):
        """
        Connector constructor
        name - connection name
        descrChar - connection description character (I, i, O, o)
        port - IP port number (for input connections)
        """
        super(FakeConnector, self).__init__(name, descrChar, port)

        self.__state = "idle"

        self.__inputThread = None
        self.__outChanList = []

    def __str__(self):
        "String description"
        return "%s(%s)" % (super(FakeConnector, self).__str__(), self.__state)

    def addOutputChannel(self, sock):
        "Set the output socket"
        self.__outChanList.append(sock)

    def close(self):
        "Clean up input/output data"
        if self.__inputThread is not None:
            self.__inputThread.close()
            self.__inputThread = None

        for chan in self.__outChanList:
            chan.close()
        del self.__outChanList[:]

    def numChan(self):
        num = 0
        if self.__inputThread is not None:
            num += self.__inputThread.numChan()
        num += len(self.__outChanList)
        return num

    def send(self, outMsg):
        "Send data to the output socket"
        if len(self.__outChanList) == 0:
            raise FakeClientException("No output socket for %s" %
                                      self.__name)

        for chan in self.__outChanList:
            chan.send(outMsg)

    def setInputThread(self, thrd):
        "Set the input thread"
        self.__inputThread = thrd

    def setState(self, state):
        "Set the connector state"
        self.__state = state

    def state(self):
        "Return the current connector state"
        return self.__state

class MBeanThread(threading.Thread):
    def __init__(self, name, num, port, client):
        self.__port = port
        self.__server = None
        self.__running = False
        self.__client = client

        super(MBeanThread, self).__init__(name="%s#%d" % (name, num))
        self.setDaemon(True)

    def __get(self, bean, fld):
        return self.__client.get(bean, fld)

    def __getAttributes(self, bean, fldList):
        return self.__client.getAttributes(bean, fldList)

    def __listGetters(self, bean):
        return self.__client.listGetters(bean)

    def __listMBeans(self):
        return self.__client.listMBeans()

    def close(self):
        self.__running = False
        return self.__server.server_close()

    def run(self):
        self.__running = True

        try:
            self.__server = ReusableXMLRPCServer(self.__port, 1)
        except socket.error:
            raise FakeClientException("Port %d is already being used" %
                                      self.__port)

        self.__server.register_function(self.__get, 'mbean.get')
        self.__server.register_function(self.__getAttributes,
                                        'mbean.getAttributes')
        self.__server.register_function(self.__listGetters, 'mbean.listGetters')
        self.__server.register_function(self.__listMBeans, 'mbean.listMBeans')

        if LOUD:
            print >>sys.stderr, "MBean srvr %d" % self.__port
        while self.__running:
            try:
                self.__server.handle_request()
            except:
                break
        try:
            self.close()
        except:
            pass

class FakeClient(ServerProxy, threading.Thread):
    "Faux DAQ client"

    LOCAL_ADDR = getHostAddress("localhost")
    CNCSERVER_HOST = LOCAL_ADDR
    CNCSERVER_PORT = DAQPort.CNCSERVER

    NEXT_COMP_INSTANCE = 1

    NEXT_PORT = 1717

    def __init__(self, name, num, connectors, mbeanDict,
                 createXmlRpcServer=True, addNumericPrefix=True,
                 cncHost=CNCSERVER_HOST, cncPort=CNCSERVER_PORT,
                 verbose=False):
        """
        Create a faux DAQ client

        name - component name
        num - component number
        connectors - list of connectors [(name, isInput), ]
        mbeanDict - dictionary of 'MBean' dictionaries
        createXmlRpcServer - False if the real Java client should be used
        cncHost - CnCServer host name (defaults to "localhost")
        cncPort - CnCServer port number (defaults to 8080)
        verbose - if XML-RPC server should print connection info
        """

        self.__createXmlRpcServer = createXmlRpcServer
        if not self.__createXmlRpcServer:
            self.__name = name
            self.__num = num
            self.__rpcPort = None
            self.__mbeanPort = None
            self.__connectors = None
            self.__mbeanDict = None
        else:
            if addNumericPrefix:
                self.__name = "%d%s" % (FakeClient.NEXT_COMP_INSTANCE, name)
            else:
                self.__name = name
            FakeClient.NEXT_COMP_INSTANCE += 1
            self.__num = num
            self.__rpcPort = FakeClient.nextPortNumber()
            self.__mbeanPort = FakeClient.nextPortNumber()
            self.__connectors = self.__buildConnectors(connectors)
            self.__mbeanDict = mbeanDict

        self.__state = "idle"

        self.__clientId = None
        self.__serverId = None
        self.__log = None
        self.__liveLog = None
        self.__dfltLog = None
        self.__dfltLiveLog = None

        self.__rpcRunning = False
        self.__mbeanServer = None

        self.__proxy = None
        self.__wrapper = None

        ServerProxy.__init__(self, "http://%s:%s" % (cncHost, cncPort),
                             verbose=verbose)
        threading.Thread.__init__(self, name=str(self))
        self.setDaemon(True)

    def __str__(self):
        return "FakeClient:%s#%d" % (self.__name, self.__num)

    def __buildConnectors(connectors):
        """
        Build the connectors for this component

        connectors - initial connector list passed to FakeClient.__init__()

        Returns a list of Connector objects
        """
        connList = []
        for conn in connectors:
            if conn[1]:
                connPort = FakeClient.nextPortNumber()
            else:
                connPort = 0
            connList.append(FakeConnector(conn[0], conn[1], connPort))
        return connList
    __buildConnectors = staticmethod(__buildConnectors)

    def __createConnectorSockets(self):
        "Create input threads for all input connectors"
        compName = self.name()
        for conn in self.__connectors:
            if not conn.isInput():
                continue

            thrd = InputThread(compName, conn.name(), conn.port())
            thrd.start()

            conn.setInputThread(thrd)

    def __getConnectorList(self):
        """
        Return a list of connectors in the initial connector form passed
        to FakeClient.__init__()
        """
        connList = []
        for c in self.__connectors:
            connList.append(c.connectorTuple())
        return connList

    def __openLogClient(self, host, port):
        """
        Open a connection to a remote logger

        host - logger host/address
        port - logger port number
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(2)

        if LOUD:
            print >>sys.stderr, "Create log client %s#%d for %s" % \
                (host, port, self)
        sock.connect((host, port))
        return sock

    def __rpcCommitSubrun(self, subrunNum, latestTime):
        "Commit subrun data"
        return "OK"

    def __rpcConfigure(self, configName):
        """
        Configure a component

        configName - configuration name
        """
        self.__state = "configuring"
        # do configuration stuff here
        self.__state = "ready"
        return "OK"

    def __rpcConnect(self, connList=None):
        """
        Connect output connectors to remote components

        connList - list of output connectors
        """

        error = False
        if connList is not None:
            for conn in connList:
                myConn = None
                for c in self.__connectors:
                    if conn['type'] == c.name():
                        myConn = c
                        break

                if myConn is None:
                    raise FakeClientException(("Cannot connect %s" +
                                               " to \"%s\" at %s:%s") %
                                              (self.name(), conn['type'],
                                               conn['host'], conn['port']))
                    
                if LOUD:
                    print >>sys.stderr, "Connect %s to %s:%d" % \
                        (self.name(), conn['host'], conn['port'])

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.settimeout(2)
                try:
                    sock.connect((conn['host'], conn['port']))
                except socket.error:
                    print >>sys.stderr, "Cannot connect %s to %s:%d" % \
                        (self.name(), conn['host'], conn['port'])
                    error = True
                myConn.addOutputChannel(sock)

        if error:
            self.__state = 'error'
            raise FakeClientException("Cannot connect %s" % self.name())

        self.__state = "connected"
        return "OK"

    def __rpcForcedStop(self):
        "Force the component to stop"
        self.__state = "stopping"
        # stop running
        self.__state = "ready"
        return "OK"

    def __rpcGetEvents(self, subrunNum):
        "Return the number of events taken during the subrun"
        if self.__mbeanDict is not None and \
               self.__mbeanDict.has_key("backEnd") and \
               self.__mbeanDict["backEnd"].has_key("NumEventsSent"):
            return self.__mbeanDict["backEnd"]["NumEventsSent"].get()
        return 0

    def __rpcGetState(self):
        "Return the current state"
        return self.__state

    def __rpcGetVersionInfo(self):
        "Return a mocked-up component version info string"
        return "$Id: %s %d 1980-01-01 00:00:00Z elmo $" % \
            (self.__name, self.__num)

    def __rpcListConnStates(self):
        "Return the current states of all connectors"
        connStates = []
        for c in self.__connectors:
            connStates.append({"type":c.name(), "state":c.state(),
                               "numChan":c.numChan()})

        return connStates

    def __rpcLogTo(self, logIP, logPort, liveIP, livePort):
        """
        Set up logging clients
        logIP - DAQ logger host/address
        logPort - DAQ logger port number
        liveIP - IceCube Live host/address
        livePort - IceCube Live port number
        """

        if logIP is not None and len(logIP) > 0 and logPort > 0:
            self.__log = self.__openLogClient(logIP, logPort)
            if self.__dfltLog is None:
                self.__dfltLog = self.__log

        if liveIP is not None and len(liveIP) > 0 and livePort > 0:
            self.__liveLog = self.__openLogClient(liveIP, livePort)
            if self.__dfltLiveLog is None:
                self.__dfltLiveLog = self.__livelog

        return "OK"

    def __rpcPrepareSubrun(self, subrunNum):
        """
        Prepare the subrun

        subrunNum - subrun number
        """
        return "OK"

    def __rpcReset(self):
        "Reset the component"
        self.__state = "idle"
        return self.__state

    def __rpcResetLogging(self):
        "Reset loggers to defaults"
        self.__log = self.__defaultLog
        self.__liveLog = self.__defaultLiveLog
        return "OK"

    def __rpcStartRun(self, runNum):
        """
        Start a run

        runNum - run number
        """
        self.__state = "starting"
        # start running
        self.__state = "running"
        return "OK"

    def __rpcStartSubrun(self, subrunData):
        """
        Start a subrun

        subrunData - ignored
        """
        return time.time()

    def __rpcStopRun(self):
        "Stop the component"
        self.__state = "stopping"
        self.__sendStops()
        self.__state = "ready"
        return "OK"

    def __rpcTerminate(self):
        "Terminate the component"
        self.close()

    def __sendStops(self):
        "Send stop payloads to all output connectors"
        stopMsg = None
        for c in self.__connectors:
            if not c.isInput():
                if stopMsg is None:
                    stopMsg = chr(0) + chr(0) + chr(0) + chr(4)
                c.send(stopMsg)
                c.setState("stopped")

    def close(self):
        "Close all connectors and the XML-RPC server"
        self.__rpcRunning = False
        for c in self.__connectors:
            try:
                c.close()
            except:
                pass

        if self.__proxy is not None:
            self.__proxy.close()

        if self.__mbeanServer is not None:
            self.__mbeanServer.close()

        rtnVal = self.__rpcServer.server_close()

        if self.__wrapper is not None:
            self.__wrapper.close()

        return rtnVal

    def fork(self):
        "Run client in a subprocess"
        proxyPort = self.nextPortNumber()

        pid = os.fork()
        if pid == 0:
            self.setWrapper(ClientWrapper(self, proxyPort))
            return 0

        time.sleep(0.1)

        self.__proxy = ServerProxy("http://localhost:%s" % proxyPort,
                                   verbose=False)

        return pid

    def get(self, bean, fld):
        if self.__mbeanDict is None or not self.__mbeanDict.has_key(bean) or \
               not self.__mbeanDict[bean].has_key(fld):
            return None

        return self.__mbeanDict[bean][fld].update()

    def getAttributes(self, bean, fldList):
        if self.__mbeanDict is None or not self.__mbeanDict.has_key(bean):
            return []

        attrDict = {}
        for fld in fldList:
            if self.__mbeanDict[bean].has_key(fld):
                try:
                    attrDict[fld] = self.__mbeanDict[bean][fld].update()
                except:
                    print >>sys.stderr, "Bean %s Fld %s" % (bean, fld)
                    traceback.print_exc()
                    raise

        return attrDict

    def listGetters(self, bean):
        if self.__mbeanDict is None or not self.__mbeanDict.has_key(bean):
            return []
        return self.__mbeanDict[bean].keys()

    def listMBeans(self):
        if self.__mbeanDict is None:
            return []

        return self.__mbeanDict.keys()

    def name(self):
        "Return component name"
        return "%s#%d" % (self.__name, self.__num)

    def nextPortNumber(cls):
        "Get the next available port number"
        port = cls.NEXT_PORT
        cls.NEXT_PORT += 1
        return port
    nextPortNumber = classmethod(nextPortNumber)

    def register(self):
        "Create input sockets and register component with CnCServer"
        if self.__rpcPort is None: return 0

        if self.__proxy is not None:
            self.__proxy.register()
            return 1

        self.__createConnectorSockets()

        regData = self.rpc_component_register(self.__name, self.__num,
                                              FakeClient.LOCAL_ADDR,
                                              self.__rpcPort, self.__mbeanPort,
                                              self.__getConnectorList())
        self.__clientId = regData["id"]
        self.__serverId = regData["serverId"]

        if regData["logIP"] is not None and regData["logIP"] != "" and \
                regData["logPort"] is not None and regData["logPort"] != 0:
            self.__log = self.__openLogClient(regData["logIP"],
                                              regData["logPort"])

        if regData["liveIP"] is not None and regData["liveIP"] != "" and \
                regData["livePort"] is not None and regData["livePort"] != 0:
            self.__liveLog = self.__openLogClient(regData["liveIP"],
                                                  regData["livePort"])

        return 2

    def run(self):
        "Run the XML-RPC server until asked to stop"

        self.__mbeanServer = MBeanThread(self.__name, self.__num,
                                         self.__mbeanPort, self)
        self.__mbeanServer.start()

        try:
            self.__rpcServer = ReusableXMLRPCServer(self.__rpcPort, 1)
        except socket.error:
            raise FakeClientException("Port %d is already being used" %
                                      self.__rpcPort)

        self.__rpcServer.register_function(self.__rpcCommitSubrun,
                                           'xmlrpc.commitSubrun')
        self.__rpcServer.register_function(self.__rpcConfigure,
                                           'xmlrpc.configure')
        self.__rpcServer.register_function(self.__rpcConnect, 'xmlrpc.connect')
        self.__rpcServer.register_function(self.__rpcForcedStop,
                                           'xmlrpc.forcedStop')
        self.__rpcServer.register_function(self.__rpcGetEvents,
                                           'xmlrpc.getEvents')
        self.__rpcServer.register_function(self.__rpcGetState,
                                           'xmlrpc.getState')
        self.__rpcServer.register_function(self.__rpcGetVersionInfo,
                                           'xmlrpc.getVersionInfo')
        self.__rpcServer.register_function(self.__rpcLogTo, 'xmlrpc.logTo')
        self.__rpcServer.register_function(self.__rpcListConnStates,
                                           'xmlrpc.listConnectorStates')
        self.__rpcServer.register_function(self.__rpcReset, 'xmlrpc.reset')
        self.__rpcServer.register_function(self.__rpcPrepareSubrun,
                                           'xmlrpc.prepareSubrun')
        self.__rpcServer.register_function(self.__rpcResetLogging,
                                           'xmlrpc.resetLogging')
        self.__rpcServer.register_function(self.__rpcStartRun,
                                           'xmlrpc.startRun')
        self.__rpcServer.register_function(self.__rpcStartSubrun,
                                           'xmlrpc.startSubrun')
        self.__rpcServer.register_function(self.__rpcStopRun, 'xmlrpc.stopRun')
        self.__rpcServer.register_function(self.__rpcTerminate,
                                           'xmlrpc.terminate')

        self.__rpcRunning = True
        while self.__rpcRunning:
            try:
                self.__rpcServer.handle_request()
            except:
                break
        try:
            self.close()
        except:
            pass

    def setWrapper(self, wrapper):
        self.__wrapper = wrapper
        self.__wrapper.start()

    def start(self):
        if self.__proxy is not None:
            self.__proxy.start()
        elif self.__rpcPort is not None:
            super(FakeClient, self).start()
        return 1

class ClientWrapper(threading.Thread):
    def __init__(self, client, rpcPort):
        self.__client = client
        self.__rpcPort = rpcPort

        self.__rpcRunning = False

        super(ClientWrapper, self).__init__(name=str(self))
        self.setDaemon(True)

    def __str__(self):
        return "Wrap[%s]" % str(self.__client)

    def close(self):
        self.__rpcRunning = False

    def run(self):
        try:
            rpcServer = ReusableXMLRPCServer(self.__rpcPort, 1)
        except socket.error:
            raise FakeClientException("Port %d is already being used" %
                                      self.__rpcPort)
        #rpcServer.register_introspection_functions()
        rpcServer.register_function(self.close, 'close')
        rpcServer.register_function(self.__client.register, 'register')
        rpcServer.register_function(self.__client.start, 'start')

        self.__rpcRunning = True
        while self.__rpcRunning:
            try:
                rpcServer.handle_request()
            except:
                break
        raise SystemExit

class DAQFakeRunException(Exception): pass

class LogThread(threading.Thread):
    "Log message reader socket"

    TIMEOUT = 100

    def __init__(self, compName, port):
        """
        Create a log socket reader

        compName - component name
        port - log port number
        """

        self.__compName = compName
        self.__port = port

        self.__sock = None
        self.__serving = False

        logName = "%s:log#%d" % (self.__compName, self.__port)
        super(LogThread, self).__init__(name=logName)
        self.setDaemon(True)

    def stop(self):
        "Stop reading from the socket"
        self.__serving = False
        self.__sock.close()

    def run(self):
        "Create socket and read until closed"
        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.setblocking(0)
        self.__sock.settimeout(2)
        self.__sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        if LOUD:
            print >>sys.stderr, "Create log server localhost#%d" % self.__port
        try:
            self.__sock.bind(("", self.__port))
        except socket.error:
            raise FakeClientException('Cannot bind log thread to port %d' %
                                      self.__port)

        self.__serving = True

        pr = [self.__sock]
        pw = []
        pe = [self.__sock]
        while self.__serving:
            rd, rw, re = select.select(pr, pw, pe, self.TIMEOUT)
            if len(re) != 0:
                print >>sys.stderr, "Error on select"

            if len(rd) == 0:
                continue

            while True:
                try:
                    data = self.__sock.recv(8192, socket.MSG_DONTWAIT)
                    if LOUD:
                        print >>sys.stderr, "%s: %s" % (self.__compName, data)
                    #print >>self.__outfile, "%s %s" % (self.__compName, data)
                    #self.__outfile.flush()
                except:
                    break # Go back to select so we don't busy-wait

class BeanValue(object):
    def __init__(self, value, delta):
        self.__value = value
        self.__delta = delta

    def get(self): return self.__value
    def update(self):
        val = self.__value
        if self.__delta is not None:
            self.__value += self.__delta
        return val

class ComponentData(object):
    "Component data used to create simulated components"

    RADAR_DOM = "123456789abc"
    __BEAN_DATA = {
        "stringHub" : {
            "DataCollectorMonitor-00A" : {
                "MainboardId" : (RADAR_DOM, None),
                "HitRate" : (0.0, 0.0),
                },
            "sender" : {
                "NumHitsReceived" : (0, 10),
                "NumReadoutRequestsReceived" : (0, 2),
                "NumReadoutsSent" : (0, 2),
                },
            "stringhub" : {
                "NumberOfActiveChannels" : (0, None),
                },
            },
        "inIceTrigger" : {
            "stringHit" : {
                "RecordsReceived" : (0, 10),
                },
            "trigger" : {
                "RecordsSent" : (0, 2),
                },
            },
        "globalTrigger" : {
            "trigger" : {
                "RecordsReceived" : (0, 2),
                },
            "glblTrig" : {
                "RecordsSent" : (0, 2),
                },
            },
        "eventBuilder" : {
            "backEnd" : {
                "DiskAvailable" : (2048, None),
                "EventData" : (0, 1),
                "FirstEventTime" : (0, None),
                "NumBadEvents" : (0, None),
                "NumEventsSent" : (0, 1),
                "NumReadoutsReceived" : (0, 2),
                "NumTriggerRequestsReceived" : (0, 2),
                },
            },
        "secondaryBuilders" : {
            "moniBuilder" : {
                "DiskAvailable" : (2048, None),
                "TotalDispatchedData" : (0, 100),
                },
            "snBuilder" : {
                "DiskAvailable" : (2048, None),
                "TotalDispatchedData" : (0, 100),
                },
            "tcalBuilder" : {
                "DiskAvailable" : (2048, None),
                "TotalDispatchedData" : (0, 100),
                },
            }}

    def __init__(self, compName, compNum, connList, addNumericPrefix=True):
        """
        Create a component

        compName - component name
        compNum - component number
        connList - list of connections
        beanDict - dictionary of 'MBean' name/value pairs
        addNumericPrefix - if True, add a number to the component name
        """
        self.__compName = compName
        self.__compNum = compNum
        self.__connList = connList[:]
        self.__create = True
        self.__addNumericPrefix = addNumericPrefix
        self.__mbeanDict = self.__buildMBeanDict()

    def __buildMBeanDict(self):
        beanDict = {}
        if not self.__BEAN_DATA.has_key(self.__compName):
            print >>sys.stderr, "No bean data for %s" % self.__compName
        else:
            for bean in self.__BEAN_DATA[self.__compName]:
                beanDict[bean] = {}
                for fld in self.__BEAN_DATA[self.__compName][bean]:
                    beanData = self.__BEAN_DATA[self.__compName][bean][fld]
                    beanDict[bean][fld] = BeanValue(beanData[0], beanData[1])

        return beanDict

    def createAll(cls, numHubs, addNumericPrefix):
        "Create initial component data list"
        comps = cls.createHubs(numHubs, addNumericPrefix)

        # create additional components
        comps.append(ComponentData("inIceTrigger", 0,
                                   [("stringHit", Connector.INPUT),
                                    ("trigger", Connector.OUTPUT)],
                                   addNumericPrefix))
        #comps.append(ComponentData("icetopTrigger", 0,
        #                           [("icetopHit", Connector.INPUT),
        #                            ("trigger", Connector.OUTPUT)],
        #                           addNumericPrefix))
        comps.append(ComponentData("globalTrigger", 0,
                                   [("trigger", Connector.INPUT),
                                    ("glblTrig", Connector.OUTPUT)],
                                   addNumericPrefix))
        comps.append(ComponentData("eventBuilder", 0,
                                   [("glblTrig", Connector.INPUT),
                                    ("rdoutReq", Connector.OUTPUT),
                                    ("rdoutData", Connector.INPUT),],
                                   addNumericPrefix))
        comps.append(ComponentData("secondaryBuilders", 0,
                                   [("moniData", Connector.INPUT),
                                    ("snData", Connector.INPUT),
                                    ("tcalData", Connector.INPUT)],
                                   addNumericPrefix))

        return comps
    createAll = classmethod(createAll)

    def createHubs(cls, numHubs, addNumericPrefix):
        "create all stringHubs"
        comps = []

        for n in range(numHubs):
            comps.append(ComponentData("stringHub", n + 1,
                                       [("stringHit", Connector.OUTPUT),
                                        ("moniData", Connector.OUTPUT),
                                        ("snData", Connector.OUTPUT),
                                        ("tcalData", Connector.OUTPUT),
                                        ("rdoutReq", Connector.INPUT),
                                        ("rdoutData", Connector.OUTPUT)],
                                       addNumericPrefix))

        return comps
    createHubs = classmethod(createHubs)

    def createSmall(cls):
        "Create 3-element component data list"
        return [ComponentData("foo", 0, [("hit", Connector.OUTPUT)]),
                ComponentData("bar", 0, [("hit", Connector.INPUT),
                                         ("event", Connector.OUTPUT)]),
                ComponentData("fooBuilder", 0, [("event", Connector.INPUT)])]
    createSmall = classmethod(createSmall)

    def createTiny(cls):
        "Create 2-element component data list"
        return [ComponentData("foo", 0, [("hit", Connector.OUTPUT)]),
                ComponentData("bar", 0, [("hit", Connector.INPUT)])]
    createTiny = classmethod(createTiny)

    def getFakeClient(self):
        "Create a FakeClient object using this component data"
        return FakeClient(self.__compName, self.__compNum, self.__connList,
                          self.__mbeanDict, self.__create,
                          self.__addNumericPrefix)

    def isComponent(self, name, num=-1):
        "Does this component have the specified name and number?"
        return self.__compName == name and (num < 0 or self.__compNum == num)

    def useRealComponent(self):
        "This component should not register itself so the Java version is used"
        self.__create = False

class DAQFakeRun(object):
    "Fake DAQRun"

    LOCAL_ADDR = getHostAddress("localhost")
    CNCSERVER_HOST = LOCAL_ADDR
    CNCSERVER_PORT = 8080

    def __init__(self, cncHost=CNCSERVER_HOST, cncPort=CNCSERVER_PORT,
                 verbose=False):
        """
        Create a fake DAQRun

        cncHost - CnCServer host name/address
        cncPort - CnCServer port number
        verbose - if XML-RPC server should print connection info
        """

        self.__logThreads = []

        self.__client = ServerProxy("http://%s:%s" % (cncHost, cncPort),
                                    verbose=verbose)

    def __createClusterDescriptionFile(cls, runCfgDir):
        path = os.path.join(runCfgDir, "sps-cluster.cfg")
        if not os.path.exists(path):
            fd = open(path, "w")

            print >>fd, """<cluster name="localhost">
  <logDirForSpade>spade</logDirForSpade>
 <default>
   <jvm>java</jvm>
    <jvmArgs>-server</jvmArgs>
    <logLevel>INFO</logLevel>
 </default>
  <host name="localhost">
    <component name="SecondaryBuilders" required="true"/>
    <component name="eventBuilder" required="true"/>
    <component name="globalTrigger" required="true"/>
    <component name="inIceTrigger"/>
    <component name="iceTopTrigger"/>
    <component name="amandaTrigger"/>
    <simulatedHub number="100" priority="1"/>
  </host>
</cluster>"""
            fd.close()
    __createClusterDescriptionFile = classmethod(__createClusterDescriptionFile)

    def __getRunTime(cls, startTime):
        diff = datetime.datetime.now() - startTime
        return float(diff.seconds) + (float(diff.microseconds) / 1000000.0)
    __getRunTime = classmethod(__getRunTime)

    def __openLog(self, host, port):
        """
        Open a connection to the log server

        host - log host name/address
        port - log port number

        Returns the new socket
        """

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(2)
        sock.connect((host, port))
        return sock

    def __runInternal(self, runsetId, runCfg, runNum, duration):
        """
        Take all components through a simulated run

        runsetId - ID of runset being used
        runCfg - run configuration name
        runNum - run number
        duration - length of run in seconds
        """
        runComps = self.__client.rpc_runset_list(runsetId)

        logList = []
        for c in runComps:
            logPort = FakeClient.nextPortNumber()

            logThread = LogThread("%s#%d" %
                                  (c["compName"], c["compNum"]), logPort)
            logThread.start()

            self.__logThreads.append(logThread)
            logList.append([c["compName"], c["compNum"], logPort])

        runOptions = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        try:
            self.__client.rpc_runset_start_run(runsetId, runNum, runOptions)

            startTime = datetime.datetime.now()

            time.sleep(1)

            self.__client.rpc_runset_list(runsetId)

            time.sleep(1)

            self.__client.rpc_runset_subrun(runsetId, -1,
                                            [("0123456789abcdef",
                                              0, 1, 2, 3, 4), ])

            waitSecs = duration - self.__getRunTime(startTime)
            if waitSecs <= 0.0:
                waitSlice = 0.0
            else:
                waitSlice = waitSecs / 3.0
                if waitSlice > 10.0:
                    waitSlice = 10.0

            while waitSecs > 0:
                time.sleep(waitSlice)
                try:
                    numEvts = self.__client.rpc_runset_events(runsetId, -1)
                except:
                    numEvts = None

                runSecs = self.__getRunTime(startTime)
                if numEvts is not None:
                    print "RunSet %d had %d events after %.2f secs" % \
                          (runsetId, numEvts, runSecs)
                else:
                    print ("RunSet %d could not get event count after" +
                           " %.2f secs") % (runsetId, numEvts, runSecs)

                waitSecs = duration - runSecs
        finally:
            try:
                self.__client.rpc_runset_stop_run(runsetId)
            except:
                pass

    def __runOne(self, compList, runCfgDir, runNum, duration):
        """
        Simulate a run

        compList - list of components
        runCfg - run configuration name
        runNum - run number
        duration - length of run in seconds
        """

        numSets = self.__client.rpc_runset_count()
        if LOUD:
            print >>sys.stderr, "%d active runsets" % numSets
            for c in self.__client.rpc_component_list_dicts():
                print >>sys.stderr, str(c)
            print >>sys.stderr, "---"

        mockRunCfg = self.createMockRunConfig(runCfgDir, compList)
        self.hackActiveConfig(mockRunCfg)

        runsetId = self.makeRunset(compList, mockRunCfg)

        if numSets != self.__client.rpc_runset_count() - 1:
            print >>sys.stderr, "Expected %d run sets" % (numSets + 1)

        try:
            self.__runInternal(runsetId, mockRunCfg, runNum, duration)
        finally:
            self.closeAll(runsetId)

    def __waitForComponents(self, numComps):
        """
        Wait for our components to be removed from CnCServer

        numComps - initial number of components
        """
        for i in range(10):
            num = self.__client.rpc_component_count()
            if num == numComps:
                break
            time.sleep(1)

        num = self.__client.rpc_component_count()
        if num > numComps:
            print >>sys.stderr, \
                "CnCServer still has %d components (expect %d)" % \
                (num, numComps)

    def closeAll(self, runsetId):
        try:
            self.__client.rpc_runset_break(runsetId)
        except:
            traceback.print_exc()

        for lt in self.__logThreads:
            lt.stop()
        del self.__logThreads[:]

    def createComps(cls, compData, forkClients):
        "create and start components"
        comps = []
        for cd in compData:
            client = cd.getFakeClient()
            if forkClients:
                if client.fork() == 0: return

            client.start()
            client.register()

            comps.append(client)
        return comps
    createComps = classmethod(createComps)

    def createMockRunConfig(cls, runCfgDir, compList):
        cfgFile = MockRunConfigFile(runCfgDir)

        nameList = []
        for c in compList:
            nameList.append(c.name())

        cls.__createClusterDescriptionFile(runCfgDir)

        return cfgFile.create(nameList, [])
    createMockRunConfig = classmethod(createMockRunConfig)

    def hackActiveConfig(cls, clusterCfg):
        path = os.path.join(os.environ["HOME"], ".active")
        if not os.path.exists(path):
            print >>sys.stderr, "Setting ~/.active to \"%s\"" % clusterCfg
        else:
            fd = open(path, "r")
            curCfg = fd.read().split("\n")[0]
            fd.close()
            print >>sys.stderr, "Changing ~/.active from \"%s\" to \"%s\"" % \
                  (curCfg, clusterCfg)

        fd = open(path, "w")
        print >>fd, clusterCfg
        fd.close()
    hackActiveConfig = classmethod(hackActiveConfig)

    def makeRunset(self, compList, runCfg):
        nameList = []
        for c in compList:
            nameList.append(c.name())

        runsetId = self.__client.rpc_runset_make(runCfg, False)
        if runsetId < 0:
            raise DAQFakeRunException("Cannot make runset from %s" %
                                      str(nameList))

        return runsetId

    def runAll(self, compData, startNum, numRuns, duration, runCfgDir,
               forkClients):
        runNum = startNum

        # do all the runs
        #
        for n in range(numRuns):
            # grab the number of components before we add ours
            #
            numComps = self.__client.rpc_component_count()

            # create components
            #
            comps = self.createComps(compData, forkClients)

            # simulate a run
            #
            try:
                self.__runOne(comps, runCfgDir, runNum, duration)
            except:
                traceback.print_exc()
            runNum += 1

            # close all created components
            #
            self.__client.rpc_end_all()

            # wait for closed components to be removed from server
            #
            print "Waiting for components"
            self.__waitForComponents(numComps)

if __name__ == "__main__":
    parser = optparse.OptionParser()

    parser.add_option("-c", "--config", type="string", dest="runCfgDir",
                      action="store", default="/tmp/config",
                      help="Run configuration directory"),
    parser.add_option("-d", "--duration", type="int", dest="duration",
                      action="store", default="5",
                      help="Number of seconds for run"),
    parser.add_option("-e", "--eventBuilder", dest="evtBldr",
                      action="store_true", default=False,
                      help="Use existing event builder")
    parser.add_option("-f", "--forkClients", dest="forkClients",
                      action="store_true", default=False,
                      help="Run clients in subprocesses")
    parser.add_option("-g", "--globalTrigger", dest="glblTrig",
                      action="store_true", default=False,
                      help="Use existing global trigger")
    parser.add_option("-H", "--numberOfHubs", type="int", dest="numHubs",
                      action="store", default=2,
                      help="Number of fake hubs"),
    parser.add_option("-i", "--iniceTrigger", dest="iniceTrig",
                      action="store_true", default=False,
                      help="Use existing in-ice trigger")
    parser.add_option("-n", "--numOfRuns", type="int", dest="numRuns",
                      action="store", default=1,
                      help="Number of runs"),
    parser.add_option("-p", "--firstPortNumber", type="int", dest="firstPort",
                      action="store", default=FakeClient.NEXT_PORT,
                      help="First port number used for fake components"),
    parser.add_option("-R", "--realNames", dest="realNames",
                      action="store_true", default=False,
                      help="Use component names without numeric prefix"),
    parser.add_option("-r", "--runNum", type="int", dest="runNum",
                      action="store", default=1234,
                      help="Run number"),
    parser.add_option("-S", "--small", dest="smallCfg",
                      action="store_true", default=False,
                      help="Use canned 3-element configuration")
    parser.add_option("-T", "--tiny", dest="tinyCfg",
                      action="store_true", default=False,
                      help="Use canned 2-element configuration")
    parser.add_option("-t", "--icetopTrigger", dest="icetopTrig",
                      action="store_true", default=False,
                      help="Use existing icetop trigger")

    opt, args = parser.parse_args()

    if opt.firstPort != FakeClient.NEXT_PORT:
        FakeClient.NEXT_PORT = opt.firstPort

    # get list of components
    #
    if opt.tinyCfg:
        compData = ComponentData.createTiny()
    elif opt.smallCfg:
        compData = ComponentData.createSmall()
    else:
        compData = ComponentData.createAll(opt.numHubs, not opt.realNames)
        for cd in compData:
            if opt.evtBldr and cd.isComponent("eventBuilder"):
                cd.useRealComponent()
            elif opt.glblTrig and cd.isComponent("globalTrigger"):
                cd.useRealComponent()
            elif opt.iniceTrig and cd.isComponent("iniceTrigger"):
                cd.useRealComponent()
            elif opt.icetopTrig and cd.isComponent("icetopTrigger"):
                cd.useRealComponent()

    try:
        DAQConfigParser.getClusterConfiguration(None, useActiveConfig=True)
    except:
        DAQFakeRun.hackActiveConfig("sim-localhost")

    from DumpThreads import DumpThreadsOnSignal
    DumpThreadsOnSignal()

    # create run object and initial run number
    #
    runner = DAQFakeRun()
    runner.runAll(compData, opt.runNum, opt.numRuns, opt.duration,
                  opt.runCfgDir, opt.forkClients)
