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
        self.__runset.updateRates()

class RateTask(CnCTask):
    NAME = "Rate"
    PERIOD = 60
    DEBUG_BIT = RunSetDebug.RATE_TASK

    def __init__(self, taskMgr, runset, dashlog, period=None):
        self.__runset = runset

        self.__thread = None
        self.__badCount = 0

        if period is None: period = self.PERIOD

        super(RateTask, self).__init__("Rate", taskMgr, dashlog,
                                       self.DEBUG_BIT, self.NAME, period)

    def _check(self):
        if self.__thread is None or not self.__thread.isAlive():
            self.__badCount = 0

            self.__thread = RateThread(self.__runset, self.logger())
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
        pass

    def waitUntilFinished(self):
        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.join()
