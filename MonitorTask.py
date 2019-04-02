#!/usr/bin/env python

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
from reraise import reraise_excinfo

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class MonitorThread(CnCThread):
    def __init__(self, compname, dashlog):
        self.__dashlog = dashlog

        self.__warned = False

        super(MonitorThread, self).__init__(compname, dashlog)

    def _run(self):
        raise NotImplementedError("Unimplemented")

    @property
    def dashlog(self):
        return self.__dashlog

    def get_new_thread(self):
        raise NotImplementedError("Unimplemented")

    @property
    def is_warned(self):
        return self.__warned

    @property
    def refused_count(self):
        raise NotImplementedError("Unimplemented")

    def set_warned(self):
        self.__warned = True


class MBeanThread(MonitorThread):
    # XXX Get rid of the !GET_DICTIONARY code after Tyranena is released
    GET_DICTIONARY = True

    def __init__(self, comp, runDir, liveMoni, runOptions, dashlog,
                 reporter=None, refused=0):
        self.__comp = comp
        self.__runDir = runDir
        self.__liveMoni = liveMoni
        self.__runOptions = runOptions
        self.__reporter = reporter
        self.__refused = refused
        self.__reporterLock = threading.Lock()

        self.__mbeanClient = comp.createMBeanClient()

        if not self.GET_DICTIONARY:
            self.__beanKeys = []
            self.__beanFlds = {}

        super(MBeanThread, self).__init__(comp.fullname, dashlog)

    def __create_reporter(self):
        if RunOption.isMoniToBoth(self.__runOptions) and \
               self.__liveMoni is not None:
            return MonitorToBoth(self.__runDir, self.__comp.filename,
                                 self.__liveMoni)
        if RunOption.isMoniToFile(self.__runOptions):
            if self.__runDir is not None:
                return MonitorToFile(self.__runDir, self.__comp.filename)
        if RunOption.isMoniToLive(self.__runOptions) and \
           self.__liveMoni is not None:
            return MonitorToLive(self.__comp.filename, self.__liveMoni)

        return None

    def __fetch_dictionary(self):
        try:
            beanDict = self.__mbeanClient.getDictionary()
            self.__refused = 0
        except BeanTimeoutException:
            beanDict = None
            if not self.isClosed:
                self.__refused += 1
        except BeanLoadException:
            beanDict = None
            if not self.isClosed:
                self.__refused += 1
                self.error("Could not load monitoring data from %s" %
                           (self.__mbeanClient, ))
        except:
            beanDict = None
            if not self.isClosed:
                self.error("Ignoring %s: %s" %
                           (self.__mbeanClient, exc_string()))

        if beanDict is not None:
            if not isinstance(beanDict, dict):
                self.error("%s getDictionary() returned %s, not dict (%s)" %
                           (self.__mbeanClient.fullname,
                            type(beanDict).__name__, beanDict))
            elif len(beanDict) > 0:
                # report monitoring data
                with self.__reporterLock:
                    reporter = self.__reporter
                for key, data in beanDict.items():
                    if not self.isClosed:
                        reporter.send(datetime.datetime.now(), key, data)

    def __fetch_beans_slowly(self):
        if len(self.__beanKeys) == 0:
            self.__beanKeys = self.__mbeanClient.getBeanNames()
            self.__beanKeys.sort()
            for b in self.__beanKeys:
                if self.isClosed:
                    # give up if this thread has been "closed"
                    return

                self.__beanFlds[b] = self.__mbeanClient.getBeanFields(b)

        for b in self.__beanKeys:
            if self.isClosed:
                break

            flds = self.__beanFlds[b]
            try:
                attrs = self.__mbeanClient.getAttributes(b, flds)
                self.__refused = 0
            except BeanTimeoutException:
                attrs = None
                if not self.isClosed:
                    self.__refused += 1
                break
            except BeanLoadException:
                attrs = None
                if not self.isClosed:
                    self.__refused += 1
                    self.error("Could not load monitoring data from %s:%s" %
                               (self.__mbeanClient, b))
            except:
                attrs = None
                if not self.isClosed:
                    self.error("Ignoring %s:%s: %s" %
                               (self.__mbeanClient, b, exc_string()))

            if attrs is not None:
                if not isinstance(attrs, dict):
                    self.error("%s getAttributes(%s, %s) returned %s, not dict"
                               " (%s)" %
                               (self.__mbeanClient.fullname, b, flds,
                                type(attrs), attrs))
                    continue

                # report monitoring data
                if len(attrs) > 0 and not self.isClosed:
                    self.__reporter.send(datetime.datetime.now(), b, attrs)

    def _run(self):
        if self.isClosed:
            return

        if self.__reporter is None:
            if not self.GET_DICTIONARY:
                # reload MBean info to pick up any dynamically created MBeans
                self.__mbeanClient.reload()

            self.__reporter = self.__create_reporter()
            if self.__reporter is None:
                return

            if not self.GET_DICTIONARY:
                self.__beanKeys = []
                self.__beanFlds = {}

        if self.GET_DICTIONARY:
            self.__fetch_dictionary()
        else:
            self.__fetch_beans_slowly()

        return self.__refused

    def close(self):
        if not self.isClosed:
            with self.__reporterLock:
                if self.__reporter is not None:
                    try:
                        self.__reporter.close()
                    except:
                        self.error(("Could not close %s monitor thread: %s") %
                                   (self.__mbeanClient.fullname, exc_string()))

                super(MBeanThread, self).close()

    def get_new_thread(self):
        thrd = MBeanThread(self.__comp, self.__runDir, self.__liveMoni,
                           self.__runOptions, self.dashlog,
                           self.__reporter, self.__refused)
        return thrd

    @property
    def refused_count(self):
        return self.__refused


class CnCMoniThread(MonitorThread):
    def __init__(self, runset, rundir, write_to_file, dashlog, reporter=None):
        self.__runset = runset
        self.__rundir = rundir
        self.__reporter = reporter

        self.__write_to_file = write_to_file

        super(CnCMoniThread, self).__init__("CnCServer", dashlog)

    def __create_reporter(self):
        if self.__write_to_file:
            if self.__rundir is not None:
                return MonitorToFile(self.__rundir, "cncServer")

        return None

    def _run(self):
        if self.isClosed:
            return

        if self.__reporter is None:
            self.__reporter = self.__create_reporter()
            if self.__reporter is None:
                return

        #sstats = self.__runset.server_statistics()
        #if sstats is not None and len(sstats) > 0:
        #    self.__reporter.send(datetime.datetime.now(), "server", sstats)

        cstats = self.__runset.client_statistics()
        if cstats is not None and len(cstats) > 0:
            self.__reporter.send(datetime.datetime.now(), "client", cstats)

    def get_new_thread(self):
        thrd = CnCMoniThread(self.__runset, self.__rundir,
                             self.__write_to_file, self.dashlog,
                             reporter=self.__reporter)
        return thrd

    @property
    def refused_count(self):
        return 0


class MonitorToFile(object):
    def __init__(self, dirname, basename):
        if dirname is None:
            self.__fd = None
        else:
            self.__fd = open(os.path.join(dirname, basename + ".moni"), "w")
        self.__fdLock = threading.Lock()

    def close(self):
        with self.__fdLock:
            if self.__fd is not None:
                self.__fd.close()
                self.__fd = None

    def send(self, now, beanName, attrs):
        with self.__fdLock:
            if self.__fd is not None:
                print("%s: %s:" % (beanName, now), file=self.__fd)
                for key in attrs:
                    print("\t%s: %s" % (key, attrs[key]), file=self.__fd)
                print(file=self.__fd)
                self.__fd.flush()


class MonitorToLive(object):
    def __init__(self, name, liveMoni):
        self.__name = name
        self.__liveMoni = liveMoni

    def close(self):
        pass

    def send(self, now, beanName, attrs):
        if self.__liveMoni is not None:
            for key in attrs:
                self.__liveMoni.sendMoni("%s*%s+%s" % (self.__name, beanName,
                                                       key), attrs[key],
                                         Prio.ITS, now)


class MonitorToBoth(object):
    def __init__(self, dirname, basename, liveMoni):
        self.__file = MonitorToFile(dirname, basename)
        self.__live = MonitorToLive(basename, liveMoni)

    def close(self):
        self.__file.close()
        self.__live.close()

    def send(self, now, beanName, attrs):
        self.__file.send(now, beanName, attrs)
        self.__live.send(now, beanName, attrs)


class MonitorTask(CnCTask):
    NAME = "Monitoring"
    PERIOD = 100

    MAX_REFUSED = 3

    MONITOR_CNCSERVER = False

    def __init__(self, taskMgr, runset, dashlog, liveMoni, runDir, runOptions,
                 period=None):
        if period is None:
            period = self.PERIOD

        super(MonitorTask, self).__init__(self.NAME, taskMgr, dashlog,
                                          self.NAME, period)

        self.__threadList = self.__createThreads(runset, dashlog, liveMoni,
                                                 runDir, runOptions)

    def __createThreads(self, runset, dashlog, liveMoni, runDir, runOptions):
        threadList = {}

        if not RunOption.isMoniToNone(runOptions):
            for c in runset.components():
                # refresh MBean info to pick up any new MBeans
                c.mbean.reload()

                threadList[c] = self.createThread(c, runDir, liveMoni,
                                                  runOptions, dashlog)

            if self.MONITOR_CNCSERVER:
                toFile = RunOption.isMoniToFile(runOptions)
                threadList["CnCServer"] \
                    = self.createCnCMoniThread(runset, runDir, toFile, dashlog)

        return threadList

    def _check(self):
        for c in list(self.__threadList.keys()):
            thrd = self.__threadList[c]
            if not thrd.isAlive():
                if thrd.refused_count >= self.MAX_REFUSED:
                    if not thrd.is_warned:
                        msg = ("ERROR: Not monitoring %s: Connect failed" +
                               " %d times") % \
                               (c.fullname, thrd.refused_count)
                        self.logError(msg)
                        thrd.set_warned()
                    continue
                self.__threadList[c] = thrd.get_new_thread()
                self.__threadList[c].start()

    @classmethod
    def createThread(cls, comp, runDir, liveMoni, runOptions, dashlog):
        return MBeanThread(comp, runDir, liveMoni, runOptions, dashlog)

    @classmethod
    def createCnCMoniThread(cls, runset, runDir, toFile, dashlog):
        return CnCMoniThread(runset, runDir, toFile, dashlog)

    def close(self):
        savedEx = None
        for thr in list(self.__threadList.values()):
            try:
                thr.close()
            except:
                if not savedEx:
                    savedEx = sys.exc_info()

        if savedEx:
            reraise_excinfo(savedEx)

    def numOpen(self):
        num = 0
        for c in list(self.__threadList.keys()):
            if not self.__threadList[c].isClosed:
                num += 1
        return num

    def waitUntilFinished(self):
        for c in list(self.__threadList.keys()):
            if self.__threadList[c].isAlive():
                self.__threadList[c].join()
