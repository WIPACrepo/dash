#!/usr/bin/env python

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
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print details")
    parser.add_argument(dest="positional", nargs="*")


def copy_files_in_range(args):
    """
    Copy all hitspool files in the time range to a subdirectory of
    the destination.
    """
    hubname = hostname()
    if not args.force and not hubname.startswith("ichub") and \
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
                os.kill(pid, signal.SIGKILL)
        sys.exit(0)

    # quit if there's another instance of this program
    if len(pids) > 1:
        raise SystemExit("Another copy of \"%s\" is running!" % my_name)

    # load all arguments
    destination, start_ticks, stop_ticks, bwlimit, chunk_size, dry_run, \
      verbose = process_args(args)

    if not dry_run:
        hs_spooldir, file_list = list_hs_files(start_ticks, stop_ticks)
    else:
        hs_spooldir = "/tmp/spool"
        file_list = ["ONE", "TWO", "THREE"]

    while len(file_list) > 0:
        chunk = file_list[:chunk_size]

        rtncode = copy_hs_files(destination, hs_spooldir, chunk, bwlimit,
                                dry_run=dry_run)
        if rtncode != 0:
            raise HSCopyException("Could not copy one or more files: %s" %
                                  " ".join(chunk))

        del file_list[:chunk_size]


def copy_hs_files(destination, spooldir, file_list, bwlimit, dry_run=False):
    """
    Copy the files from the local 'spooldir' to the remote 'destination'
    using 'rsync' with requested bandwidth limit
    """
    cmd_args = ["nice", "-19", "rsync", "-avv", "--partial",
                "--bwlimit=%s" % bwlimit] + file_list
    cmd_args.append(destination)

    if dry_run:
        print(" ".join(cmd_args))
        return 0

    proc = subprocess.Popen(cmd_args, bufsize=1, close_fds=True, cwd=spooldir,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    saw_err = False
    while True:
        reads = [proc.stdout.fileno(), proc.stderr.fileno()]
        try:
            ret = select.select(reads, [], [])
        except select.error:
            # quit if we've seen more than one error
            if saw_err:
                break
            saw_err = True
            continue

        for fno in ret[0]:
            if fno == proc.stdout.fileno():
                line = proc.stdout.readline()
                if line != "":
                    print("%s" % line)
                    sys.stdout.flush()
            if fno == proc.stderr.fileno():
                line = proc.stderr.readline().rstrip()
                if line != "":
                    print("ERROR: %s" % line, file=sys.stderr)

        if proc.poll() is not None:
            break

    proc.stdout.close()
    proc.stderr.close()

    return proc.wait()


def hostname():
    "Return this host's name"
    fullname = socket.gethostname()

    pieces = fullname.split('.', 1)

    return pieces[0]


def list_hs_files(start_ticks, stop_ticks,
                  hs_spooldir="/mnt/data/pdaqlocal/hitspool",
                  hs_dbfile="hitspool.db"):
    """
    Fetch list of files containing requested data from hitspool DB.
    Return directory holding HS files, plus the list of files with
    data in the requested range
    """
    dbpath = os.path.join(hs_spooldir, hs_dbfile)
    if not os.path.exists(dbpath):
        raise HSCopyException("Cannot find DB file in %s" % hs_spooldir)

    conn = sqlite3.connect(dbpath)
    try:
        cursor = conn.cursor()

        hs_files = []
        for row in cursor.execute("select filename from hitspool"
                                  " where stop_tick>=? "
                                  " and start_tick<=?",
                                  (start_ticks, stop_ticks)):
            hs_files.append(row[0])

    finally:
        conn.close()

    if hs_files is None or len(hs_files) == 0:
        raise HSCopyException("No data found between %s and %s" %
                              (start_ticks, stop_ticks))

    return hs_spooldir, hs_files


def process_args(args):
    """
    Parse arguments
    Return a tuple containing
    (destination, start_ticks, stop_ticks, bwlimit, chunk_size, dry_run,
     verbose)
    """
    # assign argument values
    bwlimit = args.bwlimit
    chunk_size = args.chunk_size
    destination = args.destination
    dry_run = args.dry_run
    verbose = args.verbose

    start_ticks = None
    stop_ticks = None

    # --kill ignores all other arguments
    if not args.kill:
        if len(args.positional) == 0:
            raise HSCopyException("Please specify start and end times")

        # extract remaining values from positional parameters
        for arg in args.positional:
            if arg.find("-") > 0:
                start_str, stop_str = arg.split("-")

                try:
                    start_ticks = int(start_str)
                    stop_ticks = int(stop_str)
                except:
                    raise HSCopyException("Cannot extract start/stop times"
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

            if destination is None:
                destination = arg
                continue

            raise HSCopyException("Unrecognized argument \"%s\"" % arg)

        if start_ticks is None or stop_ticks is None:
            raise HSCopyException("Please specify start/stop times")
        elif destination is None:
            raise HSCopyException("Please specify destination")

    return (destination, start_ticks, stop_ticks, bwlimit, chunk_size, dry_run,
            verbose)


def main():
    "Main program"
    parser = argparse.ArgumentParser()
    add_arguments(parser)
    parser = argp.parse_args()

    copy_files_in_range(args)


if __name__ == "__main__":
    main()
