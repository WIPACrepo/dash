#!/usr/bin/env python

import calendar
import datetime
import time
import unittest
from DAQTime import DAQDateTime, PayloadTime
from leapseconds import leapseconds

class TestDAQTime(unittest.TestCase):
    TICKS_PER_SEC = 10000000000
    CUR_YEAR = None

    def __checkCompare(self, dt0, dt1, expResult):
        result = cmp(dt0, dt1)
        self.assertEqual(expResult, result,
                         "Expected cmp(%s, %s) to return %s, not %s" %
                         (dt0, dt1, expResult, result))

        result = cmp(dt1, dt0)
        self.assertEqual(-expResult, result,
                         "Expected inverted cmp(%s, %s) to return %s, not %s" %
                         (dt1, dt0, -expResult, result))

    def __dateFormat(self, yr, mon, day, hr, min, sec, usec,
                     high_precision=False):
        if high_precision:
            subsecstr = "%010d" % usec
        else:
            subsecstr = "%06d" % (usec / 10000L)
        return "%04d-%02d-%02d %02d:%02d:%02d.%s" % \
            (yr, mon, day, hr, min, sec, subsecstr)

    def __deltaFormat(self, days, hrs, min, sec, usec):
        rtnstr = "%d day" % days
        if days != 1:
            rtnstr += "s"
        rtnstr += ", %d:%02d:%02d" % (hrs, min, sec)
        if usec > 0:
            rtnstr += ".%06d" % usec
        return rtnstr

    def setUp(self):
        if self.CUR_YEAR is None:
            now = time.gmtime()
            self.CUR_YEAR = now.tm_year

    def testPayloadTimeNone(self):
        self.assertEqual(PayloadTime.toDateTime(None), None)

    def testPayloadTimeZero(self):
        dt = PayloadTime.toDateTime(0, high_precision=False)
        expStr = self.__dateFormat(self.CUR_YEAR, 1, 1, 0, 0, 0, 0)
        self.assertEqual(expStr, str(dt),
                         "Expected date %s, not %s" % (expStr, dt))

    def testPayloadTimeZeroHP(self):
        dt = PayloadTime.toDateTime(0, high_precision=True)
        expStr = self.__dateFormat(self.CUR_YEAR, 1, 1, 0, 0, 0, 0,
                                   high_precision=True)
        self.assertEqual(expStr, str(dt),
                         "Expected date %s, not %s" % (expStr, dt))

    def testPayloadTimeOneSec(self):
        dt = PayloadTime.toDateTime(self.TICKS_PER_SEC, high_precision=False)
        expStr = self.__dateFormat(self.CUR_YEAR, 1, 1, 0, 0, 1, 0)
        self.assertEqual(expStr, str(dt),
                         "Expected date %s, not %s" % (expStr, dt))

    def testPayloadTimeOneSecHP(self):
        dt = PayloadTime.toDateTime(self.TICKS_PER_SEC, high_precision=True)
        expStr = self.__dateFormat(self.CUR_YEAR, 1, 1, 0, 0, 1, 0,
                                   high_precision=True)
        self.assertEqual(expStr, str(dt),
                         "Expected date %s, not %s" % (expStr, dt))

    def testPayloadTimeOneYear(self):
        """ test cannot easily work as calculating the number of seconds in the
        current year requires a nist file that passes the end of the year"""

        leapObj = leapseconds.getInstance()
        jan1_mjd = leapObj.mjd(self.CUR_YEAR, 1, 1.)
        expiry_mjd = leapObj.get_mjd_expiry()
        elapsed_seconds = (expiry_mjd - jan1_mjd) * 86400. + \
            (leapObj.get_tai_offset(expiry_mjd) - leapObj.get_tai_offset(jan1_mjd))

        est = leapObj.mjd_to_timestruct(expiry_mjd)

        yrsecs = elapsed_seconds

        # the LONG bit is actually important, otherwise we run into floating
        # point precision issues
        yrticks = long(yrsecs) * self.TICKS_PER_SEC + (self.TICKS_PER_SEC - 10000)

        dt = PayloadTime.toDateTime(yrticks, high_precision=False)
        expStr = self.__dateFormat(self.CUR_YEAR, est.tm_mon, est.tm_mday,
                                   est.tm_hour, est.tm_min, est.tm_sec,
                                   9999990000)
        self.assertEqual(expStr, str(dt),
                         "Expected date %s, not %s" % (expStr, dt))

    def testPayloadTimeOneYearHP(self):
        """test cannot easily work as calculating the number of seconds in the current
        year requires a nist that passes the end of the year"""

        leapObj = leapseconds.getInstance()
        jan1_mjd = leapObj.mjd(self.CUR_YEAR, 1, 1.)
        expiry_mjd = leapObj.get_mjd_expiry()
        elapsed_seconds = (expiry_mjd - jan1_mjd) * 86400. + \
            (leapObj.get_tai_offset(expiry_mjd) - leapObj.get_tai_offset(jan1_mjd))

        est = leapObj.mjd_to_timestruct(expiry_mjd)
        yrsecs = elapsed_seconds

        # the LONG bit is actually important, otherwise we run into floating
        # point precision issues
        yrticks = long(yrsecs) * self.TICKS_PER_SEC + (self.TICKS_PER_SEC - 10000)
        dt = PayloadTime.toDateTime(yrticks, high_precision=True)

        expStr = self.__dateFormat(self.CUR_YEAR, est.tm_mon, est.tm_mday,
                                   est.tm_hour, est.tm_min, est.tm_sec,
                                   9999990000, high_precision=True)
        self.assertEqual(expStr, str(dt),
                         "Expected date %s, not %s" % (expStr, dt))

    def testDeltaOneDay(self):
        jan1 = time.struct_time((self.CUR_YEAR, 1, 1, 0, 0, 0, 0, 0, -1))
        jan2 = time.struct_time((self.CUR_YEAR, 1, 2, 0, 0, 0, 0, 0, -1))
        dayticks = long(calendar.timegm(jan2) - calendar.timegm(jan1)) * \
            self.TICKS_PER_SEC

        dt0 = PayloadTime.toDateTime(0)
        dt1 = PayloadTime.toDateTime(dayticks)

        expStr = self.__deltaFormat(1, 0, 0, 0, 0)
        self.assertEqual(expStr, str(dt1 - dt0),
                         "Expected delta %s, not %s" % (expStr, dt1 - dt0))

        expStr = self.__deltaFormat(-1, 0, 0, 0, 0)
        self.assertEqual(expStr, str(dt0 - dt1),
                         "Expected delta2 %s, not %s" % (expStr, dt0 - dt1))

    def testDeltaTwoWeeks(self):
        jan1 = time.struct_time((self.CUR_YEAR, 1, 1, 0, 0, 0, 0, 0, -1))
        jan15 = time.struct_time((self.CUR_YEAR, 1, 15, 3, 2, 1, 0, 0, -1))
        usec = 101100
        dayticks = long(calendar.timegm(jan15) - calendar.timegm(jan1)) * \
            self.TICKS_PER_SEC + (usec * 10000)

        dt0 = PayloadTime.toDateTime(0)
        dt1 = PayloadTime.toDateTime(dayticks)

        expStr = self.__deltaFormat(14, 3, 2, 1, usec)
        self.assertEqual(expStr, str(dt1 - dt0),
                         "Expected delta %s, not %s" % (expStr, dt1 - dt0))

        expStr = self.__deltaFormat(-15, 20, 57, 58, 898900)
        self.assertEqual(expStr, str(dt0 - dt1),
                         "Expected delta2 %s, not %s" % (expStr, dt0 - dt1))

    def testDeltaTwoWeeksHP(self):
        jan1 = time.struct_time((self.CUR_YEAR, 1, 1, 0, 0, 0, 0, 0, -1))
        jan15 = time.struct_time((self.CUR_YEAR, 1, 15, 3, 2, 1, 0, 0, -1))
        usec = 101100
        dayticks = long(calendar.timegm(jan15) - calendar.timegm(jan1)) * \
            self.TICKS_PER_SEC + (usec * 10000)

        dt0 = PayloadTime.toDateTime(0, high_precision=True)
        dt1 = PayloadTime.toDateTime(dayticks, high_precision=True)

        expStr = self.__deltaFormat(14, 3, 2, 1, usec)
        self.assertEqual(expStr, str(dt1 - dt0),
                         "Expected delta %s, not %s" % (expStr, dt1 - dt0))

        expStr = self.__deltaFormat(-15, 20, 57, 58, 898900)
        self.assertEqual(expStr, str(dt0 - dt1),
                         "Expected delta2 %s, not %s" % (expStr, dt0 - dt1))

    def testDeltaSubsec(self):
        self.__validateDelta((self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210),
                             (self.CUR_YEAR, 1, 10, 10, 19, 23, 8765432109),
                             (0, 0, 111111))

    def __validateDelta(self, t1, t2, expDiff):
        dt1 = datetime.datetime(t1[0], t1[1], t1[2], t1[3], t1[4], t1[5],
                                (t1[6] + 500) / 10000)
        dt2 = datetime.datetime(t2[0], t2[1], t2[2], t2[3], t2[4], t2[5],
                                (t2[6] + 500) / 10000)
        diff = dt1 - dt2
        self.assertEqual(expDiff,
                         (diff.days, diff.seconds, diff.microseconds),
                         "Expected datetime diff %d/%d/%d not %d/%d/%d" %
                         (expDiff[0], expDiff[1], expDiff[2],
                          diff.days, diff.seconds, diff.microseconds))

        dt1 = DAQDateTime(t1[0], t1[1], t1[2], t1[3], t1[4], t1[5], t1[6])
        dt2 = DAQDateTime(t2[0], t2[1], t2[2], t2[3], t2[4], t2[5], t2[6])
        diff = dt1 - dt2

        self.assertEqual(expDiff[0], diff.days,
                         ("DAQDateTime days %d should be %d" +
                          " (%d/%d/%d vs. %d/%d/%d)") %
                         (diff.days, expDiff[0], expDiff[0],
                          expDiff[1], expDiff[2], diff.days, diff.seconds,
                          diff.microseconds))
        self.assertEqual(expDiff[1], diff.seconds,
                         ("DAQDateTime seconds %d should be %d" +
                          " (%d/%d/%d vs. %d/%d/%d)") %
                         (diff.seconds, expDiff[1], expDiff[0],
                          expDiff[1], expDiff[2], diff.days, diff.seconds,
                          diff.microseconds))
        self.assertEqual(expDiff[2], diff.microseconds,
                         ("DAQDateTime microseconds %d should be %d" +
                          " (%d/%d/%d vs. %d/%d/%d)") %
                         (diff.microseconds, expDiff[2], expDiff[0],
                          expDiff[1], expDiff[2], diff.days, diff.seconds,
                          diff.microseconds))

    def testDeltaSecSubsec(self):
        self.__validateDelta((self.CUR_YEAR, 4, 3, 15, 28, 0, 450989000),
                             (self.CUR_YEAR, 4, 3, 15, 25, 59, 587731000),
                             (0, 120, 986325))

    def testDeltaHrSecSubsec(self):
        self.__validateDelta((self.CUR_YEAR, 4, 3, 15, 28, 0, 450989000),
                             (self.CUR_YEAR, 4, 3, 14, 25, 59, 587731000),
                             (0, 3720, 986325))

    def testDeltaDayHrSecSubsec(self):
        self.__validateDelta((self.CUR_YEAR, 4, 3, 15, 28, 0, 450989000),
                             (self.CUR_YEAR, 4, 2, 14, 25, 59, 587731000),
                             (1, 3720, 986325))

    def testRepr(self):
        fmtstr = "DAQDateTime(%d, 1, 10, 10, 19, 23, 987654%04.4d%s)"

        low_digits = 3210
        if not DAQDateTime.HIGH_PRECISION:
            short_digits = 0
            hpStr = ""
        else:
            short_digits = low_digits
            hpStr = ", high_precision=True"

        expStr = fmtstr % (self.CUR_YEAR, low_digits, hpStr)
        shortStr = fmtstr % (self.CUR_YEAR, short_digits, hpStr)
        dt = eval(expStr)
        self.assertEqual(shortStr, repr(dt),
                         "Expected repr %s, not %s" % (shortStr, repr(dt)))

    def testReprHP(self):
        expStr = ("DAQDateTime(%d, 1, 10, 10, 19, 23, 9876543210," +
                  " high_precision=True)") % self.CUR_YEAR
        dt = eval(expStr)
        self.assertEqual(expStr, repr(dt),
                         "Expected repr %s, not %s" % (expStr, repr(dt)))

    def testCompareNone(self):
        dt0 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        dt1 = None
        self.__checkCompare(dt0, dt1, -1)

    def testCompareEqual(self):
        dt0 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        dt1 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        self.__checkCompare(dt0, dt1, 0)

    def testCompareDiffer(self):
        dt0 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        dt1 = DAQDateTime(2011, 1, 1, 1, 1, 1, 0)
        self.__checkCompare(dt0, dt1, 1)

    def testFromStringNone(self):
        self.assertEqual(PayloadTime.fromString(None), None)

    def testFromString(self):
        expStr = "DAQDateTime(%d, 1, 10, 10, 19, 23, 987654321)" % \
            self.CUR_YEAR
        dt0 = eval(expStr)
        dt1 = PayloadTime.fromString(str(dt0))
        self.__checkCompare(dt0, dt1, 0)

    def testCompareStringEqual(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR

        dt0 = PayloadTime.fromString(base + ".0001000000")
        dt1 = PayloadTime.fromString(base + ".0001")
        self.__checkCompare(dt0, dt1, 0)

        dt0 = PayloadTime.fromString(base + ".0001000000")
        dt1 = PayloadTime.fromString(base + ".00010000")
        self.__checkCompare(dt0, dt1, 0)

        dt0 = PayloadTime.fromString(base + ".0000000000")
        dt1 = PayloadTime.fromString(base)
        self.__checkCompare(dt0, dt1, 0)

    def testCompareStringDiffer(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR
        dt0 = PayloadTime.fromString(base + ".000001")
        dt1 = PayloadTime.fromString(base + ".0")
        self.__checkCompare(dt0, dt1, 1)

    def testCompareStringDifferHP(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR
        dt0 = PayloadTime.fromString(base + ".0000000001", high_precision=True)
        dt1 = PayloadTime.fromString(base + ".0", high_precision=True)
        self.__checkCompare(dt0, dt1, 1)

    def testCompareStringDifferMixed(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR
        dt0 = PayloadTime.fromString(base + ".0000000001", high_precision=True)
        dt1 = PayloadTime.fromString(base + ".0")
        self.__checkCompare(dt0, dt1, 1)

if __name__ == '__main__':
    unittest.main()
