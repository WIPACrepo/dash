#!/usr/bin/env python
"""
Copy SuperSaver *.save.tar files from 2ndbuild to a local directory
"""

from __future__ import print_function

import argparse
import os
import select
import socket
import subprocess
import sys


def add_arguments(parser):
    "Add all arguments"
    parser.add_argument("-d", "--destination", dest="destination",
                        default=None,
                        help="Final destination of copied files")
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help="Dry run (do not actually change anything)")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print details")


def copy_save_files(args):
    "Rsync saved secondary files to this host"

    destination = args.destination
    dry_run = args.dry_run
    verbose = args.verbose

    if destination is None:
        raise SystemExit("Please specify a destination")

    # create top-level directory
    if not dry_run and not os.path.exists(destination):
        os.makedirs(destination)

    # get this host's name
    fullname = socket.gethostname()
    pieces = fullname.split('.', 1)
    hostname = pieces[0]

    cmd_args = ["ssh", "2ndbuild", "nice", "-19", "rsync", "-avv",
                "--partial", "/mnt/data/pdaqlocal/*.save.tar",
                "%s:%s" % (hostname, destination)]

    if dry_run or verbose:
        print(" ".join(cmd_args))
        if dry_run:
            return

    proc = subprocess.Popen(cmd_args, bufsize=1, close_fds=True,
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
            if fno == proc.stderr.fileno():
                line = proc.stderr.readline().rstrip()
                if line != "":
                    print("ERROR: %s" % line, file=sys.stderr)
                continue

            if fno != proc.stdout.fileno():
                print("Bad file number %s" % str(fno), file=sys.stderr)
                continue

            line = proc.stdout.readline().rstrip()
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

            print("%s" % line)
            sys.stdout.flush()

        if proc.poll() is not None:
            break

    proc.stdout.close()
    proc.stderr.close()

    if proc.wait() != 0:
        raise SystemExit("RSync failed!")


def main():
    "Main method"
    argp = argparse.ArgumentParser()
    add_arguments(argp)
    args = argp.parse_args()

    copy_save_files(args)


if __name__ == "__main__":
    main()
