#!/usr/bin/env python
#
# Base class for managing pDAQ runs

from __future__ import print_function

import os
import re
import socket
import subprocess
import sys
import threading
import time
try:
    from xmlrpclib import Fault
except:  # ModuleNotFoundError only works under 2.7/3.0
    from xmlrpc.client import Fault

from ANSIEscapeCode import ANSIEscapeCode
from ComponentManager import ComponentManager
from DAQConfig import DAQConfigException, DAQConfigParser
from DAQConst import DAQPort
from DAQRPC import RPCClient
from DAQTime import PayloadTime
from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from utils.Machineid import Machineid

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


class RunException(Exception):
    "General exception"


class FlashFileException(RunException):
    "Problem with a flasher file"


class LaunchException(RunException):
    "Problem while launching components"


class StateException(RunException):
    "Bad component state"


class FlasherThread(threading.Thread):
    "Thread which starts and stops flashers during a run"

    def __init__(self, run, dataPairs, initial_delay=120, dry_run=False):
        """
        Create a flasher thread (which has not been started)

        run - BaseRun object
        dataPairs - pairs of XML_file_name/duration
        """

        super(FlasherThread, self).__init__(name="FlasherThread")
        self.setDaemon(True)

        self.__run = run
        self.__data_pairs = dataPairs
        self.__initial_delay = initial_delay
        self.__dry_run = dry_run

        self.__sem = threading.BoundedSemaphore()

        self.__running = False

    @staticmethod
    def compute_run_duration(flasher_data, initial_delay):
        """
        Compute the number of seconds needed for this flasher run

        flasher_data - list of XML_file_name/duration pairs
        """
        if initial_delay is None:
            tot = 0
        else:
            tot = initial_delay

        for pair in flasher_data:
            tot += pair[1] + 10

        return tot

    def run(self):
        "Body of the flasher thread"
        with self.__sem:
            self.__running = True

            self.__run_body()
            self.__running = False

        try:
            self.__run.stop_run()
        except:  # pylint: disable=bare-except
            pass

    def __run_body(self):
        "Run the flasher sequences"
        if self.__initial_delay is not None and self.__initial_delay > 0:
            cmd = "sleep %d" % self.__initial_delay
            self.__run.log_command(cmd)

            if self.__dry_run:
                print(cmd)
            else:
                time.sleep(self.__initial_delay)

        for pair in self.__data_pairs:
            if not self.__running:
                break

            problem = self.__run.flash(pair[0], pair[1])

            if problem or not self.__running:
                break

    def stop_thread(self):
        "Stop the flasher thread"
        self.__running = False

    def wait_for_thread(self):
        "Wait for the thread to complete"

        # acquire the semaphore (which the thread will hold until finished)
        #
        self.__sem.acquire()

        # thread must be done now, release the semaphore and return
        #
        self.__sem.release()


class FlasherScript(object):
    """
    Read in a flasher script, producing a list of XML_file_name/duration pairs.
    """

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
    def __get_duration_from_string(cls, dstr):
        """
        Return duration in seconds based on string <s>
        """
        mtch = re.search(r'^(\d+)$', dstr)
        if mtch is not None:
            return int(mtch.group(1))
        mtch = re.search(r'^(\d+)s(?:ec(?:s)?)?$', dstr)
        if mtch is not None:
            return int(mtch.group(1))
        mtch = re.search(r'^(\d+)m(?:in(?:s)?)?$', dstr)
        if mtch is not None:
            return int(mtch.group(1)) * 60
        mtch = re.search(r'^(\d+)h(?:r(?:s)?)?$', dstr)
        if mtch is not None:
            return int(mtch.group(1)) * 3600
        mtch = re.search(r'^(\d+)d(?:ay(?:s)?)?$', dstr)
        if mtch is not None:
            return int(mtch.group(1)) * 86400
        raise FlashFileException(('String "%s" is not a known duration'
                                  ' format. Try 30sec, 10min, 2days etc.') %
                                 str(dstr))

    @classmethod
    def __is_quote(cls, char):
        """Is this character a quote mark?"""
        return char in ("'", '"')

    @classmethod
    def __parse_flasher_options(cls, options, basedir=None):
        """
        Parse 'livecmd flasher' options
        """
        pairs = []
        i = 0
        dur = None
        fil = None
        while i < len(options):
            if options[i] == "-d":
                if dur is not None:
                    raise FlashFileException("Found multiple durations")

                i += 1
                dur = cls.__get_duration_from_string(options[i])
                if fil is not None:
                    pairs.append((fil, dur))
                    dur = None
                    fil = None

            elif options[i] == "-f":
                if fil is not None:
                    raise FlashFileException("Found multiple filenames")

                i += 1
                fil = cls.find_data_file(options[i], basedir=basedir)
                if dur is not None:
                    pairs.append((fil, dur))
                    dur = None
                    fil = None
            else:
                raise FlashFileException("Bad flasher option \"%s\"" %
                                         options[i])

            i += 1
        return pairs

    @classmethod
    def find_data_file(cls, flash_file, basedir=None):
        """
        Find a flasher file or raise FlashFileException

        flash_file - name of flasher sequence file
        basedir - base directory where data files are located

        Returns full path for flasher sequence file

        NOTE: Currently, only $PDAQ_HOME/src/test/resources is checked
        """

        if os.path.exists(flash_file):
            return flash_file

        path = cls.__find_flasher_data_file(basedir, flash_file)
        if path is not None:
            return path

        raise FlashFileException("Flash file '%s' not found" % flash_file)

    @classmethod
    def parse(cls, path):
        """
        Parse a flasher script, producing a list of XML_file_name/duration
        pairs.
        """
        if not os.path.isfile(path):
            print("Flasher file \"%s\" does not exist" % path)
            return None

        basedir = os.path.dirname(path)
        with open(path, "r") as fin:
            flasher_data = []
            full_line = None
            linenum = 0
            failed = False
            for line in fin:
                line = line.rstrip()

                # if continued line, glue this onto the previous line
                #
                if full_line is None:
                    full_line = line
                else:
                    full_line += line

                #  strip continuation character and wait for rest of line
                #
                if full_line.endswith("\\") and full_line.find("#") < 0:
                    full_line = full_line[:-1]
                    continue

                # strip comments
                #
                comment = full_line.find("#")
                if comment >= 0:
                    full_line = full_line[:comment].rstrip()

                # ignore blank lines
                #
                if full_line == "":
                    full_line = None
                    continue

                # break it into pieces
                words = full_line.split(" ")

                # handle 'livecmd flasher ...'
                #
                if len(words) > 2 and words[0] == "livecmd" and \
                   words[1] == "flasher":
                    flasher_data \
                      += cls.__parse_flasher_options(words[2:],
                                                     basedir=basedir)
                    full_line = None
                    continue

                # handle 'sleep ###'
                #
                if len(words) == 2 and words[0] == "sleep":
                    try:
                        flasher_data.append((None, int(words[1])))
                    except:  # pylint: disable=bare-except
                        print("Bad flasher line#%d: %s (bad sleep time)" %
                              (linenum, full_line))
                        failed = True
                    full_line = None
                    continue

                if len(words) == 2:
                    # found 'file duration'
                    name = cls.__clean_string(words[0])
                    dur_str = cls.__clean_string(words[1])
                else:
                    words = full_line.split(",")
                    wordlen = len(words)
                    if wordlen == 2:  # pylint: disable=len-as-condition
                        # found 'file,duration'
                        name = cls.__clean_string(words[0])
                        dur_str = cls.__clean_string(words[1])
                    elif wordlen == 3 and words[0] == "":
                        # found ',file,duration'
                        name = cls.__clean_string(words[1])
                        dur_str = cls.__clean_string(words[2])
                    else:
                        print("Bad flasher line#%d: %s" % (linenum, line))
                        failed = True
                        full_line = None
                        continue

                try:
                    duration = int(dur_str)
                except ValueError:
                    # hmm, maybe the duration is first
                    try:
                        duration = int(name)
                        name = dur_str
                    except ValueError:
                        print("Bad flasher line#%d: %s" % (linenum, line))
                        failed = True
                        full_line = None
                        continue

                flasher_data.append((os.path.join(basedir, name), duration))
                full_line = None
                continue

        if failed:
            return None

        return flasher_data


class Run(object):
    def __init__(self, mgr, cluster_cfg_name, run_cfg_name, config_dir=None,
                 cluster_desc=None, flasher_data=None, dry_run=False):
        """
        Manage a single run

        mgr - run manager
        cluster_cfg_name - name of cluster configuration
        run_cfg_name - name of run configuration
        flasher_data - list of flasher XML_file_name/duration pairs
        dry_run - True if commands should only be printed and not executed
        """
        self.__mgr = mgr
        self.__run_cfg_name = run_cfg_name
        self.__flasher_data = flasher_data
        self.__dry_run = dry_run

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

        active_cfg_name = self.__mgr.active_cluster_config()
        if cluster_cfg_name is None:
            cluster_cfg_name = active_cfg_name
            if cluster_cfg_name is None:
                cluster_cfg_name = run_cfg_name
                if cluster_cfg_name is None:
                    raise RunException("No cluster configuration specified")

        # Run configuration name has to be non-null as well
        # or we'll get an exception
        if self.__run_cfg_name is None:
            raise RunException("No Run Configuration Specified")

        # if pDAQ isn't active or if we need a different cluster config,
        #   kill the current components
        #
        if active_cfg_name is None or active_cfg_name != cluster_cfg_name:
            self.__mgr.kill_components(dry_run=self.__dry_run)
            self.__run_killed = True

        try:
            self.__cluster_cfg \
                = DAQConfigParser.get_cluster_configuration\
                (cluster_cfg_name, use_active_config=False,
                 cluster_desc=cluster_desc, config_dir=config_dir,
                 validate=False)
        except DAQConfigException:
            raise LaunchException("Cannot load configuration \"%s\": %s" %
                                  (cluster_cfg_name, exc_string()))

        # if necessary, launch the desired cluster configuration
        #
        if self.__run_killed or self.__mgr.is_dead():
            self.__mgr.launch(self.__cluster_cfg)

    def finish(self, verbose=False):
        "clean up after run has ended"
        if not self.__mgr.is_stopped(True):
            self.__mgr.stop_run()

        if not self.__dry_run and not self.__mgr.is_stopped(True) and \
           not self.__mgr.wait_for_stopped(verbose=verbose):
            raise RunException("Run %d did not stop" % self.__run_num)

        if self.__flash_thread is not None:
            self.__flash_thread.wait_for_thread()

        if self.__light_mode and not self.__mgr.set_light_mode(False):
            raise RunException(("Could not set lightMode to dark after run " +
                                " #%d: %s") %
                               (self.__run_num, self.__run_cfg_name))

        try:
            rtnval = self.__mgr.summarize(self.__run_num)
        except:  # pylint: disable=bare-except
            self.__mgr.log_error("Cannot summarize run %d: %s" %
                                 (self.__run_num, exc_string()))
            rtnval = False

        self.__run_num = 0

        return rtnval

    def start(self, duration, num_runs=1, ignore_db=False, run_mode=None,
              filter_mode=None, flasher_delay=None, verbose=False):
        """
        Start a run

        duration - number of seconds to run
        num_runs - number of sequential runs
        ignore_db - False if the database should be checked for this run config
        run_mode - Run mode for 'livecmd'
        filter_mode - Run mode for 'livecmd'
        flasher_delay - number of seconds to sleep before starting flashers
        verbose - provide additional details of the run
        """
        # write the run configuration to the database
        #
        if not ignore_db:
            self.__mgr.update_db(self.__run_cfg_name)

        # if we'll be flashing, build a thread to start/stop flashers
        #
        self.__light_mode = self.__flasher_data is not None
        if not self.__light_mode:
            self.__flash_thread = None
        else:
            if num_runs > 1:
                raise RunException("Only 1 consecutive flasher run allowed" +
                                   " (%d requested)" % num_runs)

            flash_duration \
              = FlasherThread.compute_run_duration(self.__flasher_data,
                                                   flasher_delay)
            if flash_duration > duration:
                if duration > 0:
                    self.__mgr.log_error("Run length was %d secs, but"
                                         " need %d secs for flashers" %
                                         (duration, flash_duration))
                duration = flash_duration

            if flasher_delay is None:
                self.__flash_thread = FlasherThread(self.__mgr,
                                                    self.__flasher_data,
                                                    dry_run=self.__dry_run)
            else:
                self.__flash_thread = \
                    FlasherThread(self.__mgr, self.__flasher_data,
                                  initial_delay=flasher_delay,
                                  dry_run=self.__dry_run)

        # get the new run number
        #
        run_data = self.__mgr.last_run_numbers
        if run_data is None or run_data[0] is None:
            raise RunException("Cannot find run number!")

        self.__run_num = run_data[0] + 1
        self.__duration = duration
        self.__num_runs = num_runs

        # set the LID mode
        #
        if not self.__mgr.set_light_mode(self.__light_mode):
            raise RunException("Could not set lightMode for run #%d: %s" %
                               (self.__run_num, self.__run_cfg_name))

        # start the run
        #
        if not self.__mgr.start_run(self.__run_cfg_name, duration, num_runs,
                                    ignore_db, run_mode=run_mode,
                                    filter_mode=filter_mode, verbose=verbose):
            raise RunException("Could not start run #%d: %s" %
                               (self.__run_num, self.__run_cfg_name))

        # make sure we've got the correct run number
        #
        cur_num = self.__mgr.run_number
        if cur_num != self.__run_num:
            self.__mgr.log_error("Expected run number %d, but actual number"
                                 " is %s" % (self.__run_num, cur_num))
            self.__run_num = cur_num

        # print run info
        #
        if self.__flash_thread is None:
            run_type = "run"
        else:
            run_type = "flasher run"

        self.__mgr.logger().info("Started %s %d (%d secs) %s" %
                                 (run_type, self.__run_num, duration,
                                  self.__run_cfg_name))

        # start flashing
        #
        if self.__flash_thread is not None:
            self.__flash_thread.start()

    def stop(self):
        "stop run"
        self.__mgr.stop()

    def wait(self):
        "wait for run to finish"

        if self.__dry_run:
            return

        logger = self.__mgr.logger()

        # wake up every 'wait_secs' seconds to check run state
        #
        wait_secs = 10
        if wait_secs > self.__duration:
            wait_secs = self.__duration

        num_tries = self.__duration / wait_secs
        num_waits = 0

        runs = 1
        while True:
            if not self.__mgr.is_running():
                run_time = num_waits * wait_secs
                if run_time < self.__duration:
                    logger.error(("WARNING: Expected %d second run, " +
                                  "but run %d ended after %d seconds") %
                                 (self.__duration, self.__run_num, run_time))

                if self.__mgr.is_stopped(False) or \
                        self.__mgr.is_stopping(False) or \
                        self.__mgr.is_recovering(False):
                    break

                if not self.__mgr.is_switching(False):
                    logger.error("Unexpected run %d state %s" %
                                 (self.__run_num, self.__mgr.state))

            num_waits += 1
            if num_waits > num_tries:
                if runs > self.__num_runs:
                    # we've finished all the requested runs
                    break
                if not self.__mgr.switch_run(self.__run_num + 1):
                    logger.error("Failed to switch to run %d" %
                                 (self.__run_num + 1))
                    break

            cur_run_num = self.__mgr.run_number
            while self.__run_num < cur_run_num:
                try:
                    self.__mgr.summarize(self.__run_num)
                except:  # pylint: disable=bare-except
                    import traceback
                    logger.error("Cannot summarize %d:\n%s" %
                                 (self.__run_num, traceback.format_exc()))

                logger.info("Switched from run %d to %d" %
                            (self.__run_num, cur_run_num))

                run_time = num_waits * wait_secs
                if run_time < self.__duration:
                    logger.error(("WARNING: Expected %d second run, " +
                                  "but run %d ended after %d seconds") %
                                 (self.__duration, self.__run_num, run_time))

                # reset number of waits
                num_waits = 1

                # increment number of runs and update run number
                runs += 1
                self.__run_num += 1

            if runs > self.__num_runs:
                plural = "" if self.__num_runs == 1 else "s"
                logger.error("WARNING: Expected %dx%d second run%s but"
                             " run#%d is active" %
                             (self.__num_runs, self.__duration, plural,
                              cur_run_num))
                break

            time.sleep(wait_secs)


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
        print(time.strftime("%Y-%m-%d %H:%M:%S") + " " + sep + " " + msg,
              file=self.__fd)

    def error(self, msg):
        print("!! %s" % (msg, ), file=sys.stderr)
        if self.__fd is not None:
            self.__logmsg("[ERROR]", msg)

    def info(self, msg):
        print(" " + msg)
        if self.__fd is not None:
            self.__logmsg("[INFO]", msg)


class BaseRun(object):
    """User's PATH, used by find_executable()"""
    PATH = None

    def __init__(self, show_commands=False, show_command_output=False,
                 dry_run=False, logfile=None):
        """
        show_commands - True if commands should be printed before being run
        show_command_output - True if command output should be printed
        dry_run - True if commands should only be printed and not executed
        logfile - file where all log messages are saved
        """
        self.__show_commands = show_commands
        self.__show_command_output = show_command_output
        self.__dry_run = dry_run
        self.__user_stopped = False

        self.__logger = RunLogger(logfile)

        self.__cnc = None

        mid = Machineid()
        self.__update_db = mid.is_sps_cluster or mid.is_spts_cluster

        # check for needed executables
        #
        self.__update_db_prog = \
            os.path.join(os.environ["HOME"], "gcd-update", "config-update.sh")
        if not self.__check_exists("GCD update", self.__update_db_prog, False):
            self.__update_db_prog = None

        # make sure run-config directory exists
        #
        self.__config_dir = find_pdaq_config()
        if not os.path.isdir(self.__config_dir):
            raise SystemExit("Run config directory '%s' does not exist" %
                             self.__config_dir)

    @staticmethod
    def __check_exists(name, path, fatal=True):
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

    def final_cleanup(self):
        """Do final cleanup before exiting"""
        raise NotImplementedError()

    def create_run(self, cluster_cfg_name, run_cfg_name, cluster_desc=None,
                   flasher_data=None):
        return Run(self, cluster_cfg_name, run_cfg_name, self.__config_dir,
                   cluster_desc=cluster_desc, flasher_data=flasher_data,
                   dry_run=self.__dry_run)

    @classmethod
    def find_executable(cls, name, cmd, dry_run=False):
        """Find 'cmd' in the user's PATH"""
        if cls.PATH is None:
            cls.PATH = os.environ["PATH"].split(":")
        for pdir in cls.PATH:
            pcmd = os.path.join(pdir, cmd)
            if os.path.exists(pcmd):
                return pcmd
        if dry_run:
            return cmd
        raise SystemExit("%s '%s' does not exist" % (name, cmd))

    def flash(self, filename, secs):
        """Start flashers with the specified data for the specified duration"""
        raise NotImplementedError()

    @staticmethod
    def active_cluster_config():
        "Return the name of the current pDAQ cluster configuration"
        cluster_file = os.path.join(os.environ["HOME"], ".active")
        try:
            with open(cluster_file, 'r') as fin:
                ret = fin.readline()
                return ret.rstrip('\r\n')
        except:  # pylint: disable=bare-except
            return None

    def cnc_connection(self, abort_on_fail=True):
        if self.__cnc is None:
            self.__cnc = RPCClient("localhost", DAQPort.CNCSERVER)
            try:
                self.__cnc.rpc_ping()
            except socket.error as err:
                if err[0] == 61 or err[0] == 111:
                    self.__cnc = None
                else:
                    raise

        if self.__cnc is None and abort_on_fail:
            raise RunException("Cannot connect to CnCServer")

        return self.__cnc

    @property
    def last_run_numbers(self):
        "Return the last used run and subrun numbers as a tuple"
        raise NotImplementedError()

    @property
    def run_number(self):
        "Return the current run number"
        raise NotImplementedError()

    @property
    def ignore_database(self):
        "Return True if run database should not be updated"
        return not self.__update_db

    def is_dead(self, refresh=False):
        raise NotImplementedError()

    def is_recovering(self, refresh=False):
        raise NotImplementedError()

    def is_running(self, refresh=False):
        raise NotImplementedError()

    def is_stopped(self, refresh=False):
        raise NotImplementedError()

    def is_stopping(self, refresh=False):
        raise NotImplementedError()

    def is_switching(self, refresh=False):
        raise NotImplementedError()

    def kill_components(self, dry_run=False):
        "Kill all pDAQ components"
        cfg_dir = find_pdaq_config()

        comps = ComponentManager.get_active_components(None,
                                                       config_dir=cfg_dir,
                                                       validate=False)

        verbose = False

        if comps is not None:
            ComponentManager.kill(comps, verbose=verbose, dry_run=dry_run,
                                  logger=self.__logger)

    def launch(self, cluster_cfg):
        """
        (Re)launch pDAQ with the specified cluster configuration

        cluster_cfg - cluster configuration
        """
        if not self.__dry_run and self.is_running():
            raise LaunchException("There is at least one active run")

        spade_dir = cluster_cfg.log_dir_for_spade
        copy_dir = cluster_cfg.log_dir_copies
        log_dir = cluster_cfg.daq_log_dir
        daq_data_dir = cluster_cfg.daq_data_dir

        cfg_dir = find_pdaq_config()
        meta_dir = find_pdaq_trunk()
        dash_dir = os.path.join(meta_dir, "dash")
        log_dir_fallback = os.path.join(meta_dir, "log")

        do_cnc = True
        verbose = False
        event_check = True

        log_port = None
        live_port = DAQPort.I3LIVE_ZMQ

        self.log_command("Launch %s" % cluster_cfg)
        ComponentManager.launch(do_cnc, dry_run=self.__dry_run,
                                verbose=verbose, cluster_config=cluster_cfg,
                                dash_dir=dash_dir, config_dir=cfg_dir,
                                daq_data_dir=daq_data_dir, log_dir=log_dir,
                                log_dir_fallback=log_dir_fallback,
                                spade_dir=spade_dir, copy_dir=copy_dir,
                                log_port=log_port, live_port=live_port,
                                event_check=event_check,
                                logger=self.__logger)

        # give components a chance to start
        time.sleep(5)

    def log_command(self, msg):
        if self.__show_commands:
            self.__logger.info("% " + msg)

    def log_command_output(self, msg):
        if self.__show_command_output:
            self.__logger.info("%%% " + msg)

    def log_error(self, msg):
        self.__logger.error(msg)

    def log_info(self, msg):
        self.__logger.info(msg)

    def logger(self):
        return self.__logger

    def run(self, cluster_cfg_name, run_cfg_name, duration, num_runs=1,
            flasher_data=None, flasher_delay=None, cluster_desc=None,
            ignore_db=False, run_mode="TestData", filter_mode=None,
            verbose=False):
        """
        Manage a set of runs

        cluster_cfg_name - cluster configuration
        run_cfg_name - name of run configuration
        duration - number of seconds to run
        num_runs - number of consecutive runs
        flasher_data - pairs of (XML file name, duration)
        flasher_delay - number of seconds to sleep before starting flashers
        ignore_db - False if the database should be checked for this run config
        run_mode - Run mode for 'livecmd'
        filter_mode - Run mode for 'livecmd'
        verbose - provide additional details of the run
        """

        if self.__user_stopped:
            return False

        if num_runs > 1:
            self.set_runs_per_restart(num_runs)
        else:
            self.set_runs_per_restart(1)

        run = self.create_run(cluster_cfg_name, run_cfg_name,
                              cluster_desc=cluster_desc,
                              flasher_data=flasher_data)

        if filter_mode is None and flasher_data is not None:
            filter_mode = "RandomFiltering"

        run.start(duration, num_runs=num_runs, ignore_db=ignore_db,
                  run_mode=run_mode, filter_mode=filter_mode,
                  flasher_delay=flasher_delay, verbose=verbose)

        try:
            run.wait()
        except:  # pylint: disable=bare-except
            import traceback
            traceback.print_exc()

        return run.finish(verbose=verbose)

    def set_light_mode(self, is_lid):
        """
        Set the Light-In-Detector mode

        is_lid - True for light-in-detector mode, False for dark mode

        Return True if the light mode was set successfully
        """
        raise NotImplementedError()

    def set_runs_per_restart(self, num):
        """Set the number of continuous runs between restarts"""
        raise NotImplementedError()

    def start_run(self, run_cfg_name, duration, num_runs=1, ignore_db=False,
                  run_mode=None, filter_mode=None, verbose=False):
        """
        Start a run

        run_cfg_name - run configuration file name
        duration - number of seconds for run
        num_runs - number of runs (default=1)
        ignore_db - don't check the database for this run config
        run_mode - Run mode for 'livecmd'
        filter_mode - Run mode for 'livecmd'
        verbose - print more details of run transitions

        Return True if the run was started
        """
        raise NotImplementedError()

    @property
    def state(self):
        """Current state of runset"""
        raise NotImplementedError()

    def stop_on_sigint(self, signal, frame):
        self.__user_stopped = True
        print("Caught signal, stopping run")
        if self.is_running(True):
            self.stop_run()
            self.wait_for_stopped(verbose=True)
        print("Exiting")
        raise SystemExit

    def stop_run(self):
        """Stop the run"""
        raise NotImplementedError()

    def summarize(self, run_number):
        if self.__dry_run:
            return True

        # some info can only be obtained from CnCServer
        cnc = self.cnc_connection()

        # grab summary info from CnC
        for _ in range(10):
            try:
                summary = cnc.rpc_run_summary(run_number)
                break
            except Fault as fault:
                if fault.faultString.find("SummaryNotReady") < 0:
                    raise
                summary = None
                time.sleep(1)

        # calculate duration
        if summary is None:
            raise ValueError("Cannot fetch run summary")

        if summary["startTime"] == "None" or summary["endTime"] == "None":
            duration = "???"
        else:
            try:
                start_time = PayloadTime.from_string(summary["startTime"])
            except:
                raise ValueError("Cannot parse run start time \"%s\": %s" %
                                 (summary["startTime"], exc_string()))
            try:
                end_time = PayloadTime.from_string(summary["endTime"])
            except:
                raise ValueError("Cannot parse run start time \"%s\": %s" %
                                 (summary["startTime"], exc_string()))

            try:
                timediff = end_time - start_time
            except:
                raise ValueError("Cannot get run duration from (%s - %s): %s" %
                                 (end_time, start_time, exc_string()))

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

        self.log_info("%sRun %d%s (%s:%s) %s seconds : %s" %
                      (ANSIEscapeCode.INVERTED_ON, summary["num"],
                       ANSIEscapeCode.INVERTED_OFF, relname, summary["config"],
                       duration, prefix + summary["result"] + suffix))

        return success

    def switch_run(self, run_number):
        """Switch to a new run number without stopping any components"""
        raise NotImplementedError()

    def update_db(self, run_cfg_name):
        """
        Add this run configuration to the database

        run_cfg_name - name of run configuration
        """
        if not self.__update_db:
            return

        if self.__update_db_prog is None:
            self.log_error("Not updating database with \"%s\"" % run_cfg_name)
            return

        run_cfg_path = os.path.join(self.__config_dir, run_cfg_name + ".xml")
        self.__check_exists("Run configuration", run_cfg_path)

        cmd = "%s %s" % (self.__update_db_prog, run_cfg_path)
        self.log_command(cmd)

        if self.__dry_run:
            print(cmd)
            return

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        for line in proc.stdout:
            try:
                line = line.decode()
            except AttributeError:
                pass
            line = line.rstrip()
            self.log_command_output(line)

            if line.find("Committing ") >= 0 and \
               line.find(" to status collection") > 0:
                continue

            if line.find("No new documents to commit") >= 0:
                continue

            self.log_error("UpdateDB: %s" % line)
        proc.stdout.close()

        proc.wait()

    def wait_for_stopped(self, verbose=False):
        """Wait for the current run to be stopped"""
        raise NotImplementedError()
