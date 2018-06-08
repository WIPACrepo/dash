#!/usr/bin/env python

from __future__ import print_function

import sys
import traceback
import unittest

from DAQLive import DAQLive, LIVE_IMPORT, LiveException
from DAQMocks import MockLogger


WARNED = False


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

    @property
    def isDestroyed(self):
        return self.__state == self.STATE_DESTROYED

    @property
    def isReady(self):
        return self.__state == self.STATE_READY

    @property
    def isRunning(self):
        return self.__state == self.STATE_RUNNING

    def runConfig(self):
        if self.isDestroyed:
            raise Exception("Runset destroyed")

        return self.__runCfg

    def sendEventCounts(self):
        if self.isDestroyed:
            raise Exception("Runset destroyed")

    def setExpectedStopError(self):
        self.__expStopErr = True

    def setState(self, newState):
        self.__state = newState

    def setStopReturnError(self):
        if self.isDestroyed:
            raise Exception("Runset destroyed")

        self.__stopReturn = True

    @property
    def state(self):
        return self.__state

    def stop_run(self, hadError=False):
        if self.isDestroyed:
            raise Exception("Runset destroyed")

        if hadError != self.__expStopErr:
            raise Exception("Expected 'hadError' to be %s" % self.__expStopErr)

        self.__state = self.STATE_READY
        return self.__stopReturn

    def stopping(self):
        return False

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

    def makeRunsetFromRunConfig(self, runCfg, runNum):
        if self.__expRunCfg is None:
            raise Exception("Expected run configuration has not been set")
        if self.__expRunCfg != runCfg:
            raise Exception("Expected run config \"%s\", not \"%s\"",
                            self.__expRunCfg, runCfg)
        if self.__expRunNum != runNum:
            raise Exception("Expected run number %s, not %s",
                            self.__expRunNum, runNum)

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
        return {"release": self.RELEASE, "repo_rev": self.REPO_REV}


class DAQLiveTest(unittest.TestCase):
    def __createLive(self, cnc, log):
        self.__live = DAQLive(cnc, log)
        return self.__live

    def assertRaisesMsg(self, exc, func, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except type(exc) as ex2:
            if exc is None:
                return
            if str(exc) == str(ex2):
                return
            raise self.failureException("Expected %s(%s), not %s(%s)" %
                                        (type(exc), exc, type(ex2), ex2))
        except:
            # handle exceptions in python 2.3
            if exc is None:
                return
            (excType, excVal, excTB) = sys.exc_info()
            if isinstance(excVal, type(exc)) and str(excVal) == str(exc):
                return
            raise self.failureException("Expected %s(%s), not %s(%s)" %
                                        (type(exc), exc, type(excVal), excVal))
        raise self.failureException("%s(%s) not raised" % (type(exc), exc))

    def setUp(self):
        self.__live = None

    def tearDown(self):
        if self.__live is not None:
            try:
                self.__live.close()
            except:
                traceback.print_exc()

    def testVersion(self):
        if not LIVE_IMPORT:
            global WARNED
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        self.assertEqual(live.version(),
                         MockCnC.RELEASE + "_" + MockCnC.REPO_REV)

        log.checkStatus(1)

    def testStartingNoStateArgs(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, None)

    def testStartingNoKeys(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {}

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, state)

    def testStartingNoRunCfgKey(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {"runNumber": runNum}

        exc = LiveException("stateArgs does not contain key \"runConfig\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunNumKey(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {"runConfig": runCfg}

        exc = LiveException("stateArgs does not contain key \"runNumber\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunSet(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertRaisesMsg(LiveException("Cannot create runset for \"%s\"" %
                                           runCfg), live.starting, state)

    def testStarting(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(MockRunSet(runCfg))

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

    def testStoppingNoRunset(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        exc = LiveException("Cannot stop run; no active runset")
        self.assertRaisesMsg(exc, live.stopping)

    def testStoppingError(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        runSet.setStopReturnError()

        exc = LiveException("Encountered ERROR while stopping run")
        self.assertRaisesMsg(exc, live.stopping)

    def testStopping(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(MockRunSet(runCfg))

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        self.assertTrue(live.stopping(), "stopping failed")

    def testRecoveringNothing(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecoveringDestroyed(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        runSet.setExpectedStopError()
        runSet.destroy()

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecoveringStopFail(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        runSet.setExpectedStopError()
        runSet.setStopReturnError()

        log.addExpectedExact("DAQLive stop_run %s returned %s" %
                             (runSet, False))
        log.addExpectedExact("DAQLive recovered %s" % runSet)
        self.assertTrue(live.recovering(), "recovering failed")

    def testRecovering(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        runSet.setExpectedStopError()

        log.addExpectedExact("DAQLive stop_run %s returned %s" %
                             (runSet, True))
        log.addExpectedExact("DAQLive recovered %s" % runSet)
        self.assertTrue(live.recovering(), "recovering failed")

    def testRunningNothing(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        exc = LiveException("Cannot check run state; no active runset")
        self.assertRaisesMsg(exc, live.running)

    def testRunningBadState(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        exc = LiveException("%s is not running (state = %s)" %
                            (runSet, runSet.state))
        self.assertRaisesMsg(exc, live.running)

    def testRunning(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        runSet.setState(runSet.STATE_RUNNING)

        self.assertTrue(live.running(), "running failed")

    def testSubrun(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests", file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.assertTrue(live.starting(state), "starting failed")

        self.assertEqual("OK", live.subrun(1, ["domA", "dom2", ]))


if __name__ == '__main__':
    unittest.main()
