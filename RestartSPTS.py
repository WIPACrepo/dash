#!/usr/bin/env python
#
# Keep SPTS busy


import MySQLdb
import datetime
import os
import re
import subprocess
import time


# location of SPTS restart configuration file
CONFIG_FILE = os.path.join(os.environ["HOME"], ".spts_restart_config")
# location of pause file
PAUSED_FILE = os.path.join(os.environ["HOME"], ".paused")

# default run configuration
RUN_CONFIG_NAME = "run_config"
RUN_CONFIG_FLAG = "-d"
RUN_CONFIG_VALUE = "spts64-dirtydozen-hlc-006"

# default duration
DURATION_NAME = "duration"
DURATION_FLAG = "-l"
DURATION_VALUE = "8h"

# default number of runs (None == use livecmd default)
NUM_RUNS_NAME = "num_runs"
NUM_RUNS_FLAG = "-n"
NUM_RUNS_VALUE = None

# map names to livecmd flags
CONFIG_DATA = {
    RUN_CONFIG_NAME:
        { "flag": RUN_CONFIG_FLAG, "value": RUN_CONFIG_VALUE },
    DURATION_NAME:
        { "flag": DURATION_FLAG, "value": DURATION_VALUE },
    NUM_RUNS_NAME:
        { "flag": NUM_RUNS_FLAG, "value": NUM_RUNS_VALUE },
}


# stolen from live/misc/util.py
def getDurationFromString(s):
    """
    Return duration in seconds based on string <s>
    """
    m = re.search('^(\d+)$', s)
    if m:
        return int(m.group(1))
    m = re.search('^(\d+)s(?:ec(?:s)?)?$', s)
    if m:
        return int(m.group(1))
    m = re.search('^(\d+)m(?:in(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 60
    m = re.search('^(\d+)h(?:r(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 3600
    m = re.search('^(\d+)d(?:ay(?:s)?)?$', s)
    if m:
        return int(m.group(1)) * 86400
    raise ValueError('String "%s" is not a known duration format.  Try'
                     '30sec, 10min, 2days etc.' % s)


def isPaused():
    """
    Return True if there is a ~/.paused file and the specified time
    has not elapsed
    """

    # get the time the file was written
    try:
        stat = os.stat(PAUSED_FILE)
    except OSError, err:
        # if the file doesn't exist, we're not paused
        return False

    # get the number of paused minutes
    pause_minutes = 0
    with open(PAUSED_FILE, "r") as fd:
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
        os.unlink(PAUSED_FILE)
    except:
        pass

    # we're not paused!
    return False


def isSPTSActive(timeout_minutes, verbose=False):
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
            MAX_DURATION_MINUTES = 8 * 60

            minutes = minuteDiff(now, startTime)
            if verbose:
                print "start %s min %d dur %d timeout %d" % \
                    (str(startTime), minutes, MAX_DURATION_MINUTES,
                     timeout_minutes)
            return minutes < MAX_DURATION_MINUTES + timeout_minutes

        raise SystemExit("Most recent run summary has null start and stop")
    finally:
        cursor.close()


def launch(run_config, verbose=False):
    """Launch the run configuration"""

    launch = os.path.join(os.environ["HOME"], "pDAQ_current", "dash",
                          "DAQLaunch.py")
    if run_config is None:
        raise SystemExit("No run configuration specified")

    if verbose:
        print "Launching %s" % str(run_config)
    rtn = subprocess.call([launch, "-c", run_config])
    if rtn != 0:
        raise SystemExit("Failed to launch " + run_config)


def minuteDiff(now, then):
    """Return the number of minutes between two datetimes"""
    diff = now - then
    return diff.days * 1440 + diff.seconds / 60


def readConfig(filename, config):
    # regular expression used to split apart keys and values
    DATA_PAT = re.compile(r"^\s*(\S+)\s*[:=]\s*(\S.*)\s*$")

    success = True
    if os.path.exists(filename):
        with open(filename, "r") as fd:
            for line in fd:
                line = line.strip()
                if line == "" or line.startswith("#"):
                    continue

                m = DATA_PAT.match(line)
                if m is None:
                    print "Bad %s line: %s" % (filename, line.rstrip())
                    success = False
                    continue

                key = m.group(1)
                if not key in CONFIG_DATA:
                    print "Unknown %s field \"%s\"" % (filename, key)
                    success = False
                    continue

                try:
                    val = int(m.group(2))
                except:
                    val = m.group(2)

                config[key] = val

    return success


def startRuns(verbose=False):
    """Start an unlimited set of runs"""

    # build the default configuration values
    config = {}
    for k, vdict in CONFIG_DATA.iteritems():
        if vdict["value"] is not None:
            config[k] = vdict["value"]

    # load config values from filesystem
    if not readConfig(CONFIG_FILE, config):
        raise SystemExit("Failed to read %s" % CONFIG_FILE)

    launch(config[RUN_CONFIG_NAME], verbose=verbose)

    # wait a bit for the launch to finish
    time.sleep(5)

    # start runs
    args = ["livecmd", "start", "daq", ]
    for k, v in config.iteritems():
        if k == DURATION_NAME:
            v = getDurationFromString(v)
        if v is not None:
            args.append(CONFIG_DATA[k]["flag"])
            args.append(str(v))

    if verbose:
        print " ".join(args)

    rtn = subprocess.call(args)
    if rtn != 0:
        raise SystemExit("Failed to start SPTS runs")


if __name__ == "__main__":
    import socket

    hname = socket.gethostname()
    if not hname.endswith("spts.icecube.wisc.edu"):
        raise SystemExit("This script should only be run on SPTS")

    verbose = False

    idle_minutes = 2 * 60    # two hours
    if not isPaused():
        if not isSPTSActive(idle_minutes, verbose=verbose):
            startRuns(verbose=verbose)
        elif verbose:
            print "SPTS is active"
    elif verbose:
        print "SPTS is paused"
