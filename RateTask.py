#!/usr/bin/env python

from CnCTask import CnCTask
from CnCThread import CnCThread
from RunSetDebug import RunSetDebug


class RateThread(CnCThread):
    "A thread which reports the current event rates"
    def __init__(self, runset, dashlog):
        self.__runset = runset
        self.__dashlog = dashlog

        super(RateThread, self).__init__("CnCServer:RateThread", dashlog)

    def _run(self):
        rates = self.__runset.updateRates()
        if rates is not None:
            (numEvts, rate, numMoni, numSN, numTcal) = rates
            if not self.isClosed():
                rateStr = ""
                if rate == 0.0:
                    rateStr = ""
                else:
                    rateStr = " (%2.2f Hz)" % rate

                self.__dashlog.error(("\t%s physics events%s, %s moni events," +
                                      " %s SN events, %s tcals")  %
                                     (numEvts, rateStr, numMoni, numSN,
                                      numTcal))

    def getNewThread(self):
        thrd = RateThread(self.__runset, self.__dashlog)
        return thrd


class RateTask(CnCTask):
    NAME = "Rate"
    PERIOD = 60
    DEBUG_BIT = RunSetDebug.RATE_TASK

    def __init__(self, taskMgr, runset, dashlog, period=None):
        self.__runset = runset

        self.__thread = RateThread(runset, dashlog)
        self.__badCount = 0

        if period is None:
            period = self.PERIOD

        super(RateTask, self).__init__("Rate", taskMgr, dashlog,
                                       self.DEBUG_BIT, self.NAME, period)

    def _check(self):
        if self.__thread is None or not self.__thread.isAlive():
            self.__badCount = 0

            self.__thread = self.__thread.getNewThread()
            self.__thread.start()
        else:
            self.__badCount += 1
            if self.__badCount <= 3:
                self.logError("WARNING: Rate thread is hanging (#%d)" %
                              self.__badCount)
            else:
                self.logError("ERROR: Rate calculation seems to be stuck," +
                              " stopping run")
                self.__runset.setError()

    def _reset(self):
        self.__badCount = 0

    def close(self):
        if self.__thread is not None:
            self.__thread.close()

    def waitUntilFinished(self):
        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.join()
