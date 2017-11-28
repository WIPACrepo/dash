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

from ANSIEscapeCode import ANSIEscapeCode
from ClusterDescription import ClusterDescription
from ComponentManager import ComponentManager
from DAQConfig import DAQConfigException, DAQConfigParser
from DAQConst import DAQPort
from DAQRPC import RPCClient
from DAQTime import PayloadTime
from locate_pdaq import find_pdaq_config, find_pdaq_trunk

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


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

    def __init__(self, run, dataPairs, initialDelay=120, dryRun=False):
        """
        Create a flasher thread (which has not been started)

        run - BaseRun object
        dataPairs - pairs of XML_file_name/duration
        """

        super(FlasherThread, self).__init__(name="FlasherThread")
        self.setDaemon(True)

        self.__run = run
        self.__data_pairs = dataPairs
        self.__initial_delay = initialDelay
        self.__dry_run = dryRun

        self.__sem = threading.BoundedSemaphore()

        self.__running = False

    @staticmethod
    def computeRunDuration(flasherData, initialDelay):
        """
        Compute the number of seconds needed for this flasher run

        flasherData - list of XML_file_name/duration pairs
        """
        if initialDelay is None:
            tot = 0
        else:
            tot = initialDelay

        for pair in flasherData:
            tot += pair[1] + 10

        return tot

    def run(self):
        "Body of the flasher thread"
        self.__sem.acquire()
        self.__running = True

        try:
            self.__run_body()
        finally:
            self.__running = False
            self.__sem.release()

        try:
            self.__run.stopRun()
        except:
            pass

    def __run_body(self):
        "Run the flasher sequences"
        if self.__initial_delay is not None and self.__initial_delay > 0:
            cmd = "sleep %d" % self.__initial_delay
            self.__run.logCmd(cmd)

            if self.__dry_run:
                print cmd
            else:
                time.sleep(self.__initial_delay)

        for pair in self.__data_pairs:
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


class FlasherScript(object):
    @classmethod
    def __find_flasher_data_file(cls, dirname, filename):
        """Find a flasher data file"""
        path = os.path.join(dirname, filename)
        if os.path.exists(path):
            return path

        if not filename.endswith(".xml"):
            path += ".xml"
            if os.path.exists(path):
                return path

        return None

    @classmethod
    def __clean_string(cls, text):
        """remove extra junk around text fields"""
        if text.startswith("("):
            text = text[1:]
        if text.endswith(")"):
            text = text[:-1]
        if text.endswith(","):
            text = text[:-1]
        if len(text) > 2 and cls.__is_quote(text[0]) and \
                cls.__is_quote(text[-1]):
            text = text[1:-1]
        return text

    # stolen from live/misc/util.py
    @classmethod
    def __get_duration_from_string(cls, s):
        """
        Return duration in seconds based on string <s>
        """
        m = re.search(r'^(\d+)$', s)
        if m:
            return int(m.group(1))
        m = re.search(r'^(\d+)s(?:ec(?:s)?)?$', s)
        if m:
            return int(m.group(1))
        m = re.search(r'^(\d+)m(?:in(?:s)?)?$', s)
        if m:
            return int(m.group(1)) * 60
        m = re.search(r'^(\d+)h(?:r(?:s)?)?$', s)
        if m:
            return int(m.group(1)) * 3600
        m = re.search(r'^(\d+)d(?:ay(?:s)?)?$', s)
        if m:
            return int(m.group(1)) * 86400
        raise FlashFileException(('String "%s" is not a known duration'
                                  ' format. Try 30sec, 10min, 2days etc.') % s)

    @classmethod
    def __is_quote(cls, ch):
        """Is this character a quote mark?"""
        return ch == "'" or ch == '"'

    @classmethod
    def __parse_flasher_options(cls, optList, basedir=None):
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
                dur = cls.__get_duration_from_string(optList[i])
                if fil is not None:
                    pairs.append((fil, dur))
                    dur = None
                    fil = None

            elif optList[i] == "-f":
                if fil is not None:
                    raise FlashFileException("Found multiple filenames")

                i += 1
                fil = cls.findDataFile(optList[i], basedir=basedir)
                if dur is not None:
                    pairs.append((fil, dur))
                    dur = None
                    fil = None
            else:
                raise FlashFileException("Bad flasher option \"%s\"" %
                                         optList[i])

            i += 1
        return pairs

    """
    Read in a flasher script, producing a list of XML_file_name/duration pairs.
    """
    @classmethod
    def findDataFile(cls, flashFile, basedir=None):
        """
        Find a flasher file or raise FlashFileException

        flashFile - name of flasher sequence file
        basedir - base directory where data files are located

        Returns full path for flasher sequence file

        NOTE: Currently, only $PDAQ_HOME/src/test/resources is checked
        """

        if os.path.exists(flashFile):
            return flashFile

        path = cls.__find_flasher_data_file(basedir, flashFile)
        if path is not None:
            return path

        raise FlashFileException("Flash file '%s' not found" % flashFile)

    @classmethod
    def parse(cls, path):
        """
        Parse a flasher script, producing a list of XML_file_name/duration
        pairs.
        """
        if not os.path.isfile(path):
            print "Flasher file \"%s\" does not exist" % path
            return None

        basedir = os.path.dirname(path)
        with open(path, "r") as fd:
            flashData = []
            fullLine = None
            linenum = 0
            failed = False
            for line in fd:
                line = line.rstrip()

                # if continued line, glue this onto the previous line
                #
                if fullLine is None:
                    fullLine = line
                else:
                    fullLine += line

                #  strip continuation character and wait for rest of line
                #
                if fullLine.endswith("\\") and fullLine.find("#") < 0:
                    fullLine = fullLine[:-1]
                    continue

                # strip comments
                #
                comment = fullLine.find("#")
                if comment >= 0:
                    fullLine = fullLine[:comment].rstrip()

                # ignore blank lines
                #
                if len(fullLine) == 0:
                    fullLine = None
                    continue

                # break it into pieces
                words = fullLine.split(" ")

                # handle 'livecmd flasher ...'
                #
                if len(words) > 2 and words[0] == "livecmd" and \
                    words[1] == "flasher":
                    flashData += cls.__parse_flasher_options(words[2:],
                                                             basedir=basedir)
                    fullLine = None
                    continue

                # handle 'sleep ###'
                #
                if len(words) == 2 and words[0] == "sleep":
                    try:
                        flashData.append((None, int(words[1])))
                    except Exception:
                        print "Bad flasher line#%d: %s (bad sleep time)" % \
                              (linenum, fullLine)
                        failed = True
                    fullLine = None
                    continue

                if len(words) == 2:
                    # found 'file duration'
                    name = cls.__clean_string(words[0])
                    durStr = cls.__clean_string(words[1])
                else:
                    words = fullLine.split(",")
                    if len(words) == 2:
                        # found 'file,duration'
                        name = cls.__clean_string(words[0])
                        durStr = cls.__clean_string(words[1])
                    elif len(words) == 3 and len(words[0]) == 0:
                        # found ',file,duration'
                        name = cls.__clean_string(words[1])
                        durStr = cls.__clean_string(words[2])
                    else:
                        print "Bad flasher line#%d: %s" % (linenum, line)
                        failed = True
                        fullLine = None
                        continue

                try:
                    duration = int(durStr)
                except ValueError:
                    # hmm, maybe the duration is first
                    try:
                        duration = int(name)
                        name = durStr
                    except:
                        print "Bad flasher line#%d: %s" % (linenum, line)
                        failed = True
                        fullLine = None
                        continue

                flashData.append((os.path.join(basedir, name), duration))
                fullLine = None
                continue

        if failed:
            return None

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
        self.__run_cfg_name = runCfgName
        self.__flash_data = flashData
        self.__dry_run = dryRun

        self.__run_killed = False

        self.__flash_thread = None
        self.__light_mode = None
        self.__cluster_cfg = None

        # __run_num being 0 is considered a safe initializer as per Dave G.
        # it was None which would cause a TypeError on some
        # error messages
        self.__run_num = 0
        self.__duration = None
        self.__num_runs = 0

        activeCfgName = self.__mgr.getActiveClusterConfig()
        if clusterCfgName is None:
            clusterCfgName = activeCfgName
            if clusterCfgName is None:
                clusterCfgName = runCfgName
                if clusterCfgName is None:
                    raise RunException("No cluster configuration specified")

        # Run configuration name has to be non-null as well
        # or we'll get an exception
        if self.__run_cfg_name is None:
            raise RunException("No Run Configuration Specified")

        # if pDAQ isn't active or if we need a different cluster config,
        #   kill the current components
        #
        if activeCfgName is None or activeCfgName != clusterCfgName:
            self.__mgr.killComponents(dryRun=self.__dry_run)
            self.__run_killed = True

        try:
            self.__cluster_cfg = \
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
        if self.__run_killed or self.__mgr.isDead():
            self.__mgr.launch(self.__cluster_cfg)

    def finish(self, verbose=False):
        "clean up after run has ended"
        if not self.__mgr.isStopped(True):
            self.__mgr.stopRun()

        if not self.__dry_run and not self.__mgr.isStopped(True) and \
            not self.__mgr.waitForStopped(verbose=verbose):
            raise RunException("Run %d did not stop" % self.__run_num)

        if self.__flash_thread is not None:
            self.__flash_thread.waitForThread()

        if self.__light_mode and not self.__mgr.setLightMode(False):
            raise RunException(("Could not set lightMode to dark after run " +
                                " #%d: %s") %
                               (self.__run_num, self.__run_cfg_name))

        try:
            rtnval = self.__mgr.summarize(self.__run_num)
        except:
            self.__mgr.logError("Cannot summarize run %d: %s" % \
                                (self.__run_num, exc_string()))
            rtnval = False

        self.__run_num = 0

        return rtnval

    def start(self, duration, numRuns=1, ignoreDB=False, runMode=None,
              filterMode=None, flasherDelay=None, verbose=False):
        """
        Start a run

        duration - number of seconds to run
        numRuns - number of sequential runs
        ignoreDB - False if the database should be checked for this run config
        runMode - Run mode for 'livecmd'
        filterMode - Run mode for 'livecmd'
        flasherDelay - number of seconds to sleep before starting flashers
        verbose - provide additional details of the run
        """
        # write the run configuration to the database
        #
        if not ignoreDB:
            self.__mgr.updateDB(self.__run_cfg_name)

        # if we'll be flashing, build a thread to start/stop flashers
        #
        self.__light_mode = self.__flash_data is not None
        if not self.__light_mode:
            self.__flash_thread = None
        else:
            if numRuns > 1:
                raise RunException("Only 1 consecutive flasher run allowed" +
                                   " (%d requested)" % numRuns)

            flashDur = FlasherThread.computeRunDuration(self.__flash_data,
                                                        flasherDelay)
            if flashDur > duration:
                if duration > 0:
                    self.__mgr.logError(("Run length was %d secs, but" +
                                         " need %d secs for flashers") %
                                        (duration, flashDur))
                duration = flashDur

            if flasherDelay is None:
                self.__flash_thread = FlasherThread(self.__mgr,
                                                    self.__flash_data,
                                                    dryRun=self.__dry_run)
            else:
                self.__flash_thread = \
                    FlasherThread(self.__mgr, self.__flash_data,
                                  initialDelay=flasherDelay,
                                  dryRun=self.__dry_run)

        # get the new run number
        #
        runData = self.__mgr.getLastRunNumber()
        if runData is None or runData[0] is None:
            raise RunException("Cannot find run number!")

        self.__run_num = runData[0] + 1
        self.__duration = duration
        self.__num_runs = numRuns

        # set the LID mode
        #
        if not self.__mgr.setLightMode(self.__light_mode):
            raise RunException("Could not set lightMode for run #%d: %s" %
                               (self.__run_num, self.__run_cfg_name))

        # start the run
        #
        if not self.__mgr.startRun(self.__run_cfg_name, duration, numRuns,
                                   ignoreDB, runMode=runMode,
                                   filterMode=filterMode, verbose=verbose):
            raise RunException("Could not start run #%d: %s" %
                               (self.__run_num, self.__run_cfg_name))

        # make sure we've got the correct run number
        #
        curNum = self.__mgr.getRunNumber()
        if curNum != self.__run_num:
            self.__mgr.logError(("Expected run number %d, but actual number" +
                                 " is %s") % (self.__run_num, curNum))
            self.__run_num = curNum

        # print run info
        #
        if self.__flash_thread is None:
            runType = "run"
        else:
            runType = "flasher run"

        self.__mgr.logger().info("Started %s %d (%d secs) %s" %
                                 (runType, self.__run_num, duration,
                                  self.__run_cfg_name))

        # start flashing
        #
        if self.__flash_thread is not None:
            self.__flash_thread.start()

    def stop(self):
        "stop run"
        self.__mgr.stop()

    def updateRunNumber(self, num):
        self.__run_num = num

    def wait(self):
        "wait for run to finish"

        if self.__dry_run:
            return

        logger = self.__mgr.logger()

        # wake up every 'waitSecs' seconds to check run state
        #
        waitSecs = 10
        if waitSecs > self.__duration:
            waitSecs = self.__duration

        numTries = self.__duration / waitSecs
        numWaits = 0

        runs = 1
        while True:
            if not self.__mgr.isRunning():
                runTime = numWaits * waitSecs
                if runTime < self.__duration:
                    logger.error(("WARNING: Expected %d second run, " +
                                  "but run %d ended after %d seconds") %
                                 (self.__duration, self.__run_num, runTime))

                if self.__mgr.isStopped(False) or \
                        self.__mgr.isStopping(False) or \
                        self.__mgr.isRecovering(False):
                    break

                if not self.__mgr.isSwitching(False):
                    logger.error("Unexpected run %d state %s" %
                                 (self.__run_num, self.__mgr.state))

            numWaits += 1
            if numWaits > numTries:
                if runs > self.__num_runs:
                    # we've finished all the requested runs
                    break
                if not self.__mgr.switchRun(self.__run_num + 1):
                    logger.error("Failed to switch to run %d" %
                                 (self.__run_num + 1))
                    break

            curRunNum = self.__mgr.getRunNumber()
            while self.__run_num < curRunNum:
                try:
                    self.__mgr.summarize(self.__run_num)
                except:
                    import traceback
                    logger.error("Cannot summarize %d:\n%s" %
                                 (self.__run_num, traceback.format_exc()))

                logger.info("Switched from run %d to %d" %
                            (self.__run_num, curRunNum))

                runTime = numWaits * waitSecs
                if runTime < self.__duration:
                    logger.error(("WARNING: Expected %d second run, " +
                                  "but run %d ended after %d seconds") %
                                 (self.__duration, self.__run_num, runTime))

                # reset number of waits
                numWaits = 1

                # increment number of runs and update run number
                runs += 1
                self.__run_num += 1

            if runs > self.__num_runs:
                plural = "" if self.__num_runs == 1 else "s"
                logger.error("WARNING: Expected %dx%d second run%s but"
                             " run#%d is active" %
                             (self.__num_runs, self.__duration, plural,
                              curRunNum))
                break

            time.sleep(waitSecs)


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
                 logfile=None):
        """
        showCmd - True if commands should be printed before being run
        showCmdOutput - True if command output should be printed
        dryRun - True if commands should only be printed and not executed
        logfile - file where all log messages are saved
        """
        self.__show_cmd = showCmd
        self.__show_cmd_output = showCmdOutput
        self.__dry_run = dryRun
        self.__user_stopped = False

        self.__logger = RunLogger(logfile)

        self.__cnc = None

        self.__db_type = ClusterDescription.getClusterDatabaseType()

        # check for needed executables
        #
        self.__update_db_prog = \
            os.path.join(os.environ["HOME"], "gcd-update", "config-update.sh")
        if not self.checkExists("GCD update", self.__update_db_prog, False):
            self.__update_db_prog = None

        # make sure run-config directory exists
        #
        self.__config_dir = find_pdaq_config()
        if not os.path.isdir(self.__config_dir):
            raise SystemExit("Run config directory '%s' does not exist" %
                             self.__config_dir)

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
        return Run(self, clusterCfgName, runCfgName, self.__config_dir,
                   clusterDesc=clusterDesc, flashData=flashData,
                   dryRun=self.__dry_run)

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
        "Return the last used run and subrun numbers as a tuple"
        raise NotImplementedError()

    def getRunNumber(self):
        "Return the current run number"
        raise NotImplementedError()

    def ignoreDatabase(self):
        return self.__db_type == ClusterDescription.DBTYPE_NONE

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

    def isSwitching(self, refreshState=False):
        raise NotImplementedError()

    def isUserStopped(self, refreshState=False):
        if refreshState:
            print >>sys.stderr, "Not refreshing state in isUserStopped()"
        return self.__user_stopped

    def killComponents(self, dryRun=False):
        "Kill all pDAQ components"
        cfgDir = find_pdaq_config()

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
        if not self.__dry_run and self.isRunning():
            raise LaunchException("There is at least one active run")

        spadeDir = clusterCfg.logDirForSpade
        copyDir = clusterCfg.logDirCopies
        logDir = clusterCfg.daqLogDir
        daqDataDir = clusterCfg.daqDataDir

        cfgDir = find_pdaq_config()
        metaDir = find_pdaq_trunk()
        dashDir = os.path.join(metaDir, "dash")
        logDirFallback = os.path.join(metaDir, "log")

        doCnC = True
        verbose = False
        eventCheck = True

        logPort = None
        livePort = DAQPort.I3LIVE_ZMQ

        self.logCmd("Launch %s" % clusterCfg)
        ComponentManager.launch(doCnC, dryRun=self.__dry_run, verbose=verbose,
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
        if self.__show_cmd:
            self.__logger.info("% " + msg)

    def logCmdOutput(self, msg):
        if self.__show_cmd_output:
            self.__logger.info("%%% " + msg)

    def logError(self, msg):
        self.__logger.error(msg)

    def logInfo(self, msg):
        self.__logger.info(msg)

    def logger(self):
        return self.__logger

    def run(self, clusterCfgName, runCfgName, duration, numRuns=1,
            flashData=None, flasherDelay=None, clusterDesc=None,
            ignoreDB=False, runMode="TestData", filterMode=None,
            verbose=False):
        """
        Manage a set of runs

        clusterCfgName - cluster configuration
        runCfgName - name of run configuration
        duration - number of seconds to run
        numRuns - number of consecutive runs
        flasherData - pairs of (XML file name, duration)
        flasherDelay - number of seconds to sleep before starting flashers
        ignoreDB - False if the database should be checked for this run config
        runMode - Run mode for 'livecmd'
        filterMode - Run mode for 'livecmd'
        verbose - provide additional details of the run
        """

        if self.__user_stopped:
            return False

        if numRuns > 1:
            self.setRunsPerRestart(numRuns)
        else:
            self.setRunsPerRestart(1)

        run = self.createRun(clusterCfgName, runCfgName,
                             clusterDesc=clusterDesc, flashData=flashData)

        if filterMode is None and flashData is not None:
            filterMode = "RandomFiltering"

        run.start(duration, numRuns=numRuns, ignoreDB=ignoreDB,
                  runMode=runMode, filterMode=filterMode,
                  flasherDelay=flasherDelay, verbose=verbose)

        try:
            run.wait()
        except:
            import traceback
            traceback.print_exc()

        return run.finish(verbose=verbose)

    def setLightMode(self, isLID):
        """
        Set the Light-In-Detector mode

        isLID - True for light-in-detector mode, False for dark mode

        Return True if the light mode was set successfully
        """
        raise NotImplementedError()

    def setRunsPerRestart(self, num):
        """Set the number of continuous runs between restarts"""
        raise NotImplementedError()

    def startRun(self, runCfgName, duration, numRuns=1, ignoreDB=False,
                 runMode=None, filterMode=None, verbose=False):
        """
        Start a run

        runCfgName - run configuration file name
        duration - number of seconds for run
        numRuns - number of runs (default=1)
        ignoreDB - don't check the database for this run config
        runMode - Run mode for 'livecmd'
        filterMode - Run mode for 'livecmd'
        verbose - print more details of run transitions

        Return True if the run was started
        """
        raise NotImplementedError()

    @property
    def state(self):
        """Current state of runset"""
        raise NotImplementedError()

    def stopOnSIGINT(self, signal, frame):
        self.__user_stopped = True
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
        if self.__dry_run:
            return True

        # some info can only be obtained from CnCServer
        cnc = self.cncConnection()

        # grab summary info from CnC
        summary = cnc.rpc_run_summary(runNum)

        # calculate duration
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

        # colorize SUCCESS/FAILED
        success = summary["result"].upper() == "SUCCESS"
        if success:
            prefix = ANSIEscapeCode.BG_GREEN + ANSIEscapeCode.FG_BLACK
        else:
            prefix = ANSIEscapeCode.BG_RED + ANSIEscapeCode.FG_BLACK
        suffix = ANSIEscapeCode.OFF

        # get release name
        vinfo = cnc.rpc_version()
        if vinfo is None or not isinstance(vinfo, dict) or \
           "release" not in vinfo:
            relname = "???"
        else:
            relname = vinfo["release"]

        self.logInfo("%sRun %d%s (%s:%s) %s seconds : %s" %
                     (ANSIEscapeCode.INVERTED_ON, summary["num"],
                      ANSIEscapeCode.INVERTED_OFF, relname, summary["config"],
                      duration, prefix + summary["result"] + suffix))

        return success

    def switchRun(self, runNum):
        """Switch to a new run number without stopping any components"""
        raise NotImplementedError()

    def updateDB(self, runCfgName):
        """
        Add this run configuration to the database

        runCfgName - name of run configuration
        """
        if self.__db_type == ClusterDescription.DBTYPE_NONE:
            return

        if self.__update_db_prog is None:
            self.logError("Not updating database with \"%s\"" % runCfgName)
            return

        runCfgPath = os.path.join(self.__config_dir, runCfgName + ".xml")
        self.checkExists("Run configuration", runCfgPath)

        cmd = "%s %s" % (self.__update_db_prog, runCfgPath)
        self.logCmd(cmd)

        if self.__dry_run:
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

            if line.find("Committing ") >= 0 and \
               line.find(" to status collection") > 0:
                continue

            if line.find("No new documents to commit") >= 0:
                continue

            self.logError("UpdateDB: %s" % line)
        proc.stdout.close()

        proc.wait()

    def waitForStopped(self, verbose=False):
        """Wait for the current run to be stopped"""
        raise NotImplementedError()
