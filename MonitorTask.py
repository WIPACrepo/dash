#!/usr/bin/env python
"Monitor pDAQ components"

from __future__ import print_function

import datetime
import os
import threading
import sys

from CnCTask import CnCTask
from CnCThread import CnCThread
from DAQClient import BeanLoadException, BeanTimeoutException
from LiveImports import Prio
from RunOption import RunOption
from decorators import classproperty
from i3helper import reraise_excinfo

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class MonitorThread(CnCThread):
    "Monitoring thread"

    def __init__(self, compname, dashlog):
        "Create a monitoring thread"
        self.__dashlog = dashlog

        self.__warned = False

        super(MonitorThread, self).__init__(compname, dashlog)

    def _run(self):
        "Run the task"
        raise NotImplementedError("Unimplemented")

    @property
    def dashlog(self):
        "Return the current log object"
        return self.__dashlog

    def get_new_thread(self):
        "Create a new monitoring thread"
        raise NotImplementedError("Unimplemented")

    @property
    def is_warned(self):
        "Return True if the user has been warned"
        return self.__warned

    @is_warned.setter
    def is_warned(self, val):
        "Set the 'is_warned' flag"
        self.__warned = val

    @property
    def refused_count(self):
        "Return count of failed monitoring requests"
        raise NotImplementedError("Unimplemented")


class MBeanThread(MonitorThread):
    "MBean monitoring thread"

    def __init__(self, comp, run_dir, live_moni, run_options, dashlog,
                 reporter=None, refused=0):
        "Create an MBean monitoring thread"
        self.__comp = comp
        self.__run_dir = run_dir
        self.__live_moni = live_moni
        self.__run_options = run_options
        self.__reporter = reporter
        self.__refused = refused
        self.__reporter_lock = threading.Lock()

        self.__mbean_client = comp.create_mbean_client()

        super(MBeanThread, self).__init__(comp.fullname, dashlog)

    def __create_reporter(self):
        "Create a monitoring reporter object"
        if RunOption.is_moni_to_both(self.__run_options) and \
               self.__live_moni is not None:
            return MonitorToBoth(self.__run_dir, self.__comp.filename,
                                 self.__live_moni)
        if RunOption.is_moni_to_file(self.__run_options):
            if self.__run_dir is not None:
                return MonitorToFile(self.__run_dir, self.__comp.filename)
        if RunOption.is_moni_to_live(self.__run_options) and \
           self.__live_moni is not None:
            return MonitorToLive(self.__comp.filename, self.__live_moni)

        return None

    def __fetch_dictionary(self):
        "Fetch the MBean dictionary from the remote component"
        try:
            bean_dict = self.__mbean_client.get_dictionary()
            self.__refused = 0
        except BeanTimeoutException:
            bean_dict = None
            if not self.is_closed:
                self.__refused += 1
        except BeanLoadException:
            bean_dict = None
            if not self.is_closed:
                self.__refused += 1
                self.error("Could not load monitoring data from %s" %
                           (self.__mbean_client, ))
        except:  # pylint: disable=bare-except
            bean_dict = None
            if not self.is_closed:
                self.error("Ignoring %s: %s" %
                           (self.__mbean_client, exc_string()))

        if bean_dict is not None:
            if not isinstance(bean_dict, dict):
                self.error("%s get_dictionary() returned %s, not dict (%s)" %
                           (self.__mbean_client.fullname,
                            type(bean_dict).__name__, bean_dict))
            elif len(bean_dict) > 0:  # pylint: disable=len-as-condition
                # report monitoring data
                with self.__reporter_lock:
                    reporter = self.__reporter
                for key, data in list(bean_dict.items()):
                    if not self.is_closed:
                        reporter.send(datetime.datetime.now(), key, data)

    def _run(self):
        "Run the task"
        if self.is_closed:
            return -1

        if self.__reporter is None:
            self.__reporter = self.__create_reporter()
            if self.__reporter is None:
                return -1

        self.__fetch_dictionary()

        return self.__refused

    def close(self):
        "Close this thread"
        if not self.is_closed:
            with self.__reporter_lock:
                if self.__reporter is not None:
                    try:
                        self.__reporter.close()
                    except:  # pylint: disable=bare-except
                        self.error(("Could not close %s monitor thread: %s") %
                                   (self.__mbean_client.fullname,
                                    exc_string()))

                super(MBeanThread, self).close()

    def get_new_thread(self):
        "Create a new monitoring thread"
        thrd = MBeanThread(self.__comp, self.__run_dir, self.__live_moni,
                           self.__run_options, self.dashlog,
                           self.__reporter, self.__refused)
        return thrd

    @property
    def refused_count(self):
        "Return count of failed monitoring requests"
        return self.__refused


class CnCMoniThread(MonitorThread):
    "Thread to monitor pDAQ component MBean data"

    def __init__(self, runset, rundir, write_to_file, dashlog, reporter=None):
        "Create a monitoring thread"
        self.__runset = runset
        self.__rundir = rundir
        self.__reporter = reporter

        self.__write_to_file = write_to_file

        super(CnCMoniThread, self).__init__("CnCServer", dashlog)

    def __create_reporter(self):
        "Create a monitoring reporter object"
        if self.__write_to_file:
            if self.__rundir is not None:
                return MonitorToFile(self.__rundir, "cncServer")

        return None

    def _run(self):
        "Run the task"
        if self.is_closed:
            return

        if self.__reporter is None:
            self.__reporter = self.__create_reporter()
            if self.__reporter is None:
                return

        cstats = self.__runset.client_statistics
        if cstats is not None and \
          len(cstats) > 0:  # pylint: disable=len-as-condition
            self.__reporter.send(datetime.datetime.now(), "client", cstats)

    def get_new_thread(self):
        "Create a new copy of this thread"
        thrd = CnCMoniThread(self.__runset, self.__rundir,
                             self.__write_to_file, self.dashlog,
                             reporter=self.__reporter)
        return thrd

    @property
    def refused_count(self):
        "Return count of failed monitoring requests"
        return 0


class MonitorToFile(object):
    "Write monitoring info to a file"
    def __init__(self, dirname, basename):
        "Open pDAQ monitoring file"
        if dirname is None:
            self.__fd = None
        else:
            self.__fd = open(os.path.join(dirname, basename + ".moni"), "w")
        self.__fd_lock = threading.Lock()

    def close(self):
        "Close pDAQ monitoring file"
        with self.__fd_lock:
            if self.__fd is not None:
                self.__fd.close()
                self.__fd = None

    def send(self, now, bean_name, attrs):
        "Send monitoring data to pDAQ file"
        with self.__fd_lock:
            if self.__fd is not None:
                print("%s: %s:" % (bean_name, now), file=self.__fd)
                for key in attrs:
                    print("\t%s: %s" % (key, attrs[key]), file=self.__fd)
                print(file=self.__fd)
                self.__fd.flush()


class MonitorToLive(object):
    "Send monitoring info to I3Live"
    def __init__(self, name, live_moni):
        "Create I3Live monitoring object"
        self.__name = name
        self.__live_moni = live_moni

    def close(self):  # pylint: disable=no-self-use
        "Close I3Live monitoring object"
        return

    def send(self, now, bean_name, attrs):
        "Send monitoring data to I3Live"
        if self.__live_moni is not None:
            for key in attrs:
                self.__live_moni.sendMoni("%s*%s+%s" % (self.__name, bean_name,
                                                        key), attrs[key],
                                          Prio.ITS, now)


class MonitorToBoth(object):
    "Send monitoring info to both I3Live and pDAQ"
    def __init__(self, dirname, basename, live_moni):
        "Create I3Live and pDAQ monitoring objects"
        self.__file = MonitorToFile(dirname, basename)
        self.__live = MonitorToLive(basename, live_moni)

    def close(self):
        "Close I3Live and pDAQ monitoring objects"
        self.__file.close()
        self.__live.close()

    def send(self, now, bean_name, attrs):
        "Send monitoring data to both I3Live and to a pDAQ file"
        self.__file.send(now, bean_name, attrs)
        self.__live.send(now, bean_name, attrs)


class MonitorTask(CnCTask):
    "Monitor all components"
    __NAME = "Monitoring"
    __PERIOD = 100

    MAX_REFUSED = 3

    MONITOR_CNCSERVER = False

    def __init__(self, task_mgr, runset, dashlog, live_moni, run_dir,
                 run_options, period=None):
        if period is None:
            period = self.period

        super(MonitorTask, self).__init__(self.name, task_mgr, dashlog,
                                          self.name, period)

        self.__thread_list = self.__create_threads(runset, dashlog, live_moni,
                                                   run_dir, run_options)

    def __create_threads(self, runset, dashlog, live_moni, run_dir,
                         run_options):
        thread_list = {}

        if not RunOption.is_moni_to_none(run_options):
            for comp in runset.components:
                # refresh MBean info to pick up any new MBeans
                comp.mbean.reload()

                thread_list[comp] = self.create_thread(comp, run_dir,
                                                       live_moni, run_options,
                                                       dashlog)

            if self.MONITOR_CNCSERVER:
                to_file = RunOption.is_moni_to_file(run_options)
                thread_list["CnCServer"] \
                    = self.__create_moni_thread(runset, run_dir, to_file,
                                                dashlog)

        return thread_list

    def _check(self):
        for key in list(self.__thread_list.keys()):
            thrd = self.__thread_list[key]
            if not thrd.is_alive():
                if thrd.refused_count >= self.MAX_REFUSED:
                    if not thrd.is_warned:
                        msg = ("ERROR: Not monitoring %s: Connect failed" +
                               " %d times") % \
                               (key.fullname, thrd.refused_count)
                        self.log_error(msg)
                        thrd.is_warned = True
                    continue
                self.__thread_list[key] = thrd.get_new_thread()
                self.__thread_list[key].start()

    @classmethod
    def create_thread(cls, comp, run_dir, live_moni, run_options, dashlog):
        "Create an MBean monitoring thread"
        return MBeanThread(comp, run_dir, live_moni, run_options, dashlog)

    @classmethod
    def __create_moni_thread(cls, runset, run_dir, to_file, dashlog):
        "Create a monitoring thread"
        return CnCMoniThread(runset, run_dir, to_file, dashlog)

    def close(self):
        "Close everything associated with this task"
        saved_exc = None
        for thr in list(self.__thread_list.values()):
            try:
                thr.close()
            except:  # pylint: disable=bare-except
                if not saved_exc:
                    saved_exc = sys.exc_info()

        if saved_exc:
            reraise_excinfo(saved_exc)

    @classproperty
    def name(cls):  # pylint: disable=no-self-argument
        "Name of this task"
        return cls.__NAME

    @property
    def open_threads(self):
        "Return number of open threads"
        num = 0
        for key in list(self.__thread_list.keys()):
            if not self.__thread_list[key].is_closed:
                num += 1
        return num

    @classproperty
    def period(cls):  # pylint: disable=no-self-argument
        "Number of seconds between tasks"
        return cls.__PERIOD

    def wait_until_finished(self):
        "Wait until all threads have finished"
        for key in list(self.__thread_list.keys()):
            if self.__thread_list[key].is_alive():
                self.__thread_list[key].join()
