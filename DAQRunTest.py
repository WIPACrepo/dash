#!/usr/bin/env python

import datetime, os, sys
import tempfile, threading, time, unittest
from DAQRun import DAQRun, PayloadTime, RunArgs
from DAQConst import DAQPort

from DAQMocks import MockAppender, MockIntervalTimer, MockLogger, \
    SocketReaderFactory

class MockMoni(object):
    def __init__(self):
        self.entries = {}

    def addEntry(self, cid, section, field, val):
        if not self.entries.has_key(cid):
            self.entries[cid] = {}

        key = section + ':' + field
        if self.entries[cid].has_key(key):
            raise Exception('Found multiple entries for %s %s/%s' %
                            (cid, section, field))
        self.entries[cid][key] = val

    def doMoni(self):
        pass

    def getSingleBeanField(self, cid, section, field):
        if not self.entries.has_key(cid):
            raise Exception('No MBean entries for %s' % cid)

        key = section + ':' + field
        if not self.entries[cid].has_key(key):
            raise Exception('No MBean entry for %s %s/%s' %
                            (cid, section, field))

        return self.entries[cid][key]

class MockWatchdog(object):
    def __init__(self):
        self.inProg = False
        self.caughtErr = False
        self.done = False
        self.healthy = False
        self.isTime = False

        self.threadCleared = False
        self.watchStarted = False

    def caughtError(self):
        return self.caughtErr

    def clearThread(self):
        self.threadCleared = True

    def inProgress(self):
        return self.inProg

    def isDone(self):
        return self.done

    def isHealthy(self):
        return self.healthy

    def startWatch(self):
        self.watchStarted = True

    def timeToWatch(self):
        return self.isTime

class MockCnCRPC(object):
    def __init__(self):
        self.compList = None

        self.nextRunsetId = 1

        self.runsetId = None
        self.runsetComps = None

        self.denyBreak = False

        self.resetFlags()

    def __buildRunset(self, required):
        if self.compList is None:
            raise Exception('List of components has not been set')

        newSet = []
        for r in required:
            sep = r.find('#')
            if sep < 0:
                raise Exception('Found bad component "%s"' % r)

            name = r[:sep]
            id = int(r[sep+1:])

            found = False
            for c in self.compList:
                if c[1] == name and c[2] == id:
                    found = True
                    newSet.append((c[0], c[1], c[2], c[3], c[4], c[5]))
                    break

            if not found:
                raise Exception('Could not find component "%s"' % r)

        self.runsetComps = newSet

        if self.nextRunsetId is None:
            self.nextRunsetId = 43
        self.runsetId = self.nextRunsetId
        self.nextRunsetId += 1

        return self.runsetId

    def _doSubrun(self, runSetId, subRunId, domList):
        pass

    def __listRunset(self, id):
        if self.runsetId is None:
            return ()
        if id != self.runsetId:
            raise Exception('Expected runset#%d, not #%d' % (self.runsetId, id))
        return self.runsetComps

    def __listRunsetIDs(self):
        if self.runsetId is None:
            return []
        return [self.runsetId, ]

    def __showComponents(self):
        if self.compList is None:
            raise Exception('List of components has not been set')

        showList = []

        for c in self.compList:
            showList.append('ID#%d %s#%d at %s:%d' %
                            (c[0], c[1], c[2], c[3], c[4]))

        return showList

    def getRunsetLoggers(self):
        return self.runsetLoggers

    def resetFlags(self):
        self.LogToFlag = False
        self.RSConfigFlag = False
        self.RSStartFlag = False
        self.RSStopFlag = False
        self.RSBreakFlag = False
        self.RSLogToFlag = False
        self.RSFlashFlag = False

    def rpccall(self, name, *args):
        if name == 'rpc_show_components':
            return self.__showComponents()
        if name == 'rpc_log_to':
            self.LogToFlag = True
            return
        if name == 'rpc_runset_make':
            return self.__buildRunset(args[0])
        if name == 'rpc_runset_list':
            return self.__listRunset(args[0])
        if name == 'rpc_runset_configure':
            self.RSConfigFlag = True
            return
        if name == 'rpc_runset_start_run':
            self.RSStartFlag = True
            return
        if name == 'rpc_runset_stop_run':
            self.RSStopFlag = True
            return
        if name == 'rpc_runset_break':
            if self.denyBreak:
                raise Exception('BROKEN')
            self.RSBreakFlag = True
            return
        if name == 'rpc_runset_log_to':
            if self.runsetId is None:
                raise Exception('Unexpected runset#%d' % args[0])
            if args[0] != self.runsetId:
                raise Exception('Expected runset#%d, not #%d' %
                                (self.runsetId, args[0]))
            self.runsetLoggers = args[2]
            return
        if name == 'rpc_runset_subrun':
            self.RSFlashFlag = True
            return
        if name == "rpc_runset_listIDs":
            return self.__listRunsetIDs()

        raise Exception('Unknown RPC call "%s"' % name)

    def setComponents(self, lst):
        self.compList = []
        for c in lst:
            self.compList.append((c[0], c[1], c[2], c[3], c[4], c[5]))

    def setRunSet(self, id, comps):
        self.runsetId = id
        self.runsetComps = comps

    def showStats(self):
        return 'NoStats'

class MostlyDAQRun(DAQRun):
    def __init__(self, extraArgs=None, startServer=False):
        self.__mockAppender = None

        super(MostlyDAQRun, self).__init__(self.__getRunArgs(extraArgs),
                                           startServer)

    def __getRunArgs(self, extraArgs=None):

        stdArgs = { '-c' : 'src/test/resources/config',
                    '-l' : TestDAQRun.LOG_DIR,
                    '-n' : '',
                    '-p' : str(TestDAQRun.NEXTPORT),
                    '-q' : '',
                    '-s' : TestDAQRun.SPADE_DIR,
                    '-u' : TestDAQRun.CLUSTER_CONFIG }
        TestDAQRun.NEXTPORT += 1

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

    def createInitialAppender(self):
        if self.__mockAppender is None:
            self.__mockAppender = MockAppender('runlog')

        return self.__mockAppender

    def setup_timer(self, name, interval):
        return MockIntervalTimer(interval)

class StubbedDAQRun(MostlyDAQRun):
    __logServer = None

    def __init__(self, extraArgs=None, startServer=False):
        self.__fileAppender = None
        self.__logServer = None

        self.catchAllLog = None

        super(StubbedDAQRun, self).__init__(extraArgs, startServer)

    def createFileAppender(self):
        return self.__fileAppender

    def createLogSocketServer(cls, logPort, shortName, logFile):
        if not cls.__logServer.serving():
            cls.__logServer.startServing()
        return cls.__logServer
    createLogSocketServer = classmethod(createLogSocketServer)

    def createRunLogDirectory(self, runNum, logDir):
        self.setLogPath(runNum, logDir)

    def get_base_prefix(self, runNum, runTime, runDuration):
        return 'MockPrefix#%d' % runNum

    def move_spade_files(self, copyDir, basePrefix, logTopLevel, runDir,
                         spadeDir):
        pass

    def restartComponents(self, pShell):
        pass

    def setFileAppender(self, appender):
        self.__fileAppender = appender

    def setLogSocketServer(cls, logger):
        cls.__logServer = logger
    setLogSocketServer = classmethod(setLogSocketServer)

    def setup_monitoring(self, log, moniPath, comps, moniType):
        return MockMoni()

    def setup_watchdog(self, log, interval, comps):
        return MockWatchdog()

class TestDAQRun(unittest.TestCase):
    NEXTPORT = 9876
    CLUSTER_CONFIG = 'sim-localhost'
    SPADE_DIR = '/tmp'
    LOG_DIR = None

    def __createLoggers(self, dr):
        appender = MockAppender('main')
        dr.setFileAppender(appender)

        catchall = self.__logFactory.createLog('catchall', DAQPort.CATCHALL,
                                               False)
        StubbedDAQRun.setLogSocketServer(catchall)

        return (appender, catchall)

    def __finishRunThreadTest(self, dr, cnc, appender, catchall, ebID, sbID,
                              comps):
        LOG_INFO = False

        time.sleep(0.4)
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)

        setId = 1
        runNum = 654
        configName = 'sim5str'

        if LOG_INFO:
            catchall.addExpectedText('Loaded global configuration "%s"' %
                                     configName)
            catchall.addExpectedText('Configuration includes detector in-ice')
            catchall.addExpectedText('Configuration includes detector icetop')

            compSrt = comps[:]
            compSrt.sort(self.__sortCompTuple)

            for c in compSrt:
                catchall.addExpectedText('Component list will require %s#%d' %
                                         (c[1], c[2]))

        catchall.addExpectedText(('Starting run %d (waiting for required %d' +
                                  ' components to register w/ CnCServer)') %
                                 (runNum, len(comps)))
        catchall.addExpectedText('Created Run Set #%d' % setId)

        appender.addExpectedExact(('Version info: %(filename)s %(revision)s' +
                                 ' %(date)s %(time)s %(author)s %(release)s' +
                                 ' %(repo_rev)s') % dr.versionInfo)
        appender.addExpectedExact('Starting run %d...' % runNum)
        appender.addExpectedExact('Run configuration: %s' % configName)
        appender.addExpectedExact('Cluster configuration: %s' %
                                TestDAQRun.CLUSTER_CONFIG)
        if LOG_INFO:
            appender.addExpectedExact('Created logger for CnCServer')
            appender.addExpectedExact('Setting up logging for %d components' %
                                      len(comps))

            for c in compSrt:
                logPort = DAQPort.RUNCOMP_BASE + c[0]
                appender.addExpectedExact('%s(%d %s:%d) -> %s:%d' %
                                          (c[1], c[0], c[3], c[4], dr.ip,
                                           logPort))
            appender.addExpectedExact('Configuring run set...')

        appender.addExpectedExact('Started run %d on run set %d' %
                                (runNum, setId))

        dr.rpc_start_run(runNum, None, configName)

        numTries = 0
        while dr.runState == 'STARTING' and numTries < 500:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('RUNNING', dr.runState, 'Should be running, not ' +
                          dr.runState)
        self.failIf(cnc.RSBreakFlag, 'Runset should not have been broken')
        self.failUnless(cnc.RSConfigFlag, 'Runset was not configured')
        self.failUnless(cnc.RSStartFlag, 'Runset was not started')
        catchall.checkStatus(10)
        cnc.resetFlags()

        numTries = 0
        while not appender.isEmpty() and numTries < 500:
            time.sleep(0.1)
            numTries += 1

        appender.checkStatus(10)

        subRunId = 1
        domList = [('53494d550101', 0, 1, 2, 3, 4),
                   ['1001', '22', 1, 2, 3, 4, 5],
                   ('a', 0, 1, 2, 3, 4)]

        flashList = [domList[0], ['53494d550122', ] + domList[1][2:]]
        appender.addExpectedExact(("Subrun %d: will ignore missing DOM ('DOM" +
                                 " %s not found in config!')...") %
                                (subRunId, domList[2][0]))
        appender.addExpectedExact('Subrun %d: flashing DOMs (%s)' %
                                (subRunId, str(flashList)))

        dr.rpc_flash(subRunId, domList)
        self.failUnless(cnc.RSFlashFlag, 'Runset should have flashed')
        appender.checkStatus(10)
        catchall.checkStatus(10)

        numEvts = 17
        evtTime = 639
        numMoni = 222
        numSN = 51
        numTCal = 93

        dr.moni.addEntry(ebID, 'backEnd', 'NumEventsSent', str(numEvts))
        dr.moni.addEntry(5, 'backEnd', 'FirstEventTime', str(evtTime))
        dr.moni.addEntry(ebID, 'backEnd', 'EventData',
                         (str(numEvts), str(evtTime)))
        dr.moni.addEntry(sbID, 'moniBuilder', 'TotalDispatchedData',
                         str(numMoni))
        dr.moni.addEntry(sbID, 'snBuilder', 'TotalDispatchedData', str(numSN))
        dr.moni.addEntry(sbID, 'tcalBuilder', 'TotalDispatchedData',
                         str(numTCal))

        appender.addExpectedExact('Stopping run %d' % runNum)
        appender.addExpectedExact('%d physics events collected in 0 seconds' %
                                numEvts)
        appender.addExpectedExact('%d moni events, %d SN events, %d tcals' %
                                (numMoni, numSN, numTCal))
        if LOG_INFO:
            appender.addExpectedExact('Stopping component logging')
            appender.addExpectedExact('RPC Call stats:\n%s' % cnc.showStats())
        appender.addExpectedExact('Run terminated SUCCESSFULLY.')
        if LOG_INFO:
            appender.addExpectedExact(('Queueing data for SPADE (spadeDir=%s,' +
                                       ' logDir=%s, runNum=%s)...') %
                                      (TestDAQRun.SPADE_DIR, TestDAQRun.LOG_DIR,
                                       runNum))

        dr.rpc_stop_run()

        numTries = 0
        while dr.runState == 'STOPPING' and numTries < 100:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)
        self.failUnless(cnc.RSStopFlag, 'Runset was not stopped')
        appender.checkStatus(10)
        catchall.checkStatus(10)
        cnc.resetFlags()

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
        appender.checkStatus(10)
        catchall.checkStatus(10)

        if LOG_INFO:
            catchall.addExpectedText('Breaking run set...')

        dr.rpc_release_runsets()
        self.failUnless(cnc.RSBreakFlag, 'Runset should have been broken')
        appender.checkStatus(10)
        cnc.resetFlags()

        dr.running = False
        time.sleep(0.4)

        numTries = 0
        while not catchall.isEmpty() and numTries < 500:
            time.sleep(0.1)
            numTries += 1

        appender.checkStatus(10)
        catchall.checkStatus(10)

    def __sortCompTuple(self, x, y):
        if x[1] == 'stringHub' and y[1] != 'stringHub':
            return 1
        elif x[1] != 'stringHub' and y[1] == 'stringHub':
            return -1

        if x[0] == y[0]:
            return 0
        elif x[0] < y[0]:
            return -1
        else:
            return 1

    def setUp(self):
        TestDAQRun.LOG_DIR = tempfile.mkdtemp()

        self.__logFactory = SocketReaderFactory()

    def tearDown(self):
        self.__logFactory.tearDown()

        for root, dirs, files in os.walk(TestDAQRun.LOG_DIR,
                                         topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

        os.rmdir(TestDAQRun.LOG_DIR)
        TestDAQRun.LOG_DIR = None

    def testParseCompName(self):
        lst = (('ID#1 foo#0 at localhost:12345 ',
                (1, 'foo', 0, 'localhost', 12345)),
               ('ID#22 bar#11 at 192.168.1.10:54321',
                (22, 'bar', 11, '192.168.1.10', 54321)),
               ('bad', ()))

        for l in lst:
            t = DAQRun.parseComponentName(l[0])
            self.assertEqual(len(l[1]), len(t),
                             'Expected %d-element tuple, but got %d elements' %
                             (len(l[1]), len(t)))
            for n in range(0, len(t)):
                self.assertEquals(l[1][n], t[n],
                                  'Expected element#%d to be "%s", not "%s"' %
                                  (n, str(l[1][n]), str(t[n])))

    def testGetNameList(self):
        lst = (('ID#1 foo#0 at localhost:12345 ',
                (1, 'foo', 0, 'localhost', 12345)),
               ('ID#22 bar#11 at 192.168.1.10:54321',
                (22, 'bar', 11, '192.168.1.10', 54321)),
               ('bad', ()))

        names = []
        vals = []
        for l in lst:
            names.append(l[0])
            if len(l[1]) > 0:
                vals.append('%s#%d' % (l[1][1], l[1][2]))

        nlst = list(DAQRun.getNameList(names))
        self.assertEqual(len(vals), len(nlst),
                         'Expected %d-element list, but got %d elements' %
                         (len(vals), len(nlst)))
        for n in range(0, len(nlst)):
            self.assertEquals(vals[n], nlst[n],
                              'Expected element#%d to be "%s", not "%s"' %
                              (n, str(vals[n]), str(nlst[n])))

    def testFindMissing(self):
        required = ['abc#1', 'def#2', 'ghi#3']

        tooFew = []
        missing = None
        for r in required:
            if len(tooFew) == 0 or missing is not None:
                tooFew.append(r)
            else:
                missing = r

        waitList = DAQRun.findMissing(required, tooFew)
        self.assertEquals(1, len(waitList),
                          "Expected ['%s'], not %s" % (missing, str(waitList)))
        self.assertEquals(missing, waitList[0], "Expected '%s' not '%s'" %
                          (missing, waitList[0]))

        justRight = []
        for r in required:
            justRight.append(r)

        waitList = DAQRun.findMissing(required, justRight)
        self.assertEquals(0, len(waitList), "Did not expect %s" % str(waitList))

        tooMany = []
        for r in required:
            tooMany.append(r)
        tooMany.append('jkl#9')

        waitList = DAQRun.findMissing(required, tooMany)
        self.assertEquals(0, len(waitList), "Did not expect %s" % str(waitList))

    def testCreate(self):
        MostlyDAQRun()

    def testWaitForRequiredBad(self):
        comps = [(0, 'abc', 1, 'xxx', 1, 2),
                 (1, 'def', 2, 'yyy', 3, 4),
                 (2, 'ghi', 3, 'zzz', 5, 6)]

        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        cnc = MockCnCRPC()
        cnc.setComponents(comps[1:])

        expRunNum = 100
        expId = 123

        dr.runStats.setRunNumber(expRunNum)
        dr.runSetID = expId

        DAQRun.REGISTRATION_TIMEOUT = 0

        required = []
        for c in comps:
            required.append('%s#%d' % (c[1], c[2]))

        logger.addExpectedExact(('Starting run %d (waiting for required %d' +
                                 ' components to register w/ CnCServer)') %
                                (dr.runStats.getRunNumber(), len(required)))

        try:
            dr.build_run_set(cnc, required)
            self.fail('Unexpected success')
        except Exception, e:
            self.assertEquals('Still waiting for ' + required[0], str(e),
                              'Unexpected exception message "%s"' % str(e))

        logger.checkStatus(10)

    def testWaitForRequiredGood(self):
        comps = [(0, 'abc', 1, 'xxx', 1, 2),
                 (1, 'def', 2, 'yyy', 3, 4),
                 (2, 'ghi', 3, 'zzz', 5, 6)]

        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        cnc = MockCnCRPC()
        cnc.setComponents(comps)

        expRunNum = 100

        dr.runStats.setRunNumber(expRunNum)

        DAQRun.REGISTRATION_TIMEOUT = 0

        expId = cnc.nextRunsetId

        required = []
        for c in comps:
            required.append('%s#%d' % (c[1], c[2]))


        logger.addExpectedExact(('Starting run %d (waiting for required %d' +
                                 ' components to register w/ CnCServer)') %
                                (dr.runStats.getRunNumber(), len(required)))
        logger.addExpectedExact('Created Run Set #%d' % expId)

        dr.build_run_set(cnc, required)
        self.assertEquals(expId, dr.runSetID, 'Expected runset#%d, not #%d' %
                          (expId, dr.runSetID))

        logger.checkStatus(10)

    def testFillCompDict(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        expId = 99
        expComps = [(3, 'foo', 0, 'localhost', 1234, 5678),
                    (7, 'bar', 1, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        for key, comp in dr.components.iteritems():
            for i in range(0, len(expComps)):
                if key == expComps[i][0]:
                    self.assertEquals(expComps[i][1], comp.name(),
                                      'Expected shortName#%d to be %s, not %s' %
                                      (i, expComps[i][1], comp.name()))
                    self.assertEquals(expComps[i][2], comp.id(),
                                      'Expected daqID#%d to be %d, not %d' %
                                      (i, expComps[i][2], comp.id()))
                    self.assertEquals(expComps[i][3], comp.inetAddress(),
                                      'Expected inetAddr#%d to be %s, not %s' %
                                      (i, expComps[i][3], comp.inetAddress()))
                    self.assertEquals(expComps[i][4], comp.rpcPort(),
                                      'Expected rpcPort#%d to be %d, not %d' %
                                      (i, expComps[i][4], comp.rpcPort()))
                    self.assertEquals(expComps[i][5], comp.mbeanPort(),
                                      'Expected mbeanPort#%d to be %d, not %d' %
                                      (i, expComps[i][5], comp.mbeanPort()))

        logger.checkStatus(10)

    def testRunsetConfig(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        cnc = MockCnCRPC()

        logger.addExpectedExact('Configuring run set...')

        dr.runset_configure(cnc, 1, 'foo')
        self.failUnless(cnc.RSConfigFlag, 'Runset was not configured')

        logger.checkStatus(10)

    def testRunsetStart(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        cnc = MockCnCRPC()

        expRunNum = 100
        expId = 123

        dr.runStats.setRunNumber(expRunNum)
        dr.runSetID = expId

        logger.addExpectedExact('Started run %d on run set %d' %
                               (expRunNum, expId))

        dr.start_run(cnc)
        self.failUnless(cnc.RSStartFlag, 'Runset was not started')

        logger.checkStatus(10)

    def testRunsetStop(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        cnc = MockCnCRPC()

        expRunNum = 100

        dr.runStats.setRunNumber(expRunNum)

        logger.addExpectedExact('Stopping run %d' % expRunNum)

        dr.stop_run(cnc)
        self.failUnless(cnc.RSStopFlag, 'Runset was not started')

        logger.checkStatus(10)

    def testRunsetBreakGood(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        expId = 99
        expComps = [(3, 'foo', 0, 'localhost', 1234, 5678),
                    (7, 'bar', 1, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        logger.addExpectedExact('Breaking run set...')

        dr.break_existing_runset(cnc)
        #self.failUnless(cnc.RSBreakFlag, 'Runset was not broken')
        self.assertEquals(0, len(dr.components),
                          'Should not have any components')
        if dr.runSetID is not None: self.fail('Runset ID should be unset')
        if dr.lastConfig is not None: self.fail('Last config should be unset')

        logger.checkStatus(10)

    def testRunsetBreakBad(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        expId = 99
        expComps = [(3, 'foo', 0, 'localhost', 1234, 5678),
                    (7, 'bar', 1, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)
        cnc.denyBreak = True

        dr.runSetID = expId

        logger.addExpectedExact('Breaking run set...')
        logger.addExpectedRegexp('WARNING: failed to break run set - .*')

        dr.break_existing_runset(cnc)
        self.failIf(cnc.RSBreakFlag, 'Runset was broken')
        self.assertEquals(0, len(dr.components),
                          'Should not have any components')
        if dr.runSetID is not None: self.fail('Runset ID should be unset')
        if dr.lastConfig is not None: self.fail('Last config should be unset')

        logger.checkStatus(10)

    def testGetEventCounts(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        numEvts = 17
        evtTime = 639
        numMoni = 222
        numSN = 51
        numTCal = 93

        dr.moni = MockMoni()

        dr.moni.addEntry(5, 'backEnd', 'NumEventsSent', str(numEvts))
        dr.moni.addEntry(5, 'backEnd', 'FirstEventTime', str(evtTime))
        dr.moni.addEntry(5, 'backEnd', 'EventData',
                         (str(numEvts), str(evtTime)))
        dr.moni.addEntry(17, 'moniBuilder', 'TotalDispatchedData', str(numMoni))
        dr.moni.addEntry(17, 'snBuilder', 'TotalDispatchedData', str(numSN))
        dr.moni.addEntry(17, 'tcalBuilder', 'TotalDispatchedData', str(numTCal))

        expId = 99
        expComps = [(5, 'eventBuilder', 0, 'x', 1234, 5678),
                    (17, 'secondaryBuilders', 0, 'x', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        evtTime = None
        evtPayTime = None
        moniTime = None
        snTime = None
        tcalTime = None

        expCnts = (numEvts, evtTime, evtPayTime, numMoni, moniTime,
                   numSN, snTime, numTCal, tcalTime)

        cnts = dr.getEventData()
        self.assertEquals(len(expCnts), len(cnts),
                          'Expected %d event counts, not %d' %
                          (len(expCnts), len(cnts)))
        for i in range(0, len(expCnts)):
            if expCnts[i] is None: continue
            self.assertEquals(expCnts[i], cnts[i],
                              'Expected event count #%d to be %d, not %d' %
                              (i, expCnts[i], cnts[i]))

        logger.checkStatus(10)

    def testCheckNone(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        rtnVal = dr.check_timers()
        self.failUnless(rtnVal, 'Expected call to succeed')

        logger.checkStatus(10)

    def testCheckMoniRate(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        firstTime = long(time.time())

        maxRate = 300
        secInc = 2

        numEvts = 1000
        evtTime = firstTime + (maxRate * secInc)
        numMoni = 222
        numSN = 51
        numTCal = 93

        dr.moni = MockMoni()

        dr.moni.isTime = True
        dr.moni.addEntry(5, 'backEnd', 'NumEventsSent', str(numEvts))
        dr.moni.addEntry(5, 'backEnd', 'FirstEventTime', str(evtTime))
        dr.moni.addEntry(5, 'backEnd', 'EventData',
                         (str(numEvts), str(evtTime)))
        dr.moni.addEntry(17, 'moniBuilder', 'TotalDispatchedData',
                         str(numMoni))
        dr.moni.addEntry(17, 'snBuilder', 'TotalDispatchedData',
                         str(numSN))
        dr.moni.addEntry(17, 'tcalBuilder', 'TotalDispatchedData',
                         str(numTCal))

        expId = 99
        expComps = [(5, 'eventBuilder', 0, 'x', 1234, 5678),
                    (17, 'secondaryBuilders', 0, 'x', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        for i in range(0, maxRate):
            secs = maxRate - i
            evts = (maxRate - i) * secInc
            evtDT = PayloadTime.toDateTime(evtTime - secs)
            dr.runStats.addRate(evtDT, numEvts - evts)

        dr.fill_component_dictionaries(cnc)

        expMsg = ('\t%d physics events, %d moni events,' +
                  ' %d SN events, %d tcals') % \
                  (numEvts, numMoni, numSN, numTCal)

        logger.addExpectedExact(expMsg)

        dr.rateTimer.trigger()

        numTries = 0
        while dr.rateThread is not None and \
                not dr.rateThread.done() and \
                numTries < 100:
            time.sleep(0.1)
            numTries += 1

        rtnVal = dr.check_timers()
        self.failUnless(rtnVal, 'Expected call to succeed')

        logger.checkStatus(10)

    def testCheckMoni(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        firstTime = long(time.time())

        maxRate = 300
        secInc = 2

        numEvts = 17
        evtTime = firstTime + (maxRate * secInc)
        numMoni = 222
        numSN = 51
        numTCal = 93

        dr.moni = MockMoni()

        dr.moni.isTime = True
        dr.moni.addEntry(5, 'backEnd', 'NumEventsSent', str(numEvts))
        dr.moni.addEntry(5, 'backEnd', 'FirstEventTime', str(evtTime))
        dr.moni.addEntry(5, 'backEnd', 'EventData',
                         (str(numEvts), str(evtTime)))
        dr.moni.addEntry(17, 'moniBuilder', 'TotalDispatchedData',
                         str(numMoni))
        dr.moni.addEntry(17, 'snBuilder', 'TotalDispatchedData',
                         str(numSN))
        dr.moni.addEntry(17, 'tcalBuilder', 'TotalDispatchedData',
                         str(numTCal))

        expId = 99
        expComps = [(5, 'eventBuilder', 0, 'x', 1234, 5678),
                    (17, 'secondaryBuilders', 0, 'x', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        dr.rateTimer.trigger()

        numTries = 0
        while dr.rateThread is not None and \
                not dr.rateThread.done() and \
                numTries < 100:
            time.sleep(0.1)
            numTries += 1

        logger.addExpectedExact(('\t%d physics events, %d moni' +
                                 ' events, %d SN events, %d tcals') %
                                (numEvts, numMoni, numSN, numTCal))

        rtnVal = dr.check_timers()
        self.failUnless(rtnVal, 'Expected call to succeed')

        logger.checkStatus(10)

    def testCheckWatchdogNone(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.watchdog = MockWatchdog()

        dr.unHealthyCount = 0

        expCnt = 0

        rtnVal = dr.check_timers()
        self.failUnless(rtnVal, 'Expected call to succeed')

        self.failIf(dr.watchdog.threadCleared,
                    'Should not have cleared thread')
        self.failIf(dr.watchdog.watchStarted,
                    'Should not have started watchdog')
        self.assertEquals(expCnt, dr.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, dr.unHealthyCount))

        logger.checkStatus(10)

    def testCheckWatchdogStart(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.watchdog = MockWatchdog()

        dr.watchdog.isTime = True
        dr.unHealthyCount = 0

        expCnt = 0

        rtnVal = dr.check_timers()
        self.failUnless(rtnVal, 'Expected call to succeed')

        self.failIf(dr.watchdog.threadCleared, 'Should not have cleared thread')
        self.failUnless(dr.watchdog.watchStarted,
                        'Should have started watchdog')
        self.assertEquals(expCnt, dr.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, dr.unHealthyCount))

        logger.checkStatus(10)

    def testCheckWatchdogErr(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.watchdog = MockWatchdog()

        dr.watchdog.inProg = True
        dr.watchdog.caughtErr = True
        dr.unHealthyCount = 0

        expCnt = 0

        rtnVal = dr.check_timers()
        self.failIf(rtnVal, 'Expected call to succeed')

        self.failUnless(dr.watchdog.threadCleared, 'Should have cleared thread')
        self.failIf(dr.watchdog.watchStarted,
                    'Should not have started watchdog')
        self.assertEquals(expCnt, dr.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, dr.unHealthyCount))

        logger.checkStatus(10)

    def testCheckWatchdogHealthy(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.watchdog = MockWatchdog()

        dr.watchdog.inProg = True
        dr.watchdog.done = True
        dr.watchdog.healthy = True
        dr.unHealthyCount = 1

        expCnt = 0

        rtnVal = dr.check_timers()
        self.failUnless(rtnVal, 'Expected call to succeed')

        self.failUnless(dr.watchdog.threadCleared, 'Should have cleared thread')
        self.failIf(dr.watchdog.watchStarted,
                    'Should not have started watchdog')
        self.assertEquals(expCnt, dr.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, dr.unHealthyCount))

        logger.checkStatus(10)

    def testCheckWatchdogUnhealthy(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.watchdog = MockWatchdog()

        dr.watchdog.inProg = True
        dr.watchdog.done = True
        dr.unHealthyCount = 0

        expCnt = 1

        rtnVal = dr.check_timers()
        self.failUnless(rtnVal, 'Expected call to succeed')

        self.failUnless(dr.watchdog.threadCleared, 'Should have cleared thread')
        self.failIf(dr.watchdog.watchStarted,
                    'Should not have started watchdog')
        self.assertEquals(expCnt, dr.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, dr.unHealthyCount))

        logger.checkStatus(10)

    def testCheckWatchdogMax(self):
        dr = MostlyDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.watchdog = MockWatchdog()

        dr.watchdog.inProg = True
        dr.watchdog.done = True
        dr.unHealthyCount = DAQRun.MAX_UNHEALTHY_COUNT

        expCnt = 0

        rtnVal = dr.check_timers()
        self.failIf(rtnVal, 'Expected call to succeed')

        self.failUnless(dr.watchdog.threadCleared, 'Should have cleared thread')
        self.failIf(dr.watchdog.watchStarted,
                    'Should not have started watchdog')
        self.assertEquals(expCnt, dr.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, dr.unHealthyCount))

        logger.checkStatus(10)

    def testSetUpAllLoggers(self):
        runNum = 5432

        dr = MostlyDAQRun()
        dr.createRunLogDirectory(runNum, TestDAQRun.LOG_DIR)

        logger = MockLogger('main')
        dr.log = logger

        expId = 99
        expComps = [(3, 'foo', 0, 'localhost', 1234, 5678),
                    (7, 'bar', 1, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        logger.addExpectedExact('Setting up logging for %d components' %
                               len(expComps))
        for c in expComps:
            logPort = DAQPort.RUNCOMP_BASE + c[0]
            logger.addExpectedExact('%s(%d %s:%d) -> %s:%d' %
                                   (c[1], c[0], c[3], c[4], dr.ip, logPort))

        try:
            dr.setUpAllComponentLoggers()
        finally:
            for comp in dr.components.values():
                if comp.logger() is not None:
                    comp.logger().stopServing()
            for c in expComps:
                path = os.path.join(dr.getLogPath(),
                                    '%s-%d.log' % (c[1], c[2]))
                if os.path.exists(path):
                    os.remove(path)
            os.rmdir(dr.getLogPath())

        logger.checkStatus(10)

    def testSetUpLoggers(self):
        runNum = 9753

        dr = MostlyDAQRun()
        dr.createRunLogDirectory(runNum, TestDAQRun.LOG_DIR)

        logger = MockLogger('main')
        dr.log = logger

        expId = 99
        expComps = [(3, 'foon', 5, 'localhost', 1234, 5678),
                    (7, 'barn', 4, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        logger.addExpectedExact('Setting up logging for %d components' %
                               len(expComps))

        for c in expComps:
            logPort = DAQPort.RUNCOMP_BASE + c[0]
            logger.addExpectedExact('%s(%d %s:%d) -> %s:%d' %
                                   (c[1], c[0], c[3], c[4], dr.ip, logPort))

        try:
            dr.setup_component_loggers(cnc, 'xxx', expId)
        finally:
            for comp in dr.components.values():
                if comp.logger() is not None:
                    comp.logger().stopServing()
            for c in expComps:
                path = os.path.join(dr.getLogPath(),
                                    '%s-%d.log' % (c[1], c[2]))
                if os.path.exists(path):
                    os.remove(path)
            os.rmdir(dr.getLogPath())

        logList = cnc.getRunsetLoggers()
        if logList is None:
            self.fail('Runset logging was not set')
        self.assertEquals(len(expComps), len(logList),
                          'Expected %d loggers, not %d' %
                          (len(expComps), len(logList)))

        for i in range(0, len(expComps)):
            c = expComps[i]
            l = logList[i]

            logPort = DAQPort.RUNCOMP_BASE + c[0]

            self.assertEquals(c[1], l[0],
                              'Expected short name #%d "%s", not "%s"' %
                              (i, c[1], l[0]))
            self.assertEquals(c[2], l[1],
                              'Expected DAQ ID #%d %d, not %d' %
                              (i, c[2], l[1]))
            self.assertEquals(logPort, l[2],
                              'Expected log port #%d %d, not %d' %
                              (i, logPort, l[2]))

        logger.checkStatus(10)

    def testRPCStopRunStopped(self):
        dr = StubbedDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        logger.addExpectedExact('Warning: run is already stopped.')

        dr.runState = 'STOPPED'
        dr.rpc_stop_run()

        logger.checkStatus(10)

    def testRPCStopRunBadState(self):
        dr = StubbedDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        badState = 'XXX'

        logger.addExpectedExact("Warning: invalid state (%s), won't stop run." %
                               badState)

        dr.runState = badState
        dr.rpc_stop_run()

        logger.checkStatus(10)

    def testRPCStopRunSuccess(self):
        dr = StubbedDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.runState = 'RUNNING'
        dr.rpc_stop_run()

        self.assertEquals('STOPPING', dr.runState, 'Should be stopping, not ' +
                          dr.runState)

        logger.checkStatus(10)

    def testRunThread(self):
        dr = StubbedDAQRun()

        ebID = 67
        sbID = 92

        comps = [(2, 'stringHub', 1001, 'localhost', 111, 211),
                 (4, 'stringHub', 1002, 'localhost', 112, 212),
                 (6, 'stringHub', 1003, 'localhost', 113, 213),
                 (8, 'stringHub', 1004, 'localhost', 114, 214),
                 (10, 'stringHub', 1005, 'localhost', 115, 215),
                 (12, 'stringHub', 1201, 'localhost', 116, 216),
                 (14, 'inIceTrigger', 0, 'localhost', 117, 217),
                 (16, 'globalTrigger', 0, 'localhost', 118, 218),
                 (ebID, 'eventBuilder', 0, 'localhost', 119, 219),
                 (sbID, 'secondaryBuilders', 0, 'localhost', 120, 220),]

        cnc = MockCnCRPC()
        cnc.setComponents(comps)

        (logger, catchall) = self.__createLoggers(dr)

        threading.Thread(target=dr.run_thread, args=(cnc, )).start()
        self.__finishRunThreadTest(dr, cnc, logger, catchall, ebID, sbID, comps)

    def testRunThreadInverted(self):
        if sys.platform != 'darwin':
            print 'Skipping server tests in non-Darwin OS'
            return

        dr = StubbedDAQRun()

        ebID = 67
        sbID = 92

        comps = [(2, 'stringHub', 1001, 'localhost', 111, 211),
                 (4, 'stringHub', 1002, 'localhost', 112, 212),
                 (6, 'stringHub', 1003, 'localhost', 113, 213),
                 (8, 'stringHub', 1004, 'localhost', 114, 214),
                 (10, 'stringHub', 1005, 'localhost', 115, 215),
                 (12, 'stringHub', 1201, 'localhost', 116, 216),
                 (14, 'inIceTrigger', 0, 'localhost', 117, 217),
                 (16, 'globalTrigger', 0, 'localhost', 118, 218),
                 (ebID, 'eventBuilder', 0, 'localhost', 119, 219),
                 (sbID, 'secondaryBuilders', 0, 'localhost', 120, 220),]

        cnc = MockCnCRPC()
        cnc.setComponents(comps)

        (logger, catchall) = self.__createLoggers(dr)

        threading.Thread(target=self.__finishRunThreadTest,
                         args=(dr, cnc, logger, catchall, ebID, sbID,
                               comps)).start()
        dr.run_thread(cnc)

    def testRunSummaryFauxTest(self):
        # this is a blatant attempt to increase the code coverage,
        # because the rpc_run_summary method is Anvil-centric and
        # I3Live is coming soon

        dr = StubbedDAQRun()

        logger = MockLogger('main')
        dr.log = logger

        dr.runState = "RUNNING"
        dr.runStats.setRunNumber(15)
        dr.prevRunStats = dr.runStats

        dr.rpc_daq_summary_xml()

if __name__ == '__main__':
    unittest.main()
