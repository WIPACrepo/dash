#!/usr/bin/env python

import datetime, time

from RateCalc import RateCalc

class PayloadTime(object):
    # number of seconds in 11 months
    ELEVEN_MONTHS = 60 * 60 * 24 * (365 - 31)

    # offset from epoch to start of year
    TIME_OFFSET = None

    # previous payload time
    PREV_TIME = None

    def toDateTime(cls, payTime):
        if payTime is None:
            return None

        # recompute start-of-year offset?
        recompute = (PayloadTime.PREV_TIME is None or
                     abs(payTime - PayloadTime.PREV_TIME) >
                     PayloadTime.ELEVEN_MONTHS)

        if recompute:
            now = time.gmtime()
            jan1 = time.struct_time((now.tm_year, 1, 1, 0, 0, 0, 0, 0, -1))
            PayloadTime.TIME_OFFSET = time.mktime(jan1)

        PayloadTime.PREV_TIME = payTime

        curTime = PayloadTime.TIME_OFFSET + (payTime / 10000000000.0)
        ts = time.gmtime(curTime)

        return datetime.datetime(ts.tm_year, ts.tm_mon, ts.tm_mday, ts.tm_hour,
                                 ts.tm_min, ts.tm_sec,
                                 int((curTime * 1000000) % 1000000))

    toDateTime = classmethod(toDateTime)

class RunStats(object):
    def __init__(self):
        self.__startPayTime = None
        self.__numEvts = None
        self.__evtTime = None
        self.__evtPayTime = None
        self.__numMoni = None
        self.__moniTime = None
        self.__numSN = None
        self.__snTime = None
        self.__numTcal = None
        self.__tcalTime = None

        # Calculates rate over latest 5min interval
        self.__physicsRate = RateCalc(300.)

    def __str__(self):
        return "Stats[e%s m%s s%s t%s]" % \
            (self.__numEvts, self.__numMoni, self.__numSN, self.__numTcal)

    def __addRate(self, payTime, numEvts):
        dt = PayloadTime.toDateTime(payTime)
        self.__physicsRate.add(dt, numEvts)

    def clear(self):
        "Clear run-related statistics"
        self.__startPayTime = None
        self.__numEvts = 0
        self.__evtTime = None
        self.__evtPayTime = None
        self.__numMoni = 0
        self.__moniTime = None
        self.__numSN = 0
        self.__snTime = None
        self.__numTcal = 0
        self.__tcalTime = None
        self.__physicsRate.reset()

    def currentData(self):
        return (self.__evtTime, self.__numEvts, self.__numMoni, self.__numSN,
                self.__numTcal)

    def monitorData(self):
        evtDT = PayloadTime.toDateTime(self.__evtPayTime)
        return (self.__numEvts, self.__evtTime, evtDT,
                self.__numMoni, self.__moniTime,
                self.__numSN, self.__snTime,
                self.__numTcal, self.__tcalTime)

    def rate(self):
        return self.__physicsRate.rate()

    def rateEntries(self):
        return self.__physicsRate.entries()

    def start(self):
        "Initialize statistics for the current run"
        pass

    def stop(self, evtData):
        "Gather and return end-of-run statistics"
        # get final event counts
        self.updateEventCounts(evtData)

        if self.__startPayTime is None or self.__evtPayTime is None:
            duration = 0
        else:
            duration = (self.__evtPayTime - self.__startPayTime) / 10000000000

        return (self.__numEvts, self.__numMoni, self.__numSN, self.__numTcal,
                duration, self.__evtPayTime)

    def updateEventCounts(self, evtData, addRate=False):
        "Gather run statistics"
        if evtData is not None:
            (self.__numEvts, self.__evtTime,
             firstPayTime, self.__evtPayTime,
             self.__numMoni, self.__moniTime,
             self.__numSN, self.__snTime,
             self.__numTcal, self.__tcalTime) = evtData

            if self.__numEvts > 0:
                if self.__startPayTime is None and firstPayTime > 0:
                    self.__startPayTime = firstPayTime
                    self.__addRate(self.__startPayTime, 1)
                if addRate:
                    self.__addRate(self.__evtPayTime, self.__numEvts)

        return evtData
