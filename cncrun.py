#!/usr/bin/env python
#
# Manage pDAQ runs via CnCServer
#
# Examples:
#
#     # create a CnCRun object
#     run = CnCRun()
#
#     clusterConfig = "spts64-real-21-29"
#     runConfig = "spts64-dirtydozen-hlc-006"
#     numSecs = 60                             # number of seconds
#     numRuns = 1
#
#     # an ordinary run
#     run.run(clusterConfig, runConfig, numSecs, numRuns)
#
#     flashFile = "flash-21.xml"
#     flashTimes = (30, 30, 20, 15)            # number of seconds
#     pauseTime = 30                           # number of seconds
#
#     # a flasher run
#     run.run(clusterConfig, runConfig, numSecs, numRuns)
#             flashFile, flashTimes, flashPause)

import os, re, socket, sys, time

from DAQConst import DAQPort
from DAQRPC import RPCClient
from BaseRun import BaseRun, RunException, StateException
from RunOption import RunOption
from RunSetState import RunSetState
import subprocess

class CnCRun(BaseRun):
    def __init__(self, showCmd=False, showCmdOutput=False, dbType=None):
        self.__showCmd = showCmd
        self.__showCmdOutput = showCmdOutput

        self.__cnc = None
        self.__reconnect(False)

        self.__runNumFile = \
            os.path.join(os.environ["HOME"], ".i3live-run")

        super(CnCRun, self).__init__(showCmd, showCmdOutput, dbType)

        self.__runSetId = None
        self.__runCfg = None
        self.__runNum = None

    def __reconnect(self, abortOnFail=True):
        self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)
        try:
            self.__cnc.rpc_ping()
        except socket.error, err:
            if err[0] == 61 or err[0] == 111:
                self.__cnc = None
            else:
                raise

        if self.__cnc is None and abortOnFail:
            raise RunException("Cannot connect to CnCServer")

    def __setLastRunNumber(self, runNum, subRunNum):
        "Set the last used run number"
        fd = open(self.__runNumFile, "w")
        print >>fd, "%d %d" % (runNum, subRunNum)
        fd.close()

    def __status(self):
        "Print the current DAQ status"

        if not self.__showCmdOutput: return

        cmd = "DAQStatus.py"
        if self.__showCmd: print cmd
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        for line in proc.stdout:
            line = line.rstrip()
            print '+ ' + line
        proc.stdout.close()

        proc.wait()

    def __waitForState(self, expState, numTries, numErrors=0, waitSecs=10):
        """
        Wait for the specified state

        expState - expected final state
        numTries - number of tries before ceasing to wait
        numErrors - number of ERROR states allowed before assuming
                    there is a problem
        waitSecs - number of seconds to wait on each "try"
        """
        if self.__runSetId is None:
            return False

        self.__status()

        prevState = self.__cnc.rpc_runset_state(self.__runSetId)
        curState = prevState

        if prevState != expState:
            print "Switching from %s to %s" % (prevState, expState)

        startTime = time.time()
        for i in range(numTries):
            if curState == RunSetState.UNKNOWN:
                break

            curState = self.__cnc.rpc_runset_state(self.__runSetId)
            if curState != prevState:
                swTime = int(time.time() - startTime)
                print "  Switched from %s to %s in %s secs" % \
                    (prevState, curState, swTime)

                prevState = curState
                startTime = time.time()

            if curState == expState:
                break

            if numErrors > 0 and curState == RunSetState.ERROR:
                time.sleep(5)
                numErrors -= 1
                continue

            if curState != RunSetState.RESETTING:
                raise StateException("DAQ state should be RESETTING, not %s" %
                                     curState)

            time.sleep(waitSecs)

        if curState != expState:
            totTime = int(time.time() - startTime)
            raise StateException(("DAQ state should be %s, not %s" +
                                  " (waited %d secs)") %
                                 (expState, curState, totTime))

        return True

    def cleanUp(self):
        """Do final cleanup before exiting"""
        if self.__runSetId is not None:
            self.__cnc.rpc_runset_break(self.__runSetId)
            self.__runSetId = None

    def flash(self, tm, data):
        """Start flashers for the specified duration with the specified data"""
        print >>sys.stderr, "Not doing flashers"

    def getLastRunNumber(self):
        "Return the last run number"
        if not os.path.exists(self.__runNumFile):
            return 0
        line = open(self.__runNumFile).readline()
        m = re.search('(\d+)\s+(\d+)', line)
        if not m:
            return 0
        return int(m.group(1))

    def getRunNumber(self):
        "Return the current run number"
        if self.__runSetId is None:
            return None
        return self.__runNum

    def isDead(self):
        return self.__cnc is None

    def isRecovering(self, refreshState=False):
        return False

    def isRunning(self):
        if self.__cnc is None:
            self.__reconnect(False)
        if self.__runSetId is None:
            return False
        try:
            state = self.__cnc.rpc_runset_state(self.__runSetId)
            return state == RunSetState.RUNNING
        except socket.error, err:
            return False

    def isStopped(self, refreshState=False):
        if self.__cnc is None:
            self.__reconnect(False)
        if self.__cnc is None or self.__runSetId is None:
            return True
        try:
            state = self.__cnc.rpc_runset_state(self.__runSetId)
            return state == RunSetState.READY
        except socket.error, err:
            return False

    def isStopping(self, refreshState=False):
        if self.__cnc is None:
            self.__reconnect(False)
        if self.__cnc is None or self.__runSetId is None:
            return False
        try:
            state = self.__cnc.rpc_runset_state(self.__runSetId)
            return state == RunSetState.STOPPING
        except socket.error, err:
            return False

    def setLightMode(self, isLID):
        """
        Set the Light-In-Detector mode

        isLID - True for light-in-detector mode, False for dark mode

        Return True if the light mode was set successfully
        """
        if isLID:
            print >>sys.stderr, "Not setting light mode!!!"
        return True

    def startRun(self, runCfg, duration, numRuns=1, ignoreDB=False):
        """
        Start a run

        runCfg - run configuration file name
        duration - number of seconds for run
        numRuns - number of runs (default=1)
        ignoreDB - don't check the database for this run config

        Return True if the run was started
        """
        if self.__cnc is None:
            self.__reconnect()

        if self.__runSetId is not None and self.__runCfg is not None and \
                self.__runCfg != runCfg:
            self.__runCfg = None
            self.__cnc.rpc_runset_break(self.__runSetId)
            self.__runSetId = None

        if self.__runSetId is None:
            runSetId = self.__cnc.rpc_runset_make(runCfg)
            if runSetId < 0:
                raise RunException("Could not create runset for \"%s\"" %
                                   runCfg)

            self.__runSetId = runSetId
            self.__runCfg = runCfg

        self.__runNum = self.getLastRunNumber() + 1
        self.__setLastRunNumber(self.__runNum, 0)

        runOptions = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        self.__cnc.rpc_runset_start_run(self.__runSetId, self.__runNum,
                                        runOptions)

        return True

    def state(self):
        if self.__cnc is None:
            self.__reconnect(False)
        if self.__cnc is None:
            return "DEAD"
        if self.__runSetId is None:
            return "STOPPED"
        try:
            state = self.__cnc.rpc_runset_state(self.__runSetId)
            return str(state).upper()
        except:
            return "ERROR"

    def stopRun(self):
        """Stop the run"""
        if self.__runSetId is None:
            raise RunException("No active run")

        if self.__cnc is None:
            self.__reconnect()

        self.__cnc.rpc_runset_stop_run(self.__runSetId)

    def waitForStopped(self):
        """Wait for the current run to be stopped"""
        try:
            state = self.__cnc.rpc_runset_state(self.__runSetId)
        except:
            state = RunSetState.ERROR

        if state == RunSetState.UNKNOWN:
            self.__runSetId = None
            return True

        return self.__waitForState(RunSetState.READY, 10)

if __name__ == "__main__":
    run = CnCRun(True, True)
    run.run("spts64-real-21-29", "spts64-dirtydozen-hlc-006", 30,
            "flash-21.xml", (5, 5), 10)
