#!/usr/bin/env python
#
# Run standard pDAQ tests

from __future__ import print_function

import os
import re
import sys
import traceback

import DeployPDAQ

from BaseRun import FlasherScript, LaunchException
from DAQConfig import DAQConfigException, DAQConfigParser
from cncrun import CnCRun
from liverun import LiveRun, LiveTimeoutException
from locate_pdaq import find_pdaq_trunk
from utils.Machineid import Machineid

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

# times in seconds
#
SECONDS_PER_HOUR = 3600
QUARTER_HR = SECONDS_PER_HOUR / 4
HALF_HR = SECONDS_PER_HOUR / 2
FOUR_HR = SECONDS_PER_HOUR * 4
EIGHT_HR = SECONDS_PER_HOUR * 8


# find top pDAQ directory
PDAQ_HOME = find_pdaq_trunk()


class PDAQRunException(Exception):
    pass


class PDAQRun(object):
    "Description of a pDAQ run"

    # location of unit test resources directory
    #
    TSTRSRC = None

    # maximum number of timeouts
    #
    MAX_TIMEOUTS = 6

    def __init__(self, run_cfg_name, duration, num_runs=1, flasher_data=None):
        self.__run_cfg_name = run_cfg_name
        self.__duration = duration
        self.__num_runs = num_runs

        if flasher_data is None:
            self.__flasher_data = None
        else:
            self.__flasher_data = []
            for pair in flasher_data:
                if pair[0] is None:
                    path = None
                else:
                    if self.TSTRSRC is None:
                        self.TSTRSRC = os.path.join(PDAQ_HOME, "src", "test",
                                                    "resources")

                    path = FlasherScript.find_data_file(pair[0],
                                                        basedir=self.TSTRSRC)

                self.__flasher_data.append((path, pair[1]))

    @property
    def cluster_config(self):
        return self.__run_cfg_name

    def run(self, runmgr, quick, cluster_desc=None, ignore_db=False,
            verbose=False):
        flasher_delay = 120
        if not quick:
            duration = self.__duration
        else:
            # compute 'quick' duration
            if self.__duration > 3600:
                duration = self.__duration / 120
            elif self.__duration > 1200:
                duration = self.__duration / 10
            else:
                duration = self.__duration

            flasher_delay = 30

        timeouts = 0
        try:
            runmgr.run(self.__run_cfg_name, self.__run_cfg_name, duration,
                       num_runs=self.__num_runs,
                       flasher_data=self.__flasher_data,
                       flasher_delay=flasher_delay, cluster_desc=cluster_desc,
                       ignore_db=ignore_db, verbose=verbose)

            # reset the timeout counter after each set of successful runs
            timeouts = 0
        except SystemExit:
            raise
        except LiveTimeoutException:
            traceback.print_exc()
            timeouts += 1
            if timeouts > self.MAX_TIMEOUTS:
                raise SystemExit("I3Live seems to have gone away")
        except:
            traceback.print_exc()


class Deploy(object):
    COMP_SUBPAT = r"(\S+):(\d+)\s*(\[(\S+)\])?"

    CFG_PAT = re.compile(r"^CONFIG:\s+(\S+)\s*$")
    NODE_PAT = re.compile(r"^\s\s+(\S+)\(\S+\)\s+" + COMP_SUBPAT + r"\s*$")
    COMP_PAT = re.compile(r"^\s\s+" + COMP_SUBPAT + r"\s*$")
    VERS_PAT = re.compile(r"^VERSION:\s+(\S+)\s*$")
    CMD_PAT = re.compile(r"^\s\s+.*rsync\s+.*$")

    def __init__(self, show_commands, show_command_output, dry_run,
                 cluster_desc):
        self.__show_commands = show_commands
        self.__show_command_output = show_command_output
        self.__dry_run = dry_run
        self.__cluster_desc = cluster_desc

    def deploy(self, cluster_cfg_name):
        "Deploy to the specified cluster"
        try:
            clu_desc = self.__cluster_desc
            cluster_cfg = \
                DAQConfigParser.get_cluster_configuration\
                (cluster_cfg_name, use_active_config=False,
                 cluster_desc=clu_desc, config_dir=None, validate=False)
        except DAQConfigException:
            raise LaunchException("Cannot load configuration \"%s\": %s" %
                                  (cluster_cfg_name, exc_string()))

        if not self.__show_commands:
            print("Deploying %s" % str(cluster_cfg))

        subdirs = None
        delete = True
        deep_dry_run = False
        trace_level = 0

        DeployPDAQ.deploy(cluster_cfg, PDAQ_HOME, subdirs, delete,
                          self.__dry_run, deep_dry_run, trace_level)

    @staticmethod
    def get_unique_cluster_configs(runlist):
        "Return a list of the unique elements"
        cc_dict = {}
        for data in runlist:
            cc_dict[data.cluster_config] = 1

        return sorted(cc_dict.keys())

    def show_home(self):
        "Print the actual pDAQ home directory name"
        print("===============================================================")
        print("== PDAQ_HOME points to %s" % str(PDAQ_HOME))
        print("===============================================================")


def add_arguments(parser):
    parser.add_argument("-C", "--cluster-desc", dest="cluster_desc",
                        help="Cluster description name")
    parser.add_argument("-c", "--cncrun", dest="cncrun",
                        action="store_true", default=False,
                        help="Control CnC directly instead of using I3Live")
    parser.add_argument("-d", "--deploy", dest="deploy",
                        action="store_true", default=False,
                        help="Deploy the standard tests")
    parser.add_argument("-i", "--ignore-db", dest="ignore_db",
                        action="store_true", default=False,
                        help="Do not update database with run configuration")
    parser.add_argument("-n", "--dry-run", dest="dry_run",
                        action="store_true", default=False,
                        help=("Don't run commands, just print as they"
                              " would be run"))
    parser.add_argument("-q", "--quick", dest="quick",
                        action="store_true", default=False,
                        help="Reduce 4/8 hour tests to 2/4 minute tests")
    parser.add_argument("-r", "--run", dest="run",
                        action="store_true", default=False,
                        help="Run the standard tests")
    parser.add_argument("-S", "--show_check", dest="show_check",
                        action="store_true", default=False,
                        help="Show the 'livecmd check' commands")
    parser.add_argument("-s", "--show_commands", dest="show_commands",
                        action="store_true", default=False,
                        help="Show the commands used to deploy and/or run")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print more details of run transitions")
    parser.add_argument("-X", "--show_check_output", dest="show_check_output",
                        action="store_true", default=False,
                        help="Show the output of the 'livecmd check' commands")
    parser.add_argument("-x", "--show_command_output", dest="show_command_output",
                        action="store_true", default=False,
                        help=("Show the output of the deploy and/or"
                              " run commands"))


# configurations to run
#
RUN_LIST = (
    PDAQRun("spts64-dirtydozen-hlc-006", FOUR_HR),
    PDAQRun("spts64-dirtydozen-hlc-006", 0, 1,
            (("flash-21", 60), (None, 10), ("flash-21", 45),
             (None, 20), ("flash-21", 120))),
    PDAQRun("spts64-dirtydozen-hitspool-15s-interval-8h-spool", HALF_HR),
    PDAQRun("spts-dirtydozen-intervals3-snmix-014", HALF_HR),
    PDAQRun("random-01", HALF_HR),
    PDAQRun("replay-125659-local", EIGHT_HR),
    PDAQRun("replay-125659-local", QUARTER_HR, num_runs=3),
)


def run_tests(args):
    import signal

    hostid = Machineid()

    if hostid.is_sps_cluster:
        raise SystemExit("Tests should not be run on SPS cluster")

    if not args.deploy and not args.run:
        if hostid.is_build_host:
            args.deploy = True
        elif hostid.is_control_host:
            args.run = True
        else:
            raise SystemExit("Please specify --deploy or --run" +
                             " (unrecognized host %s)" % hostid.hname)

    # run tests from pDAQ top-level directory
    #
    os.chdir(PDAQ_HOME)

    if args.deploy:
        deploy = Deploy(args.show_commands, args.show_command_output,
                        args.dry_run, args.cluster_desc)
        deploy.show_home()
        for cfg in Deploy.get_unique_cluster_configs(RUN_LIST):
            deploy.deploy(cfg)
        deploy.show_home()
    if args.run:
        if args.cncrun:
            runmgr = CnCRun(show_commands=args.show_commands,
                            show_command_output=args.show_command_output,
                            dry_run=args.dry_run)
        else:
            runmgr = LiveRun(show_commands=args.show_commands,
                             show_command_output=args.show_command_output,
                             show_check=args.show_check,
                             show_check_output=args.show_check_output,
                             dry_run=args.dry_run)

        if sys.version_info > (2, 3):
            from DumpThreads import DumpThreadsOnSignal
            DumpThreadsOnSignal(file_handle=sys.stderr)

        # always kill running components in case they're from a
        # previous release
        #
        runmgr.kill_components(dry_run=args.dry_run)

        # stop existing runs gracefully on ^C
        #
        signal.signal(signal.SIGINT, runmgr.stop_on_sigint)

        for data in RUN_LIST:
            data.run(runmgr, args.quick, cluster_desc=args.cluster_desc,
                     ignore_db=args.ignore_db, verbose=args.verbose)


def main():
    "Main program"

    parser = argparse.ArgumentParser()
    add_arguments(parser)
    run_tests(parser.parse_args())


if __name__ == "__main__":
    import argparse

    main()
