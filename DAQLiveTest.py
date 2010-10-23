#!/usr/bin/env python

import sys, traceback, unittest

from DAQLive import DAQLive, LiveException
from DAQMocks import MockLogger

class MockRunSet(object):
    STATE_UNKNOWN = "unknown"
    STATE_DESTROYED = "destroyed"
    STATE_READY = "ready"
    STATE_RUNNING = "running"

    def __init__(self, runCfg):
        self.__state = self.STATE_UNKNOWN
        self.__runCfg = runCfg
        self.__expStopErr = False
        self.__stopReturn = False

    def __str__(self):
        return "MockRunSet"

    def destroy(self):
        self.__state = self.STATE_DESTROYED

    def isDestroyed(self):
        return self.__state == self.STATE_DESTROYED

    def isReady(self):
        return self.__state == self.STATE_READY

    def isRunning(self):
        return self.__state == self.STATE_RUNNING
        
    def runConfig(self):
        if self.isDestroyed(): raise Exception("Runset destroyed")
        return self.__runCfg

    def sendEventCounts(self):
        if self.isDestroyed(): raise Exception("Runset destroyed")

    def setExpectedStopError(self):
        self.__expStopErr = True

    def setState(self, newState):
        self.__state = newState

    def setStopReturnError(self):
        if self.isDestroyed(): raise Exception("Runset destroyed")
        self.__stopReturn = True

    def state(self):
        return self.__state

    def stopRun(self, hadError=False):
        if self.isDestroyed(): raise Exception("Runset destroyed")
        if hadError != self.__expStopErr:
            raise Exception("Expected 'hadError' to be %s" % self.__expStopErr)
        return self.__stopReturn

    def subrun(self, id, domList):
        pass

class MockCnC(object):
    RELEASE = "rel"
    REPO_REV = "repoRev"

    def __init__(self):
        self.__expRunCfg = None
        self.__expRunNum = None
        self.__expStopErr = False
        self.__runSet = None

    def breakRunset(self, rs):
        rs.destroy()

    def makeRunsetFromRunConfig(self, runCfg):
        if self.__expRunCfg is None:
            raise Exception("Expected run configuration has not been set")
        if self.__expRunCfg != runCfg:
            raise Exception("Expected run config \"%s\", not \"%s\"",
                            self.__expRunCfg, runCfg)

        return self.__runSet

    def setExpectedRunConfig(self, runCfg):
        self.__expRunCfg = runCfg

    def setExpectedRunNumber(self, runNum):
        self.__expRunNum = runNum

    def setRunSet(self, runSet):
        self.__runSet = runSet

    def startRun(self, rs, runNum, runOpts):
        if self.__expRunCfg is None:
            raise Exception("Expected run configuration has not been set")
        if self.__expRunCfg != rs.runConfig():
            raise Exception("Expected run config \"%s\", not \"%s\"",
                            self.__expRunCfg, rs.runConfig())

        if self.__expRunNum is None:
            raise Exception("Expected run number has not been set")
        if self.__expRunNum != runNum:
            raise Exception("Expected run Number %s, not %s",
                            self.__expRunNum, runNum)

    def versionInfo(self):
        return { "release": self.RELEASE, "repo_rev": self.REPO_REV }

class DAQLiveTest(unittest.TestCase):
    def __createLive(self, cnc, log):
        self.__live = DAQLive(cnc, log)
        return self.__live

    def assertRaisesMsg(self, exc, func, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except type(exc), ex2:
            if str(exc) == str(ex2):
                return
            raise self.failureException("Expected %s(%s), not %s(%s)" %
                                        (type(exc), exc, type(ex2), ex2))
        except:
            # handle exceptions in python 2.3
            (excType, excVal, excTB) = sys.exc_info()
            if type(excVal) == type(exc) and str(excVal) == str(exc):
                return
            raise self.failureException("Expected %s(%s), not %s(%s)" %
                                        (type(exc), exc, type(excVal), excVal))
        raise self.failureException("%s(%s) not raised" % type(exc), exc)

    def setUp(self):
        self.__live = None

    def tearDown(self):
        if self.__live is not None:
            try:
                self.__live.close()
            except:
                import traceback
                traceback.print_exc()

    def testVersion(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        self.assertEqual(live.version(),
                         MockCnC.RELEASE + "_" + MockCnC.REPO_REV)

        log.checkStatus(1)

    def testStartingNoStateArgs(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, None)

    def testStartingNoKeys(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = { }

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, state)

    def testStartingNoRunCfgKey(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = { "runNumber": runNum, }

        exc = LiveException("stateArgs does not contain key \"runConfig\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunNumKey(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = { "runConfig": runCfg, }

        exc = LiveException("stateArgs does not contain key \"runNumber\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunSet(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.assertRaisesMsg(LiveException("Cannot create runset for \"%s\"" %
                                           runCfg), live.starting, state)

    def testStarting(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(MockRunSet(runCfg))

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

    def testStoppingNoRunset(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        exc = LiveException("Cannot stop run; no active runset")
        self.assertRaisesMsg(exc, live.stopping)

    def testStoppingError(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

        runSet.setStopReturnError()

        exc = LiveException("Encountered ERROR while stopping run")
        self.assertRaisesMsg(exc, live.stopping)

    def testStopping(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(MockRunSet(runCfg))

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

        self.failUnless(live.stopping(), "stopping failed")

    def testRecoveringNothing(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        self.failUnless(live.recovering(), "recovering failed")

    def testRecoveringDestroyed(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

        runSet.setExpectedStopError()
        runSet.destroy()

        self.failUnless(live.recovering(), "recovering failed")

    def testRecovering(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

        runSet.setExpectedStopError()

        log.addExpectedExact("DAQLive recovered %s" % runSet)
        self.failUnless(live.recovering(), "recovering failed")

    def testRunningNothing(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        exc = LiveException("Cannot check run state; no active runset")
        self.assertRaisesMsg(exc, live.running)

    def testRunningBadState(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

        exc = LiveException("%s is not running (state = %s)" %
                            (runSet, runSet.state()))
        self.assertRaisesMsg(exc, live.running)

    def testRunning(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

        runSet.setState(runSet.STATE_RUNNING)

        self.failUnless(live.running(), "running failed")

    def testSubrun(self):
        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = { "runConfig": runCfg, "runNumber": runNum }

        self.failUnless(live.starting(state), "starting failed")

        self.assertEquals("OK", live.subrun(1, ["domA", "dom2", ]))

if __name__ == '__main__':
    unittest.main()
