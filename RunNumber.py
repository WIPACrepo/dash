#!/usr/bin/env python
#
# Code to manipulate I3Live's "last run number" file

from __future__ import print_function

import os
import re
import sys


# Python 2/3 compatibility hack
if sys.version_info >= (3, 0):
    read_input = input
else:
    read_input = raw_input


class RunNumberException(Exception):
    pass


class RunNumber(object):
    DEFAULT_FILE = os.path.join(os.environ["HOME"], ".i3live-run")

    @classmethod
    def get_last(cls, filename=None):
        "Return the last run and subrun numbers as a tuple"
        num = 1
        subnum = 0

        if filename is None:
            filename = cls.DEFAULT_FILE

        if os.path.exists(filename):
            with open(filename, "r") as fin:
                line = fin.readline()
                mtch = re.search(r'(\d+)\s+(\d+)', line)
                if mtch is not None:
                    try:
                        num = int(mtch.group(1))
                        subnum = int(mtch.group(2))
                    except ValueError:
                        raise RunNumberException("Bad line \"%s\" from"
                                                 " \"%s\"" %
                                                 (line.rstrip(), filename))

        return (num, subnum)

    @classmethod
    def set_last(cls, number, subrun=0, filename=None):
        "Set the last run and subrun numbers"
        try:
            good_run = int(number)
        except ValueError:
            raise RunNumberException("Bad run number \"%s\"" % number)

        try:
            good_sub = int(subrun)
        except ValueError:
            raise RunNumberException("Bad subrun number \"%s\"" % subrun)

        if filename is None:
            filename = cls.DEFAULT_FILE

        try:
            with open(filename, 'w') as fout:
                print("%d %d" % (good_run, good_sub), file=fout)
        except Exception as exc:
            raise RunNumberException("Cannot update \"%s\" with \"%s %s\":"
                                     " %s" %
                                     (filename, good_run, good_sub, str(exc)))


def add_arguments(parser):
    parser.add_argument("run_number",
                        type=int, default=None, nargs="?",
                        help="Last run number")
    parser.add_argument("-s", "--subrun", dest="subrun",
                        type=int, default=0,
                        help="Last subrun number")


def get_or_set_run_number(args):
    (run_num, subrun) = RunNumber.get_last()

    if args.run_number is None:
        action = "is"
    elif not verify_change(run_num, subrun, args.run_number, args.subrun):
        action = "not changed from"
    else:
        # update file with new run and subrun numbers
        RunNumber.set_last(args.run_number, subrun=args.subrun)
        action = "set to"

        # reread file to make sure all is well
        (run_num, subrun) = RunNumber.get_last()

    if subrun == 0:
        print("Run number %s %s" % (action, run_num))
    else:
        print("Run number %s %s (subrun %d)" % (action, run_num, subrun))


def run_subrun_str(run, subrun):
    if subrun is None or subrun == 0:
        return "#%d" % run
    return "#%d (subrun %d)" % (run, subrun)


def verify_change(lastrun, lastsub, newrun, newsub):
    if lastrun == newrun and lastsub == newsub:
        return False

    laststr = run_subrun_str(lastrun, lastsub)
    newstr = run_subrun_str(newrun, newsub)

    if newrun < lastrun:
        prompt = "Are you SURE you want to revert the run number from" \
                 " %s back to %s?" % (laststr, newstr)
    elif newsub not in (0, lastsub):
        prompt = "Are you SURE you want to change the run number from" \
                 " %s to %s?" % (laststr, newstr)
    else:
        prompt = "Are you SURE you want to change the run number from" \
                 " %s to %s?" % (laststr, newstr)

    while True:
        reply = read_input(prompt + " (y/n) ")
        lreply = reply.strip().lower()
        if lreply in ("y", "yes"):
            return True
        if lreply in ("n", "no"):
            return False

        print("Please answer 'yes' or 'no'", file=sys.stderr)


def main():
    "Main program"

    import argparse

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    args = parser.parse_args()

    get_or_set_run_number(args)


if __name__ == "__main__":
    main()
