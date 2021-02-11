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
#     run_config = "spts64-dirtydozen-hlc-006"
#     numSecs = 60                             # number of seconds
#
#     # an ordinary run
#     run.run(clusterConfig, run_config, numSecs)
#
#     flasher_data = \
#         (("flash-21.xml", 30),               # flash string 21 for 30 seconds
#          (None, 15),                         # wait 15 seconds
#          ("flash-26-27.xml", 120),           # flash 26 & 27 for 2 minutes
#          (None, 20),                         # wait 20 seconds
#          ("flash-21.xml", 30))               # flash string 21 for 30 seconds
#
#     # a flasher run
#     run.run(clusterConfig, run_config, numSecs, flasher_data)

from __future__ import print_function

import os
import re
import subprocess
import time

from BaseRun import BaseRun, RunException, StateException
from DAQConst import DAQPort


class LightModeException(RunException):
    "Problem with the light-in-the-detector mode"


class LiveTimeoutException(RunException):
    "Timeout exception"


class AbstractState(object):
    "Generic class for keeping track of the current state"

    @classmethod
    def get_state(cls, states, state_name):
        """
        Return the numeric value of the named state

        state_name - named state
        """
        try:
            return states.index(state_name)
        except ValueError:
            raise StateException("Unknown state '%s'" % state_name)

    @classmethod
    def state_string(cls, states, state):
        """
        Return the string associated with a numeric state

        state - numeric state value
        """
        if state < 0 or state > len(states):
            raise StateException("Unknown state #%s" % state)
        return states[state]


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

    @classmethod
    def get(cls, state_name):
        """
        Return the numeric value of the named state

        state_name - named state
        """
        return cls.get_state(cls.STATES, state_name)

    @classmethod
    def str(cls, state):
        """
        Return the numeric value of the named state

        state_name - named state
        """
        return cls.state_string(cls.STATES, state)


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

    @classmethod
    def get(cls, state_name):
        """
        Return the numeric value of the named state

        state_name - named state
        """
        return cls.get_state(cls.STATES, state_name)

    @classmethod
    def str(cls, state):
        """
        Return the numeric value of the named state

        state_name - named state
        """
        return cls.state_string(cls.STATES, state)


class LiveService(object):
    "I3Live service instance"

    def __init__(self, name, host, port, is_async, state, num_starts):
        """
        I3Live service data (as extracted from 'livecmd check')

        name - service name
        host - name of machine on which the service is running
        port - socket port address for this service
        is_async - True if this is an asynchronous service
        state - current service state string
        num_starts - number of times this service has been started
        """
        self.__name = name
        self.__host = host
        self.__port = port
        self.__is_async = is_async
        self.__state = LiveRunState.get(state)
        self.__num_starts = num_starts

    @property
    def num_starts(self):
        return self.__num_starts

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
    ALERT_PAT = re.compile(r"^(\d+): (.*)$")

    PARSE_NORMAL = 1
    PARSE_FLASH = 2
    PARSE_ALERTS = 3
    PARSE_PAGES = 4

    def __init__(self,
                 liveCmd=os.path.join(os.environ["HOME"], "bin", "livecmd"),
                 show_check=False, show_check_output=False, logger=None,
                 dry_run=False):
        """
        Create an I3Live service tracker

        liveCmd - full path of 'livecmd' executable
        show_check - True if 'livecmd check' commands should be printed
        show_check_output - True if 'livecmd check' output should be printed
        logger - specialized run logger
        dry_run - True if commands should only be printed and not executed
        """
        self.__prog = liveCmd
        self.__show_check = show_check
        self.__show_check_output = show_check_output
        self.__logger = logger
        self.__dry_run = dry_run

        self.__thread_state = None
        self.__run_state = LiveRunState.get(LiveRunState.UNKNOWN)
        self.__light_mode = LightMode.UNKNOWN

        self.__run_num = None
        self.__subrun_num = None
        self.__config = None

        self.__svc_dict = {}

        # only complain about unknown pairs once
        self.__complained = {}

    def __str__(self):
        "Return a description of the current I3Live state"
        summary = "Live[%s] Run[%s] Light[%s]" % \
                  (self.__thread_state, LiveRunState.str(self.__run_state),
                   LightMode.str(self.__light_mode))

        for key in list(self.__svc_dict.keys()):
            svc = self.__svc_dict[key]
            summary += " %s[%s*%d]" % (key, LiveRunState.str(svc.state),
                                       svc.num_starts)

        if self.__run_num is not None:
            if self.__subrun_num is not None and self.__subrun_num > 0:
                summary += " run %d/%d" % (self.__run_num, self.__subrun_num)
            else:
                summary += " run %d" % self.__run_num

        return summary

    def __parse_line(self,  # pylint: disable=too-many-return-statements
                     parse_state, line):
        """
        Parse a live of output from 'livecmd check'

        parse_state - current parser state
        line - line to parse

        Returns the new parser state
        """
        if line == "":
            # blank lines shouldn't change parse state
            return parse_state

        if line.find("controlled by LiveControl") > 0 or line == "(None)" or \
                line == "OK":
            return self.PARSE_NORMAL

        if line.startswith("Flashing DOMs"):
            return self.PARSE_FLASH

        if parse_state == self.PARSE_FLASH:
            mtch = self.DOM_PAT.match(line)
            if mtch is not None:
                return self.PARSE_FLASH

        if line.startswith("Ongoing Alerts:"):
            return self.PARSE_ALERTS

        if line.startswith("Ongoing Pages:"):
            return self.PARSE_PAGES

        if parse_state == self.PARSE_ALERTS:
            if line.find("(None)") >= 0:
                return self.PARSE_NORMAL

            match = self.ALERT_PAT.match(line)
            if match is None:
                self.__logger.error("Unrecognized alert: \"%s\"" % (line, ))

            return self.PARSE_ALERTS

        if parse_state == self.PARSE_PAGES:
            if line.find(" PAGE FROM ") >= 0:
                return self.PARSE_PAGES

            match = self.ALERT_PAT.match(line)
            if match is None:
                self.__logger.error("Unrecognized page: \"%s\"" % (line, ))

            return self.PARSE_PAGES

        if line.find(": ") > 0:
            (front, back) = line.split(": ", 1)
            front = front.strip()
            back = back.strip()

            if front in ("DAQ thread", "I3Live DAQ thread"):
                self.__thread_state = back
                return self.PARSE_NORMAL

            if front in ("Run state", "I3Live run state"):
                self.__run_state = LiveRunState.get(back)
                return self.PARSE_NORMAL

            if front == "Current run":
                mtch = self.RUN_PAT.match(line)
                if mtch is not None:
                    self.__run_num = int(mtch.group(1))
                    self.__subrun_num = int(mtch.group(2))
                    return self.PARSE_NORMAL

            if front == "Light mode":
                self.__light_mode = LightMode.get(back)
                return self.PARSE_NORMAL

            if front == "run":
                self.__run_num = int(back)
                return self.PARSE_NORMAL

            if front == "subrun":
                self.__subrun_num = int(back)
                return self.PARSE_NORMAL

            if front == "config":
                self.__config = back
                return self.PARSE_NORMAL

            if front.startswith("tstart") or front.startswith("tstop") or \
                 front.startswith("t_valid") or front == "livestart":
                # ignore start/stop times
                return self.PARSE_NORMAL

            if front in ("physicsEvents", "physicsEventsTime",
                         "walltimeEvents", "walltimeEventsTime",
                         "tcalEvents", "moniEvents", "snEvents", "runlength"):
                # ignore rates
                return self.PARSE_NORMAL

            if front in ("Target run stop time", "Currently",
                         "Time since start", "Time until stop",
                         "Next run transition"):
                # ignore run time info
                return self.PARSE_NORMAL

            if front == "daqrelease":
                # ignore DAQ release name
                return self.PARSE_NORMAL

            if front == "Run starts":
                # ignore run start/switch info
                return self.PARSE_NORMAL

            if front == "Flashing state":
                # ignore flashing state
                return self.PARSE_NORMAL

            if front == "check failed" and back.find("timed out") >= 0:
                self.__logger.error("I3Live may have died" +
                                    " (livecmd check returned '%s')" %
                                    line.rstrip())
                return self.PARSE_NORMAL

            if front in ("Run mode", "Filter mode"):
                # ignore run/filter mode info
                return self.PARSE_NORMAL

            if front not in self.__complained:
                self.__logger.error("Unknown livecmd pair: \"%s\"/\"%s\"" %
                                    (front, back))
                self.__complained[front] = 1
                return self.PARSE_NORMAL

        mtch = self.SVC_PAT.match(line)
        if mtch is not None:
            name = mtch.group(1)
            host = mtch.group(2)
            port = int(mtch.group(4))
            is_async = mtch.group(5) == "async"
            back = mtch.group(6)

            state = LiveRunState.UNKNOWN
            num_starts = 0

            if back == "DIED!":
                state = LiveRunState.DEAD
            else:
                mtch = self.SVCBACK_PAT.match(back)
                if mtch is not None:
                    state = mtch.group(1)
                    num_starts = int(mtch.group(2))

            svc = LiveService(name, host, port, is_async, state, num_starts)
            self.__svc_dict[name] = svc
            return self.PARSE_NORMAL

        self.__logger.error("Unknown livecmd line: %s" % line)
        return self.PARSE_NORMAL

    def log_command(self, msg):
        if self.__show_check:
            self.__logger.info("% " + msg)

    def log_command_output(self, msg):
        if self.__show_check_output:
            self.__logger.info("%%% " + msg)

    def check(self):
        "Check the current I3Live service states"

        cmd = "livecmd check --nolog"
        if self.__show_check:
            self.log_command(cmd)

        if self.__dry_run:
            print(cmd)
            return

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        parse_state = self.PARSE_NORMAL
        for line in proc.stdout:
            line = line.rstrip()
            if self.__show_check_output:
                self.log_command_output(line)

            parse_state = self.__parse_line(parse_state, line)
        proc.stdout.close()

        proc.wait()

    @property
    def light_mode(self):
        "Return the light mode from the most recent check()"
        return LightMode.str(self.__light_mode)

    @property
    def run_number(self):
        "Return the pDAQ run number from the most recent check()"
        if self.__run_num is None:
            return 0
        return self.__run_num

    @property
    def run_state(self):
        "Return the pDAQ run state from the most recent check()"
        return LiveRunState.str(self.__run_state)

    def svc_state(self, svc_name):
        """
        Return the state string for the specified service
        from the most recent check()
        """
        if svc_name not in self.__svc_dict:
            return LiveRunState.UNKNOWN
        return LiveRunState.str(self.__svc_dict[svc_name].state)


class LiveRun(BaseRun):
    "Manage one or more pDAQ runs through IceCube Live"

    def __init__(self, show_commands=False, show_command_output=False,
                 show_check=False, show_check_output=False, dry_run=False,
                 logfile=None):
        """
        show_commands - True if commands should be printed before being run
        show_command_output - True if command output should be printed
        show_check - True if 'livecmd check' commands should be printed
        show_check_output - True if 'livecmd check' output should be printed
        dry_run - True if commands should only be printed and not executed
        logfile - file where all log messages are saved
        """

        super(LiveRun, self).__init__(show_commands=show_commands,
                                      show_command_output=show_command_output,
                                      dry_run=dry_run, logfile=logfile)

        self.__dry_run = dry_run

        # used during dry runs to simulate the run number
        self.__fake_run_num = 12345

        # check for needed executables
        #
        self.__livecmd_path = self.find_executable("I3Live program", "livecmd",
                                                   self.__dry_run)

        # build state-checker
        #
        self.__state = LiveState(self.__livecmd_path, show_check=show_check,
                                 show_check_output=show_check_output,
                                 logger=self.logger(), dry_run=self.__dry_run)

    def __control_pdaq(self, wait_secs, attempts=3):
        """
        Connect I3Live to pDAQ

        Return True if I3Live controls pDAQ
        """

        cmd = "%s control pdaq localhost:%s" % \
            (self.__livecmd_path, DAQPort.DAQLIVE)
        self.log_command(cmd)

        if self.__dry_run:
            print(cmd)
            return True

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        controlled = False
        for line in proc.stdout:
            line = line.rstrip()
            self.log_command_output(line)

            if line == "Service pdaq is now being controlled" or \
                    line.find("Synchronous service pdaq was already being" +
                              " controlled") >= 0:
                controlled = True
            elif line.find("Service pdaq was unreachable on ") >= 0:
                pass
            else:
                self.log_error("Control: %s" % line)
        proc.stdout.close()

        proc.wait()

        if controlled or wait_secs < 0:
            return controlled

        if attempts <= 0:
            return False

        time.sleep(wait_secs)
        return self.__control_pdaq(0, attempts=attempts - 1)

    def __refresh(self):
        self.__state.check()
        if self.__state.svc_state("pdaq") == LiveRunState.UNKNOWN:
            if not self.__control_pdaq(10):
                raise StateException("Could not tell I3Live to control pdaq")
            self.__state.check()

    def __run_basic_command(self, name, cmd):
        """
        Run a basic I3Live command

        name - description of this command (used in error messages)
        path - I3Live command which responds with "OK" or an error

        Return True if there was a problem
        """
        self.log_command(cmd)

        if self.__dry_run:
            print(cmd)
            return True

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        problem = False
        for line in proc.stdout:
            line = line.rstrip()
            self.log_command_output(line)

            if line != "OK":
                problem = True
            if problem:
                self.log_error("%s: %s" % (name, line))
        proc.stdout.close()

        proc.wait()

        return not problem

    def __wait_for_state(self, init_states, exp_state, num_tries, num_errors=0,
                         wait_secs=10, verbose=False):
        """
        Wait for the specified state

        init_states - list of possible initial detector states
        exp_state - expected final state
        num_tries - number of tries before ceasing to wait
        num_errors - number of ERROR states allowed before assuming
                    there is a problem
        wait_secs - number of seconds to wait on each "try"
        """
        prev_state = self.state
        cur_state = prev_state

        if verbose and prev_state != exp_state:
            self.log_info("Changing from %s to %s" % (prev_state, exp_state))

        start_time = time.time()
        for _ in range(num_tries):
            self.__state.check()

            cur_state = self.state
            if cur_state != prev_state:
                if verbose:
                    switch_time = int(time.time() - start_time)
                    self.log_info("Changed from %s to %s in %s secs" %
                                  (prev_state, cur_state, switch_time))

                prev_state = cur_state
                start_time = time.time()

            if cur_state == exp_state:
                break

            if num_errors > 0 and cur_state == LiveRunState.ERROR:
                time.sleep(5)
                num_errors -= 1
                continue

            if cur_state not in init_states and \
               cur_state != LiveRunState.RECOVERING:
                raise StateException(("I3Live state should be %s or" +
                                      " RECOVERING, not %s") %
                                     (", ".join(init_states), cur_state))

            time.sleep(wait_secs)

        if cur_state != exp_state:
            tot_time = int(time.time() - start_time)
            raise StateException(("I3Live state should be %s, not %s" +
                                  " (waited %d secs)") %
                                 (exp_state, cur_state, tot_time))

        return True

    def final_cleanup(self):
        """Do final cleanup before exiting"""
        return

    def flash(self, filename, secs):
        """
        Start flashers for the specified duration with the specified data file
        """
        problem = False
        if filename is None or filename == "sleep":
            if self.__dry_run:
                print("sleep %d" % secs)
            else:
                time.sleep(secs)
        else:
            cmd = "%s flasher -d %ds -f %s" % (self.__livecmd_path,
                                               secs, filename)
            self.log_command(cmd)

            if self.__dry_run:
                print(cmd)
                return False

            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, close_fds=True,
                                    shell=True)
            proc.stdin.close()

            for line in proc.stdout:
                line = line.rstrip()
                self.log_command_output(line)

                if line != "OK" and not line.startswith("Starting subrun"):
                    problem = True
                if problem:
                    self.log_error("Flasher: %s" % line)
            proc.stdout.close()

            proc.wait()

        return problem

    @property
    def last_run_numbers(self):
        "Return the last used run and subrun numbers as a tuple"
        cmd = "%s lastrun" % self.__livecmd_path
        self.log_command(cmd)

        if self.__dry_run:
            print(cmd)
            run_number = self.__fake_run_num
            self.__fake_run_num += 1
            return (run_number, 0)

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        num = None
        for line in proc.stdout:
            line = line.rstrip()
            self.log_command_output(line)

            try:
                num = int(line)
            except ValueError:
                if line.find("timed out") >= 0:
                    raise LiveTimeoutException("I3Live seems to have died")

        proc.stdout.close()

        proc.wait()

        return (num, 0)

    @property
    def run_number(self):
        "Return the current run number"
        if self.__dry_run:
            return self.__fake_run_num

        self.__refresh()
        return self.__state.run_number

    @property
    def runs_per_restart(self):
        """Get the number of continuous runs between restarts"""
        cmd = "livecmd runs-per-restart"
        self.log_command(cmd)

        if self.__dry_run:
            print(cmd)
            return 1

        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()

        cur_num = None
        for line in proc.stdout:
            line = line.rstrip()
            self.log_command_output(line)
            try:
                cur_num = int(line)
            except ValueError:
                raise SystemExit("Bad number '%s' for runs per restart" % line)

        proc.stdout.close()
        proc.wait()

        return cur_num

    def is_dead(self, refresh=False):
        if refresh:
            self.__refresh()

        return self.__state.run_state == LiveRunState.DEAD

    def is_recovering(self, refresh=False):
        if refresh:
            self.__refresh()

        return self.__state.run_state == LiveRunState.RECOVERING

    def is_running(self, refresh=False):
        if refresh:
            self.__refresh()

        return self.__state.run_state == LiveRunState.RUNNING

    def is_stopped(self, refresh=False):
        if refresh:
            self.__refresh()

        return self.__state.run_state == LiveRunState.STOPPED

    def is_stopping(self, refresh=False):
        if refresh:
            self.__refresh()

        return self.__state.run_state == LiveRunState.STOPPING

    def is_switching(self, refresh=False):
        if refresh:
            self.__refresh()

        return self.__state.run_state == LiveRunState.SWITCHRUN

    def set_light_mode(self, is_lid):
        """
        Set the I3Live LID mode

        is_lid - True for LID mode, False for dark mode

        Return True if the light mode was set successfully
        """
        if is_lid:
            exp_mode = LightMode.LID
        else:
            exp_mode = LightMode.DARK

        self.__state.check()
        if not self.__dry_run and self.__state.light_mode == exp_mode:
            return True

        if self.__dry_run or self.__state.light_mode == LightMode.LID or \
                self.__state.light_mode == LightMode.DARK:
            # mode isn't in transition, so start transitioning
            #
            cmd = "%s lightmode %s" % (self.__livecmd_path, exp_mode)
            if not self.__run_basic_command("LightMode", cmd):
                return False

        wait_secs = 10
        num_tries = 10

        for _ in range(num_tries):
            self.__state.check()
            if self.__dry_run or self.__state.light_mode == exp_mode:
                break

            if not self.__state.light_mode.startswith("changingTo"):
                raise LightModeException("I3Live lightMode should not be %s" %
                                         self.__state.light_mode)

            time.sleep(wait_secs)

        if not self.__dry_run and self.__state.light_mode != exp_mode:
            raise LightModeException("I3Live lightMode should be %s, not %s" %
                                     (exp_mode, self.__state.light_mode))

        return True

    def set_runs_per_restart(self, num):
        """Set the number of continuous runs between restarts"""
        cur_num = self.runs_per_restart
        if cur_num == num:
            return

        cmd = "livecmd runs-per-restart %d" % (subcmd, num)
        self.log_command(cmd)

        if self.__dry_run:
            print(cmd)
            return

        print("Setting runs per restart to %d" % int(num))
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()
        for line in proc.stdout:
            line = line.rstrip()
            self.log_command_output(line)
        proc.stdout.close()
        proc.wait()

    def start_run(self, run_cfg_name, duration, num_runs=1, ignore_db=False,
                  run_mode=None, filter_mode=None, extended_mode=False,
                  verbose=False):
        """
        Tell I3Live to start a run

        run_cfg_name - run configuration file name
        duration - number of seconds for run
        num_runs - number of runs (default=1)
        ignore_db - tell I3Live to not check the database for this run config
        run_mode - Run mode for 'livecmd'
        filter_mode - Run mode for 'livecmd'
        extended_mode - True if DOMs should be put into "extended" mode
        verbose - print more details of run transitions

        Return True if the run was started
        """
        if not self.__dry_run and not self.is_stopped(True):
            return False

        args = ""
        if ignore_db or self.ignore_database:
            args += " -i"
        if run_mode is not None:
            args += " -r %s" % run_mode
        if filter_mode is not None:
            args += " -p %s" % filter_mode
        if extended_mode:
            args += " -x"

        cmd = "%s start -c %s -n %d -l %ds %s daq" % \
            (self.__livecmd_path, run_cfg_name, num_runs, duration, args)
        if not self.__run_basic_command("StartRun", cmd):
            return False

        if self.__dry_run:
            return True

        if self.__state.run_state == LiveRunState.RUNNING:
            return True

        init_states = (LiveRunState.STOPPED, LiveRunState.STARTING)
        return self.__wait_for_state(init_states, LiveRunState.RUNNING, 60, 0,
                                     verbose=True)

    @property
    def state(self):
        return self.__state.run_state

    def stop_run(self):
        """Stop the run"""
        cmd = "%s stop daq" % self.__livecmd_path
        if not self.__run_basic_command("StopRun", cmd):
            return False

        return True

    def switch_run(self, run_number):
        """Switch to a new run number without stopping any components"""
        return True  # Live handles this automatically

    def wait_for_stopped(self, verbose=False):
        init_states = (self.__state.run_state, LiveRunState.STOPPING)
        return self.__wait_for_state(init_states, LiveRunState.STOPPED,
                                     60, 0, verbose=verbose)


def main():
    "Main program"

    run = LiveRun(show_commands=True, show_command_output=True, dry_run=False)
    run.run("spts64-real-21-29", "spts64-dirtydozen-hlc-006", 60,
            (("flash-21.xml", 10), (None, 10), ("flash-21.xml", 5)),
            verbose=True)


if __name__ == "__main__":
    main()
