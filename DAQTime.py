#!/usr/bin/env python

import datetime
import time


class PayloadTime(object):
    # number of seconds in 11 months
    ELEVEN_MONTHS = 60 * 60 * 24 * (365 - 31)

    # offset from epoch to start of year
    TIME_OFFSET = None

    # previous payload time
    PREV_TIME = None

    @staticmethod
    def toDateTime(payTime):
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
