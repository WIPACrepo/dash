#!/usr/bin/env python

"""
SpadeQueue.py
John Jacobsen, NPX Designs, Inc., john@mail.npxdesigns.com
Started: Tue Aug 11 17:25:20 2009

Functions for putting SPADE data in queue, either 'by hand' (when
run from command line) or programmatically (when imported from, e.g.,
RunSet.py)
"""

import datetime, os, shutil, sys, tarfile

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

def __copySpadeTarFile(logger, copyDir, spadeBaseName, tarFile):
    copyFile = os.path.join(copyDir, spadeBaseName + ".dat.tar")
    logger.info("Link or copy %s->%s" % (tarFile, copyFile))

    try:
        os.link(tarFile, copyFile)
    except OSError, e:
        if e.errno == 18: # Cross-device link
            shutil.copyfile(tarFile, copyFile)
        else:
            raise

def __writeSpadeSemaphore(spadeDir, spadeBaseName):
    semFile = os.path.join(spadeDir, spadeBaseName + ".sem")
    fd = open(semFile, "w")
    fd.close()

def __writeSpadeTarFile(spadeDir, spadeBaseName, runDir):
    tarBall = os.path.join(spadeDir, spadeBaseName + ".dat.tar")

    tarObj = tarfile.TarFile(tarBall, "w")
    tarObj.add(runDir, os.path.basename(runDir), True)
    tarObj.close()

    return tarBall

def queueForSpade(logger, spadeDir, copyDir, runDir, runNum, runTime,
                  runDuration):
    if runDir is None or not os.path.exists(runDir):
        logger.info("Run directory \"%s\" does not exist" % runDir)
        return

    if spadeDir is None or not os.path.exists(spadeDir):
        logger.info("SPADE directory \"%s\" does not exist" % spadeDir)
        return

    try:
        spadeBaseName = "SPS-pDAQ-run-%03d_%04d%02d%02d_%02d%02d%02d_%06d" % \
            (runNum, runTime.year, runTime.month, runTime.day,
             runTime.hour, runTime.minute, runTime.second, runDuration)

        tarFile = __writeSpadeTarFile(spadeDir, spadeBaseName, runDir)

        if copyDir is not None and os.path.exists(copyDir):
            __copySpadeTarFile(logger, copyDir, spadeBaseName, tarFile)

        semFile = __writeSpadeSemaphore(spadeDir, spadeBaseName)

        logger.info(("Queued data for SPADE (spadeDir=%s" +
                     ", runDir=%s, runNum=%s)...") %
                    (spadeDir, runDir, runNum))
    except:
        logger.error("FAILED to queue data for SPADE: " + exc_string())

if __name__ == "__main__":
    import logging
    if len(sys.argv) < 2:
        print >>sys.stderr, "Usage: %s runNumber" % sys.argv[0]
        raise SystemExit
    runNum = int(sys.argv[1])
    logging.basicConfig()

    logger = logging.getLogger("spadeQueue")
    logger.setLevel(logging.DEBUG)
    queue_for_spade(logger,
                    "/mnt/data/pdaqlocal/viaTDRSS",
                    None,
                    "/mnt/data/pdaq/log/daqrun%05d" % runNum,
                    runNum,
                    datetime.utcnow(),
                    0)
