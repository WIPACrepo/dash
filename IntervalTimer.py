#!/usr/bin/env python

from datetime import datetime, timedelta

class IntervalTimer(object):
    """
    Timer which triggers each time the specified number of seconds has passed.
    """
    def __init__(self, interval):
        self.__isTime = False
        self.__nextTime = None
        self.__interval = interval

    def isTime(self):
        "Return True if another interval has passed"
        if not self.__isTime:
            now = datetime.now()

            if not self.__nextTime:
                self.__nextTime = now
                self.__isTime = True
            else:
                dt  = now - self.__nextTime

                if dt.seconds + (dt.microseconds * 0.000001) > self.__interval:
                    self.__isTime = True

        return self.__isTime

    def reset(self):
        "Reset timer for the next interval"
        self.__nextTime = datetime.now()
        self.__isTime = False
