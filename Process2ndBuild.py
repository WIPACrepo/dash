#!/usr/bin/env python

"""
Process2ndBuild.py
Jacobsen, back in the 2007's or so

This script is installed on 2ndbuild, collects the output of 2ndbuild
as it appears on /mnt/data/pdaqlocal, tars them in groups as they
appear, makes hard links for I3Moni, SNDAQ and SPADE, and puts the
appropriate semaphores in place.

It should be installed and activated (in cron) by the pDAQ Fabric
installation procedure.
"""

import datetime
import os
import re
import tarfile
import time


MAX_FILES_PER_TARBALL = 50


def check_for_running_processes(progname):
    c = os.popen("pgrep -fl 'python .+%s'" % progname, "r")
    l = c.read()
    num = len(l.split('\n'))
    if num < 3:
        return False  # get extra \n at end of command
    return True


def is_target_file(f):
    "Does this file start with 'moni', 'sn', or 'tcal'?"
    if f is not None:
        if f.startswith("moni_") or f.startswith("sn_") or \
             f.startswith("tcal_"):
            return True
            return True
    return False


def process_files(matchingFiles, verbose=False, dry_run=False,
                  enable_moni_link=False):
    # Make list for tarball - restrict total number of files
    files_to_tar = []
    while len(matchingFiles) > 0:
        files_to_tar.append(matchingFiles[0])
        del matchingFiles[0]
        if len(files_to_tar) >= MAX_FILES_PER_TARBALL:
            break

    if len(files_to_tar) == 0:
        return False

    if verbose:
        print "Found %d files" % len(files_to_tar)
    t = datetime.datetime.now()
    dateTag = "%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
        (0, t.year, t.month, t.day, t.hour, t.minute, t.second, 0)
    front = "SPS-pDAQ-2ndBld-" + dateTag
    spade_tar = front + ".dat.tar"
    spade_sem = front + ".sem"
    moniLink = front + ".mon.tar"
    moni_sem = front + ".msem"
    snLink = front + ".sn.tar"

    # Duplicate file: wait for a new second, recalculate everything:
    if os.path.exists(spade_tar):
        time.sleep(1)
        return True

    # Create temporary tarball
    tmp_tar = "tmp-" + dateTag + ".tar"
    if verbose:
        print "Creating temporary tarball"
    try:
        if not dry_run: tarball = tarfile.open(tmp_tar, "w")
        for tfile in files_to_tar:
            if verbose: print "  " + tfile
            if not dry_run: tarball.add(tfile)
        if not dry_run: tarball.close()
    except:
        os.unlink(tmp_tar)
        raise
    if verbose:
        print "Done."

    # Rename temporary tarball to SPADE name
    if verbose:
        print "Renaming temporary tarball to %s" % spade_tar
    if not dry_run:
        os.rename(tmp_tar, spade_tar)

    # Create moni hard link
    if enable_moni_link:
        if verbose:
            print "MoniLink %s" % moniLink
        if not dry_run:
            os.link(spade_tar, moniLink)

    # Create sn hard link
    if verbose:
        print "SNLink %s" % snLink
    if not dry_run:
        os.link(spade_tar, snLink)
        # So that SN process can delete if it's not running as pdaq
        os.chmod(snLink, 0666)

    # Create spade .sem
    if not dry_run:
        f = open(spade_sem, "w")
        f.close()

    # Create monitoring .msem
    if enable_moni_link and not dry_run:
        f = open(moni_sem, "w")
        f.close()

    # Clean up tar'ed files
    for toAdd in files_to_tar:
        if verbose:
            print "Removing %s..." % toAdd
        if not dry_run:
            os.unlink(toAdd)

    return True


def main(spadeDir, verbose=False, dry_run=False, enable_moni_link=False):
    os.chdir(spadeDir)

    # Get list of available files, matching target tar pattern:
    matchingFiles = []
    for f in os.listdir(spadeDir):
        if is_target_file(f):
            matchingFiles.append(f)

    matchingFiles.sort(lambda x, y: (cmp(os.stat(x)[8], os.stat(y)[8])))

    running = True
    while running:
        try:
            if not process_files(matchingFiles, verbose=verbose,
                                 dry_run=dry_run,
                                 enable_moni_link=enable_moni_link):
                running = False
        except KeyboardInterrupt:
            running = False
        #except: pass


if __name__ == "__main__":
    import argparse
    import sys

    from ClusterDescription import ClusterDescription

    # Make sure I'm not already running - so I can auto-restart out of crontab
    if check_for_running_processes(os.path.basename(sys.argv[0])):
        raise SystemExit

    op = argparse.ArgumentParser()
    op.add_argument("-d", "--spadedir", dest="spadedir",
                    action="store", default=None,
                    help="SPADE directory")
    op.add_argument("-m", "--enable-moni-link", dest="enable_moni_link",
                    action="store_true", default=False,
                    help="Include moni files and create a moni link")
    op.add_argument("-n", "--dry-run", dest="dry_run",
                    action="store_true", default=False,
                    help="Do not actually do anything")
    op.add_argument("-q", "--quiet", dest="verbose",
                    action="store_false", default=False,
                    help="Do not print log of actions to console")
    op.add_argument("-v", "--verbose", dest="verbose",
                    action="store_true", default=False,
                    help="Print log of actions to console (default)")

    args = op.parse_args()

    if args.spadedir is None:
        cluster = ClusterDescription()
        spadeDir = cluster.logDirForSpade

    main(spadeDir, verbose=args.verbose, dry_run=args.dry_run,
         enable_moni_link=args.enable_moni_link)
