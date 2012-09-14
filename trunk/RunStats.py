#!/usr/bin/env python

from DAQTime import PayloadTime
from RateCalc import RateCalc


class RunStats(object):
    def __init__(self):
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
        return (self.__numEvts, self.__evtTime, self.__evtPayTime,
                self.__numMoni, self.__moniTime,
                self.__numSN, self.__snTime,
                self.__numTcal, self.__tcalTime)

    def rate(self):
        return self.__physicsRate.rate()

    def rateEntries(self):
        return self.__physicsRate.entries

    def start(self):
        "Initialize statistics for the current run"
        pass

    def updateEventCounts(self, evtData, addRate=False):
        "Gather run statistics"
        if evtData is None:
            return None

        (numEvts, evtTime, firstPayTime, evtPayTime,
         numMoni, moniTime, numSN, snTime, numTcal, tcalTime) = evtData

        if addRate and  self.__startPayTime is None and firstPayTime > 0:
            self.__startPayTime = firstPayTime
            self.__addRate(self.__startPayTime, 1)

        if numEvts >= 0 and evtPayTime > 0:
            (self.__numEvts, self.__evtTime, self.__evtPayTime,
             self.__numMoni, self.__moniTime,
             self.__numSN, self.__snTime,
             self.__numTcal, self.__tcalTime) = \
             (numEvts, evtTime, evtPayTime,
              numMoni, moniTime,
              numSN, snTime,
              numTcal, tcalTime)

            if addRate:
                self.__addRate(self.__evtPayTime, self.__numEvts)

        return (self.__numEvts, self.__numMoni, self.__numSN, self.__numTcal,
                self.__startPayTime, self.__evtPayTime)
