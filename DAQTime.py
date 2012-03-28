#!/usr/bin/env python

import calendar
import datetime
import re
import time


class DAQDateTimeDelta(object):
    def __init__(self, days, seconds, microseconds):
        self.days = days
        self.seconds = seconds
        self.microseconds = microseconds

    def __str__(self):
        rtnstr = "%d day" % self.days
        if self.days != 1:
            rtnstr += "s"
        rtnstr += ", %d:%02d:%02d" % \
            (self.seconds / 3600, (self.seconds / 60) % 60, self.seconds % 60)
        if self.microseconds > 0:
            rtnstr += ".%06d" % self.microseconds
        return rtnstr

class DAQDateTime(object):
    HIGH_PRECISION = False

    def __init__(self, year, month, day, hour, minute, second, daqticks,
                 tzinfo=None, high_precision=False):
        if high_precision:
            self.__daqticks = daqticks
            self.__high_precision = True
        else:
            self.__daqticks = (daqticks / 10000L) * 10000L
            self.__high_precision = False

        self.__dt = datetime.datetime(year, month, day, hour, minute, second,
                                      0, tzinfo)

    def __cmp__(self, other):
        if other is None:
            return -1
        val = cmp(self.__dt, other.__dt)
        if val == 0:
            val = cmp(self.__daqticks, other.__daqticks)
        return val

    def __repr__(self):
        if self.__dt.tzinfo is None:
            tzstr = ""
        else:
            tzstr = ", %s" % repr(self.__dt.tzinfo)
        if not self.__high_precision:
            hpstr = ""
        else:
            hpstr = ", high_precision=True"
        return "DAQDateTime(%d, %d, %d, %d, %d, %d, %d%s%s)" % \
            (self.__dt.year, self.__dt.month, self.__dt.day, self.__dt.hour,
             self.__dt.minute, self.__dt.second, self.__daqticks, tzstr, hpstr)

    def __sub__(self, other):
        delta = self.__dt - other.__dt
        if delta.microseconds > 0:
            print >>sys.stderr, "DELTA USEC %s SHOULD BE ZERO" % \
                delta.microseconds

        days = delta.days
        secs = delta.seconds
        ticks = self.__daqticks - other.__daqticks

        if ticks < 0:
            if secs == 0:
                if days > 0:
                    days -= 1
                    secs += 60 * 60 * 24
            if secs > 0:
                secs -= 1
                ticks += PayloadTime.TICKS_PER_SECOND

        usecs = float(ticks) / 100.0
        return DAQDateTimeDelta(days, secs, usecs)

    def __str__(self):
        if self.__high_precision:
            fmt = "%s.%010d"
            ticks = self.__daqticks
        else:
            fmt = "%s.%06d"
            ticks = self.__daqticks / 10000
        return fmt % (self.__dt, ticks)


class PayloadTime(object):
    # number of seconds in 11 months
    ELEVEN_MONTHS = 60 * 60 * 24 * (365 - 31)

    # offset from epoch to start of year
    TIME_OFFSET = None

    # previous payload time
    PREV_TIME = None

    # regular expression used to parse date/time strings
    TIME_PAT = None

    # number of DAQ ticks in one second
    TICKS_PER_SECOND = 10000000000

    @staticmethod
    def fromString(timestr, high_precision=False):
        if timestr is None:
            return None

        if PayloadTime.TIME_PAT is None:
            PayloadTime.TIME_PAT = re.compile(r"(\S+-\S+-\S+\s+\d+:\d+:\d+)" +
                                              r"(\.(\d+))?")
        m = PayloadTime.TIME_PAT.match(timestr)
        if not m:
            raise ValueError("Cannot parse date/time \"%s\"" % timestr)

        # date format without subsecond parsing
        baseFmt = "%Y-%m-%d %H:%M:%S"

        if m.group(3) is not None and len(m.group(3)) <= 6:
            # legal subsecond value for strptime
            dt = datetime.datetime.strptime(timestr, baseFmt + ".%f")
            ticks = dt.microsecond * 10000
        else:
            # must have a higher-precision subsecond value specified
            dt = datetime.datetime.strptime(m.group(1), baseFmt)

            # extract subsecond value
            if m.group(3) is None:
                ticks = 0
            else:
                ticks = int(m.group(3))
                for i in xrange(10 - len(m.group(3))):
                    ticks *= 10

        return DAQDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                           dt.second, ticks, high_precision=high_precision)

    @staticmethod
    def toDateTime(payTime, high_precision=False):
        if payTime is None:
            return None

        # recompute start-of-year offset?
        recompute = (PayloadTime.PREV_TIME is None or
                     abs(payTime - PayloadTime.PREV_TIME) >
                     PayloadTime.ELEVEN_MONTHS)

        if recompute:
            now = time.gmtime()
            jan1 = time.struct_time((now.tm_year, 1, 1, 0, 0, 0, 0, 0, -1))
            PayloadTime.TIME_OFFSET = calendar.timegm(jan1)

        PayloadTime.PREV_TIME = payTime

        curTime = PayloadTime.TIME_OFFSET + \
            (payTime / float(PayloadTime.TICKS_PER_SECOND))
        ts = time.gmtime(curTime)

        subsec = payTime % PayloadTime.TICKS_PER_SECOND

        return DAQDateTime(ts.tm_year, ts.tm_mon, ts.tm_mday, ts.tm_hour,
                           ts.tm_min, ts.tm_sec, subsec,
                           high_precision=high_precision)
