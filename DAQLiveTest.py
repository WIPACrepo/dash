#!/usr/bin/env python

from __future__ import print_function

import sys
import time
import traceback
import unittest

from CnCExceptions import MissingComponentException
from DAQLive import DAQLive, INCOMPLETE_STATE_CHANGE, LIVE_IMPORT, \
    LiveException
from DAQMocks import MockLogger


WARNED = False


class MockRunSet(object):
    STATE_UNKNOWN = "unknown"
    STATE_DESTROYED = "destroyed"
    STATE_IDLE = "idle"
    STATE_READY = "ready"
    STATE_RUNNING = "running"

    NORMAL_STOP = "normal_stop"

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
    def isIdle(self):
        return self.__state == self.STATE_IDLE

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

    def stop_run(self, caller_name, had_error=False):
        if self.isDestroyed:
            raise Exception("Runset destroyed")

        if had_error != self.__expStopErr:
            raise Exception("Expected 'had_error' to be %s" %
                            (self.__expStopErr, ))

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
        self.__missingComps = None
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
        if self.__missingComps is not None:
            tmpList = self.__missingComps
            self.__missingComps = None
            raise MissingComponentException(tmpList)

        if self.__runSet is not None:
            self.__runSet.setState(MockRunSet.STATE_RUNNING)

        return self.__runSet

    def setExpectedRunConfig(self, runCfg):
        self.__expRunCfg = runCfg

    def setExpectedRunNumber(self, runNum):
        self.__expRunNum = runNum

    def setRunSet(self, runSet):
        self.__runSet = runSet

    def setMissingComponents(self, compList):
        self.__missingComps = compList

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

    def __waitForStart(self, live, state, expectedException=None):
        if expectedException is None:
            extra = ""
        else:
            extra = " <%s>%s" % (type(expectedException).__name__,
                                 expectedException)
        for idx in range(10):
            try:
                val = live.starting(state)
            except LiveException as lex:
                if expectedException is None or \
                   str(expectedException) != str(lex):
                    raise
                expectedException = None
                break

            if val != INCOMPLETE_STATE_CHANGE:
                self.assertTrue(val, "starting failed")
                break

            time.sleep(0.1)

        if expectedException is not None:
            raise Exception("Did not received expected %s: %s" %
                            (type(expectedException).__name__,
                             expectedException))

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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {"runConfig": runCfg, "runNumber": runNum}

        errmsg = "Cannot create run #%d runset for \"%s\"" % (runNum, runCfg)
        log.addExpectedExact(errmsg)

        self.__waitForStart(live, state, LiveException(errmsg))

    def testStarting(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

    def testStartingTwice(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

        print("RS %s ST %s" % (runSet, runSet.state))
        state2 = {"runConfig": runCfg, "runNumber": runNum + 1}
        self.__waitForStart(live, state)

    def testStartingMissingComp(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        runSet = MockRunSet(runCfg)
        runSet.setState(MockRunSet.STATE_RUNNING)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        missing = ["hub", "bldr"]
        cnc.setMissingComponents(missing)

        state = {"runConfig": runCfg, "runNumber": runNum}

        errmsg = "Cannot create run #%d runset for \"%s\": Still waiting" \
                 " for %s" % (runNum, runCfg, missing)
        log.addExpectedExact(errmsg)

        self.__waitForStart(live, state, LiveException(errmsg))

    def testStoppingNoRunset(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        runSet = MockRunSet(runCfg)
        runSet.setState(MockRunSet.STATE_RUNNING)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.__waitForStart(live, state)

        runSet.setStopReturnError()


        finished = False
        for _ in range(10):
            try:
                val = live.stopping()
            except LiveException as lex:
                exp_err = "Encountered ERROR while stopping run"
                self.assertEqual(str(lex), exp_err,
                                 "Expected \"%s\", not \"%s\"" %
                                 (exp_err, lex))
                finished = None
                break

            if val == INCOMPLETE_STATE_CHANGE:
                time.sleep(0.1)
                continue

            finished = True

        self.assertTrue(finished is None, "Unexpected value for 'finished'")

    def testStopping(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
            return

        cnc = MockCnC()
        log = MockLogger("liveLog")
        live = self.__createLive(cnc, log)

        runCfg = "foo"
        runNum = 13579

        runSet = MockRunSet(runCfg)
        runSet.setState(MockRunSet.STATE_RUNNING)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        self.__waitForStart(live, state)

        self.assertTrue(live.stopping(), "stopping failed")

    def testRecoveringNothing(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

        runSet.setExpectedStopError()
        runSet.destroy()

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecoveringStopFail(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

        self.assertTrue(live.running(), "RunSet \"%s\" is %s, not running" %
                        (runSet, "???" if runSet is None else runSet.state))

    def testRunning(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

        runSet.setState(runSet.STATE_RUNNING)

        self.assertTrue(live.running(), "running failed")

    def testSubrun(self):
        global WARNED
        if not LIVE_IMPORT:
            if not WARNED:
                WARNED = True
                print("No I3Live Python code found, cannot run tests",
                      file=sys.stderr)
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

        self.__waitForStart(live, state)

        self.assertEqual("OK", live.subrun(1, ["domA", "dom2", ]))


if __name__ == '__main__':
    unittest.main()
