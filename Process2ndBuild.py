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
import fnmatch


MAX_FILES_PER_TARBALL = 50
TARGET_DIR = "/mnt/data/pdaqlocal"
TARGET_DIR_SN = "/mnt/data/sndata/tmp/"
TARGET_DIR_SN_BACKUP = TARGET_DIR_SN + "backup/"


def checkForRunningProcesses(progname):
    c = os.popen("pgrep -fl 'python .+%s'" % progname, "r")
    l = c.read()
    num = len(l.split('\n'))
    if num < 3:
        return False  # get extra \n at end of command
    return True


def isTargetFile(f):
    match = re.search(r'(\w+)_\d+_\d+_\d+_\d+\.dat', f)
    if match:
        ftype = match.group(1)
        if ftype != "moni" and ftype != "sn" and ftype != "tcal":
            return False
        return True
    return False

def processFiles(matchingFiles, verbose=False, dryRun=False):
    # Make list for tarball - restrict total number of files
    filesToTar = []
    while len(matchingFiles) > 0:
        filesToTar.append(matchingFiles[0])
        del matchingFiles[0]
        if len(filesToTar) >= MAX_FILES_PER_TARBALL:
            break

    for f in filesToTar:
        if "sn_" in f:
            generateHardlinksSN(f, verbose=verbose)
        else:
            break

    if len(filesToTar) == 0:
        return False

    if verbose: print "Found %d files" % len(filesToTar)
    t = datetime.datetime.now()
    dateTag = "%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
        (0, t.year, t.month, t.day, t.hour, t.minute, t.second, 0)
    front = "SPS-pDAQ-2ndBld-"
    spadeTar = front + dateTag + ".dat.tar"
    moniLink = front + dateTag + ".mon.tar"
    snLink = front + dateTag + ".sn.tar"
    moniSem = front + dateTag + ".msem"
    spadeSem = front + dateTag + ".sem"

    # Duplicate file: wait for a new second, recalculate everything:
    if os.path.exists(spadeTar):
        time.sleep(1)
        return True

    # Create temporary tarball
    tmpTar = "tmp-" + dateTag + ".tar"
    if verbose: print "Creating temporary tarball"
    try:
        if not dryRun: tarball = tarfile.open(tmpTar, "w")
        for toAdd in filesToTar:
            if verbose: print "  " + toAdd
            if not dryRun: tarball.add(toAdd)
        if not dryRun: tarball.close()
    except:
        os.unlink(tmpTar)
        raise
    if verbose: print "Done."

    # Rename temporary tarball to SPADE name
    if verbose: print "Renaming temporary tarball to %s" % spadeTar
    os.rename(tmpTar, spadeTar)

    # Create moni hard link
    if verbose: print "MoniLink %s" % moniLink
    if not dryRun: os.link(spadeTar, moniLink)

    # Create sn hard link
    if verbose: print "SNLink %s" % snLink
    if not dryRun: os.link(spadeTar, snLink)
    # So that SN process can delete if it's not running as pdaq
    if not dryRun: os.chmod(snLink, 0666)

    # Create spade .sem
    if not dryRun: f = open(spadeSem, "w")
    if not dryRun: f.close()

    # Create monitoring .msem
    if not dryRun: f = open(moniSem, "w")
    if not dryRun: f.close()

    # Clean up tar'ed files
    for toAdd in filesToTar:
        if verbose: print "Removing %s..." % toAdd
        if not dryRun: os.unlink(toAdd)

    return True


def generateHardlinksSN(f, verbose):
        if verbose: print "Creating links for %s" % f
        os.link(f, TARGET_DIR_SN + f)
        os.link(f, TARGET_DIR_SN_BACKUP + f)

def main(verbose=False, dryRun=False):
    os.chdir(TARGET_DIR)

    # Get list of available files, matching target tar pattern:
    matchingFiles = []
    for f in os.listdir(TARGET_DIR):
        if isTargetFile(f):
            matchingFiles.append(f)

    matchingFiles.sort(lambda x, y: (cmp(os.stat(x)[8], os.stat(y)[8])))

    running = True
    while running:
        try:
            if not processFiles(matchingFiles, verbose=verbose, dryRun=dryRun):
                running = False
        except KeyboardInterrupt:
            running = False
        #except: pass


if __name__ == "__main__":
    import optparse
    import sys

    # Make sure I'm not already running - so I can auto-restart out of crontab
    if checkForRunningProcesses(os.path.basename(sys.argv[0])):
        raise SystemExit

    op = optparse.OptionParser()
    op.add_option("-n", "--dry-run", dest="dryRun",
                  action="store_true", default=False,
                  help="Do not actually do anything")
    op.add_option("-q", "--quiet", dest="verbose",
                  action="store_false", default=True,
                  help="Do not print log of actions to console")
    op.add_option("-v", "--verbose", dest="verbose",
                  action="store_true", default=True,
                  help="Print log of actions to console (default)")

    opt, args = op.parse_args()

    main(verbose=opt.verbose, dryRun=opt.dryRun)
