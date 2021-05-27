#!/usr/bin/env python
"""
miscellaneous classes which convert DAQ ticks or a DAQ time string
(with 0.1 ns precision) to an object which emulates Python's `datetime` 
"""

from __future__ import print_function

import calendar
import datetime
import re
import sys
import time

from i3helper import Comparable
from leapseconds import LeapSeconds, MJD


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


class DAQDateTime(Comparable):
    # if True, calculate DAQ times to 0.1 nanosecond precision
    # if False, calculate to microsecond precision
    HIGH_PRECISION = True

    def __init__(self, year, month, day, hour, minute, second, daqticks,
                 tzinfo=None, high_precision=HIGH_PRECISION):

        if high_precision:
            self.__daq_ticks = daqticks
            self.__high_precision = True
        else:
            self.__daq_ticks = (daqticks / 10000) * 10000
            self.__high_precision = False

        self.leap = LeapSeconds.instance()
        self.mjd_day = MJD(year, month, day, hour, minute, second)

        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.second = second
        self.tzinfo = tzinfo

        self.tuple = (year, month, day, hour, minute, second, 0, 0, -1)

    def __str__(self):
        fmt = "%d-%02d-%02d %02d:%02d:%02d"
        if self.__high_precision:
            fmt += ".%010d"
            ticks = self.__daq_ticks
        else:
            fmt += ".%06d"
            ticks = self.__daq_ticks / 10000

        return fmt % (self.year, self.month, self.day, self.hour, self.minute,
                      self.second, ticks)

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
             self.minute, self.second, self.__daq_ticks, tzstr, hpstr)

    def __sub__(self, other):
        # assumes that all days are 86400 seconds long
        # not the case in a day containing a leapsecond
        # subtract two date time objects

        diff_mjd = self.mjd_day - other.mjd_day
        diff_seconds = diff_mjd * 3600. * 24.

        # add leapseconds
        year = self.year
        while year < other.year:
            diff_seconds += self.leap.get_leap_offset(999, year)
            year += 1
        other_yday = other.mjd_day.timestruct.tm_yday
        diff_seconds += self.leap.get_leap_offset(other_yday)

        diff_ticks = self.daq_ticks - other.daq_ticks

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

        return DAQDateTimeDelta(days, secs, int(usecs))

    @property
    def compare_key(self):
        "Return the keys to be used by the Comparable methods"
        return (self.tuple[0:6], self.__daq_ticks)

    @property
    def daq_ticks(self):
        return self.__daq_ticks


class YearData(object):
    # note that this is a dangerous
    # bit of code near the new year as the payload
    # times and the system clock are not coming from the same
    # clock, there will be a slight processing delay etc
    def __init__(self, year):
        self.__year = year

        # compute the number of seconds from the Unix epoch to January 1
        jan1 = time.struct_time((year, 1, 1, 0, 0, 0, 0, 0, -1))
        self.__jan1_offset = calendar.timegm(jan1)

        # does this year include a leap second?
        raw_tuple = time.struct_time((year, 7, 1, 0, 0, 0, 0, 0, -1))
        july1_tuple = time.gmtime(calendar.timegm(raw_tuple))
        leapsec = LeapSeconds.instance().get_leap_offset(july1_tuple.tm_yday,
                                                         year)
        self.__has_leapsecond = leapsec > 0

        if self.__has_leapsecond:
            self.__june30_offset = self.__seconds_until_june30(year)
        else:
            # no mid-year leap second, so don't need to calculate
            # seconds until June 30
            self.__june30_offset = sys.maxsize

    def __str__(self):
        if not self.__has_leapsecond:
            extra = ""
        else:
            extra = " (jun30off %d)" % (self.__june30_offset, )
        return "%04d: %d%s" % (self.__year, self.__jan1_offset, extra)

    @classmethod
    def __seconds_until_june30(cls, year):
        """
        For the given year calculate the number of seconds
        to a potential leapsecond at 23:59:60 on june 30.

        This doesn't mean that there IS a leapsecond, just that
        after this number of seconds past jan1 there is no danger
        of one.
        """

        jan1_mjd = MJD(year, 1, 1)
        june30_1159_mjd = MJD(year, 6, 30, 23, 59, 60)

        return (june30_1159_mjd - jan1_mjd) * 86400

    @property
    def has_leapsecond(self):
        return self.__has_leapsecond

    @property
    def jan1_offset(self):
        return self.__jan1_offset

    @property
    def june30_offset(self):
        return self.__june30_offset


class PayloadTime(object):
    # per-year data
    YEAR_DATA = {}

    # regular expression used to parse date/time strings
    TIME_PAT = None

    # number of seconds in 11 months
    ELEVEN_MONTHS = 60 * 60 * 24 * (365 - 31)

    # number of DAQ ticks in one second
    TICKS_PER_SECOND = 10000000000

    # current year
    YEAR = None
    # DAQ tick used when setting the current year
    YEAR_TICKS = None

    @classmethod
    def from_string(cls, timestr, high_precision=DAQDateTime.HIGH_PRECISION):
        if not timestr:
            return None

        if not cls.TIME_PAT:
            cls.TIME_PAT = re.compile(r"(\S+-\S+-\S+\s+\d+:\d+:\d+)" +
                                      r"(\.(\d+))?")

        mtch = cls.TIME_PAT.match(timestr)
        if mtch is None:
            raise ValueError("Cannot parse date/time '%s'" % timestr)

        basefmt = "%Y-%m-%d %H:%M:%S"

        ptm = time.strptime(mtch.group(1), basefmt)

        if mtch.group(3) and len(mtch.group(3)) <= 6:
            # legal subsecond value for strptime
            temp_str = ".%s" % mtch.group(3)
            dttm = datetime.datetime.strptime(temp_str, ".%f")
            ticks = dttm.microsecond * 10000
        else:
            if not mtch.group(3):
                ticks = 0
            else:
                ticks = int(mtch.group(3))
                for _ in range(10 - len(mtch.group(3))):
                    ticks *= 10

        return DAQDateTime(ptm.tm_year, ptm.tm_mon, ptm.tm_mday, ptm.tm_hour,
                           ptm.tm_min, ptm.tm_sec, ticks,
                           high_precision=high_precision)

    @classmethod
    def get_current_year(cls):
        return time.gmtime().tm_year

    @classmethod
    def to_date_time(cls, pay_time, year=None,
                     high_precision=DAQDateTime.HIGH_PRECISION):
        if pay_time is None or isinstance(pay_time, str):
            return None

        if year is None:
            recompute = cls.YEAR is None or \
              cls.YEAR_TICKS + cls.ELEVEN_MONTHS < pay_time or \
              cls.YEAR_TICKS > pay_time + cls.ELEVEN_MONTHS

            # if the year hasn't been set, or if time has gone backward,,,
            if recompute:
                # fetch the current year from the system time
                cls.YEAR = cls.get_current_year()
                cls.YEAR_TICKS = pay_time

            # use the current year
            year = cls.YEAR

        # precompute this year's data if we don't yet have it
        if year not in cls.YEAR_DATA:
            cls.YEAR_DATA[year] = YearData(year)

        # convert DAQ ticks to seconds, preserving subsecond count
        cur_sec_offset = (pay_time / int(cls.TICKS_PER_SECOND))
        subsec = pay_time % cls.TICKS_PER_SECOND

        # if there's no possibility of a leapsecond...
        if not cls.YEAR_DATA[year].has_leapsecond or \
                cur_sec_offset < cls.YEAR_DATA[year].june30_offset:
            # convert DAQ tick into number of seconds since the Unix epoch
            cur_time = cur_sec_offset + cls.YEAR_DATA[year].jan1_offset
            gmtm = time.gmtime(cur_time)

            # create a DAQDateTime object which includes the subsecond count
            return DAQDateTime(gmtm.tm_year, gmtm.tm_mon, gmtm.tm_mday,
                               gmtm.tm_hour, gmtm.tm_min, gmtm.tm_sec, subsec,
                               high_precision=high_precision)

        # if we got a payload time exactly ON the leapsecond...
        if cur_sec_offset == cls.YEAR_DATA[year].june30_offset:
            # return a leapsecond object
            return DAQDateTime(year, 6, 30, 23, 59, 60, subsec,
                               high_precision=high_precision)

        # convert DAQ tick into number of seconds since the Unix epoch
        cur_time = cur_sec_offset + cls.YEAR_DATA[year].jan1_offset

        # get time quantities after subtracting ONE leapsecond
        gmtm = time.gmtime(cur_time - 1)

        # create a DAQDateTime object which includes the subsecond count
        return DAQDateTime(gmtm.tm_year, gmtm.tm_mon, gmtm.tm_mday,
                           gmtm.tm_hour, gmtm.tm_min, gmtm.tm_sec, subsec,
                           high_precision=high_precision)


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-y", "--year", type=int, dest="year",
                        help="Base year when converting DAQ times to strings ")
    parser.add_argument("time", nargs="*")
    args = parser.parse_args()

    if len(args.time) == 0:  # pylint: disable=len-as-condition
        # pattern %Y-%m-%d %H:%M:%S
        base = "2012-01-10 10:19:23"
        dttm0 = PayloadTime.from_string(base + ".0001000000")
        dttm1 = PayloadTime.from_string(base + ".0001")

        print(dttm0)
        print(dttm1)
        raise SystemExit()

    for arg in args.time:
        try:
            try:
                val = int(arg)
                dttm = None
            except IOError:
                print("Cannot convert %s" % str(val))
                import traceback
                traceback.print_exc()
                continue
            except ValueError:
                val = None
            if val is not None:
                dttm = PayloadTime.to_date_time(val, year=args.year,
                                                high_precision=True)
                print("%s -> %s" % (arg, dttm))
            else:
                dttm = PayloadTime.from_string(arg, True)
                print("\"%s\" -> %s" % (arg, dttm))

        except:  # pylint: disable=bare-except
            print("Bad date: " + arg)
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
