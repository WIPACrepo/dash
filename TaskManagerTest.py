#!/usr/bin/env python
"Test TaskManager"

import copy
import time
import unittest

from ActiveDOMsTask import ActiveDOMThread
from Component import Component
from LiveImports import Prio
from RunOption import RunOption
from TaskManager import TaskManager
from WatchdogTask import WatchdogTask

from DAQMocks import MockIntervalTimer, MockLiveMoni, MockLogger, MockRunSet


class MockTMMBeanClient(object):
    "Mock MBean client"

    BEANBAG = {
        "stringHub": {
            "stringhub": {
                "NumberOfActiveChannels": 2,
                "NumberOfActiveAndTotalChannels": [1, 2],
                "TotalLBMOverflows": 20,
            },
            "sender": {
                "NumHitsReceived": 0,
                "NumReadoutRequestsReceived": 0,
                "NumReadoutsSent": 0,
            },
        },
        "iceTopTrigger": {
            "icetopHit": {
                "RecordsReceived": 0
            },
            "trigger": {
                "RecordsSent": 0
            },
        },
        "inIceTrigger": {
            "stringHit": {
                "RecordsReceived": 0
            },
            "trigger": {
                "RecordsSent": 0
            },
        },
        "globalTrigger": {
            "trigger": {
                "RecordsReceived": 0
            },
            "glblTrig": {
                "RecordsSent": 0
            },
        },
        "eventBuilder": {
            "backEnd": {
                "DiskAvailable": 2560,
                "NumBadEvents": 0,
                "NumEventsDispatched": 0,
                "NumEventsSent": 0,
                "NumReadoutsReceived": 0,
                "NumTriggerRequestsReceived": 0,
                "NumBytesWritten": 0
            },
        },
        "secondaryBuilders": {
            "moniBuilder": {
                "NumDispatchedData": 0
            },
            "snBuilder": {
                "NumDispatchedData": 0,
                "DiskAvailable": 0,
            },
        }
    }

    def __init__(self, name, num):
        self.__name = name
        self.__num = num

        self.__bean_data = self.__create_bean_data()

    def __str__(self):
        if self.__num == 0:
            return self.__name
        return "%s#%d" % (self.__name, self.__num)

    def __create_bean_data(self):
        if self.__name not in self.BEANBAG:
            raise Exception("No bean data found for %s" % self.__name)

        data = {}
        for bnm in self.BEANBAG[self.__name]:
            if bnm not in data:
                data[bnm] = {}
            for fld in self.BEANBAG[self.__name][bnm]:
                data[bnm][fld] = self.BEANBAG[self.__name][bnm][fld]

        return data

    def check(self, bean_name, field_name):
        "Return True if there is data for `bean.field`"
        return bean_name in self.__bean_data and \
            field_name in self.__bean_data[bean_name]

    def get(self, bean_name, field_name):
        "Return the data for `bean.field`"
        if not self.check(bean_name, field_name):
            raise Exception("No %s data for bean %s field %s" %
                            (self, bean_name, field_name))

        return self.__bean_data[bean_name][field_name]

    def get_attributes(self, bean_name, field_list):
        "Return a dictionary holding data for all the requested MBean fields"
        rtn_map = {}
        for fld in field_list:
            rtn_map[fld] = self.get(bean_name, fld)
        return rtn_map

    def get_bean_fields(self, bean_name):
        "Return a list of field names for the MBean"
        return list(self.__bean_data[bean_name].keys())

    def get_bean_names(self):
        "Return a list of MBean names"
        return list(self.__bean_data.keys())

    def get_dictionary(self):
        "Return the entire dictionary of MBean data"
        return copy.deepcopy(self.__bean_data)

    def reload(self):  # pylint: disable=no-self-use
        "Pretend to reload the MBean data"
        return


class MockTMComponent(Component):
    "Mock component"

    def __init__(self, name, num):
        super(MockTMComponent, self).__init__(name, num)

        self.__order = None
        self.__updated_rates = False

        self.__mbean = MockTMMBeanClient(name, num)

    def __str__(self):
        return self.fullname

    def create_mbean_client(self):
        "Return the common MBean client"
        return self.__mbean

    @property
    def filename(self):
        "Return a fake filename"
        return "%s-%d" % (self.name, self.num)

    @property
    def is_source(self):
        "Return True if this is a data source (e.g. stringHub)"
        return self.is_hub

    @property
    def mbean(self):
        "Return the cached MBean client"
        return self.__mbean

    @property
    def order(self):
        "Return the order for this component"
        return self.__order

    @order.setter
    def order(self, num):
        "Set the order in which components are started/stopped"
        self.__order = num

    def update_rates(self):
        "Pretend to fetch this component's updated event rates"
        self.__updated_rates = True

    def was_updated(self):
        "Return True if this component's update_rates() method was called"
        return self.__updated_rates


class MockRunConfig(object):
    "Create a mock run configuration object"

    def __init__(self):
        pass

    @property
    def monitor_period(self):
        "Return None for monitor period"
        return None

    @property
    def watchdog_period(self):
        "Return None for watchdog period"
        return None


class MyTaskManager(TaskManager):
    "Test version of TaskManager which returns mock interval timers"

    def __init__(self, runset, dashlog, live, run_dir, run_cfg, moniType):
        self.__timer_dict = {}
        super(MyTaskManager, self).__init__(runset, dashlog, live, run_dir,
                                            run_cfg, moniType)

    def create_interval_timer(self, name, period):
        "Create a mock interval timer and add it to our timer cache"
        timer = MockIntervalTimer(name)
        self.__timer_dict[name] = timer
        return timer

    def trigger_timers(self):
        "Trigger cached task timers so tasks will be run"
        for k in self.__timer_dict:
            self.__timer_dict[k].trigger()


class TaskManagerTest(unittest.TestCase):
    "Test TaskManager methods"

    @classmethod
    def __load_expected(cls, live, first=True):
        "Add expected monitoring values to 'live'"

        # add monitoring data
        live.add_expected("stringHub-1*sender+NumHitsReceived",
                          0, Prio.ITS)
        live.add_expected("stringHub-1*sender+NumReadoutRequestsReceived",
                          0, Prio.ITS)
        live.add_expected("stringHub-1*sender+NumReadoutsSent", 0, Prio.ITS)
        live.add_expected("stringHub-1*stringhub+NumberOfActiveChannels",
                          2, Prio.ITS)
        live.add_expected("stringHub-1*stringhub+TotalLBMOverflows",
                          20, Prio.ITS)
        live.add_expected(
            "stringHub-1*stringhub+NumberOfActiveAndTotalChannels",
            [1, 2], Prio.ITS)

        live.add_expected("iceTopTrigger-0*icetopHit+RecordsReceived",
                          0, Prio.ITS)
        live.add_expected("iceTopTrigger-0*trigger+RecordsSent", 0, Prio.ITS)
        live.add_expected("inIceTrigger-0*stringHit+RecordsReceived",
                          0, Prio.ITS)
        live.add_expected("inIceTrigger-0*trigger+RecordsSent", 0, Prio.ITS)
        live.add_expected("globalTrigger-0*trigger+RecordsReceived",
                          0, Prio.ITS)

        live.add_expected("globalTrigger-0*glblTrig+RecordsSent",
                          0, Prio.ITS)
        live.add_expected("eventBuilder-0*backEnd+NumTriggerRequestsReceived",
                          0, Prio.ITS)
        live.add_expected("eventBuilder-0*backEnd+NumReadoutsReceived",
                          0, Prio.ITS)
        live.add_expected("eventBuilder-0*backEnd+NumEventsSent",
                          0, Prio.ITS)
        live.add_expected("eventBuilder-0*backEnd+NumEventsDispatched",
                          0, Prio.ITS)
        live.add_expected("eventBuilder-0*backEnd+NumBadEvents",
                          0, Prio.ITS)
        live.add_expected("eventBuilder-0*backEnd+DiskAvailable",
                          2560, Prio.ITS)
        live.add_expected("eventBuilder-0*backEnd+NumBytesWritten",
                          0, Prio.ITS)

        live.add_expected("secondaryBuilders-0*moniBuilder+NumDispatchedData",
                          0, Prio.ITS)
        live.add_expected("secondaryBuilders-0*snBuilder+NumDispatchedData",
                          0, Prio.ITS)
        live.add_expected("secondaryBuilders-0*snBuilder+DiskAvailable",
                          0, Prio.ITS)

        # add activeDOM data
        live.add_expected("missingDOMs", 1, Prio.ITS)
        lbmo_dict = {
            "count": 20,
            "runNumber": 123456,
        }
        if first:
            lbmo_dict["early_lbm"] = True
            match = True
        else:
            lbmo_dict["early_lbm"] = False
            lbmo_dict["recordingStartTime"] = "???"
            lbmo_dict["recordingStopTime"] = "???"
            match = False
        live.add_expected("LBMOcount", lbmo_dict, Prio.ITS, match)

        dom_dict = {
            "expectedDOMs": 2,
            "activeDOMs": 1,
            "missingDOMs": 1,
        }
        live.add_expected("dom_update", dom_dict, Prio.ITS)

    def setUp(self):
        self.__first_time = True
        ActiveDOMThread.reset()

    def tearDown(self):
        self.__first_time = False

    def test_not_run(self):
        "Test what happens when the tasks are never run"
        comp_list = [MockTMComponent("stringHub", 1),
                     MockTMComponent("stringHub", 6),
                     MockTMComponent("inIceTrigger", 0),
                     MockTMComponent("iceTopTrigger", 0),
                     MockTMComponent("globalTrigger", 0),
                     MockTMComponent("eventBuilder", 0),
                     MockTMComponent("secondaryBuilders", 0)]

        order_num = 1
        for comp in comp_list:
            comp.order = order_num

        runset = MockRunSet(comp_list)

        dashlog = MockLogger("dashlog")

        live = MockLiveMoni()

        run_cfg = MockRunConfig()

        rst = MyTaskManager(runset, dashlog, live, None, run_cfg,
                            RunOption.MONI_TO_LIVE)
        rst.start()

        for _ in range(20):
            wait_for_thread = False
            for comp in comp_list:
                if not comp.was_updated():
                    wait_for_thread = True
                if not live.sent_all_moni:
                    wait_for_thread = True

            if not wait_for_thread:
                break

            time.sleep(0.1)

        runset.stop_mock()
        rst.stop()

        for comp in comp_list:
            self.assertFalse(comp.was_updated(), "Rate thread was updated")
        self.assertTrue(live.sent_all_moni, "Monitoring data was not sent")

    def test_run_once(self):
        "Test what happens when the tasks are run once"
        comp_list = [MockTMComponent("stringHub", 1),
                     MockTMComponent("inIceTrigger", 0),
                     MockTMComponent("iceTopTrigger", 0),
                     MockTMComponent("globalTrigger", 0),
                     MockTMComponent("eventBuilder", 0),
                     MockTMComponent("secondaryBuilders", 0)]

        order_num = 1
        for comp in comp_list:
            comp.order = order_num

        runset = MockRunSet(comp_list)
        runset.start_mock()

        dashlog = MockLogger("dashlog")

        live = MockLiveMoni()

        run_cfg = MockRunConfig()

        self.__load_expected(live)

        rst = MyTaskManager(runset, dashlog, live, None, run_cfg,
                            RunOption.MONI_TO_LIVE)

        dashlog.add_expected_exact("\t%d physics events (%.2f Hz),"
                                   " %d moni events, %d SN events, %d tcals" %
                                   runset.rates)

        rst.trigger_timers()
        rst.start()

        for _ in range(20):
            wait_for_thread = False
            for comp in comp_list:
                if not comp.was_updated():
                    wait_for_thread = True
                if not live.sent_all_moni:
                    wait_for_thread = True

            if not wait_for_thread:
                break

            time.sleep(0.1)

        for comp in comp_list:
            self.assertTrue(comp.was_updated(), "Rate thread was not updated")
        self.assertTrue(live.sent_all_moni, "Monitoring data was not sent")

        runset.stop_mock()
        rst.stop()

    def test_run_twice(self):
        "Test what happens when the tasks are run twice"
        comp_list = [MockTMComponent("stringHub", 1),
                     MockTMComponent("inIceTrigger", 0),
                     MockTMComponent("iceTopTrigger", 0),
                     MockTMComponent("globalTrigger", 0),
                     MockTMComponent("eventBuilder", 0),
                     MockTMComponent("secondaryBuilders", 0)]

        order_num = 1
        for comp in comp_list:
            comp.order = order_num

        runset = MockRunSet(comp_list)
        runset.start_mock()

        dashlog = MockLogger("dashlog")

        live = MockLiveMoni()

        run_cfg = MockRunConfig()

        rst = MyTaskManager(runset, dashlog, live, None, run_cfg,
                            RunOption.MONI_TO_LIVE)

        self.__load_expected(live)

        dashlog.add_expected_exact("\t%d physics events (%.2f Hz),"
                                   " %d moni events, %d SN events, %d tcals" %
                                   runset.rates)

        rst.trigger_timers()

        rst.start()

        for _ in range(20):
            wait_for_thread = False
            for comp in comp_list:
                if not comp.was_updated():
                    wait_for_thread = True
                if not live.sent_all_moni:
                    wait_for_thread = True

            if not wait_for_thread:
                break

            time.sleep(0.1)

        self.assertTrue(live.sent_all_moni, "Monitoring data was not sent")

        self.__load_expected(live, first=False)
        dashlog.add_expected_exact("Watchdog reports threshold components:\n"
                                   "    secondaryBuilders"
                                   " snBuilder.DiskAvailable below 1024"
                                   " (value=0)")
        dashlog.add_expected_exact("Run is unhealthy (%d checks left)" %
                                   (WatchdogTask.HEALTH_METER_FULL - 1))
        dashlog.add_expected_exact("\t%d physics events (%.2f Hz),"
                                   " %d moni events, %d SN events, %d tcals" %
                                   runset.rates)

        rst.trigger_timers()

        for _ in range(20):
            wait_for_thread = False
            for comp in comp_list:
                if not comp.was_updated():
                    wait_for_thread = True
                if not live.sent_all_moni:
                    wait_for_thread = True

            if not wait_for_thread:
                break

            time.sleep(0.1)

        for comp in comp_list:
            self.assertTrue(comp.was_updated(), "Rate thread was not updated")
        self.assertTrue(live.sent_all_moni, "Monitoring data was not sent")

        runset.stop_mock()
        rst.stop()


if __name__ == '__main__':
    unittest.main()
