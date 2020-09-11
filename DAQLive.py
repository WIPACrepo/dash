#!/usr/bin/env python

import threading
import time
import traceback

from CnCExceptions import MissingComponentException
from DAQConst import DAQPort
from IntervalTimer import IntervalTimer
from LiveImports import INCOMPLETE_STATE_CHANGE, LIVE_IMPORT, LiveComponent, \
    SERVICE_NAME
from RunOption import RunOption
from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class LiveException(Exception):
    "General DAQLive exception"


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
        except Exception as exc:  # pylint: disable=broad-except
            if self.__exception is None:
                self.__exception = exc

    def run_action(self, *args, **kwargs):
        raise NotImplementedError()


class RecoverThread(ActionThread):
    NAME = "LiveRecover"

    "Number of times to attempt recovery before giving up"
    MAX_RECOVERY_ATTEMPTS = 60

    def __init__(self, daq_live, logger, *args, **kwargs):
        super(RecoverThread, self).__init__(name=RecoverThread.NAME, args=args,
                                            kwargs=kwargs)

        self.__daq_live = daq_live
        self.__log = logger

    def run_action(self, *args, **kwargs):
        cnc = self.__daq_live.command_and_control
        runset = self.__daq_live.runset

        # if the runset was destroyed, forget about it
        if runset is not None and runset.is_destroyed:
            runset = None
            self.__daq_live.runset = runset

        if runset is None:
            if not cnc.is_starting:
                # is there's no runset and we're not starting, we're recovered
                return True

            # if runset is still not set, we're recovered
            if runset is None:
                return True

        if runset.is_ready or runset.is_idle or \
           runset.is_destroyed:
            # if we're in a known non-running state, we're done
            return True

        # if runset isn't stopping, try to stop it
        if not runset.stopping():
            try:
                self.__log.error("DAQLive has detected a problem and is"
                                 " killing the run")

                stop_val = not runset.stop_run("LiveRecover", had_error=True)
                if stop_val:
                    self.__log.error("DAQLive stop_run %s returned %s" %
                                     (runset, stop_val))
            except:  # pylint: disable=bare-except
                self.__log.error("DAQLive stop_run %s failed: %s" %
                                 (runset, exc_string()))

        # give runset a bit of time to finish stopping
        wait_secs = 5
        num_tries = 12
        for _ in range(num_tries):
            if not runset.stopping():
                break
            time.sleep(wait_secs)

        # report final state
        if runset is None or runset.is_destroyed:
            self.__log.error("DAQLive destroyed %s" % (runset, ))
            runset = None
            return True
        if runset.is_ready or runset.is_idle:
            return True
        if runset.stopping():
            self.__log.error("DAQLive giving up on hung %s" %
                             (runset, ))
        else:
            self.__log.error("DAQLive cannot recover %s (state=%s)" %
                             (runset, runset.state))

        attempts = self.__daq_live.recover_attempts
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
        (run_cfg, run_num, extended_mode) = args

        cnc = self.__daq_live.command_and_control

        runset = self.__daq_live.runset

        if runset is not None:
            if runset.is_running:
                # if we have a runset, we're ready to run!
                return True

            if runset.is_destroyed:
                # if the runset was destroyed, forget about it
                runset = None
            else:
                cnc.break_runset(runset)
            self.__daq_live.runset = None

        try:
            runset = cnc.make_runset_from_run_config(run_cfg, run_num)
        except MissingComponentException as mce:
            comp_strs = [str(x) for x in mce.components]
            self.__daq_live.moniClient.sendMoni("missingComponent",
                                                {"components": comp_strs,
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

        run_options = RunOption.LOG_TO_BOTH | RunOption.MONI_TO_FILE
        if extended_mode:
            run_options |= RunOption.EXTENDED_MODE
        cnc.start_run(runset, run_num, run_options)

        # we're now using the new runset
        self.__daq_live.runset = runset

        return True


class StopThread(ActionThread):
    NAME = "LiveStop"

    def __init__(self, daq_live, logger, *args, **kwargs):
        super(StopThread, self).__init__(name=StopThread.NAME, args=args,
                                         kwargs=kwargs)

        self.__daq_live = daq_live
        self.__log = logger

    def run_action(self, *args, **kwargs):

        cnc = self.__daq_live.command_and_control

        if cnc.is_starting:
            cnc.stop_collecting()

        runset = self.__daq_live.runset

        # if the runset was destroyed, forget about it
        if runset is not None and runset.is_destroyed:
            self.__daq_live.runset = None
            runset = None

        # no active runset, so there's nothing to stop
        if runset is None:
            return

        if runset.is_ready or runset.is_idle:
            got_error = False
        else:
            got_error = runset.stop_run(runset.NORMAL_STOP)
            if not runset.is_ready:
                raise LiveException("%s did not stop" % (runset, ))

        # XXX could get rid of this if 'livecmd' released runsets on exit
        #
        cnc.break_runset(runset)
        if runset.is_destroyed:
            self.__daq_live.runset = None

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

    def __init__(self, cnc, logger, rpc_port=DAQPort.DAQLIVE, timeout=None):
        if not LIVE_IMPORT:
            raise LiveException("Cannot import I3Live code")

        self.__cnc = cnc
        self.__log = logger

        self.__runset = None

        self.__thread = None

        self.__recover_attempts = 0

        self.__moni_timer = IntervalTimer("LiveMoni", DAQLive.MONI_PERIOD)

        if timeout is None:
            super(DAQLive, self).__init__(SERVICE_NAME, rpc_port,
                                          synchronous=True,
                                          lightSensitive=True, makesLight=True)
        else:
            super(DAQLive, self).__init__(SERVICE_NAME, rpc_port,
                                          synchronous=True,
                                          lightSensitive=True, makesLight=True,
                                          timeout=timeout)

    def __check_active_thread(self, name):
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
    def recover_attempts(self):
        return self.__recover_attempts

    def recovering(self, _=None):
        # count another recovery attempt
        self.__recover_attempts += 1

        chkval = self.__check_active_thread(RecoverThread.NAME)
        if chkval is not None:
            return chkval

        # start thread now, subsequent calls will check the thread result
        self.__thread = RecoverThread(self, self.__log)
        self.__thread.start()

        return INCOMPLETE_STATE_CHANGE

    @property
    def command_and_control(self):
        return self.__cnc

    def running(self, _=None):
        # if the runset was destroyed, forget about it
        if self.__runset is not None and self.__runset.is_destroyed:
            self.__log.error("DAQLive.running() throwing away destroyed"
                             " runset")
            self.__runset = None

        # this method doesn't start a thread, so we provide a fake name
        # it *should* always return None or INCOMPLETE
        if self.__thread is not None:
            self.__log.error("DAQLive.running() is ignoring old thread %s" %
                             str(self.__thread))
            try:
                _ = self.__check_active_thread("Fake Thread Name")
            except:
                self.__log.error("DAQLive.running() dying due to check_thread"
                                 " exception\n" + traceback.format_exc())
                raise

        if self.__runset is None:
            self.__log.error("DAQLive.running() dying due to missing runset")
            raise LiveException("Cannot check run state; no active runset")

        if not self.__runset.is_running:
            self.__log.error("DAQLive.running() dying due to stopped runset")
            raise LiveException("%s is not running (state = %s)" %
                                (self.__runset, self.__runset.state))

        if self.__moni_timer.is_time():
            try:
                self.__moni_timer.reset()
                self.__runset.send_event_counts()
            except:
                self.__log.error("DAQLive.running() dying due to moni"
                                 " exception\n" + traceback.format_exc())
                raise

        return True

    @property
    def runset(self):
        return self.__runset

    @runset.setter
    def runset(self, new_runset):
        self.__runset = new_runset

    def starting(self, stateArgs=None):
        """
        Start a new pDAQ run
        stateArgs - should be a dictionary of run data:
            "runConfig" - the name of the run configuration
            "runNumber" - run number
            "subRunNumber" - subrun number
            "extendedMode" - True if extended mode is enabled
        """
        # validate state arguments
        if stateArgs is None or \
          len(stateArgs) == 0:  # pylint: disable=len-as-condition
            raise LiveException("No state argumentss specified")

        chkval = self.__check_active_thread(StartThread.NAME)
        if chkval is not None:
            return chkval

        # reset recovery attempt counter
        self.__recover_attempts = 0

        try:
            key = "runConfig"
            run_cfg = stateArgs[key]

            key = "runNumber"
            run_num = stateArgs[key]
        except KeyError:
            raise LiveException("State arguments do not contain key \"%s\"" %
                                (key, ))

        # check for new 'extendedMode' flag
        # TODO: Make this a required argument after Basilisk is released
        try:
            key = "extendedMode"
            extended_mode = stateArgs[key]
        except KeyError:
            # raise LiveException("State arguments do not contain key \"%s\"" %
            #                     (key, ))
            extended_mode = False

        # start thread now, subsequent calls will check the thread result
        self.__thread = StartThread(self, self.__log, run_cfg, run_num,
                                    extended_mode)
        self.__thread.start()

        return INCOMPLETE_STATE_CHANGE

    def stopping(self, _=None):
        debug = False
        if debug:
            self.__log.error("LiveStop: TOP")

        chkval = self.__check_active_thread(StopThread.NAME)
        if chkval is not None:
            return chkval

        # reset recovery attempt counter
        self.__recover_attempts = 0

        if self.__runset is None:
            return True

        # stop in a thread so we can return immediately
        self.__thread = StopThread(self, self.__log)
        self.__thread.start()
        return INCOMPLETE_STATE_CHANGE

    def subrun(self, subRun, domList):
        if self.__runset is None:
            raise LiveException("Cannot stop run; no active runset")

        self.__runset.subrun(subRun, domList)

        return "OK"

    def switchrun(self, stateArgs=None):
        if self.__runset is None or self.__runset.is_destroyed:
            raise LiveException("Cannot switch run; no active runset")

        if stateArgs is None or \
          len(stateArgs) == 0:  # pylint: disable=len-as-condition
            raise LiveException("No state argumentss specified for switchrun")

        if self.__thread is None:
            thrd_name = "UNKNOWN"
        else:
            thrd_name = self.__thread.name

        chkval = self.__check_active_thread(SwitchThread.NAME)
        if chkval is not None:
            if self.__thread is None:
                self.__log.warn("SwitchRun is returning %s after ending"
                                " %s thread" % (chkval, thrd_name))
            else:
                self.__log.warn("SwitchRun is waiting for thread %s" %
                                (thrd_name, ))
            return chkval

        # reset recovery attempt counter
        self.__recover_attempts = 0

        try:
            key = "runNumber"
            run_num = stateArgs[key]
        except KeyError:
            raise LiveException("State arguments do not contain key \"%s\"" %
                                (key, ))

        # start thread now, subsequent calls will check the thread result
        self.__thread = SwitchThread(self, self.__log, run_num)
        self.__thread.start()

        return INCOMPLETE_STATE_CHANGE

    def version(self):
        "Returns the current pDAQ release name"
        version_info = self.__cnc.version_info()
        return version_info["release"] + "_" + version_info["repo_rev"]
