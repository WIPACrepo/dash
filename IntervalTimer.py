#!/usr/bin/env python

from datetime import datetime, timedelta

class IntervalTimer(object):
    """
    Timer which triggers each time the specified number of seconds has passed.
    """
    def __init__(self, name, interval, startTriggered=False):
        self.__name = name
        self.__isTime = startTriggered
        self.__nextTime = None
        self.__interval = interval

    def isTime(self, now=None):
        "Return True if another interval has passed"
        if not self.__isTime:
            secsLeft = self.timeLeft(now)

            if secsLeft <= 0.0:
                self.__isTime = True

        return self.__isTime

    def reset(self):
        "Reset timer for the next interval"
        self.__nextTime = datetime.now()
        self.__isTime = False

    def timeLeft(self, now=None):
        if self.__isTime:
            return 0.0

        if now is None:
            now = datetime.now()
        if self.__nextTime is None:
            self.__nextTime = now

        dt  = now - self.__nextTime

        secs = dt.seconds + (dt.microseconds * 0.000001)
        return self.__interval - secs
