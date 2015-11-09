#!/usr/bin/env python

"""
SpadeQueue.py
John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
Started: Tue Aug 11 17:25:20 2009

Functions for putting SPADE data in queue, either 'by hand' (when
run from command line) or programmatically (when imported from, e.g.,
RunSet.py)

If run from 'cron', run as "SpadeQueue.py -a -c"
"""

import datetime
import os
import shutil
import subprocess
import tarfile

from ClusterDescription import ClusterDescription
from LogSorter import LogSorter
from utils.DashXMLLog import DashXMLLog, FileNotFoundException

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")


# save the current run number
CURRENT_RUN_NUMBER = None

# name of file indicating that logs have been queued
FILE_MARKER = "logs-queued"

# 1 GB of log data is too large
TOO_LARGE = 1024 * 1024 * 1024

# name of combined log file
COMBINED_LOG = "combined.log"

def __copySpadeTarFile(logger, copyDir, spadeBaseName, tarFile, dryRun=False):
    copyFile = os.path.join(copyDir, spadeBaseName + ".dat.tar")
    if dryRun:
        print "ln %s %s" % (tarFile, copyFile)
        return

    logger.info("Link or copy %s->%s" % (tarFile, copyFile))
    try:
        os.link(tarFile, copyFile)
    except OSError as e:
        if e.errno == 18:  # Cross-device link
            shutil.copyfile(tarFile, copyFile)
        else:
            raise OSError(str(e) + ": Copy %s to %s" % (tarFile, copyFile))


def __findExecutable(cmd, dryRun=False):
    """Find 'cmd' in the user's PATH"""
    path = os.environ["PATH"].split(":")
    for pdir in path:
        pcmd = os.path.join(pdir, cmd)
        if os.path.exists(pcmd):
            return pcmd

    return None


def __getRunData(runDir):
    time = None
    duration = 0

    runXML = DashXMLLog.parse(runDir)

    try:
        tmp = runXML.getEndTime()
        time = tmp
    except:
        pass

    try:
        delta = runXML.getEndTime() - runXML.getStartTime()
        duration = long(delta.seconds)
    except:
        pass

    return (time, duration)


def __getSize(runDir, runNum, logger=None):
    total = 0
    for f in os.listdir(runDir):
        path = os.path.join(runDir, f)

        if not os.path.isfile(path):
            if logger is not None:
                logger.error("Ignoring run %s subdirectory %s" % (runNum, f))
            continue

        total += os.path.getsize(path)

    return total


def __in_progress(logger, runNum):
    global CURRENT_RUN_NUMBER

    if CURRENT_RUN_NUMBER is None:
        cmd = __findExecutable("livecmd")
        if cmd is None:
            # if we can't find the current run number,
            # assume 'runNum' is current
            logger.error("Cannot find 'livecmd' program")
            return True

        proc = subprocess.Popen([cmd, "check"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True)

        curNum = None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("run:"):
                try:
                    curNum = int(line[4:])
                except:
                    logger.error("Bad livecmd run number line \"%s\"" % line)
                break

        proc.stdout.close()
        proc.wait()

        if curNum is None:
            CURRENT_RUN_NUMBER = -1
        else:
            CURRENT_RUN_NUMBER = curNum

    return CURRENT_RUN_NUMBER == runNum


def __indicate_daq_logs_queued(spadeDir, dryRun=False):
    __touch_file(os.path.join(spadeDir, FILE_MARKER), dryRun=dryRun)


def __sizefmt(size):
    for x in ('bytes', 'KB', 'MB', 'GB'):
        if size < 1024.0:
            return "%3.1f %s" % (size, x)
        size /= 1024.0
    return "%3.1f TB" % size


def __touch_file(f, dryRun=False):
    if dryRun:
        print "touch %s" % f
    else:
        open(f, "w").close()


def __writeSpadeSemaphore(spadeDir, spadeBaseName, dryRun=False):
    semFile = os.path.join(spadeDir, spadeBaseName + ".sem")
    __touch_file(semFile, dryRun=dryRun)


def __writeSpadeTarFile(spadeDir, spadeBaseName, runDir, runNum, logger=None,
                        dryRun=False, force=False):
    # ignore huge directories
    dirsize = __getSize(runDir, runNum, logger=logger)
    if dirsize >= TOO_LARGE and not force:
        if logger is not None:
            logger.error("Not sending %s; %s is too large" %
                         (runDir, __sizefmt(dirsize)))
            return None

    tarBall = os.path.join(spadeDir, spadeBaseName + ".dat.tar")

    if dryRun:
        print "tar cvf %s %s" % (tarBall, runDir)
    else:
        tarObj = tarfile.TarFile(tarBall, "w")
        tarObj.add(runDir, os.path.basename(runDir), True)
        tarObj.close()

    return tarBall


def add_arguments(p):
    p.add_argument("-a", "--check-all", dest="check_all",
                   action="store_true", default=False,
                   help="Queue all unqueued daqrun directories")
    p.add_argument("-C", "--no-combine", dest="no_combine",
                   action="store_true", default=False,
                   help="Do not created a combined log file")
    p.add_argument("-f", "--force", dest="force",
                   action="store_true", default=False,
                   help="Requeue the logs for runs which have already been" +
                   "queued")
    p.add_argument("-n", "--dry-run", dest="dryRun",
                   action="store_true", default=False,
                   help="Don't create any files, just print what would happen")
    p.add_argument("-v", "--verbose", dest="verbose",
                   action="store_true", default=False,
                   help="Print running commentary of program's progress")
    p.add_argument("runNumber", nargs="*")


def check_all(logger, spadeDir, copyDir, logDir, no_combine=False, force=False,
              verbose=False, dryRun=False):
    if logDir is None or not os.path.exists(logDir):
        logger.info("Log directory \"%s\" does not exist" % logDir)
        return

    for f in os.listdir(logDir):
        if f.startswith("daqrun"):
            if os.path.exists(os.path.join(logDir, f, FILE_MARKER)):
                # skip runs which have already been queued
                continue

            try:
                runNum = int(f[6:])
            except:
                logger.error("Bad run directory name \"%s\"" % f)
                continue

            queueForSpade(logger, spadeDir, copyDir, logDir, runNum,
                          no_combine=no_combine, force=force, verbose=verbose,
                          dryRun=dryRun)


def queueForSpade(logger, spadeDir, copyDir, logDir, runNum,
                  no_combine=False, force=False, verbose=False, dryRun=False):
    if logDir is None or not os.path.exists(logDir):
        logger.error("Log directory \"%s\" does not exist" % logDir)
        return

    runDir = os.path.join(logDir, "daqrun%05d" % runNum)
    if runDir is None or not os.path.exists(runDir):
        logger.error("Run directory \"%s\" does not exist" % runDir)
        return

    if spadeDir is None or not os.path.exists(spadeDir):
        logger.error("SPADE directory \"%s\" does not exist" % spadeDir)
        return

    if os.path.exists(os.path.join(runDir, FILE_MARKER)) and \
       not force:
        logger.error(("Logs for run %d have already been queued;" +
                      " Use --force to requeue them") % runNum)
        return

    try:
        (runTime, runDuration) = __getRunData(runDir)
    except FileNotFoundException:
        if __in_progress(logger, runNum):
            # don't try to queue log files from current run
            return
        (runTime, runDuration) = (None, 0)

    if not no_combine:
        logger.error("Writing combined log for run %d" % runNum)
        # if combined log file does not exist, create it
        path = os.path.join(runDir, COMBINED_LOG)
        if not os.path.exists(path):
            ls = LogSorter(runDir, runNum)
            # write to dotfile in case thread dies before it's finished
            tmppath = os.path.join(runDir, "." + COMBINED_LOG)
            with open(tmppath, "w") as fd:
                ls.dumpRun(fd)
            # it's now safe to rename the combined log file
            os.rename(tmppath, path)
            logger.error("Wrote combined log for run %d" % runNum)
        else:
            logger.error("Combined log already exists for run %d" % runNum)
    else:
        logger.error("Not writing combined log for run %d" % runNum)

    if runTime is None:
        runTime = datetime.datetime.now()

    try:
        spadeBaseName = "SPS-pDAQ-run-%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
            (runNum, runTime.year, runTime.month, runTime.day,
             runTime.hour, runTime.minute, runTime.second, runDuration)

        tarFile = __writeSpadeTarFile(spadeDir, spadeBaseName, runDir, runNum,
                                      logger=logger, dryRun=dryRun, force=force)
        if tarFile is not None:
            if copyDir is not None and os.path.exists(copyDir):
                __copySpadeTarFile(logger, copyDir, spadeBaseName, tarFile,
                                   dryRun=dryRun)

            __writeSpadeSemaphore(spadeDir, spadeBaseName, dryRun=dryRun)

            __indicate_daq_logs_queued(runDir, dryRun=dryRun)

            logger.info(("Queued data for SPADE (spadeDir=%s" +
                         ", runDir=%s, runNum=%s)...") %
                        (spadeDir, runDir, runNum))
    except:
        logger.error("FAILED to queue data for SPADE: " + exc_string())


def queue_logs(args):
    import logging

    logging.basicConfig()

    logger = logging.getLogger("spadeQueue")
    logger.setLevel(logging.DEBUG)

    cluster = ClusterDescription()
    spadeDir = cluster.logDirForSpade
    logDir = cluster.daqLogDir
    copyDir = None

    if args.check_all or len(args.runNumber) == 0:
        check_all(logger, spadeDir, copyDir, logDir, no_combine=args.no_combine,
                  force=args.force, verbose=args.verbose, dryRun=args.dryRun)
    else:
        for numstr in args.runNumber:
            runNum = int(numstr)

        queueForSpade(logger, spadeDir, copyDir, logDir, runNum,
                      no_combine=args.no_combine, force=args.force,
                      verbose=args.verbose, dryRun=args.dryRun)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    add_arguments(p)
    args = p.parse_args()

    queue_logs(args)
