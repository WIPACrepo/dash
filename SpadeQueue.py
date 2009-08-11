#!/usr/bin/env python

"""
SpadeQueue.py
John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
Started: Tue Aug 11 17:25:20 2009

Functions for putting SPADE data in queue, either 'by hand' (when
run from command line) or programmatically (when imported from, e.g.,
DAQRun.py)
"""

from os.path    import exists
from exc_string import exc_string
from datetime   import datetime
from tarfile    import TarFile
from sys        import argv
from shutil     import move, copyfile

def logDirName(runNum):
    "Get log directory name, not including loggingDir portion of path"
    return "daqrun%05d" % runNum

def get_base_prefix(runNum, runTime, runDuration):
    """
    >>> get_base_prefix(666, datetime(2009,8,11,22,29,25), 100)
    'SPS-pDAQ-run-666_20090811_222925_000100'
    """
    return "SPS-pDAQ-run-%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
           (runNum, runTime.year, runTime.month, runTime.day, runTime.hour,
            runTime.minute, runTime.second, runDuration)

def linkOrCopy(src, dest):
    try:
        os.link(src, dest)
    except OSError, e:
        if e.errno == 18: # Cross-device link
            copyfile(src, dest)
        else:
            raise

def queue_for_spade(logger, spadeDir, copyDir, logTopLevel,
                    runNum, runTime, runDuration, moveCatchall=True):
    """
    Put tarball of log and moni files in SPADE directory as well as
    semaphore file to indicate to SPADE to effect the transfer
    """
    if not spadeDir: return
    if not exists(spadeDir): return
    logger.info(("Queueing data for SPADE (spadeDir=%s, logDir=%s," +
                " runNum=%d)...") % (spadeDir, logTopLevel, runNum))
    runDir = logDirName(runNum)
    basePrefix = get_base_prefix(runNum, runTime, runDuration)
    try:
        move_spade_files(logger, copyDir, basePrefix,
                         logTopLevel, runDir, spadeDir, moveCatchall)
    except Exception:
        logger.error("FAILED to queue data for SPADE: %s" % exc_string())

def move_spade_files(logger, copyDir, basePrefix,
                     logTopLevel, runDir, spadeDir, moveCatchall):
    tarBall = "%s/%s.dat.tar" % (spadeDir, basePrefix)
    semFile = "%s/%s.sem"     % (spadeDir, basePrefix)
    logger.info("Target files are:\n%s\n%s" % (tarBall, semFile))
    if moveCatchall:
        move("%s/catchall.log" % logTopLevel, "%s/%s" % (logTopLevel, runDir))
    tarObj = TarFile(tarBall, "w")
    tarObj.add("%s/%s" % (logTopLevel, runDir), runDir, True)
    tarObj.close()
    if copyDir:
        copyFile = "%s/%s.dat.tar" % (copyDir, basePrefix)
        logger.info("Link or copy %s->%s" % (tarBall, copyFile))
        linkOrCopy(tarBall, copyFile)
    fd = open(semFile, "w")
    fd.close()

if __name__ == "__main__":
    import logging
    if len(argv) < 2:
        print "Must supply run number argument"
        raise SystemExit
    runNum = int(argv[1])
    logging.basicConfig(level=logging.DEBUG,)
    logging.debug(runNum)
    queue_for_spade(logging,
                    "/mnt/data/pdaqlocal/viaTDRSS",
                    None,
                    "/mnt/data/pdaq/log",
                    runNum,
                    datetime.utcnow(),
                    0,
                    moveCatchall=False)
