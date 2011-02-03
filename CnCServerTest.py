#!/usr/bin/env python

import os, shutil, sys, tempfile, threading, time, traceback, unittest, xmlrpclib

from CnCServer import CnCServer, CnCServerException
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQRPC import RPCServer
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet

from DAQMocks \
    import MockAppender, MockClusterConfig, MockCnCLogger, MockRunConfigFile, \
    SocketReaderFactory, SocketWriter

ACTIVE_WARNING = False

class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbeanPort, connectors,
                                              quiet=True)

    def createLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet=quiet)

    def createMBeanClient(self, host, port):
        return None

class FakeLogger(object):
    def __init__(self): pass
    def stopServing(self): pass

class FakeTaskManager(object):
    def __init__(self): pass
    def reset(self): pass
    def start(self): pass
    def stop(self): pass

class MostlyRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger):
        self.__dashLog = logger
        self.__logDict = {}

        super(MostlyRunSet, self).__init__(parent, runConfig, compList, logger)

    def createComponentLog(self, runDir, c, host, port, liveHost, livePort,
                           quiet=True):
        return FakeLogger()

    def createDashLog(self):
        return self.__dashLog

    def createRunData(self, runNum, clusterConfigName, runOptions, versionInfo,
                      spadeDir, copyDir=None, logDir=None):
        return super(MostlyRunSet, self).createRunData(runNum,
                                                       clusterConfigName,
                                                       runOptions, versionInfo,
                                                       spadeDir, copyDir,
                                                       logDir, True)

    def createRunDir(self, logDir, runNum, backupExisting=True):
        return None

    def createTaskManager(self, dashlog, liveMoniClient, runDir, runCfg,
                          moniType):
        return FakeTaskManager()

    def cycleComponents(self, compList, configDir, dashDir, logPort, livePort,
                        verbose, killWith9, eventCheck, checkExists=True):
        pass

    def getLog(self, name):
        if not self.__logDict.has_key(name):
            self.__logDict[name] = MockLogger(name)

        return self.__logDict[name]

    def queueForSpade(self, duration):
        pass

class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, clusterConfigObject, copyDir=None, runConfigDir=None,
                 spadeDir=None, logIP='localhost', logPort=-1,
                 logFactory=None, forceRestart=False):

        self.__clusterConfig = clusterConfigObject
        self.__logFactory = logFactory

        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              copyDir=copyDir,
                                              runConfigDir=runConfigDir,
                                              spadeDir=spadeDir,
                                              logIP=logIP, logPort=logPort,
                                              forceRestart=forceRestart,
                                              quiet=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        key = '%s#%d' % (name, num)
        key = 'server'
        if not MostlyCnCServer.APPENDERS.has_key(key):
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MostlyDAQClient(name, num, host, port, mbeanPort, connectors,
                               MostlyCnCServer.APPENDERS[key])

    def createCnCLogger(self, quiet):
        key = 'server'
        if not MostlyCnCServer.APPENDERS.has_key(key):
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MockCnCLogger(MostlyCnCServer.APPENDERS[key], quiet=quiet)

    def createRunset(self, runConfig, compList, logger):
        return MostlyRunSet(self, runConfig, compList, logger)

    def getClusterConfig(self):
        return self.__clusterConfig

    def monitorLoop(self):
        pass

    def openLogServer(self, port, logDir):
        if self.__logFactory is None:
            raise Exception("MostlyCnCServer log factory has not been set")
        return self.__logFactory.createLog("catchall", port,
                                           expectStartMsg=False,
                                           startServer=False)

    def saveCatchall(self, runDir):
        pass

    def startLiveThread(self):
        return None

class RealComponent(object):
    APPENDERS = {}

    def __init__(self, name, num, cmdPort, mbeanPort, verbose=False):
        self.__name = name
        self.__num = num

        self.__state = 'FOO'

        self.__logger = None
        self.__expRunPort = None

        self.__cmd = RPCServer(cmdPort)
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__getState, 'xmlrpc.getState')
        self.__cmd.register_function(self.__getVersionInfo,
                                     'xmlrpc.getVersionInfo')
        self.__cmd.register_function(self.__logTo, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__resetLogging, 'xmlrpc.resetLogging')
        self.__cmd.register_function(self.__startRun, 'xmlrpc.startRun')
        self.__cmd.register_function(self.__stopRun, 'xmlrpc.stopRun')

        tName = "RealXML*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__cmd.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__mbean = RPCServer(mbeanPort)

        tName = "RealMBean*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__mbean.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER, verbose=verbose)
        self.__cnc.rpc_component_register(self.__name, self.__num, 'localhost',
                                          cmdPort, mbeanPort, [])

    def __str__(self):
        return "%s#%d" % (self.__name, self.__num)

    def __configure(self, cfgName=None):
        if cfgName is None:
            cfgStr = ''
        else:
            cfgStr = ' with %s' % cfgName

        #self.__logger.write('Config %s#%d%s' %
        #                    (self.__name, self.__num, cfgStr))

        self.__state = 'ready'
        return 'CFG'

    def __connect(self, *args):
        self.__state = 'connected'
        return 'CONN'

    def __getState(self):
        return self.__state

    def __getVersionInfo(self):
        return '$Id: filename revision date time author xxx'

    def __logTo(self, logHost, logPort, liveHost, livePort):
        if logHost is not None and logHost == '':
            logHost = None
        if logPort is not None and logPort == 0:
            logPort = None
        if liveHost is not None and liveHost == '':
            liveHost = None
        if livePort is not None and livePort == 0:
            livePort = None
        if logPort != self.__expRunPort:
            raise Exception('Expected runlog port %d, not %d' %
                            (self.__expRunPort, logPort))
        if liveHost is not None and livePort is not None:
            raise Exception("Didn't expect I3Live logging")

        self.__logger = SocketWriter(logHost, logPort)
        self.__logger.write('Test msg')
        return 'OK'

    def __reset(self):
        self.__state = 'idle'
        return 'RESET'

    def __resetLogging(self):
        self.__expRunPort = None
        self.__logger = None

        return 'RLOG'

    def __startRun(self, runNum):
        if self.__logger is None:
            raise Exception('No logging for %s' % self)

        self.__logger.write('Start #%d on %s' % (runNum, self))

        self.__state = 'running'
        return 'RUN#%d' % runNum

    def __stopRun(self):
        if self.__logger is None:
            raise Exception('No logging for %s' % self)

        self.__logger.write('Stop %s' % self)

        self.__state = 'ready'
        return 'STOP'

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

    def createLogger(self, quiet=True):
        key = str(self)
        if not RealComponent.APPENDERS.has_key(key):
            RealComponent.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MockCnCLogger(RealComponent.APPENDERS[key], quiet=quiet)

    def getState(self):
        return self.__getState()

    def setExpectedRunLogPort(self, port):
        self.__expRunPort = port

class TestCnCServer(unittest.TestCase):
    HUB_NUMBER = 1021
    DOM_MAINBOARD_ID = "53494d552101"

    def createLog(self, name, port, expectStartMsg=True):
        return self.__logFactory.createLog(name, port, expectStartMsg)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__copyDir = tempfile.mkdtemp()
        self.__runConfigDir = tempfile.mkdtemp()
        self.__spadeDir = tempfile.mkdtemp()

        self.comp = None
        self.cnc = None

        MostlyCnCServer.APPENDERS.clear()
        RealComponent.APPENDERS.clear()

    def tearDown(self):
        for key in RealComponent.APPENDERS:
            RealComponent.APPENDERS[key].WaitForEmpty(10)
        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].checkStatus(10)

        if self.comp is not None:
            self.comp.close()
        if self.cnc is not None:
            try:
                self.cnc.closeServer()
            except:
                pass

        if self.__copyDir is not None:
            shutil.rmtree(self.__copyDir, ignore_errors=True)
            self.__copyDir = None
        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)
            self.__runConfigDir = None
        if self.__spadeDir is not None:
            shutil.rmtree(self.__spadeDir, ignore_errors=True)
            self.__spadeDir = None

        try:
            self.__logFactory.tearDown()
        except:
            traceback.print_exc()

    def __runEverything(self, forceRestart):
        catchall = self.createLog('master', 18999)

        clientPort = DAQPort.RUNCOMP_BASE

        clientLogger = self.createLog('client', clientPort, False)

        compName = 'stringHub'
        compNum = self.HUB_NUMBER
        compHost = 'localhost'

        cluCfg = MockClusterConfig("clusterFoo")
        cluCfg.addComponent("%s#%d" % (compName, compNum), "java", "",
                            compHost)

        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        self.cnc = MostlyCnCServer(clusterConfigObject=cluCfg,
                                   copyDir=self.__copyDir,
                                   runConfigDir=self.__runConfigDir,
                                   spadeDir=self.__spadeDir,
                                   logPort=catchall.getPort(),
                                   logFactory=self.__logFactory,
                                   forceRestart=forceRestart)
        t = threading.Thread(name="CnCRun", target=self.cnc.run, args=())
        t.setDaemon(True)
        t.start()

        catchall.checkStatus(100)

        cmdPort = 19001
        mbeanPort = 19002

        if compNum == 0:
            fullName = compName
        else:
            fullName = "%s#%d" % (compName, compNum)

        catchall.addExpectedText('Registered %s' % fullName)

        self.comp = RealComponent(compName, compNum, cmdPort, mbeanPort)

        catchall.checkStatus(100)
        clientLogger.checkStatus(100)

        s = self.cnc.rpc_component_list_dicts()
        self.assertEquals(1, len(s),
                          'Expected 1 listed component, not %d' % len(s))
        self.assertEquals(compName, s[0]["compName"],
                          'Expected component %s, not %s' %
                          (compName, s[0]["compName"]))
        self.assertEquals(compNum, s[0]["compNum"],
                          'Expected %s #%d, not #%d' %
                          (compName, compNum, s[0]["compNum"]))
        self.assertEquals(compHost, s[0]["host"],
                          'Expected %s#%d host %s, not %s' %
                          (compName, compNum, compHost, s[0]["host"]))
        self.assertEquals(cmdPort, s[0]["rpcPort"],
                          'Expected %s#%d cmdPort %d, not %d' %
                          (compName, compNum, cmdPort, s[0]["rpcPort"]))
        self.assertEquals(mbeanPort, s[0]["mbeanPort"],
                          'Expected %s#%d mbeanPort %d, not %d' %
                          (compName, compNum, mbeanPort, s[0]["mbeanPort"]))

        compId = s[0]["id"]

        connErr = "No connection map entry for ID#%s %s#%d .*" % \
            (compId, compName, compNum)
        catchall.addExpectedTextRegexp(connErr)

        rcFile = MockRunConfigFile(self.__runConfigDir)

        domList = [MockRunConfigFile.createDOM(self.DOM_MAINBOARD_ID), ]
        runConfig = rcFile.create([], domList)

        catchall.addExpectedTextRegexp('Loading run configuration .*')
        catchall.addExpectedTextRegexp('Loaded run configuration .*')
        #clientLogger.addExpectedExact('Config %s#%d with %s' %
        #                              (compName, compNum, runConfig))

        catchall.addExpectedTextRegexp(r"Built runset #\d+: .*")

        setId = self.cnc.rpc_runset_make(runConfig, strict=False)
        self.assertEquals('ready', self.comp.getState(),
                          'Unexpected state %s' % self.comp.getState())

        time.sleep(1)

        catchall.checkStatus(100)

        rs = self.cnc.rpc_runset_list(setId)
        for c in rs:
            if compId != rs[0]["id"]:
                continue

            self.assertEquals(compName, c["compName"],
                              "Component#%d name should be \"%s\", not \"%s\"" %
                              (compId, compName, c["compName"]))
            self.assertEquals(compNum, c["compNum"],
                              ("Component#%d \"%s\" number should be %d," +
                               "not %d") %
                              (compId, compName, compNum, c["compNum"]))
            self.assertEquals(compHost, c["host"],
                              ("Component#%d \"%s#%d\" host should be" +
                               " \"%s\", not \"%s\"") %
                              (compId, compName, compNum, compHost, c["host"]))
            self.assertEquals(cmdPort, c["rpcPort"],
                              ("Component#%d \"%s#%d\" rpcPort should be" +
                               " \"%s\", not \"%s\"") %
                              (compId, compName, compNum, cmdPort,
                               c["rpcPort"]))
            self.assertEquals(mbeanPort, c["mbeanPort"],
                              ("Component#%d \"%s#%d\" mbeanPort should be" +
                               " \"%s\", not \"%s\"") %
                              (compId, compName, compNum, mbeanPort,
                               c["mbeanPort"]))

        catchall.checkStatus(100)

        self.comp.setExpectedRunLogPort(clientPort)

        clientLogger.checkStatus(100)
        catchall.checkStatus(100)

        runNum = 444

        clientLogger.addExpectedTextRegexp("Start of log at LOG=log(\S+:%d)" %
                                           clientPort)
        clientLogger.addExpectedExact('Test msg')
        clientLogger.addExpectedText('filename revision date time author')


        catchall.addExpectedText("Starting run #%d with \"%s\"" %
                                 (runNum, cluCfg.configName()))

        catchall.addExpectedTextRegexp(r"Version info: \S+ \d+" +
                                       r" \S+ \S+ \S+ \S+ \d+\S*")
        catchall.addExpectedText("Run configuration: %s" % runConfig)
        catchall.addExpectedText("Cluster configuration: %s" %
                                 cluCfg.configName())

        logDir = "/tmp"

        moniType = RunOption.MONI_TO_NONE

        clientLogger.addExpectedExact('Start #%d on %s#%d' %
                                      (runNum, compName, compNum))

        catchall.addExpectedText("Starting run %d..." % runNum)

        global ACTIVE_WARNING
        if not LIVE_IMPORT and not ACTIVE_WARNING:
            ACTIVE_WARNING = True
            catchall.addExpectedText("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        self.assertEqual(self.cnc.rpc_runset_start_run(setId, runNum, moniType),
                         'OK')

        clientLogger.checkStatus(100)
        catchall.checkStatus(100)

        clientLogger.addExpectedExact('Stop %s#%d' % (compName, compNum))

        numEvts = 0
        numSecs = 0
        numMoni = 0
        numSN = 0
        numTcals = 0

        catchall.addExpectedText("%d physics events collected in %d seconds" %
                                  (numEvts, numSecs))
        catchall.addExpectedText("%d moni events, %d SN events, %d tcals" %
                                  (numMoni, numSN, numTcals))
        catchall.addExpectedText("Run terminated SUCCESSFULLY.")

        if forceRestart:
            catchall.addExpectedText("Cycling components [%s]" % self.comp)

        self.assertEqual(self.cnc.rpc_runset_stop_run(setId), 'OK')

        clientLogger.checkStatus(100)
        catchall.checkStatus(100)

        if forceRestart:
            try:
                rs = self.cnc.rpc_runset_list(setId)
                self.fail("Runset #%d should have been destroyed" % setId)
            except CnCServerException:
                pass
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 0)
        else:
            self.assertEqual(len(self.cnc.rpc_runset_list(setId)), 1)
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 1)

            serverAppender = MostlyCnCServer.APPENDERS['server']

            self.assertEquals(self.cnc.rpc_runset_break(setId), 'OK')

            serverAppender.checkStatus(100)

            self.assertEqual(self.cnc.rpc_component_count(), 1)
            self.assertEqual(self.cnc.rpc_runset_count(), 0)

            serverAppender.checkStatus(100)

        clientLogger.checkStatus(100)
        catchall.checkStatus(100)

    def testEverything(self):
        self.__runEverything(False)

    def testEverythingAgain(self):
        if sys.platform != 'darwin':
            print 'Skipping server tests in non-Darwin OS'
            return

        self.__runEverything(False)

    def testForceRestart(self):
        if sys.platform != 'darwin':
            print 'Skipping server tests in non-Darwin OS'
            return

        self.__runEverything(True)

if __name__ == '__main__':
    unittest.main()
