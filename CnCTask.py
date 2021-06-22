#!/usr/bin/env python
"A task which is run at regular intervals"


class TaskException(Exception):
    "Base CnCTask exception"


class CnCTask(object):
    "A task which is run at regular intervals"

    # maximum seconds to wait for tasks
    MAX_TASK_SECS = 10.0

    def __init__(self, name, task_mgr, logger, timerName, timerPeriod):
        self.__name = name
        self.__task_mgr = task_mgr
        self.__logger = logger

        if timerName is None and timerPeriod is None:
            # if the name and/or period are undefined, this will never be run
            self.__timer = None
        else:
            # create and start the timer for this task
            self.__timer = \
                task_mgr.create_interval_timer(timerName, timerPeriod)

    def __str__(self):
        return self.__name

    def _check(self):
        "Deal with hanging threads and/or start new threads"
        raise NotImplementedError()

    def _reset(self):  # pylint: disable=no-self-use
        "Do task-specific cleanup at the end of the run"
        return

    def check(self):
        """
        Check the timer, start a task-specific thread if it's time, and
        return the amount of time remaining in the current interval
        """
        if not self.__timer:
            return self.MAX_TASK_SECS

        timer = self.__timer

        time_left = timer.time_left()
        if time_left > 0.0:
            return time_left

        timer.reset()

        self._check()

        return timer.time_left()

    def close(self):
        "Handle task-specific cleanup when the task is stopped"
        raise NotImplementedError()

    def end_timer(self):
        "Stop the timer forever"
        self.__timer = None

    def log_error(self, msg):
        "Log an error"
        self.__logger.error(msg)

    def logger(self):
        "Return this task's logger"
        return self.__logger

    def reset(self):
        "Reset everything at the end of the run"
        self.__timer = None
        self._reset()

    def set_error(self, caller_name):
        """
        Inform the task manager that this task has encountered an
        unrecoverable error and the run should be stopped
        """
        self.__task_mgr.set_error(caller_name)
