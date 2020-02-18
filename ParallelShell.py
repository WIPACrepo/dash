#!/usr/bin/env python

# ParallelShell.py
# J. Jacobsen & K. Beattie, for UW-IceCube
# February, April, June 2007

"""
This module implements a means to run multiple shell commands in parallel.

See 'main' method at bottom for example usage.

Setting trace=True will allow the output of the commands to go to the
parent's terminal.  Calling ps.wait() will prevent the interpreter
from returning before the commands finish, otherwise the interpreter
will return while the commands continue to run;
"""

from __future__ import print_function

import datetime
import os
import random
import signal
import subprocess
import time


class TimeoutException(Exception):
    "Exception thrown when a running command exceeds the timeout value"
    pass  # pylint: disable=unnecessary-pass


class PCmd(object):
    """
    Handle individual shell commands to be executed in parallel.
    """

    # class variable to guarantee unique filenames
    counter = 0

    def __init__(self, cmd, parallel=True, dry_run=False,
                 verbose=False, trace=False, timeout=None):
        """
        Construct a PCmd object with the given options:
        cmd - The command to run as a string.
        parallel - If True don't wait for command to return when
                   started, otherwise wait. Default: True
        dry_run   - If True, don't actually start command.  Only usefull
                   if verbose is also True. Default: False
        verbose  - If True, print command as they are run along with
                   process IDs and return codes. Default: False
        trace    - If True, use inherited parent's stdout and stderr.  If
                   False (the default) modifiy command string to redirect
                   stdout & err to /dev/null.
        timeout  - If not None, number of seconds to wait before killing
                   process and raising a TimeoutException;
        """

        self.cmd = cmd
        self.orig_cmd = cmd
        self.subproc = None
        self.__parallel = parallel
        self.dry_run = dry_run
        self.verbose = verbose
        self.trace = trace
        self.timeout = timeout
        self.tstart = None
        self.counter = PCmd.counter
        self.pid = os.getpid()

        filename = "__pcmd__%d__%d.txt" % (self.pid, self.counter)
        self.__out_file = os.path.join("/", "tmp", filename)

        self.__output = ""
        self.done = False

        PCmd.counter += 1

    def __str__(self):
        """ Return info about this command, the pid used and
        return code. """
        state_str = "%s%s%s%s" % (self.__parallel and 'p' or '',
                                  self.dry_run and 'd' or '',
                                  self.verbose and 'v' or '',
                                  self.trace and 't' or '')
        if self.subproc is None:  # Nothing started yet or dry run
            return "'%s' [%s] Not started or dry run" % (self.cmd, state_str)

        if self.subproc.returncode is None:
            return "'%s' [%s] running as pid %d" % (self.cmd,
                                                    state_str,
                                                    self.subproc.pid)
        if self.subproc.returncode < 0:
            return ("'%s' [%s] terminated (pid was %d) "
                    "by signal %d") % (self.cmd,
                                       state_str,
                                       self.subproc.pid,
                                       -self.subproc.returncode)

        return "'%s' [%s] (pid was %d) returned %d " % \
          (self.cmd, state_str, self.subproc.pid, self.subproc.returncode)

    def start(self):
        """ Start this command. """
        self.tstart = datetime.datetime.now()

        # If not tracing, send both stdout and stderr to /dev/null
        if not self.trace:
            # Handle the case where the command ends in an '&' (silly
            # but we shouldn't break)
            if self.cmd.rstrip().endswith("&"):
                controlop = " "
            else:
                controlop = ";"
            self.cmd = "{ %s %c } >%s 2>&1" % (self.cmd,
                                               controlop,
                                               self.__out_file)

        if self.subproc is not None:
            raise RuntimeError("Attempt to start a running command!")

        # Create a Popen object for running a shell child proc to
        # run the command
        if not self.dry_run:
            time.sleep(0.01)
            self.subproc = subprocess.Popen(self.cmd, shell=True)

        if self.verbose:
            print("ParallelShell: %s" % self)

        # If not running in parallel, then wait for this command (at
        # least the shell) to return
        if not self.__parallel:
            self.wait()

    def wait(self):
        """ Wait for the this command to return. """
        if self.done:
            return

        if self.subproc is None and not self.dry_run:
            raise RuntimeError("Attempt to wait for unstarted command!")

        if self.dry_run:
            return

        if not self.timeout:
            self.subproc.wait()
        else:  # Handle polling/timeout case
            status = self.subproc.poll()
            if status is None:
                elapsed = datetime.datetime.now() - self.tstart
                if elapsed < datetime.timedelta(seconds=self.timeout):
                    # we haven't timed out yet
                    return

                # Kill child process - note that this may fail
                # to clean up everything if child has spawned more proc's
                os.kill(self.subproc.pid, signal.SIGKILL)
                self.done = True
                self.__output += "TIMEOUT exceeded (%d seconds)" % self.timeout

        self.done = True
        if self.verbose:
            print("ParallelShell: %s" % self)

        # Harvest results
        if self.trace:
            self.__output += "Output not available: went to stdout!"
        else:
            try:
                with open(self.__out_file, "r") as fin:
                    self.__output += "".join(fin.readlines())
                os.unlink(self.__out_file)
            except Exception as exc:
                self.__output += \
                  "Could not read or delete result file %s (%s)!" % \
                  (self.__out_file, exc)

        return

    @property
    def output(self):
        "Return the output from this command"
        return self.__output


class ParallelShell(object):
    """ Class to implement multiple shell commands in parallel. """
    def __init__(self, parallel=True, dry_run=False,
                 verbose=False, trace=False, timeout=None):
        """ Construct a new ParallelShell object for managing multiple
        shell commands to be run in parallel.  The parallel, dry_run,
        verbose and trace options are identical to and used for each
        added PCmd object. """
        self.pcmds = []
        self.__parallel = parallel
        self.dry_run = dry_run
        self.verbose = verbose
        self.trace = trace
        self.timeout = timeout

    def add(self, cmd):
        "Add command to list of pending operations."
        self.pcmds.append(PCmd(cmd, self.__parallel, self.dry_run,
                               self.verbose, self.trace, self.timeout))
        return len(self.pcmds) - 1  # Start w/ 0

    def shuffle(self):
        """
        Randomize the list of commands as a lame attempt to avoid hammering
        a single machine
        """
        random.shuffle(self.pcmds)

    def start(self):
        """ Start all unstarted commands. """
        for cmd in self.pcmds:
            if cmd.subproc is None:
                cmd.start()

    def wait(self, monitor_ival=None):
        """ Wait for all started commands to complete (or time out).  If the
        commands are backgrounded (or fork then return in their
        parent) then this will return immediately. """

        start_time = datetime.datetime.now()
        num_to_do = len(self.pcmds)
        while True:
            still_waiting = False
            num_done = 0
            for cmd in self.pcmds:
                if cmd.subproc:
                    if cmd.done:
                        num_done += 1
                    else:
                        cmd.wait()  # Can raise TimeoutException
                        still_waiting = True

            if not still_waiting:
                break

            stop_time = datetime.datetime.now()
            if monitor_ival is not None:
                monitor_delta = datetime.timedelta(seconds=monitor_ival)
                if stop_time - start_time > monitor_delta:
                    dttm = stop_time - start_time
                    print("%d of %d done (%s)." % (num_done, num_to_do, dttm))

            time.sleep(0.3)

    def show_all(self):
        """
        Show commands and (if running or finished) with their
        process IDs and (if finished) with return codes.
        """
        for cmd in self.pcmds:
            print(cmd)

    def __get_job_command(self, job_id):
        return self.pcmds[job_id].orig_cmd

    def get_output_by_id(self, job_id):
        "Return the output from a specific command"
        return self.pcmds[job_id].output

    @property
    def __all_results(self):
        "Return a formatted list of all commands and their output"

        ret = ""
        for cmd in self.pcmds:
            ret += "Job: %s\nResult: %s\n" % (cmd, cmd.output)
        return ret

    @property
    def __return_codes(self):
        """Get the return codes set by wait/poll
        Setting a default value of 0 assumes success if not done.
        Is that correct???"""
        ret = []
        for cmd in self.pcmds:
            if cmd.subproc and cmd.done:
                ret.append(cmd.subproc.returncode)
            else:
                ret.append(0)
        return ret

    @property
    def command_results(self):
        """
        Return a dictionary of commands and the return codes generated by
        running those commands.  If a command is not done it is assumed to be
        unsuccesful.
        """
        ret = {}
        for cmd in self.pcmds:
            # this
            if (cmd.subproc and cmd.done):
                ret[cmd.orig_cmd] = (cmd.subproc.returncode, cmd.output)
            else:
                ret[cmd.orig_cmd] = (-1, '')

        return ret

    @property
    def is_parallel(self):
        """
        If True, commands are run in parallel
        If False, commands are run serially
        """
        return self.__parallel

    def system(self, cmd):
        "Unit tests override this to check `os.system` calls"
        return os.system(cmd)


def main():
    "Main program"
    psh = ParallelShell(timeout=5)
    jobs = []
    jobs.append(psh.add("ls"))
    jobs.append(psh.add("sleep 10"))
    jobs.append(psh.add("sleep 4; echo done sleeping four"))
    psh.start()
    psh.wait()
    for job in jobs:
        print("Job %d: result %s" % (job, psh.get_output_by_id(job)))


if __name__ == "__main__":
    main()
