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

import socket
import subprocess
import time

from xml.dom import minidom, Node

from BaseRun import BaseRun, RunException, StateException
from RunNumber import RunNumber
from RunOption import RunOption
from RunSetState import RunSetState
from exc_string import exc_string
from xmlparser import XMLParser


class FlasherDataException(Exception):
    "General FlasherData exception"


class FlasherDataParser(XMLParser):
    @classmethod
    def __load_flasher_data(cls, data_file):
        """Parse and return data from flasher file"""
        try:
            dom = minidom.parse(data_file)
        except:  # pylint: disable=bare-except
            raise FlasherDataException("Cannot parse \"%s\": %s" %
                                       (data_file, exc_string()))

        fmain = dom.getElementsByTagName("flashers")
        if len(fmain) == 0:  # pylint: disable=len-as-condition
            raise FlasherDataException("File \"%s\" has no <flashers>" %
                                       data_file)
        elif len(fmain) > 1:
            raise FlasherDataException("File \"%s\" has too many <flashers>" %
                                       data_file)

        nodes = fmain[0].getElementsByTagName("flasher")

        flash_list = []
        for node in nodes:
            try:
                flash_list.append(cls.__parse_flasher_node(node))
            except FlasherDataException as fex:
                raise FlasherDataException("File \"%s\": %s" %
                                           (data_file, fex))

        return flash_list

    @classmethod
    def __parse_flasher_node(cls, node):
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
                    hub = int(cls.get_child_text(kid))
                elif kid.nodeName == "domPosition":
                    pos = int(cls.get_child_text(kid))
                elif kid.nodeName == "brightness":
                    bright = int(cls.get_child_text(kid))
                elif kid.nodeName == "window":
                    window = int(cls.get_child_text(kid))
                elif kid.nodeName == "delay":
                    delay = int(cls.get_child_text(kid))
                elif kid.nodeName == "mask":
                    mask = int(cls.get_child_text(kid))
                elif kid.nodeName == "rate":
                    rate = int(cls.get_child_text(kid))

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
    def load(cls, data_file):
        return cls.__load_flasher_data(data_file)


class CnCRun(BaseRun):
    def __init__(self, show_commands=False, show_command_output=False,
                 dry_run=False, logfile=None):
        """
        show_commands - True if commands should be printed before being run
        show_command_output - True if command output should be printed
        dry_run - True if commands should only be printed and not executed
        logfile - file where all log messages are saved
        """

        super(CnCRun, self).__init__(show_commands=show_commands,
                                     show_command_output=show_command_output,
                                     dry_run=dry_run, logfile=logfile)

        self.__show_command_output = show_command_output
        self.__dry_run = dry_run

        # used during dry runs to simulate the runset id
        self.__fake_runset = 1

        self.__runset_id = None
        self.__runcfg = None
        self.__run_number = None

    def __status(self):
        "Print the current DAQ status"

        if not self.__show_command_output or self.__dry_run:
            return

        cmd = "DAQStatus.py"
        self.log_command(cmd)

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

    def __wait_for_state(self, exp_state, num_tries, num_errors=0,
                         wait_secs=10, verbose=False):
        """
        Wait for the specified state

        exp_state - expected final state
        num_tries - number of tries before ceasing to wait
        num_errors - number of ERROR states allowed before assuming
                    there is a problem
        wait_secs - number of seconds to wait on each "try"
        """
        if self.__runset_id is None:
            return False

        if self.__dry_run:
            return True

        self.__status()

        cnc = self.cnc_connection()

        prev_state = cnc.rpc_runset_state(self.__runset_id)
        cur_state = prev_state

        if verbose and prev_state != exp_state:
            self.log_info("Changing from %s to %s" % (prev_state, exp_state))

        start_time = time.time()
        for _ in range(num_tries):
            if cur_state == RunSetState.UNKNOWN:
                break

            cur_state = cnc.rpc_runset_state(self.__runset_id)
            if cur_state != prev_state:
                if verbose:
                    sw_time = int(time.time() - start_time)
                    self.log_info("Changed from %s to %s in %s secs" %
                                  (prev_state, cur_state, sw_time))

                prev_state = cur_state
                start_time = time.time()

            if cur_state == exp_state:
                break

            if num_errors > 0 and cur_state == RunSetState.ERROR:
                time.sleep(5)
                num_errors -= 1
                continue

            if cur_state != RunSetState.RESETTING:
                raise StateException("DAQ state should be RESETTING, not %s" %
                                     cur_state)

            time.sleep(wait_secs)

        if cur_state != exp_state:
            tot_time = int(time.time() - start_time)
            raise StateException(("DAQ state should be %s, not %s" +
                                  " (waited %d secs)") %
                                 (exp_state, cur_state, tot_time))

        return True

    def final_cleanup(self):
        """Do final cleanup before exiting"""
        if self.__runset_id is not None:
            if not self.__dry_run:
                cnc = self.cnc_connection()

            if self.__dry_run:
                print("Break runset#%s" % self.__runset_id)
            else:
                cnc.rpc_runset_break(self.__runset_id)
            self.__runset_id = None

    def flash(self, filename, secs):
        """
        Start flashers for the specified duration with the specified data file
        Return True if there was a problem
        """
        if self.__runset_id is None:
            self.log_error("No active runset!")
            return True

        if not self.__dry_run:
            cnc = self.cnc_connection()

        if filename is not None:
            try:
                data = FlasherDataParser.load(filename)
            except:  # pylint: disable=bare-except
                self.log_error("Cannot flash: " + exc_string())
                return True

            (run_num, subrun) = RunNumber.get_last()
            RunNumber.set_last(run_num, subrun + 1)

            if self.__dry_run:
                print("Flash subrun#%d - %s for %s second" %
                      (subrun, data[0], data[1]))
            else:
                cnc.rpc_runset_subrun(self.__runset_id, subrun, data)

        # XXX should be monitoring run state during this time
        if not self.__dry_run:
            time.sleep(secs)

        if filename is not None:
            subrun += 1
            RunNumber.set_last(data[0], subrun)
            if self.__dry_run:
                print("Flash subrun#%d - turn off flashers" % subrun)
            else:
                cnc.rpc_runset_subrun(self.__runset_id, subrun, [])

        return False

    @property
    def last_run_numbers(self):
        "Return the last used run and subrun numbers as a tuple"
        return RunNumber.get_last()

    @property
    def run_number(self):
        "Return the current run number"
        if self.__runset_id is None:
            return None
        return self.__run_number

    def is_dead(self, refresh=False):
        cnc = self.cnc_connection(False)
        return cnc is None

    def is_recovering(self, refresh=False):
        return False

    def is_running(self, refresh=False):
        cnc = self.cnc_connection(False)
        if self.__runset_id is None:
            return False
        try:
            state = cnc.rpc_runset_state(self.__runset_id)
            return state == RunSetState.RUNNING
        except socket.error:
            return False

    def is_stopped(self, refresh=False):
        cnc = self.cnc_connection(False)
        if cnc is None or self.__runset_id is None:
            return True
        try:
            state = cnc.rpc_runset_state(self.__runset_id)
            return state == RunSetState.READY
        except socket.error:
            return False

    def is_stopping(self, refresh=False):
        cnc = self.cnc_connection(False)
        if cnc is None or self.__runset_id is None:
            return False
        try:
            state = cnc.rpc_runset_state(self.__runset_id)
            return state == RunSetState.STOPPING
        except socket.error:
            return False

    def is_switching(self, refresh=False):
        return False

    def set_light_mode(self, is_lid):
        """
        Set the Light-In-Detector mode

        is_lid - True for light-in-detector mode, False for dark mode

        Return True if the light mode was set successfully
        """
        if is_lid:
            self.log_error("Not setting light mode!!!")
        return True

    def set_runs_per_restart(self, num):
        """Set the number of continuous runs between restarts"""
        return  # for non-Live runs, this is driven by BaseRun.waitForRun()

    def start_run(self, run_cfg_name, duration, num_runs=1, ignore_db=False,
                  run_mode=None, filter_mode=None, extended_mode=False,
                  verbose=False):
        """
        Start a run

        run_cfg_name - run configuration file name
        duration - number of seconds for run
        num_runs - number of runs (default=1)
        ignore_db - don't check the database for this run config
        run_mode - Run mode for 'livecmd'
        filter_mode - Filter mode for 'livecmd'
        extended_mode - True if DOMs should be put into "extended" mode
        verbose - print more details of run transitions

        Return True if the run was started
        """
        if not self.__dry_run:
            cnc = self.cnc_connection()

        if self.__runset_id is not None and self.__runcfg is not None and \
                self.__runcfg != run_cfg_name:
            self.__runcfg = None
            if self.__dry_run:
                print("Break runset #%s" % self.__runset_id)
            else:
                cnc.rpc_runset_break(self.__runset_id)
            self.__runset_id = None

        if self.__runset_id is None:
            if self.__dry_run:
                runset_id = self.__fake_runset
                self.__fake_runset += 1
                print("Make runset #%d" % runset_id)
            else:
                runset_id = cnc.rpc_runset_make(run_cfg_name)
            if runset_id < 0:
                raise RunException("Could not create runset for \"%s\"" %
                                   run_cfg_name)

            self.__runset_id = runset_id
            self.__runcfg = run_cfg_name

        (run_number, _) = RunNumber.get_last()
        self.__run_number = run_number + 1
        RunNumber.set_last(self.__run_number, 0)

        if run_mode is not None:
            if filter_mode is not None:
                self.log_error("Ignoring run mode %s, filter mode %s" %
                               (run_mode, filter_mode))
            else:
                self.log_error("Ignoring run mode %s" % run_mode)
        elif filter_mode is not None:
            self.log_error("Ignoring filter mode %s" % filter_mode)

        run_options = RunOption.LOG_TO_FILE | RunOption.MONI_TO_FILE
        if extended_mode:
            run_options |= RunOption.EXTENDED_MODE

        if self.__dry_run:
            print("Start run#%d with runset#%d" %
                  (self.__run_number, self.__runset_id))
        else:
            cnc.rpc_runset_start_run(self.__runset_id, self.__run_number,
                                     run_options)

        return True

    @property
    def state(self):
        cnc = self.cnc_connection(False)
        if cnc is None:
            return "DEAD"

        if self.__runset_id is None:
            return "STOPPED"

        try:
            state = cnc.rpc_runset_state(self.__runset_id)
        except:  # pylint: disable=bare-except
            return "ERROR"

        return str(state).upper()

    def stop_run(self):
        """Stop the run"""
        if self.__runset_id is None:
            raise RunException("No active run")

        if not self.__dry_run:
            cnc = self.cnc_connection()

        if self.__dry_run:
            print("Stop runset#%s" % self.__runset_id)
        else:
            cnc.rpc_runset_stop_run(self.__runset_id)

    def switch_run(self, run_number):
        """Switch to a new run number without stopping any components"""
        if self.__runset_id is None:
            raise RunException("No active run")

        if not self.__dry_run:
            cnc = self.cnc_connection()

        if self.__dry_run:
            print("Switch runset#%s to run#%d" %
                  (self.__runset_id, run_number))
        else:
            cnc.rpc_runset_switch_run(self.__runset_id, run_number)
        self.__run_number = run_number

        return True

    def wait_for_stopped(self, verbose=False):
        """Wait for the current run to be stopped"""
        cnc = self.cnc_connection()

        try:
            state = cnc.rpc_runset_state(self.__runset_id)
        except:  # pylint: disable=bare-except
            state = RunSetState.ERROR

        if state == RunSetState.UNKNOWN:
            self.__runset_id = None
            return True

        return self.__wait_for_state(RunSetState.READY, 10, verbose=verbose)


def main():
    "Main program"

    run = CnCRun(show_commands=True, show_command_output=True, dry_run=False)
    run.run("spts64-dirtydozen-hlc-006", "spts64-dirtydozen-hlc-006", 30,
            (("flash-21.xml", 5), (None, 10), ("flash-21.xml", 5)),
            verbose=True)


if __name__ == "__main__":
    main()
