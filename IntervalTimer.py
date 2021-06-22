#!/usr/bin/env python
"Timer which triggers each time the specified number of seconds has passed"

from datetime import datetime


class IntervalTimer(object):
    """
    Timer which triggers each time the specified number of seconds has passed.
    """
    def __init__(self, name, interval, start_triggered=False):
        self.__name = name
        self.__is_time = start_triggered
        self.__next_time = None
        self.__interval = interval

    def is_time(self, now=None):
        "Return True if another interval has passed"
        if not self.__is_time:
            secs_left = self.time_left(now)

            if secs_left <= 0.0:
                self.__is_time = True

        return self.__is_time

    def reset(self):
        "Reset timer for the next interval"
        self.__next_time = datetime.now()
        self.__is_time = False

    def time_left(self, now=None):
        "Return the number of seconds remaining in this interval"
        if self.__is_time:
            return 0.0

        if now is None:
            now = datetime.now()
        if self.__next_time is None:
            self.__next_time = now

        dtm = now - self.__next_time

        secs = dtm.seconds + (dtm.microseconds * 0.000001)
        return self.__interval - secs
