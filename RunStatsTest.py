#!/usr/bin/env python

import unittest
from DAQTime import PayloadTime
from RateCalc import dt, RateCalcEntry
from RunStats import RunStats
from locate_pdaq import set_pdaq_config_dir


class TestRunStats(unittest.TestCase):
    EMPTY_DICT = {
        "events": 0, "eventsTime": None, "evtPayTime": None,
        "moni": 0, "moniTime": None,
        "sn": 0, "snTime": None,
        "tcal": 0, "tcalTime": None,
        "startTime": None,
    }

    CURRENT_FIELDS = ("eventsTime", "events", "moni", "sn", "tcal")
    MONITOR_FIELDS = ("events", "eventsTime", "evtPayTime", "moni", "moniTime",
                      "sn", "snTime", "tcal", "tcalTime")
    STOP_FIELDS = ("events", "moni", "sn", "tcal", "startTime", "evtPayTime")
    UPDATE_FIELDS = ("events", "eventsTime", "startTime", "evtPayTime",
                     "moni", "moniTime", "sn", "snTime", "tcal", "tcalTime")

    def __buildDataList(self, expData, flds, current=False):
        dataList = []
        for f in flds:
            if f == "evtDate":
                if current:
                    val = PayloadTime.toDateTime(expData["eventsTime"])
                else:
                    val = PayloadTime.toDateTime(expData["evtPayTime"])
            else:
                val = expData[f]
            dataList.append((f, val))
        return dataList

    def __checkStats(self, rs, expData, expRate, expEntries):
        curData = rs.currentData()
        expCur = self.__buildDataList(expData, self.CURRENT_FIELDS,
                                      current=True)
        self.__checkValues("currentData", expCur, curData)

        monData = rs.monitorData()
        expMoni = self.__buildDataList(expData, self.MONITOR_FIELDS,
                                       current=False)
        self.__checkValues("monitorData", expMoni, monData)

        rval = rs.rate()
        self.assertEqual(expRate, rval,
                         "Expected rate %s, not %s" % (expRate, rval))

        ent = rs.rateEntries()
        self.assertTrue(isinstance(ent, type(expEntries)),
                        "Expected entry %s, not %s" %
                        (type(expEntries), type(ent)))
        self.assertEqual(len(ent), len(expEntries),
                         ("rateEntries() should return %d entries (%s)," +
                          " not %d (%s)") %
                         (len(expEntries), expEntries, len(ent), ent))
        for idx in xrange(len(ent)):
            self.assertEqual(expEntries[idx], ent[idx],
                             "Rate entry #%d should be %s, not %s" %
                             (idx, expEntries[idx], ent[idx]))

        rstr = str(rs)
        expStr = "Stats[e%s m%s s%s t%s]" % (expData["events"],
                                             expData["moni"],
                                             expData["sn"],
                                             expData["tcal"])
        self.assertEqual(expStr, rstr, "Expected \"%s\", not \"%s\"" %
                         (expStr, rstr))

    def __checkUpdate(self, rs, upDict, upRate, upEntries, addRate):
        upData = []
        for f in self.UPDATE_FIELDS:
            upData.append(upDict[f])
        rtnData = rs.updateEventCounts(upData, addRate=addRate)

        upFlds = []
        for idx in xrange(len(self.STOP_FIELDS)):
            upFlds.append((self.STOP_FIELDS[idx],
                           upDict[self.STOP_FIELDS[idx]]))
        self.__checkValues("updateData", upFlds, rtnData)

        self.__checkStats(rs, upDict, upRate, upEntries)

    def __checkValues(self, methodName, flds, vals):
        self.assertEqual(len(vals), len(flds),
                         "Expected %d stop() values for %s, not %d" %
                         (len(flds), methodName, len(vals)))

        idx = 0
        for nm, val in flds:
            self.assertEqual(type(val), type(vals[idx]),
                             "Expected %s %s %s (%s), not %s (%s)" %
                             (methodName, nm, val, type(val),
                              vals[idx], type(vals[idx])))
            self.assertEqual(val, vals[idx],
                             "Expected %s %s %s, not %s" %
                             (methodName, nm, val, vals[idx]))
            idx += 1

    def __calcRate(self, rateList, interval=300.0):
        latest = None
        for idx in xrange(len(rateList) - 1, -1, -1):
            entry = rateList[idx]
            if latest is None:
                latest = entry
            else:
                dtsec = dt(entry[0], latest[0])
                if dtsec > interval:
                    break
        if latest is None or dtsec == 0.0:
            return 0.0
        return float(latest[1] - entry[1]) / float(dtsec)

    def setUp(self):
        set_pdaq_config_dir(None, override=True)

    def tearDown(self):
        set_pdaq_config_dir(None, override=True)

    def testImmediateStop(self):
        rs = RunStats()

        rateEmpty = 0
        entriesEmpty = []

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

        noEvtData = (None, None, None, None, None, None, None, None, None,
                     None)
        evtTup = rs.updateEventCounts(noEvtData)

        stopFlds = self.__buildDataList(self.EMPTY_DICT, self.STOP_FIELDS,
                                        current=False)
        self.__checkValues("stopData", stopFlds, evtTup)

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

        rs.clear()

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

    def testStartStop(self):
        rs = RunStats()

        rateEmpty = 0
        entriesEmpty = []

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

        rs.start()

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

        noEvtData = (None, None, None, None, None, None, None, None, None,
                     None)
        evtTup = rs.updateEventCounts(noEvtData)

        stopFlds = self.__buildDataList(self.EMPTY_DICT, self.STOP_FIELDS,
                                        current=False)
        self.__checkValues("stopData", stopFlds, evtTup)

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

    def testUpdate(self):
        set_pdaq_config_dir("src/test/resources/config", override=True)

        rs = RunStats()

        rateEmpty = 0
        entriesEmpty = []

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

        rs.start()

        self.__checkStats(rs, self.EMPTY_DICT, rateEmpty, entriesEmpty)

        valInc = 56
        timeInc = 10000000000L

        upDict = {
            "events": 56, "eventsTime": 123456789L,
            "moni": 17, "moniTime": 123459876L,
            "sn": 111, "snTime": 123456666L,
            "tcal": 454, "tcalTime": 123459999L,
            "startTime": None, "evtPayTime": 123456890L,
        }

        rateList = []
        for i in xrange(5):
            for f in ("events", "moni", "sn", "tcal"):
                upDict[f] += valInc
                upDict[f + "Time"] += timeInc
            upDict["evtPayTime"] += timeInc

            if i < 1:
                upRate = 0
                upEntries = []
            else:
                startTime = 123455789L
                if len(rateList) == 0:
                    rateList.append((PayloadTime.toDateTime(startTime), 1))
                rateList.append((PayloadTime.toDateTime(upDict["evtPayTime"]),
                                 upDict["events"]))
                upRate = self.__calcRate(rateList)
                upDict["startTime"] = startTime
                upEntries = []
                for tup in rateList:
                    upEntries.append(RateCalcEntry(tup[0], tup[1]))

            self.__checkUpdate(rs, upDict, upRate, upEntries, addRate=(i > 0))

        noEvtData = (None, None, None, None, None, None, None, None, None,
                     None)
        evtTup = rs.updateEventCounts(noEvtData)

        stopFlds = self.__buildDataList(upDict, self.STOP_FIELDS,
                                        current=False)
        self.__checkValues("stopData", stopFlds, evtTup)

        self.__checkStats(rs, upDict, upRate, upEntries)

if __name__ == '__main__':
    unittest.main()
