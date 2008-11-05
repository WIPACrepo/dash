#!/usr/bin/env python

import StringIO, os, re, sys
import tempfile, thread, time, unittest, xmlrpclib

from CnCServer import CnCServer, DAQClient, RunSet
from DAQLogClient import DAQLog
from DAQMoni import DAQMoni, MoniData
from DAQRPC import RPCServer
from DAQRun import DAQRun, RunArgs
from RunWatchdog import RunWatchdog, WatchData

from DAQMocks \
    import MockAppender, MockCnCLogger, SocketReaderFactory, SocketWriter

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

class MockMoniData(MoniData):
    DATA = CachedData()

    BEAN_PAT = re.compile(r'^(\S+):\s*\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+:\s*$')
    DATA_PAT = re.compile(r'^\s+(\S+):\s*(.*)$')

    def __init__(self, name, daqId, addr, port):
        self.__stringFile = None

        super(MockMoniData, self).__init__(name, daqId, None, addr, port)

        MockMoniData.DATA.add(name, daqId, self)

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

class MockMoni(DAQMoni):
    def __init__(self, log, moniPath, interval, IDs, names, daqIDs, addrs,
                 mbeanPorts):
        super(MockMoni, self).__init__(log, moniPath, interval, IDs, names,
                                       daqIDs, addrs, mbeanPorts, True)

    def createData(self, name, daqId, fname, addr, port):
        return MockMoniData(name, daqId, addr, port)

class MockWatchData(WatchData):
    def __init__(self, id, name, daqId, addr, port):
        super(MockWatchData, self).__init__(id, name, daqId, addr, port)

class MockWatchdog(RunWatchdog):
    def __init__(self, daqLog, interval, IDs, shortNameOf, daqIDof,
                 rpcAddrOf, mbeanPortOf):
        self.__count = 0

        super(MockWatchdog, self).__init__(daqLog, interval, IDs, shortNameOf,
                                           daqIDof, rpcAddrOf, mbeanPortOf,
                                           True)

    def createData(self, id, name, daqId, addr, port):
        return MockWatchData(id, name, daqId, addr, port)

    def getCount(self): return self.__count

    def clearThread(self):
        super(MockWatchdog, self).clearThread()
        self.__count += 1

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

    def __init__(self, logIP='localhost', logPort=-1):
        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              logIP=logIP, logPort=logPort,
                                              quiet=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        key = '%s#%d' % (name, num)
        if not MostlyCnCServer.APPENDERS.has_key(key):
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MostlyDAQClient(name, num, host, port, mbeanPort, connectors,
                               MostlyCnCServer.APPENDERS[key])

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

    def __init__(self, name, num, cmdPort, mbeanPort, cncPort, verbose=False):
        self.__id = None
        self.__name = name
        self.__num = num

        self.__state = 'FOO'

        self.__logger = None
        self.__mbeanData = None

        self.__cmd = RPCServer(cmdPort)
        self.__cmd.register_function(self.__commitSubrun, 'xmlrpc.commitSubrun')
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__getState, 'xmlrpc.getState')
        self.__cmd.register_function(self.__getVersionInfo,
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

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' % cncPort,
                                           verbose=verbose)

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

    def __commitSubrun(self, id, latestTime):
        self.__logger.write('Commit subrun %d: %s' % (id, str(latestTime)))
        return 'COMMIT'

    def __configure(self, cfgName=None):
        if self.__logger is None:
            raise Exception('No logging for %s#%d' % (self.__name, self.__num))

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

    def __getVersionInfo(self):
        return '$Id: filename revision date time author xxx'

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

    def __logTo(self, host, port):
        self.__logger = SocketWriter(host, port)
        self.__logger.write('Hello from %s#%d' % (self.__name, self.__num))
        return 'OK'

    def __prepareSubrun(self, id):
        self.__logger.write('Prep subrun %d' % id)
        return 'PREP'

    def __reset(self):
        self.__state = 'idle'
        return 'RESET'

    def __resetLogging(self):
        self.__logger = None

        self.__state = 'reset'
        return 'RLOG'

    def __startRun(self, runNum):
        if self.__logger is None:
            raise Exception('No logging for %s#%d' % (self.__name, self.__num))

        self.__logger.write('Start #%d on %s#%d' %
                            (runNum, self.__name, self.__num))

        self.__state = 'running'
        return 'RUN#%d' % runNum

    def __startSubrun(self, data):
        self.__logger.write('Start subrun %s' % str(data))
        return long(time.time())

    def __stopRun(self):
        if self.__logger is None:
            raise Exception('No logging for %s#%d' % (self.__name, self.__num))

        self.__logger.write('Stop %s#%d' % (self.__name, self.__num))

        self.__state = 'stopped'
        return 'STOP'

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
        self.__id = reg[0]
        self.__logTo(reg[1], reg[2])

    def setMBean(self, bean, fld, val):
        if self.__mbeanData is None:
            self.__mbeanData = BeanData.buildDAQBeans(self.__name)

        self.__mbeanData[bean][fld].setValue(val)

class StubbedDAQRun(DAQRun):
    LOGFACTORY = None
    LOGDICT = {}

    def __init__(self, args, startServer):
        self.__watchdog = None

        self.__fileAppender = None
        self.__mockAppender = None
        self.__logServer = None

        self.liveLog = None
        self.catchAllLog = None

        super(StubbedDAQRun, self).__init__(args, startServer)

    def clearLogs(cls):
        cls.LOGDICT.clear()
    clearLogs = classmethod(clearLogs)

    def createDAQLog(self):
        if self.__mockAppender is None:
            self.__mockAppender = MockAppender('runlog')

        return DAQLog(self.__mockAppender)

    def createFileAppender(self):
        return self.__fileAppender

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
            log.addExpectedTextRegexp('Version info: filename revision date' +
                                      r' time author \S+ \d+\S+')
            if logPort != DAQRun.CATCHALL_PORT:
                log.addExpectedRegexp('Start #\d+ on \S+#\d+')

        return log

    createLogSocketServer = classmethod(createLogSocketServer)

    def createRunLogDirectory(self, runNum, logDir):
        self.setLogPath(runNum, logDir)

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

    def restartComponents(self):
        pass

    def setFileAppender(self, appender):
        self.__fileAppender = appender

    def setup_monitoring(self, log, moniPath, interval, compIDs, shortNames,
                         daqIDs, rpcAddrs, mbeanPorts):
        return MockMoni(log, moniPath, interval, compIDs, shortNames, daqIDs,
                         rpcAddrs, mbeanPorts)

    def setup_watchdog(self, log, interval, compIDs, shortNames, daqIDs,
                       rpcAddrs, mbeanPorts):
        if self.__watchdog is not None:
            raise Exception('Watchdog already exists')

        self.__watchdog = MockWatchdog(log, interval, compIDs, shortNames,
                                       daqIDs, rpcAddrs, mbeanPorts)
        return self.__watchdog

class IntegrationTest(unittest.TestCase):
    NEXTPORT = 9876
    CLUSTER_CONFIG = 'sim-localhost'
    SPADE_DIR = '/tmp'
    LOG_DIR = None

    def __createComponent(self, name, num, cmdPort, mbeanPort, cncPort,
                          verbose):
        comp = RealComponent(name, num, cmdPort, mbeanPort, cncPort, verbose)

        if self.__compList is None:
            self.__compList = []
        self.__compList.append(comp)

        return comp

    def __createLoggers(self, dr):
        appender = MockAppender('main')
        dr.setFileAppender(appender)

        catchall = \
            StubbedDAQRun.createLogSocketServer(DAQRun.CATCHALL_PORT,
                                                'catchall', 'catchall')

        return (appender, catchall)

    def __createRunObjects(self):
        dr = StubbedDAQRun(self.__getRunArgs(), False)

        (appender, catchall) = self.__createLoggers(dr)

        self.__cnc = MostlyCnCServer(logPort=DAQRun.CATCHALL_PORT)

        return (dr, self.__cnc, appender, catchall)

    def __finishRunThreadTest(self, dr, cnc, appender, catchall):

        self.__startComponents(cnc.port, catchall)

        time.sleep(0.4)
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)

        setId = RunSet.ID
        runNum = 654
        configName = 'sim5str'

        catchall.addExpectedText('Loaded global configuration "%s"' %
                                 configName)
        catchall.addExpectedText('Configuration includes detector in-ice')
        catchall.addExpectedText('Configuration includes detector icetop')

        compSrt = self.__getOrderedComponents()

        for c in compSrt:
            catchall.addExpectedText('Component list will require %s#%d' %
                                     (c.getName(), c.getNumber()))

        catchall.addExpectedText(('Starting run %d (waiting for required %d' +
                                  ' components to register w/ CnCServer)') %
                                 (runNum, len(compSrt)))

        catchall.addExpectedText('Built runset with the following components:')

        catchall.addExpectedText('Created Run Set #%d' % setId)

        appender.addExpectedExact(('Version info: %(filename)s %(revision)s' +
                                   ' %(date)s %(time)s %(author)s %(release)s' +
                                   ' %(repo_rev)s') % dr.versionInfo)
        appender.addExpectedExact('Starting run %d...' % runNum)
        appender.addExpectedExact('Run configuration: %s' % configName)
        appender.addExpectedExact('Cluster configuration: %s' %
                                  IntegrationTest.CLUSTER_CONFIG)
        appender.addExpectedExact('Created logger for CnCServer')
        appender.addExpectedExact('Setting up logging for %d components' %
                                  len(compSrt))

        nextPort = 9002
        for c in compSrt:
            appender.addExpectedRegexp(r'%s\(\d+ \S+:%d\) -> %s:%d' %
                                       (c.getName(), c.getCommandPort(), dr.ip,
                                        nextPort))
            nextPort += 1

        runDir = os.path.join(IntegrationTest.LOG_DIR,
                              DAQRun.logDirName(runNum))

        appender.addExpectedExact('Configuring run set...')
        for c in compSrt:
            appender.addExpectedExact(('Creating moni output file %s/%s-%d' +
                                       '.moni (remote is localhost:%d)') %
                                      (runDir, c.getName(), c.getNumber(),
                                       c.getMBeanPort()))

        appender.addExpectedExact('Started run %d on run set %d' %
                                  (runNum, setId))
        appender.addExpectedExact('\t0 physics events (0.00 Hz), 0 moni' +
                                  ' events, 0 SN events, 0 tcals')

        dr.rpc_start_run(runNum, None, configName)

        numTries = 0
        while dr.runState == 'STARTING' and numTries < 500:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('RUNNING', dr.runState, 'Should be running, not ' +
                          dr.runState)
        catchall.checkEmpty()

        numTries = 0
        while not appender.isEmpty() and numTries < 500:
            time.sleep(0.1)
            numTries += 1

        appender.checkEmpty()

        # wait for watchdog to finish running
        numTries = 0
        while dr.getWatchCount() <= 0 and numTries < 10:
            time.sleep(0.1)
            numTries += 1

        subRunId = 1
        domList = [('53494d550101', 0, 1, 2, 3, 4),
                   ['1001', '22', 1, 2, 3, 4, 5],
                   ('a', 0, 1, 2, 3, 4)]

        flashList = [domList[0], ['53494d550122', ] + domList[1][2:]]
        appender.addExpectedExact(("Subrun %d: will ignore missing DOM (" +
                                   "'DOM %s not found in config!')...") %
                                  (subRunId, domList[2][0]))
        appender.addExpectedExact('Subrun %d: flashing DOMs (%s)' %
                                  (subRunId, str(flashList)))

        for c in compSrt:
            clog = StubbedDAQRun.getComponentLog(c.getName(), c.getNumber())
            if clog is None:
                raise Exception('No log for %s#%d' %
                                (c.getName(), c.getNumber()))
            if c.getName() == 'eventBuilder':
                clog.addExpectedExact('Prep subrun %d' % subRunId)
                clog.addExpectedRegexp('Commit subrun %d: \d+L' % subRunId)
            elif c.getName() == 'stringHub':
                clog.addExpectedRegexp('Start subrun .*')

        dr.rpc_flash(subRunId, domList)
        appender.checkEmpty()
        catchall.checkEmpty()

        numEvts = 17
        numMoni = 222
        numSN = 51
        numTCal = 93

        for c in compSrt:
            if c.getName() == 'eventBuilder':
                c.setMBean('backEnd', 'NumEventsSent', numEvts)
            elif c.getName() == 'secondaryBuilders':
                c.setMBean('moniBuilder', 'TotalDispatchedData', numMoni)
                c.setMBean('snBuilder', 'TotalDispatchedData', numSN)
                c.setMBean('tcalBuilder', 'TotalDispatchedData', numTCal)

        appender.addExpectedExact('Stopping run %d' % runNum)

        for c in compSrt:
            clog = StubbedDAQRun.getComponentLog(c.getName(), c.getNumber())
            if clog is None:
                raise Exception('No log for %s#%d' %
                                (c.getName(), c.getNumber()))
            clog.addExpectedExact('Stop %s#%d' % (c.getName(), c.getNumber()))

        catchall.addExpectedTextRegexp(r'Reset log to \S+:\d+')

        appender.addExpectedRegexp((r'%d physics events collected in \d+' +
                                    r' seconds(\s+\(\d+\.\d+ Hz\))?') % numEvts)
        appender.addExpectedExact('%d moni events, %d SN events, %d tcals' %
                                  (numMoni, numSN, numTCal))
        appender.addExpectedExact('Stopping component logging')
        appender.addExpectedRegexp('RPC Call stats:.*')
        appender.addExpectedExact('Run terminated SUCCESSFULLY.')
        appender.addExpectedExact(('Queueing data for SPADE (spadeDir=%s,' +
                                   ' logDir=%s, runNum=%s)...') %
                                  (IntegrationTest.SPADE_DIR,
                                   IntegrationTest.LOG_DIR, runNum))

        dr.rpc_stop_run()

        numTries = 0
        while dr.runState == 'STOPPING' and numTries < 100:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)
        appender.checkEmpty()
        catchall.checkEmpty()

        #basePrefix = dr.get_base_prefix(runNum, None, None)

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
        appender.checkEmpty()
        catchall.checkEmpty()

        catchall.addExpectedText('Breaking run set...')
        for key in MostlyCnCServer.APPENDERS:
            if key != 'server':
                MostlyCnCServer.APPENDERS[key].addExpectedExact('End of log')

        dr.rpc_release_runsets()
        appender.checkEmpty()

        dr.running = False
        time.sleep(0.4)

        cnc.closeServer()

        numTries = 0
        while not catchall.isEmpty() and numTries < 500:
            time.sleep(0.1)
            numTries += 1

        appender.checkEmpty()
        catchall.checkEmpty()
        if catchall.isError(): self.fail(catchall.getError())

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

    def __getOrderedComponents(self):
        lst = self.__compList[:]
        lst.sort()
        return lst

    def __getRunArgs(self, extraArgs=None):

        stdArgs = { '-c' : 'src/test/resources/config',
                    '-l' : IntegrationTest.LOG_DIR,
                    '-n' : '',
                    '-p' : str(IntegrationTest.NEXTPORT),
                    '-q' : '',
                    '-s' : IntegrationTest.SPADE_DIR,
                    '-u' : IntegrationTest.CLUSTER_CONFIG }
        IntegrationTest.NEXTPORT += 1

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

    def __startComponents(self, cncPort, catchall):
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
            comp = self.__createComponent(c[0], c[1], c[2], c[3], cncPort,
                                          verbose)

            catchall.addExpectedTextRegexp(('Got registration for ID#%d %s#%d' +
                                            ' at localhost:%d M#%d') %
                                           (DAQClient.ID, c[0], c[1], c[2],
                                            c[3]))
            catchall.addExpectedExact('Hello from %s#%d' % (c[0], c[1]))

            comp.register(self.__getConnectionList(c[0]))

    def setUp(self):
        StubbedDAQRun.clearLogs()
        MockMoniData.clear()
        MostlyCnCServer.APPENDERS.clear()

        self.__logFactory = SocketReaderFactory()

        StubbedDAQRun.LOGFACTORY = self.__logFactory

        IntegrationTest.LOG_DIR = tempfile.mkdtemp()

        self.__compList = None
        self.__cnc = None

    def tearDown(self):
        MockMoniData.check()

        self.__logFactory.tearDown()

        if self.__compList is not None and len(self.__compList) > 0:
            for c in self.__compList:
                c.close()
        if self.__cnc is not None:
            self.__cnc.closeServer()

        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].checkEmpty()

        for root, dirs, files in os.walk(IntegrationTest.LOG_DIR,
                                         topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(IntegrationTest.LOG_DIR)
        IntegrationTest.LOG_DIR = None

    def testFinishInMain(self):
        (dr, cnc, appender, catchall) = self.__createRunObjects()

        catchall.addExpectedText("I'm server %s running on port %d" %
                                 (cnc.name, cnc.port))
        catchall.addExpectedTextRegexp('unknown unknown unknown unknown' +
                                       r' unknown \S+ \S+')

        thread.start_new_thread(cnc.run, ())
        thread.start_new_thread(dr.run_thread, ())

        self.__finishRunThreadTest(dr, cnc, appender, catchall)

    def testDAQRunInMain(self):
        (dr, cnc, appender, catchall) = self.__createRunObjects()

        catchall.addExpectedText("I'm server %s running on port %d" %
                                  (cnc.name, cnc.port))
        catchall.addExpectedTextRegexp('unknown unknown unknown unknown' +
                                       r' unknown \S+ \S+')

        thread.start_new_thread(cnc.run, ())
        thread.start_new_thread(self.__finishRunThreadTest,
                                (dr, cnc, appender, catchall))
        dr.run_thread()

    def testCnCInMain(self):
        (dr, cnc, appender, catchall) = self.__createRunObjects()

        catchall.addExpectedText("I'm server %s running on port %d" %
                                 (cnc.name, cnc.port))
        catchall.addExpectedTextRegexp('unknown unknown unknown unknown' +
                                       r' unknown \S+ \S+')

        thread.start_new_thread(dr.run_thread, ())
        thread.start_new_thread(self.__finishRunThreadTest,
                                (dr, cnc, appender, catchall))
        cnc.run()

if __name__ == '__main__':
    unittest.main()
