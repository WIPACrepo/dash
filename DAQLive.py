#!/usr/bin/env python

import threading
import time

from CnCExceptions import MissingComponentException
from DAQConst import DAQPort
from IntervalTimer import IntervalTimer
from LiveImports import INCOMPLETE_STATE_CHANGE, LIVE_IMPORT, LiveComponent, \
    SERVICE_NAME
from RunOption import RunOption
from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

class LiveException(Exception):
    pass


class ActionThread(threading.Thread):
    def __init__(self, name=None, args=(), kwargs=None):
        if name is None:
            name = str(self)

        super(ActionThread, self).__init__(target=self.safe_run, name=name,
                                           args=args)

        self.__exception = None

    def __str__(self):
        return "%s[%s]%s" % (type(self), self.name,
                             "" if self.__exception is None else "EXC")

    @property
    def exception(self):
        return self.__exception

    @property
    def is_joined(self):
        if self.is_alive():
            self.join(1)
        return not self.is_alive()

    def log_and_clear_exception(self, logger):
        if self.__exception is not None:
            logger.error("%s: %s" % (self.name, self.__exception))
            self.__exception = None

    def reraise_exception(self):
        if self.__exception is not None:
            raise self.__exception

    def safe_run(self, *args, **kwargs):
        self.__exception = None

        try:
            self.run_action(*args, **kwargs)
        except Exception as exc:
            if self.__exception is None:
                self.__exception = exc

    def run_action(self, *args, **kwargs):
        raise NotImplementedError()


class RecoverThread(ActionThread):
    NAME = "LiveRecover"

    def __init__(self, daq_live, logger, *args, **kwargs):
        super(RecoverThread, self).__init__(name=RecoverThread.NAME, args=args,
                                            kwargs=kwargs)

        self.__daq_live = daq_live
        self.__log = logger

    def run_action(self, *args, **kwargs):
        #(run_cfg, run_num) = args

        cnc = self.__daq_live.command_and_control
        runset = self.__daq_live.runset

        # if the runset was destroyed, forget about it
        if runset is not None and runset.isDestroyed:
            runset = None
            self.__daq_live.set_runset(runset)

        if runset is None:
            if not cnc.isStarting:
                # is there's no runset and we're not starting, we're recovered
                return True

            # if runset is still not set, we're recovered
            if runset is None:
                return True

        if runset.isReady or runset.isIdle or \
           runset.isDestroyed:
            # if we're in a known non-running state, we're done
            return True

        # if runset isn't stopping, try to stop it
        if not runset.stopping():
            try:
                stopVal = not runset.stop_run("LiveRecover", had_error=True)
                if stopVal:
                    self.__log.error("DAQLive stop_run %s returned %s" %
                                     (runset, stopVal))
            except:
                self.__log.error("DAQLive stop_run %s failed: %s" %
                                 (runset, exc_string()))

        # give runset a bit of time to finish stopping
        wait_secs = 5
        numTries = 12
        for _ in range(numTries):
            if not runset.stopping():
                break
            time.sleep(wait_secs)

        # report final state
        rtnVal = False
        if runset is None or runset.isDestroyed:
            self.__log.error("DAQLive destroyed %s" % (runset, ))
            runset = None
            return True
        if runset.isReady or runset.isIdle:
            return True
        if runset.stopping():
            self.__log.error("DAQLive giving up on hung %s" %
                             (runset, ))
        else:
            self.__log.error("DAQLive cannot recover %s (state=%s)" %
                             (runset, runset.state))

        attempts = self.__daq_live.recoverAttempts
        if attempts < self.MAX_RECOVERY_ATTEMPTS:
            time.sleep(1)
            return INCOMPLETE_STATE_CHANGE

        raise LiveException("Runset %s was not recovered after %d attempts" %
                            (runset, attempts))


class StartThread(ActionThread):
    NAME = "LiveStart"

    def __init__(self, daq_live, logger, *args, **kwargs):
        super(StartThread, self).__init__(name=StartThread.NAME, args=args,
                                          kwargs=kwargs)

        self.__daq_live = daq_live
        self.__log = logger

    def run_action(self, *args, **kwargs):
        """
        Attempt to build a runset and start a run from within a thread.
        """
        (run_cfg, run_num) = args

        cnc = self.__daq_live.command_and_control

        runset = self.__daq_live.runset

        if runset is not None:
            if runset.isRunning:
                # if we have a runset, we're ready to run!
                return True

            if runset.isDestroyed:
                # if the runset was destroyed, forget about it
                runset = None
            else:
                cnc.breakRunset(runset)
            self.__daq_live.set_runset(None)

        try:
            runset = cnc.makeRunsetFromRunConfig(run_cfg, run_num)
        except MissingComponentException as mce:
            compStrs = [str(x) for x in mce.components()]
            self.__daq_live.moniClient.sendMoni("missingComponent",
                                                {"components": compStrs,
                                                 "runConfig": str(run_cfg),
                                                 "runNumber": run_num})
            errmsg = "Cannot create run #%d runset for \"%s\": %s" % \
                     (run_num, run_cfg, str(mce))
            raise LiveException(errmsg)
        except:
            errmsg = "Cannot create run #%d runset for \"%s\": %s" % \
                     (run_num, run_cfg, exc_string())
            raise LiveException(errmsg)

        if runset is None:
            errmsg = "Cannot create run #%d runset for \"%s\"" % \
                     (run_num, run_cfg)
            raise LiveException(errmsg)

        runOptions = RunOption.LOG_TO_BOTH | RunOption.MONI_TO_FILE
        cnc.startRun(runset, run_num, runOptions)

        # we're now using the new runset
        self.__daq_live.set_runset(runset)


class StopThread(ActionThread):
    NAME = "LiveStop"

    def __init__(self, daq_live, logger, *args, **kwargs):
        super(StopThread, self).__init__(name=StopThread.NAME, args=args,
                                         kwargs=kwargs)

        self.__daq_live = daq_live
        self.__log = logger

    def run_action(self, *args, **kwargs):

        cnc = self.__daq_live.command_and_control

        if cnc.isStarting:
            cnc.stopCollecting()

        runset = self.__daq_live.runset

        # if the runset was destroyed, forget about it
        if runset is not None and runset.isDestroyed:
            self.__daq_live.set_runset(None)
            runset = None

        # no active runset, so there's nothing to stop
        if runset is None:
            return

        if runset.isReady or runset.isIdle:
            got_error = False
        else:
            got_error = runset.stop_run(runset.NORMAL_STOP)
            if not runset.isReady:
                raise LiveException("%s did not stop" % (runset, ))

        # XXX could get rid of this if 'livecmd' released runsets on exit
        #
        cnc.breakRunset(runset)
        if runset.isDestroyed:
            self.__daq_live.set_runset(None)

        if got_error:
            raise LiveException("Encountered ERROR while stopping run")


class SwitchThread(ActionThread):
    NAME = "LiveSwitch"

    def __init__(self, daq_live, logger, *args, **kwargs):
        super(SwitchThread, self).__init__(name=SwitchThread.NAME, args=args,
                                           kwargs=kwargs)

        self.__daq_live = daq_live
        self.__log = logger

    def run_action(self, *args, **kwargs):
        """
        Attempt to build a runset and start a run from within a thread.
        """
        # make sure we're not actively trying to stop
        (run_number, ) = args

        runset = self.__daq_live.runset
        runset.switch_run(run_number)


class DAQLive(LiveComponent):
    "Frequency of monitoring uploads"
    MONI_PERIOD = 60

    "Number of times to attempt recovery before giving up"
    MAX_RECOVERY_ATTEMPTS = 60

    def __init__(self, cnc, logger, rpc_port=DAQPort.DAQLIVE, timeout=None):
        if not LIVE_IMPORT:
            raise LiveException("Cannot import I3Live code")

        self.__cnc = cnc
        self.__log = logger

        self.__runSet = None

        self.__thread = None

        self.__recoverAttempts = 0

        self.__moniTimer = IntervalTimer("LiveMoni", DAQLive.MONI_PERIOD)

        if timeout is None:
            super(DAQLive, self).__init__(SERVICE_NAME, rpc_port,
                                          synchronous=True, lightSensitive=True,
                                          makesLight=True)
        else:
            super(DAQLive, self).__init__(SERVICE_NAME, rpc_port,
                                          synchronous=True, lightSensitive=True,
                                          makesLight=True, timeout=timeout)

    def __check_active_thread(self, name, action):
        """
        Return None if it's safe to start our thread
        Return True if our thread has finished
        Return INCOMPLETE_STATE_CHANGE if there's an active thread
        """
        # if there's no active thread, return None so our thread is started
        if self.__thread is None:
            return None

        # if the active thread is alive, try to join with it
        if self.__thread.is_alive():
            if not self.__thread.is_joined:
                # still waiting for the active thread
                return INCOMPLETE_STATE_CHANGE

        # the active thread is done
        dead_thread = self.__thread
        self.__thread = None

        # report any exceptions from the active thread
        if dead_thread.exception is not None:
            dead_thread.log_and_clear_exception(self.__log)

        # the active thread was our thread, we're done!
        if dead_thread.name == name:
            return True

        # an old thread has finished, return None so our thread is started
        return None

    @property
    def recoverAttempts(self):
        return self.__recoverAttempts

    def recovering(self, retry=True):
        # count another recovery attempt
        self.__recoverAttempts += 1

        chkval = self.__check_active_thread(RecoverThread.NAME, "recover")
        if chkval is not None:
            return chkval

        # start thread now, subsequent calls will check the thread result
        self.__thread = RecoverThread(self, self.__log)
        self.__thread.start()

        return INCOMPLETE_STATE_CHANGE


    @property
    def command_and_control(self):
        return self.__cnc

    def runChange(self, stateArgs=None):
        raise NotImplementedError()

    def running(self, retry=True):
        # if the runset was destroyed, forget about it
        if self.__runSet is not None and self.__runSet.isDestroyed:
            self.__runSet = None

        # this method doesn't start a thread, so we provide a fake name
        chkval = self.__check_active_thread("Fake Thread Name")
        if chkval is not None:
            return chkval

        if self.__runSet is None:
            raise LiveException("Cannot check run state; no active runset")

        if not self.__runSet.isRunning:
            raise LiveException("%s is not running (state = %s)" %
                                (self.__runSet, self.__runSet.state))

        if self.__moniTimer.isTime():
            self.__moniTimer.reset()
            self.__runSet.send_event_counts()

        return True

    @property
    def runset(self):
        return self.__runSet

    def set_runset(self, new_runset):
        self.__runSet = new_runset

    def starting(self, stateArgs=None):
        """
        Start a new pDAQ run
        stateArgs - should be a dictionary of run data:
            "runConfig" - the name of the run configuration
            "runNumber" - run number
            "subRunNumber" - subrun number
        """
        # validate state arguments
        if stateArgs is None or len(stateArgs) == 0:
            raise LiveException("No stateArgs specified")

        chkval = self.__check_active_thread(StartThread.NAME, "start")
        if chkval is not None:
            return chkval

        # reset recovery attempt counter
        self.__recoverAttempts = 0

        try:
            key = "runConfig"
            runCfg = stateArgs[key]

            key = "runNumber"
            runNum = stateArgs[key]
        except KeyError:
            raise LiveException("stateArgs does not contain key \"%s\"" %
                                (key, ))

        # start thread now, subsequent calls will check the thread result
        self.__thread = StartThread(self, self.__log, runCfg, runNum)
        self.__thread.start()

        return INCOMPLETE_STATE_CHANGE

    def stopping(self, stateArgs=None):
        debug = False
        if debug: self.__log.error("LiveStop: TOP")

        chkval = self.__check_active_thread(StopThread.NAME, "stop")
        if chkval is not None:
            return chkval

        # reset recovery attempt counter
        self.__recoverAttempts = 0

        if self.__runSet is None:
            return True

        # stop in a thread so we can return immediately
        self.__thread = StopThread(self, self.__log)
        self.__thread.start()
        return INCOMPLETE_STATE_CHANGE

    def subrun(self, subrunId, domList):
        if self.__runSet is None:
            raise LiveException("Cannot stop run; no active runset")

        self.__runSet.subrun(subrunId, domList)

        return "OK"

    def switchrun(self, stateArgs=None):
        if self.__runSet is None or self.__runSet.isDestroyed:
            raise LiveException("Cannot stop run; no active runset")

        if stateArgs is None or len(stateArgs) == 0:
            raise LiveException("No stateArgs specified")

        chkval = self.__check_active_thread(SwitchThread.NAME, "switch")
        if chkval is not None:
            return chkval

        # reset recovery attempt counter
        self.__recoverAttempts = 0

        try:
            key = "runNumber"
            runNum = stateArgs[key]
        except KeyError:
            raise LiveException("stateArgs does not contain key \"%s\"" % key)

        # start thread now, subsequent calls will check the thread result
        self.__thread = SwitchThread(self, self.__log, runNum)
        self.__thread.start()

        return INCOMPLETE_STATE_CHANGE

    def version(self):
        "Returns the current pDAQ release name"
        versionInfo = self.__cnc.versionInfo()
        return versionInfo["release"] + "_" + versionInfo["repo_rev"]
