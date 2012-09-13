#!/usr/bin/env python
#
# Base class for managing pDAQ runs

import os
import re
import socket
import subprocess
import sys
import threading
import time

from ClusterDescription import ClusterDescription
from ComponentManager import ComponentManager
from DAQConfig import DAQConfigException, DAQConfigParser
from DAQConst import DAQPort
from DAQRPC import RPCClient
from DAQTime import PayloadTime

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

# Find install location via $PDAQ_HOME, otherwise use locate_pdaq.py
if "PDAQ_HOME" in os.environ:
    metaDir = os.environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()


class RunException(Exception):
    pass


class FlashFileException(RunException):
    pass


class LaunchException(RunException):
    pass


class StateException(RunException):
    pass


class FlasherThread(threading.Thread):
    "Thread which starts and stops flashers during a run"

    def __init__(self, run, dataPairs):
        """
        Create a flasher thread (which has not been started)

        run - BaseRun object
        dataPairs - pairs of XML_file_name/duration
        """

        super(FlasherThread, self).__init__(name="FlasherThread")
        self.setDaemon(True)

        self.__run = run
        self.__dataPairs = dataPairs

        self.__sem = threading.BoundedSemaphore()

        self.__running = False

    @staticmethod
    def computeRunDuration(flasherData):
        """
        Compute the number of seconds needed for this flasher run

        flasherData - list of XML_file_name/duration pairs
        """
        tot = 0

        for pair in flasherData:
            tot += pair[1] + 10

        return tot

    def run(self):
        "Body of the flasher thread"
        self.__sem.acquire()
        self.__running = True

        try:
            self.__runBody()
        finally:
            self.__running = False
            self.__sem.release()

        try:
            self.__run.stopRun()
        except:
            pass

    def __runBody(self):
        "Run the flasher sequences"
        for pair in self.__dataPairs:
            if not self.__running:
                break

            problem = self.__run.flash(pair[0], pair[1])

            if problem or not self.__running:
                break

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


class FlasherShellScript(object):
    """
    Read in a flasher script, producing a list of XML_file_name/duration pairs.
    """
    @classmethod
    def findDataFile(cls, flashFile):
        """
        Find a flasher file or raise FlashFileException

        flashFile - name of flasher sequence file

        Returns full path for flasher sequence file

        NOTE: Currently, only $PDAQ_HOME/src/test/resources is checked
        """

        if os.path.exists(flashFile):
            return flashFile

        path = os.path.join(metaDir, "src", "test", "resources", flashFile)

        if os.path.exists(path):
            return path

        if not flashFile.endswith(".xml"):
            path += ".xml"
            if os.path.exists(path):
                return path

        raise FlashFileException("Flash file '%s' not found" % flashFile)

    # stolen from live/misc/util.py
    @classmethod
    def __getDurationFromString(cls, s):
        """
        Return duration in seconds based on string <s>
        """
        m = re.search('^(\d+)$', s)
        if m:
            return int(m.group(1))
        m = re.search('^(\d+)s(?:ec(?:s)?)?$', s)
        if m:
            return int(m.group(1))
        m = re.search('^(\d+)m(?:in(?:s)?)?$', s)
        if m:
            return int(m.group(1)) * 60
        m = re.search('^(\d+)h(?:r(?:s)?)?$', s)
        if m:
            return int(m.group(1)) * 3600
        m = re.search('^(\d+)d(?:ay(?:s)?)?$', s)
        if m:
            return int(m.group(1)) * 86400
        raise FlashFileException(('String "%s" is not a known duration'
                                  ' format. Try 30sec, 10min, 2days etc.'
                                  ) % s)

    @classmethod
    def __parseFlasherOptions(cls, optList):
        """
        Parse 'livecmd flasher' options
        """
        pairs = []
        i = 0
        dur = None
        fil = None
        while i < len(optList):
            if optList[i] == "-d":
                if dur is not None:
                    raise FlashFileException("Found multiple durations")

                i += 1
                dur = cls.__getDurationFromString(optList[i])
                if fil is not None:
                    pairs.append((fil, dur))
                    dur = None
                    fil = None

            elif optList[i] == "-f":
                if fil is not None:
                    raise FlashFileException("Found multiple filenames")

                i += 1
                fil = cls.findDataFile(optList[i])
                if dur is not None:
                    pairs.append((fil, dur))
                    dur = None
                    fil = None
            else:
                raise FlashFileException("Bad flasher option \"%s\"" %
                                         optList[i])

            i += 1
        return pairs

    @classmethod
    def parse(cls, fd):
        """
        Parse a flasher script, producing a list of XML_file_name/duration
        pairs.
        """
        flashData = []
        fullLine = None
        for line in fd:
            line = line.rstrip()

            if fullLine is None:
                fullLine = line
            else:
                fullLine += line

            if fullLine.endswith("\\") and fullLine.find("#") < 0:
                fullLine = fullLine[:-1]
                continue

            comment = fullLine.find("#")
            if comment >= 0:
                fullLine = fullLine[:comment].rstrip()

            # ignore blank lines
            #
            if len(fullLine) == 0:
                continue

            words = fullLine.split(" ")
            if len(words) > 2 and words[0] == "livecmd" and \
                words[1] == "flasher":
                flashData += cls.__parseFlasherOptions(words[2:])
            elif len(words) == 2 and words[0] == "sleep":
                try:
                    flashData.append((None, int(words[1])))
                except Exception as ex:
                    raise FlashFileException("Bad sleep time \"%s\": %s" %
                                              (words[1], ex))
            else:
                raise FlashFileException("Bad flasher line \"%s\"" % fullLine)

            fullLine = None

        return flashData


class Run(object):
    def __init__(self, mgr, clusterCfgName, runCfgName, configDir=None,
                 clusterDesc=None, flashData=None, dryRun=False):
        """
        Manage a single run

        mgr - run manager
        clusterCfgName - name of cluster configuration
        runCfgName - name of run configuration
        flasherData - list of flasher XML_file_name/duration pairs
        dryRun - True if commands should only be printed and not executed
        """
        self.__mgr = mgr
        self.__runCfgName = runCfgName
        self.__flashData = flashData
        self.__dryRun = dryRun

        self.__runKilled = False

        self.__flashThread = None
        self.__lightMode = None
        self.__clusterCfg = None

        # __runNum being 0 is considered a safe initializer as per Dave G.
        # it was None which would cause a TypeError on some
        # error messages
        self.__runNum = 0
        self.__duration = None

        activeCfgName = self.__mgr.getActiveClusterConfig()
        if clusterCfgName is None:
            clusterCfgName = activeCfgName
            if clusterCfgName is None:
                raise RunException("No cluster configuration specified")

        # __runCfgName has to be non-null as well otherwise we get an exception
        if self.__runCfgName is None:
            raise RunException("No Run Configuration Specified")

        # if pDAQ isn't active or if we need a different cluster config,
        #   kill the current components
        #
        if activeCfgName is None or activeCfgName != clusterCfgName:
            self.__mgr.killComponents(dryRun=self.__dryRun)
            self.__runKilled = True

        try:
            self.__clusterCfg = \
                DAQConfigParser.getClusterConfiguration(clusterCfgName,
                                                        useActiveConfig=False,
                                                        clusterDesc=clusterDesc,
                                                        configDir=configDir,
                                                        validate=False)
        except DAQConfigException:
            raise LaunchException("Cannot load configuration \"%s\": %s" %
                                  (clusterCfgName, exc_string()))

        # if necessary, launch the desired cluster configuration
        #
        if self.__runKilled or self.__mgr.isDead():
            self.__mgr.launch(self.__clusterCfg)

    def finish(self, verbose=False):
        "clean up after run has ended"
        if not self.__mgr.isStopped(True):
            self.__mgr.stopRun()

        if not self.__dryRun and not self.__mgr.isStopped(True) and \
            not self.__mgr.waitForStopped(verbose=verbose):
            raise RunException("Run %d did not stop" % self.__runNum)

        if self.__flashThread is not None:
            self.__flashThread.waitForThread()

        if self.__lightMode and not self.__mgr.setLightMode(False):
            raise RunException(("Could not set lightMode to dark after run " +
                                " #%d: %s") %
                                (self.__runNum, self.__runCfgName))

        try:
            self.__mgr.summarize(self.__runNum)
        except:
            self.__mgr.logger().error("Cannot summarize run %d: %s" % \
                                      (self.__runNum, exc_string()))

        self.__runNum = 0

    def start(self, duration, ignoreDB=False, runMode=None, filterMode=None,
              verbose=False):
        """
        Start a run

        duration - number of seconds to run
        ignoreDB - False if the database should be checked for this run config
        runMode - Run mode for 'livecmd'
        filterMode - Run mode for 'livecmd'
        verbose - provide additional details of the run
        """
        # write the run configuration to the database
        #
        if not ignoreDB:
            self.__mgr.updateDB(self.__runCfgName)

        # if we'll be flashing, build a thread to start/stop flashers
        #
        self.__lightMode = self.__flashData is not None
        if not self.__lightMode:
            self.__flashThread = None
        else:
            flashDur = FlasherThread.computeRunDuration(self.__flashData)
            if flashDur > duration:
                if duration > 0:
                    self.__mgr.logger().error(("Run length was %d secs, but" +
                                               " need %d secs for flashers") %
                                              (duration, flashDur))
                duration = flashDur

            self.__flashThread = FlasherThread(self.__mgr, self.__flashData)

        # get the new run number
        #
        runData = self.__mgr.getLastRunNumber()
        self.__runNum = runData[0] + 1
        self.__duration = duration

        # set the LID mode
        #
        if not self.__mgr.setLightMode(self.__lightMode):
            raise RunException("Could not set lightMode for run #%d: %s" %
                               (self.__runNum, self.__runCfgName))

        # start the run
        #
        if not self.__mgr.startRun(self.__runCfgName, duration, 1, ignoreDB,
                                   runMode=runMode, filterMode=filterMode,
                                   verbose=verbose):
            raise RunException("Could not start run #%d: %s" %
                               (self.__runNum, self.__runCfgName))

        # make sure we've got the correct run number
        #
        curNum = self.__mgr.getRunNumber()
        if curNum != self.__runNum:
            self.__mgr.logger().error(("Expected run number %d, but actual" +
                                       " number is %s") %
                                      (self.__runNum, curNum))
            self.__runNum = curNum

        # print run info
        #
        if self.__flashThread is None:
            runType = "run"
        else:
            runType = "flasher run"

        self.__mgr.logger().info("Started %s %d (%d secs) %s" %
                                 (runType, self.__runNum, duration,
                                  self.__runCfgName))

        # start flashing
        #
        if self.__flashThread is not None:
            self.__flashThread.start()

    def stop(self):
        "stop run"
        self.__mgr.stop()

    def wait(self):
        "wait for run to finish"
        if not self.__dryRun:
            self.__mgr.waitForRun(self.__runNum, self.__duration)


class RunLogger(object):
    def __init__(self, logfile=None):
        """
        logfile - name of file which log messages are written
                  (None for sys.stdout/sys.stderr)
        """
        if logfile is None:
            self.__fd = None
        else:
            self.__fd = open(logfile, "a")

    def __logmsg(self, sep, msg):
        print >>self.__fd, time.strftime("%Y-%m-%d %H:%M:%S") + " " + \
            sep + " " + msg

    def error(self, msg):
        print >>sys.stderr, "!! " + msg
        if self.__fd is not None:
            self.__logmsg("[ERROR]", msg)

    def info(self, msg):
        print " " + msg
        if self.__fd is not None:
            self.__logmsg("[INFO]", msg)


class BaseRun(object):
    """User's PATH, used by findExecutable()"""
    PATH = None

    def __init__(self, showCmd=False, showCmdOutput=False, dryRun=False,
                 dbType=None, logfile=None):
        """
        showCmd - True if commands should be printed before being run
        showCmdOutput - True if command output should be printed
        dryRun - True if commands should only be printed and not executed
        dbType - DatabaseType value (TEST, PROD, or NONE)
        logfile - file where all log messages are saved
        """
        self.__showCmd = showCmd
        self.__showCmdOutput = showCmdOutput
        self.__dryRun = dryRun

        self.__logger = RunLogger(logfile)

        self.__cnc = None

        if dbType is not None:
            self.__dbType = dbType
        else:
            self.__dbType = ClusterDescription.getClusterDatabaseType()

        # check for needed executables
        #
        self.__updateDBProg = \
            os.path.join(os.environ["HOME"], "offline-db-update",
                         "offline-db-update-config")
        if not self.checkExists("PnF program", self.__updateDBProg, False):
            self.__updateDBProg = None

        # make sure run-config directory exists
        #
        self.__configDir = os.path.join(metaDir, "config")

        if not os.path.isdir(self.__configDir):
            raise SystemExit("Run config directory '%s' does not exist" %
                             self.__configDir)

    @staticmethod
    def checkExists(name, path, fatal=True):
        """
        Exit if the specified path does not exist

        name - description of this path (used in error messages)
        path - file/directory path
        fatal - True if program should exit if file is not found
        """
        if not os.path.exists(path):
            if fatal:
                raise SystemExit("%s '%s' does not exist" % (name, path))
            return False
        return True

    def cleanUp(self):
        """Do final cleanup before exiting"""
        raise NotImplementedError()

    def createRun(self, clusterCfgName, runCfgName, clusterDesc=None,
                  flashData=None):
        return Run(self, clusterCfgName, runCfgName, self.__configDir,
                   clusterDesc=clusterDesc, flashData=flashData,
                   dryRun=self.__dryRun)

    @classmethod
    def findExecutable(cls, name, cmd, dryRun=False):
        """Find 'cmd' in the user's PATH"""
        if cls.PATH is None:
            cls.PATH = os.environ["PATH"].split(":")
        for pdir in cls.PATH:
            pcmd = os.path.join(pdir, cmd)
            if os.path.exists(pcmd):
                return pcmd
        if dryRun:
            return cmd
        raise SystemExit("%s '%s' does not exist" % (name, cmd))

    def flash(self, filename, secs):
        """Start flashers with the specified data for the specified duration"""
        raise NotImplementedError()

    @staticmethod
    def getActiveClusterConfig():
        "Return the name of the current pDAQ cluster configuration"
        clusterFile = os.path.join(os.environ["HOME"], ".active")
        try:
            with open(clusterFile, 'r') as f:
                ret = f.readline()
                return ret.rstrip('\r\n')
        except:
            return None

    def cncConnection(self, abortOnFail=True):
        if self.__cnc is None:
            self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)
            try:
                self.__cnc.rpc_ping()
            except socket.error as err:
                if err[0] == 61 or err[0] == 111:
                    self.__cnc = None
                else:
                    raise

        if self.__cnc is None and abortOnFail:
            raise RunException("Cannot connect to CnCServer")

        return self.__cnc

    def getLastRunNumber(self):
        "Return the last run number"
        raise NotImplementedError()

    def getRunNumber(self):
        "Return the current run number"
        raise NotImplementedError()

    def ignoreDatabase(self):
        return self.__dbType == ClusterDescription.DBTYPE_NONE

    def isDead(self, refreshState=False):
        raise NotImplementedError()

    def isRecovering(self, refreshState=False):
        raise NotImplementedError()

    def isRunning(self, refreshState=False):
        raise NotImplementedError()

    def isStopped(self, refreshState=False):
        raise NotImplementedError()

    def isStopping(self, refreshState=False):
        raise NotImplementedError()

    def killComponents(self, dryRun=False):
        "Kill all pDAQ components"
        cfgDir = os.path.join(metaDir, 'config')

        comps = ComponentManager.getActiveComponents(None, configDir=cfgDir,
                                                     validate=False)

        verbose = False

        if comps is not None:
            ComponentManager.kill(comps, verbose=verbose, dryRun=dryRun,
                                  logger=self.__logger)

    def launch(self, clusterCfg):
        """
        (Re)launch pDAQ with the specified cluster configuration

        clusterCfg - cluster configuration
        """
        if not self.__dryRun and self.isRunning():
            raise LaunchException("There is at least one active run")

        spadeDir = clusterCfg.logDirForSpade()
        copyDir = clusterCfg.logDirCopies()
        logDir = clusterCfg.daqLogDir()
        daqDataDir = clusterCfg.daqDataDir()

        cfgDir = os.path.join(metaDir, 'config')
        dashDir = os.path.join(metaDir, 'dash')
        logDirFallback = os.path.join(metaDir, "log")

        doCnC = True
        verbose = False
        eventCheck = True

        logPort = None
        livePort = DAQPort.I3LIVE

        self.logCmd("Launch %s" % clusterCfg)
        ComponentManager.launch(doCnC, dryRun=self.__dryRun, verbose=verbose,
                                clusterConfig=clusterCfg, dashDir=dashDir,
                                configDir=cfgDir, daqDataDir=daqDataDir,
                                logDir=logDir, logDirFallback=logDirFallback,
                                spadeDir=spadeDir, copyDir=copyDir,
                                logPort=logPort, livePort=livePort,
                                eventCheck=eventCheck,
                                logger=self.__logger)

        # give components a chance to start
        time.sleep(5)

    def logCmd(self, msg):
        if self.__showCmd:
            self.__logger.info("% " + msg)

    def logCmdOutput(self, msg):
        if self.__showCmdOutput:
            self.__logger.info("%%% " + msg)

    def logError(self, msg):
        self.__logger.error(msg)

    def logInfo(self, msg):
        self.__logger.info(msg)

    def logger(self):
        return self.__logger

    def run(self, clusterCfgName, runCfgName, duration, flashData=None,
            clusterDesc = None, ignoreDB=False, runMode="TestData",
            filterMode=None, verbose=False):
        """
        Manage a set of runs

        clusterCfgName - cluster configuration
        runCfgName - name of run configuration
        duration - number of seconds to run
        flasherData - pairs of (XML file name, duration)
        ignoreDB - False if the database should be checked for this run config
        runMode - Run mode for 'livecmd'
        filterMode - Run mode for 'livecmd'
        verbose - provide additional details of the run
        """

        run = self.createRun(clusterCfgName, runCfgName,
                             clusterDesc=clusterDesc, flashData=flashData)

        if filterMode is None and flashData is not None:
            filterMode = "RandomFiltering"

        run.start(duration, ignoreDB, runMode=runMode, filterMode=filterMode,
                  verbose=verbose)

        try:
            run.wait()
        finally:
            run.finish(verbose=verbose)

    def setLightMode(self, isLID):
        """
        Set the Light-In-Detector mode

        isLID - True for light-in-detector mode, False for dark mode

        Return True if the light mode was set successfully
        """
        raise NotImplementedError()

    def startRun(self, runCfgName, duration, numRuns=1, ignoreDB=False,
                 verbose=False):
        """
        Start a run

        runCfgName - run configuration file name
        duration - number of seconds for run
        numRuns - number of runs (default=1)
        ignoreDB - don't check the database for this run config
        verbose - print more details of run transitions

        Return True if the run was started
        """
        raise NotImplementedError()

    def state(self):
        """Current state of runset"""
        raise NotImplementedError()

    def stopOnSIGINT(self, signal, frame):
        print "Caught signal, stopping run"
        if self.isRunning(True):
            self.stopRun()
            self.waitForStopped(verbose=True)
        print "Exiting"
        raise SystemExit

    def stopRun(self):
        """Stop the run"""
        raise NotImplementedError()

    def summarize(self, runNum):
        if self.__dryRun:
            return

        summary = self.cncConnection().rpc_run_summary(runNum)

        if summary["startTime"] == "None" or \
            summary["endTime"] == "None":
            duration = "???"
        else:
            try:
                startTime = PayloadTime.fromString(summary["startTime"])
            except:
                raise ValueError("Cannot parse run start time \"%s\": %s" %
                                 (summary["startTime"], exc_string()))
            try:
                endTime = PayloadTime.fromString(summary["endTime"])
            except:
                raise ValueError("Cannot parse run start time \"%s\": %s" %
                                 (summary["startTime"], exc_string()))

            try:
                timediff = endTime - startTime
            except:
                raise ValueError("Cannot get run duration from (%s - %s): %s" %
                                 (endTime, startTime, exc_string()))

            duration = timediff.seconds
            if timediff.days > 0:
                duration += timediff.days * 60 * 60 * 24

        self.logInfo("Run %d (%s) %s seconds : %s" %
                     (summary["num"], summary["config"], duration,
                      summary["result"]))

    def updateDB(self, runCfgName):
        """
        Add this run configuration to the database

        runCfgName - name of run configuration
        """
        if self.__dbType == ClusterDescription.DBTYPE_NONE:
            return

        if self.__updateDBProg is None:
            self.logError("Not updating database with \"%s\"" % runCfgName)
            return

        runCfgPath = os.path.join(self.__configDir, runCfgName + ".xml")
        self.checkExists("Run configuration", runCfgPath)

        if self.__dbType == ClusterDescription.DBTYPE_TEST:
            arg = "-D I3OmDb_test"
        else:
            arg = ""

        cmd = "%s %s %s" % (self.__updateDBProg, arg, runCfgPath)
        self.logCmd(cmd)

        if self.__dryRun:
            print cmd
            return

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        for line in proc.stdout:
            line = line.rstrip()
            self.logCmdOutput(line)

            if line.find("ErrAlreadyExists") > 0:
                continue

            elif line != "xml":
                self.logError("UpdateDB: %s" % line)
        proc.stdout.close()

        proc.wait()

    def waitForRun(self, runNum, duration):
        """
        Wait for the current run to start and stop

        runNum - current run number
        duration - expected number of seconds this run will last
        """

        # wake up every 'waitSecs' seconds to check run state
        #
        waitSecs = 10

        numTries = duration / waitSecs
        numWaits = 0

        while True:
            if not self.isRunning():
                runTime = numWaits * waitSecs
                if runTime < duration:
                    self.logError(("WARNING: Expected %d second run, " +
                                   "but run %d ended after %d seconds") %
                                  (duration, runNum, runTime))

                if self.isStopped(False) or \
                        self.isStopping(False) or \
                        self.isRecovering(False):
                    break

                self.logError("Unexpected run %d state %s" %
                              (runNum, self.state()))

            numWaits += 1
            if numWaits > numTries:
                break

            time.sleep(waitSecs)

    def waitForStopped(self, verbose=False):
        """Wait for the current run to be stopped"""
        raise NotImplementedError()
