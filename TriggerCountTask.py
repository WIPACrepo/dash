#!/usr/bin/env python

from CnCTask import CnCTask
from CnCThread import CnCThread
from LiveImports import Prio
from RunSetDebug import RunSetDebug


from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class BinTotal(object):
    "Total counts for each set of bins"
    def __init__(self, srcId, cfgId, trigId, runNum):
        self.__srcId = srcId
        self.__cfgId = cfgId
        self.__trigId = trigId
        self.__runNum = runNum
        self.__start = None
        self.__end = None
        self.__value = 0

    def add(self, startTime, endTime, value):
        if self.__start is None or startTime < self.__start:
            self.__start = startTime
        if self.__end is None or endTime > self.__end:
            self.__end = endTime
        self.__value += value

    def moniDict(self):
        return {
            "runNumber": self.__runNum,
            "sourceid": self.__srcId,
            "configid": self.__cfgId,
            "trigid": self.__trigId,
            "recordingStartTime": self.__start,
            "recordingEndTime": self.__end,
            "value": self.__value
        }


class TriggerCountThread(CnCThread):
    "A thread which reports the trigger counts"

    def __init__(self, runset, dashlog, liveMoni):
        self.__runset = runset
        self.__dashlog = dashlog
        self.__liveMoniClient = liveMoni

        threadName = "CnCServer:TriggerCountThread"
        super(TriggerCountThread, self).__init__(threadName, dashlog)

    def __sendMoni(self, name, value, prio):
        #try:
        self.__liveMoniClient.sendMoni(name, value, prio)
        #except:
        #    self.__dashlog.error("Failed to send %s=%s: %s" %
        #                         (name, value, exc_string()))

    def _run(self):
        cntDicts = None
        for c in self.__runset.components():
            if not c.name().lower().startswith("globaltrigger"):
                continue

            # the counts for all trigger algorithms
            # are returned as a dictionary of values
            try:
                cntDicts = c.getMoniCounts()
            except Exception:
                self.__dashlog.error(
                    "Cannot get TriggerCountTask bean data from %s: %s" %
                    (c.fullName(), exc_string()))
                continue

        if cntDicts is not None and not self.isClosed():

            # messages that go out every minute use should lower priority
            prio = Prio.EMAIL

            totals = {}
            for d in cntDicts:
                key = (d["sourceid"], d["configid"], d["trigid"],
                       d["runNumber"])
                if not totals.has_key(key):
                    totals[key] = BinTotal(key[0], key[1], key[2], key[3])
                totals[key].add(d["recordingStartTime"],
                                d["recordingEndTime"], d["value"])

            for d in totals.values():
                self.__sendMoni("trigger_rate", d.moniDict(), prio)

    def getNewThread(self):
        thrd = TriggerCountThread(self.__runset, self.__dashlog,
                                  self.__liveMoniClient)
        return thrd


class TriggerCountTask(CnCTask):
    """
    Essentially a timer, so every REPORT_PERIOD a TriggerCountThread is
    created and run.  This sends separate reports for each algorithm to live.
    """
    NAME = "TriggerCount"
    PERIOD = 600
    DEBUG_BIT = False

    def __init__(self, taskMgr, runset, dashlog, liveMoni, period=None):
        self.__runset = runset
        self.__liveMoniClient = liveMoni

        self.__thread = TriggerCountThread(runset, dashlog, liveMoni)
        self.__badCount = 0

        if self.__liveMoniClient is None:
            name = None
            period = None
            self.__detailTimer = None
        else:
            name = self.NAME
            if period is None:
                period = self.PERIOD

        super(TriggerCountTask, self).__init__(name, taskMgr, dashlog,
                                               self.DEBUG_BIT, name, period)

    def _check(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is None or not self.__thread.isAlive():
            self.__badCount = 0

            self.__thread = self.__thread.getNewThread()
            self.__thread.start()
        else:
            self.__badCount += 1
            if self.__badCount <= 3:
                self.logError("WARNING: TriggerCount thread is hanging (#%d)" %
                              self.__badCount)
            else:
                self.logError("ERROR: TriggerCount monitoring seems to be" +
                              " stuck, monitoring will not be done")
                self.endTimer()

    def _reset(self):
        self.__detailTimer = None
        self.__badCount = 0

    def close(self):
        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.close()

    def waitUntilFinished(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.join()
