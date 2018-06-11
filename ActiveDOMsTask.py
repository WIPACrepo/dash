#!/usr/bin/env python

from CnCSingleThreadTask import CnCSingleThreadTask
from CnCThread import CnCThread
from CompOp import ComponentGroup, OpGetMultiBeanFields
from LiveImports import Prio


from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class ActiveDOMThread(CnCThread):
    "A thread which reports the active DOM counts"

    PREV_ACTIVE = {}

    KEY_ACT_TOT = "NumberOfActiveAndTotalChannels"
    KEY_LBM_OVER = "TotalLBMOverflows"

    def __init__(self, runset, dashlog, liveMoni, send_details):
        self.__runset = runset
        self.__dashlog = dashlog
        self.__live_moni_client = liveMoni
        self.__send_details = send_details

        super(ActiveDOMThread, self).__init__("CnCServer:ActiveDOMThread",
                                              dashlog)

    def __process_result(self, comp, result, totals, lbm_overflows):
        try:
            hub_active_doms = int(result[self.KEY_ACT_TOT][0])
            hub_total_doms = int(result[self.KEY_ACT_TOT][1])
        except:
            self.__dashlog.error("Cannot get # active DOMS from %s string:"
                                 " %s" % (comp.fullname, exc_string()))
            # be extra paranoid about using previous value
            tmp_active = 0
            tmp_total = 0
            if comp.num in self.PREV_ACTIVE and \
               self.KEY_ACT_TOT in self.PREV_ACTIVE[comp.num]:
                prevpair = self.PREV_ACTIVE[comp.num][self.KEY_ACT_TOT]
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

        if self.KEY_LBM_OVER in result:
            hub_lbm_overflows = result[self.KEY_LBM_OVER]
        else:
            self.__dashlog.error("Bad LBM overflow result %s<%s>" %
                                 (result, type(result)))
            hub_lbm_overflows = 0
        lbm_overflows[str(comp.num)] = hub_lbm_overflows

        # cache current results
        #
        self.PREV_ACTIVE[comp.num] = {
            self.KEY_ACT_TOT: (hub_active_doms, hub_total_doms),
            self.KEY_LBM_OVER: hub_lbm_overflows,
        }

    def __send_moni(self, name, value, prio):
        self.__live_moni_client.sendMoni(name, value, prio)

    def _run(self):
        # build a list of hubs
        src_set = []
        for comp in self.__runset.components():
            if comp.isSource:
                src_set.append(comp)

        # spawn a bunch of threads to fetch hub data
        bean_keys = (self.KEY_ACT_TOT, self.KEY_LBM_OVER)
        results = ComponentGroup.run_simple(OpGetMultiBeanFields, src_set,
                                            ("stringhub", bean_keys),
                                            self.__dashlog)

        # create dictionaries used to accumulate results
        totals = {
            "active_doms": 0, "total_doms": 0,
        }
        lbm_overflows = {}

        hanging = []
        for comp in src_set:
            if comp not in results:
                result = None
            else:
                result = results[comp]
                if result == ComponentGroup.RESULT_HANGING:
                    hanging.append(comp.fullname)
                    result = None
                elif result == ComponentGroup.RESULT_ERROR:
                    result = None

            if result is None:
                # if we don't have previous data for this component, skip it
                if comp.num not in self.PREV_ACTIVE:
                    continue

                # use previous datapoint
                result = self.PREV_ACTIVE[comp.num]

            # 'result' should now contain a dictionary with the number of
            # active and total channels and the LBM overflows

            self.__process_result(comp, result, totals, lbm_overflows)

        # report hanging components
        if len(hanging) > 0:
            errmsg = "Cannot get %s bean data from hanging components (%s)" % \
                     (ActiveDOMsTask.NAME, hanging)
            self.__dashlog.error(errmsg)

        # if the run isn't stopped and we have data from one or more hubs...
        if not self.isClosed and len(lbm_overflows) > 0:

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
            }
            self.__send_moni("dom_update", dom_update, prio)

            self.__send_moni("missingDOMs", missing_doms, prio)

            if self.__send_details:
                # important messages that go out every ten minutes
                self.__send_moni("LBMOverflows", lbm_overflows, Prio.ITS)

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

    'LBMOverflows' which is a dictionary relating string number to the total
    number of lbm overflows for a given string
    """
    NAME = "ActiveDOMs"
    PERIOD = 60

    # active DOM periodic report timer
    REPORT_NAME = "ActiveReport"
    REPORT_PERIOD = 600

    def __init__(self, taskMgr, runset, dashlog, liveMoni=None, period=None,
                 needLiveMoni=True):
        super(ActiveDOMsTask, self).__init__(taskMgr, runset, dashlog,
                                             liveMoni, period, needLiveMoni)

    def createDetailTimer(self, taskMgr):
        return taskMgr.createIntervalTimer(self.REPORT_NAME,
                                           self.REPORT_PERIOD)

    def initializeThread(self, runset, dashlog, liveMoni):
        return ActiveDOMThread(runset, dashlog, liveMoni, False)

    def taskFailed(self):
        self.logError("ERROR: %s thread seems to be stuck,"
                      " monitoring will not be done" % self.NAME)
