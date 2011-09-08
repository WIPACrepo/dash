#!/usr/bin/env python

import datetime, optparse, os, select, socket, struct, sys, threading, time, \
       traceback
from xmlrpclib import ServerProxy
from CnCServer import Connector
from DAQConfig import DAQConfigParser
from DAQMocks import MockRunConfigFile
from FakeClient import FakeClient, FakeClientException
from RunOption import RunOption
from utils import ip

LOUD = False

class ClientWrapper(threading.Thread):
    def __init__(self, client, rpcPort):
        self.__client = client
        self.__rpcPort = rpcPort

        self.__rpcRunning = False

        super(type(self), self).__init__(name=str(self))
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
        super(type(self), self).__init__(name=logName)
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
            try:
                rd, rw, re = select.select(pr, pw, pe, self.TIMEOUT)
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
        if self.__delta is not None and type(self.__delta) == int:
            if type(self.__value) == int:
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
                "NumberOfActiveChannels" : (0, 0),
                "NumberOfActiveAndTotalChannels" : ((0, 0), None),
                "TotalLBMOverflows" : (0, 0),
                "HitRate" : (0, 0),
                "HitRateLC" : (0, 0),
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

    def __str__(self):
        if self.__compNum == 0:
            return self.__compName
        return "%s#%d" % (self.__compName, self.__compNum)

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

    @classmethod
    def createAll(cls, numHubs, addNumericPrefix, includeIceTop=False,
                  includeTrackEngine=False):
        "Create initial component data list"
        comps = cls.createHubs(numHubs, addNumericPrefix,
                               sendTrackHits=includeTrackEngine,
                               isIceTop=False)
        if includeIceTop:
            itHubs = numHubs / 8
            if itHubs == 0:
                itHubs = 1
            comps = cls.createHubs(itHubs, addNumericPrefix,
                                   sendTrackHits=includeTrackEngine,
                                   isIceTop=True)

        # create additional components
        comps.append(ComponentData("inIceTrigger", 0,
                                   [("stringHit", Connector.INPUT),
                                    ("trigger", Connector.OUTPUT)],
                                   addNumericPrefix))
        if includeIceTop:
            comps.append(ComponentData("icetopTrigger", 0,
                                       [("icetopHit", Connector.INPUT),
                                        ("trigger", Connector.OUTPUT)],
                                       addNumericPrefix))
        if includeTrackEngine:
            comps.append(ComponentData("trackEngine", 0,
                                       [("trackEngHit", Connector.INPUT),
                                        ("trigger", Connector.OUTPUT)],
                                       addNumericPrefix))

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

    @staticmethod
    def createHubs(numHubs, addNumericPrefix, sendTrackHits,
                   isIceTop=False):
        "create all stringHubs"
        comps = []

        connList = [("moniData", Connector.OUTPUT),
                    ("snData", Connector.OUTPUT),
                    ("tcalData", Connector.OUTPUT),
                    ("rdoutReq", Connector.INPUT),
                    ("rdoutData", Connector.OUTPUT)]

        if isIceTop:
            connList.append(("icetopHit", Connector.OUTPUT))
        else:
            connList.append(("stringHit", Connector.OUTPUT))

        if sendTrackHits:
            connList.append(("trackEngHit", Connector.OPT_OUTPUT))

        for n in range(numHubs):
            comps.append(ComponentData("stringHub", n + 1, connList,
                                       addNumericPrefix))

        return comps

    @staticmethod
    def createSmall():
        "Create 3-element component data list"
        return [ComponentData("foo", 0, [("hit", Connector.OUTPUT)]),
                ComponentData("bar", 0, [("hit", Connector.INPUT),
                                         ("event", Connector.OUTPUT)]),
                ComponentData("fooBuilder", 0, [("event", Connector.INPUT)])]

    @staticmethod
    def createTiny():
        "Create 2-element component data list"
        return [ComponentData("foo", 0, [("hit", Connector.OUTPUT)]),
                ComponentData("bar", 0, [("hit", Connector.INPUT)])]

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

    LOCAL_ADDR = ip.getLocalIpAddr()
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

    @staticmethod
    def __createClusterDescriptionFile(runCfgDir):
        path = os.path.join(runCfgDir, "sps-cluster.cfg")
        if not os.path.exists(path):
            with open(path, 'w') as fd:
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


    @staticmethod
    def __getRunTime(startTime):
        diff = datetime.datetime.now() - startTime
        return float(diff.seconds) + (float(diff.microseconds) / 1000000.0)

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
                           " %.2f secs") % (runsetId, runSecs)

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

        runsetId = self.makeRunset(compList, mockRunCfg, runNum)

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

    @staticmethod
    def createComps(compData, forkClients):
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

    @classmethod
    def createMockRunConfig(cls, runCfgDir, compList):
        cfgFile = MockRunConfigFile(runCfgDir)

        nameList = []
        for c in compList:
            nameList.append(c.fullName())

        cls.__createClusterDescriptionFile(runCfgDir)

        return cfgFile.create(nameList, [])

    @staticmethod
    def hackActiveConfig(clusterCfg):
        path = os.path.join(os.environ["HOME"], ".active")
        if not os.path.exists(path):
            print >>sys.stderr, "Setting ~/.active to \"%s\"" % clusterCfg
        else:
            with open(path, 'r') as fd:
                curCfg = fd.read().split("\n")[0]
            print >>sys.stderr, "Changing ~/.active from \"%s\" to \"%s\"" % \
                  (curCfg, clusterCfg)

        with open(path, 'w') as fd:
            print >>fd, clusterCfg

    @staticmethod
    def makeMockClusterConfig(runCfgDir, comps, numHubs):
        path = os.path.join(runCfgDir, "localhost.cfg")
        if os.path.exists(path):
            return

        path = os.path.join(runCfgDir, "localhost-cluster.cfg")
        if os.path.exists(path):
            return

        with open(path, 'w') as fd:
            print >>fd, "<cluster name=\"localhost\">"
            print >>fd, "  <logDirForSpade>%s</logDirForSpade>"
            print >>fd, "  <host name=\"localhost\">"

            for c in comps:
                nm = c.name()
                if nm == "stringHub": continue

                if nm == "globalTrigger" or nm == "eventBuilder" or \
                       nm == "secondaryBuilders":
                    req = " required=\"true\""
                else:
                    req = ""

                print >>fd, "    <component name=\"%s\"%s/>" % (nm, req)

            print >>fd, "    <simulatedHub number=\"%d\" priority=\"1\"/>" % \
                  numHubs
            print >>fd, "  </host>"
            print >>fd, "</cluster>"


    def makeRunset(self, compList, runCfg, runNum):
        nameList = []
        for c in compList:
            nameList.append(c.fullName())

        runsetId = self.__client.rpc_runset_make(runCfg, runNum, False)
        if runsetId < 0:
            raise DAQFakeRunException("Cannot make runset from %s" %
                                      str(nameList))

        return runsetId

    def runAll(self, comps, startNum, numRuns, duration, runCfgDir):
        runNum = startNum

        # grab the number of components before we add ours
        #
        numComps = self.__client.rpc_component_count()

        # do all the runs
        #
        for n in range(numRuns):
            # wait for all components to be registered
            #
            numNew = numComps + len(comps)
            for cc in range(10):
                if self.__client.rpc_component_count() == numNew:
                    break
                time.sleep(0.1)

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
            self.__waitForComponents(numNew)

if __name__ == "__main__":
    parser = optparse.OptionParser()

    parser.add_option("-A", "--includeTrackEngine", dest="incTrackEng",
                      action="store_true", default=False,
                      help="Include track engine in full configuration")
    parser.add_option("-a", "--trackEngine", dest="trackEng",
                      action="store_true", default=False,
                      help="Use existing track engine")
    parser.add_option("-c", "--config", type="string", dest="runCfgDir",
                      action="store", default="/tmp/config",
                      help="Run configuration directory")
    parser.add_option("-d", "--duration", type="int", dest="duration",
                      action="store", default="5",
                      help="Number of seconds for run")
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
                      help="Number of fake hubs")
    parser.add_option("-i", "--iniceTrigger", dest="iniceTrig",
                      action="store_true", default=False,
                      help="Use existing in-ice trigger")
    parser.add_option("-n", "--numOfRuns", type="int", dest="numRuns",
                      action="store", default=1,
                      help="Number of runs")
    parser.add_option("-p", "--firstPortNumber", type="int", dest="firstPort",
                      action="store", default=FakeClient.NEXT_PORT,
                      help="First port number used for fake components")
    parser.add_option("-R", "--realNames", dest="realNames",
                      action="store_true", default=False,
                      help="Use component names without numeric prefix")
    parser.add_option("-r", "--runNum", type="int", dest="runNum",
                      action="store", default=1234,
                      help="Run number")
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

    if sys.version_info > (2, 3):
        from DumpThreads import DumpThreadsOnSignal
        DumpThreadsOnSignal()

    if opt.firstPort != FakeClient.NEXT_PORT:
        FakeClient.NEXT_PORT = opt.firstPort

    # make sure to include trackEngine if user wants to use real track engine
    #
    if opt.trackEng:
        opt.incTrackEng = True

    # get list of components
    #
    if opt.tinyCfg:
        compData = ComponentData.createTiny()
    elif opt.smallCfg:
        compData = ComponentData.createSmall()
    else:
        compData = ComponentData.createAll(opt.numHubs, not opt.realNames,
                                           includeTrackEngine=opt.incTrackEng)
        for cd in compData:
            if opt.evtBldr and cd.isComponent("eventBuilder"):
                cd.useRealComponent()
            elif opt.glblTrig and cd.isComponent("globalTrigger"):
                cd.useRealComponent()
            elif opt.iniceTrig and cd.isComponent("iniceTrigger"):
                cd.useRealComponent()
            elif opt.icetopTrig and cd.isComponent("icetopTrigger"):
                cd.useRealComponent()
            elif opt.trackEng and cd.isComponent("trackEngine"):
                cd.useRealComponent()

    # create components
    #
    comps = DAQFakeRun.createComps(compData, opt.forkClients)

    DAQFakeRun.makeMockClusterConfig(opt.runCfgDir, comps, opt.numHubs)

    try:
        DAQConfigParser.getClusterConfiguration(None, useActiveConfig=True)
    except:
        DAQFakeRun.hackActiveConfig("sim-localhost")

    # create run object and initial run number
    #
    runner = DAQFakeRun()

    runner.runAll(comps, opt.runNum, opt.numRuns, opt.duration, opt.runCfgDir)
