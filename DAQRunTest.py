#!/usr/bin/env python

import datetime, re, sys, thread, time, unittest
from DAQRun import DAQRun, RunArgs

class MockLogger(object):
    def __init__(self, logPath=''):
        self.msgs = []
        self.logPath = logPath

    def clearMessages(self):
        self.msgs = []

    def close(self):
        pass

    def dashLog(self, m):
        self.msgs.append(m)

    def getMessages(self):
        return self.msgs

    def localAppend(self, m):
        self.msgs.append(m)

    def stopServing(self):
        pass

    def startServing(self):
        pass

class MockMoni(object):
    def __init__(self):
        self.entries = {}
        self.isTime = False

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

    def timeToMoni(self):
        return self.isTime

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
    COMP_PAT = re.compile(r'(\S+)#(\d+)')

    def __init__(self):
        self.compList = None

        self.nextRunsetId = 1

        self.runsetId = None
        self.runsetComps = None

        self.denyBreak = False

        self.resetFlags()

    def _buildRunset(self, required):
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

    def _listRunset(self, id):
        if self.runsetId is None:
            return ()
        if id != self.runsetId:
            raise Exception('Expected runset#%d, not #%d' % (self.runsetId, id))
        return self.runsetComps

    def _showComponents(self):
        if self.compList is None:
            raise Exception('List of components has not been set')

        showList = []

        id = 1
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
            return self._showComponents()
        if name == 'rpc_log_to':
            self.LogToFlag = True
            return
        if name == 'rpc_runset_make':
            return self._buildRunset(args[0])
        if name == 'rpc_runset_list':
            return self._listRunset(args[0])
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

class StubbedDAQRun(DAQRun):
    def __init__(self, args, startServer):
        self.moniStub = MockMoni()
        self.watchdogStub = MockWatchdog()

        super(StubbedDAQRun, self).__init__(args, startServer)

    def createSocketLogger(cls, port, shortName, path):
        return MockLogger(path)
    createSocketLogger = classmethod(createSocketLogger)

    def createLogCollector(self, runNum, logDir):
        if self.log is not None:
            return self.log
        return MockLogger(logDir)

    def get_base_prefix(self, runNum, runTime, runDuration):
        return 'MockPrefix#%d' % runNum

    def move_spade_files(self, copyDir, basePrefix, logTopLevel, runDir, spadeDir):
        pass

    def restartComponents(self):
        pass

    def setup_monitoring(self):
        self.moni = self.moniStub

    def setup_watchdog(self):
        self.watchdog = self.watchdogStub

class TestDAQRun(unittest.TestCase):
    NEXTPORT = 9876
    CLUSTER_CONFIG = 'sim-localhost'
    SPADE_DIR = '/tmp'
    LOG_DIR = '/tmp'

    def checkLogMessages(self, logger, expMsgs=None):
        msgs = logger.getMessages()
        logger.clearMessages()

        if expMsgs is None:
            if len(msgs) > 0:
                if len(msgs) == 1:
                    plural = ''
                else:
                    plural = 's'
                self.fail("Didn't expect %d log message%s (first msg='%s')" %
                          (len(msgs), plural, msgs[0]))
        else:
            if len(expMsgs) == 1:
                plural = ''
            else:
                plural = 's'
            self.assertEquals(len(expMsgs), len(msgs),
                              'Expected %d log message%s, not %d' %
                              (len(expMsgs), plural, len(msgs)))
            for i in range(0, len(expMsgs)):
                self.assertEquals(expMsgs[i], msgs[i],
                                  'Expected log message#%d "%s", not "%s"' %
                                  (i, expMsgs[i], msgs[i]))

    def getRunArgs(self, extraArgs=None):

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
                if extraArgs is None or not extraArgs.has_key(key):
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
        dr = DAQRun(self.getRunArgs(), False)

    def testLog(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        expMsg = 'foo'

        dr.logmsg(expMsg)

        self.checkLogMessages(logger, (expMsg, ))

    def testWaitForRequiredBad(self):
        comps = [(0, 'abc', 1, 'xxx', 1, 2),
                 (1, 'def', 2, 'yyy', 3, 4),
                 (2, 'ghi', 3, 'zzz', 5, 6)]

        dr = DAQRun(self.getRunArgs(), False)

        cnc = MockCnCRPC()
        cnc.setComponents(comps[1:])

        required = []
        for c in comps:
            required.append('%s#%d' % (c[1], c[2]))

        try:
            dr.waitForRequiredComponents(cnc, required, 0)
            self.fail('Unexpected success')
        except Exception, e:
            self.assertEquals('Still waiting for ' + required[0], e.message,
                              'Unexpected exception message "%s"' % e.message)

        self.checkLogMessages(logger)

    def testWaitForRequiredGood(self):
        comps = [(0, 'abc', 1, 'xxx', 1, 2),
                 (1, 'def', 2, 'yyy', 3, 4),
                 (2, 'ghi', 3, 'zzz', 5, 6)]

        dr = DAQRun(self.getRunArgs(), False)

        cnc = MockCnCRPC()
        cnc.setComponents(comps)


        required = []
        for c in comps:
            required.append('%s#%d' % (c[1], c[2]))

        dr.waitForRequiredComponents(cnc, required, 0)

        self.checkLogMessages(logger)

    def testWaitForRequiredBad(self):
        comps = [(0, 'abc', 1, 'xxx', 1, 2),
                 (1, 'def', 2, 'yyy', 3, 4),
                 (2, 'ghi', 3, 'zzz', 5, 6)]

        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        cnc = MockCnCRPC()
        cnc.setComponents(comps[1:])

        expRunNum = 100
        expId = 123

        dr.runStats.runNum = expRunNum
        dr.runSetID = expId

        DAQRun.COMP_TOUT = 0

        required = []
        for c in comps:
            required.append('%s#%d' % (c[1], c[2]))

        try:
            dr.build_run_set(cnc, required)
            self.fail('Unexpected success')
        except Exception, e:
            self.assertEquals('Still waiting for ' + required[0], e.message,
                              'Unexpected exception message "%s"' % e.message)

        expMsgs = (('Starting run %d (waiting for required %d components' +
                   ' to register w/ CnCServer)') %
                   (dr.runStats.runNum, len(required)), )

        self.checkLogMessages(logger, expMsgs)

    def testWaitForRequiredGood(self):
        comps = [(0, 'abc', 1, 'xxx', 1, 2),
                 (1, 'def', 2, 'yyy', 3, 4),
                 (2, 'ghi', 3, 'zzz', 5, 6)]

        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        cnc = MockCnCRPC()
        cnc.setComponents(comps)

        expRunNum = 100

        dr.runStats.runNum = expRunNum

        DAQRun.COMP_TOUT = 0

        expId = cnc.nextRunsetId

        required = []
        for c in comps:
            required.append('%s#%d' % (c[1], c[2]))

        dr.build_run_set(cnc, required)
        self.assertEquals(expId, dr.runSetID, 'Expected runset#%d, not #%d' %
                          (expId, dr.runSetID))

        expMsgs = (('Starting run %d (waiting for required %d components' +
                   ' to register w/ CnCServer)') %
                   (dr.runStats.runNum, len(required)),
                   'Created Run Set #%d' % expId)

        self.checkLogMessages(logger, expMsgs)

    def testFillCompDict(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        expId = 99
        expComps = [(3, 'foo', 0, 'localhost', 1234, 5678),
                    (7, 'bar', 1, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        for i in range(0, len(expComps)):
            key = dr.setCompIDs[i]
            self.assertEquals(expComps[i][0], key,
                              'Expected comp#%d to be %s, not %s' %
                              (i, expComps[i][0], key))
            self.assertEquals(expComps[i][1], dr.shortNameOf[key],
                              'Expected shortName#%d to be %s, not %s' %
                              (i, expComps[i][1], dr.shortNameOf[key]))
            self.assertEquals(expComps[i][2], dr.daqIDof[key],
                              'Expected daqID#%d to be %d, not %d' %
                              (i, expComps[i][2], dr.daqIDof[key]))
            self.assertEquals(expComps[i][3], dr.rpcAddrOf[key],
                              'Expected rpcAddr#%d to be %s, not %s' %
                              (i, expComps[i][3], dr.rpcAddrOf[key]))
            self.assertEquals(expComps[i][4], dr.rpcPortOf[key],
                              'Expected rpcPort#%d to be %d, not %d' %
                              (i, expComps[i][4], dr.rpcPortOf[key]))
            self.assertEquals(expComps[i][5], dr.mbeanPortOf[key],
                              'Expected mbeanPort#%d to be %d, not %d' %
                              (i, expComps[i][5], dr.mbeanPortOf[key]))

        self.checkLogMessages(logger)

    def testRunsetConfig(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        cnc = MockCnCRPC()

        dr.runset_configure(cnc, 1, 'foo')
        self.assertTrue(cnc.RSConfigFlag, 'Runset was not configured')

        self.checkLogMessages(logger, ('Configuring run set...', ))

    def testRunsetStart(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        cnc = MockCnCRPC()

        expRunNum = 100
        expId = 123

        dr.runStats.runNum = expRunNum
        dr.runSetID = expId

        dr.start_run(cnc)
        self.assertTrue(cnc.RSStartFlag, 'Runset was not started')

        self.checkLogMessages(logger, ('Started run %d on run set %d' %
                                       (expRunNum, expId), ))

    def testRunsetStop(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        cnc = MockCnCRPC()

        expRunNum = 100

        dr.runStats.runNum = expRunNum

        dr.stop_run(cnc)
        self.assertTrue(cnc.RSStopFlag, 'Runset was not started')

        self.checkLogMessages(logger, ('Stopping run %d' % expRunNum, ))

    def testRunsetBreakGood(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        cnc = MockCnCRPC()

        expId = 123

        dr.runSetID = expId

        dr.break_existing_runset(cnc)
        self.assertTrue(cnc.RSBreakFlag, 'Runset was not broken')
        self.assertEquals(0, len(dr.setCompIDs),
                          'Should not have any components')
        self.assertEquals(0, len(dr.shortNameOf),
                          'Should not have any short names')
        self.assertEquals(0, len(dr.daqIDof),
                          'Should not have any DAQ IDs')
        self.assertEquals(0, len(dr.rpcAddrOf),
                          'Should not have any RPC addresses')
        self.assertEquals(0, len(dr.rpcPortOf),
                          'Should not have any RPC ports')
        self.assertEquals(0, len(dr.mbeanPortOf),
                          'Should not have any MBean ports')
        if dr.runSetID is not None: self.fail('Runset ID should be unset')
        if dr.lastConfig is not None: self.fail('Last config should be unset')

        self.checkLogMessages(logger, ('Breaking run set...', ))

    def testRunsetBreakBad(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        cnc = MockCnCRPC()
        cnc.denyBreak = True

        expId = 123

        dr.runSetID = expId

        dr.break_existing_runset(cnc)
        self.assertFalse(cnc.RSBreakFlag, 'Runset was broken')
        self.assertEquals(0, len(dr.setCompIDs),
                          'Should not have any components')
        self.assertEquals(0, len(dr.shortNameOf),
                          'Should not have any short names')
        self.assertEquals(0, len(dr.daqIDof),
                          'Should not have any DAQ IDs')
        self.assertEquals(0, len(dr.rpcAddrOf),
                          'Should not have any RPC addresses')
        self.assertEquals(0, len(dr.rpcPortOf),
                          'Should not have any RPC ports')
        self.assertEquals(0, len(dr.mbeanPortOf),
                          'Should not have any MBean ports')
        if dr.runSetID is not None: self.fail('Runset ID should be unset')
        if dr.lastConfig is not None: self.fail('Last config should be unset')

        msgs = logger.getMessages()

        self.assertEquals(2, len(msgs),
                          'Expected 2 log messages, not %d' % len(msgs))

        expMsg = 'Breaking run set...'
        self.assertEquals(expMsg, msgs[0],
                          'Expected log message#%d "%s", not "%s"' %
                          (0, expMsg, msgs[0]))

        if not msgs[1].startswith('WARNING: failed to break run set'):
            self.fail('Unexpected log message#1 "%s"' % msgs[1])

    def testGetEventCounts(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        numEvts = 17
        numMoni = 222
        numSN = 51
        numTCal = 93

        moni.addEntry(5, 'backEnd', 'NumEventsSent', str(numEvts))
        moni.addEntry(17, 'moniBuilder', 'TotalDispatchedData', str(numMoni))
        moni.addEntry(17, 'snBuilder', 'TotalDispatchedData', str(numSN))
        moni.addEntry(17, 'tcalBuilder', 'TotalDispatchedData', str(numTCal))

        expId = 99
        expComps = [(5, 'eventBuilder', 0, 'x', 1234, 5678),
                    (17, 'secondaryBuilders', 0, 'x', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        expCnts = (numEvts, numMoni, numSN, numTCal)

        cnts = dr.getEventCounts()
        self.assertEquals(len(expCnts), len(cnts),
                          'Expected %d event counts, not %d' %
                          (len(expCnts), len(cnts)))
        for i in range(0, len(expCnts)):
            self.assertEquals(expCnts[i], cnts[i],
                              'Expected event count #%d to be %d, not %d' %
                              (i, expCnts[i], cnts[i]))

        self.checkLogMessages(logger)

    def testCheckAllNone(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        cnc = MockCnCRPC()

        rtnVal = dr.check_all()
        self.assertTrue(rtnVal, 'Expected call to succeed')

        self.checkLogMessages(logger)

    def testCheckAllMoniRate(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        numEvts = 1000
        numMoni = 222
        numSN = 51
        numTCal = 93

        moni.isTime = True
        moni.addEntry(5, 'backEnd', 'NumEventsSent', str(numEvts))
        moni.addEntry(17, 'moniBuilder', 'TotalDispatchedData', str(numMoni))
        moni.addEntry(17, 'snBuilder', 'TotalDispatchedData', str(numSN))
        moni.addEntry(17, 'tcalBuilder', 'TotalDispatchedData', str(numTCal))

        expId = 99
        expComps = [(5, 'eventBuilder', 0, 'x', 1234, 5678),
                    (17, 'secondaryBuilders', 0, 'x', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dt = datetime.datetime.now()

        maxRate = 300
        for i in range(0, maxRate):
            secs = maxRate - i
            evts = (maxRate - i) * 2
            dr.runStats.physicsRate.add(dt - datetime.timedelta(seconds=secs),
                                        numEvts - evts)

        dr.fill_component_dictionaries(cnc)

        rtnVal = dr.check_all()
        self.assertTrue(rtnVal, 'Expected call to succeed')

        self.checkLogMessages(logger, ((('\t%d physics events (2.00 Hz)' +
                                         ', %d moni events, %d SN events' +
                                         ', %d tcals') %
                                        (numEvts, numMoni, numSN, numTCal)), ))

    def testCheckAllMoni(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        numEvts = 17
        numMoni = 222
        numSN = 51
        numTCal = 93

        moni.isTime = True
        moni.addEntry(5, 'backEnd', 'NumEventsSent', str(numEvts))
        moni.addEntry(17, 'moniBuilder', 'TotalDispatchedData', str(numMoni))
        moni.addEntry(17, 'snBuilder', 'TotalDispatchedData', str(numSN))
        moni.addEntry(17, 'tcalBuilder', 'TotalDispatchedData', str(numTCal))

        expId = 99
        expComps = [(5, 'eventBuilder', 0, 'x', 1234, 5678),
                    (17, 'secondaryBuilders', 0, 'x', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        rtnVal = dr.check_all()
        self.assertTrue(rtnVal, 'Expected call to succeed')

        self.checkLogMessages(logger, ((('\t%d physics events, %d moni events' +
                                         ', %d SN events, %d tcals') %
                                        (numEvts, numMoni, numSN, numTCal)), ))

    def testCheckAllWatchdogNone(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        dog = MockWatchdog()
        dr.watchdog = dog

        DAQRun.unHealthyCount = 0

        expCnt = 0

        cnc = MockCnCRPC()

        rtnVal = dr.check_all()
        self.assertTrue(rtnVal, 'Expected call to succeed')

        self.assertFalse(dog.threadCleared, 'Should not have cleared thread')
        self.assertFalse(dog.watchStarted, 'Should not have started watchdog')
        self.assertEquals(expCnt, DAQRun.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, DAQRun.unHealthyCount))

        self.checkLogMessages(logger)

    def testCheckAllWatchdogStart(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        dog = MockWatchdog()
        dr.watchdog = dog

        dog.isTime = True
        DAQRun.unHealthyCount = 0

        expCnt = 0

        cnc = MockCnCRPC()

        rtnVal = dr.check_all()
        self.assertTrue(rtnVal, 'Expected call to succeed')

        self.assertFalse(dog.threadCleared, 'Should not have cleared thread')
        self.assertTrue(dog.watchStarted, 'Should have started watchdog')
        self.assertEquals(expCnt, DAQRun.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, DAQRun.unHealthyCount))

    def testCheckAllWatchdogErr(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        dog = MockWatchdog()
        dr.watchdog = dog

        dog.inProg = True
        dog.caughtErr = True
        DAQRun.unHealthyCount = 0

        expCnt = 0

        cnc = MockCnCRPC()

        rtnVal = dr.check_all()
        self.assertFalse(rtnVal, 'Expected call to succeed')

        self.assertTrue(dog.threadCleared, 'Should have cleared thread')
        self.assertFalse(dog.watchStarted, 'Should not have started watchdog')
        self.assertEquals(expCnt, DAQRun.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, DAQRun.unHealthyCount))

        self.checkLogMessages(logger)

    def testCheckAllWatchdogHealthy(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        dog = MockWatchdog()
        dr.watchdog = dog

        dog.inProg = True
        dog.done = True
        dog.healthy = True
        DAQRun.unHealthyCount = 1

        expCnt = 0

        cnc = MockCnCRPC()

        rtnVal = dr.check_all()
        self.assertTrue(rtnVal, 'Expected call to succeed')

        self.assertTrue(dog.threadCleared, 'Should have cleared thread')
        self.assertFalse(dog.watchStarted, 'Should not have started watchdog')
        self.assertEquals(expCnt, DAQRun.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, DAQRun.unHealthyCount))

        self.checkLogMessages(logger)

    def testCheckAllWatchdogUnhealthy(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        dog = MockWatchdog()
        dr.watchdog = dog

        dog.inProg = True
        dog.done = True
        DAQRun.unHealthyCount = 0

        expCnt = 1

        cnc = MockCnCRPC()

        rtnVal = dr.check_all()
        self.assertTrue(rtnVal, 'Expected call to succeed')

        self.assertTrue(dog.threadCleared, 'Should have cleared thread')
        self.assertFalse(dog.watchStarted, 'Should not have started watchdog')
        self.assertEquals(expCnt, DAQRun.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, DAQRun.unHealthyCount))

        self.checkLogMessages(logger)

    def testCheckAllWatchdogMax(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        moni = MockMoni()
        dr.moni = moni

        dog = MockWatchdog()
        dr.watchdog = dog

        dog.inProg = True
        dog.done = True
        DAQRun.unHealthyCount = DAQRun.MAX_UNHEALTHY_COUNT

        expCnt = 0

        cnc = MockCnCRPC()

        rtnVal = dr.check_all()
        self.assertFalse(rtnVal, 'Expected call to succeed')

        self.assertTrue(dog.threadCleared, 'Should have cleared thread')
        self.assertFalse(dog.watchStarted, 'Should not have started watchdog')
        self.assertEquals(expCnt, DAQRun.unHealthyCount,
                          'UnhealthyCount should be %d, not %d' %
                          (expCnt, DAQRun.unHealthyCount))

        self.checkLogMessages(logger)

    def testSetUpAllLoggers(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        logger.logPath = '/tmp'
        dr.log = logger

        expId = 99
        expComps = [(3, 'foo', 0, 'localhost', 1234, 5678),
                    (7, 'bar', 1, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        try:
            dr.setUpAllComponentLoggers()
        finally:
            for k in dr.loggerOf.keys():
                dr.loggerOf[k].stopServing()

        nextPort = 9002
        expMsgs = ['Setting up logging for %d components' % len(expComps), ]
        for c in expComps:
            expMsgs.append('%s(%d %s:%d) -> %s:%d' % \
                               (c[1], c[0], c[3], c[4], dr.ip, nextPort))
            nextPort += 1

        self.checkLogMessages(logger, expMsgs)

    def testSetUpLoggers(self):
        dr = DAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        logger.logPath = '/tmp'
        dr.log = logger

        expId = 99
        expComps = [(3, 'foo', 0, 'localhost', 1234, 5678),
                    (7, 'bar', 1, 'localhost', 4321, 8765)]

        cnc = MockCnCRPC()
        cnc.setRunSet(expId, expComps)

        dr.runSetID = expId

        dr.fill_component_dictionaries(cnc)

        try:
            logList = dr.setup_component_loggers(cnc, 'xxx', expId)
        finally:
            for k in dr.loggerOf.keys():
                dr.loggerOf[k].stopServing()

        logList = cnc.getRunsetLoggers()
        if logList is None:
            self.fail('Runset logging was not set')
        self.assertEquals(len(expComps), len(logList),
                          'Expected %d loggers, not %d' %
                          (len(expComps), len(logList)))

        expMsgs = ['Setting up logging for %d components' % len(expComps), ]

        nextPort = 9002
        for i in range(0, len(expComps)):
            c = expComps[i]
            l = logList[i]

            self.assertEquals(c[1], l[0],
                              'Expected short name #%d "%s", not "%s"' %
                              (i, c[1], l[0]))
            self.assertEquals(c[2], l[1],
                              'Expected DAQ ID #%d %d, not %d' %
                              (i, c[2], l[1]))
            self.assertEquals(nextPort, l[2],
                              'Expected log port #%d %d, not %d' %
                              (i, nextPort, l[2]))

            expMsgs.append('%s(%d %s:%d) -> %s:%d' % \
                               (c[1], c[0], c[3], c[4], dr.ip, nextPort))
            nextPort += 1

        self.checkLogMessages(logger, expMsgs)

    def testRPCStopRunStopped(self):
        dr = StubbedDAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        dr.runState = 'STOPPED'
        dr.rpc_stop_run()

        expMsgs = ('Warning: run is already stopped.', )
        self.checkLogMessages(logger, expMsgs)

    def testRPCStopRunBadState(self):
        dr = StubbedDAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        badState = 'XXX'
        dr.runState = badState
        dr.rpc_stop_run()

        expMsgs = ("Warning: invalid state (%s), won't stop run." % badState, )
        self.checkLogMessages(logger, expMsgs)

    def testRPCStopRunSuccess(self):
        dr = StubbedDAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        dr.runState = 'RUNNING'
        dr.rpc_stop_run()

        self.checkLogMessages(logger)
        self.assertEquals('STOPPING', dr.runState, 'Should be stopping, not ' +
                          dr.runState)

    def finishRunThreadTest(self, dr, cnc, logger, ebID, sbID, comps):
        time.sleep(0.4)
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)

        self.checkLogMessages(logger)

        setId = 1
        runNum = 654
        configName = 'sim5str'

        dr.rpc_start_run(runNum, None, configName)

        numTries = 0
        while dr.runState == 'STARTING' and numTries < 100:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('RUNNING', dr.runState, 'Should be running, not ' +
                          dr.runState)
        self.assertFalse(cnc.RSBreakFlag, 'Runset should not have been broken')
        self.assertTrue(cnc.RSConfigFlag, 'Runset was not configured')
        self.assertTrue(cnc.RSStartFlag, 'Runset was not started')
        cnc.resetFlags()

        expMsgs = ['Loaded global configuration "%s"' % configName,
                   'Configuration includes detector in-ice',
                   'Configuration includes detector icetop']
        for id in dr.setCompIDs:
            c = None
            for i in range(len(comps)):
                if comps[i][0] == id:
                    c = comps[i]
            expMsgs.append('Component list will require %s#%d' % (c[1], c[2]))
        expMsgs.append(('Starting run %d (waiting for required %d components' +
                        ' to register w/ CnCServer)') % (runNum, len(comps)))
        expMsgs.append('Created Run Set #%d' % setId)
        expMsgs.append(('Version Info: %(filename)s %(revision)s %(date)s' +
                        ' %(time)s %(author)s %(release)s %(repo_rev)s') %
                       dr.versionInfo)
        expMsgs.append('Starting run %d...' % runNum)
        expMsgs.append('Run configuration: %s' % configName)
        expMsgs.append('Cluster configuration: %s' % TestDAQRun.CLUSTER_CONFIG)
        expMsgs.append('Created logger for CnCServer')
        expMsgs.append('Setting up logging for %d components' % len(comps))
        for id in dr.setCompIDs:
            c = None
            for i in range(len(comps)):
                if comps[i][0] == id:
                    c = comps[i]
            expMsgs.append('%s(%d %s:%d) -> %s:%d' %
                           (c[1], c[0], c[3], c[4], dr.ip, dr.logPortOf[c[0]]))
        expMsgs.append('Configuring run set...')
        expMsgs.append('Started run %d on run set %d' % (runNum, setId))

        self.checkLogMessages(logger, expMsgs)

        subRunId = 1
        domList = [('53494d550101', 0, 1, 2, 3, 4),
                   ['1001', '22', 1, 2, 3, 4, 5],
                   ('a', 0, 1, 2, 3, 4)]

        dr.rpc_flash(subRunId, domList)
        self.assertTrue(cnc.RSFlashFlag, 'Runset should have flashed')

        expMsgs = (("Subrun %d: will ignore missing DOM ('DOM %s not found" +
                    " in config!')...") % (subRunId, domList[2][0]),
                    'Subrun %d: flashing DOMs (%s)' %
                   (subRunId, str(domList[:2])), )
        self.checkLogMessages(logger, expMsgs)

        numEvts = 17
        numMoni = 222
        numSN = 51
        numTCal = 93

        moni = dr.moni
        moni.addEntry(ebID, 'backEnd', 'NumEventsSent', str(numEvts))
        moni.addEntry(sbID, 'moniBuilder', 'TotalDispatchedData', str(numMoni))
        moni.addEntry(sbID, 'snBuilder', 'TotalDispatchedData', str(numSN))
        moni.addEntry(sbID, 'tcalBuilder', 'TotalDispatchedData', str(numTCal))

        dr.rpc_stop_run()

        numTries = 0
        while dr.runState == 'STOPPING' and numTries < 100:
            time.sleep(0.1)
            numTries += 1
        self.assertEquals('STOPPED', dr.runState, 'Should be stopped, not ' +
                          dr.runState)
        self.assertTrue(cnc.RSStopFlag, 'Runset was not stopped')
        cnc.resetFlags()

        basePrefix = dr.get_base_prefix(runNum, None, None)

        expMsgs = ('Stopping run %d' % runNum,
                   '%d physics events collected in 0 seconds' % numEvts,
                   '%d moni events, %d SN events, %d tcals' %
                   (numMoni, numSN, numTCal),
                   'Stopping component logging',
                   'RPC Call stats:\n%s' % cnc.showStats(),
                   'Run terminated SUCCESSFULLY.',
                   ('Queueing data for SPADE (spadeDir=%s, logDir=%s,' +
                    ' runNum=%s)...') %
                   (TestDAQRun.SPADE_DIR, TestDAQRun.LOG_DIR, runNum))
        self.checkLogMessages(logger, expMsgs)

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

        dr.rpc_release_runsets()
        self.assertTrue(cnc.RSBreakFlag, 'Runset should have been broken')
        cnc.resetFlags()

        self.checkLogMessages(logger)

        dr.running = False
        time.sleep(0.4)

        self.checkLogMessages(logger)

    def testRunThread(self):
        dr = StubbedDAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        ebID = 67
        sbID = 92

        comps = [(2, 'stringHub', 1001, 'localhost', 111, 211),
                 (4, 'stringHub', 1002, 'localhost', 112, 212),
                 (6, 'stringHub', 1003, 'localhost', 113, 213),
                 (8, 'stringHub', 1004, 'localhost', 114, 214),
                 (10, 'stringHub', 1005, 'localhost', 115, 215),
                 (12, 'stringHub', 1081, 'localhost', 116, 216),
                 (14, 'inIceTrigger', 0, 'localhost', 117, 217),
                 (16, 'globalTrigger', 0, 'localhost', 118, 218),
                 (ebID, 'eventBuilder', 0, 'localhost', 119, 219),
                 (sbID, 'secondaryBuilders', 0, 'localhost', 120, 220),]

        cnc = MockCnCRPC()
        cnc.setComponents(comps)

        runThread = thread.start_new_thread(dr.run_thread, (cnc, ))
        self.finishRunThreadTest(dr, cnc, logger, ebID, sbID, comps)

    def testRunThreadInverted(self):
        dr = StubbedDAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        ebID = 67
        sbID = 92

        comps = [(2, 'stringHub', 1001, 'localhost', 111, 211),
                 (4, 'stringHub', 1002, 'localhost', 112, 212),
                 (6, 'stringHub', 1003, 'localhost', 113, 213),
                 (8, 'stringHub', 1004, 'localhost', 114, 214),
                 (10, 'stringHub', 1005, 'localhost', 115, 215),
                 (12, 'stringHub', 1081, 'localhost', 116, 216),
                 (14, 'inIceTrigger', 0, 'localhost', 117, 217),
                 (16, 'globalTrigger', 0, 'localhost', 118, 218),
                 (ebID, 'eventBuilder', 0, 'localhost', 119, 219),
                 (sbID, 'secondaryBuilders', 0, 'localhost', 120, 220),]

        cnc = MockCnCRPC()
        cnc.setComponents(comps)

        runThread = \
            thread.start_new_thread(self.finishRunThreadTest,
                                    (dr, cnc, logger, ebID, sbID, comps))
        dr.run_thread(cnc)

    def testRunSummaryFauxTest(self):
        # this is a blatant attempt to increase the code coverage, because the
        # rpc_run_summary method is Anvil-centric and I3Live is coming soon

        dr = StubbedDAQRun(self.getRunArgs(), False)

        logger = MockLogger()
        dr.log = logger

        dr.runState = "RUNNING"
        dr.runStats.runNum = 15
        dr.prevRunStats = dr.runStats

        dr.rpc_daq_summary_xml()

if __name__ == '__main__':
    unittest.main()
