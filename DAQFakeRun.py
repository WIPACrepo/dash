#!/usr/bin/env python

import datetime
import numbers
import os
import select
import shutil
import socket
import sys
import threading
import time
import traceback

from CnCServer import Connector
from DAQConfig import DAQConfigParser
from DAQConst import DAQPort
from DAQMocks import MockLeapsecondFile, MockRunConfigFile, MockTriggerConfig
from DAQRPC import RPCClient
from DefaultDomGeometry import DefaultDomGeometryReader
from FakeClient import FakeClient, FakeClientException, PortNumber
from FakeComponent import StringHub
from RunOption import RunOption
from utils import ip

LOUD = False


class DAQFakeRunException(Exception):
    pass


class HubType(object):
    ALL = 0
    PHYSICS_ONLY = 1
    SECONDARY_ONLY = 2


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
            try:
                rd, _, re = select.select(pr, pw, pe, self.TIMEOUT)
            except select.error as selerr:
                if selerr[0] == socket.EBADF:
                    break
                raise
            except socket.error as sockerr:
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
                except:
                    break  # Go back to select so we don't busy-wait


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
            for idx in range(len(value)):
                _, newval = cls.__update_recursive(value[idx], delta[idx])
                newlist.append(newval)
            if isinstance(value, list):
                return rtnval, newlist
            else:
                return rtnval, tuple(newlist)

        print >>sys.stderr, "Not updating %s: value %s<%s> != delta" \
            " %s<%s>" % (self.__name, value, type(value).__name__, delta,
                         type(delta).__name__)
        return value, delta

    def get(self):
        return self.__value

    def update(self):
        rtnval, newval = self.__update_recursive(self.__name, self.__value,
                                                 self.__delta)
        self.__value = newval
        return rtnval

class ComponentData(object):
    "Component data used to create simulated components"

    RADAR_DOM = "123456789abc"
    __BEAN_DATA = {
        "stringHub": {
            "DataCollectorMonitor-00A": {
                "MainboardId": (RADAR_DOM, None),
                "HitRate": (0.0, 0.0),
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
                "HitRate": (0, 0),
                "HitRateLC": (0, 0),
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
                "EventData": ((0, 1), (3, 10000000000)),
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

    def __init__(self, compName, compNum, connList, numeric_prefix=False):
        """
        Create a component

        compName - component name
        compNum - component number
        connList - list of connections
        beanDict - dictionary of 'MBean' name/value pairs
        numeric_prefix - if True, add a number to the component name
        """
        self.__name = compName
        self.__num = compNum
        self.__connList = connList[:]
        self.__is_fake = True
        self.__numeric_prefix = numeric_prefix

    def __str__(self):
        return self.fullname

    @property
    def connections(self):
        return self.__connList[:]

    @classmethod
    def createAll(cls, numHubs, def_dom_geom, numeric_prefix=False,
                  include_icetop=False):
        "Create initial component data list"
        comps = cls.create_hubs(numHubs, 1, numeric_prefix=numeric_prefix,
                                is_icetop=False)
        if include_icetop:
            itHubs = numHubs / 8
            if itHubs == 0:
                itHubs = 1
            comps += cls.create_hubs(itHubs, 201,
                                     numeric_prefix=numeric_prefix,
                                     is_icetop=True)

        # create additional components
        comps.append(ComponentData("inIceTrigger", 0,
                                   [("stringHit", Connector.INPUT),
                                    ("trigger", Connector.OUTPUT)],
                                   numeric_prefix))
        if include_icetop:
            comps.append(ComponentData("icetopTrigger", 0,
                                       [("icetopHit", Connector.INPUT),
                                        ("trigger", Connector.OUTPUT)],
                                       numeric_prefix))

        comps.append(ComponentData("globalTrigger", 0,
                                   [("trigger", Connector.INPUT),
                                    ("glblTrig", Connector.OUTPUT)],
                                   numeric_prefix))
        comps.append(ComponentData("eventBuilder", 0,
                                   [("glblTrig", Connector.INPUT),
                                    ("rdoutReq", Connector.OUTPUT),
                                    ("rdoutData", Connector.INPUT)],
                                   numeric_prefix))
        comps.append(ComponentData("secondaryBuilders", 0,
                                   [("moniData", Connector.INPUT),
                                    ("snData", Connector.INPUT),
                                    ("tcalData", Connector.INPUT)],
                                   numeric_prefix))

        return comps

    @staticmethod
    def create_hubs(num_hubs, starting_number, numeric_prefix=False,
                    is_icetop=False, hub_type=HubType.ALL):
        "create all stringHubs"
        comps = []

        connList = []
        if hub_type == HubType.ALL or hub_type == HubType.PHYSICS_ONLY:
            connList += [
                ("rdoutReq", Connector.INPUT),
                ("rdoutData", Connector.OUTPUT),
            ]
            if is_icetop:
                connList.append(("icetopHit", Connector.OUTPUT))
            else:
                connList.append(("stringHit", Connector.OUTPUT))
        if hub_type == HubType.ALL or hub_type == HubType.SECONDARY_ONLY:
            connList += [
                ("moniData", Connector.OUTPUT),
                ("snData", Connector.OUTPUT),
                ("tcalData", Connector.OUTPUT),
            ]

        for n in range(num_hubs):
            comps.append(HubDescription(n + starting_number, connList,
                                        numeric_prefix=numeric_prefix))

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

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def get_fake_client(self, def_dom_geom, quiet=False):
        "Create a FakeClient object using this component data"
        if not self.__is_fake:
            return None

        return FakeClient(self.__name, self.__num, self.__connList,
                          self.mbean_dict,
                          numeric_prefix=self.__numeric_prefix, quiet=quiet)

    def isComponent(self, name, num=-1):
        "Does this component have the specified name and number?"
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def isFake(self):
        return self.__is_fake

    @property
    def mbean_dict(self):
        beanDict = {}
        if self.__name not in self.__BEAN_DATA:
            raise FakeClientException("No bean data for %s" %
                                      (self.__name, ))
        else:
            for bean in self.__BEAN_DATA[self.__name]:
                beanDict[bean] = {}
                for fld in self.__BEAN_DATA[self.__name][bean]:
                    beanData = self.__BEAN_DATA[self.__name][bean][fld]
                    beanval = BeanValue("%s.%s.%s" % (self.__name, bean, fld),
                                     beanData[0], beanData[1])
                    beanDict[bean][fld] = beanval

        return beanDict

    @property
    def name(self):
        return self.__name

    @property
    def num(self):
        return self.__num

    @property
    def use_numeric_prefix(self):
        return self.__numeric_prefix

    def useRealComponent(self):
        "This component should not register itself so the Java version is used"
        self.__is_fake = False


class HubDescription(ComponentData):
    def __init__(self, num, connList, numeric_prefix=False):
        super(HubDescription, self).__init__("stringHub", num, connList,
                                             numeric_prefix=numeric_prefix)

    def get_fake_client(self, def_dom_geom, quiet=False):
        "Create a FakeClient object using this component data"
        if not self.isFake:
            return None

        return StringHub(self.name, self.num, def_dom_geom, self.connections,
                         self.mbean_dict, quiet=quiet)


class DAQFakeRun(object):
    "Fake DAQRun"

    LOCAL_ADDR = ip.getLocalIpAddr()
    CNCSERVER_HOST = LOCAL_ADDR

    def __init__(self, cncHost=CNCSERVER_HOST, cncPort=DAQPort.CNCSERVER,
                 dumpRPC=False):
        """
        Create a fake DAQRun

        cncHost - CnCServer host name/address
        cncPort - CnCServer port number
        dumpRPC - if XML-RPC server should print connection info
        """

        self.__logThreads = []

        self.__client = RPCClient(cncHost, cncPort)

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

    def __runInternal(self, runsetId, runNum, duration, test_subrun=True,
                      verbose=False):
        """
        Take all components through a simulated run

        runsetId - ID of runset being used
        runNum - run number
        duration - length of run in seconds
        verbose - if True, print progress messages
        """
        runComps = self.__client.rpc_runset_list(runsetId)
        if verbose:
            print "Found %d components" % len(runComps)

        logList = []
        for c in runComps:
            logPort = PortNumber.next_number()

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

            if test_subrun:
                self.__client.rpc_runset_subrun(runsetId, -1,
                                                [("0123456789abcdef",
                                                  0, 1, 2, 3, 4), ])

            doSwitch = True

            runtime = self.__getRunTime(startTime)
            waitSecs = duration - runtime
            if waitSecs <= 0.0:
                waitSlice = 0.0
            else:
                if doSwitch:
                    slices = 6
                else:
                    slices = 3
                waitSlice = waitSecs / float(slices)

            for switch in (False, True):
                if switch and doSwitch:
                    self.__client.rpc_runset_switch_run(runsetId, runNum + 1)

                reps = 0
                while waitSecs > 0:
                    time.sleep(waitSlice)
                    try:
                        numEvts = self.__client.rpc_runset_events(runsetId, -1)
                    except:
                        numEvts = None

                    runSecs = self.__getRunTime(startTime)
                    if numEvts is not None:
                        print "RunSet %d had %d event%s after %.2f secs" % \
                            (runsetId, numEvts, "s" if numEvts != 1 else "",
                             runSecs)
                    else:
                        print "RunSet %d could not get event count after" \
                            " %.2f secs" % (runsetId, runSecs)

                    waitSecs = duration - runSecs

                    reps += 1
                    if doSwitch and not switch and reps == 3:
                        break
        finally:
            try:
                self.__client.rpc_runset_stop_run(runsetId)
            except:
                print >>sys.stderr, "Cannot stop run for runset #%d" % runsetId
                traceback.print_exc()

    def __runOne(self, compList, runCfgDir, mockRunCfg, runNum, duration,
                 verbose=False, test_subrun=False):
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

        leapfile = MockLeapsecondFile(runCfgDir)
        leapfile.create()

        self.hackActiveConfig(mockRunCfg)

        runsetId = self.makeRunset(compList, mockRunCfg, runNum)

        if numSets != self.__client.rpc_runset_count() - 1:
            print >>sys.stderr, "Expected %d run sets" % (numSets + 1)

        try:
            self.__runInternal(runsetId, runNum, duration, verbose=verbose,
                               test_subrun=test_subrun)
        finally:
            traceback.print_exc()
            self.closeAll(runsetId)

    def __waitForComponents(self, numComps):
        """
        Wait for our components to be removed from CnCServer

        numComps - initial number of components
        """
        for _ in range(10):
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
            pass

        for lt in self.__logThreads:
            lt.stop()
        del self.__logThreads[:]

    @staticmethod
    def create_comps(comp_data, def_dom_geom, fork_clients=False,
                     quiet=False):
        "create and start components"
        comps = []
        for cd in comp_data:
            client = cd.get_fake_client(def_dom_geom, quiet=quiet)
            if client is None:
                continue

            if cd.isFake:
                if fork_clients:
                    if client.fork() == 0:
                        return

                client.start()
                client.register()

            comps.append(client)
        return comps

    @classmethod
    def createMockRunConfig(cls, runCfgDir, compList):
        trigCfg = MockTriggerConfig("global-only")
        trigCfg.add(6000, "ThroughputTrigger", 3, -1)

        cfgFile = MockRunConfigFile(runCfgDir)

        nameList = []
        for c in compList:
            nameList.append(c.fullname)

        cls.__createClusterDescriptionFile(runCfgDir)

        return cfgFile.create(nameList, {}, trigCfg=trigCfg)

    @staticmethod
    def hackActiveConfig(clusterCfg):
        path = os.path.join(os.environ["HOME"], ".active")
        if not os.path.exists(path):
            print >>sys.stderr, "Setting ~/.active to \"%s\"" % clusterCfg
            curCfg = None
        else:
            with open(path, 'r') as fd:
                curCfg = fd.read().split("\n")[0]

        if curCfg != clusterCfg:
            print >>sys.stderr, "Changing ~/.active from \"%s\" to \"%s\"" % \
                (curCfg, clusterCfg)
            with open(path, 'w') as fd:
                print >>fd, clusterCfg

    @classmethod
    def makeMockClusterConfig(cls, runCfgDir, comps, num_hubs):
        mockName = "localhost-cluster.cfg"
        path = os.path.join(runCfgDir, mockName)
        if os.path.exists(path):
            return

        with open(path, 'w') as fd:
            print >>fd, "<cluster name=\"localhost\">"
            print >>fd, "  <host name=\"localhost\">"

            for c in comps:
                nm = c.name
                if nm == "stringHub":
                    continue

                if nm == "globalTrigger" or nm == "eventBuilder" or \
                   nm == "secondaryBuilders":
                    req = " required=\"true\""
                else:
                    req = ""

                print >>fd, "    <component name=\"%s\"%s/>" % (nm, req)

            print >>fd, "    <simulatedHub number=\"%d\" priority=\"1\"/>" % \
                (num_hubs, )
            print >>fd, "  </host>"
            print >>fd, "</cluster>"

    @classmethod
    def makeMockRunConfig(cls, runCfgDir, comp_data, moniPeriod=None):
        mockName = "fake-localhost"
        trigCfgName = "spts-IT-stdtest-01"

        path = os.path.join(runCfgDir, mockName + ".xml")
        with open(path, 'w') as fd:
            print >>fd, "<runConfig>"
            if moniPeriod is not None:
                print >>fd, "  <monitor period=\"%d\"/>" % moniPeriod
            print >>fd, "  <randomConfig>"
            print >>fd, "   <noiseRate>17.0</noiseRate>"
            for c in comp_data:
                if c.name != "stringHub":
                    continue

                print >>fd, "  <string id=\"%d\"/>" % c.num
            print >>fd, "  </randomConfig>"

            print >>fd, "  <triggerConfig>%s</triggerConfig>" % trigCfgName
            for c in comp_data:
                nm = c.name
                if nm == "stringHub":
                    continue

                print >>fd, "  <runComponent name=\"%s\"/>" % nm

            print >>fd, "</runConfig>"

        cls.makeMockTriggerConfig(runCfgDir, trigCfgName)

        return (mockName, trigCfgName)

    @classmethod
    def writeTagAndValue(cls, fd, indent, name, value):
        print >>fd, "%s<%s>%s</%s>" % (indent, name, value, name)

    @classmethod
    def writeTriggerConfig(cls, fd, indent, trigType, trigCfgId, srcId, name,
                           parameterDict, readoutDict):
        indent2 = indent + "  "
        indent3 = indent2 + "  "
        readoutDefaults = {
            "type": ("readoutType", 0),
            "offset": ("timeOffset", 0),
            "minus": ("timeMinus", 10000),
            "plus": ("timePlus", 10000),
        }

        print >>fd
        print >>fd, "%s<triggerConfig>" % indent
        cls.writeTagAndValue(fd, indent2, "triggerType", str(trigType))
        cls.writeTagAndValue(fd, indent2, "triggerConfigId", str(trigCfgId))
        cls.writeTagAndValue(fd, indent2, "sourceId", str(srcId))
        cls.writeTagAndValue(fd, indent2, "triggerName", name)
        if parameterDict is not None:
            for name, value in parameterDict.items():
                print >>fd, "%s<parameterConfig>" % indent2
                cls.writeTagAndValue(fd, indent3, "parameterName", str(name))
                cls.writeTagAndValue(fd, indent3, "parameterValueName",
                                     str(value))
                print >>fd, "%s</parameterConfig>" % indent2

        print >>fd, "%s<readoutConfig>" % indent2
        for key in ("type", "offset", "minus", "plus"):
            name, defValue = readoutDefaults[key]
            if readoutDict is not None and key in readoutDict:
                value = readoutDict[key]
            else:
                value = defValue
            cls.writeTagAndValue(fd, indent3, name, str(value))
        print >>fd, "%s</readoutConfig>" % indent2
        print >>fd, "%s</triggerConfig>" % indent

    @classmethod
    def makeMockTriggerConfig(cls, runCfgDir, trigCfgName):
        inIceId = 4000
        iceTopId = 5000
        globalId = 6000

        path = os.path.join(runCfgDir, "trigger", trigCfgName + ".xml")
        if not os.path.exists(path):
            with open(path, 'w') as fd:
                indent = "  "
                print >>fd, "<activeTriggers>"
                # add global trigger
                cls.writeTriggerConfig(fd, indent, 3, -1, globalId,
                                       "ThroughputTrigger", None, None)

                # add in-ice fixed rate trigger
                cls.writeTriggerConfig(fd, indent, 23, 23050, inIceId,
                                       "FixedRateTrigger",
                                       {"interval": 30000000000},
                                       {"minus": 5000000, "plus": 5000000})

                # add in-ice min bias trigger
                cls.writeTriggerConfig(fd, indent, 2, 0, inIceId,
                                       "MinBiasTrigger",
                                       {"prescale": 23},
                                       {"minus": 25000, "plus": 25000})

                # add icetop simple majority trigger
                cls.writeTriggerConfig(fd, indent, 0, 102, iceTopId,
                                       "SimpleMajorityTrigger",
                                       {"threshold": 6}, None)

                # add icetop calibration trigger
                cls.writeTriggerConfig(fd, indent, 1, 1009, iceTopId,
                                       "CalibrationTrigger",
                                       {"hitType": 4},
                                       {"minus": 1000, "plus": 1000})

                # add icetop min bias trigger
                cls.writeTriggerConfig(fd, indent, 2, 101, iceTopId,
                                       "MinBiasTrigger",
                                       {"prescale": 10000}, None)

                # add final tag
                print >>fd, "</activeTriggers>"

    def makeRunset(self, compList, runCfg, runNum):
        nameList = []
        for c in compList:
            nameList.append(c.fullname)

        runsetId = self.__client.rpc_runset_make(runCfg, runNum, False)
        if runsetId < 0:
            raise DAQFakeRunException(("Cannot make runset from %s" +
                                       " (runset ID=%d)") %
                                      (nameList, runsetId))

        return runsetId

    def runAll(self, comps, startNum, numRuns, duration, runCfgDir,
               mockRunCfg, verbose=False, test_subrun=False):
        runNum = startNum

        # grab the number of components before we add ours
        #
        numComps = self.__client.rpc_component_count()

        # do all the runs
        #
        for _ in range(numRuns):
            # wait for all components to be registered
            #
            numNew = numComps + len(comps)
            for _ in range(10):
                if self.__client.rpc_component_count() == numNew:
                    break
                time.sleep(0.1)

            # simulate a run
            #
            try:
                self.__runOne(comps, runCfgDir, mockRunCfg, runNum, duration,
                              verbose=verbose, test_subrun=test_subrun)
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
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--config", dest="runCfgDir",
                        default="/tmp/pdaq/config",
                        help="Run configuration directory")
    parser.add_argument("-d", "--duration", type=int, dest="duration",
                        default="5",
                        help="Number of seconds for run")
    parser.add_argument("-e", "--eventBuilder", dest="evtBldr",
                        action="store_true", default=False,
                        help="Use existing event builder")
    parser.add_argument("-F", "--fakeNames", dest="fakeNames",
                        action="store_true", default=False,
                        help="Add a numeric prefix to component names")
    parser.add_argument("-f", "--forkClients", dest="forkClients",
                        action="store_true", default=False,
                        help="Run clients in subprocesses")
    parser.add_argument("-g", "--globalTrigger", dest="glblTrig",
                        action="store_true", default=False,
                        help="Use existing global trigger")
    parser.add_argument("-H", "--numberOfHubs", type=int, dest="numHubs",
                        default=2,
                        help="Number of fake hubs")
    parser.add_argument("-i", "--iniceTrigger", dest="iniceTrig",
                        action="store_true", default=False,
                        help="Use existing in-ice trigger")
    parser.add_argument("-K", "--keep-old-files", dest="keepOldFiles",
                        action="store_true", default=False,
                        help="Keep old runs from /tmp/pdaq/log and"
                        " /tmp/pdaq/pdaqlocal")
    parser.add_argument("-n", "--numOfRuns", type=int, dest="numRuns",
                        default=1,
                        help="Number of runs")
    parser.add_argument("-M", "--moniPeriod", type=int, dest="moniPeriod",
                        default=None,
                        help="Number of seconds between monitoring requests")
    parser.add_argument("-p", "--firstPortNumber", type=int, dest="firstPort",
                        default=None,
                        help="First port number used for fake components")
    parser.add_argument("-q", "--quiet", dest="quiet",
                        action="store_true", default=False,
                        help="Fake components don't announce what they're"
                        " doing")
    parser.add_argument("-r", "--runNum", type=int, dest="runNum",
                        default=1234,
                        help="Run number")
    parser.add_argument("-S", "--small", dest="smallCfg",
                        action="store_true", default=False,
                        help="Use canned 3-element configuration")
    parser.add_argument("-s", "--secondaryBuilders", dest="secBldrs",
                        action="store_true", default=False,
                        help="Use existing secondary builders")
    parser.add_argument("-T", "--tiny", dest="tinyCfg",
                        action="store_true", default=False,
                        help="Use canned 2-element configuration")
    parser.add_argument("-t", "--icetopTrigger", dest="icetopTrig",
                        action="store_true", default=False,
                        help="Use existing icetop trigger")
    parser.add_argument("-u", "--test-subrun", dest="testSubrun",
                        action="store_true", default=False,
                        help="Test subrun")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print progress messages during run")
    parser.add_argument("-X", "--extraHubs", type=int, dest="extraHubs",
                        default=0,
                        help="Number of extra hubs to create")

    args = parser.parse_args()

    if sys.version_info > (2, 3):
        from DumpThreads import DumpThreadsOnSignal
        DumpThreadsOnSignal(fd=sys.stderr)

    if args.firstPort is not None:
        PortNumber.set_first(args.firstPort)

    if not args.keepOldFiles:
        logname = "/tmp/pdaq/log"
        for entry in os.listdir(logname):
            path = os.path.join(logname, entry)
            if os.path.isdir(path):
                shutil.rmtree(path)

        datname = "/tmp/pdaq/pdaqlocal"
        for entry in os.listdir(datname):
            path = os.path.join(datname, entry)
            if os.path.isfile(path):
                os.unlink(path)

    # get string/dom info
    def_dom_geom = DefaultDomGeometryReader.parse()

    # get list of components
    #
    if args.tinyCfg:
        comp_data = ComponentData.createTiny()
    elif args.smallCfg:
        comp_data = ComponentData.createSmall()
    else:
        comp_data = ComponentData.createAll(args.numHubs, def_dom_geom,
                                            args.fakeNames)
        for cd in comp_data:
            if args.evtBldr and cd.isComponent("eventBuilder"):
                cd.useRealComponent()
            elif args.glblTrig and cd.isComponent("globalTrigger"):
                cd.useRealComponent()
            elif args.iniceTrig and cd.isComponent("iniceTrigger"):
                cd.useRealComponent()
            elif args.icetopTrig and cd.isComponent("icetopTrigger"):
                cd.useRealComponent()
            elif args.secBldrs and cd.isComponent("secondaryBuilders"):
                cd.useRealComponent()

    args.runCfgDir = os.path.abspath(args.runCfgDir)
    if not os.path.exists(args.runCfgDir):
        os.makedirs(args.runCfgDir)
    trigSubdir = os.path.join(args.runCfgDir, "trigger")
    if not os.path.exists(trigSubdir):
        os.makedirs(trigSubdir)

    DAQFakeRun.makeMockClusterConfig(args.runCfgDir, comp_data, args.numHubs)
    mockRunCfg, _ = DAQFakeRun.makeMockRunConfig(args.runCfgDir, comp_data,
                                                 args.moniPeriod)

    if args.extraHubs <= 0:
        extraData = None
    else:
        extraData = ComponentData.create_hubs(args.extraHubs, args.numHubs + 1,
                                              args.fakeNames, False)

    # create components
    #
    try:
        comps = DAQFakeRun.create_comps(comp_data, def_dom_geom,
                                        fork_clients=args.forkClients,
                                        quiet=args.quiet)
    except socket.error, serr:
        if serr.errno != 111:
            raise
        raise SystemExit("Please start CnCServer before faking a run")

    if extraData is not None:
        extra = DAQFakeRun.create_comps(extraData, def_dom_geom,
                                        fork_clients=args.forkClients,
                                        quiet=args.quiet)

    try:
        DAQConfigParser.getClusterConfiguration(None, useActiveConfig=True,
                                                configDir=args.runCfgDir,
                                                validate=False)
    except:
        DAQFakeRun.hackActiveConfig("sim-localhost")

    # create run object and initial run number
    #
    runner = DAQFakeRun()

    runner.runAll(comps, args.runNum, args.numRuns, args.duration,
                  args.runCfgDir, mockRunCfg, verbose=args.verbose,
                  test_subrun=args.testSubrun)
