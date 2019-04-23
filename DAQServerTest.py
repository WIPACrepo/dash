#!/usr/bin/env python

import shutil
import tempfile
import traceback
import unittest
from CnCExceptions import CnCServerException
from CnCServer import CnCServer
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQMocks import MockClusterConfig, MockCnCLogger, \
    MockDefaultDomGeometryFile, MockLeapsecondFile, MockLogger, \
    MockRunConfigFile, SocketReaderFactory, SocketWriter
from RunOption import RunOption
from RunSet import RunSet
from locate_pdaq import set_pdaq_config_dir
from utils import ip


class TinyMBeanClient(object):
    def __init__(self):
        pass

    def get_attributes(self, beanname, fldlist):
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
    def __init__(self, name, num, host, port, mbean_port, connectors):
        self.__name = name
        self.__num = num
        self.__connectors = connectors

        self.__id = next(DAQClient.ID)

        self.__host = host
        self.__port = port
        self.__mbean_port = mbean_port

        self.__state = 'idle'
        self.__order = None

        self.__log = None
        self.__mbeanClient = TinyMBeanClient()

    def __str__(self):
        if self.__mbean_port == 0:
            mStr = ''
        else:
            mStr = ' M#%d' % self.__mbean_port
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
    def is_replay_hub(self):
        return False

    @property
    def is_source(self):
        return True

    def log_to(self, log_host, log_port, live_host, live_port):
        if live_host is not None and live_port is not None:
            raise Exception('Cannot log to I3Live')

        self.__log = SocketWriter(log_host, log_port)
        self.__log.write_ts('Start of log at LOG=log(%s:%d)' %
                            (log_host, log_port))
        self.__log.write_ts('Version info: BRANCH 0:0 unknown unknown')

    def map(self):
        return {"id": self.__id,
                "compName": self.__name,
                "compNum": self.__num,
                "host": self.__host,
                "rpcPort": self.__port,
                "mbeanPort": self.__mbean_port,
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

    @property
    def order(self):
        return self.__order

    def reset(self):
        self.__state = 'idle'

    def reset_logging(self):
        pass

    def set_order(self, orderNum):
        self.__order = orderNum

    def start_run(self, runNum):
        self.__state = 'running'

    @property
    def state(self):
        return self.__state

    def stop_run(self):
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
    def is_error_enabled(self):
        return self.__logger.is_error_enabled

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

    def set_finished(self):
        self.__finished = True

    def set_mock_logger(self, logger):
        self.__logger = logger

    def stop_tasks(self):
        pass


class MockRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, logger, clientLog=None):
        self.__runConfig = runConfig
        self.__dashLog = logger
        self.__clientLog = clientLog
        self.__deadComp = []

        super(MockRunSet, self).__init__(parent, runConfig, compList, logger)

    def create_component_log(self, runDir, comp, host, port, quiet=True):
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

    @staticmethod
    def report_good_time(run_data, name, daq_time):
        pass


class MockServer(CnCServer):
    APPENDER = MockLogger('server')

    def __init__(self, clusterConfigObject=None, copyDir=None,
                 runConfigDir=None, daqDataDir=None, spadeDir=None,
                 log_port=None, live_port=None, forceRestart=False,
                 clientLog=None, logFactory=None):
        self.__clusterConfig = clusterConfigObject
        self.__clientLog = clientLog
        self.__logFactory = logFactory

        super(MockServer, self).__init__(copyDir=copyDir,
                                         runConfigDir=runConfigDir,
                                         daqDataDir=daqDataDir,
                                         spadeDir=spadeDir,
                                         logIP='localhost',
                                         logPort=log_port,
                                         liveIP='localhost',
                                         livePort=live_port,
                                         forceRestart=forceRestart,
                                         testOnly=True)

    def createClient(self, name, num, host, port, mbean_port, connectors):
        return TinyClient(name, num, host, port, mbean_port, connectors)

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

    def __verifyRegArray(self, rtnArray, expId, log_host, log_port,
                         live_host, live_port):
        numElem = 6
        self.assertEqual(numElem, len(rtnArray),
                         'Expected %d-element array, not %d elements' %
                         (numElem, len(rtnArray)))
        self.assertEqual(expId, rtnArray["id"],
                         'Registration should return client ID#%d, not %d' %
                         (expId, rtnArray["id"]))
        self.assertEqual(log_host, rtnArray["logIP"],
                         'Registration should return loghost %s, not %s' %
                         (log_host, rtnArray["logIP"]))
        self.assertEqual(log_port, rtnArray["logPort"],
                         'Registration should return logport#%d, not %d' %
                         (log_port, rtnArray["logPort"]))
        self.assertEqual(live_host, rtnArray["liveIP"],
                         'Registration should return livehost %s, not %s' %
                         (live_host, rtnArray["liveIP"]))
        self.assertEqual(live_port, rtnArray["livePort"],
                         'Registration should return liveport#%d, not %d' %
                         (live_port, rtnArray["livePort"]))

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
        log_port = 11853
        logger = self.__createLog('file', log_port)

        live_host = ''
        live_port = 0

        dc = MockServer(log_port=log_port, logFactory=self.__logFactory)

        self.assertEqual(dc.rpc_component_list_dicts(), [])

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID.peek_next()

        if num == 0:
            fullName = name
        else:
            fullName = "%s#%d" % (name, num)

        logger.addExpectedText('Registered %s' % fullName)

        rtnArray = dc.rpc_component_register(name, num, host, port, mPort, [])

        localAddr = self.__getInternetAddress()

        self.__verifyRegArray(rtnArray, expId, localAddr, log_port,
                              live_host, live_port)

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
        log_port = 23456
        logger = self.__createLog('log', log_port)

        dc = MockServer(log_port=log_port, logFactory=self.__logFactory)

        logger.checkStatus(100)

        live_host = ''
        live_port = 0

        name = 'foo'
        num = 0
        host = 'localhost'
        port = 666
        mPort = 667

        expId = DAQClient.ID.peek_next()

        if num == 0:
            fullName = name
        else:
            fullName = "%s#%d" % (name, num)

        logger.addExpectedText('Registered %s' % fullName)

        rtnArray = dc.rpc_component_register(name, num, host, port, mPort, [])

        localAddr = self.__getInternetAddress()

        self.__verifyRegArray(rtnArray, expId, localAddr, log_port,
                              live_host, live_port)

        logger.checkStatus(100)

    def testNoRunset(self):
        log_port = 11545

        logger = self.__createLog('main', log_port)

        dc = MockServer(log_port=log_port,
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

        log_port = 21765

        logger = self.__createLog('main', log_port)

        clientPort = DAQPort.EPHEMERAL_BASE

        clientLogger = self.__createLog('client', clientPort)

        compId = DAQClient.ID.peek_next()
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
                        log_port=log_port, clientLog=clientLogger,
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
