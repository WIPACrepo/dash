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

    def __init__(self, run_cfg):
        self.__state = self.STATE_UNKNOWN
        self.__run_cfg = run_cfg
        self.__expStopErr = False
        self.__stopReturn = False

    def __str__(self):
        return "MockRunSet"

    def destroy(self):
        self.__state = self.STATE_DESTROYED

    @property
    def is_destroyed(self):
        return self.__state == self.STATE_DESTROYED

    @property
    def is_idle(self):
        return self.__state == self.STATE_IDLE

    @property
    def is_ready(self):
        return self.__state == self.STATE_READY

    @property
    def is_running(self):
        return self.__state == self.STATE_RUNNING

    def run_config(self):
        if self.is_destroyed:
            raise Exception("Runset destroyed")

        return self.__run_cfg

    def sendEventCounts(self):
        if self.is_destroyed:
            raise Exception("Runset destroyed")

    def set_expected_stop_error(self):
        self.__expStopErr = True

    def set_running(self):
        self.__state = MockRunSet.STATE_RUNNING

    def set_stop_return_error(self):
        if self.is_destroyed:
            raise Exception("Runset destroyed")

        self.__stopReturn = True

    @property
    def state(self):
        return self.__state

    def stop_run(self, caller_name, had_error=False):
        if self.is_destroyed:
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
        self.__exp_run_cfg = None
        self.__exp_run_num = None
        self.__missingComps = None
        self.__runSet = None

    def break_runset(self, runset):
        runset.destroy()

    def is_starting(self):
        return False

    def make_runset_from_run_config(self, run_cfg, run_num):
        if self.__exp_run_cfg is None:
            raise Exception("Expected run configuration has not been set")
        if self.__exp_run_cfg != run_cfg:
            raise Exception("Expected run config \"%s\", not \"%s\"",
                            self.__exp_run_cfg, run_cfg)
        if self.__exp_run_num != run_num:
            raise Exception("Expected run number %s, not %s",
                            self.__exp_run_num, run_num)
        if self.__missingComps is not None:
            tmpList = self.__missingComps
            self.__missingComps = None
            raise MissingComponentException(tmpList)

        if self.__runSet is not None:
            self.__runSet.set_running()

        return self.__runSet

    def set_expected_run_config(self, run_cfg):
        self.__exp_run_cfg = run_cfg

    def set_expected_run_number(self, run_num):
        self.__exp_run_num = run_num

    def set_runset(self, runSet):
        self.__runSet = runSet

    def setMissingComponents(self, compList):
        self.__missingComps = compList

    def start_run(self, runset, run_num, runOpts):
        if self.__exp_run_cfg is None:
            raise Exception("Expected run configuration has not been set")
        if self.__exp_run_cfg != runset.run_config():
            raise Exception("Expected run config \"%s\", not \"%s\"",
                            self.__exp_run_cfg, runset.run_config())

        if self.__exp_run_num is None:
            raise Exception("Expected run number has not been set")
        if self.__exp_run_num != run_num:
            raise Exception("Expected run Number %s, not %s",
                            self.__exp_run_num, run_num)

    def stop_collecting(self):
        pass

    def version_info(self):
        return {"release": self.RELEASE, "repo_rev": self.REPO_REV}


class DAQLiveTest(unittest.TestCase):
    def __create_live(self, cnc, log):
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
        live = self.__create_live(cnc, self.__log)

        self.assertEqual(live.version(),
                         MockCnC.RELEASE + "_" + MockCnC.REPO_REV)

    def testStartingNoStateArgs(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, None)

    def testStartingNoKeys(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)

        state = {}

        self.assertRaisesMsg(LiveException("No stateArgs specified"),
                             live.starting, state)

    def testStartingNoRun_cfgKey(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)

        state = {"runNumber": run_num}

        exc = LiveException("stateArgs does not contain key \"runConfig\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunNumKey(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)

        state = {"runConfig": run_cfg}

        exc = LiveException("stateArgs does not contain key \"runNumber\"")
        self.assertRaisesMsg(exc, live.starting, state)

    def testStartingNoRunSet(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        errmsg = "Cannot create run #%d runset for \"%s\"" % (run_num, run_cfg)

        self.__log.addExpectedExact(StartThread.NAME + ": " + errmsg)

        rtnval = self.__waitForComplete(live.starting, state,
                                        expectedException=LiveException(errmsg))
        self.assertFalse(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStarting(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(MockRunSet(run_cfg))

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStartingTwice(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        state2 = {"runConfig": run_cfg, "runNumber": run_num + 1}
        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStartingMissingComp(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        runSet = MockRunSet(run_cfg)
        runSet.set_running()

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        missing = ["hub", "bldr"]
        cnc.setMissingComponents(missing)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        errmsg = "%s: Cannot create run #%d runset for \"%s\": Still waiting" \
                 " for %s" % (StartThread.NAME, run_num, run_cfg, missing)
        self.__log.addExpectedExact(errmsg)

        rtnval = self.__waitForComplete(live.starting, state,
                                        expectedException=LiveException(errmsg))
        self.assertFalse(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def testStoppingNoRunset(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

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
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        runSet = MockRunSet(run_cfg)
        runSet.set_running()

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        self.__log.addExpectedExact("%s: Encountered ERROR while stopping run" %
                                    (StopThread.NAME, ))

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.set_stop_return_error()

        finished = self.__waitForComplete(live.stopping, "Encountered ERROR" +
                                          " while stopping run")

        self.assertFalse(finished, "Unexpected value %s for 'finished'" %
                        str(finished))

    def testStopping(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        runSet = MockRunSet(run_cfg)
        runSet.set_running()

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

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
        live = self.__create_live(cnc, self.__log)

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecoveringDestroyed(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.set_expected_stop_error()
        runSet.destroy()

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecoveringStopFail(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.set_expected_stop_error()
        runSet.set_stop_return_error()

        self.assertTrue(live.recovering(), "recovering failed")

    def testRecovering(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.set_expected_stop_error()

        self.__log.addExpectedExact("DAQLive stop_run %s returned %s" %
                                    (runSet, True))
        self.assertTrue(live.recovering(), "recovering failed")

    def testRunningNothing(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        exc = LiveException("Cannot check run state; no active runset")
        self.assertRaisesMsg(exc, live.running)

    def testRunningBadState(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        self.assertTrue(live.running(), "RunSet \"%s\" is %s, not running" %
                        (runSet, "???" if runSet is None else runSet.state))

    def testRunning(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runSet.set_running()

        self.assertTrue(live.running(), "running failed")

    def testSubrun(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        self.assertEqual("OK", live.subrun(1, ["domA", "dom2", ]))

    def testSwitchRun(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runSet = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runSet)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__waitForComplete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        state = {"runNumber": run_num + 1}

        rtnval = self.__waitForComplete(live.switchrun, state)
        self.assertTrue(rtnval, "switchrun failed with <%s>%s" %
                        (type(rtnval), rtnval))


if __name__ == '__main__':
    unittest.main()
