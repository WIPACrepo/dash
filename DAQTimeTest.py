#!/usr/bin/env python

import calendar
import datetime
import time
import unittest
from DAQTime import DAQDateTime, PayloadTime
from locate_pdaq import set_pdaq_config_dir


class MockPayloadTime(PayloadTime):
    """
    Wrapper which allows tests to change the "current" year
    """
    MOCK_YEAR = None

    @classmethod
    def get_current_year(cls):
        return cls.MOCK_YEAR


class TestDAQTime(unittest.TestCase):
    TICKS_PER_SEC = 10000000000
    CUR_YEAR = None

    def __compare(self, name, valid, to_check):
        self.assertEqual(valid, to_check,
                         "Expected %s %s, not %s" % (name, valid, to_check))

    @staticmethod
    def __compare_dates(dttm0, dttm1):
        if dttm0 == dttm1:
            return 0
        if dttm0 < dttm1:
            return -1
        if dttm0 > dttm1:
            return 1

        raise Exception("Comparison always fails (<%s>%s <=> <%s>%s)" %
                        (type(dttm0), dttm0, type(dttm1), dttm1))

    def __check_compare(self, dttm0, dttm1, exp_result):
        result = self.__compare_dates(dttm0, dttm1)
        self.assertEqual(exp_result, result,
                         "Expected cmp(%s, %s) to return %s, not %s" %
                         (dttm0, dttm1, exp_result, result))

        result = self.__compare_dates(dttm1, dttm0)
        self.assertEqual(-exp_result, result,
                         "Expected inverted cmp(%s, %s) to return %s, not %s" %
                         (dttm1, dttm0, -exp_result, result))

    @classmethod
    def __date_format(cls, year, mon, day, hour, minutes, sec, usec,
                      high_precision=False):
        if high_precision:
            subsecstr = "%010d" % usec
        else:
            subsecstr = "%06d" % (usec / 10000)
        return "%04d-%02d-%02d %02d:%02d:%02d.%s" % \
            (year, mon, day, hour, minutes, sec, subsecstr)

    @classmethod
    def __delta_format(cls, days, hours, minutes, sec, usec):
        rtnstr = "%d day" % days
        if days != 1:
            rtnstr += "s"
        rtnstr += ", %d:%02d:%02d" % (hours, minutes, sec)
        if usec > 0:
            rtnstr += ".%06d" % usec
        return rtnstr

    def setUp(self):
        if self.CUR_YEAR is None:
            self.CUR_YEAR = PayloadTime.get_current_year()

        set_pdaq_config_dir("src/test/resources/config", override=True)

    def tearDown(self):
        set_pdaq_config_dir(None, override=True)

    def test_payload_time_none(self):
        self.assertEqual(PayloadTime.to_date_time(None), None)

    def test_payload_time_zero(self):
        dttm = PayloadTime.to_date_time(0, high_precision=False)
        expstr = self.__date_format(self.CUR_YEAR, 1, 1, 0, 0, 0, 0)
        self.assertEqual(expstr, str(dttm),
                         "Expected date %s, not %s" % (expstr, dttm))

    def test_payload_time_zero_h_p(self):
        dttm = PayloadTime.to_date_time(0, high_precision=True)
        expstr = self.__date_format(self.CUR_YEAR, 1, 1, 0, 0, 0, 0,
                                    high_precision=True)
        self.assertEqual(expstr, str(dttm),
                         "Expected date %s, not %s" % (expstr, dttm))

    def test_payload_time_one_sec(self):
        dttm = PayloadTime.to_date_time(self.TICKS_PER_SEC,
                                        high_precision=False)
        expstr = self.__date_format(self.CUR_YEAR, 1, 1, 0, 0, 1, 0)
        self.assertEqual(expstr, str(dttm),
                         "Expected date %s, not %s" % (expstr, dttm))

    def test_payload_time_one_sec_h_p(self):
        dttm = PayloadTime.to_date_time(self.TICKS_PER_SEC,
                                        high_precision=True)
        expstr = self.__date_format(self.CUR_YEAR, 1, 1, 0, 0, 1, 0,
                                    high_precision=True)
        self.assertEqual(expstr, str(dttm),
                         "Expected date %s, not %s" % (expstr, dttm))

    def test_delta_one_day(self):
        jan1 = time.struct_time((self.CUR_YEAR, 1, 1, 0, 0, 0, 0, 0, -1))
        jan2 = time.struct_time((self.CUR_YEAR, 1, 2, 0, 0, 0, 0, 0, -1))
        dayticks = int(calendar.timegm(jan2) - calendar.timegm(jan1)) * \
            self.TICKS_PER_SEC

        dttm0 = PayloadTime.to_date_time(0)
        dttm1 = PayloadTime.to_date_time(dayticks)

        expstr = self.__delta_format(1, 0, 0, 0, 0)
        self.assertEqual(expstr, str(dttm1 - dttm0),
                         "Expected delta %s, not %s" % (expstr, dttm1 - dttm0))

        expstr = self.__delta_format(-1, 0, 0, 0, 0)
        self.assertEqual(expstr, str(dttm0 - dttm1),
                         "Expected delta2 %s, not %s" % (expstr, dttm0 - dttm1))

    def test_delta_two_weeks(self):
        jan1 = time.struct_time((self.CUR_YEAR, 1, 1, 0, 0, 0, 0, 0, -1))
        jan15 = time.struct_time((self.CUR_YEAR, 1, 15, 3, 2, 1, 0, 0, -1))
        usec = 101100
        dayticks = int(calendar.timegm(jan15) - calendar.timegm(jan1)) * \
            self.TICKS_PER_SEC + (usec * 10000)

        dttm0 = PayloadTime.to_date_time(0)
        dttm1 = PayloadTime.to_date_time(dayticks)

        expstr = self.__delta_format(14, 3, 2, 1, usec)
        self.assertEqual(expstr, str(dttm1 - dttm0),
                         "Expected delta %s, not %s" % (expstr, dttm1 - dttm0))

        expstr = self.__delta_format(-15, 20, 57, 58, 898900)
        self.assertEqual(expstr, str(dttm0 - dttm1),
                         "Expected delta2 %s, not %s" % (expstr, dttm0 - dttm1))

    def test_delta_two_weeks_h_p(self):
        jan1 = time.struct_time((self.CUR_YEAR, 1, 1, 0, 0, 0, 0, 0, -1))
        jan15 = time.struct_time((self.CUR_YEAR, 1, 15, 3, 2, 1, 0, 0, -1))
        usec = 101100
        dayticks = int(calendar.timegm(jan15) - calendar.timegm(jan1)) * \
            self.TICKS_PER_SEC + (usec * 10000)

        dttm0 = PayloadTime.to_date_time(0, high_precision=True)
        dttm1 = PayloadTime.to_date_time(dayticks, high_precision=True)

        expstr = self.__delta_format(14, 3, 2, 1, usec)
        self.assertEqual(expstr, str(dttm1 - dttm0),
                         "Expected delta %s, not %s" % (expstr, dttm1 - dttm0))

        expstr = self.__delta_format(-15, 20, 57, 58, 898900)
        self.assertEqual(expstr, str(dttm0 - dttm1),
                         "Expected delta2 %s, not %s" % (expstr, dttm0 - dttm1))

    def test_delta_subsec(self):
        self.__validate_delta((self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210),
                              (self.CUR_YEAR, 1, 10, 10, 19, 23, 8765432109),
                              (0, 0, 111111))

    def __validate_delta(self, tm1, tm2, exp_diff):
        dttm1 = datetime.datetime(tm1[0], tm1[1], tm1[2], tm1[3], tm1[4],
                                  tm1[5], int((tm1[6] + 500) / 10000))
        dttm2 = datetime.datetime(tm2[0], tm2[1], tm2[2], tm2[3], tm2[4],
                                  tm2[5], int((tm2[6] + 500) / 10000))
        diff = dttm1 - dttm2
        self.assertEqual(exp_diff,
                         (diff.days, diff.seconds, diff.microseconds),
                         "Expected datetime diff %d/%d/%d not %d/%d/%d" %
                         (exp_diff[0], exp_diff[1], exp_diff[2],
                          diff.days, diff.seconds, diff.microseconds))

        dttm1 = DAQDateTime(tm1[0], tm1[1], tm1[2], tm1[3], tm1[4], tm1[5],
                            tm1[6])
        dttm2 = DAQDateTime(tm2[0], tm2[1], tm2[2], tm2[3], tm2[4], tm2[5],
                            tm2[6])
        diff = dttm1 - dttm2

        self.assertEqual(exp_diff[0], diff.days,
                         ("DAQDateTime days %d should be %d" +
                          " (%d/%d/%d vs. %d/%d/%d)") %
                         (diff.days, exp_diff[0], exp_diff[0],
                          exp_diff[1], exp_diff[2], diff.days, diff.seconds,
                          diff.microseconds))
        self.assertEqual(exp_diff[1], diff.seconds,
                         ("DAQDateTime seconds %d should be %d" +
                          " (%d/%d/%d vs. %d/%d/%d)") %
                         (diff.seconds, exp_diff[1], exp_diff[0],
                          exp_diff[1], exp_diff[2], diff.days, diff.seconds,
                          diff.microseconds))
        self.assertEqual(exp_diff[2], diff.microseconds,
                         ("DAQDateTime microseconds %d should be %d" +
                          " (%d/%d/%d vs. %d/%d/%d)") %
                         (diff.microseconds, exp_diff[2], exp_diff[0],
                          exp_diff[1], exp_diff[2], diff.days, diff.seconds,
                          diff.microseconds))

    def test_delta_sec_subsec(self):
        self.__validate_delta((self.CUR_YEAR, 4, 3, 15, 28, 0, 450989000),
                              (self.CUR_YEAR, 4, 3, 15, 25, 59, 587731000),
                              (0, 120, 986325))

    def test_delta_hr_sec_subsec(self):
        self.__validate_delta((self.CUR_YEAR, 4, 3, 15, 28, 0, 450989000),
                              (self.CUR_YEAR, 4, 3, 14, 25, 59, 587731000),
                              (0, 3720, 986325))

    def test_delta_day_hr_sec_subsec(self):
        self.__validate_delta((self.CUR_YEAR, 4, 3, 15, 28, 0, 450989000),
                              (self.CUR_YEAR, 4, 2, 14, 25, 59, 587731000),
                              (1, 3720, 986325))

    def test_repr(self):
        fmtstr = "DAQDateTime(%d, 1, 10, 10, 19, 23, 987654%04.4d%s)"

        low_digits = 3210
        if not DAQDateTime.HIGH_PRECISION:
            short_digits = 0
            hpstr = ""
        else:
            short_digits = low_digits
            hpstr = ", high_precision=True"

        expstr = fmtstr % (self.CUR_YEAR, low_digits, hpstr)
        shortstr = fmtstr % (self.CUR_YEAR, short_digits, hpstr)
        dttm = eval(expstr)
        self.assertEqual(shortstr, repr(dttm),
                         "Expected repr %s, not %s" % (shortstr, repr(dttm)))

    def test_repr_h_p(self):
        expstr = ("DAQDateTime(%d, 1, 10, 10, 19, 23, 9876543210," +
                  " high_precision=True)") % self.CUR_YEAR
        dttm = eval(expstr)
        self.assertEqual(expstr, repr(dttm),
                         "Expected repr %s, not %s" % (expstr, repr(dttm)))

    def test_compare_none(self):
        dttm0 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        dttm1 = None
        self.__check_compare(dttm0, dttm1, -1)

    def test_compare_equal(self):
        dttm0 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        dttm1 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        self.__check_compare(dttm0, dttm1, 0)

    def test_compare_differ(self):
        dttm0 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 9876543210)
        dttm1 = DAQDateTime(2011, 1, 1, 1, 1, 1, 0)
        self.__check_compare(dttm0, dttm1, 1)

    def test_from_string_none(self):
        self.assertEqual(PayloadTime.from_string(None), None)

    def test_from_string(self):
        dttm0 = DAQDateTime(self.CUR_YEAR, 1, 10, 10, 19, 23, 987654321)
        dttm1 = PayloadTime.from_string(str(dttm0))
        self.__check_compare(dttm0, dttm1, 0)

    def test_compare_string_equal(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR

        dttm0 = PayloadTime.from_string(base + ".0001000000")
        dttm1 = PayloadTime.from_string(base + ".0001")
        self.__check_compare(dttm0, dttm1, 0)

        dttm0 = PayloadTime.from_string(base + ".0001000000")
        dttm1 = PayloadTime.from_string(base + ".00010000")
        self.__check_compare(dttm0, dttm1, 0)

        dttm0 = PayloadTime.from_string(base + ".0000000000")
        dttm1 = PayloadTime.from_string(base)
        self.__check_compare(dttm0, dttm1, 0)

    def test_compare_string_differ(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR
        dttm0 = PayloadTime.from_string(base + ".000001")
        dttm1 = PayloadTime.from_string(base + ".0")
        self.__check_compare(dttm0, dttm1, 1)

    def test_compare_string_differ_h_p(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR
        dttm0 = PayloadTime.from_string(base + ".0000000001",
                                        high_precision=True)
        dttm1 = PayloadTime.from_string(base + ".0", high_precision=True)
        self.__check_compare(dttm0, dttm1, 1)

    def test_compare_string_differ_mixed(self):
        base = "%04d-01-10 10:19:23" % self.CUR_YEAR
        dttm0 = PayloadTime.from_string(base + ".0000000001",
                                        high_precision=True)
        dttm1 = PayloadTime.from_string(base + ".0")
        self.__check_compare(dttm0, dttm1, 1)

    def test_compare_leap_year(self):
        dttm = PayloadTime.to_date_time(199999990000000000, year=2012,
                                        high_precision=False)
        expstr = self.__date_format(2012, 8, 19, 11, 33, 18, 0)
        self.assertEqual(expstr, str(dttm),
                         "Expected date %s, not %s" % (expstr, dttm))

    def test_compare_non_leap_year(self):
        dttm = PayloadTime.to_date_time(199999990000000000, year=2013,
                                        high_precision=False)
        expstr = self.__date_format(2013, 8, 20, 11, 33, 19, 0)
        self.assertEqual(expstr, str(dttm),
                         "Expected date %s, not %s" % (expstr, dttm))

    def test_new_year(self):
        MockPayloadTime.MOCK_YEAR = self.CUR_YEAR

        one_day = 60 * 60 * 24
        dec31_ticks = ((one_day * 365) - 1) * MockPayloadTime.TICKS_PER_SECOND

        ny_eve = MockPayloadTime.to_date_time(dec31_ticks)
        self.__compare("NY Eve year", self.CUR_YEAR, ny_eve.year)
        self.__compare("NY Eve month", 12, ny_eve.month)
        # ignore ny_eve.day, it could be the 30th if this is a leap year
        self.__compare("NY Eve hour", 23, ny_eve.hour)
        self.__compare("NY Eve minute", 59, ny_eve.minute)
        self.__compare("NY Eve second", 59, ny_eve.second)

        # Happy New Year!
        MockPayloadTime.MOCK_YEAR = self.CUR_YEAR + 1

        ny_day = MockPayloadTime.to_date_time(MockPayloadTime.TICKS_PER_SECOND)
        self.__compare("NY Day year", self.CUR_YEAR + 1, ny_day.year)
        self.__compare("NY Day month", 1, ny_day.month)
        self.__compare("NY Day day", 1, ny_day.day)
        self.__compare("NY Day hour", 0, ny_day.hour)
        self.__compare("NY Day minute", 0, ny_day.minute)
        self.__compare("NY Day second", 1, ny_day.second)


if __name__ == '__main__':
    unittest.main()
