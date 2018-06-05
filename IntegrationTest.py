#!/usr/bin/env python

import datetime
import os
import shutil
import sys
import tempfile
import threading
import time
import traceback
import unittest
import xmlrpclib

from CnCServer import CnCServer, Connector
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQRPC import RPCServer
from LiveImports import Prio, LIVE_IMPORT, SERVICE_NAME
from RunOption import RunOption
from RunSet import RunData, RunSet
from TaskManager import MonitorTask, RateTask, TaskManager, WatchdogTask
from locate_pdaq import set_pdaq_config_dir
from scmversion import get_scmversion_str

try:
    from DAQLive import DAQLive
except SystemExit:
    class DAQLive(object):
        SERVICE_NAME = 'dead'

from DAQMocks \
    import MockClusterConfig, MockCnCLogger, MockDeployComponent, \
    MockIntervalTimer, MockLeapsecondFile, MockLogger, \
    MockParallelShell, RunXMLValidator, SocketReader, SocketReaderFactory, \
    SocketWriter


class LiveStub(object):
    pass


class BeanData(object):
    def __init__(self, remoteComp, bean, field, watchType, val=0,
                 increasing=True):
        self.__remoteComp = remoteComp
        self.__bean = bean
        self.__field = field
        self.__watchType = watchType
        self.__value = val
        self.__increasing = increasing

    def __str__(self):
        if self.__increasing:
            updown = '^'
        else:
            updown = 'v'
        return '%s.%s.%s<%s>%s%s' % \
            (self.__remoteComp, self.__bean, self.__field, self.__watchType,
             str(self.__value), updown)

    def getValue(self):
        return self.__value

    def setValue(self, val):
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
    def __buildComponentBeans(cls, masterList, compName):
        if compName not in masterList:
            raise Exception('Unknown component %s' % compName)

        mbeans = {}

        beanTuples = masterList[compName]
        for t in beanTuples:
            if t[1] not in mbeans:
                mbeans[t[1]] = {}

            if len(t) == 5:
                mbeans[t[1]][t[2]] = BeanData(t[0], t[1], t[2], t[3], t[4])
            elif len(t) == 6:
                mbeans[t[1]][t[2]] = BeanData(t[0], t[1], t[2], t[3], t[4],
                                              t[5])
            else:
                raise Exception('Bad bean tuple %s' % str(t))

        return mbeans

    @classmethod
    def build(cls, compName):
        with cls.LOCK:
            if compName not in cls.BEANS:
                cls.BEANS[compName] = cls.__buildComponentBeans(cls.TEMPLATE,
                                                                compName)
            return cls.BEANS[compName]

    @classmethod
    def clear(cls):
        with cls.LOCK:
            for key in cls.BEANS.keys():
                del cls.BEANS[key]


class MostlyTaskManager(TaskManager):
    WAITSECS = 0.25

    TIMERS = {}

    def __init__(self, runset, dashlog, liveMoniClient, runDir, runCfg,
                 runOptions):
        super(MostlyTaskManager, self).__init__(runset, dashlog,
                                                liveMoniClient,
                                                runDir, runCfg, runOptions)

    def createIntervalTimer(self, name, period):
        if name not in self.TIMERS:
            self.TIMERS[name] = MockIntervalTimer(name, self.WAITSECS)

        return self.TIMERS[name]

    def triggerTimer(self, name):
        if name not in self.TIMERS:
            raise Exception("Unknown timer \"%s\"" % name)

        self.TIMERS[name].trigger()


class FakeMoniClient(object):
    def __init__(self):
        pass

    def sendMoni(self, name, data, prio=None, time=None):
        pass


class MostlyRunData(RunData):
    def __init__(self, runSet, runNumber, clusterConfig, runConfig,
                 runOptions, versionInfo, spadeDir, copyDir, logDir,
                 appender=None, testing=False):
        self.__appender = appender

        self.__dashlog = None
        self.__taskMgr = None

        super(MostlyRunData, self).__init__(runSet, runNumber, clusterConfig,
                                            runConfig, runOptions,
                                            versionInfo, spadeDir, copyDir,
                                            logDir, testing=testing)

    def create_dash_log(self):
        self.__dashlog = MockCnCLogger("dash", appender=self.__appender,
                                       quiet=True, extraLoud=False)
        return self.__dashlog

    def create_moni_client(self, port):
        return FakeMoniClient()

    def create_task_manager(self, runset):
        self.__taskMgr = MostlyTaskManager(runset, self.__dashlog,
                                           self.moni_client,
                                           self.run_directory,
                                           self.run_configuration,
                                           self.run_options)
        return self.__taskMgr

    def get_event_counts(self, run_num, run_set):
        numEvts = None
        lastPayTime = None
        numMoni = None
        numSN = None
        numTCal = None

        for comp in run_set.components():
            if comp.name == "eventBuilder":
                evtData = comp.mbean.get("backEnd", "EventData")
                numEvts = evtData[1]
                lastPayTime = long(evtData[2])
            elif comp.name == "secondaryBuilders":
                for stream in ("moni", "sn", "tcal"):
                    val = comp.mbean.get(stream + "Builder", "EventData")
                    if stream == "moni":
                        numMoni = val[1]
                        moniTicks = val[2]
                    elif stream == "sn":
                        numSN = val[1]
                        snTicks = val[2]
                    elif stream == "tcal":
                        numTCal = val[1]
                        tcalTicks = val[2]

        return {
            "physicsEvents": numEvts,
            "wallTime": None,
            "eventPayloadTicks": lastPayTime,
            "moniEvents": numMoni,
            "moniTime": moniTicks,
            "snEvents": numSN,
            "snTime": snTicks,
            "tcalEvents": numTCal,
            "tcalTime": tcalTicks,
        }

    @property
    def log_directory(self):
        return None

    @property
    def task_manager(self):
        return self.__taskMgr


class MostlyRunSet(RunSet):
    LOGFACTORY = SocketReaderFactory()
    LOGDICT = {}

    def __init__(self, parent, runConfig, runset, logger, dashAppender=None):
        self.__runConfig = runConfig
        self.__dashAppender = dashAppender

        self.__runData = None

        if len(self.LOGDICT) > 0:
            raise Exception("Found %d open runset logs" % len(self.LOGDICT))

        super(MostlyRunSet, self).__init__(parent, runConfig, runset, logger)

    @classmethod
    def closeAllLogs(cls):
        for k in cls.LOGDICT.keys():
            cls.LOGDICT[k].stopServing()
            del cls.LOGDICT[k]

    @classmethod
    def create_component_log(cls, runDir, comp, host, port, liveHost,
                             livePort, quiet=True):
        if comp.fullname in cls.LOGDICT:
            return cls.LOGDICT[comp.fullname]

        log = cls.LOGFACTORY.createLog(comp.fullname, port,
                                       expectStartMsg=True)
        cls.LOGDICT[comp.fullname] = log

        log.addExpectedRegexp(r'Hello from \S+#\d+')
        log.addExpectedTextRegexp(r'Version info: \S+ \S+ \S+ \S+')

        comp.logTo(host, port, liveHost, livePort)

        return log

    def create_run_data(self, runNum, clusterConfig, runOptions, versionInfo,
                        spadeDir, copyDir=None, logDir=None, testing=True):
        self.__runData = MostlyRunData(self, runNum, clusterConfig,
                                       self.__runConfig, runOptions,
                                       versionInfo, spadeDir, copyDir,
                                       logDir, appender=self.__dashAppender,
                                       testing=True)
        return self.__runData

    def create_run_dir(self, logDir, runNum, backupExisting=True):
        pass

    @classmethod
    def getComponentLog(cls, comp):
        if comp.fullname in cls.LOGDICT:
            return cls.LOGDICT[comp.fullname]
        return None

    def getTaskManager(self):
        if self.__runData is None:
            return None
        return self.__runData.task_manager


class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbeanPort, connectors,
                                              quiet=True)

    def createLogger(self, quiet):
        return MockCnCLogger(self.fullname, appender=self.__appender,
                             quiet=quiet)


class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, clusterConfigObject, logPort, livePort, copyDir,
                 defaultLogDir, runConfigDir, daqDataDir, spadeDir):
        self.__clusterConfig = clusterConfigObject
        self.__liveOnly = logPort is None and livePort is not None
        self.__logServer = None
        self.__runset = None

        if logPort is None:
            logIP = None
        else:
            logIP = 'localhost'
        if livePort is None:
            liveIP = None
        else:
            liveIP = 'localhost'

        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              copyDir=copyDir,
                                              defaultLogDir=defaultLogDir,
                                              runConfigDir=runConfigDir,
                                              daqDataDir=daqDataDir,
                                              spadeDir=spadeDir,
                                              logIP=logIP, logPort=logPort,
                                              liveIP=liveIP, livePort=livePort,
                                              forceRestart=False, quiet=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        if self.__liveOnly:
            appender = None
        else:
            key = '%s#%d' % (name, num)
            if key not in MostlyCnCServer.APPENDERS:
                MostlyCnCServer.APPENDERS[key] = MockLogger('Mock-%s' % key)
            appender = MostlyCnCServer.APPENDERS[key]

        return MostlyDAQClient(name, num, host, port, mbeanPort, connectors,
                               appender)

    def createCnCLogger(self, quiet):
        key = 'server'
        if key not in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = \
                MockLogger('Mock-%s' % key,
                           depth=IntegrationTest.NUM_COMPONENTS)

        return MockCnCLogger(key, appender=MostlyCnCServer.APPENDERS[key],
                             quiet=quiet)

    def getClusterConfig(self, runConfig=None):
        return self.__clusterConfig

    def createRunset(self, runConfig, compList, logger):
        self.__runset = MostlyRunSet(self, runConfig, compList, logger,
                                     dashAppender=self.__dashAppender)
        return self.__runset

    def getLogServer(self):
        return self.__logServer

    def getRunSet(self):
        return self.__runset

    def monitorLoop(self):
        pass

    def openLogServer(self, port, logDir):
        self.__logServer = SocketReader("CnCDefault", port)

        msg = "Start of log at LOG=log(localhost:%d)" % port
        self.__logServer.addExpectedText(msg)
        msg = get_scmversion_str(info=self.versionInfo())
        self.__logServer.addExpectedText(msg)

        return self.__logServer

    def saveCatchall(self, runDir):
        pass

    def setDashAppender(self, dashAppender):
        self.__dashAppender = dashAppender

    def startLiveThread(self):
        return None


class RealComponent(object):
    # Component order, used in the __getOrder() method
    COMP_ORDER = {
        'stringHub': (50, 50),
        'amandaTrigger': (0, 13),
        'iceTopTrigger': (2, 12),
        'inIceTrigger': (4, 11),
        'globalTrigger': (10, 10),
        'eventBuilder': (30, 2),
        'secondaryBuilders': (32, 0),
    }

    def __init__(self, name, num, cmdPort, mbeanPort, hsDir, hsInterval,
                 hsMaxFiles, jvmPath, jvmServer, jvmHeapInit, jvmHeapMax,
                 jvmArgs, jvmExtraArgs):
        self.__id = None
        self.__name = name
        self.__num = num
        self.__hsDir = hsDir
        self.__hsInterval = hsInterval
        self.__hsMaxFiles = hsMaxFiles
        self.__jvmPath = jvmPath
        self.__jvmServer = jvmServer
        self.__jvmHeapInit = jvmHeapInit
        self.__jvmHeapMax = jvmHeapMax
        self.__jvmArgs = jvmArgs
        self.__jvmExtraArgs = jvmExtraArgs

        self.__state = 'FOO'

        self.__logger = None
        self.__liver = None

        self.__compList = None
        self.__connections = None

        self.__mbeanData = None
        self.__runData = None

        self.__firstGoodTime = None
        self.__lastGoodTime = None

        self.__version = {'filename': name, 'revision': '1', 'date': 'date',
                          'time': 'time', 'author': 'author', 'release': 'rel',
                          'repo_rev': '1234'}

        self.__cmd = RPCServer(cmdPort)
        self.__cmd.register_function(self.__commitSubrun,
                                     'xmlrpc.commitSubrun')
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__getRunData, 'xmlrpc.getRunData')
        self.__cmd.register_function(self.__getState, 'xmlrpc.getState')
        self.__cmd.register_function(self.__logTo, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__prepareSubrun,
                                     'xmlrpc.prepareSubrun')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__resetLogging,
                                     'xmlrpc.resetLogging')
        self.__cmd.register_function(self.__setFirstGoodTime,
                                     'xmlrpc.setFirstGoodTime')
        self.__cmd.register_function(self.__setLastGoodTime,
                                     'xmlrpc.setLastGoodTime')
        self.__cmd.register_function(self.__startRun, 'xmlrpc.startRun')
        self.__cmd.register_function(self.__startSubrun, 'xmlrpc.startSubrun')
        self.__cmd.register_function(self.__stopRun, 'xmlrpc.stopRun')

        tName = "RealXML*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__cmd.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__mbean = RPCServer(mbeanPort)
        self.__mbean.register_function(self.__getAttributes,
                                       'mbean.getAttributes')
        self.__mbean.register_function(self.__getMBeanValue, 'mbean.get')
        self.__mbean.register_function(self.__listGetters, 'mbean.listGetters')
        self.__mbean.register_function(self.__listMBeans, 'mbean.listMBeans')

        tName = "RealMBean*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__mbean.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__cnc = None

    def __cmp__(self, other):
        selfOrder = RealComponent.__getLaunchOrder(self.__name)
        otherOrder = RealComponent.__getLaunchOrder(other.__name)

        if selfOrder < otherOrder:
            return -1
        elif selfOrder > otherOrder:
            return 1

        if self.__num < other.__num:
            return -1
        elif self.__num > other.__num:
            return 1

        return 0

    def __repr__(self):
        return str(self)

    def __str__(self):
        return '%s#%d' % (self.__name, self.__num)

    def __commitSubrun(self, rid, latestTime):
        self.__log('Commit subrun %d: %s' % (rid, str(latestTime)))
        return 'COMMIT'

    def __configure(self, cfgName=None):
        if self.__logger is None and self.__liver is None:
            raise Exception('No logging for %s' % (str(self)))

        self.__state = 'ready'
        return 'CFG'

    def __connect(self, connList=None):
        if self.__compList is None:
            raise Exception("No component list for %s" % str(self))

        tmpDict = {}
        if connList is not None:
            for cd in connList:
                for c in self.__compList:
                    if c.isComponent(cd["compName"], cd["compNum"]):
                        tmpDict[c] = 1
                        break

        self.__connections = tmpDict.keys()

        self.__state = 'connected'
        return 'CONN'

    @classmethod
    def __fixValue(cls, obj):
        if isinstance(obj, dict):
            for k in obj:
                obj[k] = cls.__fixValue(obj[k])
        elif isinstance(obj, list):
            for i in xrange(0, len(obj)):
                obj[i] = cls.__fixValue(obj[i])
        elif isinstance(obj, tuple):
            newObj = []
            for v in obj:
                newObj.append(cls.__fixValue(v))
            obj = tuple(newObj)
        elif isinstance(obj, int) or isinstance(obj, long):
            if obj < xmlrpclib.MININT or obj > xmlrpclib.MAXINT:
                return str(obj)
        return obj

    def __getAttributes(self, bean, fldList):
        if self.__mbeanData is None:
            self.__mbeanData = DAQMBeans.build(self.__name)

        attrs = {}
        for f in fldList:
            attrs[f] = self.__mbeanData[bean][f].getValue()
        return attrs

    @classmethod
    def __getLaunchOrder(cls, name):
        if name not in cls.COMP_ORDER:
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name][0]

    def __getMBeanValue(self, bean, fld):
        if self.__mbeanData is None:
            self.__mbeanData = DAQMBeans.build(self.__name)

        val = self.__mbeanData[bean][fld].getValue()

        return self.__fixValue(val)

    def __getRunData(self, runnum):
        if self.__runData is None:
            raise Exception("RunData has not been set")
        return self.__fixValue(self.__runData)

    @classmethod
    def __getStartOrder(cls, name):
        if name not in cls.COMP_ORDER:
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name][1]

    @classmethod
    def __getOrder(cls, name):
        if name not in cls.COMP_ORDER:
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name][0]

    def __getState(self):
        return self.__state

    def __listGetters(self, bean):
        if self.__mbeanData is None:
            self.__mbeanData = DAQMBeans.build(self.__name)

        k = self.__mbeanData[bean].keys()
        k.sort()
        return k

    def __listMBeans(self):
        if self.__mbeanData is None:
            self.__mbeanData = DAQMBeans.build(self.__name)

        k = self.__mbeanData.keys()
        k.sort()
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

    def __logTo(self, logHost, logPort, liveHost, livePort):
        if logHost == '':
            logHost = None
        if logPort == 0:
            logPort = None
        if logHost is not None and logPort is not None:
            self.__logger = SocketWriter(logHost, logPort)
        else:
            self.__logger = None

        if liveHost == '':
            liveHost = None
        if livePort == 0:
            livePort = None
        if liveHost is not None and livePort is not None:
            self.__liver = SocketWriter(liveHost, livePort)
        else:
            self.__liver = None

        self.__log('Hello from %s' % str(self))
        return 'OK'

    def __prepareSubrun(self, rid):
        self.__log('Prep subrun %d' % rid)
        return 'PREP'

    def __reset(self):
        self.__state = 'idle'
        return 'RESET'

    def __resetLogging(self):
        self.__logger = None

        return 'RLOG'

    def __setFirstGoodTime(self, payTime):
        self.__firstGoodTime = payTime
        return "OK"

    def __setLastGoodTime(self, payTime):
        self.__lastGoodTime = payTime
        return "OK"

    def __startRun(self, runNum):
        if self.__connections is None:
            print >>sys.stderr, "Component %s has no connections" % str(self)
        elif self.__name != "eventBuilder":
            for c in self.__connections:
                if c.getState() != 'running':
                    print >>sys.stderr, ("Comp %s is running before %s" %
                                         (str(c), str(self)))

        self.__state = 'running'
        return 'RUN#%d' % runNum

    def __startSubrun(self, data):
        self.__log('Start subrun %s' % str(data))
        return long(time.time())

    def __stopRun(self):
        self.__log('Stop %s' % str(self))

        if self.__connections is None:
            print >>sys.stderr, "Component %s has no connections" % str(self)
        elif self.__name != "eventBuilder":
            for c in self.__connections:
                if c.getState() == 'stopped':
                    print >>sys.stderr, ("Comp %s is stopped before %s" %
                                         (str(c), str(self)))

        self.__state = 'ready'
        return 'STOP'

    def addI3LiveMonitoring(self, liveLog, useMBeanData=True):
        if self.__mbeanData is None:
            self.__mbeanData = DAQMBeans.build(self.__name)

        beanKeys = self.__mbeanData.keys()
        beanKeys.sort()
        for bean in beanKeys:
            for fld in self.__mbeanData[bean]:
                name = '%s-%d*%s+%s' % (self.__name, self.__num, bean, fld)

                val = None
                if not useMBeanData and bean == "backEnd":
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
                    val = self.__mbeanData[bean][fld].getValue()

                if bean == "backEnd" and fld == "EventData":
                    fldtype = "json"
                else:
                    fldtype = None

                liveLog.addExpectedLiveMoni(name, val, fldtype)

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

    def connectToCnC(self):
        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER)

    @property
    def fullname(self):
        if self.__num == 0 and not self.__name.lower().endswith("hub"):
            return self.__name

        return "%s#%d" % (self.__name, self.__num)

    def getCommandPort(self):
        return self.__cmd.portnum

    def getId(self):
        return 999

    def getMBean(self, bean, fld):
        if self.__mbeanData is None:
            self.__mbeanData = DAQMBeans.build(self.__name)

        return self.__mbeanData[bean][fld].getValue()

    def getMBeanPort(self):
        return self.__mbean.portnum

    def getName(self):
        return self.__name

    def getNumber(self):
        return self.__num

    def getState(self):
        return self.__getState()

    @property
    def hitspoolDirectory(self):
        return self.__hsDir

    @property
    def hitspoolInterval(self):
        return self.__hsInterval

    @property
    def hitspoolMaxFiles(self):
        return self.__hsMaxFiles

    def isComponent(self, name, num=-1):
        return self.__name == name and (num < 0 or self.__num == num)

    @property
    def jvmArgs(self):
        return self.__jvmArgs

    @property
    def jvmExtraArgs(self):
        return self.__jvmExtraArgs

    @property
    def jvmHeapInit(self):
        return self.__jvmHeapInit

    @property
    def jvmHeapMax(self):
        return self.__jvmHeapMax

    @property
    def jvmPath(self):
        return self.__jvmPath

    @property
    def jvmServer(self):
        return self.__jvmServer

    def logTo(self, logHost, logPort, liveHost, livePort):
        return self.__logTo(logHost, logPort, liveHost, livePort)

    def register(self, connList):
        reg = self.__cnc.rpc_component_register(self.__name, self.__num,
                                                'localhost',
                                                self.__cmd.portnum,
                                                self.__mbean.portnum,
                                                connList)
        if not isinstance(reg, dict):
            raise Exception('Expected registration to return dict, not %s' %
                            str(type(reg)))

        numElems = 6
        if len(reg) != numElems:
            raise Exception(('Expected registration to return %d-element' +
                             ' dictionary, not %d') % (numElems, len(reg)))

        self.__id = reg["id"]

        self.__logTo(reg["logIP"], reg["logPort"], reg["liveIP"],
                     reg["livePort"])

    def setComponentList(self, compList):
        self.__compList = compList

    def setMBean(self, bean, fld, val):
        if self.__mbeanData is None:
            self.__mbeanData = DAQMBeans.build(self.__name)

        self.__mbeanData[bean][fld].setValue(val)

    def setRunData(self, val0, val1, val2, val3=None, val4=None):
        if val3 is None and val4 is None:
            self.__runData = (long(val0), long(val1), long(val2))
        else:
            self.__runData = (long(val0), long(val1), long(val2), long(val3),
                              long(val4))

    @staticmethod
    def sortForLaunch(y, x):
        selfOrder = RealComponent.__getLaunchOrder(x.__name)
        otherOrder = RealComponent.__getLaunchOrder(y.__name)

        if selfOrder < otherOrder:
            return -1
        elif selfOrder > otherOrder:
            return 1

        if x.__num < y.__num:
            return 1
        elif x.__num > y.__num:
            return -1

        return 0

    @staticmethod
    def sortForStart(y, x):
        selfOrder = RealComponent.__getStartOrder(x.__name)
        otherOrder = RealComponent.__getStartOrder(y.__name)

        if selfOrder < otherOrder:
            return -1
        elif selfOrder > otherOrder:
            return 1

        if x.__num < y.__num:
            return 1
        elif x.__num > y.__num:
            return -1

        return 0


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

    RUNNING = False

    def __createComponents(self):
        hsDir = "/mnt/data/nowhere"
        hsInterval = 15.0
        hsMaxFiles = 18000

        # Note that these jvmPath/jvmArg values needs to correspond to
        # what would be used by the config in 'sim-localhost'
        jvmPath = 'java'
        jvmServer = True
        jvmHeapInit = None
        jvmHeapMax = "512m"
        jvmArgs = None
        jvmExtra = None
        comps = [('stringHub', 1001, 9111, 9211, hsDir, hsInterval,
                  hsMaxFiles, jvmPath, jvmServer, jvmHeapInit, jvmHeapMax,
                  jvmArgs, jvmExtra),
                 ('stringHub', 1002, 9112, 9212, hsDir, hsInterval,
                  hsMaxFiles, jvmPath, jvmServer,
                  jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra),
                 ('stringHub', 1003, 9113, 9213, hsDir, hsInterval,
                  hsMaxFiles, jvmPath, jvmServer,
                  jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra),
                 ('stringHub', 1004, 9114, 9214, hsDir, hsInterval,
                  hsMaxFiles, jvmPath, jvmServer,
                  jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra),
                 ('stringHub', 1005, 9115, 9215, hsDir, hsInterval,
                  hsMaxFiles, jvmPath, jvmServer,
                  jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra),
                 ('inIceTrigger', 0, 9117, 9217, None, None, None, jvmPath,
                  jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra),
                 ('globalTrigger', 0, 9118, 9218, None, None, None, jvmPath,
                  jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra),
                 ('eventBuilder', 0, 9119, 9219, None, None, None, jvmPath,
                  jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra),
                 ('secondaryBuilders', 0, 9120, 9220, None, None, None,
                  jvmPath, jvmServer, jvmHeapInit, jvmHeapMax, jvmArgs,
                  jvmExtra)]

        if len(comps) != IntegrationTest.NUM_COMPONENTS:
            raise Exception("Expected %d components, not %d" %
                            (IntegrationTest.NUM_COMPONENTS, len(comps)))

        for c in comps:
            comp = RealComponent(c[0], c[1], c[2], c[3], c[4], c[5], c[6],
                                 c[7], c[8], c[9], c[10], c[11], c[12])

            if self.__compList is None:
                self.__compList = []
            self.__compList.append(comp)
            comp.setComponentList(self.__compList)

        self.__compList.sort()

    def __createLiveObjects(self, livePort):
        numComps = IntegrationTest.NUM_COMPONENTS * 2
        log = self.__logFactory.createLog('liveMoni', DAQPort.I3LIVE, False,
                                          depth=numComps)

        log.addExpectedText('Connecting to DAQRun')
        log.addExpectedText('Started %s service on port %d' %
                            (SERVICE_NAME, livePort))

        self.__live = LiveStub(livePort)

        return (self.__live, log)

    def __createLoggers(self, runOptions, liveRunOnly):
        if not RunOption.isLogToFile(runOptions) and not liveRunOnly:
            appender = None
        else:
            appender = MockLogger('main',
                                  depth=IntegrationTest.NUM_COMPONENTS)

        dashLog = MockLogger("dash")
        return (appender, dashLog)

    def __createParallelShell(self, logPort, livePort):
        pShell = MockParallelShell()

        doCnC = True
        verbose = False
        killWith9 = False

        dashDir = pShell.getMetaPath('dash')

        host = 'localhost'

        logLevel = 'INFO'

        pShell.addExpectedPythonKill(doCnC, killWith9)

        launchList = self.__compList[:]
        launchList.sort(RealComponent.sortForLaunch)

        for comp in launchList:
            pShell.addExpectedJavaKill(comp.getName(), comp.getNumber(),
                                       killWith9, verbose, host)

        pShell.addExpectedPython(doCnC, dashDir, IntegrationTest.CONFIG_DIR,
                                 IntegrationTest.LOG_DIR,
                                 IntegrationTest.DATA_DIR,
                                 IntegrationTest.SPADE_DIR,
                                 None,
                                 IntegrationTest.CONFIG_NAME,
                                 IntegrationTest.COPY_DIR, logPort, livePort)
        for comp in launchList:
            deployComp = MockDeployComponent(comp.getName(), comp.getNumber(),
                                             logLevel, comp.hitspoolDirectory,
                                             comp.hitspoolInterval,
                                             comp.hitspoolMaxFiles,
                                             comp.jvmPath, comp.jvmServer,
                                             comp.jvmHeapInit,
                                             comp.jvmHeapMax, comp.jvmArgs,
                                             comp.jvmExtraArgs, None, None)
            pShell.addExpectedJava(deployComp, IntegrationTest.CONFIG_DIR,
                                   IntegrationTest.DATA_DIR,
                                   DAQPort.CATCHALL, livePort, verbose, False,
                                   host)

        return pShell

    def __createRunObjects(self, runOptions, liveRunOnly=False):

        (appender, dashLog) = \
            self.__createLoggers(runOptions, liveRunOnly)

        self.__createComponents()

        cluCfg = MockClusterConfig(IntegrationTest.CLUSTER_CONFIG,
                                   IntegrationTest.CLUSTER_DESC)
        for c in self.__compList:
            cluCfg.addComponent(c.fullname, c.jvmPath, c.jvmArgs,
                                "localhost")

        if RunOption.isLogToFile(runOptions) or liveRunOnly:
            logPort = DAQPort.CATCHALL
        else:
            logPort = None
        if RunOption.isLogToLive(runOptions) and not liveRunOnly:
            livePort = DAQPort.I3LIVE
        else:
            livePort = None

        self.__cnc = MostlyCnCServer(cluCfg, None, livePort, self.COPY_DIR,
                                     self.LOG_DIR, self.CONFIG_DIR,
                                     self.DATA_DIR, self.SPADE_DIR)
        self.__cnc.setDashAppender(dashLog)

        if liveRunOnly:
            paraLivePort = None
        else:
            paraLivePort = livePort
        pShell = \
            self.__createParallelShell(logPort, paraLivePort)

        return (self.__cnc, appender, dashLog, pShell)

    def __forceMonitoring(self, cnc, liveMoni):
        taskMgr = cnc.getRunSet().getTaskManager()

        if liveMoni is not None:
            liveMoni.setCheckDepth(32)
            for c in self.__compList:
                c.addI3LiveMonitoring(liveMoni)

        taskMgr.triggerTimer(MonitorTask.NAME)
        time.sleep(MostlyTaskManager.WAITSECS)
        taskMgr.waitForTasks()

        if liveMoni is not None:
            self.__waitForEmptyLog(liveMoni, "Didn't get moni messages")

    def __forceRate(self, cnc, dashLog, runNum):
        taskMgr = cnc.getRunSet().getTaskManager()

        self.__setBeanData("eventBuilder", 0, "backEnd", "EventData",
                           [runNum, 0, 0])
        self.__setBeanData("eventBuilder", 0, "backEnd", "FirstEventTime", 0)
        self.__setBeanData("eventBuilder", 0, "backEnd", "GoodTimes", [0, 0])
        for bldr in ("moni", "sn", "tcal"):
            self.__setBeanData("secondaryBuilders", 0, bldr + "Builder",
                               "EventData", [runNum, 0, 0])

        dashLog.addExpectedRegexp(r"\s*0 physics events, 0 moni events," +
                                  r" 0 SN events, 0 tcals")

        taskMgr.triggerTimer(RateTask.NAME)
        time.sleep(MostlyTaskManager.WAITSECS)
        taskMgr.waitForTasks()

        self.__waitForEmptyLog(dashLog, "Didn't get rate message")

        numEvts = 5
        firstTime = 5000
        curTime = 20000000000 + firstTime

        self.__setBeanData("eventBuilder", 0, "backEnd", "EventData",
                           [runNum, numEvts, curTime])
        self.__setBeanData("eventBuilder", 0, "backEnd", "FirstEventTime",
                           firstTime)
        self.__setBeanData("eventBuilder", 0, "backEnd", "GoodTimes",
                           [firstTime, curTime])

        duration = (curTime - firstTime) / 10000000000
        if duration <= 0:
            hzStr = ""
        else:
            hzStr = " (%2.2f Hz)" % (float(numEvts - 1) / float(duration))

        dashLog.addExpectedExact(("	%d physics events%s, 0 moni events," +
                                  " 0 SN events, 0 tcals") % (numEvts, hzStr))

        taskMgr.triggerTimer(RateTask.NAME)
        time.sleep(MostlyTaskManager.WAITSECS)
        taskMgr.waitForTasks()

        self.__waitForEmptyLog(dashLog, "Didn't get second rate message")

    def __forceWatchdog(self, cnc, dashLog):
        taskMgr = cnc.getRunSet().getTaskManager()

        self.__setBeanData("eventBuilder", 0, "backEnd", "DiskAvailable", 0)

        for idx in range(5):
            if idx >= 3:
                dashLog.addExpectedRegexp(r"Watchdog reports starved"
                                          r" components.*")
                dashLog.addExpectedRegexp(r"Watchdog reports stagnant"
                                          r" components.*")
                dashLog.addExpectedRegexp(r"Watchdog reports threshold"
                                          r" components.*")

            taskMgr.triggerTimer(WatchdogTask.NAME)
            time.sleep(MostlyTaskManager.WAITSECS)
            taskMgr.waitForTasks()

    def __getConnectionList(self, name):
        if name == 'stringHub':
            connList = [
                ('moniData', Connector.OUTPUT, -1),
                ('rdoutData', Connector.OUTPUT, -1),
                ('rdoutReq', Connector.INPUT, -1),
                ('snData', Connector.OUTPUT, -1),
                ('tcalData', Connector.OUTPUT, -1),
                ('stringHit', Connector.OUTPUT, -1),
            ]
        elif name == 'inIceTrigger':
            connList = [
                ('stringHit', Connector.INPUT, -1),
                ('trigger', Connector.OUTPUT, -1),
            ]
        elif name == 'globalTrigger':
            connList = [
                ('glblTrig', Connector.OUTPUT, -1),
                ('trigger', Connector.INPUT, -1),
            ]
        elif name == 'eventBuilder':
            connList = [
                ('glblTrig', Connector.INPUT, -1),
                ('rdoutData', Connector.INPUT, -1),
                ('rdoutReq', Connector.OUTPUT, -1),
            ]
        elif name == 'secondaryBuilders':
            connList = [
                ('moniData', Connector.INPUT, -1),
                ('snData', Connector.INPUT, -1),
                ('tcalData', Connector.INPUT, -1),
            ]
        else:
            raise Exception('Cannot get connection list for %s' % name)

        return connList

    def __registerComponents(self, liveLog, logServer, liveRunOnly):
        for comp in self.__compList:
            if logServer is not None:
                logServer.addExpectedText("Registered %s" % (comp.fullname, ))
                logServer.addExpectedExact('Hello from %s' % (comp, ))
            if liveLog is not None and not liveRunOnly:
                liveLog.addExpectedText('Registered %s' % (comp.fullname, ))
                liveLog.addExpectedText('Hello from %s' % (comp, ))
            comp.register(self.__getConnectionList(comp.getName()))

    def __runTest(self, live, cnc, liveLog, appender, dashLog, runOptions,
                  liveRunOnly):

        try:
            self.__testBody(live, cnc, liveLog, appender, dashLog, runOptions,
                            liveRunOnly)
        finally:
            time.sleep(0.4)

            cnc.closeServer()

            self.RUNNING = False

    def __setBeanData(self, compName, compNum, beanName, fieldName, value):
        setData = False
        for c in self.__compList:
            if c.getName() == compName and c.getNumber() == compNum:
                c.setMBean(beanName, fieldName, value)
                setData = True
                break

        if not setData:
            raise Exception("Could not find component %s#%d" %
                            (compName, compNum))

    def __setRunData(self, numEvts, startEvtTime, lastEvtTime, numTcal, numSN,
                     numMoni, firstGood, lastGood):
        for c in self.__compList:
            if c.getName() == "eventBuilder":
                c.setRunData(numEvts, startEvtTime, lastEvtTime, firstGood,
                             lastGood)
            elif c.getName() == "secondaryBuilders":
                c.setRunData(numTcal, numSN, numMoni)

    def __testBody(self, live, cnc, liveLog, appender, dashLog, runOptions,
                   liveRunOnly):
        for c in self.__compList:
            c.connectToCnC()

        logServer = cnc.getLogServer()

        RUNLOG_INFO = False

        if liveLog:
            liveLog.checkStatus(10)
        if appender:
            appender.checkStatus(10)
        if dashLog:
            dashLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        self.__registerComponents(liveLog, logServer, liveRunOnly)

        time.sleep(0.4)

        if liveLog:
            liveLog.checkStatus(10)
        if appender:
            appender.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        setId = RunSet.ID_SOURCE.peekNext()
        runNum = 654
        configName = IntegrationTest.CONFIG_NAME

        if liveLog:
            liveLog.addExpectedText('Starting run %d - %s' %
                                    (runNum, configName))

        if RUNLOG_INFO:
            if liveLog:
                liveLog.addExpectedText('Loading run configuration "%s"' %
                                        configName)
                liveLog.addExpectedText('Loaded run configuration "%s"' %
                                        configName)

            for n in ('in-ice', 'icetop'):
                msg = 'Configuration includes detector %s' % n
                if liveLog:
                    liveLog.addExpectedText(msg)

            for c in self.__compList:
                msg = 'Component list will require %s#%d' % \
                    (c.getName(), c.getNumber())
                if liveLog:
                    liveLog.addExpectedText(msg)

        for s in ("Loading", "Loaded"):
            msg = '%s run configuration "%s"' % (s, configName)
            if liveLog and not liveRunOnly:
                liveLog.addExpectedText(msg)
            if logServer:
                logServer.addExpectedText(msg)

        msg = r'Built runset #\d+: .*'
        if liveLog and not liveRunOnly:
            liveLog.addExpectedTextRegexp(msg)
        if logServer:
            logServer.addExpectedTextRegexp(msg)

        msg = 'Created Run Set #%d' % setId
        if liveLog:
            liveLog.addExpectedText(msg)

        msgList = [
            ('Version info: ' +
             get_scmversion_str(info=cnc.versionInfo())),
            'Starting run %d...' % runNum,
            'Run configuration: %s' % configName
        ]
        if RUNLOG_INFO:
            msgList.append('Created logger for CnCServer')

        if liveLog:
            for msg in msgList:
                liveLog.addExpectedText(msg)

            liveLog.addExpectedRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
            liveLog.addExpectedRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        if dashLog:
            dashLog.addExpectedRegexp(r'Version info: \S+ \S+ \S+ \S+')
            dashLog.addExpectedExact('Run configuration: %s' % configName)
            dashLog.addExpectedExact("Cluster: " +
                                     IntegrationTest.CLUSTER_DESC)

        if liveLog:
            keys = self.__compList[:]
            keys.sort(RealComponent.sortForStart)

            for c in keys:
                liveLog.addExpectedText('Hello from %s' % str(c))
                liveLog.addExpectedTextRegexp(r'Version info: %s \S+ \S+ \S+' %
                                              c.getName())

        if RUNLOG_INFO:
            msg = 'Configuring run set...'
            if appender and not liveRunOnly:
                appender.addExpectedExact(msg)
            if liveLog:
                liveLog.addExpectedText(msg)

            if RunOption.isMoniToFile(runOptions):
                runDir = os.path.join(IntegrationTest.LOG_DIR,
                                      str(runNum))
                for c in self.__compList:
                    msg = ('Creating moni output file %s/%s-%d.moni' +
                           ' (remote is localhost:%d)') % \
                           (runDir, c.getName(), c.getNumber(),
                            c.getMBeanPort())
                    if appender and not liveRunOnly:
                        appender.addExpectedExact(msg)
                    if liveLog:
                        liveLog.addExpectedText(msg)

        msg = "Starting run #%d on \"%s\"" % \
            (runNum, IntegrationTest.CLUSTER_DESC)
        if liveLog and not liveRunOnly:
            liveLog.addExpectedText(msg)
        if logServer:
            logServer.addExpectedText(msg)

        if dashLog:
            dashLog.addExpectedExact("Starting run %d..." % runNum)

        if logServer:
            logServer.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds"
                                            r" for NonHubs")
            logServer.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds"
                                            r" for Hubs")

        if liveLog:
            for c in self.__compList:
                liveLog.addExpectedText('Start #%d on %s' % (runNum, str(c)))

        msg = 'Started run %d on run set %d' % (runNum, setId)
        if liveLog:
            liveLog.addExpectedText(msg)

        startEvtTime = 1001

        if liveLog:
            liveLog.addExpectedTextRegexp(r"DAQ state is RUNNING after \d+" +
                                          " seconds")
            liveLog.addExpectedText('Started run %d' % runNum)

        if live is not None:
            live.starting({'runNumber': runNum, 'runConfig': configName})
        else:
            id = cnc.rpc_runset_make(configName, runNum)
            self.assertEqual(setId, id,
                             "Expected to create runset #%d, not #%d" %
                             (setId, id))
            cnc.rpc_runset_start_run(setId, runNum, RunOption.LOG_TO_FILE)

        self.__waitForState(cnc, setId, "running")

        if liveLog:
            liveLog.checkStatus(10)
        if appender:
            appender.checkStatus(500)
        if dashLog:
            dashLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        if RunOption.isMoniToLive(runOptions):
            # monitoring values can potentially come in any order
            liveLog.setCheckDepth(32)
            for c in self.__compList:
                c.addI3LiveMonitoring(liveLog)

        if liveLog:
            activeDOMMap = {}
            for c in self.__compList:
                if c.isComponent("stringHub"):
                    activeDOMMap[str(c.getNumber())] = 0
            liveLog.addExpectedLiveMoni("activeDOMs", 0)
            liveLog.addExpectedLiveMoni("expectedDOMs", 0)
            liveLog.addExpectedLiveMoni("activeStringDOMs", activeDOMMap,
                                        "json")
        self.__forceMonitoring(cnc, liveLog)

        if liveLog:
            liveLog.checkStatus(10)
        if appender:
            appender.checkStatus(500)
        if dashLog:
            dashLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        self.__forceRate(cnc, dashLog, runNum)

        if liveLog:
            liveLog.checkStatus(10)
        if appender:
            appender.checkStatus(500)
        if dashLog:
            dashLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        self.__forceWatchdog(cnc, dashLog)

        if liveLog:
            liveLog.checkStatus(10)
        if appender:
            appender.checkStatus(500)
        if dashLog:
            dashLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        if RunOption.isMoniToLive(runOptions):
            liveLog.setCheckDepth(5)

        subRunId = 1

        if liveLog:
            liveLog.addExpectedText('Starting subrun %d.%d' %
                                    (runNum, subRunId))

        domList = [['53494d550101', 0, 1, 2, 3, 4],
                   ['1001', '22', 1, 2, 3, 4, 5],
                   ('a', 0, 1, 2, 3, 4)]

        rawFlashList = []
        rpcFlashList = []
        for i in range(len(domList)):
            if i == 0:
                rawFlashList.append(domList[0])

                data = []
                data += domList[0][:]
                rpcFlashList.append(data)
            elif i == 1:
                data = ['53494d550122', ]
                data += domList[1][2:]
                rawFlashList.append(data)
                rpcFlashList.append(data)
            else:
                break

        msg = "Subrun %d: ignoring missing DOM ['#%s']" % \
              (subRunId, domList[2][0])
        if dashLog:
            dashLog.addExpectedExact(msg)

        fmt = 'Subrun %d: flashing DOM (%%s)' % subRunId
        if dashLog:
            dashLog.addExpectedExact(fmt % str(rpcFlashList))

        for c in self.__compList:
            if not appender or liveRunOnly:
                clog = None
            else:
                clog = MostlyRunSet.getComponentLog(c)
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (c.getName(), c.getNumber()))

            if c.getName() == 'eventBuilder':
                msg = 'Prep subrun %d' % subRunId
                if clog:
                    clog.addExpectedExact(msg)
                if liveLog:
                    liveLog.addExpectedText(msg)

            if c.getName() == 'stringHub':
                msg = 'Start subrun %s' % str(rpcFlashList)
                if clog:
                    clog.addExpectedExact(msg)
                if liveLog:
                    liveLog.addExpectedText(msg)

            if c.getName() == 'eventBuilder':
                patStr = r'Commit subrun %d: \d+' % subRunId
                if clog:
                    clog.addExpectedRegexp(patStr)
                if liveLog:
                    liveLog.addExpectedTextRegexp(patStr)

        if live is not None:
            live.subrun(subRunId, domList)
        else:
            cnc.rpc_runset_subrun(setId, subRunId, domList)

        if dashLog:
            dashLog.checkStatus(10)
        if appender:
            appender.checkStatus(10)
        if liveLog:
            liveLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        subRunId += 1

        if liveLog:
            liveLog.addExpectedText('Stopping subrun %d.%d' %
                                    (runNum, subRunId))

        msg = 'Subrun %d: stopping flashers' % subRunId
        if dashLog:
            dashLog.addExpectedExact(msg)

        for c in self.__compList:
            if not appender or liveRunOnly:
                clog = None
            else:
                clog = MostlyRunSet.getComponentLog(c)
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (c.getName(), c.getNumber()))

            if c.getName() == 'eventBuilder':
                msg = 'Prep subrun %d' % subRunId
                if clog:
                    clog.addExpectedExact(msg)
                if liveLog:
                    liveLog.addExpectedText(msg)

            if c.getName() == 'stringHub':
                msg = 'Start subrun %s' % str([])
                if clog:
                    clog.addExpectedExact(msg)
                if liveLog:
                    liveLog.addExpectedText(msg)

            if c.getName() == 'eventBuilder':
                patStr = r'Commit subrun %d: \d+' % subRunId
                if clog:
                    clog.addExpectedRegexp(patStr)
                if liveLog:
                    liveLog.addExpectedTextRegexp(patStr)

        if live is not None:
            live.subrun(subRunId, [])
        else:
            cnc.rpc_runset_subrun(setId, subRunId, [])

        if dashLog:
            dashLog.checkStatus(10)
        if appender:
            appender.checkStatus(10)
        if liveLog:
            liveLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        if liveLog:
            liveLog.addExpectedText('Stopping run %d' % runNum)

        domTicksPerSec = 10000000000

        numEvts = 17
        numMoni = 222
        moniTicks = 0L
        numSN = 51
        snTicks = 0L
        numTcal = 93
        tcalTicks = 0L
        lastEvtTime = startEvtTime + (domTicksPerSec * 3)

        self.__setBeanData("eventBuilder", 0, "backEnd", "NumEventsSent",
                           numEvts)
        self.__setBeanData("eventBuilder", 0, "backEnd", "NumEventsDispatched",
                           numEvts)
        self.__setBeanData("eventBuilder", 0, "backEnd", "EventData",
                           [runNum, numEvts, lastEvtTime])
        self.__setBeanData("eventBuilder", 0, "backEnd", "FirstEventTime",
                           startEvtTime)
        self.__setBeanData("eventBuilder", 0, "backEnd", "GoodTimes",
                           (startEvtTime, lastEvtTime))
        self.__setBeanData("secondaryBuilders", 0, "moniBuilder",
                           "NumDispatchedData", numMoni)
        self.__setBeanData("secondaryBuilders", 0, "moniBuilder",
                           "EventData", (runNum, numMoni, moniTicks))
        self.__setBeanData("secondaryBuilders", 0, "snBuilder",
                           "NumDispatchedData", numSN)
        self.__setBeanData("secondaryBuilders", 0, "snBuilder",
                           "EventData", (runNum, numSN, snTicks))
        self.__setBeanData("secondaryBuilders", 0, "tcalBuilder",
                           "NumDispatchedData", numTcal)
        self.__setBeanData("secondaryBuilders", 0, "tcalBuilder",
                           "EventData", (runNum, numTcal, tcalTicks))

        self.__setRunData(numEvts, startEvtTime, lastEvtTime, numTcal, numSN,
                          numMoni, startEvtTime, lastEvtTime)

        msg = 'Stopping run %d' % runNum
        if liveLog:
            liveLog.addExpectedText(msg)

        for c in self.__compList:
            if not appender or liveRunOnly:
                clog = None
            else:
                clog = MostlyRunSet.getComponentLog(c)
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (c.getName(), c.getNumber()))

            msg = 'Stop %s#%d' % (c.getName(), c.getNumber())
            if clog:
                clog.addExpectedExact(msg)
            if liveLog:
                liveLog.addExpectedText(msg)

        patStr = (r'%d physics events collected in -?\d+ seconds' +
                  r'(\s+\(-?\d+\.\d+ Hz\))?') % numEvts
        dashLog.addExpectedRegexp(patStr)
        if liveLog:
            liveLog.addExpectedTextRegexp(patStr)

        msg = '%d moni events, %d SN events, %d tcals' % \
            (numMoni, numSN, numTcal)
        dashLog.addExpectedExact(msg)
        if liveLog:
            liveLog.addExpectedText(msg)

        if RUNLOG_INFO:
            msg = 'Stopping component logging'
            if appender and not liveRunOnly:
                appender.addExpectedExact(msg)
            if liveLog:
                liveLog.addExpectedText(msg)

            patStr = 'RPC Call stats:.*'
            if appender and not liveRunOnly:
                appender.addExpectedRegexp(patStr)
            if liveLog:
                liveLog.addExpectedTextRegexp(patStr)

        msg = 'Run terminated SUCCESSFULLY.'
        dashLog.addExpectedExact(msg)
        if liveLog:
            liveLog.addExpectedText(msg)

        dashLog.addExpectedExact("Not logging to file so cannot queue to"
                                 " SPADE")

        if liveLog:
            liveLog.addExpectedTextRegexp(r"DAQ state is STOPPED after \d+" +
                                          " seconds")
            liveLog.addExpectedText('Stopped run %d' % runNum)

        if live is not None:
            live.stopping()
        else:
            cnc.rpc_runset_stop_run(setId)

        self.__waitForState(cnc, setId, "ready")

        if dashLog:
            dashLog.checkStatus(10)
        if appender:
            appender.checkStatus(10)
        if liveLog:
            liveLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        cnc.updateRates(setId)

        moni = cnc.rpc_runset_monitor_run(setId, runNum)
        self.assertFalse(moni is None, 'rpc_run_monitoring returned None')
        self.assertFalse(len(moni) == 0, 'rpc_run_monitoring returned no data')
        self.assertEqual(numEvts, moni['physicsEvents'],
                         'Expected %d physics events, not %d' %
                         (numEvts, moni['physicsEvents']))
        self.assertEqual(numMoni, moni['moniEvents'],
                         'Expected %d moni events, not %d' %
                         (numMoni, moni['moniEvents']))
        self.assertEqual(numSN, moni['snEvents'],
                         'Expected %d sn events, not %d' %
                         (numSN, moni['snEvents']))
        self.assertEqual(numTcal, moni['tcalEvents'],
                         'Expected %d tcal events, not %d' %
                         (numTcal, moni['tcalEvents']))

        if dashLog:
            dashLog.checkStatus(10)
        if appender:
            appender.checkStatus(10)
        if liveLog:
            liveLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

        RunXMLValidator.validate(self, runNum, configName,
                                 IntegrationTest.CLUSTER_DESC, None, None,
                                 numEvts, numMoni, numSN, numTcal, False)

        if RUNLOG_INFO:
            msg = 'Breaking run set...'
            if liveLog and not liveRunOnly:
                liveLog.addExpectedText(msg)

        if live is not None:
            live.release()
        else:
            cnc.rpc_runset_break(setId)

        if dashLog:
            dashLog.checkStatus(10)
        if appender:
            appender.checkStatus(10)
        if liveLog:
            liveLog.checkStatus(10)
        if logServer:
            logServer.checkStatus(10)

    @staticmethod
    def __waitForEmptyLog(log, errMsg):
        for _ in range(5):
            if log.isEmpty:
                break
            time.sleep(0.25)
        log.checkStatus(1)

    def __waitForState(self, cnc, setId, expState):
        numTries = 0
        state = 'unknown'
        while numTries < 500:
            state = cnc.rpc_runset_state(setId)
            if state == expState:
                break
            time.sleep(0.1)
            numTries += 1
        self.assertEqual(expState, state, 'Should be %s, not %s' %
                         (expState, state))

    def setUp(self):
        if sys.version_info < (2, 7):
            self.setUpClass()

        MostlyCnCServer.APPENDERS.clear()
        DAQMBeans.clear()

        self.__logFactory = SocketReaderFactory()

        IntegrationTest.LOG_DIR = tempfile.mkdtemp()

        DAQLive.STATE_WARNING = False

        self.__live = None
        self.__cnc = None
        self.__compList = None

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
            self.__logFactory.tearDown()
        except:
            traceback.print_exc()

        if self.__compList is not None and len(self.__compList) > 0:
            for c in self.__compList:
                c.close()
        if self.__cnc is not None:
            self.__cnc.closeServer()
        if self.__live is not None:
            self.__live.close()

        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].checkStatus(10)

        MostlyRunSet.closeAllLogs()

        shutil.rmtree(IntegrationTest.LOG_DIR, ignore_errors=True)
        IntegrationTest.LOG_DIR = None

        if False:
            reps = 5
            for n in range(reps):
                if threading.activeCount() < 2:
                    break

                needHdr = True
                for t in threading.enumerate():
                    if t.getName() == "MainThread":
                        continue

                    if needHdr:
                        print >>sys.stderr, "---- Active threads #%d" % \
                            (reps - n)
                        needHdr = False
                    print >>sys.stderr, "  %s" % t

                time.sleep(1)

            if threading.activeCount() > 1:
                print >>sys.stderr, \
                    "tearDown exiting with %d active threads" % \
                    threading.activeCount()

        RunXMLValidator.tearDown()

        if sys.version_info < (2, 7):
            self.tearDownClass()

    def testFinishInMain(self):
        runOptions = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        (cnc, appender, dashLog, pShell) = \
            self.__createRunObjects(runOptions)

        t = threading.Thread(name="MainFinish", target=cnc.run, args=())
        t.setDaemon(True)
        t.start()

        self.__runTest(None, cnc, None, appender, dashLog, runOptions, False)

    def testCnCInMain(self):
        runOptions = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        (cnc, appender, dashLog, pShell) = self.__createRunObjects(runOptions)

        t = threading.Thread(name="CnCFinish", target=self.__runTest,
                             args=(None, cnc, None, appender, dashLog,
                                   runOptions, False))
        t.setDaemon(True)
        t.start()

        cnc.run()

    def testLiveFinishInMain(self):
        print "Not running testLiveFinishInMain"
        return
        # from DAQMocks import LogChecker; LogChecker.DEBUG = True
        if not LIVE_IMPORT:
            print 'Skipping I3Live-related test'
            return

        livePort = 9751

        runOptions = RunOption.LOG_TO_LIVE | RunOption.MONI_TO_FILE

        (cnc, appender, dashLog, pShell) = \
            self.__createRunObjects(runOptions, True)

        t = threading.Thread(name="LiveFinish", target=cnc.run, args=())
        t.setDaemon(True)
        t.start()

        (live, liveLog) = self.__createLiveObjects(livePort)

        self.__runTest(live, cnc, liveLog, appender, dashLog, runOptions,
                       True)

    def testZAllLiveFinishInMain(self):
        print "Not running testZAllLiveFinishInMain"
        return
        # from DAQMocks import LogChecker; LogChecker.DEBUG = True
        if not LIVE_IMPORT:
            print 'Skipping I3Live-related test'
            return

        livePort = 9751

        if IntegrationTest.LIVEMONI_ENABLED:
            moniType = RunOption.MONI_TO_LIVE
        else:
            moniType = RunOption.MONI_TO_NONE

        runOptions = RunOption.LOG_TO_LIVE | moniType

        (cnc, appender, dashLog, pShell) = \
            self.__createRunObjects(runOptions)

        (live, liveLog) = self.__createLiveObjects(livePort)

        liveLog.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        t = threading.Thread(name="AllLiveFinish", target=cnc.run, args=())
        t.setDaemon(True)
        t.start()

        liveLog.checkStatus(100)

        self.__runTest(live, cnc, liveLog, appender, dashLog, runOptions,
                       False)

    def testZBothFinishInMain(self):
        print "Not running testZBothFinishInMain"
        return
        if not LIVE_IMPORT:
            print 'Skipping I3Live-related test'
            return

        livePort = 9751

        if IntegrationTest.LIVEMONI_ENABLED:
            moniType = RunOption.MONI_TO_BOTH
        else:
            moniType = RunOption.MONI_TO_FILE

        runOptions = RunOption.LOG_TO_BOTH | moniType

        (cnc, appender, dashLog, pShell) = \
            self.__createRunObjects(runOptions)

        (live, liveLog) = self.__createLiveObjects(livePort)

        patStr = r'\S+ \S+ \S+ \S+ \S+ \S+ \S+'
        liveLog.addExpectedTextRegexp(patStr)

        t = threading.Thread(name="BothLiveFinish", target=cnc.run, args=())
        t.setDaemon(True)
        t.start()

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True
        self.__runTest(live, cnc, liveLog, appender, dashLog, runOptions,
                       False)


if __name__ == '__main__':
    unittest.main()
