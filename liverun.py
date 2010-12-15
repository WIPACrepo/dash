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


import os, re, subprocess, sys, time
from BaseRun import BaseRun, RunException, StateException
from DAQConst import DAQPort

class LightModeException(RunException): pass

class AbstractState(object):
    "Generic class for keeping track of the current state"

    def get(cls, stateName):
        """
        Return the numeric value of the named state

        stateName - named state
        """
        try:
            return cls.STATES.index(stateName)
        except ValueError:
            raise StateException("Unknown state '%s'" % stateName)
    get = classmethod(get)

    def str(cls, state):
        """
        Return the string associated with a numeric state

        state - numeric state value
        """
        if state < 0 or state > len(cls.STATES):
            raise StateException("Unknown state #%s" % state)
        return cls.STATES[state]
    str = classmethod(str)

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

    def numStarts(self): return self.__numStarts
    def state(self): return self.__state

class LiveState(object):
    "Track the current I3Live service states"

    RUN_PAT = re.compile(r"Current run: (\d+)\s+subrun: (\d+)")
    DOM_PAT = re.compile(r"\s+(\d+)-(\d+): \d+ \d+ \d+ \d+ \d+")
    SVC_PAT = re.compile(r"(\S+)( .*)? \((\S+):(\d+)\), (async|sync)hronous" +
                         " - (.*)")
    SVCBACK_PAT = re.compile(r"(\S+) \(started (\d+) times\)")

    PARSE_NORMAL = 1
    PARSE_FLASH = 2

    def __init__(self, liveCmd=os.path.join(os.environ["HOME"], "bin",
                                            "livecmd"), showCmd=False,
                 showCmdOutput=False):
        """
        Create an I3Live service tracker

        liveCmd - full path of 'livecmd' executable
        showCmd - True if commands should be printed before being run
        showCmdOutput - True if command output should be printed
        """
        self.__prog = liveCmd
        self.__showCmd = showCmd
        self.__showCmdOutput = showCmdOutput

        self.__threadState = None
        self.__runState = LiveRunState.get(LiveRunState.UNKNOWN)
        self.__lightMode = LightMode.UNKNOWN

        self.__runNum = None
        self.__subrunNum = None

        self.__svcDict = {}

    def __str__(self):
        "Return a description of the current I3Live state"
        sum = "Live[%s] Run[%s] Light[%s]" % \
            (self.__threadState, LiveRunState.str(self.__runState),
             LightMode.str(self.__lightMode))

        for key in self.__svcDict.keys():
            svc = self.__svcDict[key]
            sum += " %s[%s*%d]" % (key, LiveRunState.str(svc.state()),
                                   svc.numStarts())

        if self.__runNum is not None:
            if self.__subrunNum is not None and self.__subrunNum > 0:
                sum += " run %d/%d" % (self.__runNum, self.__subrunNum)
            else:
                sum += " run %d" % self.__runNum

        return sum

    def __parseLine(self, parseState, line):
        """
        Parse a live of output from 'livecmd check'

        parseState - current parser state
        line - line to parse

        Returns the new parser state
        """
        if len(line) == 0 or line.find("controlled by LiveControl") > 0 or \
                line == "(None)":
            return LiveState.PARSE_NORMAL

        if line.startswith("Flashing DOMs"):
            return LiveState.PARSE_FLASH

        if line.find(": ") > 0:
            (front, back) = line.split(": ", 1)
            front = front.strip()
            back = back.strip()

            if front == "DAQ thread":
                self.__threadState = back
                return LiveState.PARSE_NORMAL
            elif front == "Run state":
                self.__runState = LiveRunState.get(back)
                return LiveState.PARSE_NORMAL
            elif front == "Current run":
                m = LiveState.RUN_PAT.match(line)
                if m:
                    self.__runNum = int(m.group(1))
                    self.__subrunNum = int(m.group(2))
                    return LiveState.PARSE_NORMAL
            elif front == "Light mode":
                self.__lightMode = LightMode.get(back)
                return LiveState.PARSE_NORMAL
            elif front == "run":
                self.__runNum = int(back)
                return LiveState.PARSE_NORMAL
            elif front == "subrun":
                self.__subrunNum = int(back)
                return LiveState.PARSE_NORMAL
            elif front == "config":
                self.__config = back
                return LiveState.PARSE_NORMAL
            elif front == "tstart" or front == "tstop":
                # ignore start/stop times
                return LiveState.PARSE_NORMAL
            elif front == "physicsEvents" or \
                    front == "physicsEventsTime" or \
                    front == "walltimeEvents" or \
                    front =="walltimeEventsTime"  or \
                    front == "tcalEvents" or \
                    front == "moniEvents" or \
                    front == "snEvents" or \
                    front == "runlength":
                # ignore rates
                return LiveState.PARSE_NORMAL
            elif front == "daqrelease":
                # ignore DAQ release name
                return LiveState.PARSE_NORMAL
            else:
                print >>sys.stderr, "Unknown livecmd pair: \"%s\"/\"%s\"" % \
                      (front, back)
                return LiveState.PARSE_NORMAL

        if parseState == LiveState.PARSE_FLASH:
            m = LiveState.DOM_PAT.match(line)
            if m:
                # toss flashing DOM line
                return LiveState.PARSE_FLASH

        m = LiveState.SVC_PAT.match(line)
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
                m = LiveState.SVCBACK_PAT.match(back)
                if m:
                    state = m.group(1)
                    numStarts = int(m.group(2))

            svc = LiveService(name, host, port, isAsync, state, numStarts)
            self.__svcDict[name] = svc
            return LiveState.PARSE_NORMAL

        print >>sys.stderr, "Unknown livecmd line: %s" % line
        return LiveState.PARSE_NORMAL

    def check(self):
        "Check the current I3Live service states"

        cmd = "%s check" % self.__prog
        if self.__showCmd: print cmd
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        parseState = LiveState.PARSE_NORMAL
        for line in proc.stdout:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line
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
        if not self.__svcDict.has_key(svcName):
            return LiveRunState.UNKNOWN
        return LiveRunState.str(self.__svcDict[svcName].state())

class LiveRun(BaseRun):
    "Manage one or more pDAQ runs through IceCube Live"

    def __init__(self, showCmd=False, showCmdOutput=False,
                 showCheck=False, showCheckOutput=False, dbType=None):
        """
        showCmd - True if commands should be printed before being run
        showCmdOutput - True if command output should be printed
        showCheck - True if 'livecmd check' commands should be printed
        showCheckOutput - True if 'livecmd check' output should be printed
        dbType - DatabaseType value (TEST, PROD, or NONE)
        """
        self.__showCmd = showCmd
        self.__showCmdOutput = showCmdOutput

        # check for needed executables
        #
        self.__liveCmdProg = self.findExecutable("I3Live program", "livecmd")

        # build state-checker
        #
        self.__state = LiveState(self.__liveCmdProg, showCheck, showCheckOutput)

        super(LiveRun, self).__init__(showCmd, showCmdOutput, dbType)

    def __controlPDAQ(self, waitSecs, attempts=3):
        """
        Connect I3Live to pDAQ

        Return True if I3Live controls pDAQ
        """

        cmd = "%s control pdaq localhost:%s" % \
            (self.__liveCmdProg, DAQPort.DAQLIVE)
        if self.__showCmd: print cmd
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        controlled = False
        unreachable = True
        for line in proc.stdout:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line
            if line == "Service pdaq is now being controlled" or \
                    line.find("Synchronous service pdaq was already being" +
                              " controlled") >= 0:
                controlled = True
            elif line.find("Service pdaq was unreachable on ") >= 0:
                unreachable = True
            else:
                print >>sys.stderr, "Control: %s" % line
        proc.stdout.close()

        proc.wait()

        if controlled or waitSecs < 0:
            return controlled

        if attempts <= 0:
            return False

        time.sleep(waitSecs)
        return self.__controlPDAQ(0, attempts=attempts-1)

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
        if self.__showCmd: print cmd
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        problem = False
        for line in proc.stdout:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line

            if line != "OK":
                problem = True
            if problem:
                print >>sys.stderr, "%s: %s" % (name, line)
        proc.stdout.close()

        proc.wait()

        return not problem

    def __waitForRun(self, runNum, duration):
        """
        Wait for the current run to start and stop

        runNum - current run number
        duration - expected number of seconds this run will last
        """
        waitSecs = 10
        numTries = duration / waitSecs

        expState = LiveRunState.RUNNING
        numWaits = 0

        daqStopped = False

        while True:
            self.__state.check()
            if self.__state.runState() == expState:
                if expState == LiveRunState.STOPPED:
                    break
            else:
                if expState == LiveRunState.RUNNING:
                    runTime = numWaits * waitSecs
                    if runTime < duration:
                        print >>sys.stderr, \
                            ("WARNING: Expected %d second run, but run %d" +
                             " ended after about %d seconds") % \
                             (duration, runNum, runTime)

                    if self.__state.runState() == LiveRunState.STOPPED or \
                            self.__state.runState() == LiveRunState.STOPPING or \
                            self.__state.runState() == LiveRunState.RECOVERING:
                        break

                    print >>sys.stderr, "Unexpected run %d state %s" % \
                        (runNum, self.__state.runState())

                elif expState != LiveRunState.STOPPED:
                    print >>sys.stderr, "Ignoring expected run %d state %s" % \
                        (runNum, expState)

            if not daqStopped and \
                    self.__state.svcState("pdaq") == LiveRunState.STOPPED:
                print >>sys.stderr, "pDAQ is STOPPED"
                daqStopped = True

            numWaits += 1
            if numWaits > numTries:
                break

            time.sleep(waitSecs)

    def __waitForState(self, curState, expState, numTries, numErrors=0,
                       waitSecs=10):
        """
        Wait for the specified state

        curState - current detector state
        expState - expected final state
        numTries - number of tries before ceasing to wait
        numErrors - number of ERROR states allowed before assuming
                    there is a problem
        waitSecs - number of seconds to wait on each "try"
        """
        prevState = self.__state.runState()

        if prevState != expState:
            print "Switching from %s to %s" % (prevState, expState)

        startTime = time.time()
        for i in range(numTries):
            self.__state.check()

            if self.__state.runState() != prevState:
                swTime = int(time.time() - startTime)
                print "  Switched from %s to %s in %s secs" % \
                    (prevState, self.__state.runState(), swTime)

                prevState = self.__state.runState()
                startTime = time.time()

            if self.__state.runState() == expState:
                break

            if numErrors > 0 and self.__state.runState() == LiveRunState.ERROR:
                time.sleep(5)
                numErrors -= 1
                continue

            if self.__state.runState() != curState and \
                    self.__state.runState() != LiveRunState.RECOVERING:
                raise StateException(("I3Live state should be %s or" +
                                      " RECOVERING, not %s") %
                                     (curState, self.__state.runState()))

            time.sleep(waitSecs)

        if self.__state.runState() != expState:
            totTime = int(time.time() - startTime)
            raise StateException(("I3Live state should be %s, not %s" +
                                  " (waited %d secs)") %
                                 (expState, self.__state.runState(), totTime))

        return True

    def cleanUp(self):
        """Do final cleanup before exiting"""
        pass

    def flash(self, tm, data):
        """Start flashers for the specified duration with the specified data"""
        cmd = "%s flasher -d %d -f %s" % (self.__liveCmdProg, tm, data)
        if self.__showCmd: print cmd
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        problem = False
        for line in proc.stdout:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line

            if line != "OK" and not line.startswith("Starting subrun"):
                problem = True
            if problem:
                print >>sys.stderr, "Flasher: %s" % line
        proc.stdout.close()

        proc.wait()

        return problem

    def getLastRunNumber(self):
        "Return the last run number"
        cmd = "%s lastrun" % self.__liveCmdProg
        if self.__showCmd: print cmd
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        num = None
        for line in proc.stdout:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line
            num = int(line)
        proc.stdout.close()

        proc.wait()

        return num

    def getRunNumber(self):
        "Return the current run number"
        self.__state.check()
        return self.__state.runNumber()

    def isDead(self, refreshState=False):
        if refreshState: self.__refreshState()
        return self.__state.runState() == LiveRunState.DEAD

    def isRecovering(self, refreshState=False):
        if refreshState: self.__refreshState()
        return self.__state.runState() == LiveRunState.RECOVERING

    def isRunning(self, refreshState=False):
        if refreshState: self.__refreshState()
        return self.__state.runState() == LiveRunState.RUNNING

    def isStopped(self, refreshState=False):
        if refreshState: self.__refreshState()
        return self.__state.runState() == LiveRunState.STOPPED

    def isStopping(self, refreshState=False):
        if refreshState: self.__refreshState()
        return self.__state.runState() == LiveRunState.STOPPING

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
        if self.__state.lightMode() == expMode:
            return True

        if self.__state.lightMode() == LightMode.LID or \
                self.__state.lightMode() == LightMode.DARK:
            # mode isn't in transition, so start transitioning
            #
            cmd = "%s lightmode %s" % (self.__liveCmdProg, expMode)
            if not self.__runBasicCommand("LightMode", cmd):
                return False

        waitSecs = 10
        numTries = 10

        for i in range(numTries):
            self.__state.check()
            if self.__state.lightMode() == expMode:
                break

            if not self.__state.lightMode().startswith("changingTo"):
                raise LightModeException("I3Live lightMode should not be %s" %
                                         self.__state.lightMode())

            time.sleep(waitSecs)

        if self.__state.lightMode() != expMode:
            raise LightModeException("I3Live state should be %s, not %s" %
                                     (expMode, self.__state.lightMode()))

        return True

    def startRun(self, runCfg, duration, numRuns=1, ignoreDB=False):
        """
        Tell I3Live to start a run

        runCfg - run configuration file name
        duration - number of seconds for run
        numRuns - number of runs (default=1)
        ignoreDB - tell I3Live to not check the database for this run config

        Return True if the run was started
        """
        if not self.isStopped(True):
            return False

        if ignoreDB or self.ignoreDatabase():
            iArg = "-i"
        else:
            iArg = ""
        cmd = "%s start -d %s -n %d -l %d %s daq" % \
            (self.__liveCmdProg, runCfg, numRuns, duration, iArg)
        if not self.__runBasicCommand("StartRun", cmd):
            return False

        if not self.__waitForState(LiveRunState.STOPPED, LiveRunState.STARTING,
                                   10, 6):
            raise RunException("Run %d did not start" % runNum)
        return self.__waitForState(LiveRunState.STARTING, LiveRunState.RUNNING,
                                   18, 0)

    def stopRun(self):
        """Stop the run"""
        pass

    def waitForStopped(self):
        return self.__waitForState(LiveRunState.STOPPING, LiveRunState.STOPPED,
                                   60, 0)

if __name__ == "__main__":
    run = LiveRun(True, True)
    run.run("spts64-real-21-29", "spts64-dirtydozen-hlc-006", 60,
            "flash-21.xml", (10, 10), 10)
