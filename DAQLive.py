#!/usr/bin/env python

import sys

from DAQConst import DAQPort
from IntervalTimer import IntervalTimer
from LiveImports import Component, SERVICE_NAME
from RunOption import RunOption

class LiveException(Exception): pass
class UnimplementedException(LiveException): pass

class DAQLive(Component):
    "Frequency of monitoring uploads"
    MONI_PERIOD = 60

    def __init__(self, cnc, logger):
        self.__cnc = cnc
        self.__log = logger

        self.__runSet = None

        self.__moniTimer = IntervalTimer("LiveMoni", DAQLive.MONI_PERIOD)

        super(DAQLive, self).__init__(SERVICE_NAME, DAQPort.DAQLIVE,
                                        synchronous=True, lightSensitive=True,
                                        makesLight=True)

    def recovering(self, retry=True):
        rtnVal = True
        if self.__runSet is None:
            # if no active runset, nothing to recover
            pass
        else:
            if self.__runSet.isDestroyed():
                self.__runSet = None
            elif not self.__runSet.isReady():
                rtnVal = not self.__runSet.stopRun(hadError=True)
                self.__log.error("DAQLive recovered %s" % self.__runSet)

        return rtnVal

    def runChange(self, stateArgs=None): raise UnimplementedException()

    def running(self, retry=True):
        if self.__runSet is None:
            raise LiveException("Cannot check run state; no active runset")

        if not self.__runSet.isRunning():
            raise LiveException("%s is not running (state = %s)" %
                                (self.__runSet, self.__runSet.state()))

        if self.__moniTimer.isTime():
            self.__moniTimer.reset()
            self.__runSet.sendEventCounts()

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

        if self.__runSet is not None and not self.__runSet.isDestroyed():
            self.__cnc.breakRunset(self.__runSet)

        self.__runSet = self.__cnc.makeRunsetFromRunConfig(runCfg)
        if self.__runSet is None:
            raise LiveException("Cannot create runset for \"%s\"" % runCfg)

        runOptions = RunOption.LOG_TO_BOTH | RunOption.MONI_TO_FILE
        self.__cnc.startRun(self.__runSet, runNum, runOptions)

        return True

    def stopping(self, stateArgs=None):
        if self.__runSet is None:
            raise LiveException("Cannot stop run; no active runset")

        gotError = self.__runSet.stopRun()

        self.__runSet.sendEventCounts()

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

    def version(self):
        "Returns the current pDAQ release name"
        versionInfo = self.__cnc.versionInfo()
        return versionInfo["release"] + "_" + versionInfo["repo_rev"]
