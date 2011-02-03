#!/usr/bin/env python

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

    def getRate(self):
        return self.__comp.getSingleBeanField(self.__beanName, "HitRate")

    def mbID(self): return self.__mbID

class RadarThread(CnCThread):
    "A thread which reports the hit rate for all radar sentinel DOMs"

    # mapping of DOM mainboard ID -> string number
    DOM_MAP = { "48e492170268": 6 }

    # generated list of radar sentinel DOMs
    RADAR_DOMS = None

    def __init__(self, runset, dashlog, liveMoni, samples, duration):
        self.__comps = runset.components()
        self.__dashlog = dashlog
        self.__liveMoniClient = liveMoni
        self.__samples = samples
        self.__sampleSleep = float(duration) / float(samples)

        super(RadarThread, self).__init__("CnCServer:RadarThread",
                                              dashlog)

    def __findDOMs(self):
        strings = {}
        for k in self.DOM_MAP.keys():
            if not strings.has_key(self.DOM_MAP[k]):
                strings[self.DOM_MAP[k]] = []
            strings[self.DOM_MAP[k]].append(k)

        self.RADAR_DOMS = []

        for n in strings.keys():
            for c in self.__comps:
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

                        self.RADAR_DOMS.append(RadarDOM(mbid, n, c, b))

    def _run(self):
        if self.RADAR_DOMS is None:
            self.__findDOMs()

        if len(self.RADAR_DOMS) == 0:
            return

        rateList = {}
        for i in range(self.__samples):
            for rdom in self.RADAR_DOMS:
                rate = rdom.getRate()

                if not rateList.has_key(rdom.mbID()) or \
                        rateList[rdom.mbID()] < rate:
                    rateList[rdom.mbID()] = rate

        rateData = []
        for mbID in rateList:
            rateData.append((mbID, rateList[mbID]))

        if not self.__liveMoniClient.sendMoni("radarDOMs", rateData,
                                              Prio.EMAIL):
            self.__dashlog.error("Failed to send radar DOM report")

class RadarTask(CnCTask):
    NAME = "Radar"
    PERIOD = 900
    DEBUG_BIT = RunSetDebug.RADAR_TASK

    # number of samples per radar check
    RADAR_SAMPLES    = 8

    # number of seconds for sampling
    RADAR_SAMPLE_DURATION = 120

    def __init__(self, taskMgr, runset, dashlog, liveMoni,
                 samples=RADAR_SAMPLES, duration=RADAR_SAMPLE_DURATION,
                 period=None):
        self.__runset = runset
        self.__liveMoniClient = liveMoni
        self.__samples = samples
        self.__duration = duration

        self.__thread = None
        self.__badCount = 0

        if self.__liveMoniClient is None:
            name = None
            period = None
        else:
            name = self.NAME
            if period is None: period = self.PERIOD

        super(RadarTask, self).__init__("Radar", taskMgr, dashlog,
                                        self.DEBUG_BIT, name, period)

    def _check(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is None or not self.__thread.isAlive():
            self.__badCount = 0
            self.__thread = \
                RadarThread(self.__runset, self.logger(),
                            self.__liveMoniClient, self.__samples,
                            self.__duration)
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
        self.__thread = None
        self.__badCount = 0

    def close(self):
        pass

    def waitUntilFinished(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.join()
