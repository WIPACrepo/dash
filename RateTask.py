#!/usr/bin/env python

from CnCSingleThreadTask import CnCSingleThreadTask
from CnCThread import CnCThread
from RunSetDebug import RunSetDebug


class RateThread(CnCThread):
    "A thread which reports the current event rates"
    def __init__(self, runset, dashlog):
        self.__runset = runset
        self.__dashlog = dashlog

        super(RateThread, self).__init__("CnCServer:RateThread", dashlog)

    def _run(self):
        if self.__runset.id is None:
            raise Exception("Runset has been destroyed")
        rates = self.__runset.updateRates()
        if rates is not None:
            (numEvts, rate, numMoni, numSN, numTcal) = rates
            if not self.isClosed:
                rateStr = ""
                if rate == 0.0:
                    rateStr = ""
                else:
                    rateStr = " (%2.2f Hz)" % rate

                self.__dashlog.error(("\t%s physics events%s, %s moni events,"
                                      " %s SN events, %s tcals") % \
                                         (numEvts, rateStr, numMoni, numSN,
                                          numTcal))

    def get_new_thread(self, ignored=True):
        thrd = RateThread(self.__runset, self.__dashlog)
        return thrd


class RateTask(CnCSingleThreadTask):
    NAME = "Rate"
    PERIOD = 60
    DEBUG_BIT = RunSetDebug.RATE_TASK

    def __init__(self, taskMgr, runset, dashlog, liveMoni=None, period=None,
                 needLiveMoni=False):
        super(RateTask, self).__init__(taskMgr, runset, dashlog,
                                       liveMoni=liveMoni, period=period,
                                       needLiveMoni=needLiveMoni)

    def initializeThread(self, runset, dashlog, liveMoni):
        return RateThread(runset, dashlog)

    def taskFailed(self):
        self.logError("ERROR: %s thread seems to be stuck,"
                      " stopping run" % self.NAME)
        self.stopRunset("RateTask")
