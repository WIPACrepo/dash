#!/usr/bin/env python

import datetime

from CnCTask import CnCTask
from CnCThread import CnCThread
from LiveImports import Prio
from RunSetDebug import RunSetDebug


from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class ActiveDOMThread(CnCThread):
    "A thread which reports the active DOM counts"
    def __init__(self, runset, dashlog, liveMoni, sendDetails):
        self.__comps = runset.components()
        self.__dashlog = dashlog
        self.__liveMoniClient = liveMoni
        self.__sendDetails = sendDetails

        super(ActiveDOMThread, self).__init__("CnCServer:ActiveDOMThread",
                                              dashlog)

    def _run(self):
        activeTotal = 0
        total = 0
        hubActiveDoms = 0
        hubTotalDoms = 0
        hubDOMs = {}
        hubInactiveDOMs = {}

        for c in self.__comps:
            if c.isSource():
                
                # collect the number of active and total channels
                try:
                    nList = c.getSingleBeanField("stringhub",
                                                 "NumberOfActiveAndTotalChannels")
                except Exception, e:
                    self.__dashlog.error("Cannot get # active and total DOMS from" +
                                         " %s: %s" %
                                         (c.fullName(), exc_string()))
                    print "Exception: "
                    print e

                    continue

                
                try:
                    hubActiveDoms, hubTotalDoms = [ int(a) for a in nList ] 
                except:
                    self.__dashlog.error("Cannot get # active DOMS from" +
                                         " %s string \"%s\": %s" %
                                         (c.fullName(), str(nStr),
                                          exc_string()))
                    continue
                
                activeTotal += hubActiveDoms
                total += hubTotalDoms

                if self.__sendDetails:
                    hubDOMs[str(c.num())] = (hubActiveDoms, hubTotalDoms)

        now = datetime.datetime.now()

        self.__liveMoniClient.sendMoni("totalDOMs", (activeTotal,total), Prio.ITS)

        if self.__sendDetails:
            if not self.__liveMoniClient.sendMoni("stringDOMsInfo", hubDOMs,
                                                  Prio.ITS):
                self.__dashlog.error("Failed to send active/total DOM report")


class ActiveDOMsTask(CnCTask):
    NAME = "ActiveDOM"
    PERIOD = 60
    DEBUG_BIT = RunSetDebug.ACTDOM_TASK

    # active DOM periodic report timer
    REPORT_NAME = "ActiveReport"
    REPORT_PERIOD = 600

    def __init__(self, taskMgr, runset, dashlog, liveMoni, period=None):
        self.__runset = runset
        self.__liveMoniClient = liveMoni

        self.__thread = None
        self.__badCount = 0

        if self.__liveMoniClient is None:
            name = None
            period = None
            self.__detailTimer = None
        else:
            name = self.NAME
            if period is None: period = self.PERIOD
            self.__detailTimer = \
                taskMgr.createIntervalTimer(self.REPORT_NAME,
                                            self.REPORT_PERIOD)

        super(ActiveDOMsTask, self).__init__("ActiveDOMs", taskMgr, dashlog,
                                             self.DEBUG_BIT, name, period)

    def _check(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is None or not self.__thread.isAlive():
            self.__badCount = 0

            sendDetails = False
            if self.__detailTimer is not None and \
                    self.__detailTimer.isTime():
                sendDetails = True
                self.__detailTimer.reset()

            self.__thread = \
                ActiveDOMThread(self.__runset, self.logger(),
                                self.__liveMoniClient, sendDetails)
            self.__thread.start()
        else:
            self.__badCount += 1
            if self.__badCount <= 3:
                self.logError("WARNING: Active DOM thread is hanging (#%d)" %
                              self.__badCount)
            else:
                self.logError("ERROR: Active DOM monitoring seems to be" +
                              " stuck, monitoring will not be done")
                self.endTimer()

    def _reset(self):
        self.__detailTimer = None
        self.__thread = None
        self.__badCount = 0

    def close(self):
        pass

    def waitUntilFinished(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.join()
