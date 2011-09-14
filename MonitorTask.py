#!/usr/bin/env python

import datetime
import os
import socket
import threading

from CnCTask import CnCTask
from CnCThread import CnCThread
from LiveImports import Prio
from RunOption import RunOption
from RunSetDebug import RunSetDebug

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class MonitorThread(CnCThread):
    def __init__(self, comp, runDir, live, runOptions, dashlog, reporter=None,
                 now=None, refused=0):
        self.__comp = comp
        self.__runDir = runDir
        self.__live = live
        self.__runOptions = runOptions
        self.__dashlog = dashlog
        self.__reporter = reporter
        self.__now = now
        self.__refused = refused
        self.__warned = False
        self.__closeLock = threading.Lock()

        super(MonitorThread, self).__init__(comp.fullName(), dashlog)

    def __createReporter(self):
        if RunOption.isMoniToBoth(self.__runOptions) and \
               self.__live is not None:
            return MonitorToBoth(self.__runDir, self.__comp.fileName(),
                                 self.__live)
        if RunOption.isMoniToFile(self.__runOptions):
            if self.__runDir is not None:
                return MonitorToFile(self.__runDir, self.__comp.fileName())
        if RunOption.isMoniToLive(self.__runOptions) and \
               self.__live is not None:
            return MonitorToLive(self.__comp.fileName(), self.__live)

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

        bSrt = self.__comp.getBeanNames()
        bSrt.sort()
        for b in bSrt:
            if self.isClosed():
                # break out of the loop if this thread has been "closed"
                break

            flds = self.__comp.getBeanFields(b)
            try:
                attrs = self.__comp.getMultiBeanFields(b, flds)
                self.__refused = 0
            except socket.error, se:
                sockStr = exc_string()
                try:
                    msg = se[1]
                except IndexError:
                    msg = None

                if msg is not None and msg == "Connection refused":
                    self.__refused += 1
                    break

                attrs = None
                self.__dashlog.error("Ignoring %s:%s: %s" %
                                     (str(self.__comp), b, sockStr))
            except:
                attrs = None
                self.__dashlog.error("Ignoring %s:%s: %s" %
                                     (str(self.__comp), b, exc_string()))

            # report monitoring data
            if attrs is not None and len(attrs) > 0 and not self.isClosed():
                self.__reporter.send(self.__now, b, attrs)

    def close(self):
        super(type(self), self).close()

        with self.__closeLock:
            if self.__reporter is not None:
                try:
                    self.__reporter.close()
                except:
                    self.__dashlog.error(("Could not close %s monitor" +
                                          " thread: %s") %
                                         (self.__comp, exc_string()))
                self.__reporter = None

    def getNewThread(self, now):
        thrd = MonitorThread(self.__comp, self.__runDir, self.__live,
                             self.__runOptions, self.__dashlog,
                             self.__reporter, now, self.__refused)
        return thrd

    def isWarned(self):
        return self.__warned

    def refusedCount(self):
        return self.__refused

    def setWarned(self):
        self.__warned = True


class MonitorToFile(object):
    def __init__(self, dir, basename):
        if dir is None:
            self.__fd = None
        else:
            self.__fd = open(os.path.join(dir, basename + ".moni"), "w")

    def close(self):
        self.__fd.close()

    def send(self, now, beanName, attrs):
        if self.__fd is None:
            return

        print >>self.__fd, "%s: %s:" % (beanName, now)
        for key in attrs:
            print >>self.__fd, "\t%s: %s" % \
                (key, str(attrs[key]))
        print >>self.__fd
        self.__fd.flush()


class MonitorToLive(object):
    def __init__(self, name, live):
        self.__name = name
        self.__live = live

    def close(self):
        pass

    def send(self, now, beanName, attrs):
        for key in attrs:
            self.__live.sendMoni("%s*%s+%s" % (self.__name, beanName, key),
                                 attrs[key], Prio.ITS, now)


class MonitorToBoth(object):
    def __init__(self, dir, basename, live):
        self.__file = MonitorToFile(dir, basename)
        self.__live = MonitorToLive(basename, live)

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

    def __init__(self, taskMgr, runset, dashlog, live, runDir, runOptions,
                 period=None):
        self.__threadList = {}
        if not RunOption.isMoniToNone(runOptions):
            for c in runset.components():
                # refresh MBean info to pick up any new MBeans
                c.reloadBeanInfo()

                self.__threadList[c] = self.createThread(c, runDir, live,
                                                         runOptions, dashlog)

        if period is None:
            period = self.PERIOD

        super(MonitorTask, self).__init__("Monitor", taskMgr, dashlog,
                                          self.DEBUG_BIT, self.NAME,
                                          period)

    @classmethod
    def createThread(cls, comp, runDir, live, runOptions, dashlog):
        return MonitorThread(comp, runDir, live, runOptions, dashlog)

    def _check(self):
        now = None
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
                if now is None:
                    now = datetime.datetime.now()
                self.__threadList[c] = thrd.getNewThread(now)
                self.__threadList[c].start()

    def close(self):
        savedEx = None
        for c in self.__threadList.keys():
            try:
                self.__threadList[c].close()
            except Exception, ex:
                if savedEx is None:
                    savedEx = ex

        if savedEx is not None:
            raise savedEx

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
