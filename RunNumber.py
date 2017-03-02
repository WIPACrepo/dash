#!/usr/bin/env python
#
# Code to manipulate I3Live's "last run number" file


import os
import re
import sys


class RunNumberException(Exception):
    pass

class RunNumber(object):
    DEFAULT_FILE = os.path.join(os.environ["HOME"], ".i3live-run")

    @classmethod
    def getLast(cls, filename=None):
        "Return the last run and subrun numbers as a tuple"
        num = 1
        subnum = 0

        if filename is None:
            filename = cls.DEFAULT_FILE

        if os.path.exists(filename):
            with open(filename) as fd:
                line = fd.readline()
                m = re.search(r'(\d+)\s+(\d+)', line)
                if m:
                    try:
                        num = int(m.group(1))
                        subnum = int(m.group(2))
                    except:
                        raise RunNumberException("Bad line \"%s\" from \"%s\"" %
                                                 (line.rstrip(), filename))

        return (num, subnum)


    @classmethod
    def setLast(cls, number, subrun=0, filename=None):
        "Set the last run and subrun numbers"
        try:
            goodRun = int(number)
        except:
            raise RunNumberException("Bad run number \"%s\"" % number)

        try:
            goodSub = int(subrun)
        except:
            raise RunNumberException("Bad subrun number \"%s\"" % subrun)

        if filename is None:
            filename = cls.DEFAULT_FILE

        try:
            with open(filename, 'w') as fd:
                print >>fd, "%d %d" % (goodRun, goodSub)
        except Exception, exc:
            raise RunNumberException("Cannot update \"%s\" with \"%s %s\": %s" %
                                     (filename, goodRun, goodSub, str(exc)))


def add_arguments(parser):
    parser.add_argument("runNumber",
                        type=int, default=None, nargs="?",
                        help="Last run number")
    parser.add_argument("-s", "--subrun", dest="subrun",
                        type=int, default=0,
                        help="Last subrun number")

def get_or_set_run_number(args):
    (runNum, subrun) = RunNumber.getLast()

    if args.runNumber is None:
        action = "is"
    elif not verify_change(runNum, subrun, args.runNumber, args.subrun):
        action ="not changed from"
    else:
        # update file with new run and subrun numbers
        RunNumber.setLast(args.runNumber, subrun=args.subrun)
        action = "set to"

        # reread file to make sure all is well
        (runNum, subrun) = RunNumber.getLast()

    if subrun == 0:
        print "Run number %s %s" % (action, runNum)
    else:
        print "Run number %s %s (subrun %d)" % (action, runNum, subrun)


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
    elif newsub != 0 and newsub != lastsub:
        prompt = "Are you SURE you want to change the run number from" \
                 " %s to %s?" % (laststr, newstr)
    else:
        prompt = "Are you SURE you want to change the run number from" \
                 " %s to %s?" % (laststr, newstr)

    while True:
        reply = raw_input(prompt + " (y/n) ")
        lreply = reply.strip().lower()
        if lreply == "y" or lreply == "yes":
            return True
        if lreply == "n" or lreply == "no":
            return False

        print >>sys.stderr, "Please answer 'yes' or 'no'"


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    get_or_set_run_number(args)
