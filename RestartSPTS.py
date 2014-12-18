#!/usr/bin/env python
#
# Keep SPTS busy


import MySQLdb
import datetime
import os
import re
import subprocess
import time

from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from DAQLaunch import ConsoleLogger, check_detector_state, \
    check_running_on_expcont, kill, launch

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

# default number of stopless runs
NUM_STOPLESS_NAME = "num_stopless"
NUM_STOPLESS_FLAG = None
NUM_STOPLESS_VALUE = None

# map names to livecmd flags
CONFIG_DATA = {
    RUN_CONFIG_NAME:
        { "flag": RUN_CONFIG_FLAG, "value": RUN_CONFIG_VALUE },
    DURATION_NAME:
        { "flag": DURATION_FLAG, "value": DURATION_VALUE },
    NUM_RUNS_NAME:
        { "flag": NUM_RUNS_FLAG, "value": NUM_RUNS_VALUE },
    NUM_STOPLESS_NAME:
        { "flag": NUM_STOPLESS_FLAG, "value": NUM_STOPLESS_VALUE },
}


def getLiveDBName():
    liveConfigName = ".i3live.conf"
    defaultName = "I3OmDb"

    path = os.path.join(os.environ["HOME"], liveConfigName)
    if os.path.exists(path):
        with open(path, "r") as fd:
            for line in fd:
                if line.startswith("["):
                    ridx = line.find("]")
                    if ridx < 0:
                        print "Bad section marker \"%s\"" % line.rstrip()
                        continue

                    section = line[1:ridx]
                    continue

                if section != "livecontrol":
                    continue

                pos = line.find("=")
                if pos < 0:
                    continue

                if line[:pos].strip() != "dbname":
                    continue

                return line[pos + 1:].strip()

    print "Cannot find %s, assuming Online DB is %s" % \
        (liveConfigName, defaultName)
    return defaultName


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


def isSPTSActive(timeout_minutes, dbName="I3OmDb_test", verbose=False):
    """Return True if there is an active run on SPTS"""

    DBHOST = "dbs"
    DBUSER = "i3omdbro"

    db = MySQLdb.connect(DBHOST, DBUSER, "", dbName)
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    try:
        cmd = "select start, stop from run_summary order by start desc limit 1"
        cursor.execute(cmd)

        dbRow = cursor.fetchone()
        if dbRow is None:
            raise SystemExit("Cannot fetch run summary from " + dbName)

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


def launchSPTS(run_config, verbose=False):
    """Launch the run configuration"""

    if run_config is None:
        raise SystemExit("No run configuration specified")

    check_running_on_expcont("RestartSPTS")
    check_detector_state()

    metaDir = find_pdaq_trunk()
    dashDir = os.path.join(metaDir, "dash")
    cfgDir = find_pdaq_config()

    logger = ConsoleLogger()

    kill(cfgDir, logger)
    launch(cfgDir, dashDir, logger, configName=str(run_config))


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


def setNumberOfRestarts(numRestarts):
    cmd = "livecmd runs per restart"
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, close_fds=True,
                            shell=True)
    proc.stdin.close()

    curNum = None
    for line in proc.stdout:
        line = line.rstrip()
        try:
            curNum = int(line)
        except ValueError:
            raise SystemExit("Bad number '%s' for runs per restart" % line)

    proc.stdout.close()
    proc.wait()

    if curNum != numRestarts:
        print "Setting runs per restart to %d" % numRestarts
        cmd = "livecmd runs per restart %d" % numRestarts
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()
        for line in proc.stdout:
            print line.rstrip()
        proc.stdout.close()
        proc.wait()


def startRuns(numStopless=None, verbose=False):
    """Start an unlimited set of runs"""

    # if we want continuous runs, make sure to tell Live
    if numStopless is not None:
        setNumberOfRestarts(numStopless - 1)

    # build the default configuration values
    config = {}
    for k, vdict in CONFIG_DATA.iteritems():
        if vdict["flag"] is not None and vdict["value"] is not None:
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
        if CONFIG_DATA[k]["flag"] is not None and v is not None:
            args.append(CONFIG_DATA[k]["flag"])
            args.append(str(v))

    if verbose:
        print str(args)

    rtn = subprocess.call(args)
    if rtn != 0:
        raise SystemExit("Failed to start SPTS runs")


if __name__ == "__main__":
    import argparse

    from utils.Machineid import Machineid

    hostid = Machineid()
    if hostid.is_sps_cluster():
        raise SystemExit("This script should not be run on SPS")
    if hostid.is_build_host():
        raise SystemExit("This script should not be run on access")

    p = argparse.ArgumentParser()

    p.add_argument("-D", "--dbname", dest="dbName",
                   help="Name of database to check")
    p.add_argument("-f", "--force", dest="force",
                   action="store_true", default=False,
                   help="kill components even if there is an active run")
    p.add_argument("-v", "--verbose", dest="verbose",
                   action="store_true", default=False,
                   help="Log output for all components to terminal")

    args = p.parse_args()

    idle_minutes = 2 * 60    # two hours
    if isPaused():
        if args.verbose:
            print "SPTS is paused"
    else:
        dbName = args.dbName
        if dbName is None:
            dbName = getLiveDBName()
        if args.force or not isSPTSActive(idle_minutes, dbName=dbName,
                                          verbose=args.verbose):
            startRuns(numStopless=NUM_STOPLESS_VALUE, verbose=args.verbose)
        elif args.verbose:
            print "SPTS is active"
