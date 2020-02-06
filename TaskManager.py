#!/usr/bin/env python

import sys
import threading

from ActiveDOMsTask import ActiveDOMsTask
from CnCTask import CnCTask, TaskException
from IntervalTimer import IntervalTimer
from MonitorTask import MonitorTask
from RateTask import RateTask
from WatchdogTask import WatchdogTask
from i3helper import reraise_excinfo

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class TaskManager(threading.Thread):
    "Manage RunSet tasks"

    def __init__(self, runset, dashlog, live_moni, rundir, run_cfg,
                 run_options):
        if dashlog is None:
            raise TaskException("Dash logfile cannot be None")

        self.__runset = runset
        self.__dashlog = dashlog

        self.__running = False
        self.__stopping = False
        self.__flag = threading.Condition()

        super(TaskManager, self).__init__(name="TaskManager")
        self.setDaemon(True)

        self.__tasks = self.__create_all_tasks(live_moni, rundir, run_cfg,
                                               run_options)

    def __create_all_tasks(self, live_moni, rundir, run_cfg, run_options):
        """
        This method exists solely to make it easy to detect
        errors in the task constructors.
        """
        taskList = []

        task_num = 0
        while True:
            try:
                task = self.__create_task(task_num, live_moni, rundir,
                                          run_cfg, run_options)
                if task is None:
                    break
                taskList.append(task)
            except:
                self.__dashlog.error("Cannot create task#%d: %s" %
                                     (task_num, exc_string()))
            task_num += 1

        return taskList

    def __create_task(self, task_num, live_moni, rundir, run_cfg, run_options):
        """
        Create a single task.  There's nothing magic about 'task_num',
        it's just a convenient way to iterate through all the task
        constructors.
        """
        if task_num == 0:
            return MonitorTask(self, self.__runset, self.__dashlog, live_moni,
                               rundir, run_options,
                               period=run_cfg.monitorPeriod)
        elif task_num == 1:
            return RateTask(self, self.__runset, self.__dashlog)
        elif task_num == 2:
            return ActiveDOMsTask(self, self.__runset, self.__dashlog,
                                  live_moni)
        elif task_num == 3:
            return WatchdogTask(self, self.__runset, self.__dashlog,
                                initial_health=12,
                                period=run_cfg.watchdogPeriod)

        return None

    def __run(self):
        self.__running = True
        while not self.__stopping:
            wait_secs = CnCTask.MAX_TASK_SECS
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
                if wait_secs > taskSecs:
                    wait_secs = taskSecs

            if not self.__stopping:
                self.__flag.acquire()
                try:
                    self.__flag.wait(wait_secs)
                finally:
                    self.__flag.release()

        self.__running = False

        saved_exc = None
        for t in self.__tasks:
            try:
                t.close()
            except:
                if not saved_exc:
                    saved_exc = sys.exc_info()

        self.__stopping = False

        if saved_exc:
            reraise_excinfo(saved_exc)

    @classmethod
    def createIntervalTimer(cls, name, period):
        return IntervalTimer(name, period, start_triggered=True)

    @property
    def is_running(self):
        return self.__running

    @property
    def is_stopped(self):
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

    def set_error(self, caller_name):
        self.__runset.set_run_error(caller_name)

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
            t.wait_until_finished()
