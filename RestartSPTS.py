#!/usr/bin/env python
"""
Utility script which keeps SPTS busy
"""

from __future__ import print_function

import datetime
import os
import re
import subprocess
import sys
import time

import MySQLdb

from locate_pdaq import find_pdaq_config, find_pdaq_trunk
from DAQLaunch import ConsoleLogger, check_detector_state, kill, launch


# location of SPTS restart configuration file
CONFIG_FILE = os.path.join(os.environ["HOME"], ".spts_restart_config")
# location of pause file
PAUSED_FILE = os.path.join(os.environ["HOME"], ".paused")

# default run configuration
RUN_CONFIG_NAME = "run_config"
RUN_CONFIG_FLAG = "-d"
RUN_CONFIG_VALUE = "replay-125659-local"

# default duration
DURATION_NAME = "duration"
DURATION_FLAG = "-l"
DURATION_VALUE = "160m"

# default number of runs (None == use livecmd default)
NUM_RUNS_NAME = "num_runs"
NUM_RUNS_FLAG = "-n"
NUM_RUNS_VALUE = None

# default number of stopless runs
NUM_STOPLESS_NAME = "num_stopless"
NUM_STOPLESS_FLAG = None
NUM_STOPLESS_VALUE = 3

# map names to livecmd flags
CONFIG_DATA = {
    RUN_CONFIG_NAME: {
        "flag": RUN_CONFIG_FLAG,
        "value": RUN_CONFIG_VALUE
    },
    DURATION_NAME: {
        "flag": DURATION_FLAG,
        "value": DURATION_VALUE
    },
    NUM_RUNS_NAME: {
        "flag": NUM_RUNS_FLAG,
        "value": NUM_RUNS_VALUE
    },
    NUM_STOPLESS_NAME: {
        "flag": NUM_STOPLESS_FLAG,
        "value": NUM_STOPLESS_VALUE
    },
}


def get_live_db_name():
    live_config_name = ".i3live.conf"
    default_name = "I3OmDb"

    path = os.path.join(os.environ["HOME"], live_config_name)
    if os.path.exists(path):
        with open(path, "r") as fin:
            for line in fin:
                if line.startswith("["):
                    ridx = line.find("]")
                    if ridx < 0:
                        print("Bad section marker \"%s\"" % line.rstrip())
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

    print("Cannot find %s, assuming Online DB is %s" %
          (live_config_name, default_name))
    return default_name


# stolen from live/misc/util.py
def get_duration_from_string(dstr):
    """
    Return duration in seconds based on string <s>
    """
    mtch = re.search(r'^(\d+)$', dstr)
    if mtch is not None:
        return int(mtch.group(1))
    mtch = re.search(r'^(\d+)s(?:ec(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1))
    mtch = re.search(r'^(\d+)m(?:in(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1)) * 60
    mtch = re.search(r'^(\d+)h(?:r(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1)) * 3600
    mtch = re.search(r'^(\d+)d(?:ay(?:s)?)?$', dstr)
    if mtch is not None:
        return int(mtch.group(1)) * 86400
    raise ValueError('String "%s" is not a known duration format.  Try'
                     '30sec, 10min, 2days etc.' % dstr)


def is_paused():
    """
    Return True if there is a ~/.paused file and the specified time
    has not elapsed
    """

    # get the time the file was written
    try:
        stat = os.stat(PAUSED_FILE)
    except OSError:
        # if the file doesn't exist, we're not paused
        return False

    # get the number of paused minutes
    pause_minutes = 0
    with open(PAUSED_FILE, "r") as fin:
        for line in fin:
            line = line.rstrip()

            try:
                pause_minutes += int(line)
            except ValueError:
                print("Bad 'paused' line: " + line, file=sys.stderr)

    # get the number of minutes since the file was written
    modtime_minutes = (time.time() - stat.st_mtime) / 60.0

    # if still paused, return True
    if modtime_minutes < pause_minutes:
        return True

    # remove expired file
    try:
        os.unlink(PAUSED_FILE)
    except OSError:
        pass

    # we're not paused!
    return False


def is_spts_active(timeout_minutes, db_name="I3OmDb_test", verbose=False):
    """Return True if there is an active run on SPTS"""

    dbhost = "dbs"
    dbuser = "i3omdbro"

    dbconn = MySQLdb.connect(dbhost, dbuser, "", db_name)
    cursor = dbconn.cursor(MySQLdb.cursors.DictCursor)
    try:
        cmd = "select start, stop from run_summary order by start desc limit 1"
        cursor.execute(cmd)

        dbrow = cursor.fetchone()
        if dbrow is None:
            raise SystemExit("Cannot fetch run summary from " + db_name)

        now = datetime.datetime.now()

        stop_time = dbrow["stop"]
        if stop_time is not None:
            minutes = minute_diff(now, stop_time)
            return minutes < timeout_minutes

        start_time = dbrow["start"]
        if start_time is not None:
            max_duration = 8 * 60  # eight hours

            minutes = minute_diff(now, start_time)
            if verbose:
                print("start %s min %d dur %d timeout %d" %
                      (start_time, minutes, max_duration, timeout_minutes))
            return minutes < max_duration + timeout_minutes

        raise SystemExit("Most recent run summary has null start and stop")
    finally:
        cursor.close()


class FakeArguments(object):
    def __init__(self, config_name, verbose):
        self.config_name = config_name
        self.verbose = verbose


def launch_spts(run_config, verbose=False):
    """Launch the run configuration"""

    if run_config is None:
        raise SystemExit("No run configuration specified")

    check_detector_state()

    meta_dir = find_pdaq_trunk()
    dash_dir = os.path.join(meta_dir, "dash")
    cfg_dir = find_pdaq_config()

    logger = ConsoleLogger()

    args = FakeArguments(str(run_config), verbose)

    kill(cfg_dir, logger, args=args)
    launch(cfg_dir, dash_dir, logger, args=args)


def minute_diff(now, then):
    """Return the number of minutes between two datetimes"""
    diff = now - then
    return diff.days * 1440 + diff.seconds / 60


def read_config(filename, config):
    # regular expression used to split apart keys and values
    data_pat = re.compile(r"^\s*(\S+)\s*[:=]\s*(\S.*)\s*$")

    success = True
    if os.path.exists(filename):
        with open(filename, "r") as fin:
            for line in fin:
                line = line.strip()
                if line == "" or line.startswith("#"):
                    continue

                mtch = data_pat.match(line)
                if mtch is None:
                    print("Bad %s line: %s" % (filename, line.rstrip()))
                    success = False
                    continue

                key = mtch.group(1)
                if key not in CONFIG_DATA:
                    print("Unknown %s field \"%s\"" % (filename, key))
                    success = False
                    continue

                try:
                    val = int(mtch.group(2))
                except ValueError:
                    val = mtch.group(2)

                config[key] = val

    return success


def set_number_of_restarts(num_restarts):
    cmd = "livecmd runs per restart"
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, close_fds=True,
                            shell=True)
    proc.stdin.close()

    cur_num = None
    for line in proc.stdout:
        line = line.rstrip()
        try:
            cur_num = int(line)
        except ValueError:
            raise SystemExit("Bad number '%s' for runs per restart" % line)

    proc.stdout.close()
    proc.wait()

    if cur_num != num_restarts:
        print("Setting runs per restart to %d" % num_restarts)
        cmd = "livecmd runs per restart %d" % num_restarts
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True,
                                shell=True)
        proc.stdin.close()
        for line in proc.stdout:
            print(line.rstrip())
        proc.stdout.close()
        proc.wait()


def start_runs(num_stopless=None, verbose=False):
    """Start an unlimited set of runs"""

    # if we want continuous runs, make sure to tell Live
    if num_stopless is not None:
        set_number_of_restarts(num_stopless - 1)

    # build the default configuration values
    config = {}
    for k, vdict in list(CONFIG_DATA.items()):
        if vdict["flag"] is not None and vdict["value"] is not None:
            config[k] = vdict["value"]

    # load config values from filesystem
    if not read_config(CONFIG_FILE, config):
        raise SystemExit("Failed to read %s" % CONFIG_FILE)

    launch_spts(config[RUN_CONFIG_NAME], verbose=verbose)

    # wait a bit for the launch to finish
    time.sleep(5)

    # start runs
    args = ["livecmd", "start", "daq", ]
    for key, val in config.items():
        if key == DURATION_NAME:
            val = "%ds" % get_duration_from_string(val)
        if CONFIG_DATA[key]["flag"] is not None and val is not None:
            args.append(CONFIG_DATA[key]["flag"])
            args.append(str(val))

    if verbose:
        print(str(args))

    rtn = subprocess.call(args)
    if rtn != 0:
        raise SystemExit("Failed to start SPTS runs")


def main():
    "Main program"

    import argparse

    from utils.Machineid import Machineid

    parser = argparse.ArgumentParser()

    parser.add_argument("-D", "--dbname", dest="db_name",
                        help="Name of database to check")
    parser.add_argument("-f", "--force", dest="force",
                        action="store_true", default=False,
                        help="kill components even if there is an active run")
    parser.add_argument("-m", "--no-host-check", dest="nohostcheck",
                        action="store_true", default=False,
                        help=("Disable checking the host type for"
                              " run permission"))
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Log output for all components to terminal")

    args = parser.parse_args()

    if not args.nohostcheck:
        hostid = Machineid()
        if hostid.is_sps_cluster:
            raise SystemExit("This script should not be run on SPS")
        if not (hostid.is_control_host or
                (hostid.is_unknown_host and hostid.is_unknown_cluster)):
            # you should either be a control host or a totally unknown host
            raise SystemExit("Are you sure you are restarting test runs"
                             " on the correct host?")

    idle_minutes = 2 * 60    # two hours
    if is_paused():
        if args.verbose:
            print("SPTS is paused")
    else:
        db_name = args.db_name
        if db_name is None:
            db_name = get_live_db_name()
        if args.force or not is_spts_active(idle_minutes, db_name=db_name,
                                            verbose=args.verbose):
            start_runs(num_stopless=NUM_STOPLESS_VALUE, verbose=args.verbose)
        elif args.verbose:
            print("SPTS is active")


if __name__ == "__main__":
    main()
