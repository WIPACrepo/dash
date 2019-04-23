#!/usr/bin/env python
"Track and report the event rate"

from CnCSingleThreadTask import CnCSingleThreadTask
from CnCThread import CnCThread
from decorators import classproperty


class RateThread(CnCThread):
    "A thread which reports the current event rates"
    def __init__(self, runset, dashlog):
        self.__runset = runset
        self.__dashlog = dashlog

        super(RateThread, self).__init__("CnCServer:RateThread", dashlog)

    def _run(self):
        if self.__runset.id is None:
            raise Exception("Runset has been destroyed")
        rates = self.__runset.update_rates()
        if rates is not None:
            (num_evts, rate, num_moni, num_sn, num_tcal) = rates
            if not self.isClosed:
                ratestr = ""
                if rate == 0.0:
                    ratestr = ""
                else:
                    ratestr = " (%2.2f Hz)" % rate

                self.__dashlog.error("\t%s physics events%s, %s moni events,"
                                     " %s SN events, %s tcals" %
                                     (num_evts, ratestr, num_moni, num_sn,
                                      num_tcal))

    def get_new_thread(self, ignored=True):
        "Create a new copy of this thread"
        thrd = RateThread(self.__runset, self.__dashlog)
        return thrd


class RateTask(CnCSingleThreadTask):
    "Track and report the event rate"

    __NAME = "Rate"
    __PERIOD = 60

    def __init__(self, task_mgr, runset, dashlog, live_moni=None, period=None,
                 need_live_moni=False):
        super(RateTask, self).__init__(task_mgr, runset, dashlog,
                                       live_moni=live_moni, period=period,
                                       need_live_moni=need_live_moni)

    def initialize_thread(self, runset, dashlog, live_moni):
        return RateThread(runset, dashlog)

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
                       " stopping run" % self.name)
        self.stop_runset("RateTask")
