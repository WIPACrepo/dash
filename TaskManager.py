#!/usr/bin/env python

import sys
import threading

from ActiveDOMsTask import ActiveDOMsTask
from CnCTask import CnCTask, TaskException
from IntervalTimer import IntervalTimer
from MonitorTask import MonitorTask
from RateTask import RateTask
from WatchdogTask import WatchdogTask

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class TaskManager(threading.Thread):
    "Manage RunSet tasks"

    def __init__(self, runset, dashlog, liveMoni, runDir, runCfg, runOptions):
        if dashlog is None:
            raise TaskException("Dash logfile cannot be None")

        self.__runset = runset
        self.__dashlog = dashlog

        self.__tasks = self.__createAllTasks(liveMoni, runDir, runCfg,
                                             runOptions)

        self.__running = False
        self.__stopping = False
        self.__flag = threading.Condition()

        super(TaskManager, self).__init__(name="TaskManager")
        self.setDaemon(True)

    def __createAllTasks(self, liveMoni, runDir, runCfg, runOptions):
        """
        This method exists solely to make it easy to detect
        errors in the task constructors.
        """
        taskList = []

        taskNum = 0
        while True:
            try:
                task = self.__createTask(taskNum, liveMoni, runDir,
                                         runCfg, runOptions)
                if task is None:
                    break
                taskList.append(task)
            except:
                self.__dashlog.error("Cannot create task#%d: %s" %
                                     (taskNum, exc_string()))
            taskNum += 1

        return taskList

    def __createTask(self, taskNum, liveMoni, runDir, runCfg, runOptions):
        """
        Create a single task.  There's nothing magic about 'taskNum',
        it's just a convenient way to iterate through all the task
        constructors.
        """
        if taskNum == 0:
            return MonitorTask(self, self.__runset, self.__dashlog, liveMoni,
                               runDir, runOptions,
                               period=runCfg.monitorPeriod())
        elif taskNum == 1:
            return RateTask(self, self.__runset, self.__dashlog)
        elif taskNum == 2:
            return ActiveDOMsTask(self, self.__runset, self.__dashlog,
                                  liveMoni)
        elif taskNum == 3:
            return WatchdogTask(self, self.__runset, self.__dashlog,
                                period=runCfg.watchdogPeriod())

        return None

    def __run(self):
        self.__running = True
        while not self.__stopping:
            waitSecs = CnCTask.MAX_TASK_SECS
            for t in self.__tasks:
                # don't do remaining tasks if stop() has been called
                if self.__stopping:
                    break

                try:
                    taskSecs = t.check()
                except:
                    if self.__dashlog is not None:
                        self.__dashlog.error("%s exception: %s" %
                                             (str(t), exc_string()))
                    taskSecs = CnCTask.MAX_TASK_SECS
                if waitSecs > taskSecs:
                    waitSecs = taskSecs

            if not self.__stopping:
                self.__flag.acquire()
                try:
                    self.__flag.wait(waitSecs)
                finally:
                    self.__flag.release()

        self.__running = False

        savedEx = None
        for t in self.__tasks:
            try:
                t.close()
            except:
                if not savedEx:
                    savedEx = sys.exc_info()

        self.__stopping = False

        if savedEx:
            raise savedEx[0], savedEx[1], savedEx[2]

    @classmethod
    def createIntervalTimer(cls, name, period):
        return IntervalTimer(name, period, startTriggered=True)

    @property
    def isRunning(self):
        return self.__running

    @property
    def isStopped(self):
        return not self.__running and not self.__stopping

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

    def setError(self, callerName):
        self.__runset.setError(callerName)

    def stop(self):
        if self.__running and not self.__stopping:
            self.__flag.acquire()
            try:
                self.__stopping = True
                self.__flag.notify()
            finally:
                self.__flag.release()

    def waitForTasks(self):
        for t in self.__tasks:
            t.waitUntilFinished()
