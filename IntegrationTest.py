#!/usr/bin/env python

import StringIO, datetime, os, re, sys
import tempfile, thread, time, unittest, xmlrpclib

from CnCServer import CnCServer, DAQClient, RunSet
from DAQConst import DAQPort
from DAQLogClient import LiveMonitor, Prio
from DAQMoni import DAQMoni, FileMoniData
from DAQRPC import RPCServer
from DAQRun import DAQRun, RunArgs
from RunWatchdog import RunWatchdog

TEST_LIVE = True
try:
    from DAQLive import DAQLive, LiveArgs
except SystemExit:
    TEST_LIVE = False
    class DAQLive:
        SERVICE_NAME = 'dead'

from DAQMocks \
    import MockAppender, MockCnCLogger, MockParallelShell, \
    SocketReaderFactory, SocketWriter

class BeanData(object):
    DAQ_BEANS = {'stringHub' :
                     (('dom', 'sender', 'NumHitsReceived', 'i', 0),
                      ('eventBuilder', 'sender', 'NumReadoutRequestsReceived',
                       'i', 0),
                      ('eventBuilder', 'sender', 'NumReadoutsSent', 'o', 0),
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

    def buildBeans(cls, masterList, compName):
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
    buildBeans = classmethod(buildBeans)

    def buildDAQBeans(cls, compName):
        return cls.buildBeans(BeanData.DAQ_BEANS, compName)
    buildDAQBeans = classmethod(buildDAQBeans)

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

class CachedData(object):
    def __init__(self):
        self.__data = {}

    def __getitem__(self, key):
        return self.__data[key]

    def __iter__(self):
        for k in self.__data:
            yield k

    def __len__(self):
        return len(self.__data)

    def __key(self, name, daqId):
        return '%s#%d' % (name, daqId)

    def add(self, name, daqId, client):
        key = self.__key(name, daqId)

        if self.__data.has_key(key):
            raise Exception('MBean exists for %s' % key)

        self.__data[key] = client

    def clear(self):
        self.__data.clear()

    def get(self, name, daqId):
        key = self.__key(name, daqId)

        if not self.__data.has_key(key):
            raise Exception('MBean not found for %s' % key)

        return self.__data[key]

    def has_key(self, name, daqId):
        return self.__data.has_key(self.__key(name, daqId))

class MockMoniFile(FileMoniData):
    DATA = CachedData()

    BEAN_PAT = re.compile(r'^(\S+):\s*\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+:\s*$')
    DATA_PAT = re.compile(r'^\s+(\S+):\s*(.*)$')

    def __init__(self, name, daqId, addr, port):
        self.__stringFile = None

        super(MockMoniFile, self).__init__(name, daqId, addr, port, None)

        MockMoniFile.DATA.add(name, daqId, self)

    def check(cls):
        for c in cls.DATA:
            lines = cls.DATA[c].getOutputLines()

            #bean = None
            for l in lines:
                if len(l) == 0:
                    # ignore blank lines
                    continue

                m = cls.BEAN_PAT.match(l)
                if m:
                    #bean = m.group(1)
                    continue

                m = cls.DATA_PAT.match(l)
                if m:
                    #fld = m.group(1)
                    #print 'Moni %s: %s.%s' % (c, bean, fld)
                    continue

                raise Exception('Bad %s moni: %s' % (str(c), l))

    check = classmethod(check)

    def clear(cls):
        cls.DATA.clear()
    clear = classmethod(clear)

    def getOutputLines(self):
        if self.__stringFile is None:
            return None
        return self.__stringFile.getvalue().split('\n')

    def openFile(self, fname):
        if self.__stringFile is None:
            self.__stringFile = StringIO.StringIO()
        return self.__stringFile

class MockMoniBoth(MockMoniFile):
    def __init__(self, name, daqId, addr, port):
        super(MockMoniBoth, self).__init__(name, daqId, addr, port)

        self.__moni = LiveMonitor()

    def _report(self, now, b, attrs):
        super(MockMoniBoth, self)._report(now, b, attrs)

        for key in attrs:
            self.__moni.send('%s*%s+%s' % (str(self), b, key), now, attrs[key])

class MockMoni(DAQMoni):
    def __init__(self, log, moniPath, interval, IDs, names, daqIDs, addrs,
                 mbeanPorts, moniType):

        self.__moniFlag = False
        self.__didMoni = False

        super(MockMoni, self).__init__(log, moniPath, interval, IDs, names,
                                       daqIDs, addrs, mbeanPorts, moniType,
                                       quiet=True)

    def createFileData(self, name, daqId, addr, port, fname):
        return MockMoniFile(name, daqId, addr, port)

    def createBothData(self, name, daqId, addr, port, fname):
        return MockMoniBoth(name, daqId, addr, port)

    def didMoni(self):
        return self.__didMoni

    def doMoni(self):
        super(MockMoni, self).doMoni()
        self.__didMoni = True

    def setMoniFlag(self):
        self.__moniFlag = True
        self.__didMoni = False

    def timeToMoni(self):
        "Override this so we can control when monitoring runs"
        val = self.__moniFlag
        self.__moniFlag = False
        return val

class MockWatchdog(RunWatchdog):
    def __init__(self, daqLog, interval, IDs, shortNameOf, daqIDof,
                 rpcAddrOf, mbeanPortOf):
        self.__watchFlag = False
        self.__didWatch = False

        super(MockWatchdog, self).__init__(daqLog, interval, IDs, shortNameOf,
                                           daqIDof, rpcAddrOf, mbeanPortOf,
                                           True)

    def didWatch(self):
        return self.__didWatch

    def realWatch(self):
        val = super(MockWatchdog, self).realWatch()
        self.__didWatch = True
        return val

    def setWatchFlag(self):
        self.__watchFlag = True
        self.__didWatch = False

    def timeToWatch(self):
        "Override this so we can control when watchdog runs"
        if self.inProgress(): return False
        val = self.__watchFlag
        self.__watchFlag = False
        return val

class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbeanPort, connectors)

    def createCnCLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet)

class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, logPort, livePort):
        self.__liveOnly = logPort is None and livePort is not None

        if logPort is None:
            logIP = None
        else:
            logIP = 'localhost'
        if livePort is None:
            liveIP = None
        else:
            liveIP = 'localhost'
        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              logIP=logIP, logPort=logPort,
                                              liveIP=liveIP, livePort=livePort,
                                              quiet=True)

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
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MockCnCLogger(MostlyCnCServer.APPENDERS[key], quiet)

    def monitorLoop(self):
        pass

class RealComponent(object):
    # Component order, used in the __getOrder() method
    COMP_ORDER = { 'stringHub' : 50,
                   'amandaTrigger' : 0,
                   'iceTopTrigger' : 2,
                   'inIceTrigger' : 4,
                   'globalTrigger' : 10,
                   'eventBuilder' : 30,
                   'secondaryBuilders' : 32,
                   }

    def __init__(self, name, num, cmdPort, mbeanPort, verbose=False):
        self.__id = None
        self.__name = name
        self.__num = num

        self.__state = 'FOO'

        self.__logger = None
        self.__liver = None

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
        thread.start_new_thread(self.__cmd.serve_forever, ())

        self.__mbean = RPCServer(mbeanPort)
        self.__mbean.register_function(self.__getAttributes,
                                     'mbean.getAttributes')
        self.__mbean.register_function(self.__getMBeanValue, 'mbean.get')
        self.__mbean.register_function(self.__listGetters, 'mbean.listGetters')
        self.__mbean.register_function(self.__listMBeans, 'mbean.listMBeans')
        thread.start_new_thread(self.__mbean.serve_forever, ())

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER, verbose=verbose)

    def __cmp__(self, other):
        selfOrder = RealComponent.__getOrder(self.__name)
        otherOrder = RealComponent.__getOrder(other.__name)

        if selfOrder < otherOrder:
            return -1
        elif selfOrder > otherOrder:
            return 1

        if self.__num < other.__num:
            return -1
        elif self.__num > other.__num:
            return 1

        return 0

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
        self.__state = 'connected'
        return 'CONN'

    def __getAttributes(self, bean, fldList):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        attrs = {}
        for f in fldList:
            attrs[f] = self.__mbeanData[bean][f].getValue()
        return attrs

    def __getMBeanValue(self, bean, fld):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        return self.__mbeanData[bean][fld].getValue()

    def __getOrder(cls, name):
        if not cls.COMP_ORDER.has_key(name):
            raise Exception('Unknown component type %s' % name)
        return cls.COMP_ORDER[name]
    __getOrder = classmethod(__getOrder)

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
                               (DAQLive.SERVICE_NAME, Prio.DEBUG, time, msg))

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

        self.__state = 'reset'
        return 'RLOG'

    def __startRun(self, runNum):
        self.__log('Start #%d on %s' % (runNum, str(self)))

        self.__state = 'running'
        return 'RUN#%d' % runNum

    def __startSubrun(self, data):
        self.__log('Start subrun %s' % str(data))
        return long(time.time())

    def __stopRun(self):
        self.__log('Stop %s' % str(self))

        self.__state = 'stopped'
        return 'STOP'

    def addI3LiveMonitoring(self, liveLog):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        beanKeys = self.__mbeanData.keys()
        beanKeys.sort()
        for bean in beanKeys:
            for fld in self.__mbeanData[bean]:
                name = '%s-%d*%s+%s' % (self.__name, self.__num, bean, fld)
                val = self.__mbeanData[bean][fld].getValue()
                liveLog.addExpectedLiveMoni(name, val)

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

    def getCommandPort(self): return self.__cmd.portnum
    def getId(self): return 999
    def getMBeanPort(self): return self.__mbean.portnum
    def getName(self): return self.__name
    def getNumber(self): return self.__num

    def getState(self):
        return self.__getState()

    def register(self, connList):
        reg = self.__cnc.rpc_register_component(self.__name, self.__num,
                                                'localhost', self.__cmd.portnum,
                                                self.__mbean.portnum, connList)
        if type(reg) != list:
            raise Exception('Expected registration to return list, not %s' %
                            str(type(reg)))

        numElems = 6
        if len(reg) != numElems:
            raise Exception(('Expected registration to return %d-element' +
                             ' list, not %d') % (numElems, len(reg)))

        self.__id = reg[0]

        self.__logTo(reg[1], reg[2], reg[3], reg[4])

    def setMBean(self, bean, fld, val):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        self.__mbeanData[bean][fld].setValue(val)

    def sortForLaunch(y, x):
        selfOrder = RealComponent.__getOrder(x.__name)
        otherOrder = RealComponent.__getOrder(y.__name)

        if selfOrder < otherOrder:
            return -1
        elif selfOrder > otherOrder:
            return 1

        if x.__num < y.__num:
            return 1
        elif x.__num > y.__num:
            return -1

        return 0
    sortForLaunch = staticmethod(sortForLaunch)

class StubbedDAQRun(DAQRun):
    LOGFACTORY = None
    LOGDICT = {}

    def __init__(self, extraArgs=None, startServer=False):
        self.__moni = None
        self.__watchdog = None

        self.__fileAppender = None
        self.__mockAppender = None
        self.__logServer = None

        self.liveLog = None
        self.catchAllLog = None

        super(StubbedDAQRun, self).__init__(self.__getRunArgs(extraArgs),
                                            startServer)

    def __getRunArgs(self, extraArgs=None):

        stdArgs = { '-a' : IntegrationTest.COPY_DIR,
                    '-c' : IntegrationTest.CONFIG_DIR,
                    '-l' : IntegrationTest.LOG_DIR,
                    '-n' : '',
                    '-p' : str(DAQPort.DAQRUN),
                    '-q' : '',
                    '-s' : IntegrationTest.SPADE_DIR,
                    '-u' : IntegrationTest.CLUSTER_CONFIG }

        oldArgv = sys.argv
        try:
            sys.argv = ['foo']

            for k in stdArgs.keys():
                if extraArgs is None or not extraArgs.has_key(k):
                    sys.argv.append(k)
                    if len(stdArgs[k]) > 0:
                        sys.argv.append(stdArgs[k])

            if extraArgs is not None:
                for k in extraArgs.keys():
                    sys.argv.append(k)
                    if len(extraArgs[k]) > 0:
                        sys.argv.append(extraArgs[k])

            args = RunArgs()
            args.parse()
        finally:
            sys.argv = oldArgv

        return args

    def clearLogs(cls):
        cls.LOGDICT.clear()
    clearLogs = classmethod(clearLogs)

    def createFileAppender(self):
        return self.__fileAppender

    def createInitialAppender(self):
        if self.__mockAppender is None:
            self.__mockAppender = MockAppender('runlog')

        return self.__mockAppender

    def createLogSocketServer(cls, logPort, shortName, logFile):
        name = os.path.basename(logFile)
        if name[-4:] == '.log':
            name = name[:-4]

        if cls.LOGDICT.has_key(name):
            return cls.LOGDICT[name]

        isServer = (name == 'catchall' or name == 'cncserver')

        expStartMsg = True
        log = cls.LOGFACTORY.createLog(name, logPort, expStartMsg)
        cls.LOGDICT[name] = log

        if not isServer:
            log.addExpectedRegexp(r'Hello from \S+#\d+')
            log.addExpectedTextRegexp(r'Version info: \S+ \S+ \S+ \S+ \S+' +
                                      r' \S+ \d+\S+')
            if logPort != DAQPort.CATCHALL:
                log.addExpectedRegexp('Start #\d+ on \S+#\d+')

        return log

    createLogSocketServer = classmethod(createLogSocketServer)

    def createRunLogDirectory(self, runNum, logDir):
        self.setLogPath(runNum, logDir)

    def forceMonitoring(self):
        self.__moni.setMoniFlag()

        numTries = 0
        while not self.__moni.didMoni() and numTries < 100:
            time.sleep(0.1)
            numTries += 1

        if not self.__moni.didMoni():
            raise Exception('Monitoring did not run')

        numTries = 0
        while self.__moni.isActive() and numTries < 100:
            time.sleep(0.1)
            numTries += 1

    def forceWatchdog(self):
        self.__watchdog.setWatchFlag()

        numTries = 0
        while not self.__watchdog.didWatch() and numTries < 100:
            time.sleep(0.1)
            numTries += 1

        if not self.__watchdog.didWatch():
            raise Exception('Watchdog did not run')

    def get_base_prefix(self, runNum, runTime, runDuration):
        return 'MockPrefix#%d' % runNum

    def getComponentLog(cls, name, num):
        key = '%s-%d' % (name, num)
        if cls.LOGDICT.has_key(key):
            return cls.LOGDICT[key]
        return None
    getComponentLog = classmethod(getComponentLog)

    def getWatchCount(self):
        if self.__watchdog is None:
            return -1

        return self.__watchdog.getCount()

    def move_spade_files(self, copyDir, basePrefix, logTopLevel, runDir,
                         spadeDir):
        pass

    def restartComponents(self, pShell):
        super(StubbedDAQRun, self).restartComponents(pShell, checkExists=False,
                                                     startMissing=False)

    def setFileAppender(self, appender):
        self.__fileAppender = appender

    def setup_monitoring(self, log, moniPath, interval, compIDs, shortNames,
                         daqIDs, rpcAddrs, mbeanPorts, moniType):
        if self.__moni is not None:
            raise Exception('DAQMoni already exists')

        self.__moni = MockMoni(log, moniPath, interval, compIDs, shortNames,
                               daqIDs, rpcAddrs, mbeanPorts, moniType)
        return self.__moni

    def setup_watchdog(self, log, interval, compIDs, shortNames, daqIDs,
                       rpcAddrs, mbeanPorts):
        if self.__watchdog is not None:
            raise Exception('Watchdog already exists')

        self.__watchdog = MockWatchdog(log, interval, compIDs, shortNames,
                                       daqIDs, rpcAddrs, mbeanPorts)
        return self.__watchdog

class MostlyLive(DAQLive):
    def __init__(self, port):
        super(MostlyLive, self).__init__(self.__buildArgs(port))

    def __buildArgs(self, port, extraArgs=None):
        stdArgs = { '-v' : '',
                    '-P' : str(port) }

        oldArgv = sys.argv
        try:
            sys.argv = ['foo']

            for k in stdArgs.keys():
                if extraArgs is None or not extraArgs.has_key(k):
                    sys.argv.append(k)
                    if len(stdArgs[k]) > 0:
                        sys.argv.append(stdArgs[k])

            if extraArgs is not None:
                for k in extraArgs.keys():
                    sys.argv.append(k)
                    if len(extraArgs[k]) > 0:
                        sys.argv.append(extraArgs[k])

            args = LiveArgs()
            args.parse()
        finally:
            sys.argv = oldArgv

        return args

class MoniLogTarget(object):
    MONI_TO_FILE = 1
    LOG_TO_FILE = 2
    MONI_TO_LIVE = 4
    LOG_TO_LIVE = 8
    DEFAULT = MONI_TO_FILE | LOG_TO_FILE

    def __init__(self, flags=DEFAULT):
        self.__flags = flags

    def __str__(self):
        fStr = ''
        if self.__flags & MoniLogTarget.MONI_TO_FILE:
            fStr += '|MoniToFile'
        if self.__flags & MoniLogTarget.MONI_TO_LIVE:
            fStr += '|MoniToLive'
        if self.__flags & MoniLogTarget.LOG_TO_FILE:
            fStr += '|LogToFile'
        if self.__flags & MoniLogTarget.LOG_TO_LIVE:
            fStr += '|LogToLive'
        if len(fStr) == 0:
            fStr = 'None'
        else:
            fStr = fStr[1:]
        return fStr

    def anyToFile(self):
        return (self.__flags & (MoniLogTarget.MONI_TO_FILE |
                                MoniLogTarget.LOG_TO_FILE)) != 0

    def anyToLive(self):
        return (self.__flags & (MoniLogTarget.MONI_TO_LIVE |
                                MoniLogTarget.LOG_TO_LIVE)) != 0

    def logToFile(self):
        return (self.__flags & MoniLogTarget.LOG_TO_FILE) == \
            MoniLogTarget.LOG_TO_FILE

    def logToLive(self):
        return (self.__flags & MoniLogTarget.LOG_TO_LIVE) == \
            MoniLogTarget.LOG_TO_LIVE

    def moniToFile(self):
        return (self.__flags & MoniLogTarget.MONI_TO_FILE) == \
            MoniLogTarget.MONI_TO_FILE

    def moniToLive(self):
        return (self.__flags & MoniLogTarget.MONI_TO_LIVE) == \
            MoniLogTarget.MONI_TO_LIVE

class IntegrationTest(unittest.TestCase):
    CLUSTER_CONFIG = 'sim-localhost'
    CONFIG_DIR = os.path.abspath('src/test/resources/config')
    CONFIG_NAME = 'sim5str'
    COPY_DIR = '/tmp'
    SPADE_DIR = '/tmp'
    LOG_DIR = None
    LIVEMONI_ENABLED = False

    def __createComponents(self):
        comps = [('stringHub', 1001, 9111, 9211),
                 ('stringHub', 1002, 9112, 9212),
                 ('stringHub', 1003, 9113, 9213),
                 ('stringHub', 1004, 9114, 9214),
                 ('stringHub', 1005, 9115, 9215),
                 ('stringHub', 1081, 9116, 9216),
                 ('inIceTrigger', 0, 9117, 9217),
                 ('globalTrigger', 0, 9118, 9218),
                 ('eventBuilder', 0, 9119, 9219),
                 ('secondaryBuilders', 0, 9120, 9220),]

        verbose = False

        for c in comps:
            comp = RealComponent(c[0], c[1], c[2], c[3], verbose)

            if self.__compList is None:
                self.__compList = []
            self.__compList.append(comp)

        self.__compList.sort()

    def __createLiveObjects(self, livePort):
        log = self.__logFactory.createLog('liveMoni', DAQPort.I3LIVE, False)

        log.addExpectedText('Connecting to DAQRun')
        log.addExpectedText('Started %s service on port %d' %
                            (DAQLive.SERVICE_NAME, livePort))

        self.__live = MostlyLive(livePort)

        return (self.__live, log)

    def __createLoggers(self, dr, targetFlags, liveRunOnly):
        if not targetFlags.logToFile() and not liveRunOnly:
            appender = None
            catchall = None
        else:
            appender = MockAppender('main')
            catchall = \
                StubbedDAQRun.createLogSocketServer(DAQPort.CATCHALL,
                                                    'catchall', 'catchall')

        dr.setFileAppender(appender)

        return (appender, catchall)

    def __createParallelShell(self, logPort, livePort):
        pShell = MockParallelShell()

        doLive = False
        doDAQRun = False
        doCnC = True
        dryRun = False
        verbose = False
        killWith9 = False

        dashDir = pShell.getMetaPath('dash')

        host = 'localhost'

        logLevel = 'INFO'

        pShell.addExpectedPythonKill(doLive, doDAQRun, doCnC, dashDir,
                                     killWith9)

        launchList = self.__compList[:]
        for i in range(len(launchList)):
            comp = launchList[i]
            if comp.getName() == 'stringHub' and comp.getNumber() == 1081:
                del launchList[i]
                break
        launchList.sort(RealComponent.sortForLaunch)

        for comp in launchList:
            pShell.addExpectedJavaKill(comp.getName(), killWith9, verbose, host)

        pShell.addExpectedPython(doLive, doDAQRun, doCnC, dashDir,
                                 IntegrationTest.CONFIG_DIR,
                                 IntegrationTest.LOG_DIR,
                                 IntegrationTest.SPADE_DIR,
                                 IntegrationTest.CONFIG_NAME,
                                 IntegrationTest.COPY_DIR, logPort, livePort)
        for comp in launchList:
            pShell.addExpectedJava(comp.getName(), comp.getNumber(),
                                   IntegrationTest.CONFIG_DIR, logPort,
                                   livePort, logLevel, verbose, False, host)

        return pShell

    def __createRunObjects(self, targetFlags, liveRunOnly=False):
        if targetFlags.anyToFile() and targetFlags.anyToLive() and \
                not liveRunOnly:
            extraArgs = {'-B' : '', }
        elif liveRunOnly or not targetFlags.anyToLive():
            extraArgs = None
        else:
            extraArgs = {'-L' : '', }

        self.__run = StubbedDAQRun(extraArgs)

        (appender, catchall) = \
            self.__createLoggers(self.__run, targetFlags, liveRunOnly)

        if targetFlags.logToFile() or liveRunOnly:
            logPort = DAQPort.CATCHALL
        else:
            logPort = None
        if targetFlags.logToLive() and not liveRunOnly:
            livePort = DAQPort.I3LIVE
        else:
            livePort = None
        self.__cnc = MostlyCnCServer(logPort, livePort)

        self.__createComponents()

        if liveRunOnly:
            paraLivePort = None
        else:
            paraLivePort = livePort
        pShell = \
            self.__createParallelShell(logPort, paraLivePort)

        return (self.__run, self.__cnc, appender, catchall, pShell)

    def __getConnectionList(self, name):
        if name == 'stringHub':
            connList = [('moniData', False, -1),
                        ('rdoutData', False, -1),
                        ('rdoutReq', True, -1),
                        ('snData', False, -1),
                        ('tcalData', False, -1),
                        ('stringHit', False, -1),
                        ]
        elif name == 'inIceTrigger':
            connList = [('stringHit', True, -1),
                        ('trigger', False, -1),
                        ]
        elif name == 'globalTrigger':
            connList = [('glblTrig', False, -1),
                        ('trigger', True, -1),
                        ]
        elif name == 'eventBuilder':
            connList = [('glblTrig', True, -1),
                        ('rdoutData', True, -1),
                        ('rdoutReq', False, -1),
                        ]
        elif name == 'secondaryBuilders':
            connList = [('moniData', True, -1),
                        ('snData', True, -1),
                        ('tcalData', True, -1),
                        ]
        else:
            raise Exception('Cannot get connection list for %s' % name)

        return connList

    def __registerComponents(self, liveLog, catchall, liveRunOnly):
        for comp in self.__compList:
            if catchall is not None:
                catchall.addExpectedTextRegexp(('Got registration for ID#%d' +
                                                ' %s at localhost:%d M#%d.*') %
                                               (DAQClient.ID, str(comp),
                                                comp.getCommandPort(),
                                                comp.getMBeanPort()))
                catchall.addExpectedExact('Hello from %s' % str(comp))
            if liveLog is not None and not liveRunOnly:
                liveLog.addExpectedTextRegexp(('Got registration for ID#%d %s' +
                                               ' at localhost:%d M#%d.*') %
                                              (DAQClient.ID, str(comp),
                                               comp.getCommandPort(),
                                               comp.getMBeanPort()))
                liveLog.addExpectedText('Hello from %s' % str(comp))
            comp.register(self.__getConnectionList(comp.getName()))

    def __runTest(self, live, dr, cnc, liveLog, appender, catchall,
                   targetFlags, liveRunOnly):

        try:
            self.__testBody(live, dr, cnc, liveLog, appender, catchall,
                            targetFlags, liveRunOnly)
        finally:
            dr.running = False
            time.sleep(0.4)

            cnc.closeServer()

    def __testBody(self, live, dr, cnc, liveLog, appender, catchall,
                   targetFlags, liveRunOnly):

        RUNLOG_INFO = False

        if liveLog: liveLog.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if appender: appender.checkStatus(10)

        self.__registerComponents(liveLog, catchall, liveRunOnly)

        time.sleep(0.4)
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)

        if liveLog: liveLog.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if appender: appender.checkStatus(10)

        setId = RunSet.ID
        runNum = 654
        configName = IntegrationTest.CONFIG_NAME

        if liveLog:
            liveLog.addExpectedText('Starting run %d - %s' %
                                    (runNum, configName))

        if RUNLOG_INFO:
            msg = 'Loaded global configuration "%s"' % configName
            if catchall and not liveRunOnly: catchall.addExpectedText(msg)
            if liveLog: liveLog.addExpectedText(msg)

            for n in ('in-ice', 'icetop'):
                msg = 'Configuration includes detector %s' % n
                if catchall and not liveRunOnly: catchall.addExpectedText(msg)
                if liveLog: liveLog.addExpectedText(msg)

            for c in self.__compList:
                msg = 'Component list will require %s#%d' % \
                    (c.getName(), c.getNumber())
                if catchall and not liveRunOnly: catchall.addExpectedText(msg)
                if liveLog: liveLog.addExpectedText(msg)

        msg = ('Starting run %d (waiting for required %d components to' +
               ' register w/ CnCServer)') % (runNum, len(self.__compList))
        if catchall and not liveRunOnly: catchall.addExpectedText(msg)
        if liveLog: liveLog.addExpectedText(msg)

        msg = 'Built runset with the following components:'
        if catchall: catchall.addExpectedText(msg)
        if liveLog and not liveRunOnly: liveLog.addExpectedText(msg)

        if liveLog:
            liveLog.addExpectedText("Waiting for state RUNNING for 10 seconds" +
                                    ", (currently STARTING)")

        msg = 'Created Run Set #%d' % setId
        if catchall and not liveRunOnly: catchall.addExpectedText(msg)
        if liveLog: liveLog.addExpectedText(msg)

        msgList = (('Version info: %(filename)s %(revision)s %(date)s' +
                    ' %(time)s %(author)s %(release)s %(repo_rev)s') %
                   dr.versionInfo,
                   'Starting run %d...' % runNum,
                   'Run configuration: %s' % configName,
                   'Cluster configuration: %s' %
                   IntegrationTest.CLUSTER_CONFIG
                   )
        if RUNLOG_INFO:
            msgList.append('Created logger for CnCServer')

        for msg in msgList:
            if appender and not liveRunOnly: appender.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

        if appender and not liveRunOnly and RUNLOG_INFO:
            msg = 'Setting up logging for %d components' % len(self.__compList)
            appender.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

            nextPort = DAQPort.RUNCOMP_BASE
            for c in self.__compList:
                patStr = r'%s\(\d+ \S+:%d\) -> %s:%d' % \
                    (c.getName(), c.getCommandPort(), dr.ip, nextPort)
                appender.addExpectedRegexp(patStr)
                if liveLog: liveLog.addExpectedTextRegexp(patStr)
                nextPort += 1
        if liveLog:
            for c in self.__compList:
                liveLog.addExpectedText('Hello from %s' % str(c))
                liveLog.addExpectedTextRegexp((r'Version info: %s \S+ \S+' +
                                               r' \S+ \S+ \S+ \d+\S+') %
                                              c.getName())

        if RUNLOG_INFO:
            msg = 'Configuring run set...'
            if appender and not liveRunOnly: appender.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

            if targetFlags.moniToFile():
                runDir = os.path.join(IntegrationTest.LOG_DIR,
                                      DAQRun.logDirName(runNum))
                for c in self.__compList:
                    msg = ('Creating moni output file %s/%s-%d.moni' +
                           ' (remote is localhost:%d)') % \
                           (runDir, c.getName(), c.getNumber(),
                            c.getMBeanPort())
                    if appender and not liveRunOnly:
                        appender.addExpectedExact(msg)
                    if liveLog: liveLog.addExpectedText(msg)

        if liveLog:
            for c in self.__compList:
                liveLog.addExpectedText('Start #%d on %s' % (runNum, str(c)))

        msg = 'Started run %d on run set %d' % (runNum, setId)
        if appender and not liveRunOnly: appender.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        if liveLog:
            liveLog.addExpectedTextRegexp(r"DAQ state is RUNNING after \d+" +
                                          " seconds")
            liveLog.addExpectedText('Started run %d' % runNum)

        msg = '0 physics events (0.00 Hz), 0 moni events, 0 SN events, 0 tcals'
        if appender and not liveRunOnly: appender.addExpectedExact('\t' + msg)
        if liveLog: liveLog.addExpectedText(msg)

        if targetFlags.moniToLive():
            # monitoring values can potentially come in any order
            liveLog.setCheckDepth(32)
            for c in self.__compList:
                c.addI3LiveMonitoring(liveLog)

        if live is not None:
            live.starting({'runNumber':runNum, 'runConfig':configName})
        else:
            dr.rpc_start_run(runNum, None, configName)

        numTries = 0
        while dr.runState == 'STARTING' and numTries < 500:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('RUNNING', dr.runState, 'Should be running, not ' +
                          dr.runState)

        dr.forceMonitoring()
        dr.forceWatchdog()

        if liveLog: liveLog.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if appender: appender.checkStatus(500)

        if targetFlags.moniToLive():
            liveLog.setCheckDepth(5)

        subRunId = 1

        if liveLog: liveLog.addExpectedText('Starting subrun %d.%d' %
                                            (runNum, subRunId))

        domList = [('53494d550101', 0, 1, 2, 3, 4),
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

        msg = ("Subrun %d: will ignore missing DOM ('DOM %s not found in" +
               " config!')...") % (subRunId, domList[2][0])
        if appender and not liveRunOnly: appender.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        fmt = 'Subrun %d: flashing DOMs (%%s)' % subRunId
        if appender and not liveRunOnly:
            if liveLog:
                appender.addExpectedExact(fmt % str(rpcFlashList))
            else:
                appender.addExpectedExact(fmt % str(rawFlashList))
        if liveLog: liveLog.addExpectedText(fmt % str(rpcFlashList))

        for c in self.__compList:
            if not appender or liveRunOnly:
                clog = None
            else:
                clog = StubbedDAQRun.getComponentLog(c.getName(), c.getNumber())
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
            dr.rpc_flash(subRunId, domList)

        if appender: appender.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)

        subRunId += 1

        if liveLog: liveLog.addExpectedText('Stopping subrun %d.%d' %
                                            (runNum, subRunId))

        msg = 'Subrun %d: Got command to stop flashers' % subRunId
        if appender and not liveRunOnly: appender.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        for c in self.__compList:
            if not appender or liveRunOnly:
                clog = None
            else:
                clog = StubbedDAQRun.getComponentLog(c.getName(), c.getNumber())
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
            dr.rpc_flash(subRunId, [])

        if appender: appender.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)

        if liveLog: liveLog.addExpectedText('Stopping run %d' % runNum)

        numEvts = 17
        numMoni = 222
        numSN = 51
        numTCal = 93

        for c in self.__compList:
            if c.getName() == 'eventBuilder':
                c.setMBean('backEnd', 'NumEventsSent', numEvts)
            elif c.getName() == 'secondaryBuilders':
                c.setMBean('moniBuilder', 'TotalDispatchedData', numMoni)
                c.setMBean('snBuilder', 'TotalDispatchedData', numSN)
                c.setMBean('tcalBuilder', 'TotalDispatchedData', numTCal)

        msg = 'Stopping run %d' % runNum
        if appender and not liveRunOnly: appender.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        for c in self.__compList:
            if not appender or liveRunOnly:
                clog = None
            else:
                clog = StubbedDAQRun.getComponentLog(c.getName(), c.getNumber())
                if clog is None:
                    raise Exception('No log for %s#%d' %
                                    (c.getName(), c.getNumber()))

            msg = 'Stop %s#%d' % (c.getName(), c.getNumber())
            if clog: clog.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

        if catchall:
            catchall.addExpectedTextRegexp(r'Reset log to \S+:\d+')
            if liveLog and not liveRunOnly:
                liveLog.addExpectedTextRegexp(r'Reset log to \S+:\d+')

        patStr = (r'%d physics events collected in \d+ seconds' +
                  r'(\s+\(\d+\.\d+ Hz\))?') % numEvts
        if appender and not liveRunOnly: appender.addExpectedRegexp(patStr)
        if liveLog: liveLog.addExpectedTextRegexp(patStr)

        msg = '%d moni events, %d SN events, %d tcals' % \
            (numMoni, numSN, numTCal)
        if appender and not liveRunOnly: appender.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        if RUNLOG_INFO:
            msg = 'Stopping component logging'
            if appender and not liveRunOnly: appender.addExpectedExact(msg)
            if liveLog: liveLog.addExpectedText(msg)

            patStr = 'RPC Call stats:.*'
            if appender and not liveRunOnly: appender.addExpectedRegexp(patStr)
            if liveLog: liveLog.addExpectedTextRegexp(patStr)

        msg = 'Run terminated SUCCESSFULLY.'
        if appender and not liveRunOnly: appender.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        if RUNLOG_INFO:
            if targetFlags.moniToFile():
                msg = ('Queueing data for SPADE (spadeDir=%s, logDir=%s,' +
                       ' runNum=%s)...') % \
                       (IntegrationTest.SPADE_DIR, IntegrationTest.LOG_DIR,
                        runNum)
                if appender and not liveRunOnly: appender.addExpectedExact(msg)
                if liveLog: liveLog.addExpectedText(msg)

        msg = "Doing complete rip-down and restart of pDAQ" + \
            " (everything but DAQRun)"
        if appender and not liveRunOnly: appender.addExpectedExact(msg)
        if liveLog: liveLog.addExpectedText(msg)

        if liveLog:
            liveLog.addExpectedTextRegexp(r"DAQ state is STOPPED after \d+" +
                                          " seconds")
            liveLog.addExpectedText('Stopped run %d' % runNum)

            liveLog.addExpectedLiveMoni('tcalEvents', numTCal)
            liveLog.addExpectedLiveMoni('moniEvents', numMoni)
            liveLog.addExpectedLiveMoni('snEvents', numSN)
            liveLog.addExpectedLiveMoni('physicsEvents', numEvts)

        if live is not None:
            live.stopping()
        else:
            dr.rpc_stop_run()

        numTries = 0
        while dr.runState == 'STOPPING' and numTries < 100:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)

        if appender: appender.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)

        moni = dr.rpc_run_monitoring()
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

        if appender: appender.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)

        if RUNLOG_INFO:
            msg = 'Breaking run set...'
            if liveLog and not liveRunOnly: liveLog.addExpectedText(msg)
            if catchall:
                catchall.addExpectedText(msg)

        if catchall:
            endMsg = 'End of log'
            for key in MostlyCnCServer.APPENDERS:
                if key != 'server':
                    MostlyCnCServer.APPENDERS[key].addExpectedExact(endMsg)

        if live is not None:
            live.release()
        else:
            dr.rpc_release_runsets()

        if appender: appender.checkStatus(10)
        if catchall: catchall.checkStatus(10)
        if liveLog: liveLog.checkStatus(10)

    def setUp(self):
        StubbedDAQRun.clearLogs()
        MockMoniFile.clear()
        MostlyCnCServer.APPENDERS.clear()

        self.__logFactory = SocketReaderFactory()

        StubbedDAQRun.LOGFACTORY = self.__logFactory

        IntegrationTest.LOG_DIR = tempfile.mkdtemp()

        self.__live = None
        self.__run = None
        self.__cnc = None
        self.__compList = None

    def tearDown(self):
        MockMoniFile.check()

        self.__logFactory.tearDown()

        if self.__compList is not None and len(self.__compList) > 0:
            for c in self.__compList:
                c.close()
        if self.__cnc is not None:
            self.__cnc.closeServer()
        if self.__run is not None:
            if self.__run.running:
                self.__run.running = False
                time.sleep(0.4)
            self.__run.server.server_close()
        if self.__live is not None:
            self.__live.close()

        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].checkStatus(10)

        for root, dirs, files in os.walk(IntegrationTest.LOG_DIR,
                                         topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(IntegrationTest.LOG_DIR)
        IntegrationTest.LOG_DIR = None

    def testFinishInMain(self):
        targetFlags = MoniLogTarget(MoniLogTarget.MONI_TO_FILE |
                                    MoniLogTarget.LOG_TO_FILE)

        (dr, cnc, appender, catchall, pShell) = \
            self.__createRunObjects(targetFlags)

        catchall.addExpectedText("I'm server %s running on port %d" %
                                 (cnc.name, DAQPort.CNCSERVER))
        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        thread.start_new_thread(cnc.run, ())
        thread.start_new_thread(dr.run_thread, (None, pShell))

        self.__runTest(None, dr, cnc, None, appender, catchall, targetFlags,
                       False)

    def testDAQRunInMain(self):
        if sys.platform != 'darwin':
            print 'Skipping server tests in non-Darwin OS'
            return

        targetFlags = MoniLogTarget(MoniLogTarget.MONI_TO_FILE |
                                    MoniLogTarget.LOG_TO_FILE)

        (dr, cnc, appender, catchall, pShell) = \
            self.__createRunObjects(targetFlags)

        catchall.addExpectedText("I'm server %s running on port %d" %
                                  (cnc.name, DAQPort.CNCSERVER))
        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        thread.start_new_thread(cnc.run, ())
        thread.start_new_thread(self.__runTest,
                                (None, dr, cnc, None, appender, catchall,
                                 targetFlags, False))

        dr.run_thread(None, pShell)

    def testCnCInMain(self):
        if sys.platform != 'darwin':
            print 'Skipping server tests in non-Darwin OS'
            return

        targetFlags = MoniLogTarget(MoniLogTarget.MONI_TO_FILE |
                                    MoniLogTarget.LOG_TO_FILE)

        (dr, cnc, appender, catchall, pShell) = \
            self.__createRunObjects(targetFlags)

        catchall.addExpectedText("I'm server %s running on port %d" %
                                 (cnc.name, DAQPort.CNCSERVER))
        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        thread.start_new_thread(dr.run_thread, (None, pShell))
        thread.start_new_thread(self.__runTest,
                                (None, dr, cnc, None, appender, catchall,
                                 targetFlags, False))

        cnc.run()

    def testLiveFinishInMain(self):
        if not TEST_LIVE:
            print 'Skipping I3Live-related test'
            return

        livePort = 9751

        targetFlags = MoniLogTarget(MoniLogTarget.MONI_TO_FILE |
                                    MoniLogTarget.LOG_TO_LIVE)

        (dr, cnc, appender, catchall, pShell) = \
            self.__createRunObjects(targetFlags, True)

        catchall.addExpectedText("I'm server %s running on port %d" %
                                 (cnc.name, DAQPort.CNCSERVER))
        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        thread.start_new_thread(cnc.run, ())
        thread.start_new_thread(dr.run_thread, (None, pShell))
        thread.start_new_thread(dr.server.serve_forever, ())

        (live, liveLog) = self.__createLiveObjects(livePort)

        self.__runTest(live, dr, cnc, liveLog, appender, catchall, targetFlags,
                       True)

    def testAllLiveFinishInMain(self):
        #from DAQMocks import LogChecker; LogChecker.DEBUG = True
        if not TEST_LIVE:
            print 'Skipping I3Live-related test'
            return

        livePort = 9751

        if IntegrationTest.LIVEMONI_ENABLED:
            liveMoniFlag = MoniLogTarget.MONI_TO_LIVE
        else:
            liveMoniFlag = 0

        targetFlags = MoniLogTarget(liveMoniFlag |
                                    MoniLogTarget.LOG_TO_LIVE)

        (dr, cnc, appender, catchall, pShell) = \
            self.__createRunObjects(targetFlags)

        thread.start_new_thread(dr.run_thread, (None, pShell))
        thread.start_new_thread(dr.server.serve_forever, ())

        (live, liveLog) = self.__createLiveObjects(livePort)

        liveLog.addExpectedText("I'm server %s running on port %d" %
                                 (cnc.name, DAQPort.CNCSERVER))
        liveLog.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        thread.start_new_thread(cnc.run, ())

        liveLog.checkStatus(100)

        self.__runTest(live, dr, cnc, liveLog, appender, catchall, targetFlags,
                       False)

    def testBothFinishInMain(self):
        if not TEST_LIVE:
            print 'Skipping I3Live-related test'
            return

        livePort = 9751

        if IntegrationTest.LIVEMONI_ENABLED:
            liveMoniFlag = MoniLogTarget.MONI_TO_LIVE
        else:
            liveMoniFlag = 0

        targetFlags = MoniLogTarget(MoniLogTarget.MONI_TO_FILE |
                                    MoniLogTarget.LOG_TO_FILE |
                                    liveMoniFlag |
                                    MoniLogTarget.LOG_TO_LIVE)

        (dr, cnc, appender, catchall, pShell) = \
            self.__createRunObjects(targetFlags)

        thread.start_new_thread(dr.run_thread, (None, pShell))
        thread.start_new_thread(dr.server.serve_forever, ())

        (live, liveLog) = self.__createLiveObjects(livePort)

        msg = "I'm server %s running on port %d" % (cnc.name, DAQPort.CNCSERVER)
        catchall.addExpectedText(msg)
        liveLog.addExpectedText(msg)

        patStr = r'\S+ \S+ \S+ \S+ \S+ \S+ \S+'
        catchall.addExpectedTextRegexp(patStr)
        liveLog.addExpectedTextRegexp(patStr)

        thread.start_new_thread(cnc.run, ())

        #from DAQMocks import LogChecker; LogChecker.DEBUG = True
        self.__runTest(live, dr, cnc, liveLog, appender, catchall, targetFlags,
                       False)

if __name__ == '__main__':
    unittest.main()
