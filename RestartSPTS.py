#!/usr/bin/env python
#
# Keep SPTS busy


import MySQLdb
import datetime
import os
import subprocess
import time


RUN_CONFIG = "spts64-dirtydozen-hlc-006"
MAX_RUN_MINUTES = 8 * 60    # eight hours


def isPaused():
    """
    Return True if there is a ~/.paused file and the specified time
    has not elapsed
    """

    # get the time the file was written
    path = os.path.join(os.environ["HOME"], ".paused")
    try:
        stat = os.stat(path)
    except OSError, err:
        # if the file doesn't exist, we're not paused
        return False

    # get the number of paused minutes
    pause_minutes = 0
    with open(path, "r") as fd:
        for line in fd:
            line = line.rstrip()

            try:
                tmp = int(line)
                pause_minutes += tmp
            except:
                print >> sys.stderr, "Bad 'paused' line: " + line

    # get the number of minutes since the file was written
    modtime_minutes = (time.time() - stat.st_mtime) / 60.0

    # if still paused, return True
    if modtime_minutes < pause_minutes:
        return True

    # remove expired file
    try:
        os.unlink(path)
    except:
        pass

    # we're not paused!
    return False


def isSPTSActive(timeout_minutes):
    """Return True if there is an active run on SPTS"""

    DBHOST = "dbs"
    DBUSER = "i3omdbro"
    DBNAME = "I3OmDb_test"

    db = MySQLdb.connect(DBHOST, DBUSER, "", DBNAME)
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    try:
        cmd = "select start, stop from run_summary order by start desc limit 1"
        cursor.execute(cmd)

        dbRow = cursor.fetchone()
        if dbRow is None:
            raise SystemExit("Cannot fetch run summary from " + DBNAME)

        now = datetime.datetime.now()

        stopTime = dbRow["stop"]
        if stopTime is not None:
            minutes = minuteDiff(now, stopTime)
            return minutes < timeout_minutes

        startTime = dbRow["start"]
        if startTime is not None:
            minutes = minuteDiff(now, startTime)
            return minutes < MAX_RUN_MINUTES + timeout_minutes

        raise SystemExit("Most recent run summary has null start and stop")
    finally:
        cursor.close()


def minuteDiff(now, then):
    """Return the number of minutes between two datetimes"""
    diff = now - then
    return diff.days * 1440 + diff.seconds / 60


def startRuns():
    """Start an unlimited set of runs"""

    # launch the config
    launch = os.path.join(os.environ["HOME"], "pDAQ_current", "dash",
                          "DAQLaunch.py")
    rtn = subprocess.call([launch, "-c", RUN_CONFIG])
    if rtn != 0:
        raise SystemExit("Failed to launch " + RUN_CONFIG)

    # wait a bit for the launch to finish
    time.sleep(5)

    # start unlimited runs
    rtn = subprocess.call(["livecmd", "start", "daq", "-d", RUN_CONFIG])
    if rtn != 0:
        raise SystemExit("Failed to start " + RUN_CONFIG)


if __name__ == "__main__":
    import socket

    hname = socket.gethostname()
    if not hname.endswith("spts.icecube.wisc.edu"):
        raise SystemExit("This script should only be run on SPTS")

    idle_minutes = 2 * 60    # two hours
    if not isPaused():
        if not isSPTSActive(idle_minutes):
            startRuns()
