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


class DAQLive(LiveComponent):
    "Frequency of monitoring uploads"
    MONI_PERIOD = 60

    "Number of times to attempt recovery before giving up"
    MAX_RECOVERY_ATTEMPTS = 60

    def __init__(self, cnc, logger, rpc_port=DAQPort.DAQLIVE, force_old=False):
        if not LIVE_IMPORT:
            raise LiveException("Cannot import I3Live code")

        self.__cnc = cnc
        self.__log = logger

        self.__oldAPI = force_old or INCOMPLETE_STATE_CHANGE is None

        self.__runSet = None

        self.__starting = False
        self.__startThrd = None
        self.__startExc = None

        self.__stopping = False
        self.__stopThrd = None
        self.__stopExc = None

        self.__recoverAttempts = 0

        self.__moniTimer = IntervalTimer("LiveMoni", DAQLive.MONI_PERIOD)

        super(DAQLive, self).__init__(SERVICE_NAME, rpc_port,
                                      synchronous=True, lightSensitive=True,
                                      makesLight=True)

    def __joinThread(self, thrd):
        thrd.join(1)
        return not thrd.isAlive()

    def __startInternal(self, runCfg, runNum):
        """
        Attempt to build a runset and start a run from within a thread.
        Returns if self.__starting is set to False.
        """
        # make sure we're not actively trying to stop
        if self.__stopping or self.__stopThrd is not None:
            if self.__stopThrd is not None:
                self.__log.error("Waiting for stopping thread before"
                                 " starting run %s" % (runNum, ))
                self.__stopThrd.join()
                self.__stopThrd = None
            self.__stopping = False

        if self.__runSet is not None:
            if not self.__runSet.isDestroyed:
                self.__cnc.breakRunset(self.__runSet)
            self.__runSet = None

            # if we got here after the start was cancelled, give up
            if not self.__starting:
                return

        try:
            runSet = self.__cnc.makeRunsetFromRunConfig(runCfg, runNum)
        except MissingComponentException as mce:
            compStrs = [str(x) for x in mce.components()]
            self.moniClient.sendMoni("missingComponent",
                                     {"components": compStrs,
                                      "runConfig": str(runCfg),
                                      "runNumber": runNum})
            errmsg = "Cannot create run #%d runset for \"%s\": %s" % \
                     (runNum, runCfg, str(mce))
            self.__log.error(errmsg)
            raise LiveException(errmsg)
        except:
            errmsg = "Cannot create run #%d runset for \"%s\": %s" % \
                     (runNum, runCfg, exc_string())
            self.__log.error(errmsg)
            raise LiveException(errmsg)

        if runSet is None:
            errmsg = "Cannot create run #%d runset for \"%s\"" % \
                     (runNum, runCfg)
            self.__log.error(errmsg)
            raise LiveException(errmsg)

        if self.__starting:
            runOptions = RunOption.LOG_TO_BOTH | RunOption.MONI_TO_FILE
            self.__cnc.startRun(runSet, runNum, runOptions)

        # we successfully started!
        if self.__starting:
            # signal that we're running
            self.__runSet = runSet
        else:
            # darn, we're being asked to stop so undo all that work :-(
            self.__cnc.breakRunset(runSet)

    def __startRun(self, runCfg, runNum):
        """
        Method used by the startRun thread.
        Guarantees that self.__starting is set to False before it exits
        """

        # set up a couple of state variables
        self.__starting = True
        self.__startExc = None

        try:
            self.__startInternal(runCfg, runNum)
        except Exception as exc:
            if self.__startExc is None:
                self.__startExc = exc
        finally:
            self.__starting = False

    def __stopInternal(self):
        if self.__startThrd is not None:
            self.__log.error("Waiting for starting thread before stopping run")
            self.__startThrd.join()
            self.__startThrd = None

        if self.__starting:
            self.__cnc.stopCollecting()
            self.__starting = False

        # if the runset was destroyed, forget about it
        if self.__runSet is not None and self.__runSet.isDestroyed:
            self.__runSet = None

        # no active runset, so there's nothing to stop
        if self.__runSet is None:
            return

        if self.__runSet.isReady or self.__runSet.isIdle:
            got_error = False
        else:
            got_error = self.__runSet.stop_run(self.__runSet.NORMAL_STOP)
            if not self.__runSet.isReady:
                raise LiveException("%s did not stop" % (self.__runSet, ))

        # XXX could get rid of this if 'livecmd' released runsets on exit
        #
        self.__cnc.breakRunset(self.__runSet)
        if self.__runSet.isDestroyed:
            self._runSet = None

        if got_error:
            raise LiveException("Encountered ERROR while stopping run")

    def __stopRun(self):
        """
        Method used by the stopRun thread.
        Guarantees that self.__stopping is set to False before it exits
        """

        # set up a couple of state variables
        self.__stopping = True
        self.__stopExc = None

        try:
            self.__stopInternal()
        except Exception as exc:
            if self.__stopExc is None:
                self.__stopExc = exc
        finally:
            self.__stopping = False

    def recovering(self, retry=True):
        # count another recovery attempt
        self.__recoverAttempts += 1

        # if no active runset, nothing to recover
        if self.__stopping:
            if self.__stopThrd is not None:
                if self.__oldAPI:
                    self.__stopThrd.join()
                elif not self.__joinThread(self.__stopThrd):
                    return INCOMPLETE_STATE_CHANGE

                self.__stopThrd = None
                if self.__stopExc is not None:
                    self._log.error("While recovering, saw stopping"
                                    " exception: %s" % (self.__stopExc, ))
                    self.__stopExc = None

                # done stopping
                self.__stopping = False

        # if the runset was destroyed, forget about it
        if self.__runSet is not None and self.__runSet.isDestroyed:
            self.__runSet = None

        if self.__runSet is None:
            if not self.__starting:
                # is there's no runset and we're not starting, we're recovered
                return True

            if self.__startThrd is not None:
                if self.__oldAPI:
                    self.__startThrd.join()
                elif not self.__joinThread(self.__startThrd):
                    return INCOMPLETE_STATE_CHANGE

                self.__startThrd = None
                if self.__startExc is not None:
                    self._log.error("While recovering, saw starting"
                                    " exception: %s" % (self.__startExc, ))
                    self.__startExc = None

            # done starting
            self.__starting = False

            # if runset is still not set, we're recovered
            if self.__runSet is None:
                return True

        if self.__runSet.isReady or self.__runSet.isIdle or \
           self.__runSet.isDestroyed:
            # if we're in a known non-running state, we're done
            return True

        # if runset isn't stopping, try to stop it
        if not self.__runSet.stopping():
            try:
                stopVal = not self.__runSet.stop_run("LiveRecover",
                                                     had_error=True)
                if stopVal:
                    self.__log.error("DAQLive stop_run %s returned %s" %
                                     (self.__runSet, stopVal))
            except:
                self.__log.error("DAQLive stop_run %s failed: %s" %
                                 (self.__runSet, exc_string()))

        # give runset a bit of time to finish stopping
        waitSecs = 5
        numTries = 12
        for _ in range(numTries):
            if not self.__runSet.stopping():
                break
            time.sleep(waitSecs)

        # report final state
        rtnVal = False
        if self.__runSet is None or self.__runSet.isDestroyed:
            self.__log.error("DAQLive destroyed %s" % (self.__runSet, ))
            self.__runSet = None
            return True
        if self.__runSet.isReady or self.__runSet.isIdle:
            return True
        if self.__runSet.stopping():
            self.__log.error("DAQLive giving up on hung %s" %
                             (self.__runSet, ))
        else:
            self.__log.error("DAQLive cannot recover %s (state=%s)" %
                             (self.__runSet, self.__runSet.state))

        if self.__recoverAttempts < self.MAX_RECOVERY_ATTEMPTS:
            time.sleep(1)
            return INCOMPLETE_STATE_CHANGE

        raise LiveException("Runset %s was not recovered after %d attempts" %
                            (self.__runSet, self.__recoverAttempts))

    def runChange(self, stateArgs=None):
        raise NotImplementedError()

    def running(self, retry=True):
        # if the runset was destroyed, forget about it
        if self.__runSet is not None and self.__runSet.isDestroyed:
            self.__runSet = None

        if self.__stopping or self.__stopThrd is not None:
            raise LiveException("pDAQ has not finished stopping")

        if self.__runSet is None:
            if self.__starting:
                if self.__oldAPI:
                    return True

                raise LiveException("pDAQ has not yet finished starting")

            if self.__startThrd is not None:
                if self.__joinThread(self.__startThrd):
                    self.__startThrd = None

            if self.__startExc is not None:
                exc = self.__startExc
                self.__startExc = None
                raise exc

            if not self.__starting and self.__runSet is None:
                raise LiveException("Cannot check run state; no active runset")

        if not self.__runSet.isRunning:
            raise LiveException("%s is not running (state = %s)" %
                                (self.__runSet, self.__runSet.state))

        if self.__moniTimer.isTime():
            self.__moniTimer.reset()
            self.__runSet.send_event_counts()

        return True

    def starting(self, stateArgs=None):
        """
        Start a new pDAQ run
        stateArgs - should be a dictionary of run data:
            "runConfig" - the name of the run configuration
            "runNumber" - run number
            "subRunNumber" - subrun number
        """
        # reset recovery attempt counter
        self.__recoverAttempts = 0

        # if there was an exception in the startup thread, rethrow it here
        if self.__startExc is not None:
            exc = self.__startExc
            self.__startExc = None
            raise exc

        # if the runset was destroyed, forget about it
        if self.__runSet is not None and self.__runSet.isDestroyed:
            self.__runSet = None

        # if we have a runset, we're ready to run!
        if self.__runSet is not None and self.__runSet.isRunning:
            if self.__startThrd is not None:
                if self.__joinThread(self.__startThrd):
                    self.__startThrd = None

            return True

        # if we haven't tried starting yet...
        if not self.__starting:
            if stateArgs is None or len(stateArgs) == 0:
                raise LiveException("No stateArgs specified")

            try:
                key = "runConfig"
                runCfg = stateArgs[key]

                key = "runNumber"
                runNum = stateArgs[key]
            except KeyError:
                raise LiveException("stateArgs does not contain key \"%s\"" %
                                    (key, ))

            # start DAQ in a thread so we can return immediately
            self.__startThrd = threading.Thread(target=self.__startRun,
                                                args=(runCfg, runNum))
            self.__startThrd.start()

        if self.__oldAPI:
            self.__startThrd.join()
            self.__startThrd = None

            if self.__startExc is not None:
                exc = self.__startExc
                self.__startExc = None
                raise exc

            return True

        return INCOMPLETE_STATE_CHANGE

    def stopping(self, stateArgs=None):
        # if there was an exception in the startup thread, rethrow it here
        if self.__stopExc is not None:
            exc = self.__stopExc
            self.__stopExc = None
            raise exc

        # if we're not stopping yet, start the thread now
        if not self.__stopping:
            if self.__runSet is not None and self.__runSet.isRunning:
                # stop in a thread so we can return immediately
                self.__stopThrd = threading.Thread(target=self.__stopRun)
                self.__stopThrd.start()
        else:
            # if we're stopping, try to join with the thread
            if self.__stopThrd is not None:
                if self.__joinThread(self.__stopThrd):
                    self.__stopThrd = None

            return True

        if self.__oldAPI:
            self.__stopThrd.join()
            self.__stopThrd = None
            if self.__stopExc is not None:
                exc = self.__stopExc
                self.__stopExc = None
                raise exc

            return True

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

        try:
            key = "runNumber"
            runNum = stateArgs[key]
        except KeyError:
            raise LiveException("stateArgs does not contain key \"%s\"" % key)

        self.__runSet.switch_run(runNum)

        return "OK"

    def version(self):
        "Returns the current pDAQ release name"
        versionInfo = self.__cnc.versionInfo()
        return versionInfo["release"] + "_" + versionInfo["repo_rev"]
