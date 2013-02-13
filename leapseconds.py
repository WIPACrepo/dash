"""A python set of leapsecond utilities
Note that the doctests assume that the nist ntp tai offset file available from:

ftp://tycho.usno.navy.mil/pub/ntp/leap-seconds.nnnnnnnn

Is present and is named 'leap-seconds.latest'
"""


import bisect
import calendar
import os
import re
import time

from locate_pdaq import find_pdaq_config


class leapseconds:
    """every calculation that might be of use when it comes to leapseconds"""

    instance = None

    class leapsecondsHelper:
        def __call__(self, *args, **kw):
            if not leapseconds.instance:
                configDir = find_pdaq_config()
                path = os.path.join(configDir, 'nist', 'leapseconds-latest')
                leapseconds.instance = leapseconds(path)
            return leapseconds.instance

    getInstance = leapsecondsHelper()

    def __init__(self, leap_filename):
        self.__mjd_expiry = None
        self.__nist_data = []
        self.__parse_nist(leap_filename)

    def get_mjd_expiry(self):
        """
        Return the modified julian date that the current nist file expires
        """
        return self.__mjd_expiry

    @staticmethod
    def seconds_till_june30(year):
        """For the given year calculate the number of seconds
        to a potential leapsecond at 23:59:60 on june 30.

        This doesn't mean that there IS a leapsecond, just that
        below this number of seconds past jan1 there is no danger
        of one.
        """

        jan1_mjd = leapseconds.mjd(year, 1, 1)
        midnight = leapseconds.frac_day(23, 59, 60)
        june30_1159_mjd = leapseconds.mjd(year, 6, 30 + midnight)

        return (june30_1159_mjd - jan1_mjd) * 86400

    @staticmethod
    def days_in_year(year):
        """Figure out the number of days in a given year
        This accounts for leap years

        >>> leapseconds.days_in_year(2012)
        366
        >>> leapseconds.days_in_year(2008)
        366
        >>> leapseconds.days_in_year(2016)
        366
        >>> leapseconds.days_in_year(2013)
        365
        >>> leapseconds.days_in_year(2014)
        365
        >>> leapseconds.days_in_year(2015)
        365
        >>> leapseconds.days_in_year(2017)
        365
        """
        if year % 400 == 0:
            return 366
        elif year % 100 == 0:
            return 365
        elif year % 4 == 0:
            return 366
        else:
            return 365

    def seconds_in_year(self, year):
        """
        calculate the number of seconds in a given year

        cannot be less than 1972 and cannot pass the expiration of
        the nist leap file

        >>> p = find_pdaq_config()
        >>> p = os.path.join(p, "nist", "leapseconds-latest")
        >>> a = leapseconds(p)
        >>> a.seconds_in_year(2008)
        31622401L
        >>> a.seconds_in_year(2011)
        31536000L
        >>> a.seconds_in_year(1997)
        31536001L
        >>> a.seconds_in_year(2007)
        31536000L
        >>> a.seconds_in_year(1972)
        31622402L
        """
        mjd1 = self.mjd(year, 1, 1)
        mjd2 = self.mjd(year + 1, 1, 1)

        # year cannot be less than 1972
        # mjd2 cannot be > expiry
        if year < 1972:
            raise ValueError("argument year must be >=1972 was %d" % year)
        if mjd2 > self.__mjd_expiry:
            raise ValueError(("calculation may not span the"
                              "validity of the nist file"))

        return long((mjd2 - mjd1) * 3600 * 24 + \
                        (self.get_tai_offset(mjd2) - \
                              self.get_tai_offset(mjd1)))

    @staticmethod
    def ntp_to_mjd(ntp_timestamp):
        """convert an ntp timestamp to a modified julian date
        Note that this equation comes directly from the documentation
        of the leapsecond file"""
        return ntp_timestamp / 86400. + 15020

    @staticmethod
    def mjd_now():
        """Calculate the modified julian date for the current system time"""
        __now = time.gmtime()

        frac_day = leapseconds.frac_day(__now.tm_hour,
                                        __now.tm_min,
                                        __now.tm_sec)

        return leapseconds.mjd(__now.tm_year,
                               __now.tm_mon,
                               __now.tm_mday + frac_day)

    @staticmethod
    def frac_day(hour, minute, second):
        """given the hour minute second calculate the fractional part of
        a day

        >>> leapseconds.frac_day(12, 0, 0)
        0.5
        """

        tmp = second / 60.
        tmp = (tmp + minute) / 60.
        tmp = (tmp + hour) / 24.

        return tmp

    @staticmethod
    def mjd(year, month, day):
        """Convert the given year, month, and fractional day
        to the modified julian date.

        >>> leapseconds.mjd(2004, 1, 1)
        53005.0
        >>> leapseconds.mjd(2005, 1, 1)
        53371.0
        >>> leapseconds.mjd(2005, 1, 30)
        53400.0
        >>> leapseconds.mjd(1985, 2, 17.25)
        46113.25
        """

        if month == 1 or month == 2:
            year = year - 1
            month = month + 12

        # assume that we will never be calculating
        # mjd's before oct 15 1582

        a = int(year / 100)
        b = 2 - a + int(a / 4)
        c = int(365.25 * year)
        d = int(30.600 * (month + 1.0))

        jd = b + c + d + day + 1720994.5

        mjd = jd - 2400000.5

        return mjd

    @staticmethod
    def mjd_to_timestruct(mjd):
        """Convert a modified julian date to a python time tuple.

        >>> jul1_2012 = leapseconds.mjd(2012, 7, 1)
        >>> leapseconds.mjd_to_timestruct(jul1_2012)
        time.struct_time(tm_year=2012, tm_mon=7, tm_mday=1, tm_hour=0, tm_min=0, tm_sec=0, tm_wday=6, tm_yday=183, tm_isdst=0)
        """

        jd = mjd + 2400000.5

        jd = jd + 0.5
        i = int(jd)
        f = jd % 1

        if i > 2299160:
            a = int((i - 1867216.25) / 36524.25)
            b = i + 1 + a - int(a / 4)
        else:
            b = i

        c = b + 1524.
        d = int((c - 122.1) / 365.25)
        e = int(365.25 * d)
        g = int((c - e) / 30.6001)

        day = c - e + f - int(30.6001 * g)
        if g < 13.5:
            m = g - 1
        else:
            m = g - 13

        if m > 2.5:
            year = d - 4716
        else:
            year = d - 4715

        # note that day will be a fractional day
        # and python handles that
        time_str = (year, m, day, 0, 0, 0, 0, 0, -1)
        # looks silly, but have to deal with fractional day
        gm_epoch = calendar.timegm(time_str)
        time_str = time.gmtime(gm_epoch)

        return time_str

    def is_expired(self):
        """Returns true if the supplied nist leapsecond file is expired
        true otherwise.

        If it is expired see the leapsecond_fetch.py script to get a new one
        """
        if not self.__mjd_expiry:
            # if no expiry information return expired
            return True

        __now = self.mjd_now()
        if __now > self.__mjd_expiry:
            return True
        return False

    def get_tai_offset(self, mjd, ignore_exception=False):
        """Calulate the offset from TAI for the given mjd
        This will be used to calculate the elapsed leapseconds
        since the beginning of the year.

        >>> p = find_pdaq_config()
        >>> p = os.path.join(p, "nist", "leapseconds-latest")
        >>> a = leapseconds(p)
        >>> jul1_2012 = leapseconds.mjd(2012, 7, 1.)
        >>> a.get_tai_offset(jul1_2012)
        35
        """

        # search the __nist_data list to find where
        # mjd 'mjd' lands and get the tai offset at that point
        if not ignore_exception and mjd > self.__mjd_expiry:
            raise Exception("mjd data file expired")

        position = bisect.bisect_right(self.__nist_mjd, mjd)
        if position:
            return self.__nist_tai[position - 1]

        raise Exception("tai error")

    def get_leap_offset(self, time_obj, ignore_exception=False):
        """ Take the given timestruct and get the number of
        leapseconds since the beginning of the year

        >>> p = find_pdaq_config()
        >>> p = os.path.join(p, "nist", "leapseconds-latest")
        >>> a = leapseconds(p)
        >>> before_leap = time.struct_time((2012, 6, 30, 23, 59, 59, 0, 0, -1))
        >>> a.get_leap_offset(before_leap)
        0
        >>> during_leap = time.struct_time((2012, 6, 30, 23, 59, 60, 0, 0, -1))
        >>> a.get_leap_offset(during_leap)
        0
        >>> after_leap = time.struct_time((2012, 7, 1, 0, 0, 0, 0, 0, -1))
        >>> a.get_leap_offset(after_leap)
        1
        """

        mjd_jan1 = self.mjd(time_obj.tm_year, 1, 1.)
        mjd_obj = self.mjd(time_obj.tm_year,
                           time_obj.tm_mon,
                           time_obj.tm_mday)

        jan1_tai = self.get_tai_offset(mjd_jan1, ignore_exception)
        obj_tai = self.get_tai_offset(mjd_obj, ignore_exception)

        leap_offset = obj_tai - jan1_tai

        return leap_offset

    def __parse_nist(self, fname):
        """Assume that the filename passed in points to a nist
        leapsecond file.  Parse that file looking for data and
        file expiration information.
        """

        expiry_pat = re.compile('^#@\s+([0-9]+)')
        comment_pat = re.compile('(^#$)|(^#[^@].*$)')
        data_pat = re.compile('([0-9]+)\s+([0-9]+)')

        nist_data = []

        with open(fname, 'r') as fd:
            for line in fd:

                if comment_pat.match(line):
                    # is a comment skip
                    continue
                else:
                    expiry_match = expiry_pat.match(line)
                    data_match = data_pat.match(line)

                    if expiry_match:
                        expiry_ntp = int(expiry_match.group(1))
                        self.__mjd_expiry = self.ntp_to_mjd(expiry_ntp)
                    elif data_match:
                        ntp_stamp = int(data_match.group(1))
                        tai_offset = int(data_match.group(2))

                        mjd_stamp = self.ntp_to_mjd(ntp_stamp)
                        nist_data.append((mjd_stamp, tai_offset))
                    else:
                        raise Exception("bad nist data file '%s'" % fname)

        nist_data.sort(key=lambda pt: pt[0])

        self.__nist_mjd, self.__nist_tai = zip(*nist_data)


if __name__ == "__main__":
    import doctest
    doctest.testmod()

    print "mjd now: ", leapseconds.mjd_now()
    print "mjd expiry: ", leapseconds.getInstance().get_mjd_expiry()

    now = leapseconds.mjd_now()
    dtime = leapseconds.mjd_to_timestruct(now)
    print "mjd now back to datetime: ", time.strftime("%c", dtime)
    print "time.gmtime(): ", time.strftime("%c", time.gmtime())
