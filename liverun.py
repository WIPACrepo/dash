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


import optparse, os, re, socket, stat, sys, threading, time
from DAQConst import DAQPort

class FlashFileException(Exception): pass
class LaunchException(Exception): pass
class LightModeException(Exception): pass
class RunException(Exception): pass
class StateException(Exception): pass

class DatabaseType(object):
    """I3DB types"""

    TEST = "test"
    PROD = "production"
    NONE = "none"

    def guessType(cls):
        """
        Use host name to determine if we're using the production or test
        database and return that type
        """
        hostName = socket.gethostname()
        if hostName.startswith("spts64-"):
            return cls.TEST
        if hostName.startswith("sps-"):
            return cls.PROD
        return cls.NONE
    guessType = classmethod(guessType)

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
            raise StateException("Unknown state #%d" % state)
        return cls.STATES[state]
    str = classmethod(str)

class RunState(AbstractState):
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
        self.__state = RunState.get(state)
        self.__numStarts = numStarts

    def numStarts(self): return self.__numStarts
    def state(self): return self.__state

class LiveState(object):
    "Track the current I3Live service states"

    RUN_PAT = re.compile(r"Current run: (\d+)\s+subrun: (\d+)")
    DOM_PAT = re.compile(r"\s+(\d+)-(\d+): \d+ \d+ \d+ \d+ \d+")
    SVC_PAT = re.compile(r"(\S+) \((\S+):(\d+)\), (async|sync)hronous - (.*)")
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
        self.__runState = RunState.get(RunState.UNKNOWN)
        self.__lightMode = LightMode.UNKNOWN

        self.__runNum = None
        self.__subrunNum = None

        self.__svcDict = {}

    def __str__(self):
        "Return a description of the current I3Live state"
        sum = "Live[%s] Run[%s] Light[%s]" % \
            (self.__threadState, RunState.str(self.__runState),
             LightMode.str(self.__lightMode))

        for key in self.__svcDict.keys():
            svc = self.__svcDict[key]
            sum += " %s[%s*%d]" % (key, RunState.str(svc.state()),
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
                self.__runState = RunState.get(back)
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
                    front == "snEvents":
                # ignore rates
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
            port = int(m.group(3))
            isAsync = m.group(4) == "async"
            back = m.group(5)

            state = RunState.UNKNOWN
            numStarts = 0

            if back == "DIED!":
                state = RunState.DEAD
            else:
                m = LiveState.SVCBACK_PAT.match(back)
                if m:
                    state = m.group(1)
                    numStarts = int(m.group(2))

            svc = LiveService(name, host, port, isAsync, state, numStarts)
            self.__svcDict[name] = svc
            return LiveState.PARSE_NORMAL

        print >>sys.stderr, "Unknown livecmd line: %s" % line

    def check(self):
        "Check the current I3Live service states"

        cmd = "%s check" % self.__prog
        if self.__showCmd: print cmd
        (fi, foe) = os.popen4(cmd)
        fi.close()

        parseState = LiveState.PARSE_NORMAL
        for line in foe:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line
            parseState = self.__parseLine(parseState, line)
        foe.close()

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
        return RunState.str(self.__runState)

    def svcState(self, svcName):
        """
        Return the state string for the specified service
        from the most recent check()
        """
        if not self.__svcDict.has_key(svcName):
            return RunState.UNKNOWN
        return RunState.str(self.__svcDict[svcName].state())

class FlasherThread(threading.Thread):
    "Thread which starts and stops flashers during a run"

    def __init__(self, prog, data, times, pauseSecs, showCmd, showCmdOutput):
        """
        Create a flasher thread (which has not been started)

        prog - location of 'livecmd' executable
        data - flasher description file
        times - list of flasher durations (in seconds)
        pauseSecs - number of seconds to pause between flasher sequences
        showCmd - True if commands should be printed before being run
        showCmdOutput - True if command output should be printed
        """

        super(FlasherThread, self).__init__()

        self.__prog = prog
        self.__data = data
        self.__times = times
        self.__pauseSecs = pauseSecs
        self.__showCmd = showCmd
        self.__showCmdOutput = showCmdOutput

        self.__sem = threading.BoundedSemaphore()

        self.__running = False

    def computeRunDuration(cls, times, pauseSecs):
        """
        Compute the number of seconds needed for this flasher run

        times - list of flasher durations (in seconds)
        pauseSecs - number of seconds to pause between flasher sequences
        """
        tot = 0

        for tm in times:
            tot += tm + pauseSecs + 5

        return tot
    computeRunDuration = classmethod(computeRunDuration)

    def run(self):
        "Body of the flasher thread"
        self.__sem.acquire()
        self.__running = True

        try:
            self.__runBody()
        finally:
            self.__sem.release()

    def __runBody(self):
        "Run the flasher sequences"
        for tm in self.__times:
            if not self.__running:
                break

            cmd = "%s flasher -d %d -f %s" % (self.__prog, tm, self.__data)
            if self.__showCmd: print cmd
            (fi, foe) = os.popen4(cmd)
            fi.close()

            problem = False
            for line in foe:
                line = line.rstrip()
                if self.__showCmdOutput: print '+ ' + line

                if not self.__running:
                    break

                if line != "OK" and not line.startswith("Starting subrun"):
                    problem = True
                if problem:
                    print >>sys.stderr, "Flasher: %s" % line
            foe.close()

            if problem or not self.__running:
                break

            time.sleep(self.__pauseSecs)

    def stopThread(self):
        "Stop the flasher thread"
        self.__running = False

    def waitForThread(self):
        "Wait for the thread to complete"

        # acquire the semaphore (which the thread will hold until finished)
        #
        self.__sem.acquire()

        # thread must be done now, release the semaphore and return
        #
        self.__sem.release()

class LiveRun(object):
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

        if dbType is not None:
            self.__dbType = dbType
        else:
            self.__dbType = DatabaseType.guessType()

        # check for needed executables
        #
        self.__launchProg = \
            os.path.join(os.environ["PDAQ_HOME"], "dash", "DAQLaunch.py")
        self.__checkExists("Launch program", self.__launchProg)

        self.__liveCmdProg = os.path.join(os.environ["HOME"], "bin", "livecmd")
        self.__checkExists("I3Live program", self.__liveCmdProg)

        self.__updateDBProg = \
            os.path.join(os.environ["HOME"], "offline-db-update",
                         "offline-db-update-config")
        self.__checkExists("PnF program", self.__updateDBProg)

        # make sure run-config directory exists
        #
        self.__configDir = os.path.join(os.environ["PDAQ_HOME"], "config")
        if not os.path.isdir(self.__configDir):
            raise SystemExit("Run config directory '%s' does not exist" %
                             self.__configDir)

        # build state-checker
        #
        self.__state = LiveState(self.__liveCmdProg, showCheck, showCheckOutput)

    def __checkExists(self, name, path):
        """
        Exit if the specified path does not exist

        name - description of this path (used in error messages)
        path - file/directory path
        """
        if not os.path.exists(path):
            raise SystemExit("%s '%s' does not exist" % (name, path))

    def __controlPDAQ(self):
        """
        Connect I3Live to pDAQ

        Return True if I3Live controls pDAQ
        """

        cmd = "%s control pdaq localhost:%s" % \
            (self.__liveCmdProg, DAQPort.DAQLIVE)
        if self.__showCmd: print cmd
        (fi, foe) = os.popen4(cmd)
        fi.close()

        controlled = False
        for line in foe:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line
            if line == "Service pdaq is now being controlled":
                controlled = True
            else:
                print >>sys.stderr, "Control: %s" % line
        foe.close()

        return controlled

    def __flashPath(self, flashFile):
        """
        Find a flasher file or raise FlashFileException

        flashFile - name of flasher sequence file

        Returns full path for flasher sequence file

        NOTE: Currently, only $PDAQ_HOME/src/test/resources is checked
        """

        if os.path.exists(flashFile):
            return flashFile

        path = os.path.join(os.environ["PDAQ_HOME"], "src", "test",
                            "resources", flashFile)
        if os.path.exists(path):
            return path

        if not flashFile.endswith(".xml"):
            path += ".xml"
            if os.path.exists(path):
                return path

        raise FlashFileException("Flash file '%s' not found" % flashFile)

    def __getActiveClusterConfig(self):
        "Return the name of the current pDAQ cluster configuration"
        clusterFile = os.path.join(os.environ["HOME"], ".active")
        try:
            f = open(clusterFile, "r")
            ret = f.readline()
            f.close()
            return ret.rstrip('\r\n')
        except:
            return None

    def __getLastRunNumber(self):
        "Return the last run number"
        cmd = "%s lastrun" % self.__liveCmdProg
        if self.__showCmd: print cmd
        (fi, foe) = os.popen4(cmd)
        fi.close()

        num = None
        for line in foe:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line
            num = int(line)
        foe.close()

        return num

    def __runBasicCommand(self, name, cmd):
        """
        Run a basic I3Live command

        name - description of this command (used in error messages)
        path - I3Live command which responds with "OK" or an error

        Return True if there was a problem
        """
        if self.__showCmd: print cmd
        (fi, foe) = os.popen4(cmd)
        fi.close()

        problem = False
        for line in foe:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line

            if line != "OK":
                problem = True
            if problem:
                print >>sys.stderr, "%s: %s" % (name, line)
        foe.close()

        return not problem

    def __setLightMode(self, isLID):
        """
        Set the I3Live LID mode

        isLID - True for LID mode, False for dark mode

        Return True if the light mode was set successfully
        """
        if isLID:
            expMode = LightMode.LID
        else:
            expMode = LightMode.DARK

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

    def __startRun(self, runCfg, duration, numRuns=1, ignoreDB=False):
        """
        Tell I3Live to start a run

        runCfg - run configuration file name
        duration - number of seconds for run
        numRuns - number of runs (default=1)
        ignoreDB - tell I3Live to not check the database for this run config

        Return True if the run was started
        """
        if ignoreDB or self.__dbType == DatabaseType.NONE:
            iArg = "-i"
        else:
            iArg = ""
        cmd = "%s start -d %s -n %d -l %d %s daq" % \
            (self.__liveCmdProg, runCfg, numRuns, duration, iArg)
        if not self.__runBasicCommand("StartRun", cmd):
            return False

        if not self.__waitForState(RunState.STOPPED, RunState.STARTING, 10, 6):
            raise RunException("Run %d did not start" % runNum)
        return self.__waitForState(RunState.STARTING, RunState.RUNNING, 18, 0)

    def __updateDB(self, runCfg):
        """
        Add this run configuration to the database

        runCfg - run configuration
        """
        if self.__dbType == DatabaseType.NONE:
            return

        runCfgPath = os.path.join(self.__configDir, runCfg + ".xml")
        self.__checkExists("Run configuration", runCfgPath)

        if self.__dbType == DatabaseType.TEST:
            arg = "-D I3OmDb_test"
        else:
            arg = ""

        cmd = "%s %s %s" % (self.__updateDBProg, arg, runCfgPath)
        if self.__showCmd: print cmd
        (fi, foe) = os.popen4(cmd)
        fi.close()

        for line in foe:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line

            if line.find("ErrAlreadyExists") > 0:
                continue

            print >>sys.stderr, "UpdateDB: %s" % line
        foe.close()

    def __waitForRun(self, runNum, duration):
        """
        Wait for the current run to start and stop

        runNum - current run number
        duration - expected number of seconds this run will last
        """
        waitSecs = 10
        numTries = duration / waitSecs

        expState = RunState.RUNNING
        numWaits = 0

        daqStopped = False

        while True:
            self.__state.check()
            if self.__state.runState() == expState:
                if expState == RunState.STOPPED:
                    break
            else:
                if expState == RunState.RUNNING:
                    runTime = numWaits * waitSecs
                    if runTime < duration:
                        print >>sys.stderr, \
                            ("WARNING: Expected %d second run, but run %d" +
                             " ended after about %d seconds") % \
                             (duration, runNum, runTime)

                    if self.__state.runState() == RunState.STOPPED or \
                            self.__state.runState() == RunState.STOPPING or \
                            self.__state.runState() == RunState.RECOVERING:
                        break

                    print >>sys.stderr, "Unexpected run %d state %s" % \
                        (runNum, self.__state.runState())

                elif expState != RunState.STOPPED:
                    print >>sys.stderr, "Ignoring expected run %d state %s" % \
                        (runNum, expState)

            if not daqStopped and \
                    self.__state.svcState("pdaq") == RunState.STOPPED:
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

            if numErrors > 0 and self.__state.runState() == RunState.ERROR:
                time.sleep(5)
                numErrors -= 1
                continue

            if self.__state.runState() != curState and \
                    self.__state.runState() != RunState.RECOVERING:
                raise RunException(("I3Live state should be %s or" +
                                    " RECOVERING, not %s") %
                                   (curState, self.__state.runState()))

            time.sleep(waitSecs)

        if self.__state.runState() != expState:
            totTime = int(time.time() - startTime)
            raise RunException(("I3Live state should be %s, not %s" +
                                " (waited %d secs)") %
                               (expState, self.__state.runState(), totTime))

        return True

    def killComponents(self):
        "Kill all pDAQ components"
        cmd = "%s -k" % self.__launchProg
        if self.__showCmd: print cmd
        (fi, foe) = os.popen4(cmd)
        fi.close()

        failLive = None
        for line in foe:
            line = line.rstrip()

            if line.startswith("Found "):
                failLine = line
            elif line.find("To force a restart") < 0:
                print >>sys.stderr, "KillComponents: %s" % line
        foe.close()

        if failLive is not None:
            raise LaunchException("Could not kill components: %s" % failLive)

    def launch(self, clusterCfg):
        """
        (Re)launch pDAQ with the specified cluster configuration

        clusterCfg - cluster configuration
        """
        self.__state.check()
        if self.__state.runState() != RunState.STOPPED:
            raise LaunchException("I3Live state should be %s, not %s" %
                                  (RunState.STOPPED, self.__state.runState()))

        cmd = "%s -c %s -e -B &" % (self.__launchProg, clusterCfg)
        if self.__showCmd:
            print cmd
        else:
            print "Launching %s" % clusterCfg

        (fi, foe) = os.popen4(cmd)
        fi.close()
        foe.close()

    def run(self, clusterCfg, runCfg, duration, numRuns=1,
            flashName=None, flashTimes=None, flashPause=60,
            ignoreDB=False):
        """
        Manage a set of runs using IceCube Live

        clusterCfg - cluster configuration
        runCfg - run configuration
        duration - number of seconds to run
        numRuns - number of runs (default=1)
        flashName - flasher description file name
        flashTimes - list of times (in seconds) to flash
        flashPause - number of seconds to pause between flashing
        ignoreDB - False if I3Live should ensure this run config is
                   in the database
        """
        self.__state.check()
        if self.__state.svcState("pdaq") == RunState.UNKNOWN:
            if not self.__controlPDAQ():
                raise RunException("Could not tell I3Live to control pdaq")
            self.__state.check()
        if self.__state.runState() != RunState.STOPPED:
            raise RunException("I3Live state should be %s, not %s" %
                               (RunState.STOPPED, self.__state.runState()))

        # get absolute path to flasher data file
        #
        if flashName is None:
            flashData = None
        else:
            flashData = self.__flashPath(flashName)

        # write the run configuration to the database
        #
        self.__updateDB(runCfg)

        # get the last active cluster configuration
        #
        activeCfg = self.__getActiveClusterConfig()

        # if pDAQ isn't active or if we need a different cluster config,
        #   kill the current components
        #
        if activeCfg is None or activeCfg != clusterCfg:
            self.killComponents()
            runKilled = True
        else:
            runKilled = False

        # if necessary, launch the desited cluster configuration
        #
        if runKilled or self.__state.runState() == RunState.DEAD:
            self.launch(clusterCfg)

        # get the new run number
        #
        runNum = self.__getLastRunNumber() + 1

        # if we'll be flashing, build a thread to start/stop flashers
        #
        lightMode = flashData is not None and flashTimes is not None
        if not lightMode:
            flashThread = None
        else:
            flashDur = FlasherThread.computeRunDuration(flashTimes, flashPause)
            if flashDur > duration:
                if duration > 0:
                    print >>sys.stderr, ("Run length was %d secs, but need" +
                                         " %d secs for flashers") % \
                                         (duration, flashDur)
                duration = flashDur

            flashThread = FlasherThread(self.__liveCmdProg, flashData,
                                        flashTimes, flashPause, self.__showCmd,
                                        self.__showCmdOutput)

        # set the LID mode
        #
        if not self.__setLightMode(lightMode):
            raise RunException("Could not set lightMode for run #%d: %s" %
                               (runNum, runCfg))

        # start the run
        #
        if not self.__startRun(runCfg, duration, numRuns, ignoreDB):
            raise RunException("Could not start run #%d: %s" % (runNum, runCfg))

        # make sure we've got the correct run number
        #
        if self.__state.runNumber() != runNum:
            print >>sys.stderr, \
                "  Expected run number %d, but actual number is %d" % \
                (runNum, self.__state.runNumber())
            runNum = self.__state.runNumber()

        # print run info
        #
        if flashThread is None:
            runType = "run"
        else:
            runType = "flasher run"

        print "Started %s %d (%d secs) %s" % \
            (runType, runNum, duration, runCfg)

        # start flashing
        #
        if flashThread is not None:
            flashThread.start()

        # wait for everything to finish
        #
        self.__waitForRun(runNum, duration)
        if flashThread is not None:
            flashThread.waitForThread()

        # wait for pDAQ to stop
        #
        if not self.__waitForState(RunState.STOPPING, RunState.STOPPED, 60, 0):
            raise RunException("Run %d did not stop" % runNum)

        # turn off LID mode
        #
        if not self.__setLightMode(False):
            raise RunException(("Could not set lightMode to dark after run " +
                                " #%d: %s") % (runNum, runCfg))

if __name__ == "__main__":
    run = LiveRun(True, True)
    run.run("spts64-real-21-29", "spts64-dirtydozen-hlc-006", 60, 1,
            "flash-21.xml", (30, 30, 20, 15), 30)
