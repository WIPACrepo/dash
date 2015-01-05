#!/usr/bin/env python
#
# Manage pdaq's `pDAQ_current` symlink


import os
import stat


CURRENT = "pDAQ_current"


def add_arguments(parser):
    parser.add_argument("directory",
                        nargs="?",
                        help="New workspace")


def workspace(args):
    # set up some standard locations
    home = os.environ["HOME"]
    current = os.path.join(home, CURRENT)

    try:
        cstat = os.lstat(current)
    except OSError:
        cstat = None

    # if ~/pDAQ_current exists and is not a symlink...
    if cstat is not None and not stat.S_ISLNK(cstat.st_mode):
        if stat.S_ISDIR(cstat.st_mode):
            msg = "%s is a directory" % current
        else:
            msg = "%s is neither a symlink not a directory" % current
        raise SystemExit("Cannot change workspace; " + msg)

    # if nothing was specified...
    if args.directory is None:
        if cstat is None:
            raise SystemExit("%s does not exist" % current)

        # print the current link and exit
        print os.readlink(current)
        return

    # make sure the target directory exists
    try:
        tstat = os.lstat(args.directory)
    except OSError:
        raise SystemExit("%s does not exist" % args.directory)

    if not stat.S_ISDIR(tstat.st_mode):
        raise SystemExit("%s is not a directory" % args.directory)

    if cstat is None:
        os.symlink(args.directory, current)
        print "%s linked to %s" % (CURRENT, args.directory)
        return

    cabs = os.path.realpath(current)
    tabs = os.path.realpath(args.directory)
    if cabs == tabs:
        raise SystemExit("%s already linked to %s" % (current, args.directory))

    oldlink = os.readlink(current)
    os.unlink(current)
    os.symlink(args.directory, current)
    print "%s moved from %s to %s" % (CURRENT, oldlink, args.directory)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()

    add_arguments(p)

    args = p.parse_args()

    workspace(args)