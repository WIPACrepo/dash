#!/usr/bin/env python
"""
Copy HitSpool data from a list of hubs to a local directory
"""

from __future__ import print_function

import argparse
import os
import re
import select
import signal
import socket
import subprocess
import sys
import threading
import time


class HSCopyException(Exception):
    "Hub copy exceptions"
    pass


class DAQState(object):
    "Track DAQ run state"

    def __init__(self):
        "Get current run state from 'livecmd check' on expcont"
        self.__runnum = None
        self.__time_since_start = None
        self.__time_left = None

        # get this host's name
        fullname = socket.gethostname()
        pieces = fullname.split('.', 1)
        self.__hostname = pieces[0]

    def __str__(self):
        if self.__runnum is None:
            rstr = "**NO ACTIVE RUN**"
        else:
            rstr = "Run %s" % self.__runnum
        if self.__time_left is not None:
            rstr += ": %ds left" % self.__time_left
        return rstr

    @classmethod
    def __parse_time(cls, fieldname, time_str):
        """
        Parse a time string like "01:23:45.6789"
        Return number of seconds (as integer value)
        """
        pieces = time_str.split(":")
        if len(pieces) < 2 or len(pieces) > 4:
            raise HSCopyException("Bad %s string \"%s\"" %
                                  (fieldname, time_str))

        # drop subseconds from final field
        pieces[-1] = pieces[-1].split(".")[0]

        # work from back to front
        pieces.reverse()
        total = 0
        for idx, valstr in enumerate(pieces):
            try:
                val = int(valstr)
            except ValueError:
                raise HSCopyException("Bad field #%d \"%s\" in %s \"%s\"" %
                                      (idx, valstr, fieldname, time_str))

            if idx == 0:
                # seconds
                total = val
            elif idx == 1:
                # minutes
                total += val * 60
            elif idx == 2:
                # hours
                total += val * 60 * 60
            elif idx == 3:
                # days
                total += val * 60 * 60 * 24

        return total

    @property
    def running(self):
        "Return True if a run is active"
        return self.__runnum is not None

    @property
    def time_left(self):
        "Return the time until the run ends"
        return self.__time_left

    @property
    def time_since_start(self):
        "Return the time since the run started"
        return self.__time_since_start

    def update(self, dry_run=False, debug=False):
        "Fetch the latest run data"
        if self.__hostname == "expcont":
            cmd_args = []
        else:
            cmd_args = ["ssh", "expcont", "-l", "pdaq"]
        cmd_args += ("livecmd", "check")

        if dry_run:
            print(" ".join(cmd_args))
            if self.__time_left is None:
                self.__runnum = 123456
                self.__time_left = 44
                self.__time_since_start = 9999
            else:
                self.__time_left -= 10
                self.__time_since_start += 10
            return

        proc = subprocess.Popen(cmd_args,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                close_fds=True)

        runnum = None
        time_left = None
        time_since_start = None
        debug_lines = []
        for line in proc.stdout:
            if debug:
                debug_lines.append(line)

            if line.find(": ") > 0:
                (front, back) = line.split(": ", 1)

                front = front.lstrip()
                back = back.rstrip()
                if front == "run":
                    try:
                        runnum = int(back)
                    except:
                        runnum = back
                elif front == "Time until stop":
                    time_left = self.__parse_time("time left", back)
                elif front == "Time since start":
                    time_since_start = self.__parse_time("time since start",
                                                         back)

        self.__runnum = runnum
        self.__time_left = time_left
        self.__time_since_start = time_since_start

        # clean up after subprocess exits
        proc.wait()

        if proc.returncode != 0:
            print("WARNING: 'livecmd check' failed", file=sys.stderr)
            if debug:
                for line in debug_lines:
                    print(">> %s" % line.rstrip())


class HubWorker(object):
    """
    Copy (or get sizes for) HitSpool files from a hub
    """

    # prefix used for all HitSpool files
    HITSPOOL_FILENAME = "HitSpool-"

    # regular expression used to extract total size from all hubs
    SIZE_PAT = re.compile(r"Found (\d+) bytes in (\d+) files")

    def __init__(self, hostname, hub, destination, start_ticks, stop_ticks,
                 bwlimit=None, chunk_size=None, dry_run=False,
                 hub_command=None, size_only=False, verbose=False):
        self.__hub = hub
        self.__destination = destination
        self.__start_ticks = start_ticks
        self.__stop_ticks = stop_ticks
        self.__bwlimit = bwlimit
        self.__chunk_size = chunk_size
        self.__dry_run = dry_run
        self.__size_only = size_only
        self.__verbose = verbose

        if self.__hub.startswith("ichub"):
            self.__short_name = self.__hub[5:]
        else:
            self.__short_name = "t" + self.__hub[5:]

        if hub_command is None:
            self.__hub_command = ("pdaq", "copy_hs_files")
        else:
            self.__hub_command = hub_command.split(" ")

        self.__hostname = hostname

        self.__thread = None
        self.__proc = None
        self.__finished = False

        self.__file_count = 0
        self.__total_size = 0

    def __run_command(self):
        "Start rsync process for this hub"
        if self.__destination.endswith(self.__hub):
            dest = self.__destination
        else:
            dest = os.path.join(self.__destination, self.__hub)
        rmtpath = "%s:%s" % (self.__hostname, dest)

        cmd_args = ["ssh", self.__hub]
        cmd_args += self.__hub_command
        if not self.__size_only:
            cmd_args += ("-d", rmtpath)
        else:
            cmd_args.append("-s")
        cmd_args += (str(self.__start_ticks), str(self.__stop_ticks))

        # add optional arguments, if present
        if self.__bwlimit is not None:
            cmd_args.append("--bwlimit=%d" % self.__bwlimit)
        if self.__chunk_size is not None:
            cmd_args.append("--chunk_size=%d" % self.__chunk_size)

        if self.__dry_run or self.__verbose:
            print(" ".join(cmd_args))
            if self.__dry_run:
                return

        self.__proc = subprocess.Popen(cmd_args, bufsize=1, close_fds=True,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)

        saw_err = False
        while True:
            reads = [self.__proc.stdout.fileno(), self.__proc.stderr.fileno()]
            try:
                ret = select.select(reads, [], [])
            except select.error:
                # quit if we've seen more than one error
                if saw_err:
                    break
                saw_err = True
                continue

            for fno in ret[0]:
                if fno == self.__proc.stderr.fileno():
                    line = self.__proc.stderr.readline().rstrip()
                    if line != "":
                        print("%s: %s" % (self.__hub, line), file=sys.stderr)
                    continue

                if fno != self.__proc.stdout.fileno():
                    print("%s: Bad file number %s" % (self.__hub, fno),
                          file=sys.stderr)
                    continue

                line = self.__proc.stdout.readline().rstrip()
                if line == "":
                    continue
                if line.startswith("opening connection"):
                    continue
                if line.startswith("sending incremental"):
                    continue
                if line.startswith("delta-transmission"):
                    continue
                if line.startswith("total: "):
                    continue
                if line.find(self.HITSPOOL_FILENAME) >= 0:
                    self.__file_count += 1
                    if self.__verbose:
                        print("%s: %s" % (self.__hub, line))
                        sys.stdout.flush()
                    continue
                if line.startswith("sent ") or \
                  line.startswith("total size is ") or \
                  line.startswith("created directory "):
                    if self.__verbose:
                        print("%s: %s" % (self.__hub, line))
                        sys.stdout.flush()
                    continue

                if self.__size_only and line.startswith("Found "):
                    mtch = self.SIZE_PAT.match(line)
                    if mtch is not None:
                        self.__total_size += int(mtch.group(1))
                        self.__file_count += int(mtch.group(2))
                    continue

                print("%s: ?? \"%s\" ??" % (self.__hub, line), file=sys.stderr)

            if self.__proc.poll() is not None:
                break

        self.__proc.stdout.close()
        self.__proc.stderr.close()

        self.__proc.wait()

        if not self.__size_only:
            print("** %s copied %d files" % (self.__hub, self.__file_count))
        elif self.__verbose:
            print("** %s DONE" % (self.__hub, ))

        self.__finished = True

    @property
    def file_count(self):
        return self.__file_count

    @property
    def is_finished(self):
        return self.__finished

    def kill(self):
        "Kill the copy process on the hub"
        if not self.__dry_run:
            cmd_args = ["ssh", self.__hub]
            cmd_args += self.__hub_command
            cmd_args.append("-k")

            try:
                lines = subprocess.check_output(cmd_args,
                                                stderr=subprocess.PIPE)
                for line in lines.splitlines():
                    print("KILL: %s" % line)
            except subprocess.CalledProcessError as cpe:
                print("Could not kill \"%s\" on %s: %s" %
                      (" ".join(self.__hub_command), self.__hub, cpe))

    @property
    def name(self):
        "Return the name of this hub"
        return self.__hub

    def poll(self):
        "Return None if the process is still running, return code otherwise"
        if self.__dry_run:
            return 0

        if self.__proc is None:
            return -1

        return self.__proc.poll()

    @property
    def running(self):
        """
        Return None if the hub is copying data, otherwise return the
        process's return code
        """
        if self.__dry_run:
            return True

        if self.__proc is None:
            return False

        if self.__proc.returncode is None:
            return None

        # if the process has finished, clean up the thread
        if self.__thread is not None:
            self.__thread.join()
            self.__thread = None

        return self.__proc.returncode

    @property
    def short_name(self):
        """
        Return the short name of this hub (e.g. "01" or "t01")
        """
        return self.__short_name

    def start(self):
        "Start a thread to copy the HitSpool data from a hub"
        self.__thread = threading.Thread(target=self.__run_command,
                                         name="%sCopy" % self.__hub)
        self.__thread.start()

    @property
    def total_size(self):
        return self.__total_size


class CopyManager(object):
    "Manage hubs which are copying HitSpool data"

    # time window at the start of the run when busy hubs may be unstable
    UNSTABLE_START = 180
    # sleep time between checks that the run is still in the "stable" window
    UNSTABLE_SLEEP = 5
    # window at the end of the run when hubs may be unstable
    # (add extra time so we're sure to wake up before reaching the window)
    UNSTABLE_STOP = 10 + (UNSTABLE_SLEEP * 2)

    def __init__(self, args):
        # load all arguments
        (hub_list, destination, start_ticks, stop_ticks, bwlimit, chunk_size,
         debug, dry_run, hub_command, size_only, verbose) \
         = process_args(args)

        self.__debug = debug
        self.__dry_run = dry_run
        self.__size_only = size_only
        self.__verbose = verbose

        # create DAQ run state monitor and initialize it
        self.__state = DAQState()
        self.__state.update(dry_run, self.__debug)

        # get this host's name
        fullname = socket.gethostname()
        pieces = fullname.split('.', 1)
        hostname = pieces[0]

        # create top-level directory
        if not dry_run and not os.path.exists(destination):
            os.makedirs(destination)

        self.__workers = []
        for hub in hub_list:
            wrkr = HubWorker(hostname, hub, destination, start_ticks,
                             stop_ticks, bwlimit=bwlimit,
                             chunk_size=chunk_size, dry_run=dry_run,
                             hub_command=hub_command, size_only=size_only,
                             verbose=verbose)
            self.__workers.append(wrkr)

        # if the process is killed, kill hub workers before quitting
        signal.signal(signal.SIGINT, self.kill_with_signal)

    @classmethod
    def __sizefmt(cls, size):
        for suffix in ('bytes', 'KB', 'MB', 'GB'):
            if size < 1024.0:
                return "%3.1f %s" % (size, suffix)
            size /= 1024.0
        return "%3.1f TB" % size

    def __print_copy_progress(self):
        "Print short hub names and number of files copied"
        summary = ""
        for wrkr in self.__workers:
            if wrkr.is_finished:
                continue

            if summary == "":
                prefix = ""
            else:
                prefix = " "

            summary += "%s%s*%d" % (prefix, wrkr.short_name, wrkr.file_count)
        print("%s" % summary)

    @classmethod
    def __print_sizes(cls, workers):
        "Print the sorted list of sizes for all hubs in <workers>"
        total_count = 0
        total_size = 0
        for wrkr in sorted(workers, key=lambda x: x.total_size):
            if wrkr.total_size is None or wrkr.file_count is None:
                print("WARNING: No file sizes found for %s" % (wrkr.name, ),
                      file=sys.stderr)
            else:
                total_count += wrkr.file_count
                total_size += wrkr.total_size
                print("%s: %d bytes (%s) in %d files" %
                      (wrkr.name, wrkr.total_size,
                       cls.__sizefmt(wrkr.total_size), wrkr.file_count))

        print("Total size: %d bytes (%s) in %d files" %
              (total_size, cls.__sizefmt(total_size), total_count))

    @property
    def is_stable(self):
        "Return True if run is stable"
        return self.__state.running and \
          self.__state.time_since_start is not None and \
          self.__state.time_since_start > self.UNSTABLE_START and \
          self.__state.time_left is not None and \
          self.__state.time_left > self.UNSTABLE_STOP

    def run(self):
        "Manage hub copy processes"
        # don't start copying until there's a stable run
        if not self.is_stable:
            if self.__verbose:
                print("Waiting until DAQ is stable")
            self.pause_when_not_running()

        if self.__verbose:
            print("Starting hub workers")
        self.start_processes()

        while True:
            self.__state.update(dry_run=self.__dry_run)
            if not self.is_stable:
                if self.__verbose:
                    print("Killing hub workers")
                self.kill_processes()

                if self.__verbose:
                    print("Waiting until DAQ is stable")
                self.pause_when_not_running()

                if self.__verbose:
                    print("Restarting hub workers")
                self.start_processes()

            if self.check_done():
                if self.__verbose:
                    print("All workers have finished")
                break

            if not self.__size_only:
                self.__print_copy_progress()

            if self.__verbose:
                print("Sleeping...")
            time.sleep(self.UNSTABLE_SLEEP)

        if self.__size_only:
            self.__print_sizes()

    def check_done(self):
        "Return True if all processes have finished"
        for wrkr in self.__workers:
            if wrkr.poll() is None:
                return False
        return True

    def pause_when_not_running(self):
        """
        Pause if pDAQ is not running or is in the "unsafe" window at the
        start/end of a run
        """
        while True:
            self.__state.update(dry_run=self.__dry_run)
            if self.is_stable:
                break
            time.sleep(self.UNSTABLE_SLEEP)

    def start_processes(self):
        "Start copy processes on hubs"
        for wrkr in self.__workers:
            wrkr.start()


    def kill_processes(self):
        "Kill copy processes on hubs"
        for wrkr in self.__workers:
            wrkr.kill()

    def kill_with_signal(self, signum, frame):
        self.kill_processes()
        sys.exit(0)


def add_arguments(parser):
    "Add all arguments"
    parser.add_argument("-C", "--hub-command", dest="hub_command",
                        default="pdaq copy_hs_files",
                        help="Hub command to run")
    parser.add_argument("-b", "--bwlimit", type=int, dest="bwlimit",
                        action="store", default=None,
                        help="Bandwidth limit for 'rsync' copies")
    parser.add_argument("-c", "--chunk-size", type=int, dest="chunk_size",
                        action="store", default=None,
                        help="Number of files copied at a time")
    parser.add_argument("-d", "--destination", dest="destination",
                        default=None,
                        help="Final destination of copied files")
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help="Dry run (do not actually change anything)")
    parser.add_argument("-s", "--size-only", dest="size_only",
                        action="store_true", default=False,
                        help="Only gather total file size, don't copy anything")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print details")
    parser.add_argument("-x", "--debug", dest="debug",
                        action="store_true", default=False,
                        help="Print debugging information")
    parser.add_argument(dest="positional", nargs="*",
                        help="Positional arguments"
                        " (start/stop times, list of hubs)")


def process_args(args):
    """
    Parse arguments and return a tuple containing:
    hub_list - list of hubs to copy from
    destination - local directory
    start_ticks - starting DAQ tick (integer value)
    stop_ticks - ending DAQ tick (integer value)
    bwlimit - 'rsync' bandwidth limit (if None, default will be used)
    chunk_size - number of files to copy at a time (if None, uses default)
    debug - if True, print debugging information to STDERR
    dry_run - if True, print what would be done but run anything
    hub_command - alternative command to run on hubs (used for debugging)
    size_only - if True, report the total size to be copied but don't copy
    verbose - if True, print status messages
    """
    bwlimit = args.bwlimit
    chunk_size = args.chunk_size
    dry_run = args.dry_run
    debug = args.debug
    destination = args.destination
    hub_command = args.hub_command
    size_only = args.size_only
    verbose = args.verbose

    start_ticks = None
    stop_ticks = None

    hub_list = []

    if len(args.positional) == 0:
        raise SystemExit("Please specify start and end times")

    for arg in args.positional:
        # is this a hub name?
        if arg.startswith("ichub") or arg.startswith("ithub"):
            hub_list.append(arg)
            continue

        # is this a start/stop time pair?
        if arg.find("-") > 0:
            start_str, stop_str = arg.split("-")

            try:
                start_ticks = int(start_str)
                stop_ticks = int(stop_str)
            except:
                raise SystemExit("Cannot extract start/stop times"
                                 " from \"%s\"" % str(arg))
            continue

        # is this a single time?
        try:
            val = int(arg)
            if start_ticks is None:
                start_ticks = val
                continue
            if stop_ticks is None:
                stop_ticks = val
                continue
        except ValueError:
            pass

        # WTF?
        raise SystemExit("Unrecognized argument \"%s\"" % arg)

    if start_ticks is None or stop_ticks is None:
        raise SystemExit("Please specify start/stop times")
    elif len(hub_list) == 0:
        raise SystemExit("Please specify one or more hubs")
    elif not size_only:
        if destination is None:
            raise SystemExit("Please specify destination")
        elif not os.path.exists(destination):
            raise SystemExit("Destination \"%s\" does not exist" %
                             str(destination))

    if start_ticks > stop_ticks:
        print("WARNING: Start and stop times were reversed")
        tmp_ticks = start_ticks
        start_ticks = stop_ticks
        stop_ticks = tmp_ticks

    return (hub_list, destination, start_ticks, stop_ticks, bwlimit,
            chunk_size, debug, dry_run, hub_command, size_only, verbose)


def main():
    "Main method"
    argp = argparse.ArgumentParser()
    add_arguments(argp)
    args = argp.parse_args()

    mgr = CopyManager(args)
    mgr.run()


if __name__ == "__main__":
    main()
