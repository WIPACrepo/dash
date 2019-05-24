#!/usr/bin/env python

import datetime

from CnCSingleThreadTask import CnCSingleThreadTask
from CnCThread import CnCThread
from CompOp import ComponentGroup, OpGetMultiBeanFields
from LiveImports import Prio
from decorators import classproperty


from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class ActiveDOMThread(CnCThread):
    "A thread which reports the active DOM counts"

    PREV_ACTIVE = {}
    PREV_COUNT = None

    KEY_ACT_TOT = "NumberOfActiveAndTotalChannels"
    KEY_LBM_OVER = "TotalLBMOverflows"

    KEY_ACTIVE = "active_doms"
    KEY_TOTAL = "total_doms"

    def __init__(self, runset, dashlog, live_moni, lbm_start_time=None,
                 send_details=False):
        self.__runset = runset
        self.__dashlog = dashlog
        self.__live_moni_client = live_moni
        self.__lbm_start_time = lbm_start_time
        self.__send_details = send_details

        super(ActiveDOMThread, self).__init__("CnCServer:ActiveDOMThread",
                                              dashlog)

    @classmethod
    def __get_previous_doms(cls, hub_num):
        tmp_active = 0
        tmp_total = 0
        if hub_num in cls.PREV_ACTIVE and \
           cls.KEY_ACT_TOT in cls.PREV_ACTIVE[hub_num]:
            prevpair = cls.PREV_ACTIVE[hub_num][cls.KEY_ACT_TOT]
            if len(prevpair) == 2:
                try:
                    tmp_active = int(prevpair[0])
                    tmp_total = int(prevpair[1])
                except:
                    tmp_active = 0
                    tmp_total = 0
        return (tmp_active, tmp_total)

    @classmethod
    def __get_previous_entry(cls, hub_num):
        if hub_num in cls.PREV_ACTIVE:
            return cls.PREV_ACTIVE[hub_num]
        return None

    @classmethod
    def __get_previous_lbm(cls, hub_num):
        if hub_num in cls.PREV_ACTIVE and \
           cls.KEY_LBM_OVER in cls.PREV_ACTIVE[hub_num]:
            return cls.PREV_ACTIVE[hub_num][cls.KEY_LBM_OVER]

        return None

    def __got_data(self, totals):
        if len(totals) == 0:
            return False
        if self.KEY_ACTIVE not in totals or self.KEY_TOTAL not in totals:
            return False
        if totals[self.KEY_ACTIVE] == 0 and totals[self.KEY_TOTAL] == 0:
            return False
        return True

    def __process_result(self, comp, result, totals, lbm_overflows):
        try:
            hub_active_doms = int(result[self.KEY_ACT_TOT][0])
            hub_total_doms = int(result[self.KEY_ACT_TOT][1])
        except:
            self.__dashlog.error("Cannot get # active DOMS from %s string:"
                                 " %s" % (comp.fullname, exc_string()))
            (hub_active_doms, hub_total_doms) \
                = self.__get_previous_doms(comp.num)

        totals[self.KEY_ACTIVE] += hub_active_doms
        totals[self.KEY_TOTAL] += hub_total_doms

        if self.KEY_LBM_OVER in result:
            hub_lbm_overflows = result[self.KEY_LBM_OVER]
        else:
            hub_lbm_overflows = self.__get_previous_lbm(comp.num)
            if hub_lbm_overflows is None:
                self.__dashlog.error("No LBM overflows in result %s<%s>" %
                                     (result, type(result)))
                hub_lbm_overflows = 0

        lbm_overflows[str(comp.num)] = hub_lbm_overflows

        # cache current results
        #
        self.__set_previous(comp.num, hub_active_doms, hub_total_doms,
                            hub_lbm_overflows)
    def _run(self):
        # build a list of hubs
        src_set = []
        for comp in self.__runset.components():
            if comp.is_source:
                src_set.append(comp)

        # save the current time
        start_time = datetime.datetime.now()

        # spawn a bunch of threads to fetch hub data
        bean_keys = (self.KEY_ACT_TOT, self.KEY_LBM_OVER)
        results = ComponentGroup.run_simple(OpGetMultiBeanFields, src_set,
                                            ("stringhub", bean_keys),
                                            self.__dashlog)

        # create dictionaries used to accumulate results
        totals = {
            self.KEY_ACTIVE: 0, self.KEY_TOTAL: 0,
        }
        lbm_overflows = {}

        hanging = []
        for comp in src_set:
            if comp not in results:
                result = None
            else:
                result = results[comp]
                if result == ComponentGroup.RESULT_HANGING:
                    hanging.append(comp.fullname)
                    result = None
                elif result == ComponentGroup.RESULT_ERROR:
                    result = None

            if result is None:
                # use previous datapoint
                result = self.__get_previous_entry(comp.num)
                if result is None:
                    # if no previous data for this component, skip it
                    continue

            # 'result' should now contain a dictionary with the number of
            # active and total channels and the LBM overflows

            self.__process_result(comp, result, totals, lbm_overflows)

        # report hanging components
        if len(hanging) > 0:
            errmsg = "Cannot get %s bean data from hanging components (%s)" % \
                     (ActiveDOMsTask.name, hanging)
            self.__dashlog.error(errmsg)

        # if the run isn't stopped and we have data from one or more hubs...
        if not self.isClosed and self.__got_data(totals) > 0:

            # active doms should be reported over ITS once every ten minutes
            # and over email once a minute.  The two should not overlap

            # priority for standard messages
            if not self.__send_details:
                # messages that go out every minute use lower priority
                prio = Prio.EMAIL
            else:
                # use higher priority every 10 minutes to keep North updated
                prio = Prio.ITS

            active_doms = totals[self.KEY_ACTIVE]
            total_doms = totals[self.KEY_TOTAL]
            missing_doms = total_doms - active_doms

            dom_update = {
                "activeDOMs": active_doms,
                "expectedDOMs": total_doms,
                "missingDOMs": missing_doms,
            }
            self.__send_moni("dom_update", dom_update, prio)

            self.__send_moni("missingDOMs", missing_doms, prio)

            # send LBM overflow count every minute
            self.__send_lbm_overflow(lbm_overflows, start_time,
                                     self.__runset.run_number())
            if self.__send_details:
                # important messages that go out every ten minutes
                pass


    def __send_lbm_overflow(self, lbmo_dict, start_time, run_number):
        # get the total LBM overflow count
        count = 0
        for hub_count in lbmo_dict.values():
            count += hub_count

        # replace the previous LBM count with the new count
        prev_count = self.__update_lbm_count(count)

        # sanity-check the LBM count
        if prev_count is None:
            prev_count = 0
        if prev_count > count:
            self.__dashlog.error("WARNING: Total LBM count decreased from"
                                 " %s to %s" % (prev_count, count))

        msg_dict = {}
        if self.__lbm_start_time is None:
            msg_dict["early_lbm"] = True
        else:
            msg_dict["early_lbm"] = False
            msg_dict["recordingStartTime"] = str(self.__lbm_start_time)
            msg_dict["recordingStopTime"] = str(start_time)

        msg_dict["runNumber"] = run_number
        msg_dict["count"] = count - prev_count

        self.__send_moni("LBMOcount", msg_dict, Prio.ITS)

        # save start time for current bin
        self.__lbm_start_time = start_time

    def __send_moni(self, name, value, prio):
        self.__live_moni_client.sendMoni(name, value, prio)

    @classmethod
    def __set_previous(cls, hub_num, hub_active_doms, hub_total_doms,
                       hub_lbm_overflows):
        cls.PREV_ACTIVE[hub_num] = {
            cls.KEY_ACT_TOT: (hub_active_doms, hub_total_doms),
            cls.KEY_LBM_OVER: hub_lbm_overflows,
        }

    @classmethod
    def __update_lbm_count(cls, new_count):
        prev_count = cls.PREV_COUNT
        cls.PREV_COUNT = new_count
        return prev_count

    def get_new_thread(self, send_details=False):
        "Create a new copy of this thread"
        thrd = ActiveDOMThread(self.__runset, self.__dashlog,
                               self.__live_moni_client, self.__lbm_start_time,
                               send_details)
        return thrd

    @classmethod
    def reset(cls):
        "This is used by unit tests to reset the cached values"
        cls.PREV_ACTIVE.clear()
        cls.PREV_COUNT = None


class ActiveDOMsTask(CnCSingleThreadTask):
    """
    Essentially a timer, so every REPORT_PERIOD an ActiveDOMsThread is created
    and run.  This sends three chunks of information off to live:

    'totalDOMS' which is a count of the total number of active doms
    in the array along with a count of the number of doms (active or inactive).

    'LBMOverflows' which is a dictionary relating string number to the total
    number of lbm overflows for a given string
    """
    __NAME = "ActiveDOMs"
    __PERIOD = 60

    # active DOM periodic report timer
    REPORT_NAME = "ActiveReport"
    REPORT_PERIOD = 600

    def create_detail_timer(self, task_mgr):
        return task_mgr.createIntervalTimer(self.REPORT_NAME,
                                            self.REPORT_PERIOD)

    def initialize_thread(self, runset, dashlog, live_moni):
        return ActiveDOMThread(runset, dashlog, live_moni)

    @classproperty
    def name(cls):
        "Name of this task"
        return cls.__NAME

    @classproperty
    def period(cls):
        "Number of seconds between tasks"
        return cls.__PERIOD

    def task_failed(self):
        self.log_error("ERROR: %s thread seems to be stuck,"
                       " monitoring will not be done" % self.name)
