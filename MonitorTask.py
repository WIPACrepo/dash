#!/usr/bin/env python

import datetime, os, socket

from CnCTask import CnCTask
from CnCThread import CnCThread
from LiveImports import Prio
from RunOption import RunOption
from RunSetDebug import RunSetDebug

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class MonitorThread(CnCThread):
    def __init__(self, comp, dashlog, reporter, now=None, refused=0):
        self.__comp = comp
        self.__dashlog = dashlog
        self.__reporter = reporter
        self.__now = now
        self.__refused = refused
        self.__warned = False

        super(MonitorThread, self).__init__(comp.fullName(), dashlog)

    def _run(self):
        if self.__reporter is None:
            return

        bSrt = self.__comp.getBeanNames()
        bSrt.sort()
        for b in bSrt:
            flds = self.__comp.getBeanFields(b)
            try:
                attrs = self.__comp.getMultiBeanFields(b, flds)
                self.__refused = 0
            except socket.error, se:
                attrs = None
                msg = None
                try:
                    msg = se[1]
                except IndexError:
                    msg = None
                if msg is not None and msg == "Connection refused":
                    self.__refused += 1
                    break
            except:
                attrs = None
                self.__dashlog.error("Ignoring %s:%s: %s" %
                                     (str(self.__comp), b, exc_string()))

            # report monitoring data
            if attrs is not None and len(attrs) > 0:
                self.__reporter.send(self.__now, b, attrs)

    def getNewThread(self, now):
        thrd = MonitorThread(self.__comp, self.__dashlog, self.__reporter,
                             now, self.__refused)
        return thrd

    def isWarned(self): return self.__warned

    def refusedCount(self): return self.__refused

    def setWarned(self): self.__warned = True

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

    def __str__(self):
        return "MonitorToLive(%s)" % self.__name

    def send(self, now, beanName, attrs):
        for key in attrs:
            self.__live.sendMoni("%s*%s+%s" % (self.__name, beanName, key),
                                 attrs[key], Prio.ITS, now)

class MonitorToBoth(object):
    def __init__(self, dir, basename, live):
        self.__file = MonitorToFile(dir, basename)
        self.__live = MonitorToLive(basename, live)

    def send(self, now, beanName, attrs):
        self.__file.send(now, beanName, attrs)
        self.__live.send(now, beanName, attrs)

class MonitorTask(CnCTask):
    NAME = "Monitoring"
    PERIOD = 100
    DEBUG_BIT = RunSetDebug.MONI_TASK

    MAX_REFUSED = 3

    def __init__(self, taskMgr, runset, dashlog, live, runDir, runOptions):
        self.__threadList = {}
        if not RunOption.isMoniToNone(runOptions):
            for c in runset.components():
                reporter = self.__createReporter(c, runDir, live, runOptions)
                self.__threadList[c] = MonitorThread(c, dashlog, reporter)

        super(MonitorTask, self).__init__("Monitor", taskMgr, dashlog,
                                          self.DEBUG_BIT, self.NAME,
                                          self.PERIOD)

    def __createReporter(cls, comp, runDir, live, runOptions):
        if RunOption.isMoniToBoth(runOptions) and live is not None:
            return MonitorToBoth(runDir, comp.fileName(), live)
        if RunOption.isMoniToFile(runOptions):
            if runDir is not None:
                return MonitorToFile(runDir, comp.fileName())
        if RunOption.isMoniToLive(runOptions) and live is not None:
            return MonitorToLive(comp.fileName(), live)

        return None
    __createReporter = classmethod(__createReporter)

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

    def waitUntilFinished(self):
        for c in self.__threadList.keys():
            if self.__threadList[c].isAlive():
                self.__threadList[c].join()
