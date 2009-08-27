#!/usr/bin/env python

import datetime

class IntervalTimer(object):
    """
    Timer which triggers each time the specified interval has passed.
    """
    def __init__(self, interval):
        self.__isTime = False
        self.__tlast = None
        self.__interval = interval

    def isTime(self):
        "Return True if another interval has passed"
        if not self.__isTime:
            now = datetime.datetime.now()

            if not self.__tlast:
                self.__isTime = True
            else:
                dt  = now - self.__tlast

                if dt.seconds + (dt.microseconds * 0.000001) > self.__interval:
                    self.__isTime = True

        return self.__isTime

    def reset(self):
        self.__tlast = datetime.datetime.now()
        self.__isTime = False
