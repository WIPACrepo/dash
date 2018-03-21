#!/usr/bin/env python

import shutil
import tempfile
import traceback
import unittest
from CnCExceptions import CnCServerException
from CnCServer import CnCServer
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQMocks import MockAppender, MockClusterConfig, MockCnCLogger, \
    MockDefaultDomGeometryFile, MockLeapsecondFile, MockRunConfigFile, \
    SocketReaderFactory, SocketWriter
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet
from locate_pdaq import set_pdaq_config_dir
from utils import ip


class TinyMBeanClient(object):
    def __init__(self):
        pass

    def getAttributes(self, beanname, fldlist):
        if beanname != "stringhub":
            raise Exception("Unknown bean \"%s\"" % beanname)
        rtndict = {}
        for fld in fldlist:
            if fld == "LatestFirstChannelHitTime" or \
                fld == "NumberOfNonZombies" or \
                fld == "EarliestLastChannelHitTime":
                rtndict[fld] = 10
            else:
                raise Exception("Unknown beanField \"%s.%s\"" %
                                (beanname, fld))
        return rtndict


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

        self.__log = None
        self.__mbeanClient = TinyMBeanClient()

    def __str__(self):
        if self.__mbeanPort == 0:
            mStr = ''
        else:
            mStr = ' M#%d' % self.__mbeanPort
        return 'ID#%d %s#%d at %s:%d%s' % \
            (self.__id, self.__name, self.__num, self.__host, self.__port,
             mStr)

    def configure(self, cfgName=None):
        self.__state = 'ready'

    def connect(self, connList=None):
        self.__state = 'connected'

    def connectors(self):
        return self.__connectors[:]

    @property
    def fullname(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    @property
    def id(self):
        return self.__id

    @property
    def is_dying(self):
        return False

    @property
    def isReplayHub(self):
        return False

    @property
    def isSource(self):
        return True

    def logTo(self, logIP, logPort, liveIP, livePort):
        if liveIP is not None and livePort is not None:
            raise Exception('Cannot log to I3Live')

        self.__log = SocketWriter(logIP, logPort)
        self.__log.write_ts('Start of log at LOG=log(%s:%d)' %
                            (logIP, logPort))
        self.__log.write_ts('Version info: BRANCH 0:0 unknown unknown')

    def map(self):
        return {"id": self.__id,
                "compName": self.__name,
                "compNum": self.__num,
                "host": self.__host,
                "rpcPort": self.__port,
                "mbeanPort": self.__mbeanPort,
                "state": self.__state}

    @property
    def mbean(self):
        return self.__mbeanClient

    @property
    def name(self):
        return self.__name

    @property
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

    @property
    def state(self):
        return self.__state

    def stopRun(self):
        self.__state = 'ready'


class FakeRunData(object):
    def __init__(self, runNum, runCfg, cluCfg):
        self.__run_number = runNum
        self.__run_config = runCfg
        self.__cluster_config = cluCfg

        self.__logger = None
        self.__finished = False

    def __str__(self):
        return "FakeRunData[%d/%s/%s]" % \
            (self.__run_number, self.__run_config.basename,
             self.__cluster_config.description)

    @property
    def cluster_configuration(self):
        return self.__cluster_config

    def connect_to_live(self):
        pass

    def error(self, logmsg):
        if self.__logger is None:
            raise Exception("Mock logger has not been set")
        self.__logger.error(logmsg)

    @property
    def finished(self):
        return self.__finished

    @property
    def has_moni_client(self):
        return True

    @property
    def isErrorEnabled(self):
        return self.__logger.isErrorEnabled

    @property
    def log_directory(self):
        return None

    def reset(self):
        pass

    @property
    def run_configuration(self):
        return self.__run_config

    @property
    def run_directory(self):
        return "/bad/path"

    @property
    def run_number(self):
        return self.__run_number

    def send_event_counts(self, run_set=None):
        pass

    def send_moni(self, name, value, prio=None, time=None, debug=False):
        pass

    def set_finished(self):
        self.__finished = True

    def set_mock_logger(self, logger):
        self.__logger = logger

    def stop_tasks(self):
        pass

    @property
    def subrun_number(self):
        return 0


class MockRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger, clientLog=None):
        self.__runConfig = runConfig
        self.__dashLog = logger
        self.__clientLog = clientLog
        self.__deadComp = []

        super(MockRunSet, self).__init__(parent, runConfig, compList, logger)

    def create_component_log(self, runDir, comp, host, port, liveHost,
                             livePort, quiet=True):
        return self.__clientLog

    def create_run_data(self, runNum, clusterConfig, runOptions, versionInfo,
                        spade_dir, copy_dir=None, log_dir=None, testing=True):
        mrd = FakeRunData(runNum, self.__runConfig, clusterConfig)
        mrd.set_mock_logger(self.__dashLog)
        return mrd

    def final_report(self, comps, runData, had_error=False, switching=False):
        if switching:
            verb = "switched"
        else:
            verb = "terminated"
        if had_error:
            result = "WITH ERROR"
        else:
            result = "SUCCESSFULLY"
        self.__dashLog.error("Run %s %s." % (verb, result))

    def finish_setup(self, run_data, start_time):
        self.__dashLog.error('Version info: BRANCH 0:0 unknown unknown')
        self.__dashLog.error("Run configuration: %s" %
                             (run_data.run_configuration.basename, ))
        self.__dashLog.error("Cluster: %s" %
                             (run_data.cluster_configuration.description, ))

    def get_event_counts(self, run_num):
        return {
            "physicsEvents": 1,
            "eventPayloadTicks": -100,
            "wallTime": None,
            "moniEvents": 1,
            "moniTime": 98,
            "snEvents": 1,
            "snTime": 97,
            "tcalEvents": 1,
            "tcalTime": 96,
        }

    @staticmethod
    def report_good_time(run_data, name, daq_time):
        pass


class MockServer(CnCServer):
    APPENDER = MockAppender('server')

    def __init__(self, clusterConfigObject=None, copyDir=None,
                 runConfigDir=None, daqDataDir=None, spadeDir=None,
                 logPort=None, livePort=None, forceRestart=False,
                 clientLog=None, logFactory=None):
        self.__clusterConfig = clusterConfigObject
        self.__clientLog = clientLog
        self.__logFactory = logFactory

        super(MockServer, self).__init__(copyDir=copyDir,
                                         runConfigDir=runConfigDir,
                                         daqDataDir=daqDataDir,
                                         spadeDir=spadeDir,
                                         logIP='localhost', logPort=logPort,
                                         liveIP='localhost', livePort=livePort,
                                         forceRestart=forceRestart,
                                         testOnly=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        return TinyClient(name, num, host, port, mbeanPort, connectors)

    def createCnCLogger(self, quiet):
        return MockCnCLogger("CnC", appender=MockServer.APPENDER, quiet=quiet)

    def createRunset(self, runConfig, compList, logger):
        return MockRunSet(self, runConfig, compList, logger,
                          clientLog=self.__clientLog)

    def getClusterConfig(self, runConfig=None):
        return self.__clusterConfig

    def openLogServer(self, port, logDir):
        if self.__logFactory is None:
            raise Exception("MockServer log factory has not been set")
        return self.__logFactory.createLog("catchall", port,
                                           expectStartMsg=False,
                                           startServer=False)

    def saveCatchall(self, runDir):
        pass


class TestDAQServer(unittest.TestCase):
    HUB_NUMBER = 1021
    DOM_MAINBOARD_ID = 0x53494d552101

    def __createLog(self, name, port, expectStartMsg=True):
        return self.__logFactory.createLog(name, port, expectStartMsg)

    def __getInternetAddress(self):
        return ip.getLocalIpAddr()

    def __verifyRegArray(self, rtnArray, expId, logHost, logPort,
                         liveHost, livePort):
        numElem = 6
        self.assertEqual(numElem, len(rtnArray),
                         'Expected %d-element array, not %d elements' %
                         (numElem, len(rtnArray)))
        self.assertEqual(expId, rtnArray["id"],
                         'Registration should return client ID#%d, not %d' %
                         (expId, rtnArray["id"]))
        self.assertEqual(logHost, rtnArray["logIP"],
                         'Registration should return loghost %s, not %s' %
                         (logHost, rtnArray["logIP"]))
        self.assertEqual(logPort, rtnArray["logPort"],
                         'Registration should return logport#%d, not %d' %
                         (logPort, rtnArray["logPort"]))
        self.assertEqual(liveHost, rtnArray["liveIP"],
                         'Registration should return livehost %s, not %s' %
                         (liveHost, rtnArray["liveIP"]))
        self.assertEqual(livePort, rtnArray["livePort"],
                         'Registration should return liveport#%d, not %d' %
                         (livePort, rtnArray["livePort"]))

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__runConfigDir = None
        self.__daqDataDir = None

        set_pdaq_config_dir(None, override=True)

    def tearDown(self):
        try:
            self.__logFactory.tearDown()
        except:
            traceback.print_exc()

        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)
            self.__runConfigDir = None
        if self.__daqDataDir is not None:
            shutil.rmtree(self.__daqDataDir, ignore_errors=True)
            self.__daqDataDir = None

        MockServer.APPENDER.checkStatus(10)

        set_pdaq_config_dir(None, override=True)

    def testRegister(self):
        logPort = 11853
        logger = self.__createLog('file', logPort)

        liveHost = ''
        livePort = 0

        dc = MockServer(logPort=logPort, logFactory=self.__logFactory)

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

        rtnArray = dc.rpc_component_register(name, num, host, port, mPort, [])

        localAddr = self.__getInternetAddress()

        self.__verifyRegArray(rtnArray, expId, localAddr, logPort,
                              liveHost, livePort)

        self.assertEqual(dc.rpc_component_count(), 1)

        fooDict = {"id": expId,
                   "compName": name,
                   "compNum": num,
                   "host": host,
                   "rpcPort": port,
                   "mbeanPort": mPort,
                   "state": "idle"}
        self.assertEqual(dc.rpc_component_list_dicts(), [fooDict, ])

        logger.checkStatus(100)

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
        self.__daqDataDir = tempfile.mkdtemp()

        set_pdaq_config_dir(self.__runConfigDir, override=True)

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
                        runConfigDir=self.__runConfigDir,
                        daqDataDir=self.__daqDataDir, spadeDir="/tmp",
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

        hubDomDict = {
            self.HUB_NUMBER:
            [MockRunConfigFile.createDOM(self.DOM_MAINBOARD_ID, 3,
                                         "DSrvrTst", "Z98765"), ],
        }

        runConfig = rcFile.create([], hubDomDict)

        leapFile = MockLeapsecondFile(self.__runConfigDir)
        leapFile.create()

        MockDefaultDomGeometryFile.create(self.__runConfigDir, hubDomDict)

        logger.addExpectedTextRegexp('Loading run configuration .*')
        logger.addExpectedTextRegexp('Loaded run configuration .*')
        logger.addExpectedTextRegexp(r"Built runset #\d+: .*")

        runNum = 456

        setId = dc.rpc_runset_make(runConfig, runNum, strict=False)

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

        logger.addExpectedText("Starting run #%d on \"%s\"" %
                               (runNum, cluCfg.description))

        logger.addExpectedTextRegexp(r"Version info: \S+ \S+ \S+ \S+")
        clientLogger.addExpectedTextRegexp(r"Version info: \S+ \S+ \S+ \S+")

        logger.addExpectedText("Run configuration: %s" % runConfig)
        logger.addExpectedText("Cluster: %s" % cluCfg.description)

        moniType = RunOption.MONI_TO_NONE

        logger.addExpectedText("Starting run %d..." % runNum)

        logger.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        logger.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        self.assertEqual(dc.rpc_runset_start_run(setId, runNum, moniType),
                         'OK')

        logger.checkStatus(10)
        clientLogger.checkStatus(10)

        logger.addExpectedText("Run terminated SUCCESSFULLY")

        logger.addExpectedText("Not logging to file so cannot queue to"
                               " SPADE")

        self.assertEqual(dc.rpc_runset_stop_run(setId), 'OK')

        logger.checkStatus(10)

        self.assertEqual(dc.rpc_component_count(), 0)
        self.assertEqual(dc.rpc_runset_count(), 1)

        logger.checkStatus(10)

        self.assertEqual(dc.rpc_runset_break(setId), 'OK')

        logger.checkStatus(10)

        self.assertEqual(dc.rpc_component_count(), 1)
        self.assertEqual(dc.rpc_runset_count(), 0)

        logger.checkStatus(10)
        clientLogger.checkStatus(10)


if __name__ == '__main__':
    unittest.main()
