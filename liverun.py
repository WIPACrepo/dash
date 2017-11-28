#!/usr/bin/env python
#
# Manage pDAQ runs via IceCube Live
#
# Examples:
#
#     # create a LiveRun object
#     run = LiveRun()
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
import subprocess
import time

from BaseRun import BaseRun, RunException, StateException
from DAQConst import DAQPort


class LightModeException(RunException):
    pass


class LiveTimeoutException(RunException):
    pass


class AbstractState(object):
    "Generic class for keeping track of the current state"

    @classmethod
    def get(cls, stateName):
        """
        Return the numeric value of the named state

        stateName - named state
        """
        try:
            return cls.STATES.index(stateName)
        except ValueError:
            raise StateException("Unknown state '%s'" % stateName)

    @classmethod
    def str(cls, state):
        """
        Return the string associated with a numeric state

        state - numeric state value
        """
        if state < 0 or state > len(cls.STATES):
            raise StateException("Unknown state #%s" % state)
        return cls.STATES[state]


class LiveRunState(AbstractState):
    "I3Live states"

    DEAD = "DEAD"
    ERROR = "ERROR"
    NEW_SUBRUN = "NEW-SUBRUN"
    RECOVERING = "RECOVERING"
    RUN_CHANGE = "RUN-CHANGE"
    RUNNING = "RUNNING"
    STARTING = "STARTING"
    STOPPED = "STOPPED"
    STOPPING = "STOPPING"
    SWITCHRUN = "SWITCHRUN"
    UNKNOWN = "???"

    STATES = [
        DEAD,
        ERROR,
        NEW_SUBRUN,
        RECOVERING,
        RUN_CHANGE,
        RUNNING,
        STARTING,
        STOPPED,
        STOPPING,
        SWITCHRUN,
        UNKNOWN,
        ]


class LightMode(AbstractState):
    "I3Live light-in-detector modes"

    CHG2DARK = "changingToDark"
    CHG2LIGHT = "changingToLID"
    DARK = "dark"
    LID = "LID"
    UNKNOWN = "???"

    STATES = [
        CHG2DARK,
        CHG2LIGHT,
        DARK,
        LID,
        UNKNOWN,
        ]


class LiveService(object):
    "I3Live service instance"

    def __init__(self, name, host, port, isAsync, state, numStarts):
        """
        I3Live service data (as extracted from 'livecmd check')

        name - service name
        host - name of machine on which the service is running
        port - socket port address for this service
        isAsync - True if this is an asynchronous service
        state - current service state string
        numStarts - number of times this service has been started
        """
        self.__name = name
        self.__host = host
        self.__port = port
        self.__isAsync = isAsync
        self.__state = LiveRunState.get(state)
        self.__numStarts = numStarts

    def numStarts(self):
        return self.__numStarts

    @property
    def state(self):
        return self.__state


class LiveState(object):
    "Track the current I3Live service states"

    RUN_PAT = re.compile(r"Current run: (\d+)\s+subrun: (\d+)")
    DOM_PAT = re.compile(r"\s+(\d+)-(\d+): \d+ \d+ \d+ \d+ \d+")
    SVC_PAT = re.compile(r"(\S+)( .*)? \((\S+):(\d+)\), (async|sync)hronous" +
                         " - (.*)")
    SVCBACK_PAT = re.compile(r"(\S+) \(started (\d+) times\)")

    PARSE_NORMAL = 1
    PARSE_FLASH = 2
    PARSE_ALERTS = 3

    def __init__(self,
                 liveCmd=os.path.join(os.environ["HOME"], "bin", "livecmd"),
                 showCheck=False, showCheckOutput=False, logger=None,
                 dryRun=False):
        """
        Create an I3Live service tracker

        liveCmd - full path of 'livecmd' executable
        showCheck - True if 'livecmd check' commands should be printed
        showCheckOutput - True if 'livecmd check' output should be printed
        logger - specialized run logger
        dryRun - True if commands should only be printed and not executed
        """
        self.__prog = liveCmd
        self.__showCheck = showCheck
        self.__showCheckOutput = showCheckOutput
        self.__logger = logger
        self.__dryRun = dryRun

        self.__threadState = None
        self.__runState = LiveRunState.get(LiveRunState.UNKNOWN)
        self.__lightMode = LightMode.UNKNOWN

        self.__runNum = None
        self.__subrunNum = None
        self.__config = None

        self.__svcDict = {}

        # only complain about unknown pairs once
        self.__complained = {}

    def __str__(self):
        "Return a description of the current I3Live state"
        summary = "Live[%s] Run[%s] Light[%s]" % \
                  (self.__threadState, LiveRunState.str(self.__runState),
                   LightMode.str(self.__lightMode))

        for key in self.__svcDict.keys():
            svc = self.__svcDict[key]
            summary += " %s[%s*%d]" % (key, LiveRunState.str(svc.state),
                                       svc.numStarts())

        if self.__runNum is not None:
            if self.__subrunNum is not None and self.__subrunNum > 0:
                summary += " run %d/%d" % (self.__runNum, self.__subrunNum)
            else:
                summary += " run %d" % self.__runNum

        return summary

    def __parseLine(self, parseState, line):
        """
        Parse a live of output from 'livecmd check'

        parseState - current parser state
        line - line to parse

        Returns the new parser state
        """
        if len(line) == 0 or line.find("controlled by LiveControl") > 0 or \
                line == "(None)" or line == "OK":
            return self.PARSE_NORMAL

        if line.startswith("Flashing DOMs"):
            return self.PARSE_FLASH

        if parseState == self.PARSE_FLASH:
            m = self.DOM_PAT.match(line)
            if m:
                return self.PARSE_FLASH

        if line.startswith("Ongoing Alerts:"):
            return self.PARSE_ALERTS

        if parseState == self.PARSE_ALERTS:
            if line.find("(None)") >= 0:
                return self.PARSE_NORMAL

            self.__logger.error("Ongoing Alert: " + line.rstrip())
            return self.PARSE_ALERTS

        if line.find(": ") > 0:
            (front, back) = line.split(": ", 1)
            front = front.strip()
            back = back.strip()

            if front == "DAQ thread":
                self.__threadState = back
                return self.PARSE_NORMAL
            elif front == "Run state":
                self.__runState = LiveRunState.get(back)
                return self.PARSE_NORMAL
            elif front == "Current run":
                m = self.RUN_PAT.match(line)
                if m:
                    self.__runNum = int(m.group(1))
                    self.__subrunNum = int(m.group(2))
                    return self.PARSE_NORMAL
            elif front == "Light mode":
                self.__lightMode = LightMode.get(back)
                return self.PARSE_NORMAL
            elif front == "run":
                self.__runNum = int(back)
                return self.PARSE_NORMAL
            elif front == "subrun":
                self.__subrunNum = int(back)
                return self.PARSE_NORMAL
            elif front == "config":
                self.__config = back
                return self.PARSE_NORMAL
            elif front.startswith("tstart") or front.startswith("tstop") or \
                front.startswith("t_valid") or front == "livestart":
                # ignore start/stop times
                return self.PARSE_NORMAL
            elif front == "physicsEvents" or \
                    front == "physicsEventsTime" or \
                    front == "walltimeEvents" or \
                    front == "walltimeEventsTime"  or \
                    front == "tcalEvents" or \
                    front == "moniEvents" or \
                    front == "snEvents" or \
                    front == "runlength":
                # ignore rates
                return self.PARSE_NORMAL
            elif front == "Target run stop time" or \
                 front == "Currently" or \
                 front == "Time since start" or \
                 front == "Time until stop":
                # ignore run time info
                return self.PARSE_NORMAL
            elif front == "daqrelease":
                # ignore DAQ release name
                return self.PARSE_NORMAL
            elif front == "Run starts":
                # ignore run start/switch info
                return self.PARSE_NORMAL
            elif front == "Flashing state":
                # ignore flashing state
                return self.PARSE_NORMAL
            elif front == "check failed" and back.find("timed out") >= 0:
                self.__logger.error("I3Live may have died" +
                                    " (livecmd check returned '%s')" %
                                    line.rstrip())
                return self.PARSE_NORMAL
            elif front == "Run mode" or front == "Filter mode":
                # ignore run/filter mode info
                return self.PARSE_NORMAL
            elif front not in self.__complained:
                self.__logger.error("Unknown livecmd pair: \"%s\"/\"%s\"" %
                                    (front, back))
                self.__complained[front] = 1
                return self.PARSE_NORMAL

        m = self.SVC_PAT.match(line)
        if m:
            name = m.group(1)
            host = m.group(2)
            port = int(m.group(4))
            isAsync = m.group(5) == "async"
            back = m.group(6)

            state = LiveRunState.UNKNOWN
            numStarts = 0

            if back == "DIED!":
                state = LiveRunState.DEAD
            else:
                m = self.SVCBACK_PAT.match(back)
                if m:
                    state = m.group(1)
                    numStarts = int(m.group(2))

            svc = LiveService(name, host, port, isAsync, state, numStarts)
            self.__svcDict[name] = svc
            return self.PARSE_NORMAL

        self.__logger.error("Unknown livecmd line: %s" % line)
        return self.PARSE_NORMAL

    def logCmd(self, msg):
        if self.__showCheck:
            self.__logger.info("% " + msg)

    def logCmdOutput(self, msg):
        if self.__showCheckOutput:
            self.__logger.info("%%% " + msg)

    def check(self):
        "Check the current I3Live service states"

        cmd = "%s check" % self.__prog
        if self.__showCheck:
            self.logCmd(cmd)

        if self.__dryRun:
            print cmd
            return

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        parseState = self.PARSE_NORMAL
        for line in proc.stdout:
            line = line.rstrip()
            if self.__showCheckOutput:
                self.logCmdOutput(line)

            parseState = self.__parseLine(parseState, line)
        proc.stdout.close()

        proc.wait()

    def lightMode(self):
        "Return the light mode from the most recent check()"
        return LightMode.str(self.__lightMode)

    def runNumber(self):
        "Return the pDAQ run number from the most recent check()"
        if self.__runNum is None:
            return 0
        return self.__runNum

    def runState(self):
        "Return the pDAQ run state from the most recent check()"
        return LiveRunState.str(self.__runState)

    def svcState(self, svcName):
        """
        Return the state string for the specified service
        from the most recent check()
        """
        if not svcName in self.__svcDict:
            return LiveRunState.UNKNOWN
        return LiveRunState.str(self.__svcDict[svcName].state)


class LiveRun(BaseRun):
    "Manage one or more pDAQ runs through IceCube Live"

    def __init__(self, showCmd=False, showCmdOutput=False, showCheck=False,
                 showCheckOutput=False, dryRun=False, logfile=None):
        """
        showCmd - True if commands should be printed before being run
        showCmdOutput - True if command output should be printed
        showCheck - True if 'livecmd check' commands should be printed
        showCheckOutput - True if 'livecmd check' output should be printed
        dryRun - True if commands should only be printed and not executed
        logfile - file where all log messages are saved
        """

        super(LiveRun, self).__init__(showCmd=showCmd,
                                      showCmdOutput=showCmdOutput,
                                      dryRun=dryRun, logfile=logfile)

        self.__dryRun = dryRun

        # used during dry runs to simulate the run number
        self.__fakeRunNum = 12345

        # check for needed executables
        #
        self.__liveCmdProg = self.findExecutable("I3Live program", "livecmd",
                                                 self.__dryRun)

        # build state-checker
        #
        self.__state = LiveState(self.__liveCmdProg, showCheck=showCheck,
                                 showCheckOutput=showCheckOutput,
                                 logger=self.logger(), dryRun=self.__dryRun)

    def __controlPDAQ(self, waitSecs, attempts=3):
        """
        Connect I3Live to pDAQ

        Return True if I3Live controls pDAQ
        """

        cmd = "%s control pdaq localhost:%s" % \
            (self.__liveCmdProg, DAQPort.DAQLIVE)
        self.logCmd(cmd)

        if self.__dryRun:
            print cmd
            return True

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        controlled = False
        for line in proc.stdout:
            line = line.rstrip()
            self.logCmdOutput(line)

            if line == "Service pdaq is now being controlled" or \
                    line.find("Synchronous service pdaq was already being" +
                              " controlled") >= 0:
                controlled = True
            elif line.find("Service pdaq was unreachable on ") >= 0:
                pass
            else:
                self.logError("Control: %s" % line)
        proc.stdout.close()

        proc.wait()

        if controlled or waitSecs < 0:
            return controlled

        if attempts <= 0:
            return False

        time.sleep(waitSecs)
        return self.__controlPDAQ(0, attempts=attempts - 1)

    def __refreshState(self):
        self.__state.check()
        if self.__state.svcState("pdaq") == LiveRunState.UNKNOWN:
            if not self.__controlPDAQ(10):
                raise StateException("Could not tell I3Live to control pdaq")
            self.__state.check()

    def __runBasicCommand(self, name, cmd):
        """
        Run a basic I3Live command

        name - description of this command (used in error messages)
        path - I3Live command which responds with "OK" or an error

        Return True if there was a problem
        """
        self.logCmd(cmd)

        if self.__dryRun:
            print cmd
            return True

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        problem = False
        for line in proc.stdout:
            line = line.rstrip()
            self.logCmdOutput(line)

            if line != "OK":
                problem = True
            if problem:
                self.logError("%s: %s" % (name, line))
        proc.stdout.close()

        proc.wait()

        return not problem

    def __waitForState(self, initStates, expState, numTries, numErrors=0,
                       waitSecs=10, verbose=False):
        """
        Wait for the specified state

        initStates - list of possible initial detector states
        expState - expected final state
        numTries - number of tries before ceasing to wait
        numErrors - number of ERROR states allowed before assuming
                    there is a problem
        waitSecs - number of seconds to wait on each "try"
        """
        prevState = self.state
        curState = prevState

        if verbose and prevState != expState:
            self.logInfo("Changing from %s to %s" % (prevState, expState))

        startTime = time.time()
        for _ in range(numTries):
            self.__state.check()

            curState = self.state
            if curState != prevState:
                if verbose:
                    swTime = int(time.time() - startTime)
                    self.logInfo("Changed from %s to %s in %s secs" %
                                 (prevState, curState, swTime))

                prevState = curState
                startTime = time.time()

            if curState == expState:
                break

            if numErrors > 0 and curState == LiveRunState.ERROR:
                time.sleep(5)
                numErrors -= 1
                continue

            if curState not in initStates and \
               curState != LiveRunState.RECOVERING:
                raise StateException(("I3Live state should be %s or" +
                                      " RECOVERING, not %s") %
                                     (", ".join(initStates), curState))

            time.sleep(waitSecs)

        if curState != expState:
            totTime = int(time.time() - startTime)
            raise StateException(("I3Live state should be %s, not %s" +
                                  " (waited %d secs)") %
                                 (expState, curState, totTime))

        return True

    def cleanUp(self):
        """Do final cleanup before exiting"""
        pass

    def flash(self, dataPath, secs):
        """
        Start flashers for the specified duration with the specified data file
        """
        problem = False
        if dataPath is None or dataPath == "sleep":
            if self.__dryRun:
                print "sleep %d" % secs
            else:
                time.sleep(secs)
        else:
            cmd = "%s flasher -d %ds -f %s" % (self.__liveCmdProg,
                                               secs, dataPath)
            self.logCmd(cmd)

            if self.__dryRun:
                print cmd
                return False

            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, close_fds=True,
                                    shell=True)
            proc.stdin.close()

            for line in proc.stdout:
                line = line.rstrip()
                self.logCmdOutput(line)

                if line != "OK" and not line.startswith("Starting subrun"):
                    problem = True
                if problem:
                    self.logError("Flasher: %s" % line)
            proc.stdout.close()

            proc.wait()

        return problem

    def getLastRunNumber(self):
        "Return the last used run and subrun numbers as a tuple"
        cmd = "%s lastrun" % self.__liveCmdProg
        self.logCmd(cmd)

        if self.__dryRun:
            print cmd
            runNum = self.__fakeRunNum
            self.__fakeRunNum += 1
            return (runNum, 0)

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        num = None
        for line in proc.stdout:
            line = line.rstrip()
            self.logCmdOutput(line)

            try:
                num = int(line)
            except ValueError:
                if line.find("timed out") >= 0:
                    raise LiveTimeoutException("I3Live seems to have died")

        proc.stdout.close()

        proc.wait()

        return (num, 0)

    def getRunNumber(self):
        "Return the current run number"
        if self.__dryRun:
            return self.__fakeRunNum

        self.__refreshState()
        return self.__state.runNumber()

    def getRunsPerRestart(self):
        """Get the number of continuous runs between restarts"""
        cmd = "livecmd runs per restart"
        self.logCmd(cmd)

        if self.__dryRun:
            print cmd
            return 1

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        curNum = None
        for line in proc.stdout:
            line = line.rstrip()
            self.logCmdOutput(line)
            try:
                curNum = int(line)
            except ValueError:
                raise SystemExit("Bad number '%s' for runs per restart" % line)

        proc.stdout.close()
        proc.wait()

        return curNum

    def isDead(self, refreshState=False):
        if refreshState:
            self.__refreshState()

        return self.__state.runState() == LiveRunState.DEAD

    def isRecovering(self, refreshState=False):
        if refreshState:
            self.__refreshState()

        return self.__state.runState() == LiveRunState.RECOVERING

    def isRunning(self, refreshState=False):
        if refreshState:
            self.__refreshState()

        return self.__state.runState() == LiveRunState.RUNNING

    def isStopped(self, refreshState=False):
        if refreshState:
            self.__refreshState()

        return self.__state.runState() == LiveRunState.STOPPED

    def isStopping(self, refreshState=False):
        if refreshState:
            self.__refreshState()

        return self.__state.runState() == LiveRunState.STOPPING

    def isSwitching(self, refreshState=False):
        if refreshState:
            self.__refreshState()

        return self.__state.runState() == LiveRunState.SWITCHRUN

    def setLightMode(self, isLID):
        """
        Set the I3Live LID mode

        isLID - True for LID mode, False for dark mode

        Return True if the light mode was set successfully
        """
        if isLID:
            expMode = LightMode.LID
        else:
            expMode = LightMode.DARK

        self.__state.check()
        if not self.__dryRun and self.__state.lightMode() == expMode:
            return True

        if self.__dryRun or self.__state.lightMode() == LightMode.LID or \
                self.__state.lightMode() == LightMode.DARK:
            # mode isn't in transition, so start transitioning
            #
            cmd = "%s lightmode %s" % (self.__liveCmdProg, expMode)
            if not self.__runBasicCommand("LightMode", cmd):
                return False

        waitSecs = 10
        numTries = 10

        for _ in range(numTries):
            self.__state.check()
            if self.__dryRun or self.__state.lightMode() == expMode:
                break

            if not self.__state.lightMode().startswith("changingTo"):
                raise LightModeException("I3Live lightMode should not be %s" %
                                         self.__state.lightMode())

            time.sleep(waitSecs)

        if not self.__dryRun and self.__state.lightMode() != expMode:
            raise LightModeException("I3Live lightMode should be %s, not %s" %
                                     (expMode, self.__state.lightMode()))

        return True

    def setRunsPerRestart(self, numRestarts):
        """Set the number of continuous runs between restarts"""
        curNum = self.getRunsPerRestart()
        if curNum == numRestarts:
            return

        cmd = "livecmd runs per restart %d" % numRestarts
        self.logCmd(cmd)

        if self.__dryRun:
            print cmd
            return

        print "Setting runs per restart to %d" % numRestarts
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

    def startRun(self, runCfg, duration, numRuns=1, ignoreDB=False,
                 runMode=None, filterMode=None, verbose=False):
        """
        Tell I3Live to start a run

        runCfg - run configuration file name
        duration - number of seconds for run
        numRuns - number of runs (default=1)
        ignoreDB - tell I3Live to not check the database for this run config
        runMode - Run mode for 'livecmd'
        filterMode - Run mode for 'livecmd'
        verbose - print more details of run transitions

        Return True if the run was started
        """
        if not self.__dryRun and not self.isStopped(True):
            return False

        args = ""
        if ignoreDB or self.ignoreDatabase():
            args += " -i"
        if runMode is not None:
            args += " -r %s" % runMode
        if filterMode is not None:
            args += " -p %s" % filterMode

        cmd = "%s start -c %s -n %d -l %ds %s daq" % \
            (self.__liveCmdProg, runCfg, numRuns, duration, args)
        if not self.__runBasicCommand("StartRun", cmd):
            return False

        if self.__dryRun:
            return True

        if self.__state.runState() == LiveRunState.RUNNING:
            return True

        initStates = (LiveRunState.STOPPED, LiveRunState.STARTING)
        return self.__waitForState(initStates, LiveRunState.RUNNING, 60, 0,
                                   verbose=True)

    @property
    def state(self):
        return self.__state.runState()

    def stopRun(self):
        """Stop the run"""
        cmd = "%s stop daq" % self.__liveCmdProg
        if not self.__runBasicCommand("StopRun", cmd):
            return False

    def switchRun(self, runNum):
        """Switch to a new run number without stopping any components"""
        return True # Live handles this automatically

    def waitForStopped(self, verbose=False):
        initStates = (self.__state.runState(), LiveRunState.STOPPING)
        return self.__waitForState(initStates, LiveRunState.STOPPED,
                                   60, 0, verbose=verbose)

if __name__ == "__main__":
    run = LiveRun(showCmd=True, showCmdOutput=True, dryRun=False)
    run.run("spts64-real-21-29", "spts64-dirtydozen-hlc-006", 60,
            (("flash-21.xml", 10), (None, 10), ("flash-21.xml", 5)),
            verbose=True)
