#!/usr/bin/env python

from CnCSingleThreadTask import CnCSingleThreadTask
from CnCThread import CnCThread
from CompOp import ComponentOperation, ComponentOperationGroup
from LiveImports import Prio
from RunSetDebug import RunSetDebug


from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class ActiveDOMThread(CnCThread):
    "A thread which reports the active DOM counts"

    PREV_ACTIVE = {}

    KEY_ACT_TOT = "NumberOfActiveAndTotalChannels"
    KEY_LBM_OVER = "TotalLBMOverflows"
    KEY_LC_RATE = "HitRateLC"
    KEY_TOTAL_RATE = "HitRate"

    def __init__(self, runset, dashlog, liveMoni, send_details):
        self.__runset = runset
        self.__dashlog = dashlog
        self.__live_moni_client = liveMoni
        self.__send_details = send_details

        super(ActiveDOMThread, self).__init__("CnCServer:ActiveDOMThread",
                                              dashlog)

    def __process_result(self, comp, result, totals, lbm_overflows, hub_doms):
        try:
            hub_active_doms = int(result[self.KEY_ACT_TOT][0])
            hub_total_doms = int(result[self.KEY_ACT_TOT][1])
        except:
            self.__dashlog.error("Cannot get # active DOMS from %s string: %s" %
                                 (comp.fullName(), exc_string()))
            # be extra paranoid about using previous value
            tmp_active = 0
            tmp_total = 0
            if self.PREV_ACTIVE[comp.num()].has_key(self.KEY_ACT_TOT):
                prevpair = self.PREV_ACTIVE[comp.num()][self.KEY_ACT_TOT]
                if len(prevpair) == 2:
                    try:
                        tmp_active = int(prevpair[0])
                        tmp_total = int(prevpair[0])
                    except:
                        tmp_active = 0
                        tmp_total = 0
            hub_active_doms = tmp_active
            hub_total_doms = tmp_total

        totals["active_doms"] += hub_active_doms
        totals["total_doms"] += hub_total_doms

        if result.has_key(self.KEY_LBM_OVER):
            hub_lbm_overflows = result[self.KEY_LBM_OVER]
        else:
            hub_lbm_overflows = 0
        lbm_overflows[str(comp.num())] = hub_lbm_overflows

        # collect hit rate information
        # note that we are rounding rates to 2 decimal points
        # because we need to conserve space in the stringRateInfo dict
        try:
            lc_rate = float(result[self.KEY_LC_RATE])
            total_rate = float(result[self.KEY_TOTAL_RATE])
        except:
            lc_rate = 0.0
            total_rate = 0.0

        totals["lc_rate"] += lc_rate
        totals["total_rate"] += total_rate

        if self.__send_details:
            hub_doms[str(comp.num())] = (hub_active_doms, hub_total_doms)

        # cache current results
        #
        self.PREV_ACTIVE[comp.num()] = {
            self.KEY_ACT_TOT: (hub_active_doms, hub_total_doms),
            self.KEY_LBM_OVER: hub_lbm_overflows,
            self.KEY_LC_RATE: lc_rate,
            self.KEY_TOTAL_RATE: total_rate
        }

    def __send_moni(self, name, value, prio):
        #try:
        self.__live_moni_client.sendMoni(name, value, prio)
        #except:
        #    self.__dashlog.error("Failed to send %s=%s: %s" %
        #                         (name, value, exc_string()))

    def _run(self):
        # build a list of hubs
        src_set = []
        for comp in self.__runset.components():
            if comp.isSource():
                src_set.append(comp)

        # spawn a bunch of threads to fetch hub data
        bean_op = ComponentOperation.GET_MULTI_BEAN
        bean_keys = (self.KEY_ACT_TOT, self.KEY_LBM_OVER, self.KEY_LC_RATE,
                     self.KEY_TOTAL_RATE)
        results = ComponentOperationGroup.runSimple(bean_op, src_set,
                                                    ("stringhub", bean_keys),
                                                    self.__dashlog)

        # create dictionaries used to accumulate results
        totals = {
            "active_doms": 0, "total_doms": 0,
            "lc_rate": 0.0, "total_rate": 0.0
        }
        lbm_overflows = {}
        hub_doms = {}

        hanging = []
        for comp in src_set:
            if not results.has_key(comp):
                result = None
            else:
                result = results[comp]
                if result == ComponentOperation.RESULT_HANGING or \
                   result == ComponentOperation.RESULT_ERROR:
                    if result == ComponentOperation.RESULT_HANGING:
                        hanging.append(comp.fullName())
                    result = None

            if result is None:
                # if we don't have previous data for this component, skip it
                if not comp.num() in self.PREV_ACTIVE:
                    continue

                # use previous datapoint
                result = self.PREV_ACTIVE[comp.num()]

            # 'result' should now contain a dictionary with the number of
            # active and total channels and the LBM overflows

            self.__process_result(comp, result, totals, lbm_overflows, hub_doms)

        # report hanging components
        if len(hanging) > 0:
            errmsg = "Cannot get %s bean data from hanging components (%s)" % \
                     (ActiveDOMsTask.NAME, hanging)
            self.__dashlog.error(errmsg)

        # if the run isn't stopped and we have data from one or more hubs...
        if not self.isClosed() and len(lbm_overflows) > 0:

            # active doms should be reported over ITS once every ten minutes
            # and over email once a minute.  The two should not overlap

            # priority for standard messages
            if not self.__send_details:
                # messages that go out every minute use lower priority
                prio = Prio.EMAIL
            else:
                # use higher priority every 10 minutes to keep North updated
                prio = Prio.ITS

            active_doms = totals["active_doms"]
            total_doms = totals["total_doms"]
            missing_doms = total_doms - active_doms

            dom_update = {
                "activeDOMs": active_doms,
                "expectedDOMs": total_doms,
                "missingDOMs": missing_doms,
                "total_ratelc": totals["lc_rate"],
                "total_rate": totals["total_rate"],
            }
            self.__send_moni("dom_update", dom_update, prio)

            # XXX get rid of these once I3Live uses "dom_update"
            self.__send_moni("activeDOMs", active_doms, prio)
            self.__send_moni("expectedDOMs", total_doms, prio)
            self.__send_moni("missingDOMs", missing_doms, prio)
            self.__send_moni("total_ratelc", totals["lc_rate"], prio)
            self.__send_moni("total_rate", totals["total_rate"], prio)

            if self.__send_details:
                # important messages that go out every ten minutes
                self.__send_moni("LBMOverflows", lbm_overflows, Prio.ITS)

                # less urgent messages use lower priority
                self.__send_moni("stringDOMsInfo", hub_doms, Prio.EMAIL)

    def get_new_thread(self, send_details=False):
        thrd = ActiveDOMThread(self.__runset, self.__dashlog,
                               self.__live_moni_client, send_details)
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
