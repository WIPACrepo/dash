#!/usr/bin/env python

import threading

from ActiveDOMsTask import ActiveDOMsTask
from CnCTask import CnCTask, TaskException
from IntervalTimer import IntervalTimer
from MonitorTask import MonitorTask
from RadarTask import RadarTask
from RateTask import RateTask
from RunSetDebug import RunSetDebug
from WatchdogTask import WatchdogTask

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class TaskManager(threading.Thread):
    "Manage RunSet tasks"

    def __init__(self, runset, dashlog, live, runDir, runCfg, runOptions):
        if dashlog is None:
            raise TaskException("Dash logfile cannot be None")

        self.__runset = runset
        self.__dashlog = dashlog

        self.__tasks = (MonitorTask(self, runset, dashlog, live, runDir,
                                    runOptions,
                                    period=runCfg.monitorPeriod()),
                        RateTask(self, runset, dashlog),
                        ActiveDOMsTask(self, runset, dashlog, live),
                        WatchdogTask(self, runset, dashlog,
                                     period=runCfg.watchdogPeriod()),
                        RadarTask(self, runset, dashlog, live))

        self.__running = False
        self.__flag = threading.Condition()

        super(TaskManager, self).__init__(name="TaskManager")
        self.setDaemon(True)

    def __run(self):
        self.__running = True
        while self.__running:
            waitSecs = CnCTask.MAX_TASK_SECS
            for t in self.__tasks:
                try:
                    taskSecs = t.check()
                except:
                    if self.__dashlog is not None:
                        self.__dashlog.error("%s exception: %s" %
                                             (str(t), exc_string()))
                    taskSecs = CnCTask.MAX_TASK_SECS
                if waitSecs > taskSecs:
                    waitSecs = taskSecs

            self.__flag.acquire()
            try:
                self.__flag.wait(waitSecs)
            finally:
                self.__flag.release()

        for t in self.__tasks:
            t.close()

    def createIntervalTimer(self, name, period):
        return IntervalTimer(name, period, startTriggered=True)

    def reset(self):
        for t in self.__tasks:
            t.reset()

    def run(self):
        try:
            self.__run()
        except:
            if self.__dashlog is not None:
                self.__dashlog.error(exc_string())

    def setDebugBits(self, debugBits):
        for t in self.__tasks:
            t.setDebug(debugBits)

    def setError(self):
        self.__runset.setError()

    def stop(self):
        self.__flag.acquire()
        try:
            self.__running = False
            self.__flag.notify()
        finally:
            self.__flag.release()

    def waitForTasks(self):
        for t in self.__tasks:
            t.waitUntilFinished()
