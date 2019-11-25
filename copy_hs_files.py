#!/usr/bin/env python
#
# TODO: if missing, insert local SSH credentials into hub's ~/.ssh/known_hosts
#       before doing rsyncs

from __future__ import print_function

import argparse
import os
import re
import select
import signal
import socket
import sqlite3
import subprocess
import sys

from datetime import datetime


# default bandwidth limit for rsyncs
BWLIMIT = 8000


class Profile(object):
    def __init__(self, name):
        self.__name = name
        self.__start_time = None

    def __enter__(self):
        self.__start_time = datetime.now()

    def __exit__(self, exc_type, exc_value, traceback):
        tdiff = datetime.now() - self.__start_time
        tottime = float(tdiff.seconds) + \
          (float(tdiff.microseconds) / 1000000.0)
        print("** %s took %0.6fs" % (self.__name, tottime))


######################### STOLEN FROM dash/Process.py #########################
#

class ProcessException(Exception):
    "Process exception"
    pass


def find_python_process(target):
    "Return the IDs of any Python processes containing the target string"
    for line in list_processes():
        match = re.match(r"\s*(\d+)\s+.+?[Pp]ython[\d]*\S*\s+.+?%s" %
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

#
######################### STOLEN FROM dash/Process.py #########################


class HSCopyException(Exception):
    "HitSpool copy exception"
    pass


class HsCopier(object):
    """
    Copy all hitspool files in the time range to a subdirectory of
    the destination.
    """

    def __init__(self, args):
        if not args.force:
            # this should only be run on a hub
            hubname = hostname()
            if not hubname.startswith("ichub") and \
              not hubname.startswith("ithub"):
                raise SystemExit("This command should only be run on a hub")

        # get the IDs of all processes running this program
        my_name = os.path.basename(sys.argv[0])
        if my_name == "pdaq":
            my_name = sys.argv[1]
        pids = list(find_python_process(my_name))

        if args.kill:
            # kill other instances of this program
            mypid = os.getpid()
            for pid in pids:
                if pid != mypid:
                    # print("Killing %d..." % pid)
                    os.kill(pid, signal.SIGHUP)
            sys.exit(0)

        # quit if there's another instance of this program
        if len(pids) > 1:
            raise SystemExit("Another copy of \"%s\" is running!" % my_name)

        # load all arguments
        (destination, start_ticks, stop_ticks, bwlimit, chunk_size, dry_run,
         size_only, verbose) = process_args(args)

        self.__destination = destination
        self.__start_ticks = start_ticks
        self.__stop_ticks = stop_ticks
        self.__bwlimit = bwlimit
        self.__chunk_size = chunk_size
        self.__dry_run = dry_run
        self.__size_only = size_only
        self.__verbose = verbose

        self.__proc = None

    def __copy_files(self, spooldir, file_list):
        """
        Copy the files from the local 'spooldir' to the remote 'destination'
        using 'rsync' with requested bandwidth limit
        """
        cmd_args = ["nice", "-19", "rsync", "-avv", "--partial",
                    "--bwlimit=%s" % self.__bwlimit] + file_list
        cmd_args.append(self.__destination)

        if self.__dry_run:
            print(" ".join(cmd_args))
            return 0

        self.__proc = subprocess.Popen(cmd_args, close_fds=True, cwd=spooldir,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)

        select_err = False
        rsync_err = False
        while True:
            reads = [self.__proc.stdout.fileno(), self.__proc.stderr.fileno()]
            try:
                ret = select.select(reads, [], [])
            except select.error:
                # quit if we've seen more than one error
                if select_err:
                    break
                select_err = True
                continue

            for fno in ret[0]:
                if fno == self.__proc.stdout.fileno():
                    line = self.__proc.stdout.readline()
                    if line != "":
                        print("%s" % line)
                        sys.stdout.flush()
                    continue

                if fno == self.__proc.stderr.fileno():
                    line = self.__proc.stderr.readline().rstrip()
                    if line != "":
                        print("ERROR: %s" % line, file=sys.stderr)
                        if line.find("rsync error") >= 0:
                            rsync_err = True
                    continue

            if self.__proc.poll() is not None:
                break

        self.__proc.stdout.close()
        self.__proc.stderr.close()

        rtncode = self.__proc.wait()
        if rtncode == 0:
            if rsync_err:
                print("YIKES: Saw 'rsync error' with rtncode 0!!",
                      file=sys.stderr)
                return -1
        return rtncode

    def __get_size(self, hs_spooldir, file_list):
        "Get the total size in bytes for all files in <file_list>"

        total_size = 0
        for fname in file_list:
            path = os.path.join(hs_spooldir, fname)
            if self.__dry_run:
                total_size += len(path)
            else:
                total_size += os.path.getsize(path)

        return total_size


    def __kill_with_signal(self, signum, frame):
        self.__proc.kill()
        sys.exit(0)

    def __list_files(self, hs_spooldir="/mnt/data/pdaqlocal/hitspool",
                        hs_dbfile="hitspool.db"):
        """
        Fetch list of files containing requested data from hitspool DB.
        Return directory holding HS files, plus the list of files with
        data in the requested range
        """
        dbpath = os.path.join(hs_spooldir, hs_dbfile)
        if not os.path.exists(dbpath):
            raise SystemExit("Cannot find DB file \"%s\" in %s" %
                             (hs_dbfile, hs_spooldir))

        conn = sqlite3.connect(dbpath)
        try:
            cursor = conn.cursor()

            hs_files = []
            for row in cursor.execute("select filename from hitspool"
                                      " where stop_tick>=? "
                                      " and start_tick<=?",
                                      (self.__start_ticks, self.__stop_ticks)):
                hs_files.append(row[0])

        finally:
            conn.close()

        if hs_files is None or len(hs_files) == 0:
            raise SystemExit("No data found between %s and %s" %
                             (self.__start_ticks, self.__stop_ticks))

        return hs_spooldir, hs_files

    def run(self):
        # fetch the list of files to copy
        if not self.__dry_run:
            hs_spooldir, file_list = self.__list_files()
        else:
            hs_spooldir = "/tmp/spool"
            file_list = ["ONE", "TWO", "THREE"]

        # if the process is killed, kill hub workers before quitting
        signal.signal(signal.SIGINT, self.__kill_with_signal)
        signal.signal(signal.SIGHUP, self.__kill_with_signal)

        num_files = len(file_list)
        total_size = 0
        while len(file_list) > 0:
            chunk = file_list[:self.__chunk_size]

            if self.__size_only:
                total_size += self.__get_size(hs_spooldir, chunk)
            else:
                for idx in range(5):
                    rtncode = self.__copy_files(hs_spooldir, chunk)
                    if rtncode == 0:
                        if idx > 0:
                            print("Copy attempt #%d succeeded" % idx,
                                  file=sys.stderr)
                        break

                    print("Copy attempt #%d failed for %s" %
                          (idx, ", ".join(chunk)), file=sys.stderr)

            del file_list[:self.__chunk_size]

        if self.__size_only:
            print("Found %d bytes in %d files" % (total_size, num_files))


def add_arguments(parser):
    "Add all arguments"
    parser.add_argument("-b", "--bwlimit", type=int, dest="bwlimit",
                        action="store", default=BWLIMIT,
                        help="Bandwidth limit for 'rsync' copies")
    parser.add_argument("-c", "--chunk-size", type=int, dest="chunk_size",
                        action="store", default=20,
                        help="Number of files copied at a time")
    parser.add_argument("-d", "--destination", dest="destination",
                        default=None,
                        help="Final destination of copied files")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="Run this on a non-hub machine")
    parser.add_argument("-k", "--kill", dest="kill",
                        action="store_true", default=False,
                        help="Kill all other copies of this program")
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help="Dry run (do not actually change anything)")
    parser.add_argument("-s", "--size-only", dest="size_only",
                        action="store_true", default=False,
                        help="Only gather total file size, don't copy anything")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print details")
    parser.add_argument(dest="positional", nargs="*")


def hostname():
    "Return this host's name"
    fullname = socket.gethostname()

    pieces = fullname.split('.', 1)

    return pieces[0]


def process_args(args):
    """
    Parse arguments and return a tuple containing:
    destination - local directory
    start_ticks - starting DAQ tick (integer value)
    stop_ticks - ending DAQ tick (integer value)
    bwlimit - 'rsync' bandwidth limit (if None, default will be used)
    chunk_size - number of files to copy at a time (if None, uses default)
    dry_run - if True, print what would be done but run anything
    size_only - if True, report the total size to be copied but don't copy
    verbose - if True, print status messages
    """
    # assign argument values
    bwlimit = args.bwlimit
    chunk_size = args.chunk_size
    destination = args.destination
    dry_run = args.dry_run
    size_only = args.size_only
    verbose = args.verbose

    start_ticks = None
    stop_ticks = None

    # --kill ignores all other arguments
    if not args.kill:
        if len(args.positional) == 0:
            raise SystemExit("Please specify start and end times")

        # extract remaining values from positional parameters
        for arg in args.positional:
            if arg.find("-") > 0:
                start_str, stop_str = arg.split("-")

                try:
                    start_ticks = int(start_str)
                    stop_ticks = int(stop_str)
                except:
                    raise SystemExit("Cannot extract start/stop times"
                                     " from \"%s\"" % str(arg))
                continue

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

            raise SystemExit("Unrecognized argument \"%s\"" % arg)

        if start_ticks is None or stop_ticks is None:
            raise SystemExit("Please specify start/stop times")
        elif not size_only and destination is None:
            raise SystemExit("Please specify destination")

        if start_ticks > stop_ticks:
            print("WARNING: Start and stop times were reversed",
                  file=sys.stderr)
            tmp_ticks = start_ticks
            start_ticks = stop_ticks
            stop_ticks = tmp_ticks

    return (destination, start_ticks, stop_ticks, bwlimit, chunk_size, dry_run,
            size_only, verbose)


def main():
    "Main method"
    argp = argparse.ArgumentParser()
    add_arguments(argp)
    args = argp.parse_args()

    copier = HsCopier(args)
    copier.run()


if __name__ == "__main__":
    main()
