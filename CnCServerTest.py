#!/usr/bin/env python

import shutil
import sys
import tempfile
import threading
import time
import traceback
import unittest
import xmlrpclib

from CnCExceptions import CnCServerException
from CnCServer import CnCServer
from ComponentManager import listComponentRanges
from DAQClient import DAQClient
from DAQConst import DAQPort
from DAQRPC import RPCServer
from LiveImports import LIVE_IMPORT
from RunOption import RunOption
from RunSet import RunSet

from DAQMocks \
    import MockAppender, MockClusterConfig, MockCnCLogger, MockRunConfigFile,\
    SocketReaderFactory, SocketWriter, MockLogger, RunXMLValidator

ACTIVE_WARNING = False


class MostlyDAQClient(DAQClient):
    def __init__(self, name, num, host, port, mbeanPort, connectors, appender):
        self.__appender = appender

        super(MostlyDAQClient, self).__init__(name, num, host, port,
                                              mbeanPort, connectors,
                                              quiet=True)

    def createLogger(self, quiet):
        return MockCnCLogger(self.__appender, quiet=quiet)


class FakeLogger(object):
    def __init__(self):
        pass

    def stopServing(self):
        pass


class FakeTaskManager(object):
    def __init__(self):
        pass

    def reset(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass


class MostlyRunSet(RunSet):
    def __init__(self, parent, runConfig, compList, catchall, dashlog):
        self.__catchall = catchall
        self.__dashlog = dashlog
        self.__logDict = {}

        super(MostlyRunSet, self).__init__(parent, runConfig, compList,
                                           catchall)

    def createComponentLog(self, runDir, c, host, port, liveHost, livePort,
                           quiet=True):
        return FakeLogger()

    def createDashLog(self):
        return self.__dashlog

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

    def cycleComponents(self, compList, configDir, daqDataDir, logger, logPort,
                        livePort, verbose, killWith9, eventCheck,
                        checkExists=True):
        compStr = listComponentRanges(compList)
        logger.error("Cycling components %s" % compStr)

    def getLog(self, name):
        if not name in self.__logDict:
            self.__logDict[name] = MockLogger(name)

        return self.__logDict[name]

    def queueForSpade(self, duration):
        pass

    def switchComponentLog(self, oldLog, runDir, comp):
        return oldLog


class MostlyCnCServer(CnCServer):
    SERVER_NAME = "MostlyCnC"
    APPENDERS = {}

    def __init__(self, clusterConfigObject, copyDir=None, runConfigDir=None,
                 daqDataDir=None, spadeDir=None, logIP='localhost',
                 logPort=-1, logFactory=None, dashlog=None,
                 forceRestart=False):

        self.__clusterConfig = clusterConfigObject
        self.__logFactory = logFactory
        self.__dashlog = dashlog

        super(MostlyCnCServer, self).__init__(name=MostlyCnCServer.SERVER_NAME,
                                              copyDir=copyDir,
                                              runConfigDir=runConfigDir,
                                              daqDataDir=daqDataDir,
                                              spadeDir=spadeDir,
                                              logIP=logIP, logPort=logPort,
                                              forceRestart=forceRestart,
                                              quiet=True)

    def createClient(self, name, num, host, port, mbeanPort, connectors):
        key = '%s#%d' % (name, num)
        key = 'server'
        if not key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MostlyDAQClient(name, num, host, port, mbeanPort, connectors,
                               MostlyCnCServer.APPENDERS[key])

    def createCnCLogger(self, quiet):
        key = 'server'
        if not key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MockCnCLogger(MostlyCnCServer.APPENDERS[key], quiet=quiet)

    def createRunset(self, runConfig, compList, logger):
        return MostlyRunSet(self, runConfig, compList, logger, self.__dashlog)

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

    def __init__(self, name, num, cmdPort, mbeanPort,
                 connArray, verbose=False):
        self.__name = name
        self.__num = num

        self.__id = None
        self.__state = 'FOO'

        self.__runNum = None

        self.__logger = None
        self.__expRunPort = None

        self.__runData = None
        self.__bean = None

        self.__cmd = RPCServer(cmdPort)
        self.__cmd.register_function(self.__configure, 'xmlrpc.configure')
        self.__cmd.register_function(self.__connect, 'xmlrpc.connect')
        self.__cmd.register_function(self.__getRunData, 'xmlrpc.getRunData')
        self.__cmd.register_function(self.__getRunNumber,
                                     'xmlrpc.getRunNumber')
        self.__cmd.register_function(self.__getState, 'xmlrpc.getState')
        self.__cmd.register_function(self.__getVersionInfo,
                                     'xmlrpc.getVersionInfo')
        self.__cmd.register_function(self.__logTo, 'xmlrpc.logTo')
        self.__cmd.register_function(self.__reset, 'xmlrpc.reset')
        self.__cmd.register_function(self.__resetLogging,
                                     'xmlrpc.resetLogging')
        self.__cmd.register_function(self.__setFirstGoodTime,
                                     'xmlrpc.setFirstGoodTime')
        self.__cmd.register_function(self.__setLastGoodTime,
                                     'xmlrpc.setLastGoodTime')
        self.__cmd.register_function(self.__startRun, 'xmlrpc.startRun')
        self.__cmd.register_function(self.__stopRun, 'xmlrpc.stopRun')
        self.__cmd.register_function(self.__switchToNewRun,
                                     'xmlrpc.switchToNewRun')

        tName = "RealXML*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__cmd.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__mbean = RPCServer(mbeanPort)
        self.__mbean.register_function(self.__getMBeanValue,
                                     'mbean.get')
        self.__mbean.register_function(self.__listMBeans, 'mbean.listMBeans')
        self.__mbean.register_function(self.__getMBeanAttributes,
                                       'mbean.getAttributes')
        self.__mbean.register_function(self.__listMBeanGetters,
                                       'mbean.listGetters')

        tName = "RealMBean*%s#%d" % (self.__name, self.__num)
        t = threading.Thread(name=tName, target=self.__mbean.serve_forever,
                             args=())
        t.setDaemon(True)
        t.start()

        self.__cnc = xmlrpclib.ServerProxy('http://localhost:%d' %
                                           DAQPort.CNCSERVER, verbose=verbose)
        regData = self.__cnc.rpc_component_register(self.__name, self.__num,
                                                    'localhost', cmdPort,
                                                    mbeanPort, connArray)

        self.__id = regData["id"]
        self.__expRunPort = regData["logPort"]

        self.__logTo(regData["logIP"], regData["logPort"],
                     regData["liveIP"], regData["livePort"])

        self.__expRunPort = None

    def __cmp__(self, other):
        val = cmp(self.__name, other.__name)
        if val == 0:
            val = cmp(self.__num, other.__num)
        return val

    def __repr__(self):
        return self.fullName()

    def __str__(self):
        return "%s#%d" % (self.__name, self.__num)

    def __configure(self, cfgName=None):
        if cfgName is None:
            cfgStr = ''
        else:
            cfgStr = ' with %s' % cfgName

        self.__logger.write('Config %s#%d%s' %
                            (self.__name, self.__num, cfgStr))

        self.__state = 'ready'
        return 'CFG'

    def __connect(self, *args):
        self.__state = 'connected'
        return 'CONN'

    @classmethod
    def __fixValue(cls, obj):
        if type(obj) is dict:
            for k in obj:
                obj[k] = cls.__fixValue(obj[k])
        elif type(obj) is list:
            for i in xrange(0, len(obj)):
                obj[i] = cls.__fixValue(obj[i])
        elif type(obj) is tuple:
            newObj = []
            for v in obj:
                newObj.append(cls.__fixValue(v))
            obj = tuple(newObj)
        elif type(obj) is int or type(obj) is long:
            if obj < xmlrpclib.MININT or obj > xmlrpclib.MAXINT:
                return str(obj)
        return obj

    def __getRunData(self, runNum):
        if self.__runData is None:
            raise Exception("%s runData has not been set" % self.fullName())
        rd = self.__runData
        self.__runData = None
        return self.__fixValue(rd)

    def __getRunNumber(self):
        return self.__runNum

    def __getMBeanAttributes(self, bean, attrList):
        valDict = {}
        for attr in attrList:
            valDict[attr] = self.__getMBeanValue(bean, attr)
        return valDict

    def __getMBeanValue(self, bean, field):
        if self.__bean is None or not bean in self.__bean or \
            not field in self.__bean[bean]:
            raise Exception("%s has no value for bean %s.%s" %
                            (self.fullName(), bean, field))

        return self.__fixValue(self.__bean[bean][field])

    def __getState(self):
        return self.__state

    def __getVersionInfo(self):
        return '$Id: filename revision date time author xxx'

    def __listMBeanGetters(self, bean):
        if self.__bean is None or not bean in self.__bean:
            return []
        return self.__bean[bean].keys()

    def __listMBeans(self):
        if self.__bean is None:
            return []
        return self.__bean.keys()

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
            print >>sys.stderr, "Remapping %s runlog port from %s to %s" % \
                (self, logPort, self.__expRunPort)
            logPort = self.__expRunPort
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

    def __setFirstGoodTime(self, payTime):
        return 'OK'

    def __setLastGoodTime(self, payTime):
        return 'OK'

    def __startRun(self, runNum):
        if self.__logger is None:
            raise Exception('No logging for %s' % self)

        self.__logger.write('Start #%d on %s' % (runNum, self.fullName()))

        self.__runNum = runNum
        self.__state = 'running'
        return 'RUN#%d' % runNum

    def __stopRun(self):
        if self.__logger is None:
            raise Exception('No logging for %s' % self)

        self.__logger.write('Stop %s' % self.fullName())

        self.__state = 'ready'
        return 'STOP'

    def __switchToNewRun(self, newNum):
        if self.__logger is None:
            raise Exception('No logging for %s' % self)

        self.__logger.write('Switch %s to run#%d' % (self.fullName(), newNum))

        self.__runNum = newNum
        self.__state = 'running'
        return 'SWITCHED'

    def close(self):
        self.__cmd.server_close()
        self.__mbean.server_close()

    def cmdPort(self):
        return self.__cmd.portnum

    def createLogger(self, quiet=True):
        key = str(self)
        if not key in RealComponent.APPENDERS:
            RealComponent.APPENDERS[key] = MockAppender('Mock-%s' % key)

        return MockCnCLogger(RealComponent.APPENDERS[key], quiet=quiet)

    def fullName(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def getState(self):
        return self.__getState()

    def id(self):
        return self.__id

    def isHub(self):
        if self.__name is None:
            return False
        return self.__name.lower().endswith("hub")

    def mbeanPort(self):
        return self.__mbean.portnum

    def name(self):
        return self.__name

    def num(self):
        return self.__num

    def number(self):
        return self.__num

    def setBeanFieldValue(self, bean, field, value):
        if self.__bean is None:
            self.__bean = {}
        if not bean in  self.__bean:
            self.__bean[bean] = {}
        self.__bean[bean][field] = value

    def setExpectedRunLogPort(self, port):
        self.__expRunPort = port

    def setRunData(self, v1, v2, v3, v4=None, v5=None):
        if v4 is None and v5 is None:
            self.__runData = (long(v1), long(v2), long(v3))
        else:
            self.__runData = (long(v1), long(v2), long(v3), long(v4), long(v5))


class RateTracker(object):
    def __init__(self, ticksInc, evtsInc, moniInc, snInc,
                 tcalInc):
        self.__ticksInc = ticksInc
        self.__evtsInc = evtsInc
        self.__moniInc = moniInc
        self.__snInc = snInc
        self.__tcalInc = tcalInc

        self.reset()

    def addFinalLogMsgs(self, logger):
        numSecs = self.__numTicks / 10000000000
        logger.addExpectedExact(("%d physics events collected" +
                                  " in %d seconds (%0.2f Hz)") %
                                  (self.__numEvts, numSecs,
                                    float(self.__numEvts) /
                                    float(numSecs)))
        logger.addExpectedExact("%d moni events, %d SN events, %d tcals" %
                                (self.__numMoni, self.__numSN, self.__numTcal))

    def getTotals(self):
        return (self.__numEvts, self.__numMoni, self.__numSN, self.__numTcal)

    def reset(self):
        self.__firstEvtTime = None
        self.__numTicks = 0
        self.__numEvts = 0
        self.__numMoni = 0
        self.__numSN = 0
        self.__numTcal = 0

    def updateRunData(self, cnc, runsetId, comps):
        self.__numTicks += self.__ticksInc
        self.__numEvts += self.__evtsInc
        self.__numMoni += self.__moniInc
        self.__numSN += self.__snInc
        self.__numTcal += self.__tcalInc

        if self.__firstEvtTime is None:
            self.__firstEvtTime = self.__numTicks

        lastEvtTime = self.__firstEvtTime + self.__numTicks

        for comp in comps:
            if comp.name() == "eventBuilder":
                comp.setRunData(self.__numEvts, self.__firstEvtTime,
                                lastEvtTime, self.__firstEvtTime, lastEvtTime)
                comp.setBeanFieldValue("backEnd", "EventData",
                                       (self.__numEvts, lastEvtTime))
                comp.setBeanFieldValue("backEnd", "FirstEventTime",
                                       self.__firstEvtTime)
                comp.setBeanFieldValue("backEnd", "GoodTimes",
                                       (self.__firstEvtTime, lastEvtTime))
            elif comp.name() == "secondaryBuilders":
                comp.setRunData(self.__numTcal, self.__numSN, self.__numMoni)

        cnc.updateRates(runsetId)

    def validateRunXML(self, testCase, runNum, runConfig, clusterCfg):
        RunXMLValidator.validate(testCase, runNum, runConfig, clusterCfg,
                                 None, None, self.__numEvts, self.__numMoni,
                                 self.__numSN, self.__numTcal, False)


class TestCnCServer(unittest.TestCase):
    HUB_NUMBER = 1021
    DOM_MAINBOARD_ID = "53494d552101"

    def createLog(self, name, port, expectStartMsg=True):
        return self.__logFactory.createLog(name, port, expectStartMsg)

    def setUp(self):
        self.__logFactory = SocketReaderFactory()

        self.__copyDir = tempfile.mkdtemp()
        self.__runConfigDir = tempfile.mkdtemp()
        self.__daqDataDir = tempfile.mkdtemp()
        self.__spadeDir = tempfile.mkdtemp()

        self.comps = []
        self.cnc = None

        MostlyCnCServer.APPENDERS.clear()
        RealComponent.APPENDERS.clear()

        RunXMLValidator.setUp()

    def tearDown(self):
        for key in RealComponent.APPENDERS:
            RealComponent.APPENDERS[key].WaitForEmpty(10)
        for key in MostlyCnCServer.APPENDERS:
            MostlyCnCServer.APPENDERS[key].checkStatus(10)

        for comp in self.comps:
            comp.close()
        del self.comps[:]

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
        if self.__daqDataDir is not None:
            shutil.rmtree(self.__daqDataDir, ignore_errors=True)
            self.__daqDataDir = None
        if self.__spadeDir is not None:
            shutil.rmtree(self.__spadeDir, ignore_errors=True)
            self.__spadeDir = None

        try:
            self.__logFactory.tearDown()
        except:
            traceback.print_exc()

        RunXMLValidator.tearDown()

    def __addRange(rangeStr, rStart, rCurr):
        if not rangeStr.endswith(" "):
            rangeStr += ","
        if rStart == rCurr:
            rangeStr += "%d" % rCurr
        else:
            rangeStr += "%d-%d" % (rStart, rCurr)
        return rangeStr

    def __listComponentsLegibly(self, comps):
        cycleList = self.comps[:]
        cycleList.sort()

        compDict = {}
        for c in cycleList:
            if not c.name() in compDict:
                compDict[c.name()] = []
            compDict[c.name()].append(c.num())

        strList = []
        for name in compDict:
            numList = compDict[name]

            if len(numList) == 1:
                num = numList[0]
                if num == 0:
                    strList.append(name)
                else:
                    strList.append("%s#%d" % (name, num))
                continue

            rangeStr = "name "
            rStart = None
            rCurr = None
            for n in numList:
                if rCurr == None:
                    rStart = n
                    rCurr = n
                elif rCurr == n - 1:
                    rCurr = n
                else:
                    rangeStr = self.__addRange(rangeStr, rStart, rCurr)
                    rStart = n
                    rCurr = n
                    strList.append(self.__addRange(rangeStr, rStart, rCurr))

        return ", ".join(strList)

    def __runEverything(self, forceRestart=False, switchRun=False):
        catchall = self.createLog('master', 18999)
        dashlog = MockLogger('dashlog')

        compData = [('stringHub', self.HUB_NUMBER, (("hit", "o", 1), )),
                    ('inIceTrigger', 0, (("hit", "i", 2), ("trig", "o", 3), )),
                    ('eventBuilder', 0, (("trig", "i", 4), )), ]
        compHost = 'localhost'

        cluCfg = MockClusterConfig("clusterFoo")
        for cd in compData:
            cluCfg.addComponent("%s#%d" % (cd[0], cd[1]), "java", "", compHost)

        catchall.addExpectedTextRegexp(r'\S+ \S+ \S+ \S+ \S+ \S+ \S+')

        self.cnc = MostlyCnCServer(clusterConfigObject=cluCfg,
                                   copyDir=self.__copyDir,
                                   runConfigDir=self.__runConfigDir,
                                   daqDataDir=self.__daqDataDir,
                                   spadeDir=self.__spadeDir,
                                   logPort=catchall.getPort(),
                                   logFactory=self.__logFactory,
                                   dashlog=dashlog,
                                   forceRestart=forceRestart)
        t = threading.Thread(name="CnCRun", target=self.cnc.run, args=())
        t.setDaemon(True)
        t.start()

        catchall.checkStatus(100)

        basePort = 19000
        baseLogPort = DAQPort.RUNCOMP_BASE

        logs = {}

        for cd in compData:
            catchall.addExpectedExact("Test msg")

            if cd[1] == 0:
                fullName = cd[0]
            else:
                fullName = "%s#%d" % (cd[0], cd[1])
            catchall.addExpectedText('Registered %s' % fullName)

            comp = RealComponent(cd[0], cd[1], basePort, basePort + 1, cd[2])

            logs[comp.fullName()] = self.createLog(comp.fullName(),
                                                   baseLogPort, False)
            comp.setExpectedRunLogPort(baseLogPort)

            basePort += 2
            baseLogPort += 1

            self.comps.append(comp)

        catchall.checkStatus(100)
        for nm in logs:
            logs[nm].checkStatus(100)

        s = self.cnc.rpc_component_list_dicts()
        self.assertEqual(len(self.comps), len(s),
                         'Expected %s components, not %d' %
                         (len(self.comps), len(s)))
        for d in s:
            comp = None
            for c in self.comps:
                if d["compName"] == c.name() and d["compNum"] == c.number():
                    comp = c
                    break

            self.assertTrue(comp is not None,
                            "Unknown component %s#%d" %
                            (d["compName"], d["compNum"]))
            self.assertEqual(compHost, d["host"],
                             'Expected %s host %s, not %s' %
                             (comp.fullName(), compHost, d["host"]))
            self.assertEqual(comp.cmdPort(), d["rpcPort"],
                             'Expected %s cmdPort %d, not %d' %
                             (comp.fullName(), comp.cmdPort(), d["rpcPort"]))
            self.assertEqual(comp.mbeanPort(), d["mbeanPort"],
                             'Expected %s mbeanPort %d, not %d' %
                             (comp.fullName(), comp.mbeanPort(),
                              d["mbeanPort"]))

        rcFile = MockRunConfigFile(self.__runConfigDir)

        compList = []
        for comp in self.comps:
            if not comp.isHub():
                compList.append(comp.fullName())

        domList = [MockRunConfigFile.createDOM(self.DOM_MAINBOARD_ID), ]

        runConfig = rcFile.create(compList, domList)

        catchall.addExpectedTextRegexp('Loading run configuration .*')
        catchall.addExpectedTextRegexp('Loaded run configuration .*')

        for comp in self.comps:
            catchall.addExpectedExact('Config %s#%d with %s' %
                                      (comp.name(), comp.number(), runConfig))

        catchall.addExpectedTextRegexp(r"Built runset #\d+: .*")

        runNum = 444

        setId = self.cnc.rpc_runset_make(runConfig, runNum, strict=False)
        for comp in self.comps:
            self.assertEqual('ready', comp.getState(),
                             'Unexpected state %s for %s' %
                             (comp.getState(), comp.fullName()))

        time.sleep(1)

        catchall.checkStatus(100)

        rs = self.cnc.rpc_runset_list(setId)
        for d in rs:
            comp = None
            for c in self.comps:
                if c.id() == d["id"]:
                    comp = c
                    break
            self.assertTrue(comp is not None,
                            "Unknown component %s#%d" %
                            (d["compName"], d["compNum"]))

            self.assertEqual(comp.name(), d["compName"],
                             ("Component#%d name should be \"%s\"," +
                              "not \"%s\"") % \
                               (comp.id(), comp.name(), d["compName"]))
            self.assertEqual(comp.number(), d["compNum"],
                             ("Component#%d \"%s\" number should be %d," +
                               " not %d") %
                             (comp.id(), comp.fullName(), comp.number(),
                             d["compNum"]))
            self.assertEqual(compHost, d["host"],
                              ("Component#%d \"%s\" host should be" +
                               " \"%s\", not \"%s\"") %
                              (comp.id(), comp.fullName(), compHost,
                                d["host"]))
            self.assertEqual(comp.cmdPort(), d["rpcPort"],
                              ("Component#%d \"%s\" rpcPort should be" +
                               " \"%s\", not \"%s\"") %
                              (comp.id(), comp.fullName(), comp.cmdPort(),
                                d["rpcPort"]))
            self.assertEqual(comp.mbeanPort(), d["mbeanPort"],
                              ("Component#%d \"%s\" mbeanPort should be" +
                               " \"%s\", not \"%s\"") %
                              (comp.id(), comp.fullName(), comp.mbeanPort(),
                                d["mbeanPort"]))

        catchall.checkStatus(100)
        for nm in logs:
            logs[nm].checkStatus(100)

        baseLogPort = DAQPort.RUNCOMP_BASE
        for comp in self.comps:
            log = logs[comp.fullName()]
            log.addExpectedTextRegexp("Start of log at LOG=log(\S+:%d)" %
                                      baseLogPort)
            log.addExpectedExact('Test msg')
            log.addExpectedText('filename revision date time author')
            baseLogPort += 1

        catchall.addExpectedText("Starting run #%d on \"%s\"" %
                                 (runNum, cluCfg.descName()))

        dashlog.addExpectedRegexp(r"Version info: \S+ \d+" +
                                  r" \S+ \S+ \S+ \S+ \d+\S*")
        dashlog.addExpectedExact("Run configuration: %s" % runConfig)
        dashlog.addExpectedExact("Cluster: %s" % cluCfg.descName())

        moniType = RunOption.MONI_TO_NONE

        for comp in self.comps:
            log = logs[comp.fullName()]
            log.addExpectedExact('Start #%d on %s' % (runNum, comp.fullName()))

        dashlog.addExpectedExact("Starting run %d..." % runNum)

        for comp in self.comps:
            if comp.name() == "stringHub":
                comp.setBeanFieldValue("stringhub", "LatestFirstChannelHitTime",
                                       10)
                comp.setBeanFieldValue("stringhub", "NumberOfNonZombies",
                                       10)

        global ACTIVE_WARNING
        if not LIVE_IMPORT and not ACTIVE_WARNING:
            ACTIVE_WARNING = True
            dashlog.addExpectedExact("Cannot import IceCube Live code, so" +
                                     " per-string active DOM stats wil not" +
                                     " be reported")

        catchall.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for NonHubs")
        catchall.addExpectedTextRegexp(r"Waited \d+\.\d+ seconds for Hubs")

        self.assertEqual(self.cnc.rpc_runset_start_run(setId, runNum,
                                                       moniType), 'OK')

        catchall.checkStatus(100)
        dashlog.checkStatus(100)
        for nm in logs:
            logs[nm].checkStatus(100)

        rateTracker = RateTracker(10000000000, 100, 0, 0, 0)

        if switchRun:
            for i in xrange(5):
                rateTracker.updateRunData(self.cnc, setId, self.comps)

            for comp in self.comps:
                if not comp.isHub():
                    log = logs[comp.fullName()]
                    log.addExpectedExact('Switch %s to run#%d' %
                                         (comp.fullName(), runNum + 1))

            dashlog.addExpectedRegexp(r"Version info: \S+ \d+" +
                                      r" \S+ \S+ \S+ \S+ \d+\S*")
            dashlog.addExpectedExact("Run configuration: %s" % runConfig)
            dashlog.addExpectedExact("Cluster: %s" % cluCfg.descName())

            newNum = runNum + 1

            dashlog.addExpectedExact("Switching to run %d..." % newNum)

            rateTracker.updateRunData(self.cnc, setId, self.comps)

            rateTracker.addFinalLogMsgs(dashlog)
            dashlog.addExpectedExact("Run switched SUCCESSFULLY.")

            self.cnc.rpc_runset_switch_run(setId, newNum)

            (numEvts, numMoni, numSN, numTcal) = rateTracker.getTotals()

            rateTracker.validateRunXML(self, runNum, runConfig,
                                       cluCfg.descName())

            runNum = newNum

            catchall.checkStatus(100)
            dashlog.checkStatus(100)
            for nm in logs:
                logs[nm].checkStatus(100)

            rateTracker.reset()

        for i in xrange(5):
            rateTracker.updateRunData(self.cnc, setId, self.comps)

        for comp in self.comps:
            log = logs[comp.fullName()]
            log.addExpectedExact('Stop %s' % comp.fullName())

        rateTracker.updateRunData(self.cnc, setId, self.comps)
        rateTracker.addFinalLogMsgs(dashlog)

        dashlog.addExpectedExact("Run terminated SUCCESSFULLY.")

        for comp in self.comps:
            if comp.name() == "stringHub":
                comp.setBeanFieldValue("stringhub", "EarliestLastChannelHitTime",
                                       10)

        if forceRestart:
            cycleStr = self.__listComponentsLegibly(self.comps)
            catchall.addExpectedText("Cycling components %s" % cycleStr)

        self.assertEqual(self.cnc.rpc_runset_stop_run(setId), 'OK')

        catchall.checkStatus(100)
        dashlog.checkStatus(100)
        for nm in logs:
            logs[nm].checkStatus(100)

        rateTracker.validateRunXML(self, runNum, runConfig, cluCfg.descName())

        if forceRestart:
            try:
                rs = self.cnc.rpc_runset_list(setId)
                self.fail("Runset #%d should have been destroyed" % setId)
            except CnCServerException:
                pass
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 0)
        else:
            self.assertEqual(len(self.cnc.rpc_runset_list(setId)),
                             len(compData))
            self.assertEqual(self.cnc.rpc_component_count(), 0)
            self.assertEqual(self.cnc.rpc_runset_count(), 1)

            serverAppender = MostlyCnCServer.APPENDERS['server']

            self.assertEqual(self.cnc.rpc_runset_break(setId), 'OK')

            serverAppender.checkStatus(100)

            self.assertEqual(self.cnc.rpc_component_count(), len(compData))
            self.assertEqual(self.cnc.rpc_runset_count(), 0)

            serverAppender.checkStatus(100)

        catchall.checkStatus(100)
        for nm in logs:
            logs[nm].checkStatus(100)

        self.cnc.closeServer()

    def __setRunData(self, comps, numEvts, firstEvtTime, lastEvtTime, numTcal,
                     numSN, numMoni, firstGood, lastGood):
        for comp in comps:
            if comp.name() == "eventBuilder":
                print >>sys.stderr, "---- Set RunData for %s" % comp.fullName()
                comp.setRunData(numEvts, firstEvtTime, lastEvtTime, firstGood,
                                lastGood)
                comp.setBeanFieldValue("backEnd", "EventData",
                                       (numEvts, lastEvtTime))
                comp.setBeanFieldValue("backEnd", "FirstEventTime",
                                       firstEvtTime)
                comp.setBeanFieldValue("backEnd", "GoodTimes",
                                       (firstGood, lastGood))
            elif comp.name() == "secondaryBuilders":
                print >>sys.stderr, "---- Set RunData for %s" % comp.fullName()
                comp.setRunData(numTcal, numSN, numMoni)
            else:
                print >>sys.stderr, "**** Not setting RunData for %s" % \
                    comp.fullName()

    def testEverything(self):
        self.__runEverything()

    def testEverythingAgain(self):
        #if sys.platform != 'darwin':
        #    print 'Skipping server tests in non-Darwin OS'
        #    return

        self.__runEverything()

    def testForceRestart(self):
        #if sys.platform != 'darwin':
        #    print 'Skipping server tests in non-Darwin OS'
        #    return

        self.__runEverything(forceRestart=True)

    def testSwitchRun(self):
        #if sys.platform != 'darwin':
        #    print 'Skipping server tests in non-Darwin OS'
        #    return

        self.__runEverything(switchRun=True)

if __name__ == '__main__':
    unittest.main()
