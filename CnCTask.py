#!/usr/bin/env python

class TaskException(Exception): pass

class CnCTask(object):

    # maximum seconds to wait for tasks
    MAX_TASK_SECS = 10.0

    def __init__(self, name, taskMgr, logger, debugBit, timerName,
                 timerPeriod):
        self.__name = name
        self.__taskMgr = taskMgr
        self.__logger = logger
        self.__debugBit = debugBit
        self.__debug = False

        if timerName is None and timerPeriod is None:
            self.__timer = None
        else:
            self.__timer = \
                taskMgr.createIntervalTimer(timerName, timerPeriod)

    def __str__(self):
        return self.__name

    def _check(self):
        raise Exception("Unimplemented")

    def _reset(self): pass

    def check(self):
        if not self.__timer:
            return self.MAX_TASK_SECS

        timer = self.__timer

        timeLeft = timer.timeLeft()
        if timeLeft > 0.0:
            return timeLeft

        timer.reset()

        self._check()

        return timer.timeLeft()

    def close(self):
        raise Exception("Unimplemented")

    def endTimer(self):
        self.__timer = None

    def logDebug(self, msg):
        if self.__debug:
            self.__logger.error(msg)

    def logError(self, msg):
        self.__logger.error(msg)

    def logger(self):
        return self.__logger

    def reset(self):
        self.__timer = None
        self._reset()

    def setDebug(self, debugBits):
        self.__debug = ((debugBits & self.__debugBit) == self.__debugBit)

    def setError(self):
        self.__taskMgr.setError()

    def waitUntilFinished(self):
        raise Exception("Unimplemented")
