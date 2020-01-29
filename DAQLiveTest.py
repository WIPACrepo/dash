#!/usr/bin/env python

from __future__ import print_function

import sys
import time
import traceback
import unittest

from CnCExceptions import MissingComponentException
from DAQLive import DAQLive, INCOMPLETE_STATE_CHANGE, LIVE_IMPORT, \
    LiveException, StartThread, StopThread
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

    def switch_run(self, stateArgs):
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

    def isStarting(self):
        return False

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

    def start_run(self, rs, runNum, runOpts):
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

    def stopCollecting(self):
        pass

    def versionInfo(self):
        return {"release": self.RELEASE, "repo_rev": self.REPO_REV}


class DAQLiveTest(unittest.TestCase):
    def __createLive(self, cnc, log):
        self.__live = DAQLive(cnc, log, timeout=1)
        return self.__live

    @property
    def __imported_live(self):
        global WARNED

        if LIVE_IMPORT:
            return True

        if not WARNED:
            WARNED = True
            print("No I3Live Python code found, cannot run tests",
                  file=sys.stderr)

        return False

    def __waitForComplete(self, func, *args, **kwargs):
        if "expectedException" not in kwargs:
            expectedException = None
        else:
            expectedException = kwargs["expectedException"]

        for _ in range(10):
            try:
                val = func(*args)
            except LiveException as lex:
                if expectedException is None or \
                   str(expectedException) != str(lex):
                    raise
                expectedException = None
                break

            if val != INCOMPLETE_STATE_CHANGE:
                return val

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
        self.__log = MockLogger("liveLog")

    def tearDown(self):
        if self.__live is not None:
            try:
                self.__live.close()
            except:
                traceback.print_exc()

        self.__log.checkStatus(0)

    def testVersion(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        self.assertEqual(live.version(),
                         MockCnC.RELEASE + "_" + MockCnC.REPO_REV)

    def testStartingNoStateArgs(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, None)

    def testStartingNoKeys(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {}

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, state)

    def testStartingNoRunCfgKey(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {"runNumber": runNum}

        exc = LiveException("stateArgs does not contain key \"runConfig\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunNumKey(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {"runConfig": runCfg}

        exc = LiveException("stateArgs does not contain key \"runNumber\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunSet(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)

        state = {"runConfig": runCfg, "runNumber": runNum}

        errmsg = "Cannot create run #%d runset for \"%s\"" % (runNum, runCfg)

        self.__log.addExpectedExact(StartThread.NAME + ": " + errmsg)

        rtnval = self.__waitForComplete(live.starting, state,
                                        expectedException=LiveException(errmsg))
        self.assertFalse(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStarting(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(MockRunSet(runCfg))

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStartingTwice(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        state2 = {"runConfig": runCfg, "runNumber": runNum + 1}
        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStartingMissingComp(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

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

        errmsg = "%s: Cannot create run #%d runset for \"%s\": Still waiting" \
                 " for %s" % (StartThread.NAME, runNum, runCfg, missing)
        self.__log.addExpectedExact(errmsg)

        rtnval = self.__waitForComplete(live.starting, state,
                                        expectedException=LiveException(errmsg))
        self.assertFalse(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStoppingNoRunset(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        finished = False
        for idx in range(10):
            val = live.stopping()
            if val == INCOMPLETE_STATE_CHANGE:
                time.sleep(0.1)
                continue

            finished = True

        self.assertTrue(finished, "Unexpected value %s for 'finished'" %
                        str(finished))

    def testStoppingError(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579

        runSet = MockRunSet(runCfg)
        runSet.setState(MockRunSet.STATE_RUNNING)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        self.__log.addExpectedExact("%s: Encountered ERROR while stopping run" %
                                    (StopThread.NAME, ))

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.setStopReturnError()

        finished = self.__waitForComplete(live.stopping, "Encountered ERROR" +
                                          " while stopping run")

        self.assertFalse(finished, "Unexpected value %s for 'finished'" %
                        str(finished))

    def testStopping(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579

        runSet = MockRunSet(runCfg)
        runSet.setState(MockRunSet.STATE_RUNNING)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        finished = False
        for _ in range(10):
            val = live.stopping()
            if val == INCOMPLETE_STATE_CHANGE:
                time.sleep(0.1)
                continue

            finished = True
            break

        self.assertTrue(finished, "Unexpected value %s for 'finished'" %
                        str(finished))

    def testRecoveringNothing(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecoveringDestroyed(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.setExpectedStopError()
        runSet.destroy()

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecoveringStopFail(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.setExpectedStopError()
        runSet.setStopReturnError()

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecovering(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.setExpectedStopError()

        self.__log.addExpectedExact("DAQLive stop_run %s returned %s" %
                                    (runSet, True))
        self.assertTrue(live.recovering(), "recovering failed")

    def testRunningNothing(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        exc = LiveException("Cannot check run state; no active runset")
        self.assertRaisesMsg(exc, live.running)

    def testRunningBadState(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        self.assertTrue(live.running(), "RunSet \"%s\" is %s, not running" %
                        (runSet, "???" if runSet is None else runSet.state))

    def testRunning(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.setState(runSet.STATE_RUNNING)

        self.assertTrue(live.running(), "running failed")

    def testSubrun(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        self.assertEqual("OK", live.subrun(1, ["domA", "dom2", ]))

    def testSwitchRun(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__createLive(cnc, self.__log)

        runCfg = "foo"
        runNum = 13579
        runSet = MockRunSet(runCfg)

        cnc.setExpectedRunConfig(runCfg)
        cnc.setExpectedRunNumber(runNum)
        cnc.setRunSet(runSet)

        state = {"runConfig": runCfg, "runNumber": runNum}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        state = {"runNumber": runNum + 1}

        rtnval = self.__waitForComplete(live.switchrun, state)
        self.assertTrue(rtnval, "switchrun failed with <%s>%s" %
                        (type(rtnval), rtnval))


if __name__ == '__main__':
    unittest.main()
