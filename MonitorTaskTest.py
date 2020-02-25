#!/usr/bin/env python

import os
import tempfile
import unittest
import shutil

from DAQClient import BeanTimeoutException
from LiveImports import Prio
from MonitorTask import MonitorTask
from RunOption import RunOption

from DAQMocks import MockComponent, MockIntervalTimer, MockLiveMoni, \
     MockLogger, MockMBeanClient, MockRunSet, MockTaskManager


class BadMBeanClient(MockMBeanClient):
    def __init__(self, comp_name):
        self.__raise_socket_error = False
        self.__raise_exception = False

        super(BadMBeanClient, self).__init__(comp_name)

    def clear_conditions(self):
        self.__raise_socket_error = False
        self.__raise_exception = False

    def get(self, bean_name, field_name):
        if self.__raise_socket_error:
            self.__raise_socket_error = False
            raise BeanTimeoutException("Mock exception")
        if self.__raise_exception:
            self.__raise_exception = False
            raise Exception("Mock exception")
        return super(BadMBeanClient, self).get(bean_name, field_name)

    def get_dictionary(self):
        if self.__raise_socket_error:
            self.__raise_socket_error = False
            raise BeanTimeoutException("Mock exception")
        if self.__raise_exception:
            self.__raise_exception = False
            raise Exception("Mock exception")
        return super(BadMBeanClient, self).get_dictionary()

    def raise_exception(self):
        self.__raise_exception = True

    def raise_socket_error(self):
        self.__raise_socket_error = True


class BadComponent(MockComponent):
    def __init__(self, name, num=0):
        super(BadComponent, self).__init__(name, num)

    def _create_mbean_client(self):
        return BadMBeanClient(self.fullname)


class BadCloseThread(object):
    def __init__(self):
        super(BadCloseThread, self).__init__()

        self.__closed = False

    def close(self):
        self.__closed = True
        raise Exception("Forced exception")

    def is_alive(self):  # pylint: disable=no-self-use
        return True

    @property
    def is_closed(self):
        return self.__closed


class BadMonitorTask(MonitorTask):
    def __init__(self, task_mgr, runset, logger, live, rundir, run_opts):
        super(BadMonitorTask, self).__init__(task_mgr, runset, logger, live,
                                             rundir, run_opts)

    @classmethod
    def create_thread(cls, comp, run_dir, live_moni, run_options, dashlog):
        return BadCloseThread()


class MonitorTaskTest(unittest.TestCase):
    __temp_dir = None

    @classmethod
    def __create_standard_components(cls):
        foo_comp = MockComponent("foo", 1)
        foo_comp.mbean.add_mock_data("fooB", "fooF", 12)
        foo_comp.mbean.add_mock_data("fooB", "fooG", "abc")

        bar_comp = MockComponent("bar", 0)
        bar_comp.mbean.add_mock_data("barB", "barF", 7)

        return [foo_comp, bar_comp, ]

    @classmethod
    def __create_standard_objects(cls):
        timer = MockIntervalTimer(MonitorTask.name)
        taskmgr = MockTaskManager()
        taskmgr.add_interval_timer(timer)

        logger = MockLogger("logger")
        live = MockLiveMoni()

        return (timer, taskmgr, logger, live)

    def __run_test(self, comp_list, timer, taskmgr, logger, live, run_opt,
                   raise_socket_error=False, raise_exception=False):
        runset = MockRunSet(comp_list)

        tsk = MonitorTask(taskmgr, runset, logger, live, self.__temp_dir,
                          run_opt)

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        for idx in range(-1, 5):
            if RunOption.is_moni_to_live(run_opt):
                for comp in comp_list:
                    if isinstance(comp, BadComponent):
                        comp.mbean.clear_conditions()
                    for bnm in comp.mbean.get_bean_names():
                        for fld in comp.mbean.get_bean_fields(bnm):
                            live.add_expected(comp.filename + "*" + bnm + "+" +
                                              fld,
                                              comp.mbean.get(bnm, fld),
                                              Prio.ITS)

            for comp in comp_list:
                if isinstance(comp, BadComponent):
                    if raise_socket_error:
                        if idx == 3:
                            errmsg = ("ERROR: Not monitoring %s:" +
                                      " Connect failed %d times") % \
                                      (comp.fullname, idx)
                            logger.add_expected_exact(errmsg)
                        elif 0 <= idx < 3:
                            comp.mbean.raise_socket_error()
                    elif idx > 0 and raise_exception:
                        errmsg = "Ignoring %s:(.*:)? Exception.*$" % \
                          comp.fullname
                        logger.add_expected_regexp(errmsg)
                        comp.mbean.raise_exception()

            timer.trigger()
            left = tsk.check()
            self.assertEqual(timer.wait_secs(), left,
                             "Expected %d seconds, not %d" %
                             (timer.wait_secs(), left))

            tsk.wait_until_finished()

            logger.check_status(4)

        tsk.close()

        self.__validate_files(run_opt, comp_list)

        logger.check_status(4)

    def __validate_files(self, run_opt, comp_list):
        files = os.listdir(self.__temp_dir)
        if not RunOption.is_moni_to_file(run_opt):
            found = len(files) > 0  # pylint: disable=len-as-condition
            self.assertFalse(found, "Found unexpected monitoring files: %s" %
                             str(files))
            return

        exp_files = len(comp_list)
        if MonitorTask.MONITOR_CNCSERVER:
            # if monitoring CnCServer, there should be a cncServer.moni file
            exp_files += 1

        self.assertTrue(len(files) == exp_files,
                        "Expected %d files, not %d: %s" %
                        (exp_files, len(files), files))

    def setUp(self):
        self.__temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        try:
            shutil.rmtree(self.__temp_dir)
        except:  # pylint: disable=bare-except
            pass  # ignore errors

    def test_bad_run_opt(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        comp_list = self.__create_standard_components()

        self.__run_test(comp_list, timer, taskmgr, logger, live, 0)

    def test_good_none(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        comp_list = self.__create_standard_components()

        self.__run_test(comp_list, timer, taskmgr, logger, live,
                        RunOption.MONI_TO_NONE)

    def test_good_file(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        comp_list = self.__create_standard_components()

        self.__run_test(comp_list, timer, taskmgr, logger, live,
                        RunOption.MONI_TO_FILE)

    def test_good_live(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        comp_list = self.__create_standard_components()

        self.__run_test(comp_list, timer, taskmgr, logger, live,
                        RunOption.MONI_TO_LIVE)

    def test_good_both(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        comp_list = self.__create_standard_components()

        self.__run_test(comp_list, timer, taskmgr, logger, live,
                        RunOption.MONI_TO_BOTH)

    def test_socket_error(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        foo_comp = MockComponent("foo", 1)
        foo_comp.mbean.add_mock_data("fooB", "fooF", 12)
        foo_comp.mbean.add_mock_data("fooB", "fooG", "abc")

        bar_comp = BadComponent("bar", 0)
        bar_comp.mbean.add_mock_data("barB", "barF", 7)

        comp_list = [foo_comp, bar_comp, ]
        self.__run_test(comp_list, timer, taskmgr, logger, live,
                        RunOption.MONI_TO_BOTH, raise_socket_error=True)

    def test_exception(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        foo_comp = MockComponent("foo", 1)
        foo_comp.mbean.add_mock_data("fooB", "fooF", 12)
        foo_comp.mbean.add_mock_data("fooB", "fooG", "abc")

        bar_comp = BadComponent("bar", 0)
        bar_comp.mbean.add_mock_data("barB", "barF", 7)

        comp_list = [foo_comp, bar_comp, ]
        self.__run_test(comp_list, timer, taskmgr, logger, live,
                        RunOption.MONI_TO_BOTH, raise_exception=True)

    def test_failed_close(self):
        (timer, taskmgr, logger, live) = self.__create_standard_objects()

        comp_list = self.__create_standard_components()
        runset = MockRunSet(comp_list)

        tsk = BadMonitorTask(taskmgr, runset, logger, live, self.__temp_dir,
                             RunOption.MONI_TO_LIVE)
        timer.trigger()
        tsk.check()

        try:
            tsk.close()
        except Exception as exc:  # pylint: disable=broad-except
            if not str(exc).endswith("Forced exception"):
                raise
        self.assertTrue(tsk.open_threads == 0,
                        "%d threads were not closed" % (tsk.open_threads, ))


if __name__ == '__main__':
    unittest.main()
