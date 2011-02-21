#!/usr/bin/env python

import shutil, socket, tempfile, traceback, unittest
from CnCServer import CnCServer, CnCServerException
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQMocks import MockAppender, MockClusterConfig, MockCnCLogger, \
    MockRunConfigFile, SocketReaderFactory, SocketWriter
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet
from utils import ip

CAUGHT_WARNING = False

class TinyClient(object):
    def __init__(self, name, num, host, port, mbeanPort, connectors):
        self.__name = name
        self.__num = num
        self.__connectors = connectors

        self.__id = DAQClient.ID.next()

        self.__host = host
        self.__port = port
        self.__mbeanPort = mbeanPort

        self.__state = 'idle'
        self.__order = None

    def __str__(self):
        if self.__mbeanPort == 0:
            mStr = ''
        else:
            mStr = ' M#%d' % self.__mbeanPort
        return 'ID#%d %s#%d at %s:%d%s' % \
            (self.__id, self.__name, self.__num, self.__host, self.__port, mStr)

    def configure(self, cfgName=None):
        self.__state = 'ready'

    def connect(self, connList=None):
        self.__state = 'connected'

    def connectors(self):
        return self.__connectors[:]

    def fullName(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def id(self):
        return self.__id

    def isComponent(self, name, num=-1):
        return self.__name == name and (num < 0 or self.__num == num)

    def isSource(self):
        return True

    def logTo(self, logIP, logPort, liveIP, livePort):
        if liveIP is not None and livePort is not None:
            raise Exception('Cannot log to I3Live')

        self.__log = SocketWriter(logIP, logPort)
        self.__log.write_ts('Start of log at LOG=log(%s:%d)' % (logIP, logPort))
        self.__log.write_ts('Version info: unknown 000 unknown unknown' +
                            ' unknown BRANCH 0:0')

    def map(self):
        return { "id" : self.__id,
                 "compName" : self.__name,
                 "compNum" : self.__num,
                 "host" : self.__host,
                 "rpcPort" : self.__port,
                 "mbeanPort" : self.__mbeanPort,
                 "state" : self.__state}

    def name(self):
        return self.__name

    def num(self):
        return self.__num

    def order(self):
        return self.__order

    def reset(self):
        self.__state = 'idle'

    def resetLogging(self):
        pass

    def setOrder(self, orderNum):
        self.__order = orderNum

    def startRun(self, runNum):
        self.__state = 'running'

    def state(self):
        return self.__state

    def stopRun(self):
        self.__state = 'ready'

class FakeTaskManager(object):
    def __init__(self): pass
    def reset(self): pass
    def start(self): pass
    def stop(self): pass

class MockRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger, clientLog=None):
        self.__dashLog = logger
        self.__clientLog = clientLog
        self.__deadComp = []

        super(MockRunSet, self).__init__(parent, runConfig, compList, logger)

    def createComponentLog(self, runDir, c, host, port, liveHost, livePort,
                           quiet=True):
        return self.__clientLog

    def createDashLog(self):
        return self.__dashLog

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir=None, logDir=None):
        return super(MockRunSet, self).createRunData(runNum,
                                                     clusterConfigName,
                                                     runOptions, versionInfo,
                                                     spadeDir, copyDir,
                                                     logDir, True)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        return None

    def createTaskManager(self, dashlog, liveMoniClient, runDir, runCfg,
                          moniType):
        return FakeTaskManager()

    def queueForSpade(self, duration):
        pass

class MockServer(CnCServer):
    APPENDER = MockAppender('server')

    def __init__(self, clusterConfigObject=None, copyDir=None,
                 runConfigDir=None, spadeDir=None, logPort=None, livePort=None,
                 forceRestart=False, clientLog=None, logFactory=None):
        self.__clusterConfig = clusterConfigObject
        self.__clientLog = clientLog
        self.__logFactory = logFactory

        super(MockServer, self).__init__(copyDir=copyDir,
                                         runConfigDir=runConfigDir,
                                         spadeDir=spadeDir,
                                         logIP='localhost', logPort=logPort,
                                         liveIP='localhost', livePort=livePort,
                                         forceRestart=forceRestart,
                                         testOnly=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        return TinyClient(name, num, host, port, mbeanPort, connectors)

    def createCnCLogger(self, quiet):
        return MockCnCLogger(MockServer.APPENDER, quiet)

    def createRunset(self, runConfig, compList, logger):
        return MockRunSet(self, runConfig, compList, logger,
                          clientLog=self.__clientLog)

    def getClusterConfig(self):
        return self.__clusterConfig

    def openLogServer(self, port, logDir):
        if self.__logFactory is None:
            raise Exception("MockServer log factory has not been set")
        return self.__logFactory.createLog("catchall", port,
                                           expectStartMsg=False,
                                           startServer=False)

    def saveCatchall(self, runDir):
        pass

    def startLiveThread(self):
        return None

class TestDAQServer(unittest.TestCase):
    HUB_NUMBER = 1021
    DOM_MAINBOARD_ID = "53494d552101"

    def __createLog(self, name, port, expectStartMsg=True):
        return self.__logFactory.createLog(name, port, expectStartMsg)

    def __getInternetAddress(self):
        return ip.getLocalIpAddr()

    def __verifyRegArray(self, rtnArray, expId, logHost, logPort,
                         liveHost, livePort):
        numElem = 6
        self.assertEquals(numElem, len(rtnArray),
                          'Expected %d-element array, not %d elements' %
                          (numElem, len(rtnArray)))
        self.assertEquals(expId, rtnArray["id"],
                          'Registration should return client ID#%d, not %d' %
                          (expId, rtnArray["id"]))
        self.assertEquals(logHost, rtnArray["logIP"],
                          'Registration should return loghost %s, not %s' %
                          (logHost, rtnArray["logIP"]))
        self.assertEquals(logPort, rtnArray["logPort"],
                          'Registration should return logport#%d, not %d' %
                          (logPort, rtnArray["logPort"]))
        self.assertEquals(liveHost, rtnArray["liveIP"],
                          'Registration should return livehost %s, not %s' %
                          (liveHost, rtnArray["liveIP"]))
        self.assertEquals(livePort, rtnArray["livePort"],
                          'Registration should return liveport#%d, not %d' %
                          (livePort, rtnArray["livePort"]))

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__runConfigDir = None

    def tearDown(self):
        try:
            self.__logFactory.tearDown()
        except:
            traceback.print_exc()

        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)
            self.__runConfigDir = None

        MockServer.APPENDER.checkStatus(10)

    def testRegister(self):
        logPort = 11853
        logger = self.__createLog('file', logPort)

        livePort = 35811
        liver = self.__createLog('live', livePort, False)

        dc = MockServer(logPort=logPort, livePort=livePort,
                        logFactory=self.__logFactory)

        self.assertEqual(dc.rpc_component_list_dicts(), [])

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID.peekNext()

        if num == 0:
            fullName = name
        else:
            fullName = "%s#%d" % (name, num)

        logger.addExpectedText('Registered %s' % fullName)
        liver.addExpectedText('Registered %s' % fullName)

        rtnArray = dc.rpc_component_register(name, num, host, port, mPort, [])

        localAddr = self.__getInternetAddress()

        self.__verifyRegArray(rtnArray, expId, localAddr, logPort,
                              localAddr, livePort)

        self.assertEqual(dc.rpc_component_count(), 1)

        fooDict = { "id" : expId,
                    "compName" : name,
                    "compNum" : num,
                    "host" : host,
                    "rpcPort" : port,
                    "mbeanPort" : mPort,
                    "state" : "idle"}
        self.assertEqual(dc.rpc_component_list_dicts(), [fooDict, ])

        logger.checkStatus(100)
        liver.checkStatus(100)

    def testRegisterWithLog(self):
        logPort = 23456
        logger = self.__createLog('log', logPort)

        dc = MockServer(logPort=logPort, logFactory=self.__logFactory)

        logger.checkStatus(100)

        liveHost = ''
        livePort = 0

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID.peekNext()

        if num == 0:
            fullName = name
        else:
            fullName = "%s#%d" % (name, num)

        logger.addExpectedText('Registered %s' % fullName)

        rtnArray = dc.rpc_component_register(name, num, host, port, mPort, [])

        localAddr = self.__getInternetAddress()

        self.__verifyRegArray(rtnArray, expId, localAddr, logPort,
                              liveHost, livePort)

        logger.checkStatus(100)

    def testNoRunset(self):
        logPort = 11545

        logger = self.__createLog('main', logPort)

        dc = MockServer(logPort=logPort,
                        logFactory=self.__logFactory)

        logger.checkStatus(100)

        moniType = RunOption.MONI_TO_NONE

        self.assertRaises(CnCServerException, dc.rpc_runset_break, 1)
        self.assertRaises(CnCServerException, dc.rpc_runset_list, 1)
        self.assertRaises(CnCServerException, dc.rpc_runset_start_run, 1, 1,
                          moniType)
        self.assertRaises(CnCServerException, dc.rpc_runset_stop_run, 1)

        logger.checkStatus(100)

    def testRunset(self):
        self.__runConfigDir = tempfile.mkdtemp()

        logPort = 21765

        logger = self.__createLog('main', logPort)

        clientPort = DAQPort.RUNCOMP_BASE

        clientLogger = self.__createLog('client', clientPort)

        compId = DAQClient.ID.peekNext()
        compName = 'stringHub'
        compNum = self.HUB_NUMBER
        compHost = 'localhost'
        compPort = 666
        compBeanPort = 0

        cluCfg = MockClusterConfig("clusterFoo")
        cluCfg.addComponent("%s#%d" % (compName, compNum), "java", "",
                            compHost)

        dc = MockServer(clusterConfigObject=cluCfg, copyDir="copyDir",
                        runConfigDir=self.__runConfigDir, spadeDir="/tmp",
                        logPort=logPort, clientLog=clientLogger,
                        logFactory=self.__logFactory)

        logger.checkStatus(100)

        self.assertEqual(dc.rpc_component_count(), 0)
        self.assertEqual(dc.rpc_runset_count(), 0)
        self.assertEqual(dc.rpc_component_list_dicts(), [])

        if compNum == 0:
            fullName = compName
        else:
            fullName = "%s#%d" % (compName, compNum)

        logger.addExpectedText('Registered %s' % fullName)

        dc.rpc_component_register(compName, compNum, compHost, compPort,
                                  compBeanPort, [])

        logger.checkStatus(100)

        self.assertEqual(dc.rpc_component_count(), 1)
        self.assertEqual(dc.rpc_runset_count(), 0)

        connErr = "No connection map entry for ID#%s %s#%d .*" % \
            (compId, compName, compNum)
        logger.addExpectedTextRegexp(connErr)

        rcFile = MockRunConfigFile(self.__runConfigDir)

        domList = [MockRunConfigFile.createDOM(self.DOM_MAINBOARD_ID), ]
        runConfig = rcFile.create([], domList)

        logger.addExpectedTextRegexp('Loading run configuration .*')
        logger.addExpectedTextRegexp('Loaded run configuration .*')
        logger.addExpectedTextRegexp("Built runset #\d+: .*")

        setId = dc.rpc_runset_make(runConfig, strict=False)

        logger.checkStatus(100)

        self.assertEqual(dc.rpc_component_count(), 0)
        self.assertEqual(dc.rpc_runset_count(), 1)

        rs = dc.rpc_runset_list(setId)
        self.assertEqual(len(rs), 1)

        rsc = rs[0]
        self.assertEqual(compId, rsc["id"])
        self.assertEqual(compName, rsc["compName"])
        self.assertEqual(compNum, rsc["compNum"])
        self.assertEqual(compHost, rsc["host"])
        self.assertEqual(compPort, rsc["rpcPort"])
        self.assertEqual(compBeanPort, rsc["mbeanPort"])
        self.assertEqual("ready", rsc["state"])

        logger.checkStatus(100)

        runNum = 456

        logger.addExpectedText("Starting run #%d with \"%s\"" %
                                (runNum, cluCfg.configName()))

        logger.addExpectedTextRegexp(r"Version info: \S+ \d+" +
                                     r" \S+ \S+ \S+ \S+ \d+\S*")
        clientLogger.addExpectedTextRegexp(r"Version info: \S+ \d+" +
                                           r" \S+ \S+ \S+ \S+ \d+\S*")

        logger.addExpectedText("Run configuration: %s" % runConfig)
        logger.addExpectedText("Cluster configuration: %s" %
                               cluCfg.configName())

        moniType = RunOption.MONI_TO_NONE

        global CAUGHT_WARNING
        if not LIVE_IMPORT and not CAUGHT_WARNING:
            CAUGHT_WARNING = True
            logger.addExpectedTextRegexp(r"^Cannot import IceCube Live.*")

        logger.addExpectedText("Starting run %d..." % runNum)

        self.assertEqual(dc.rpc_runset_start_run(setId, runNum, moniType), 'OK')

        logger.checkStatus(10)
        clientLogger.checkStatus(10)

        logger.addExpectedText("0 physics events collected in 0 seconds")
        logger.addExpectedText("0 moni events, 0 SN events, 0 tcals")
        logger.addExpectedText("Run terminated SUCCESSFULLY")

        self.assertEqual(dc.rpc_runset_stop_run(setId), 'OK')

        logger.checkStatus(10)

        self.assertEqual(dc.rpc_component_count(), 0)
        self.assertEqual(dc.rpc_runset_count(), 1)

        logger.checkStatus(10)

        self.assertEquals(dc.rpc_runset_break(setId), 'OK')

        logger.checkStatus(10)

        self.assertEqual(dc.rpc_component_count(), 1)
        self.assertEqual(dc.rpc_runset_count(), 0)

        logger.checkStatus(10)
        clientLogger.checkStatus(10)

if __name__ == '__main__':
    unittest.main()
