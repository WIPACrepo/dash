#!/usr/bin/env python

import threading
import time

from CnCExceptions import MissingComponentException
from DAQConst import DAQPort
from IntervalTimer import IntervalTimer
from LiveImports import Component, LIVE_IMPORT, SERVICE_NAME
from RunOption import RunOption
from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class LiveException(Exception):
    pass


class DAQLive(Component):
    "Frequency of monitoring uploads"
    MONI_PERIOD = 60

    def __init__(self, cnc, logger):
        if not LIVE_IMPORT:
            raise LiveException("Cannot import I3Live code")

        self.__cnc = cnc
        self.__log = logger

        self.__starting = False
        self.__startThrd = None
        self.__startExc = None

        self.__runSet = None

        self.__moniTimer = IntervalTimer("LiveMoni", DAQLive.MONI_PERIOD)

        super(DAQLive, self).__init__(SERVICE_NAME, DAQPort.DAQLIVE,
                                      synchronous=True, lightSensitive=True,
                                      makesLight=True)

    def __startInternal(self, runCfg, runNum):
        """
        Attempt to build a runset and start a run from within a thread.
        Returns if self.__starting is set to False.
        Any errors are saved to self.__startExc
        """
        self.__startExc = None

        if self.__runSet is not None and not self.__runSet.isDestroyed:
            self.__cnc.breakRunset(self.__runSet)
            if not self.__starting:
                return

        self.__runSet = None
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
            self.__startExc = LiveException(errmsg)
            return
        except:
            errmsg = "Cannot create run #%d runset for \"%s\": %s" % \
                     (runNum, runCfg, exc_string())
            self.__log.error(errmsg)
            self.__startExc = LiveException(errmsg)
            return

        if runSet is None:
            errmsg = "Cannot create run #%d runset for \"%s\"" % \
                     (runNum, runCfg)
            self.__log.error(errmsg)
            self.__startExc = LiveException(errmsg)
            return

        if self.__starting:
            self.__runSet = runSet
            runOptions = RunOption.LOG_TO_BOTH | RunOption.MONI_TO_FILE
            self.__cnc.startRun(runSet, runNum, runOptions)

        if not self.__starting:
            self.__cnc.breakRunset(runSet)

    def __startRun(self, runCfg, runNum):
        """
        Method used by the startRun thread.
        Guarantees that self.__starting is set to False before it exits
        """
        try:
            self.__startInternal(runCfg, runNum)
        finally:
            self.__starting = False

    def recovering(self, retry=True):
        rtnVal = True
        if self.__runSet is None:
            # if no active runset, nothing to recover
            pass
        else:
            if self.__runSet.isDestroyed:
                self.__runSet = None
            elif not self.__runSet.isReady:
                if not self.__runSet.stopping():
                    stopVal = not self.__runSet.stop_run("LiveRecover",
                                                         had_error=True)
                    self.__log.error("DAQLive stopRun %s returned %s" %
                                     (self.__runSet, stopVal))

                waitSecs = 5
                numTries = 12
                for _ in range(numTries):
                    if not self.__runSet.stopping():
                        break
                    time.sleep(waitSecs)
                if self.__runSet.isDestroyed:
                    self.__log.error("DAQLive destroyed %s" % self.__runSet)
                    self.__runSet = None
                    rtnVal = True
                elif self.__runSet.stopping():
                    self.__log.error("DAQLive giving up on hung %s" %
                                     self.__runSet)
                    rtnVal = False
                elif not self.__runSet.isReady:
                    self.__log.error("DAQLive cannot recover %s" %
                                     self.__runSet)
                    rtnVal = False
                else:
                    self.__log.error("DAQLive recovered %s" % self.__runSet)
                    rtnVal = True

        return rtnVal

    def runChange(self, stateArgs=None):
        raise NotImplementedError()

    def running(self, retry=True):
        if self.__starting:
            return True

        if self.__startThrd is not None:
            self.__startThrd.join(1)
            if not self.__startThrd.isAlive():
                self.__startThrd = None

        if self.__runSet is None:
            raise LiveException("Cannot check run state; no active runset")

        if self.__startExc is not None:
            exc = self.__startExc
            self.__startExc = None
            raise exc

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
        if stateArgs is None or len(stateArgs) == 0:
            raise LiveException("No stateArgs specified")

        try:
            key = "runConfig"
            runCfg = stateArgs[key]

            key = "runNumber"
            runNum = stateArgs[key]
        except KeyError:
            raise LiveException("stateArgs does not contain key \"%s\"" % key)

        if self.__startThrd is not None:
            self.__startThrd.join(1)
            if not self.__startThrd.isAlive():
                self.__startThrd = None

        # start DAQ in a thread so we can return immediately
        self.__starting = True
        self.__startThrd = threading.Thread(target=self.__startRun,
                                            args=(runCfg, runNum))
        self.__startThrd.start()

        return True

    def stopping(self, stateArgs=None):
        if self.__starting:
            self.__cnc.stopCollecting()
            self.__starting = False
            return

        if self.__runSet is None:
            raise LiveException("Cannot stop run; no active runset")

        if self.__startThrd is not None:
            self.__startThrd.join(1)
            if not self.__startThrd.isAlive():
                self.__startThrd = None

        gotError = self.__runSet.stop_run(self.__runSet.NORMAL_STOP)
        if not self.__runSet.isReady:
            raise LiveException("%s did not stop" % self.__runSet)

        # XXX could get rid of this if 'livecmd' released runsets on exit
        #
        self.__cnc.breakRunset(self.__runSet)

        if gotError:
            raise LiveException("Encountered ERROR while stopping run")

        return True

    def subrun(self, subrunId, domList):
        if self.__runSet is None:
            raise LiveException("Cannot stop run; no active runset")

        self.__runSet.subrun(subrunId, domList)

        return "OK"

    def switchrun(self, stateArgs=None):
        if self.__runSet is None:
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
