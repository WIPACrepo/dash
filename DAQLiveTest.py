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
from decorators import classproperty


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
        self.__exp_stop_err = False
        self.__stop_return = False

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

    def send_event_counts(self):
        if self.is_destroyed:
            raise Exception("Runset destroyed")

    def set_expected_stop_error(self):
        self.__exp_stop_err = True

    def set_running(self):
        self.__state = MockRunSet.STATE_RUNNING

    def set_stop_return_error(self):
        if self.is_destroyed:
            raise Exception("Runset destroyed")

        self.__stop_return = True

    @property
    def state(self):
        return self.__state

    def stop_run(self, caller_name, had_error=False):
        if self.is_destroyed:
            raise Exception("Runset destroyed")

        if had_error != self.__exp_stop_err:
            raise Exception("Expected 'had_error' to be %s" %
                            (self.__exp_stop_err, ))

        self.__state = self.STATE_READY
        return self.__stop_return

    def stopping(self):
        return False

    def subrun(self, subrun_id, dom_list):
        pass

    def switch_run(self, state_args):
        pass


class MockCnC(object):
    RELEASE = "rel"
    REPO_REV = "repoRev"

    def __init__(self):
        self.__exp_run_cfg = None
        self.__exp_run_num = None
        self.__missing_comps = None
        self.__runset = None

    def break_runset(self, runset):
        runset.destroy()

    def is_starting(self):
        return False

    def make_runset_from_run_config(self, run_cfg, run_num):
        if self.__exp_run_cfg is None:
            raise Exception("Expected run configuration has not been set")
        if self.__exp_run_cfg != run_cfg:
            raise Exception("Expected run config \"%s\", not \"%s\"" %
                            (self.__exp_run_cfg, run_cfg))
        if self.__exp_run_num != run_num:
            raise Exception("Expected run number %s, not %s" %
                            (self.__exp_run_num, run_num))
        if self.__missing_comps is not None:
            tmp_list = self.__missing_comps
            self.__missing_comps = None
            raise MissingComponentException(tmp_list)

        if self.__runset is not None:
            self.__runset.set_running()

        return self.__runset

    def set_expected_run_config(self, run_cfg):
        self.__exp_run_cfg = run_cfg

    def set_expected_run_number(self, run_num):
        self.__exp_run_num = run_num

    def set_runset(self, runset):
        self.__runset = runset

    def set_missing_components(self, comp_list):
        self.__missing_comps = comp_list

    def start_run(self, runset, run_num,
                  run_opts):  # pylint: disable=unused-argument
        if self.__exp_run_cfg is None:
            raise Exception("Expected run configuration has not been set")
        if self.__exp_run_cfg != runset.run_config():
            raise Exception("Expected run config \"%s\", not \"%s\"" %
                            (self.__exp_run_cfg, runset.run_config()))

        if self.__exp_run_num is None:
            raise Exception("Expected run number has not been set")
        if self.__exp_run_num != run_num:
            raise Exception("Expected run Number %s, not %s" %
                            (self.__exp_run_num, run_num))

    def stop_collecting(self):
        pass

    def version_info(self):
        return {"release": self.RELEASE, "repo_rev": self.REPO_REV}


class DAQLiveTest(unittest.TestCase):
    __warned = False

    def __create_live(self, cnc, log):
        self.__live = DAQLive(cnc, log, timeout=1)
        return self.__live

    @property
    def __imported_live(self):
        if LIVE_IMPORT:
            return True

        if not self.was_warned:
            self.set_warned()
            print("No I3Live Python code found, cannot run tests",
                  file=sys.stderr)

        return False

    @classmethod
    def set_warned(cls):
        cls.__warned = True

    @classproperty
    def was_warned(cls):  # pylint: disable=no-self-argument
        return cls.__warned

    @classmethod
    def __wait_for_complete(cls, func, *args, **kwargs):
        if "expected_exception" not in kwargs:
            expected_exception = None
        else:
            expected_exception = kwargs["expected_exception"]

        for _ in range(10):
            try:
                val = func(*args)
            except LiveException as lex:
                if expected_exception is None or \
                   str(expected_exception) != str(lex):
                    raise
                expected_exception = None
                break

            if val != INCOMPLETE_STATE_CHANGE:
                return val

            time.sleep(0.1)

        if expected_exception is not None:
            raise Exception("Did not received expected %s: %s" %
                            (type(expected_exception).__name__,
                             expected_exception))

        return None

    def assert_raises_msg(self, exc, func, *args, **kwargs):
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
            (exc_type, exc_val, exc_tb) = sys.exc_info()
            if isinstance(exc_val, type(exc)) and str(exc_val) == str(exc):
                return
            raise self.failureException("Expected %s(%s), not %s(%s)" %
                                        (type(exc), exc, type(exc_val),
                                         exc_val))
        raise self.failureException("%s(%s) not raised" % (type(exc), exc))

    def setUp(self):
        self.__live = None
        self.__log = MockLogger("liveLog")

    def tearDown(self):
        if self.__live is not None:
            try:
                self.__live.close()
            except:  # pylint: disable=bare-except
                traceback.print_exc()

        self.__log.check_status(0)

    def test_version(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        self.assertEqual(live.version(),
                         MockCnC.RELEASE + "_" + MockCnC.REPO_REV)

    def test_starting_no_state_args(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        self.assert_raises_msg(LiveException("No state_args specified"),
                               live.starting, None)

    def test_starting_no_keys(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)

        state = {}

        self.assert_raises_msg(LiveException("No state_args specified"),
                               live.starting, state)

    def test_starting_no_run_cfg_key(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)

        state = {"runNumber": run_num}

        exc = LiveException("state_args does not contain key \"runConfig\"")
        self.assert_raises_msg(exc, live.starting, state)

    def test_starting_no_run_num_key(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)

        state = {"runConfig": run_cfg}

        exc = LiveException("state_args does not contain key \"runNumber\"")
        self.assert_raises_msg(exc, live.starting, state)

    def test_starting_no_run_set(self):
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

        self.__log.add_expected_exact(StartThread.NAME + ": " + errmsg)

        exp_exc = LiveException(errmsg)
        rtnval = self.__wait_for_complete(live.starting, state,
                                          expected_exception=exp_exc)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def test_starting(self):
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

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def test_starting_twice(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        state2 = {"runConfig": run_cfg, "runNumber": run_num + 1}
        rtnval = self.__wait_for_complete(live.starting, state2)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def test_starting_missing_comp(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        runset = MockRunSet(run_cfg)
        runset.set_running()

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        missing = ["hub", "bldr"]
        cnc.set_missing_components(missing)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        errmsg = "%s: Cannot create run #%d runset for \"%s\": Still waiting" \
                 " for %s" % (StartThread.NAME, run_num, run_cfg, missing)
        self.__log.add_expected_exact(errmsg)

        exp_exc = LiveException(errmsg)
        rtnval = self.__wait_for_complete(live.starting, state,
                                          expected_exception=exp_exc)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

    def test_stopping_no_runset(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        finished = False
        for _ in range(10):
            val = live.stopping()
            if val == INCOMPLETE_STATE_CHANGE:
                time.sleep(0.1)
                continue

            finished = True

        self.assertTrue(finished, "Unexpected value %s for 'finished'" %
                        str(finished))

    def test_stopping_error(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        runset = MockRunSet(run_cfg)
        runset.set_running()

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        self.__log.add_expected_exact("%s: Encountered ERROR while stopping"
                                      " run" % (StopThread.NAME, ))

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runset.set_stop_return_error()

        finished = self.__wait_for_complete(live.stopping, "Encountered ERROR"
                                            " while stopping run")

        self.assertTrue(finished, "Unexpected value %s for 'finished'" %
                        str(finished))

    def test_stopping(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579

        runset = MockRunSet(run_cfg)
        runset.set_running()

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
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

    def test_recovering_nothing(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        self.assertTrue(live.recovering(), "recovering failed")

    def test_recovering_destroyed(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runset.set_expected_stop_error()
        runset.destroy()

        self.assertTrue(live.recovering(), "recovering failed")

    def test_recovering_stop_fail(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runset.set_expected_stop_error()
        runset.set_stop_return_error()

        self.assertTrue(live.recovering(), "recovering failed")

    def test_recovering(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runset.set_expected_stop_error()

        self.__log.add_expected_exact("DAQLive stop_run %s returned %s" %
                                      (runset, True))
        self.assertTrue(live.recovering(), "recovering failed")

    def test_running_nothing(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        self.__log.add_expected_exact("DAQLive.running() dying due to"
                                      " missing runset")
        exc = LiveException("Cannot check run state; no active runset")
        self.assert_raises_msg(exc, live.running)

    def test_running_bad_state(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        self.assertTrue(live.running(), "RunSet \"%s\" is %s, not running" %
                        (runset, "???" if runset is None else runset.state))

    def test_running(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        runset.set_running()

        self.assertTrue(live.running(), "running failed")

    def test_subrun(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        self.assertEqual("OK", live.subrun(1, ["domA", "dom2", ]))

    def test_switch_run(self):
        if not self.__imported_live:
            return

        cnc = MockCnC()
        live = self.__create_live(cnc, self.__log)

        run_cfg = "foo"
        run_num = 13579
        runset = MockRunSet(run_cfg)

        cnc.set_expected_run_config(run_cfg)
        cnc.set_expected_run_number(run_num)
        cnc.set_runset(runset)

        state = {"runConfig": run_cfg, "runNumber": run_num}

        rtnval = self.__wait_for_complete(live.starting, state)
        self.assertTrue(rtnval, "starting failed with <%s>%s" %
                        (type(rtnval), rtnval))

        state = {"runNumber": run_num + 1}

        self.__log.add_expected_exact("SwitchRun is returning True after"
                                      " ending LiveSwitch thread")
        rtnval = self.__wait_for_complete(live.switchrun, state)
        self.assertTrue(rtnval, "switchrun failed with <%s>%s" %
                        (type(rtnval), rtnval))


if __name__ == '__main__':
    unittest.main()
