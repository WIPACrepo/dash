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
#
#     # an ordinary run
#     run.run(clusterConfig, runConfig, numSecs)
#
#     flasherData = \
#         (("flash-21.xml", 30),               # flash string 21 for 30 seconds
#          (None, 15),                         # wait 15 seconds
#          ("flash-26-27.xml", 120),           # flash 26 & 27 for 2 minutes
#          (None, 20),                         # wait 20 seconds
#          ("flash-21.xml", 30))               # flash string 21 for 30 seconds
#
#     # a flasher run
#     run.run(clusterConfig, runConfig, numSecs, flasherData)

import os
import re
import socket
import subprocess
import time

from BaseRun import BaseRun, RunException, StateException
from DefaultDomGeometry import XMLParser
from RunOption import RunOption
from RunSetState import RunSetState
from exc_string import exc_string
from xml.dom import minidom, Node


class FlasherDataException(Exception):
    pass


class FlasherDataParser(XMLParser):
    @classmethod
    def __loadFlasherData(cls, dataFile):
        """Parse and return data from flasher file"""
        try:
            dom = minidom.parse(dataFile)
        except Exception:
            raise FlasherDataException("Cannot parse \"%s\": %s" %
                                       (dataFile, exc_string()))

        fmain = dom.getElementsByTagName("flashers")
        if len(fmain) == 0:
            raise FlasherDataException("File \"%s\" has no <flashers>" %
                                       dataFile)
        elif len(fmain) > 1:
            raise FlasherDataException("File \"%s\" has too many <flashers>" %
                                       dataFile)

        nodes = fmain[0].getElementsByTagName("flasher")

        flashList = []
        for n in nodes:
            try:
                flashList.append(cls.__parseFlasherNode(n))
            except FlasherDataException as fe:
                raise FlasherDataException("File \"%s\": %s" % (dataFile, fe))

        return flashList

    @classmethod
    def __parseFlasherNode(cls, node):
        """Parse a single flasher entry"""
        hub = None
        pos = None
        bright = None
        window = None
        delay = None
        mask = None
        rate = None

        for kid in node.childNodes:
            if kid.nodeType == Node.TEXT_NODE:
                continue

            if kid.nodeType == Node.COMMENT_NODE:
                continue

            if kid.nodeType == Node.ELEMENT_NODE:
                if kid.nodeName == "stringHub":
                    hub = int(cls.getChildText(kid))
                elif kid.nodeName == "domPosition":
                    pos = int(cls.getChildText(kid))
                elif kid.nodeName == "brightness":
                    bright = int(cls.getChildText(kid))
                elif kid.nodeName == "window":
                    window = int(cls.getChildText(kid))
                elif kid.nodeName == "delay":
                    delay = int(cls.getChildText(kid))
                elif kid.nodeName == "mask":
                    mask = int(cls.getChildText(kid))
                elif kid.nodeName == "rate":
                    rate = int(cls.getChildText(kid))

        if hub is None or \
           pos is None:
            raise FlasherDataException("Missing stringHub/domPosition" +
                                       " information")
        if bright is None or \
           window is None or \
           delay is None or \
           mask is None or \
           rate is None:
            raise FlasherDataException("Bad entry for %s-%s" % (hub, pos))

        return (hub, pos, bright, window, delay, mask, rate)

    @classmethod
    def load(cls, dataFile):
        return cls.__loadFlasherData(dataFile)


class CnCRun(BaseRun):
    def __init__(self, showCmd=False, showCmdOutput=False, dryRun=False,
                 logfile=None):
        """
        showCmd - True if commands should be printed before being run
        showCmdOutput - True if command output should be printed
        dryRun - True if commands should only be printed and not executed
        logfile - file where all log messages are saved
        """

        super(CnCRun, self).__init__(showCmd=showCmd,
                                     showCmdOutput=showCmdOutput,
                                     dryRun=dryRun, logfile=logfile)

        self.__showCmdOutput = showCmdOutput
        self.__dryRun = dryRun

        # used during dry runs to simulate the runset id
        self.__fakeRunSet = 1

        self.__runNumFile = \
            os.path.join(os.environ["HOME"], ".i3live-run")

        self.__runSetId = None
        self.__runCfg = None
        self.__runNum = None

    def __setLastRunNumber(self, runNum, subRunNum):
        "Set the last used run number"
        with open(self.__runNumFile, 'w') as fd:
            print >>fd, "%d %d" % (runNum, subRunNum)

    def __status(self):
        "Print the current DAQ status"

        if not self.__showCmdOutput or self.__dryRun:
            return

        cmd = "DAQStatus.py"
        self.logCmd(cmd)

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        for line in proc.stdout:
            line = line.rstrip()
            self.logCmdOutput(line)
        proc.stdout.close()

        proc.wait()

    def __waitForState(self, expState, numTries, numErrors=0, waitSecs=10,
                       verbose=False):
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

        if self.__dryRun:
            return True

        self.__status()

        cnc = self.cncConnection()

        prevState = cnc.rpc_runset_state(self.__runSetId)
        curState = prevState

        if verbose and prevState != expState:
            self.logInfo("Changing from %s to %s" % (prevState, expState))

        startTime = time.time()
        for _ in range(numTries):
            if curState == RunSetState.UNKNOWN:
                break

            curState = cnc.rpc_runset_state(self.__runSetId)
            if curState != prevState:
                if verbose:
                    swTime = int(time.time() - startTime)
                    self.logInfo("Changed from %s to %s in %s secs" %
                                 (prevState, curState, swTime))

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
            if not self.__dryRun:
                cnc = self.cncConnection()

            if self.__dryRun:
                print "Break runset#%s" % self.__runSetId
            else:
                cnc.rpc_runset_break(self.__runSetId)
            self.__runSetId = None

    def flash(self, dataPath, secs):
        """
        Start flashers for the specified duration with the specified data file
        """
        if self.__runSetId is None:
            self.logError("No active runset!")
            return True

        if not self.__dryRun:
            cnc = self.cncConnection()

        if dataPath is not None:
            try:
                data = FlasherDataParser.load(dataPath)
            except:
                self.logError("Cannot flash: " + exc_string())
                return True

            runData = self.getLastRunNumber()
            subrun = runData[1] + 1
            self.__setLastRunNumber(runData[0], subrun)

            if self.__dryRun:
                print "Flash subrun#%d - %s for %s second" % \
                    (subrun, data[0], data[1])
            else:
                cnc.rpc_runset_subrun(self.__runSetId, subrun, data)

        # XXX should be monitoring run state during this time
        if not self.__dryRun:
            time.sleep(secs)

        if dataPath is not None:
            subrun += 1
            self.__setLastRunNumber(runData[0], subrun)
            if self.__dryRun:
                print "Flash subrun#%d - turn off flashers" % subrun
            else:
                cnc.rpc_runset_subrun(self.__runSetId, subrun, [])

    def getLastRunNumber(self):
        "Return the last run number"
        num = 1
        subnum = 0

        if os.path.exists(self.__runNumFile):
            with open(self.__runNumFile) as fd:
                line = fd.readline()
                m = re.search('(\d+)\s+(\d+)', line)
                if m:
                    num = int(m.group(1))
                    subnum = int(m.group(2))

        return (num, subnum)

    def getRunNumber(self):
        "Return the current run number"
        if self.__runSetId is None:
            return None
        return self.__runNum

    def isDead(self, refreshState=False):
        cnc = self.cncConnection(False)
        return cnc is None

    def isRecovering(self, refreshState=False):
        return False

    def isRunning(self, refreshState=False):
        cnc = self.cncConnection(False)
        if self.__runSetId is None:
            return False
        try:
            state = cnc.rpc_runset_state(self.__runSetId)
            return state == RunSetState.RUNNING
        except socket.error:
            return False

    def isStopped(self, refreshState=False):
        cnc = self.cncConnection(False)
        if cnc is None or self.__runSetId is None:
            return True
        try:
            state = cnc.rpc_runset_state(self.__runSetId)
            return state == RunSetState.READY
        except socket.error:
            return False

    def isSwitching(self, refreshState=False):
        return False

    def isStopping(self, refreshState=False):
        cnc = self.cncConnection(False)
        if cnc is None or self.__runSetId is None:
            return False
        try:
            state = cnc.rpc_runset_state(self.__runSetId)
            return state == RunSetState.STOPPING
        except socket.error:
            return False

    def setLightMode(self, isLID):
        """
        Set the Light-In-Detector mode

        isLID - True for light-in-detector mode, False for dark mode

        Return True if the light mode was set successfully
        """
        if isLID:
            self.logError("Not setting light mode!!!")
        return True

    def setRunsPerRestart(self, num):
        """Set the number of continuous runs between restarts"""
        pass # for non-Live runs, this is driven by BaseRun.waitForRun()

    def startRun(self, runCfg, duration, numRuns=1, ignoreDB=False,
                 runMode=None, filterMode=None, verbose=False):
        """
        Start a run

        runCfg - run configuration file name
        duration - number of seconds for run
        numRuns - number of runs (default=1)
        ignoreDB - don't check the database for this run config
        runMode - Run mode for 'livecmd'
        filterMode - Run mode for 'livecmd'
        verbose - print more details of run transitions

        Return True if the run was started
        """
        if not self.__dryRun:
            cnc = self.cncConnection()

        if self.__runSetId is not None and self.__runCfg is not None and \
                self.__runCfg != runCfg:
            self.__runCfg = None
            if self.__dryRun:
                print "Break runset #%s" % self.__runSetId
            else:
                cnc.rpc_runset_break(self.__runSetId)
            self.__runSetId = None

        if self.__runSetId is None:
            if self.__dryRun:
                runSetId = self.__fakeRunSet
                self.__fakeRunSet += 1
                print "Make runset #%d" % runSetId
            else:
                runSetId = cnc.rpc_runset_make(runCfg)
            if runSetId < 0:
                raise RunException("Could not create runset for \"%s\"" %
                                   runCfg)

            self.__runSetId = runSetId
            self.__runCfg = runCfg

        self.__runNum = self.getLastRunNumber()[0] + 1
        self.__setLastRunNumber(self.__runNum, 0)

        if runMode is not None:
            if filterMode is not None:
                self.logError("Ignoring run mode %s, filter mode %s" %
                                    (runMode, filterMode))
            else:
                self.logError("Ignoring run mode %s" % runMode)
        elif filterMode is not None:
            self.logError("Ignoring filter mode %s" % filterMode)

        runOptions = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE

        if self.__dryRun:
            print "Start run#%d with runset#%d" % \
                (self.__runNum, self.__runSetId)
        else:
            cnc.rpc_runset_start_run(self.__runSetId, self.__runNum,
                                     runOptions)

        return True

    def state(self):
        cnc = self.cncConnection(False)
        if cnc is None:
            return "DEAD"
        if self.__runSetId is None:
            return "STOPPED"
        try:
            state = cnc.rpc_runset_state(self.__runSetId)
            return str(state).upper()
        except:
            return "ERROR"

    def stopRun(self):
        """Stop the run"""
        if self.__runSetId is None:
            raise RunException("No active run")

        if not self.__dryRun:
            cnc = self.cncConnection()

        if self.__dryRun:
            print "Stop runset#%s" % self.__runSetId
        else:
            cnc.rpc_runset_stop_run(self.__runSetId)

    def switchRun(self, runNum):
        """Switch to a new run number without stopping any components"""
        if self.__runSetId is None:
            raise RunException("No active run")

        if not self.__dryRun:
            cnc = self.cncConnection()

        if self.__dryRun:
            print "Switch runset#%s to run#%d" % (self.__runSetId, runNum)
        else:
            cnc.rpc_runset_switch_run(self.__runSetId, runNum)
        self.__runNum = runNum

        return True

    def waitForStopped(self, verbose=False):
        """Wait for the current run to be stopped"""
        cnc = self.cncConnection()

        try:
            state = cnc.rpc_runset_state(self.__runSetId)
        except:
            state = RunSetState.ERROR

        if state == RunSetState.UNKNOWN:
            self.__runSetId = None
            return True

        return self.__waitForState(RunSetState.READY, 10, verbose=verbose)

if __name__ == "__main__":
    run = CnCRun(showCmd=True, showCmdOutput=True, dryRun=False)
    run.run("spts64-dirtydozen-hlc-006", "spts64-dirtydozen-hlc-006", 30,
            (("flash-21.xml", 5), (None, 10), ("flash-21.xml", 5)),
            verbose=True)
