#!/usr/bin/env python

from CnCSingleThreadTask import CnCSingleThreadTask
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
            "recordingStopTime": self.__end,
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
                    "Cannot get %s bean data from %s: %s" %
                    (TriggerCountTask.NAME, c.fullName(), exc_string()))
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
                                d["recordingStopTime"], d["value"])

            for d in totals.values():
                self.__sendMoni("trigger_rate", d.moniDict(), prio)

    def getNewThread(self, ignored=True):
        thrd = TriggerCountThread(self.__runset, self.__dashlog,
                                  self.__liveMoniClient)
        return thrd


class TriggerCountTask(CnCSingleThreadTask):
    """
    Every PERIOD seconds, send to I3Live a count of the number of requests
    issues by each trigger algorithm.
    """
    NAME = "TriggerCount"
    PERIOD = 600
    DEBUG_BIT = False

    def __init__(self, taskMgr, runset, dashlog, liveMoni=None, period=None,
                 needLiveMoni=True):
        super(TriggerCountTask, self).__init__(taskMgr, runset, dashlog,
                                               liveMoni, period, needLiveMoni)

    def close(self):
        "Gather on last set of trigger counts after the detector has stopped"
        self.gatherLast()

    def initializeThread(self, runset, dashlog, liveMoni):
        return TriggerCountThread(runset, dashlog, liveMoni)

    def taskFailed(self):
        self.logError("ERROR: %s thread seems to be stuck,"
                      " monitoring will not be done" % self.NAME)
