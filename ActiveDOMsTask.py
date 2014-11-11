#!/usr/bin/env python

from CnCSingleThreadTask import CnCSingleThreadTask
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

    def __sendMoni(self, name, value, prio):
        #try:
        self.__liveMoniClient.sendMoni(name, value, prio)
        #except:
        #    self.__dashlog.error("Failed to send %s=%s: %s" %
        #                         (name, value, exc_string()))

    def _run(self):
        active_total = 0
        total = 0
        hub_active_doms = 0
        hub_total_doms = 0

        # hit rate ( in hz )
        sum_total_rate = 0
        sum_lc_rate = 0
        total_rate = 0
        lc_rate = 0

        hub_DOMs = {}

        lbm_Overflows_Dict = {}

        KEY_ACT_TOT = "NumberOfActiveAndTotalChannels"
        KEY_LBM_OVER = "TotalLBMOverflows"
        KEY_LC_RATE = "HitRateLC"
        KEY_TOTAL_RATE = "HitRate"

        for c in self.__runset.components():
            if not c.isSource():
                continue

            # the number of active and total channels and the LBM overflows
            # are returned as a dictionary of values
            try:
                beanData = c.getMultiBeanFields("stringhub", [KEY_ACT_TOT,
                                                              KEY_LBM_OVER,
                                                              KEY_LC_RATE,
                                                              KEY_TOTAL_RATE])
            except Exception:
                self.__dashlog.error(
                    "Cannot get %s bean data from %s: %s" %
                    (ActiveDOMsTask.NAME, c.fullName(), exc_string()))
                if not c.num() in self.PREV_ACTIVE:
                    continue

                beanData = self.PREV_ACTIVE[c.num()]

            try:
                hub_active_doms = int(beanData[KEY_ACT_TOT][0])
                hub_total_doms = int(beanData[KEY_ACT_TOT][1])
            except:
                self.__dashlog.error("Cannot get # active DOMS from" +
                                     " %s string: %s" %
                                     (c.fullName(), exc_string()))
                # be extra paranoid about using previous value
                tmp_active = 0
                tmp_total = 0
                if self.PREV_ACTIVE[c.num()].has_key(KEY_ACT_TOT):
                    prevpair = self.PREV_ACTIVE[c.num()][KEY_ACT_TOT]
                    if len(prevpair) == 2:
                        try:
                            tmp_active = int(prevpair[0])
                            tmp_total = int(prevpair[0])
                        except:
                            tmp_active = 0
                            tmp_total = 0
                hub_active_doms = tmp_active
                hub_total_doms = tmp_total

            active_total += hub_active_doms
            total += hub_total_doms

            if beanData.has_key(KEY_LBM_OVER):
                lbm_Overflows = beanData[KEY_LBM_OVER]
            else:
                lbm_Overflows = 0
            lbm_Overflows_Dict[str(c.num())] = lbm_Overflows

            # collect hit rate information
            # note that we are rounding rates to 2 decimal points
            # because we need to conserve space in the stringRateInfo dict
            try:
                lc_rate = float(beanData[KEY_LC_RATE])
                total_rate = float(beanData[KEY_TOTAL_RATE])
            except:
                lc_rate = 0.0
                total_rate = 0.0

            sum_lc_rate += lc_rate
            sum_total_rate += total_rate

            if self.__sendDetails:
                hub_DOMs[str(c.num())] = (hub_active_doms, hub_total_doms)

            # cache current results
            #
            self.PREV_ACTIVE[c.num()] = {
                KEY_ACT_TOT: (hub_active_doms, hub_total_doms),
                KEY_LBM_OVER: lbm_Overflows,
                KEY_LC_RATE: lc_rate,
                KEY_TOTAL_RATE: total_rate
                }

        # active doms should be reported over ITS once every ten minutes
        # and over email once a minute.  The two should not overlap
        if not self.isClosed():

            # if an mbean exception occurs above it's possible to get here
            # with an empty data dict
            # we just want to return if we get here and don't have data
            if len(lbm_Overflows_Dict) == 0:
                return

            # priority for standard messages
            if not self.__sendDetails:
                # messages that go out every minute use lower priority
                prio = Prio.EMAIL
            else:
                # use higher priority every 10 minutes to keep North updated
                prio = Prio.ITS

            dom_update = \
                      { "activeDOMs": active_total,
                        "expectedDOMs": total,
                        "total_ratelc": sum_lc_rate,
                        "total_rate": sum_total_rate,
                    }
            self.__sendMoni("dom_update", dom_update, prio)

            # XXX get rid of these once I3Live uses "dom_update"
            self.__sendMoni("activeDOMs", active_total, prio)
            self.__sendMoni("expectedDOMs", total, prio)
            self.__sendMoni("total_ratelc", sum_lc_rate, prio)
            self.__sendMoni("total_rate", sum_total_rate, prio)

            if self.__sendDetails:
                # important messages that go out every ten minutes
                self.__sendMoni("LBMOverflows", lbm_Overflows_Dict, Prio.ITS)

                # less urgent messages use lower priority
                self.__sendMoni("stringDOMsInfo", hub_DOMs, Prio.EMAIL)

    def getNewThread(self, sendDetails=False):
        thrd = ActiveDOMThread(self.__runset, self.__dashlog,
                               self.__liveMoniClient, sendDetails)
        return thrd


class ActiveDOMsTask(CnCSingleThreadTask):
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
    NAME = "ActiveDOMs"
    PERIOD = 60
    DEBUG_BIT = RunSetDebug.ACTDOM_TASK

    # active DOM periodic report timer
    REPORT_NAME = "ActiveReport"
    REPORT_PERIOD = 600

    def __init__(self, taskMgr, runset, dashlog, liveMoni=None, period=None,
                 needLiveMoni=True):
        super(ActiveDOMsTask, self).__init__(taskMgr, runset, dashlog,
                                             liveMoni, period, needLiveMoni)

    def createDetailTimer(self, taskMgr):
        return taskMgr.createIntervalTimer(self.REPORT_NAME, self.REPORT_PERIOD)

    def initializeThread(self, runset, dashlog, liveMoni):
        return ActiveDOMThread(runset, dashlog, liveMoni, False)

    def taskFailed(self):
        self.logError("ERROR: %s thread seems to be stuck,"
                      " monitoring will not be done" % self.NAME)
