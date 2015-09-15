#!/usr/bin/env python

import datetime
import os
import threading
import sys

from CnCTask import CnCTask
from CnCThread import CnCThread
from DAQClient import BeanTimeoutException
from LiveImports import Prio
from RunOption import RunOption
from RunSetDebug import RunSetDebug

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class MonitorThread(CnCThread):
    def __init__(self, comp, runDir, liveMoni, runOptions, dashlog,
                 reporter=None, refused=0):
        self.__comp = comp
        self.__runDir = runDir
        self.__liveMoni = liveMoni
        self.__runOptions = runOptions
        self.__dashlog = dashlog
        self.__reporter = reporter
        self.__refused = refused
        self.__warned = False
        self.__closeLock = threading.Lock()

        self.__beanKeys = []
        self.__beanFlds = {}

        super(MonitorThread, self).__init__(comp.fullName(), dashlog)

    def __createReporter(self):
        if RunOption.isMoniToBoth(self.__runOptions) and \
               self.__liveMoni is not None:
            return MonitorToBoth(self.__runDir, self.__comp.fileName(),
                                 self.__liveMoni)
        if RunOption.isMoniToFile(self.__runOptions):
            if self.__runDir is not None:
                return MonitorToFile(self.__runDir, self.__comp.fileName())
        if RunOption.isMoniToLive(self.__runOptions) and \
               self.__liveMoni is not None:
            return MonitorToLive(self.__comp.fileName(), self.__liveMoni)

        return None

    def _run(self):
        if self.isClosed():
            return

        if self.__reporter is None:
            # reload MBean info to pick up any dynamically created MBeans
            self.__comp.reloadBeanInfo()

            self.__reporter = self.__createReporter()
            if self.__reporter is None:
                return

            self.__beanKeys = []
            self.__beanFlds = {}

        if len(self.__beanKeys) == 0:
            self.__beanKeys = self.__comp.getBeanNames()
            self.__beanKeys.sort()
            for b in self.__beanKeys:
                if self.isClosed():
                    # give up if this thread has been "closed"
                    return

                self.__beanFlds[b] = self.__comp.getBeanFields(b)

        for b in self.__beanKeys:
            if self.isClosed():
                break

            flds = self.__beanFlds[b]
            try:
                attrs = self.__comp.getMultiBeanFields(b, flds)
                self.__refused = 0
            except BeanTimeoutException:
                self.__refused += 1
                break
            except:
                attrs = None
                self.__dashlog.error("Ignoring %s:%s: %s" %
                                     (str(self.__comp), b, exc_string()))

            # report monitoring data
            if attrs and len(attrs) > 0 and not self.isClosed():
                self.__reporter.send(datetime.datetime.now(), b, attrs)

        return self.__refused

    def close(self):
        super(MonitorThread, self).close()

        with self.__closeLock:
            if self.__reporter is not None:
                try:
                    self.__reporter.close()
                except:
                    self.__dashlog.error(("Could not close %s monitor" +
                                          " thread: %s") %
                                         (self.__comp, exc_string()))
                self.__reporter = None

    def get_new_thread(self):
        thrd = MonitorThread(self.__comp, self.__runDir, self.__liveMoni,
                             self.__runOptions, self.__dashlog,
                             self.__reporter, self.__refused)
        return thrd

    def isWarned(self):
        return self.__warned

    def refusedCount(self):
        return self.__refused

    def setWarned(self):
        self.__warned = True


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
                print >> self.__fd, "%s: %s:" % (beanName, now)
                for key in attrs:
                    print >> self.__fd, "\t%s: %s" % \
                        (key, str(attrs[key]))
                print >> self.__fd
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
    DEBUG_BIT = RunSetDebug.MONI_TASK

    MAX_REFUSED = 3

    def __init__(self, taskMgr, runset, dashlog, liveMoni, runDir, runOptions,
                 period=None):
        if period is None:
            period = self.PERIOD

        super(MonitorTask, self).__init__(self.NAME, taskMgr, dashlog,
                                          self.DEBUG_BIT, self.NAME,
                                          period)

        self.__threadList = self.__createThreads(runset, dashlog, liveMoni,
                                                 runDir, runOptions)

    def __createThreads(self, runset, dashlog, liveMoni, runDir, runOptions):
        threadList = {}

        if not RunOption.isMoniToNone(runOptions):
            for c in runset.components():
                # refresh MBean info to pick up any new MBeans
                c.reloadBeanInfo()

                threadList[c] = self.createThread(c, runDir, liveMoni,
                                                  runOptions, dashlog)

        return threadList

    def _check(self):
        for c in self.__threadList.keys():
            thrd = self.__threadList[c]
            if not thrd.isAlive():
                if thrd.refusedCount() >= self.MAX_REFUSED:
                    if not thrd.isWarned():
                        msg = ("ERROR: Not monitoring %s: Connect failed" +
                               " %d times") % \
                               (c.fullName(), thrd.refusedCount())
                        self.logError(msg)
                        thrd.setWarned()
                    continue
                self.__threadList[c] = thrd.get_new_thread()
                self.__threadList[c].start()

    @classmethod
    def createThread(cls, comp, runDir, liveMoni, runOptions, dashlog):
        return MonitorThread(comp, runDir, liveMoni, runOptions, dashlog)

    def close(self):
        savedEx = None
        for thr in self.__threadList.values():
            try:
                thr.close()
            except:
                if not savedEx:
                    savedEx = sys.exc_info()

        if savedEx:
            raise savedEx[0], savedEx[1], savedEx[2]

    def numOpen(self):
        num = 0
        for c in self.__threadList.keys():
            if not self.__threadList[c].isClosed():
                num += 1
        return num

    def waitUntilFinished(self):
        for c in self.__threadList.keys():
            if self.__threadList[c].isAlive():
                self.__threadList[c].join()
