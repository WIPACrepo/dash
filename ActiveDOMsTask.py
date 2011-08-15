#!/usr/bin/env python

from CnCTask import CnCTask
from CnCThread import CnCThread
from LiveImports import Prio
from RunSetDebug import RunSetDebug


from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class ActiveDOMThread(CnCThread):
    "A thread which reports the active DOM counts"
    PREV_ACTIVE = {}

    def __init__(self, runset, dashlog, liveMoni, sendDetails):
        self.__runset = runset
        self.__dashlog = dashlog
        self.__liveMoniClient = liveMoni
        self.__sendDetails = sendDetails

        super(ActiveDOMThread, self).__init__("CnCServer:ActiveDOMThread",
                                              dashlog)

    def _run(self):
        active_total = 0
        total = 0
        hub_active_doms = 0
        hub_total_doms = 0
        hub_DOMs = {}

        lbm_Overflows_Dict = {}

        KEY_ACT_TOT = "NumberOfActiveAndTotalChannels"
        KEY_LBM_OVER = "TotalLBMOverflows"

        for c in self.__runset.components():
            if not c.isSource():
                continue

            # the number of active and total channels and the LBM overflows
            # are returned as a dictionary of values
            #
            try:
                beanData = c.getMultiBeanFields("stringhub", [ KEY_ACT_TOT,
                                                               KEY_LBM_OVER ])
            except Exception:
                self.__dashlog.error(
                    "Cannot get ActiveDomsTask bean data from %s: %s" %
                    (c.fullName(), exc_string()))
                if not self.PREV_ACTIVE.has_key(c.num()): continue
                beanData = self.PREV_ACTIVE[c.num()]

            try:
                hub_active_doms, hub_total_doms = \
                                 [ int(a) for a in beanData[KEY_ACT_TOT] ]
            except:
                self.__dashlog.error("Cannot get # active DOMS from" +
                                     " %s string: %s" %
                                     (c.fullName(), exc_string()))
                continue

            active_total += hub_active_doms
            total += hub_total_doms

            lbm_Overflows = beanData[KEY_LBM_OVER]

            lbm_Overflows_Dict[str(c.num())] = lbm_Overflows

            if self.__sendDetails:
                hub_DOMs[str(c.num())] = (hub_active_doms, hub_total_doms)

            # cache current results
            #
            self.PREV_ACTIVE[c.num()] = {
                KEY_ACT_TOT : (hub_active_doms, hub_total_doms),
                KEY_LBM_OVER : lbm_Overflows,
                }

        if not self.isClosed():
            self.__liveMoniClient.sendMoni("activeDOMs", active_total,
                                           Prio.ITS)
            self.__liveMoniClient.sendMoni("expectedDOMs", total, Prio.ITS)

        if not self.isClosed() and self.__sendDetails:
            if not self.__liveMoniClient.sendMoni("stringDOMsInfo", hub_DOMs,
                                                  Prio.EMAIL):
                self.__dashlog.error("Failed to send active/total DOM report")

                # send the lbm overflow information off to live
            if not self.__liveMoniClient.sendMoni("LBMOverflows",
                                                  lbm_Overflows_Dict, Prio.ITS):
                self.__dashlog.error("Failed to send lbm overflow data")

    def getNewThread(self, sendDetails):
        thrd = ActiveDOMThread(self.__runset, self.__dashlog,
                               self.__liveMoniClient, sendDetails)
        return thrd

class ActiveDOMsTask(CnCTask):
    """
    Essentially a timer, so every REPORT_PERIOD an ActiveDOMsThread is created
    and run.  This sends three chunks of information off to live:

    'totalDOMS' which is a count of the total number of active doms
    in the array along with a count of the number of doms (active or inactive).

    'stringDOMsInfo' which is a dictionary relating string number to the
    number of active and total number of doms in a string

    'LBMOverflows' which is a dictionary relating string number to the total
    number of lbm overflows for a given string
    """
    NAME = "ActiveDOM"
    PERIOD = 60
    DEBUG_BIT = RunSetDebug.ACTDOM_TASK

    # active DOM periodic report timer
    REPORT_NAME = "ActiveReport"
    REPORT_PERIOD = 600

    def __init__(self, taskMgr, runset, dashlog, liveMoni, period=None):
        self.__runset = runset
        self.__liveMoniClient = liveMoni

        self.__thread = ActiveDOMThread(runset, dashlog, liveMoni, False)
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

            self.__thread = self.__thread.getNewThread(sendDetails)
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
        self.__badCount = 0

    def close(self):
        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.close()

    def waitUntilFinished(self):
        if self.__liveMoniClient is None:
            return

        if self.__thread is not None and self.__thread.isAlive():
            self.__thread.join()
