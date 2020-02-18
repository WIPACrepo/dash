#!/usr/bin/env python

import unittest

from WatchdogTask import WatchdogRule, WatchdogTask

from DAQMocks import MockComponent, MockIntervalTimer, MockLogger, \
     MockRunSet, MockTaskManager


class BadMatchRule(WatchdogRule):
    def init_data(self, data, this_comp, components):
        pass

    def matches(self, comp):
        raise Exception("FAIL")


class BadInitRule(WatchdogRule):
    def init_data(self, data, this_comp, components):
        raise Exception("FAIL")

    def matches(self, comp):
        return comp.name == "foo"


class BarRule(WatchdogRule):
    def __init__(self, check_val):
        self.__check_val = check_val

    def init_data(self, data, this_comp, components):
        if self.__check_val:
            data.add_input_value(this_comp, "barBean", "barFld")

    def matches(self, comp):
        return comp.name == "bar"


class FooRule(WatchdogRule):
    def __init__(self, test_in=True, test_out=True, test_thresh=True):
        self.__test_in = test_in
        self.__test_out = test_out
        self.__test_thresh = test_thresh

    def init_data(self, data, this_comp, components):
        foo_comp = None
        for comp in components:
            if comp.name == "foo":
                foo_comp = comp
                break
        if foo_comp is None:
            raise Exception("Cannot find \"foo\" component")

        if self.__test_in:
            data.add_input_value(foo_comp, "inBean", "inFld")
        if self.__test_out:
            data.add_output_value(foo_comp, "outBean", "outFld")
        if self.__test_thresh:
            data.add_threshold_value("threshBean", "threshFld", 10)

    def matches(self, comp):
        return comp.name == "foo"


class WatchdogTaskTest(unittest.TestCase):
    def __build_foo(self):
        foo_comp = MockComponent("foo", 1)
        foo_comp.order = 1
        foo_comp.mbean.add_mock_data("inBean", "inFld", 0)
        foo_comp.mbean.add_mock_data("outBean", "outFld", 0)
        foo_comp.mbean.add_mock_data("threshBean", "threshFld", 0)
        return foo_comp

    def __build_bar(self, add_bar_beans=False):
        bar_comp = MockComponent("bar", 0)
        bar_comp.order = 2
        if add_bar_beans:
            bar_comp.mbean.add_mock_data("barBean", "barFld", 0)

        return bar_comp

    def __build_runset(self, add_bar_beans=False):
        comps = (self.__build_foo(),
                 self.__build_bar(add_bar_beans=add_bar_beans))

        return MockRunSet(comps)

    def __run_test(self, runset, rules, test_in, test_out, test_thresh,
                   test_both):
        timer = MockIntervalTimer(WatchdogTask.name)
        task_mgr = MockTaskManager()
        task_mgr.add_interval_timer(timer)

        logger = MockLogger("logger")

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(task_mgr, runset, logger, rules=rules)

        timer.trigger()
        tsk.check()
        tsk.wait_until_finished()

        end_val = WatchdogTask.HEALTH_METER_FULL
        if not test_thresh:
            end_val += 1

        for i in range(0, end_val):
            health = WatchdogTask.HEALTH_METER_FULL - i
            if test_thresh:
                health -= 1
            timer.trigger()

            if test_thresh:
                logger.add_expected_regexp(r"Watchdog reports threshold"
                                           r" components:.*")
            if i > 0:
                if test_in:
                    logger.add_expected_regexp(r"Watchdog reports starved"
                                               r" components:.*")
                if (test_out and not test_in) or (test_out and test_both):
                    logger.add_expected_regexp(r"Watchdog reports stagnant"
                                               r" components:.*")
                if test_in or test_out or test_thresh:
                    if health <= 0:
                        logger.add_expected_exact("Run is not healthy,"
                                                  " stopping")
                    elif health % WatchdogTask.NUM_HEALTH_MSGS == 0:
                        logger.add_expected_exact("Run is unhealthy" +
                                                  " (%d checks left)" % health)

            tsk.check()
            tsk.wait_until_finished()

            logger.check_status(4)

        if test_in or test_out or test_thresh:
            self.assertTrue(task_mgr.has_error,
                            "TaskManager is not error state")

        tsk.close()

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_unknown_comp(self):
        timer = MockIntervalTimer(WatchdogTask.name)
        task_mgr = MockTaskManager()
        task_mgr.add_interval_timer(timer)

        foo_comp = MockComponent("foo", 1)
        foo_comp.order = 1

        runset = MockRunSet([foo_comp, ])

        logger = MockLogger("logger")
        logger.add_expected_exact("Couldn't create watcher for unknown" +
                                  " component %s#%d" %
                                  (foo_comp.name, foo_comp.num))

        WatchdogTask(task_mgr, runset, logger, period=None, rules=())

        logger.check_status(1)

    def test_bad_match_rule(self):
        timer = MockIntervalTimer(WatchdogTask.name)
        task_mgr = MockTaskManager()
        task_mgr.add_interval_timer(timer)

        foo_comp = MockComponent("foo", 1)
        foo_comp.order = 1

        runset = MockRunSet([foo_comp, ])

        logger = MockLogger("logger")
        logger.add_expected_regexp(r"Couldn't create watcher for component"
                                   r" %s#%d: .*" %
                                   (foo_comp.name, foo_comp.num))

        WatchdogTask(task_mgr, runset, logger, rules=(BadMatchRule(), ))

        logger.check_status(1)

    def test_bad_init_rule(self):

        foo_comp = self.__build_foo()

        rules = (BadInitRule(), )

        timer = MockIntervalTimer(WatchdogTask.name)
        task_mgr = MockTaskManager()
        task_mgr.add_interval_timer(timer)

        logger = MockLogger("logger")

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        tsk = WatchdogTask(task_mgr, MockRunSet((foo_comp, )), logger,
                           rules=rules)

        logger.check_status(5)

        for i in range(1, 4):
            logger.add_expected_regexp(r"Initialization failure #%d for"
                                       r" %s %s.*" %
                                       (i, foo_comp.fullname, rules[0]))

            timer.trigger()
            tsk.check()
            tsk.wait_until_finished()

            logger.check_status(5)

    def test_foo_input_unhealthy(self):
        test_in = True
        test_out = False
        test_thresh = False
        add_bar_beans = False

        runset = self.__build_runset(add_bar_beans=add_bar_beans)

        rules = (FooRule(test_in, test_out, test_thresh),
                 BarRule(add_bar_beans))

        self.__run_test(runset, rules, test_in, test_out, test_thresh, False)

    def test_foo_output_unhealthy(self):
        test_in = False
        test_out = True
        test_thresh = False
        add_bar_beans = False

        runset = self.__build_runset(add_bar_beans=add_bar_beans)

        rules = (FooRule(test_in, test_out, test_thresh),
                 BarRule(add_bar_beans))

        self.__run_test(runset, rules, test_in, test_out, test_thresh, False)

    def test_foo_threshold_unhealthy(self):
        test_in = False
        test_out = False
        test_thresh = True
        add_bar_beans = False

        runset = self.__build_runset(add_bar_beans=add_bar_beans)

        rules = (FooRule(test_in, test_out, test_thresh),
                 BarRule(add_bar_beans))

        self.__run_test(runset, rules, test_in, test_out, test_thresh, False)

    def test_foo_all_unhealthy(self):
        test_in = True
        test_out = True
        test_thresh = True
        add_bar_beans = False

        runset = self.__build_runset(add_bar_beans=add_bar_beans)

        rules = (FooRule(test_in, test_out, test_thresh),
                 BarRule(add_bar_beans))

        self.__run_test(runset, rules, test_in, test_out, test_thresh, False)

    def test_foo_unhealthy_with_bar(self):
        test_in = True
        test_out = False
        test_thresh = False
        add_bar_beans = True

        runset = self.__build_runset(add_bar_beans=add_bar_beans)

        rules = (FooRule(test_in, test_out, test_thresh),
                 BarRule(add_bar_beans))

        self.__run_test(runset, rules, test_in, test_out, test_thresh, False)

    def test_standard(self):
        hub = MockComponent("stringHub", 0, 1)
        hub.mbean.add_mock_data("sender", "NumHitsReceived", 0)
        hub.mbean.add_mock_data("sender", "NumReadoutRequestsReceived", 0)
        hub.mbean.add_mock_data("sender", "NumReadoutsSent", 0)

        iitrig = MockComponent("inIceTrigger", 0, 1)
        iitrig.mbean.add_mock_data("stringHit", "RecordsReceived", 0)
        iitrig.mbean.add_mock_data("trigger", "RecordsSent", 0)

        gtrig = MockComponent("globalTrigger", 0, 1)
        gtrig.mbean.add_mock_data("trigger", "RecordsReceived", 0)
        gtrig.mbean.add_mock_data("glblTrig", "RecordsSent", 0)

        ebldr = MockComponent("eventBuilder", 0, 1)
        ebldr.mbean.add_mock_data("backEnd", "NumReadoutsReceived", 0)
        ebldr.mbean.add_mock_data("backEnd", "NumTriggerRequestsReceived", 0)
        ebldr.mbean.add_mock_data("backEnd", "NumEventsDispatched", 0)
        ebldr.mbean.add_mock_data("backEnd", "NumEventsSent", 0)
        ebldr.mbean.add_mock_data("backEnd", "NumBadEvents", 0)
        ebldr.mbean.add_mock_data("backEnd", "DiskAvailable", 0)

        sbldr = MockComponent("secondaryBuilders", 0, 1)
        sbldr.mbean.add_mock_data("snBuilder", "NumDispatchedData", 0)
        sbldr.mbean.add_mock_data("snBuilder", "DiskAvailable", 0)
        sbldr.mbean.add_mock_data("moniBuilder", "NumDispatchedData", 0)
        # sbldr.mbean.add_mock_data("tcalBuilder", "NumDispatchedData", 0)

        comp_list = [hub, iitrig, gtrig, ebldr, sbldr, ]

        num = 1
        for comp in comp_list:
            comp.order = num
            num += 1

        runset = MockRunSet(comp_list)

        self.__run_test(runset, None, True, True, True, True)

    def test_long_startup(self):
        timer = MockIntervalTimer(WatchdogTask.name)
        task_mgr = MockTaskManager()
        task_mgr.add_interval_timer(timer)

        logger = MockLogger("logger")

        # from DAQMocks import LogChecker; LogChecker.DEBUG = True

        foo_comp = self.__build_foo()

        rules = (FooRule(True, False, False), )

        max_health = WatchdogTask.HEALTH_METER_FULL + 6

        tsk = WatchdogTask(task_mgr, MockRunSet((foo_comp, )), logger,
                           initial_health=max_health, rules=rules)

        timer.trigger()
        tsk.check()
        tsk.wait_until_finished()

        for health in range(max_health - 1, 0, -1):
            if health <= WatchdogTask.HEALTH_METER_FULL:
                logger.add_expected_regexp(r"Watchdog reports starved"
                                           r" components:.*")
                if health < WatchdogTask.HEALTH_METER_FULL and \
                   ((health - 1) % WatchdogTask.NUM_HEALTH_MSGS) == 0:
                    if health - 1 == 0:
                        logger.add_expected_exact("Run is not healthy,"
                                                  " stopping")
                    else:
                        logger.add_expected_regexp(r"Run is unhealthy"
                                                   r" \(\d+ checks left\)")

            timer.trigger()

            tsk.check()
            tsk.wait_until_finished()

            logger.check_status(5)


if __name__ == '__main__':
    unittest.main()
