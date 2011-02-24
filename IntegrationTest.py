#!/usr/bin/env python

import datetime, os, shutil, sys
import tempfile, threading, time, traceback, unittest, xmlrpclib

from CnCServer import CnCServer, Connector
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQLog import LiveMonitor
from DAQRPC import RPCServer
from LiveImports import Prio, LIVE_IMPORT, SERVICE_NAME
from RunOption import RunOption
from RunSet import RunSet
from TaskManager import MonitorTask, RateTask, TaskManager, WatchdogTask

ACTIVE_WARNING = False

try:
    from DAQLive import DAQLive
except SystemExit:
    class DAQLive:
        SERVICE_NAME = 'dead'

from DAQMocks \
    import MockAppender, MockClusterConfig, MockCnCLogger, \
    MockDeployComponent, MockIntervalTimer, MockParallelShell, \
    MockRunConfigFile, SocketReader, SocketReaderFactory, SocketWriter

class MostlyLive:
    def __init__(self, port):
        raise NotImplementedError("Missing code")

class BeanData(object):
    DAQ_BEANS = {'stringHub' :
                     (('dom', 'sender', 'NumHitsReceived', 'i', 0),
                      ('eventBuilder', 'sender', 'NumReadoutRequestsReceived',
                       'i', 0),
                      ('eventBuilder', 'sender', 'NumReadoutsSent', 'o', 0),
                      ('stringHub', 'stringhub', 'NumberOfActiveChannels', 't',
                       0),
                      ),
                 'inIceTrigger' :
                     (('stringHub', 'stringHit', 'RecordsReceived', 'i', 0),
                      ('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                      ),
                 'simpleTrigger' :
                     (('stringHub', 'stringHit', 'RecordsReceived', 'i', 0),
                      ('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                      ),
                 'iceTopTrigger' :
                     (('stringHub', 'stringHit', 'RecordsReceived', 'i', 0),
                      ('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                      ),
                 'amandaTrigger' :
                     (('globalTrigger', 'trigger', 'RecordsSent', 'o', 0),
                      ),
                 'globalTrigger' :
                     (('inIceTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                      ('simpleTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                      ('iceTopTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                      ('amandaTrigger', 'trigger', 'RecordsReceived', 'i', 0),
                      ('eventBuilder', 'glblTrig', 'RecordsSent', 'o', 0),
                      ),
                 'eventBuilder' :
                     (('stringHub', 'backEnd', 'NumReadoutsReceived', 'i', 0),
                      ('globalTrigger', 'backEnd',
                       'NumTriggerRequestsReceived', 'i', 0),
                      ('dispatch', 'backEnd', 'NumEventsSent', 's', 0),
                      ('eventBuilder', 'backEnd', 'DiskAvailable',
                       't', 1024, True),
                      ('eventBuilder', 'backEnd', 'EventData',
                       'o', [0, 0, 0]),
                      ('eventBuilder', 'backEnd', 'FirstEventTime',
                       'o', 0, True),
                      ('eventBuilder', 'backEnd', 'NumBadEvents',
                       't', 0, False),
                      ),
                 'secondaryBuilders' :
                     (('secondaryBuilders', 'snBuilder', 'DiskAvailable',
                       't', 1024, True),
                      ('dispatch', 'moniBuilder','TotalDispatchedData',
                       'o', 0),
                       ('dispatch', 'snBuilder', 'TotalDispatchedData', 'o', 0),
                      ('dispatch', 'tcalBuilder', 'TotalDispatchedData',
                       'o', 0),
                      ),
                 }

    TYPE_INPUT = 'i'
    TYPE_OUTPUT = 'o'
    TYPE_STATIC = 's'
    TYPE_THRESHOLD = 't'

    def __init__(self, remoteComp, bean, field, watchType, val=0,
                 increasing=True):
        self.__remoteComp = remoteComp
        self.__bean = bean
        self.__field = field
        self.__watchType = watchType
        self.__value = val
        self.__increasing = increasing

    def __cmp__(self, other):
        val = cmp(self.__remoteComp, other.__remoteComp)
        if val == 0:
            val = cmp(self.__bean, other.__bean)
            if val == 0:
                val = cmp(self.__field, other.__field)
                if val == 0:
                    val = cmp(self.__watchType, other.__watchType)
                    if val == 0:
                        val = cmp(self.__increasing, other.__increasing)

        return val

    def __str__(self):
        if self.__increasing:
            dir = '^'
        else:
            dir = 'v'
        return '%s.%s.%s<%s>%s%s' % \
            (self.__remoteComp, self.__bean, self.__field, self.__watchType,
             str(self.__value), dir)

    @staticmethod
    def buildBeans(masterList, compName):
        if not masterList.has_key(compName):
            raise Exception('Unknown component %s' % compName)

        mbeans = {}

        beanTuples = masterList[compName]
        for t in beanTuples:
            if not mbeans.has_key(t[1]):
                mbeans[t[1]] = {}

            if len(t) == 5:
                mbeans[t[1]][t[2]] = BeanData(t[0], t[1], t[2], t[3], t[4])
            elif len(t) == 6:
                mbeans[t[1]][t[2]] = BeanData(t[0], t[1], t[2], t[3], t[4],
                                              t[5])
            else:
                raise Exception('Bad bean tuple %s' % str(t))

        return mbeans

    @staticmethod
    def buildDAQBeans(compName):
        return BeanData.buildBeans(BeanData.DAQ_BEANS, compName)

    def getValue(self):
        return self.__value

    def setValue(self, val):
        self.__value = val

    def update(self):
        if self.__watchType != BeanData.TYPE_STATIC:
            if type(self.__value) == int:
                if self.__increasing:
                    self.__value += 1
                else:
                    self.__value -= 1
            else:
                print 'Not updating %s:%s:%s type %s' % \
                    (self.__remoteComp, self.__bean, self.__field,
                     str(type(self.__value)))

class MostlyTaskManager(TaskManager):
    WAITSECS = 0.25

    TIMERS = {}

    def __init__(self, runset, dashlog, liveMoniClient, runDir, runCfg,
                 runOptions):
        super(MostlyTaskManager, self).__init__(runset, dashlog, liveMoniClient,
                                                runDir, runCfg, runOptions)

    def createIntervalTimer(self, name, period):
        if not self.TIMERS.has_key(name):
            self.TIMERS[name] = MockIntervalTimer(name, self.WAITSECS)

        return self.TIMERS[name]

    def triggerTimer(self, name):
        if not self.TIMERS.has_key(name):
            raise Exception("Unknown timer \"%s\"" % name)

        self.TIMERS[name].trigger()

class MostlyRunSet(RunSet):
    LOGFACTORY = SocketReaderFactory()
    LOGDICT = {}

    def __init__(self, parent, runConfig, set, logger, dashAppender=None):
        self.__dashAppender = dashAppender
        self.__taskMgr = None

        if len(self.LOGDICT) > 0:
            raise Exception("Found %d open runset logs" % len(self.LOGDICT))

        super(MostlyRunSet, self).__init__(parent, runConfig, set, logger)

    @classmethod
    def closeAllLogs(cls):
        for k in cls.LOGDICT.keys():
            cls.LOGDICT[k].stopServing()
            del cls.LOGDICT[k]

    @classmethod
    def createComponentLog(cls, runDir, comp, host, port, liveHost, livePort,
                           quiet=True):
        if cls.LOGDICT.has_key(comp.fullName()):
            return cls.LOGDICT[comp.fullName()]

        expStartMsg = True
        log = cls.LOGFACTORY.createLog(comp.fullName(), port, expStartMsg)
        cls.LOGDICT[comp.fullName()] = log

        #log.addExpectedRegexp('Start #\d+ on \S+#\d+')
        log.addExpectedRegexp(r'Hello from \S+#\d+')
        log.addExpectedTextRegexp(r'Version info: \S+ \S+ \S+ \S+ \S+' +
                                  r' \S+ \d+\S+')

        comp.logTo(host, port, liveHost, livePort)

        return log

    def createDashLog(self):
        return MockCnCLogger(self.__dashAppender, quiet=True, extraLoud=False)

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir=None, logDir=None):
        return super(MostlyRunSet, self).createRunData(runNum,
                                                       clusterConfigName,
                                                       runOptions, versionInfo,
                                                       spadeDir, copyDir,
                                                       logDir, True)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        pass

    def createTaskManager(self, dashlog, liveMoniClient, runDir, runCfg,
                          runOptions):
        self.__taskMgr = MostlyTaskManager(self, dashlog, liveMoniClient,
                                           runDir, runCfg, runOptions)
        return self.__taskMgr

    @classmethod
    def getComponentLog(cls, comp):
        if cls.LOGDICT.has_key(comp.fullName()):
            return cls.LOGDICT[comp.fullName()]
        return None

    def getTaskManager(self):
        return self.__taskMgr

    def queueForSpade(self, duration):
        pass

class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbeanPort, connectors,
                                              quiet=True)

    def createLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet)

class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, clusterConfigObject, logPort, livePort, copyDir,
                 defaultLogDir, runConfigDir, spadeDir):
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
                                              spadeDir=spadeDir,
                                              logIP=logIP, logPort=logPort,
                                              liveIP=liveIP, livePort=livePort,
                                              forceRestart=False, quiet=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        if self.__liveOnly:
            appender = None
        else:
            key = '%s#%d' % (name, num)
            if not MostlyCnCServer.APPENDERS.has_key(key):
                MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)
            appender = MostlyCnCServer.APPENDERS[key]

        return MostlyDAQClient(name, num, host, port, mbeanPort, connectors,
                               appender)

    def createCnCLogger(self, quiet):
        key = 'server'
        if not MostlyCnCServer.APPENDERS.has_key(key):
            MostlyCnCServer.APPENDERS[key] = \
                MockAppender('Mock-%s' % key,
                             depth=IntegrationTest.NUM_COMPONENTS)

        return MockCnCLogger(MostlyCnCServer.APPENDERS[key], quiet)

    def getClusterConfig(self):
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
        msg = ("%(filename)s %(revision)s %(date)s %(time)s %(author)s" +
               " %(release)s %(repo_rev)s") % self.versionInfo()
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
    COMP_ORDER = { 'stringHub' : (50, 50),
                   'amandaTrigger' : (0, 13),
                   'iceTopTrigger' : (2, 12),
                   'inIceTrigger' : (4, 11),
                   'globalTrigger' : (10, 10),
                   'eventBuilder' : (30, 2),
                   'secondaryBuilders' : (32, 0),
                   }

    def __init__(self, name, num, cmdPort, mbeanPort, jvm, jvmArgs,
                 verbose=False):
        self.__id = None
        self.__name = name
        self.__num = num
        self.__jvm = jvm
        self.__jvmArgs = jvmArgs

        self.__state = 'FOO'

        self.__logger = None
        self.__liver = None

        self.__compList = None
        self.__connections = None

        self.__mbeanData = None

        self.__version = {'filename':name, 'revision':'1', 'date':'date',
                          'time':'time', 'author':'author', 'release':'rel',
                          'repo_rev':'1234'}

        self.__cmd = RPCServer(cmdPort)
        self.__cmd.register_function(self.__commitSubrun, 'xmlrpc.commitSubrun')
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__getState, 'xmlrpc.getState')
        self.__cmd.register_function(self.__getVersionString,
                                     'xmlrpc.getVersionInfo')
        self.__cmd.register_function(self.__logTo, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__prepareSubrun,
                                     'xmlrpc.prepareSubrun')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__resetLogging, 'xmlrpc.resetLogging')
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

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER, verbose=verbose)

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

    def __repr__(self): return str(self)

    def __str__(self):
        return '%s#%d' % (self.__name, self.__num)

    def __commitSubrun(self, id, latestTime):
        self.__log('Commit subrun %d: %s' % (id, str(latestTime)))
        return 'COMMIT'

    def __configure(self, cfgName=None):
        if self.__logger is None and self.__liver is None:
            raise Exception('No logging for %s' % (str(self)))

        self.__state = 'ready'
        return 'CFG'

    def __connect(self, *args):
        if self.__compList is None:
            raise Exception("No component list for %s" % str(self))

        tmpDict = {}
        for connList in args:
            for cd in connList:
                for c in self.__compList:
                    if c.isComponent(cd["compName"], cd["compNum"]):
                        tmpDict[c] = 1
                        break

        self.__connections = tmpDict.keys()

        self.__state = 'connected'
        return 'CONN'

    def __getAttributes(self, bean, fldList):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        attrs = {}
        for f in fldList:
            attrs[f] = self.__mbeanData[bean][f].getValue()
        return attrs

    @classmethod
    def __getLaunchOrder(cls, name):
        if not cls.COMP_ORDER.has_key(name):
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name][0]

    def __getMBeanValue(self, bean, fld):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        val = self.__mbeanData[bean][fld].getValue()
        if type(val) == list:
            for i in range(len(val)):
                if type(val[i]) == long or val[i] < xmlrpclib.MININT or \
                        val[i] > xmlrpclib.MAXINT:
                    val[i] = str(val[i])
                    if val[i].endswith("L"):
                        val[i] = val[i][:-1]

        return val

    @classmethod
    def __getStartOrder(cls, name):
        if not cls.COMP_ORDER.has_key(name):
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name][1]

    @classmethod
    def __getOrder(cls, name):
        if not cls.COMP_ORDER.has_key(name):
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name][0]

    def __getState(self):
        return self.__state

    def __getVersionString(self):
        return ('$Id: %(filename)s %(revision)s %(date)s %(time)s' +
                '%(author)s %(repo_rev)s $') % self.__version

    def __listGetters(self, bean):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        k = self.__mbeanData[bean].keys()
        k.sort()
        return k

    def __listMBeans(self):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        k = self.__mbeanData.keys()
        k.sort()
        return k

    def __log(self, msg):
        if self.__logger is None and self.__liver is None:
            raise Exception('No logging for %s' % (str(self)))
        if self.__logger is not None:
            self.__logger.write(msg)
        if self.__liver is not None:
            time = datetime.datetime.utcnow()
            self.__liver.write('%s(log:str) %d [%s] %s' %
                               (SERVICE_NAME, Prio.DEBUG, time, msg))

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

    def __prepareSubrun(self, id):
        self.__log('Prep subrun %d' % id)
        return 'PREP'

    def __reset(self):
        self.__state = 'idle'
        return 'RESET'

    def __resetLogging(self):
        self.__logger = None

        return 'RLOG'

    def __startRun(self, runNum):
        #self.__log('Start #%d on %s' % (runNum, str(self)))

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
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        beanKeys = self.__mbeanData.keys()
        beanKeys.sort()
        for bean in beanKeys:
            for fld in self.__mbeanData[bean]:
                name = '%s-%d*%s+%s' % (self.__name, self.__num, bean, fld)
                if useMBeanData:
                    val = self.__mbeanData[bean][fld].getValue()
                else:
                    val = None
                    if bean == "backEnd":
                        if fld == "FirstEventTime":
                            val = 1000
                        elif fld == "EventData":
                            val = [2, 10000000000]
                        elif fld == "NumEventsSent":
                            val = 2
                    if val is None:
                        val = self.__mbeanData[bean][fld].getValue()

                if bean == "backEnd" and fld == "EventData":
                    type = "json"
                else:
                    type = None

                liveLog.addExpectedLiveMoni(name, val, type)

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

    def fullName(self):
        if self.__num == 0 and not self.__name.lower().endswith("hub"):
            return self.__name

        return "%s#%d" % (self.__name, self.__num)

    def getCommandPort(self): return self.__cmd.portnum
    def getId(self): return 999

    def getMBean(self, bean, fld):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        return self.__mbeanData[bean][fld].getValue()

    def getMBeanPort(self): return self.__mbean.portnum
    def getName(self): return self.__name
    def getNumber(self): return self.__num

    def getState(self):
        return self.__getState()

    def isComponent(self, name, num=-1):
        return self.__name == name and (num < 0 or self.__num == num)
    def jvm(self): return self.__jvm
    def jvmArgs(self): return self.__jvmArgs

    def logTo(self, logHost, logPort, liveHost, livePort):
        return self.__logTo(logHost, logPort, liveHost, livePort)

    def register(self, connList):
        reg = self.__cnc.rpc_component_register(self.__name, self.__num,
                                                'localhost',
                                                self.__cmd.portnum,
                                                self.__mbean.portnum,
                                                connList)
        if type(reg) != dict:
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
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        self.__mbeanData[bean][fld].setValue(val)

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
    CLUSTER_CONFIG = 'simpleConfig'
    CONFIG_DIR = os.path.abspath('src/test/resources/config')
    CONFIG_NAME = 'simpleConfig'
    COPY_DIR = 'bogus'
    SPADE_DIR = '/tmp'
    LOG_DIR = None
    LIVEMONI_ENABLED = False

    NUM_COMPONENTS = 9

    RUNNING = False

    def __addLiveMoni(self, liveMoni, compName, compNum, beanName,
                      fieldName, isJSON=False):

        for c in self.__compList:
            if c.getName()() == compName and c.getNumber() == compNum:
                val = c.getMBean(beanName, fieldName)
                var = "%s-%d*%s+%s" % (compName, compNum, beanName, fieldName)
                if isJSON:
                    liveMoni.addExpectedLiveMoni(var, val, "json")
                else:
                    liveMoni.addExpectedLiveMoni(var, val)
                return

        raise Exception("Unknown component %s-%d" % (compName, compNum))

    def __createComponents(self):
        # Note that these jvm/jvmArg values needs to correspond to
        # what would be used by the config in 'sim-localhost'
        jvm = 'java'
        hubJvmArgs = '-server -Xmx512m'
        comps = [('stringHub', 1001, 9111, 9211, jvm, hubJvmArgs),
                 ('stringHub', 1002, 9112, 9212, jvm, hubJvmArgs),
                 ('stringHub', 1003, 9113, 9213, jvm, hubJvmArgs),
                 ('stringHub', 1004, 9114, 9214, jvm, hubJvmArgs),
                 ('stringHub', 1005, 9115, 9215, jvm, hubJvmArgs),
                 ('inIceTrigger', 0, 9117, 9217, jvm, '-server'),
                 ('globalTrigger', 0, 9118, 9218, jvm, '-server'),
                 ('eventBuilder', 0, 9119, 9219, jvm, '-server'),
                 ('secondaryBuilders', 0, 9120, 9220, jvm, '-server'),]

        if len(comps) != IntegrationTest.NUM_COMPONENTS:
            raise Exception("Expected %d components, not %d" %
                            (IntegrationTest.NUM_COMPONENTS, len(comps)))

        verbose = False

        for c in comps:
            comp = RealComponent(c[0], c[1], c[2], c[3], c[4], c[5], verbose)

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

        self.__live = MostlyLive(livePort)

        return (self.__live, log)

    def __createLoggers(self, runOptions, liveRunOnly):
        if not RunOption.isLogToFile(runOptions) and not liveRunOnly:
            appender = None
        else:
            appender = MockAppender('main',
                                    depth=IntegrationTest.NUM_COMPONENTS)

        dashLog = MockAppender("dash")
        return (appender, dashLog)

    def __createParallelShell(self, logPort, livePort):
        pShell = MockParallelShell()

        doCnC = True
        verbose = False
        killWith9 = False

        dashDir = pShell.getMetaPath('dash')

        host = 'localhost'

        logLevel = 'INFO'

        pShell.addExpectedPythonKill(doCnC, dashDir, killWith9)

        launchList = self.__compList[:]
        launchList.sort(RealComponent.sortForLaunch)

        for comp in launchList:
            pShell.addExpectedJavaKill(comp.getName(), comp.getNumber(),
                                       killWith9, verbose, host)

        pShell.addExpectedPython(doCnC, dashDir, IntegrationTest.CONFIG_DIR,
                                 IntegrationTest.LOG_DIR,
                                 IntegrationTest.SPADE_DIR,
                                 IntegrationTest.CONFIG_NAME,
                                 IntegrationTest.COPY_DIR, logPort, livePort)
        for comp in launchList:
            deployComp = MockDeployComponent(comp.getName(), comp.getNumber(),
                                             logLevel, comp.jvm(),
                                             comp.jvmArgs())
            pShell.addExpectedJava(deployComp, IntegrationTest.CONFIG_DIR,
                                   DAQPort.CATCHALL, livePort, verbose, False,
                                   host)

        return pShell

    def __createRunObjects(self, runOptions, liveRunOnly=False):

        (appender, dashLog) = \
            self.__createLoggers(runOptions, liveRunOnly)

        self.__createComponents()

        cluCfg = MockClusterConfig(IntegrationTest.CLUSTER_CONFIG)
        for c in self.__compList:
            cluCfg.addComponent(c.fullName(), c.jvm(), c.jvmArgs(),
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
                                     self.SPADE_DIR)
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

    def __forceRate(self, cnc, dashLog):
        taskMgr = cnc.getRunSet().getTaskManager()

        self.__setBeanData("eventBuilder", 0, "backEnd", "EventData", [0, 0])
        self.__setBeanData("eventBuilder", 0, "backEnd", "FirstEventTime", 0)

        dashLog.addExpectedRegexp(r"\s+0 physics events, 0 moni events," +
                                  r" 0 SN events, 0 tcals")

        taskMgr.triggerTimer(RateTask.NAME)
        time.sleep(MostlyTaskManager.WAITSECS)
        taskMgr.waitForTasks()

        self.__waitForEmptyLog(dashLog, "Didn't get rate message")

        numEvts = 5
        firstTime = 5000
        curTime = 20000000000 + firstTime

        self.__setBeanData("eventBuilder", 0, "backEnd", "EventData",
                           [numEvts, curTime])
        self.__setBeanData("eventBuilder", 0, "backEnd", "FirstEventTime",
                           firstTime)

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

        taskMgr.triggerTimer(WatchdogTask.NAME)
        time.sleep(MostlyTaskManager.WAITSECS)
        taskMgr.waitForTasks()

        dashLog.addExpectedRegexp("Watchdog reports threshold components.*")
        dashLog.addExpectedExact("Run is unhealthy (%d checks left)" %
                                 (WatchdogTask.HEALTH_METER_FULL - 1))

        taskMgr.triggerTimer(WatchdogTask.NAME)
        time.sleep(MostlyTaskManager.WAITSECS)
        taskMgr.waitForTasks()

        self.__waitForEmptyLog(dashLog, "Didn't get watchdog message")

    def __getConnectionList(self, name):
        if name == 'stringHub':
            connList = [('moniData', Connector.OUTPUT, -1),
                        ('rdoutData', Connector.OUTPUT, -1),
                        ('rdoutReq', Connector.INPUT, -1),
                        ('snData', Connector.OUTPUT, -1),
                        ('tcalData', Connector.OUTPUT, -1),
                        ('stringHit', Connector.OUTPUT, -1),
                        ]
        elif name == 'inIceTrigger':
            connList = [('stringHit', Connector.INPUT, -1),
                        ('trigger', Connector.OUTPUT, -1),
                        ]
        elif name == 'globalTrigger':
            connList = [('glblTrig', Connector.OUTPUT, -1),
                        ('trigger', Connector.INPUT, -1),
                        ]
        elif name == 'eventBuilder':
            connList = [('glblTrig', Connector.INPUT, -1),
                        ('rdoutData', Connector.INPUT, -1),
                        ('rdoutReq', Connector.OUTPUT, -1),
                        ]
        elif name == 'secondaryBuilders':
            connList = [('moniData', Connector.INPUT, -1),
                        ('snData', Connector.INPUT, -1),
                        ('tcalData', Connector.INPUT, -1),
                        ]
        else:
            raise Exception('Cannot get connection list for %s' % name)

        return connList

    def __registerComponents(self, liveLog, logServer, liveRunOnly):
        
        for comp in self.__compList:
            if logServer is not None:
                logServer.addExpectedTextRegexp("Registered %s" %
                                                comp.fullName())
                logServer.addExpectedExact('Hello from %s' % str(comp))
            if liveLog is not None and not liveRunOnly:
                liveLog.addExpectedTextRegexp('Registered %s' % comp.fullName())
                liveLog.addExpectedText('Hello from %s' % str(comp))
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

    def __testBody(self, live, cnc, liveLog, appender, dashLog, runOptions,
                   liveRunOnly):

        logServer = cnc.getLogServer()

        RUNLOG_INFO = False

        #import datetime
        if liveLog: liveLog.checkStatus(10)
        if appender: appender.checkStatus(10)
        if dashLog: dashLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        self.__registerComponents(liveLog, logServer, liveRunOnly)

        time.sleep(0.4)

        if liveLog: liveLog.checkStatus(10)
        if appender: appender.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        setId = RunSet.ID.peekNext()
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
                if liveLog: liveLog.addExpectedText(msg)

            for c in self.__compList:
                msg = 'Component list will require %s#%d' % \
                    (c.getName(), c.getNumber())
                if liveLog: liveLog.addExpectedText(msg)

        for s in ("Loading", "Loaded"):
            msg = '%s run configuration "%s"' % (s, configName)
            if liveLog and not liveRunOnly: liveLog.addExpectedText(msg)
            if logServer: logServer.addExpectedText(msg)

        msg = 'Built runset #\d+: .*'
        if liveLog and not liveRunOnly: liveLog.addExpectedTextRegexp(msg)
        if logServer: logServer.addExpectedTextRegexp(msg)

        msg = 'Created Run Set #%d' % setId
        if liveLog: liveLog.addExpectedText(msg)

        msgList = [('Version info: %(filename)s %(revision)s %(date)s' +
                    ' %(time)s %(author)s %(release)s %(repo_rev)s') %
                   cnc.versionInfo(),
                   'Starting run %d...' % runNum,
                   'Run configuration: %s' % configName
                   ]
        if RUNLOG_INFO:
            msgList.append('Created logger for CnCServer')

        for msg in msgList:
            #if appender and not liveRunOnly: appender.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

        if dashLog:
            dashLog.addExpectedRegexp(r'Version info: \S+ \d+ \S+ \S+ \S+' +
                                      r' \S+ \d+\S+')
            dashLog.addExpectedExact('Run configuration: %s' % configName)
            dashLog.addExpectedExact("Cluster configuration: " +
                                     IntegrationTest.CLUSTER_CONFIG)

        if liveLog:
            keys = self.__compList[:]
            keys.sort(RealComponent.sortForStart)

            for c in keys:
                liveLog.addExpectedText('Hello from %s' % str(c))
                liveLog.addExpectedTextRegexp((r'Version info: %s \S+ \S+' +
                                               r' \S+ \S+ \S+ \d+\S+') %
                                              c.getName())

        if RUNLOG_INFO:
            msg = 'Configuring run set...'
            if appender and not liveRunOnly: appender.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

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
                    if liveLog: liveLog.addExpectedText(msg)

        msg = "Starting run #%d with \"%s\"" % \
            (runNum, IntegrationTest.CLUSTER_CONFIG)
        if liveLog and not liveRunOnly: liveLog.addExpectedText(msg)
        if logServer: logServer.addExpectedText(msg)

        if dashLog:
            dashLog.addExpectedExact("Starting run %d..." % runNum)
            if live is None:
                global ACTIVE_WARNING
                if not LIVE_IMPORT and not ACTIVE_WARNING:
                    ACTIVE_WARNING = True
                    msg = "Cannot import IceCube Live code, so per-string" + \
                        " active DOM stats wil not be reported"
                    dashLog.addExpectedExact(msg)
        if liveLog:
            for c in self.__compList:
                liveLog.addExpectedText('Start #%d on %s' % (runNum, str(c)))

        msg = 'Started run %d on run set %d' % (runNum, setId)
        if liveLog: liveLog.addExpectedText(msg)

        startEvtTime = 1001

        if liveLog:
            liveLog.addExpectedTextRegexp(r"DAQ state is RUNNING after \d+" +
                                          " seconds")
            liveLog.addExpectedText('Started run %d' % runNum)

        if live is not None:
            live.starting({'runNumber':runNum, 'runConfig':configName})
        else:
            id = cnc.rpc_runset_make(configName)
            self.assertEquals(setId, id,
                              "Expected to create runset #%d, not #%d" %
                              (setId, id))
            cnc.rpc_runset_start_run(setId, runNum, RunOption.LOG_TO_FILE)

        self.__waitForState(cnc, setId, "running")

        if liveLog: liveLog.checkStatus(10)
        if appender: appender.checkStatus(500)
        if dashLog: dashLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

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
            liveLog.addExpectedLiveMoni("activeStringDOMs", activeDOMMap,
                                        "json")
        self.__forceMonitoring(cnc, liveLog)

        if liveLog: liveLog.checkStatus(10)
        if appender: appender.checkStatus(500)
        if dashLog: dashLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        self.__forceRate(cnc, dashLog)

        if liveLog: liveLog.checkStatus(10)
        if appender: appender.checkStatus(500)
        if dashLog: dashLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        self.__forceWatchdog(cnc, dashLog)

        if liveLog: liveLog.checkStatus(10)
        if appender: appender.checkStatus(500)
        if dashLog: dashLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        if RunOption.isMoniToLive(runOptions):
            liveLog.setCheckDepth(5)

        subRunId = 1

        if liveLog: liveLog.addExpectedText('Starting subrun %d.%d' %
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
        if dashLog: dashLog.addExpectedExact(msg)

        fmt = 'Subrun %d: flashing DOM (%%s)' % subRunId
        if dashLog: dashLog.addExpectedExact(fmt % str(rpcFlashList))

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
                if clog: clog.addExpectedExact(msg)
                if liveLog: liveLog.addExpectedText(msg)
            if c.getName() == 'stringHub':
                msg = 'Start subrun %s' % str(rpcFlashList)
                if clog: clog.addExpectedExact(msg)
                if liveLog: liveLog.addExpectedText(msg)
            if c.getName() == 'eventBuilder':
                patStr = 'Commit subrun %d: \d+L' % subRunId
                if clog: clog.addExpectedRegexp(patStr)
                if liveLog: liveLog.addExpectedTextRegexp(patStr)

        if live is not None:
            live.subrun(subRunId, domList)
        else:
            cnc.rpc_runset_subrun(setId, subRunId, domList)

        if dashLog: dashLog.checkStatus(10)
        if appender: appender.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        subRunId += 1

        if liveLog: liveLog.addExpectedText('Stopping subrun %d.%d' %
                                            (runNum, subRunId))

        msg = 'Subrun %d: stopping flashers' % subRunId
        if dashLog: dashLog.addExpectedExact(msg)

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
                if clog: clog.addExpectedExact(msg)
                if liveLog: liveLog.addExpectedText(msg)
            if c.getName() == 'stringHub':
                msg = 'Start subrun %s' % str([])
                if clog: clog.addExpectedExact(msg)
                if liveLog: liveLog.addExpectedText(msg)
            if c.getName() == 'eventBuilder':
                patStr = 'Commit subrun %d: \d+L' % subRunId
                if clog: clog.addExpectedRegexp(patStr)
                if liveLog: liveLog.addExpectedTextRegexp(patStr)

        if live is not None:
            live.subrun(subRunId, [])
        else:
            cnc.rpc_runset_subrun(setId, subRunId, [])

        if dashLog: dashLog.checkStatus(10)
        if appender: appender.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        if liveLog: liveLog.addExpectedText('Stopping run %d' % runNum)

        domTicksPerSec = 10000000000

        numEvts = 17
        numMoni = 222
        numSN = 51
        numTCal = 93
        lastEvtTime = startEvtTime + (domTicksPerSec * 3)

        self.__setBeanData("eventBuilder", 0, "backEnd", "NumEventsSent",
                           numEvts)
        self.__setBeanData("eventBuilder", 0, "backEnd", "EventData",
                           [numEvts, lastEvtTime])
        self.__setBeanData("eventBuilder", 0, "backEnd", "FirstEventTime",
                           startEvtTime)
        self.__setBeanData("secondaryBuilders", 0, "moniBuilder",
                           "TotalDispatchedData", numMoni)
        self.__setBeanData("secondaryBuilders", 0, "snBuilder",
                           "TotalDispatchedData", numSN)
        self.__setBeanData("secondaryBuilders", 0, "tcalBuilder",
                           "TotalDispatchedData", numTCal)

        msg = 'Stopping run %d' % runNum
        if liveLog: liveLog.addExpectedText(msg)

        for c in self.__compList:
            if not appender or liveRunOnly:
                clog = None
            else:
                clog = MostlyRunSet.getComponentLog(c)
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (c.getName(), c.getNumber()))

            msg = 'Stop %s#%d' % (c.getName(), c.getNumber())
            if clog: clog.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

        patStr = (r'%d physics events collected in -?\d+ seconds' +
                  r'(\s+\(-?\d+\.\d+ Hz\))?') % numEvts
        dashLog.addExpectedRegexp(patStr)
        if liveLog: liveLog.addExpectedTextRegexp(patStr)

        msg = '%d moni events, %d SN events, %d tcals' % \
            (numMoni, numSN, numTCal)
        dashLog.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        if RUNLOG_INFO:
            msg = 'Stopping component logging'
            if appender and not liveRunOnly: appender.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

            patStr = 'RPC Call stats:.*'
            if appender and not liveRunOnly: appender.addExpectedRegexp(patStr)
            if liveLog: liveLog.addExpectedTextRegexp(patStr)

        msg = 'Run terminated SUCCESSFULLY.'
        dashLog.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        if liveLog:
            liveLog.addExpectedTextRegexp(r"DAQ state is STOPPED after \d+" +
                                          " seconds")
            liveLog.addExpectedText('Stopped run %d' % runNum)

            liveLog.addExpectedLiveMoni('tcalEvents', numTCal)
            liveLog.addExpectedLiveMoni('moniEvents', numMoni)
            liveLog.addExpectedLiveMoni('snEvents', numSN)
            liveLog.addExpectedLiveMoni('physicsEvents', numEvts)
            liveLog.addExpectedLiveMoni('walltimeEvents', numEvts)

        if live is not None:
            live.stopping()
        else:
            cnc.rpc_runset_stop_run(setId)

        self.__waitForState(cnc, setId, "ready")

        if dashLog: dashLog.checkStatus(10)
        if appender: appender.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        moni = cnc.rpc_runset_monitor_run(setId)
        self.failIf(moni is None, 'rpc_run_monitoring returned None')
        self.failIf(len(moni) == 0, 'rpc_run_monitoring returned no data')
        self.assertEquals(numEvts, moni['physicsEvents'],
                          'Expected %d physics events, not %d' %
                          (numEvts, moni['physicsEvents']))
        self.assertEquals(numMoni, moni['moniEvents'],
                          'Expected %d moni events, not %d' %
                          (numMoni, moni['moniEvents']))
        self.assertEquals(numSN, moni['snEvents'],
                          'Expected %d sn events, not %d' %
                          (numSN, moni['snEvents']))
        self.assertEquals(numTCal, moni['tcalEvents'],
                          'Expected %d tcal events, not %d' %
                          (numTCal, moni['tcalEvents']))

        if dashLog: dashLog.checkStatus(10)
        if appender: appender.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

        if RUNLOG_INFO:
            msg = 'Breaking run set...'
            if liveLog and not liveRunOnly: liveLog.addExpectedText(msg)

        if live is not None:
            live.release()
        else:
            cnc.rpc_runset_break(setId)

        if dashLog: dashLog.checkStatus(10)
        if appender: appender.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)
        if logServer: logServer.checkStatus(10)

    @staticmethod
    def __waitForEmptyLog(log, errMsg):
        for i in range(5):
            if log.isEmpty():
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
        self.assertEquals(expState, state, 'Should be %s, not %s' %
                          (expState, state))

    def setUp(self):
        MostlyCnCServer.APPENDERS.clear()

        self.__logFactory = SocketReaderFactory()

        IntegrationTest.LOG_DIR = tempfile.mkdtemp()

        DAQLive.STATE_WARNING = False

        self.__live = None
        self.__cnc = None
        self.__compList = None

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

        for root, dirs, files in os.walk(IntegrationTest.LOG_DIR,
                                         topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        shutil.rmtree(IntegrationTest.LOG_DIR, ignore_errors=True)
        IntegrationTest.LOG_DIR = None

        if True:
            reps = 5
            for n in range(reps):
                if threading.activeCount() < 2:
                    break

                needHdr = True
                for t in threading.enumerate():
                    if t.getName() == "MainThread": continue

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

    def testFinishInMain(self):
        #print "Not running testFinishInMain"; return
        runOptions = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        (cnc, appender, dashLog, pShell) = \
            self.__createRunObjects(runOptions)

        t = threading.Thread(name="MainFinish", target=cnc.run, args=())
        t.setDaemon(True)
        t.start()

        self.__runTest(None, cnc, None, appender, dashLog, runOptions, False)

    def testCnCInMain(self):
        #print "Not running testCnCInMain"; return
        if sys.platform != 'darwin':
            print 'Skipping server tests in non-Darwin OS'
            return

        runOptions = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        (cnc, appender, dashLog, pShell) = self.__createRunObjects(runOptions)

        t = threading.Thread(name="CnCFinish", target=self.__runTest,
                             args=(None, cnc, None, appender, dashLog,
                                   runOptions, False))
        t.setDaemon(True)
        t.start()

        cnc.run()

    def testLiveFinishInMain(self):
        print "Not running testLiveFinishInMain"; return
        #from DAQMocks import LogChecker; LogChecker.DEBUG = True
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
        print "Not running testZAllLiveFinishInMain"; return
        #from DAQMocks import LogChecker; LogChecker.DEBUG = True
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
        print "Not running testZBothFinishInMain"; return
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

        #from DAQMocks import LogChecker; LogChecker.DEBUG = True
        self.__runTest(live, cnc, liveLog, appender, dashLog, runOptions,
                       False)

if __name__ == '__main__':
    unittest.main()
