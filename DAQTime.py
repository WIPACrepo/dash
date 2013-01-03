#!/usr/bin/env python

import re
import calendar
import time
import datetime

from leapseconds import leapseconds


class DAQDateTimeDelta(object):
    def __init__(self, days, seconds, microseconds):
        self.days = days
        self.seconds = seconds
        self.microseconds = microseconds

    def __str__(self):
        if self.days == 0:
            rtnstr = ""
        else:
            rtnstr = "%d day" % self.days
            if self.days != 1:
                rtnstr += "s"
            rtnstr += ", "
        rtnstr += "%d:%02d:%02d" % \
            (self.seconds / 3600, (self.seconds / 60) % 60, self.seconds % 60)
        if self.microseconds != 0:
            rtnstr += ".%06d" % self.microseconds
        return rtnstr


class DAQDateTime(object):
    HIGH_PRECISION = False

    def __init__(self, year, month, day, hour, minute, second, daqticks,
                 tzinfo=None, high_precision=HIGH_PRECISION):

        if high_precision:
            self.__daqticks = daqticks
            self.__high_precision = True
        else:
            self.__daqticks = (daqticks / 10000L) * 10000L
            self.__high_precision = False

        self.leap = leapseconds.getInstance()
        frac_day = self.leap.frac_day(hour, minute, second)
        self.mjd_day = self.leap.mjd(year, month, day + frac_day)

        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.second = second
        self.tzinfo = tzinfo

        self.tuple = (year, month, day, hour, minute, second, 0, 0, -1)

    def __repr__(self):
        if not self.tzinfo:
            tzstr = ""
        else:
            tzstr = ", %s" % repr(self.tzinfo)

        if not self.__high_precision:
            hpstr = ""
        else:
            hpstr = ", high_precision=True"

        return "DAQDateTime(%d, %d, %d, %d, %d, %d, %d%s%s)" % \
            (self.year, self.month, self.day, self.hour,
             self.minute, self.second, self.__daqticks, tzstr, hpstr)

    def __cmp__(self, other):
        # compare two date time objects
        if not other:
            return -1

        val = cmp(self.tuple[0:6], other.tuple[0:6])
        if val == 0:
            val = cmp(self.__daqticks, other.__daqticks)
        return val

    def __sub__(self, other):
        # assumes that all days are 86400 seconds long
        # not the case in a day containing a leapsecond
        # subtract two date time objects

        diff_mjd = self.mjd_day - other.mjd_day
        try:
            diff_tai = self.leap.get_tai_offset(self.mjd_day) - \
                self.leap.get_tai_offset(other.mjd_day)
        except:
            raise ValueError("Cannot get TAI offset for either %d or %d" %
                             (self.mjd_day, other.mjd_day))

        diff_seconds = diff_mjd * 3600. * 24. + diff_tai

        diff_ticks = self.__daqticks - other.__daqticks

        days = int(diff_seconds / 86400)
        # round to the nearest number of seconds
        # otherwise had a lack of precision issue
        # a number of tests where failing as they where one second off
        # turned out we had 120.999 instead of 121 seconds
        secs = diff_seconds - days * 86400
        secs = round(secs)

        if secs < 0:
            days -= 1
            secs += 86400

        usecs = float(diff_ticks) / 10000.0

        if usecs < 0:
            if secs == 0:
                days -= 1.0
                secs += 86400
            secs -= 1
            usecs += 1000000

        return DAQDateTimeDelta(days, secs, long(usecs))

    def __str__(self):
        if self.__high_precision:
            fmt = "%s.%010d"
            ticks = self.__daqticks
        else:
            fmt = "%s.%06d"
            ticks = self.__daqticks / 10000

        timeStr = "%d-%02d-%02d %02d:%02d:%02d" % (self.year,
                                                   self.month,
                                                   self.day,
                                                   self.hour,
                                                   self.minute,
                                                   self.second)

        return fmt % (timeStr, ticks)


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

    # seconds till jul 30 of this year
    TIME_TILL_JUNE30 = None

    @staticmethod
    def fromString(timestr, high_precision=DAQDateTime.HIGH_PRECISION):
        if not timestr:
            return None

        if not PayloadTime.TIME_PAT:
            PayloadTime.TIME_PAT = re.compile(r"(\S+-\S+-\S+\s+\d+:\d+:\d+)" +
                                              r"(\.(\d+))?")

        m = PayloadTime.TIME_PAT.match(timestr)
        if not m:
            raise ValueError("Cannot parse date/time '%s'" % timestr)

        basefmt = "%Y-%m-%d %H:%M:%S"

        pt = time.strptime(m.group(1), basefmt)

        if m.group(3) and len(m.group(3)) <= 6:
            # legal subsecond value for strptime
            temp_str = ".%s" % m.group(3)
            dt = datetime.datetime.strptime(temp_str,
                                            ".%f")
            ticks = dt.microsecond * 10000
        else:
            if not m.group(3):
                ticks = 0
            else:
                ticks = int(m.group(3))
                for i in xrange(10 - len(m.group(3))):
                    ticks *= 10

        return DAQDateTime(pt.tm_year, pt.tm_mon,
                           pt.tm_mday, pt.tm_hour,
                           pt.tm_min, pt.tm_sec,
                           ticks,
                           high_precision=high_precision)

    @staticmethod
    def toDateTime(payTime, high_precision=DAQDateTime.HIGH_PRECISION):
        if payTime is None:
            return None

        # recompute start-of-year offset?
        recompute = (PayloadTime.PREV_TIME is None or
                     abs(payTime - PayloadTime.PREV_TIME) >
                     PayloadTime.ELEVEN_MONTHS)

        if recompute:
            # note that this is a dangerous
            # bit of code near the new year as the payload
            # times and the system clock are not coming from the same
            # clock, there will be a slight processing delay etc
            now = time.gmtime()
            jan1 = time.struct_time((now.tm_year, 1, 1, 0, 0, 0, 0, 0, -1))
            PayloadTime.TIME_OFFSET = calendar.timegm(jan1)
            july1_tuple = time.struct_time((now.tm_year, 7, 1, 0, 0, 0, 0, 0,
                                            -1))
            PayloadTime.YEAR = now.tm_year
            PayloadTime.has_leapsecond = \
                leapseconds.getInstance().get_leap_offset(july1_tuple) > 0
            if not PayloadTime.has_leapsecond:
                # no mid-year leap second, so don't need to calculate
                # seconds until June 30
                PayloadTime.TIME_TILL_JUNE30 = sys.maxint
            else:
                PayloadTime.TIME_TILL_JUNE30 = \
                    leapseconds.seconds_till_june30(now.tm_year)

        PayloadTime.PREV_TIME = payTime

        curSecOffset = (payTime / long(PayloadTime.TICKS_PER_SECOND))
        subsec = payTime % PayloadTime.TICKS_PER_SECOND

        if not PayloadTime.has_leapsecond or \
                curSecOffset < PayloadTime.TIME_TILL_JUNE30:
            # no possibility of leapseconds to worry about

            curTime = curSecOffset + PayloadTime.TIME_OFFSET
            ts = time.gmtime(curTime)

            return DAQDateTime(ts.tm_year, ts.tm_mon, ts.tm_mday, ts.tm_hour,
                               ts.tm_min, ts.tm_sec, subsec,
                               high_precision=high_precision)
        else:
            # we have to worry about a potential leapsecond

            # did we get a payload time exactly ON the leapsecond
            if curSecOffset == PayloadTime.TIME_TILL_JUNE30:
                return DAQDateTime(PayloadTime.YEAR, 6, 30, 23, 59, 60,
                                   subsec, high_precision=high_precision)
            else:
                curTime = curSecOffset + PayloadTime.TIME_OFFSET
                # there was a leapsecond
                # assuming we only have to deal with ONE leapsecond
                ts = time.gmtime(curTime - 1)

                return DAQDateTime(ts.tm_year, ts.tm_mon, ts.tm_mday,
                                   ts.tm_hour, ts.tm_min, ts.tm_sec, subsec,
                                   high_precision=high_precision)


if __name__ == "__main__":
    import optparse

    p = optparse.OptionParser()

    opt, args = p.parse_args()

    if len(args) == 0:
        # pattern %Y-%m-%d %H:%M:%S
        base = "2012-01-10 10:19:23"
        dt0 = PayloadTime.fromString(base + ".0001000000")
        dt1 = PayloadTime.fromString(base + ".0001")

        print dt0
        print dt1
        raise SystemExit()

    for arg in args:
        try:
            try:
                val = long(arg)
                dt = PayloadTime.toDateTime(val, True)
            except:
                dt = PayloadTime.fromString(arg, True)
            print "%s -> %s" % (arg, dt)
        except:
            print "Bad date: " + arg
            import traceback
            traceback.print_exc()
