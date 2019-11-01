#!/usr/bin/env python
#
# Note that most of this functionality exists in the `psutil` package
# so this code should be reexamined if we ever add it to pDAQ

import os
import re
import subprocess


class ProcessException(Exception):
    pass


def find_python_process(target):
    "Return the IDs of any Python processes containing the target string"
    for line in list_processes():
        match = re.match(r"\s*(\d+)\s+.+?[Pp]ython[\d\.]*\s+.+?%s" %
                         (target, ), line)
        if match is not None:
            yield int(match.group(1))


def list_processes():
    "Return a list of strings describing all running processes"
    proc = subprocess.Popen(("ps", "ahwwx"), close_fds=True,
                            stdout=subprocess.PIPE)
    lines = proc.stdout.readlines()
    if proc.wait():
        raise ProcessException("Failed to list processes")

    for line in lines:
        yield line.decode("utf-8").rstrip()


def process_exists(filename):
    """
    Return True if the file exists and contains an active process ID
    Throw ProcessException for any problems
    """

    if not os.path.exists(filename):
        return False

    pid = None
    with open(filename, "r") as fin:
        for line in fin:
            if pid is not None:
                # file should not have more than one line
                raise ProcessException("File \"%s\" is not a PID file" %
                                       (filename, ))

            try:
                pid = int(line)
            except ValueError:
                # PIDs must be numeric
                raise ProcessException("File \"%s\" contains non-PID line"
                                       " \"%s\"" % (filename, line.rstrip()))

    if pid is None:
        raise ProcessException("File \"%s\" seems to be empty" % (filename, ))

    if False:
        # "kill -0" was broken on my Ubuntu laptop when I tried testing this
        # i.e. "kill -0 <pid>" didn't return an error for nonexistent processes
        try:
            # this does nothing if the process exists
            os.kill(pid, 0)
        except OSError:
            return False
    else:
        proc = subprocess.Popen(("ps", "h", str(pid)), close_fds=True,
                                stdout=subprocess.PIPE)
        exists = False
        for line in proc.stdout:
            # assume that any output means the process exists
            exists = True

        proc.stdout.close()
        proc.wait()

        if not exists:
            # process is dead, remove the irrelevant file and return
            os.unlink(filename)
            return False

    return True


def write_pid_file(filename):
    "Write the current process ID to the named file"

    try:
        fdout = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        raise ProcessException("Cannot write to existing \"%s\"" %
                               (filename, ))
    else:
        with os.fdopen(fdout, "w") as out:
            out.write(str(os.getpid()))


class exclusive_process(object):
    "context manager guaranteeing only one process at a time can run"
    def __init__(self, filename):
        self.__filename = filename

    def __enter__(self):
        if process_exists(self.__filename):
            raise ProcessException("Process is running")
        write_pid_file(self.__filename)

    def __exit__(self, exc_type, exc_value, traceback):
        os.unlink(self.__filename)
