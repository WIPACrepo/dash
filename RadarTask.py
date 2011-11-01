#!/usr/bin/env python

import time

from CnCTask import CnCTask
from CnCThread import CnCThread
from LiveImports import Prio
from RunSetDebug import RunSetDebug


class RadarDOM(object):
    def __init__(self, mbID, string, comp, beanName):
        self.__mbID = mbID
        self.__string = string
        self.__comp = comp
        self.__beanName = beanName

    def __str__(self):
        return "%s@hub#%s" % (self.__mbID, self.__string)

    def getRate(self):
        return self.__comp.getSingleBeanField(self.__beanName, "HitRate")

    def mbID(self):
        return self.__mbID


class RadarThread(CnCThread):
    "A thread which reports the hit rate for all radar sentinel DOMs"

    # mapping of DOM mainboard ID -> string number
    DOM_MAP = {"48e492170268": 6}

    def __init__(self, runset, dashlog, liveMoni, samples, duration,
                 radarDOMs=None):
        self.__runset = runset
        self.__dashlog = dashlog
        self.__liveMoniClient = liveMoni
        self.__samples = samples
        self.__duration = duration
        self.__sampleSleep = float(duration) / float(samples)
        self.__radarDOMs = radarDOMs

        super(RadarThread, self).__init__("CnCServer:RadarThread",
                                              dashlog)

    def __findDOMs(self):
        strings = {}
        for k in self.DOM_MAP.keys():
            if not self.DOM_MAP[k] in strings:
                strings[self.DOM_MAP[k]] = []
            strings[self.DOM_MAP[k]].append(k)

        radarDOMs = []

        for n in strings.keys():
            for c in self.__runset.components():
                if len(strings[n]) == 0:
                    break

                if c.name() != "stringHub" or (c.num() % 1000) != n:
                    continue

                beans = c.getBeanNames()
                for b in beans:
                    if len(strings[n]) == 0:
                        break

                    if b.startswith("DataCollectorMonitor"):
                        mbid = c.getSingleBeanField(b, "MainboardId")
                        try:
                            idx = strings[n].index(mbid)
                        except:
                            continue

                        del strings[n][idx]

                        radarDOMs.append(RadarDOM(mbid, n, c, b))

        return radarDOMs

    def _run(self):
        if self.__liveMoniClient is None:
            return

        if self.__radarDOMs is None:
            self.__radarDOMs = self.__findDOMs()

        if len(self.__radarDOMs) == 0:
            return

        rateList = {}
        for i in range(self.__samples):
            for rdom in self.__radarDOMs:
                rate = rdom.getRate()

                if not rdom.mbID() in rateList or \
                        rateList[rdom.mbID()] < rate:
                    rateList[rdom.mbID()] = rate

            time.sleep(self.__sampleSleep)

        if not self.isClosed():
            rateData = []
            for mbID in rateList:
                rateData.append((mbID, rateList[mbID]))

            if not self.__liveMoniClient.sendMoni("radarDOMs", rateData,
                                                  Prio.EMAIL):
                self.__dashlog.error("Failed to send radar DOM report")

    def getNewThread(self):
        thrd = RadarThread(self.__runset, self.__dashlog,
                           self.__liveMoniClient, self.__samples,
                           self.__duration, self.__radarDOMs)
        return thrd

    def reset(self):
        self.__radarDOMs = None


class RadarTask(CnCTask):
    NAME = "Radar"
    PERIOD = 900
    DEBUG_BIT = RunSetDebug.RADAR_TASK

    # number of samples per radar check
    RADAR_SAMPLES = 8

    # number of seconds for sampling
    RADAR_SAMPLE_DURATION = 120

    def __init__(self, taskMgr, runset, dashlog, liveMoni,
                 samples=RADAR_SAMPLES, duration=RADAR_SAMPLE_DURATION,
                 period=None):
        self.__runset = runset
        self.__liveMoniClient = liveMoni
        self.__samples = samples
        self.__duration = duration

        self.__thread = RadarThread(runset, dashlog, liveMoni, samples,
                                    duration)
        self.__badCount = 0

        if self.__liveMoniClient is None:
            name = None
            period = None
        else:
            name = self.NAME
            if period is None:
                period = self.PERIOD

        super(RadarTask, self).__init__("Radar", taskMgr, dashlog,
                                        self.DEBUG_BIT, name, period)

    def _check(self):
        if self.__liveMoniClient is None:
            return

        if not self.__thread.isAlive():
            self.__badCount = 0
            thrd = self.__thread.getNewThread()
            if thrd is not None:
                self.__thread = thrd
                self.__thread.start()
        else:
            self.__badCount += 1
            if self.__badCount <= 3:
                self.logError("WARNING: Radar thread is hanging (#%d)" %
                              self.__badCount)
            else:
                self.logError("ERROR: Radar monitoring seems to be stuck," +
                              " monitoring will not be done")
                self.endTimer()

    def _reset(self):
        self.__badCount = 0
        self.__thread.reset()

    def close(self):
        self.__thread.close()

    def waitUntilFinished(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread.isAlive():
            self.__thread.join()
