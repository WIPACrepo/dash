#!/usr/bin/env python


class TaskException(Exception):
    pass


class CnCTask(object):
    "A task which is run at regular intervals"

    # maximum seconds to wait for tasks
    MAX_TASK_SECS = 10.0

    def __init__(self, name, taskMgr, logger, timerName, timerPeriod):
        self.__name = name
        self.__taskMgr = taskMgr
        self.__logger = logger

        if timerName is None and timerPeriod is None:
            # if the name and/or period are undefined, this will never be run
            self.__timer = None
        else:
            # create and start the timer for this task
            self.__timer = \
                taskMgr.createIntervalTimer(timerName, timerPeriod)

    def __str__(self):
        return self.__name

    def _check(self):
        "Deal with hanging threads and/or start new threads"
        raise NotImplementedError()

    def _reset(self):
        "Do task-specific cleanup at the end of the run"
        pass

    def check(self):
        """
        Check the timer, start a task-specific thread if it's time, and
        return the amount of time remaining in the current interval
        """
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
        "Handle task-specific cleanup when the task is stopped"
        raise NotImplementedError()

    def endTimer(self):
        "Stop the timer forever"
        self.__timer = None

    def logError(self, msg):
        "Log an error"
        self.__logger.error(msg)

    def logger(self):
        "Return this task's logger"
        return self.__logger

    def reset(self):
        "Reset everything at the end of the run"
        self.__timer = None
        self._reset()

    def setError(self, callerName):
        """
        Inform the task manager that this task has encountered an
        unrecoverable error and the run should be stopped
        """
        self.__taskMgr.setError(callerName)
