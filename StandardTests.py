#!/usr/bin/env python
#
# Run standard pDAQ tests

from __future__ import print_function

import os
import re
import stat
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

    def __init__(self, runCfgName, duration, numRuns=1, flashData=None):
        self.__runCfgName = runCfgName
        self.__duration = duration
        self.__numRuns = numRuns

        if flashData is None:
            self.__flashData = None
        else:
            self.__flashData = []
            for pair in flashData:
                if pair[0] is None:
                    path = None
                else:
                    if self.TSTRSRC is None:
                        metadir = find_pdaq_trunk()
                        self.TSTRSRC = os.path.join(metadir, "src", "test",
                                                    "resources")

                    path = FlasherScript.findDataFile(pair[0],
                                                      basedir=self.TSTRSRC)

                self.__flashData.append((path, pair[1]))

    def clusterConfig(self):
        return self.__runCfgName

    def run(self, runmgr, quick, clusterDesc=None, ignoreDB=False,
            verbose=False):
        flasherDelay = 120
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

            flasherDelay = 30

        timeouts = 0
        try:
            runmgr.run(self.__runCfgName, self.__runCfgName, duration,
                       numRuns=self.__numRuns, flashData=self.__flashData,
                       flasherDelay=flasherDelay, clusterDesc=clusterDesc,
                       ignoreDB=ignoreDB, verbose=verbose)

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
    DEPLOY_CLEAN = False

    COMP_SUBPAT = r"(\S+):(\d+)\s*(\[(\S+)\])?"

    CFG_PAT = re.compile(r"^CONFIG:\s+(\S+)\s*$")
    NODE_PAT = re.compile(r"^\s\s+(\S+)\(\S+\)\s+" + COMP_SUBPAT + r"\s*$")
    COMP_PAT = re.compile(r"^\s\s+" + COMP_SUBPAT + r"\s*$")
    VERS_PAT = re.compile(r"^VERSION:\s+(\S+)\s*$")
    CMD_PAT = re.compile(r"^\s\s+.*rsync\s+.*$")

    def __init__(self, showCmd, showCmdOutput, dryRun, clusterDesc):
        self.__showCmd = showCmd
        self.__showCmdOutput = showCmdOutput
        self.__dryRun = dryRun
        self.__clusterDesc = clusterDesc

        homePath = os.environ["PDAQ_HOME"]
        self.__pdaqHome = self.__getCurrentLocation(homePath)

    def __checkExists(self, name, path):
        if not os.path.exists(path):
            raise SystemExit("%s '%s' does not exist" % (name, path))

    def __getCurrentLocation(self, homePath):
        statTuple = os.lstat(homePath)
        if not stat.S_ISLNK(statTuple[stat.ST_MODE]):
            return homePath
        return os.readlink(homePath)

    def deploy(self, clusterCfgName):
        "Deploy to the specified cluster"
        try:
            cluDesc = self.__clusterDesc
            clusterCfg = \
                DAQConfigParser.getClusterConfiguration(clusterCfgName,
                                                        useActiveConfig=False,
                                                        clusterDesc=cluDesc,
                                                        configDir=None,
                                                        validate=False)
        except DAQConfigException:
            raise LaunchException("Cannot load configuration \"%s\": %s" %
                                  (clusterCfgName, exc_string()))

        if not self.__showCmd:
            print("Deploying %s" % clusterCfg)

        subdirs = None
        delete = True
        deepDryRun = False
        traceLevel = 0

        if Deploy.DEPLOY_CLEAN:
            undeploy = True

            DeployPDAQ.deploy(clusterCfg, os.environ["HOME"],
                              os.environ["PDAQ_HOME"], subdirs, delete,
                              self.__dryRun, deepDryRun, undeploy, traceLevel)

        undeploy = False
        DeployPDAQ.deploy(clusterCfg, os.environ["HOME"],
                          os.environ["PDAQ_HOME"], subdirs, delete,
                          self.__dryRun, deepDryRun, undeploy, traceLevel)

    @staticmethod
    def getUniqueClusterConfigs(runList):
        "Return a list of the unique elements"
        ccDict = {}
        for data in runList:
            ccDict[data.clusterConfig()] = 1

        uniqList = sorted(ccDict.keys())

        return uniqList

    def showHome(self):
        "Print the actual pDAQ home directory name"
        print("===============================================================")
        print("== PDAQ_HOME points to %s" % self.__pdaqHome)
        print("===============================================================")


def add_arguments(parser):
    parser.add_argument("-C", "--cluster-desc", dest="clusterDesc",
                        help="Cluster description name")
    parser.add_argument("-c", "--cncrun", dest="cncrun",
                        action="store_true", default=False,
                        help="Control CnC directly instead of using I3Live")
    parser.add_argument("-d", "--deploy", dest="deploy",
                        action="store_true", default=False,
                        help="Deploy the standard tests")
    parser.add_argument("-i", "--ignore-db", dest="ignoreDB",
                        action="store_true", default=False,
                        help="Do not update database with run configuration")
    parser.add_argument("-n", "--dry-run", dest="dryRun",
                        action="store_true", default=False,
                        help=("Don't run commands, just print as they"
                              " would be run"))
    parser.add_argument("-q", "--quick", dest="quick",
                        action="store_true", default=False,
                        help="Reduce 4/8 hour tests to 2/4 minute tests")
    parser.add_argument("-r", "--run", dest="run",
                        action="store_true", default=False,
                        help="Run the standard tests")
    parser.add_argument("-S", "--showCheck", dest="showChk",
                        action="store_true", default=False,
                        help="Show the 'livecmd check' commands")
    parser.add_argument("-s", "--showCommands", dest="showCmd",
                        action="store_true", default=False,
                        help="Show the commands used to deploy and/or run")
    parser.add_argument("-v", "--verbose", dest="verbose",
                        action="store_true", default=False,
                        help="Print more details of run transitions")
    parser.add_argument("-X", "--showCheckOutput", dest="showChkOutput",
                        action="store_true", default=False,
                        help="Show the output of the 'livecmd check' commands")
    parser.add_argument("-x", "--showCommandOutput", dest="showCmdOutput",
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
    PDAQRun("replay-125659-local", QUARTER_HR, numRuns=3),
)


def run_tests(args):
    import signal

    hostid = Machineid()

    if hostid.is_sps_cluster():
        raise SystemExit("Tests should not be run on SPS cluster")

    if not args.deploy and not args.run:
        if hostid.is_build_host():
            args.deploy = True
        elif hostid.is_control_host():
            args.run = True
        else:
            raise SystemExit("Please specify --deploy or --run" +
                             " (unrecognized host %s)" % hostid.hname)

    # Make sure expected environment variables are set
    #
    for nm in ("HOME", "PDAQ_HOME"):
        if nm not in os.environ:
            raise SystemExit("Environment variable '%s' has not been set" % nm)

    # run tests from pDAQ top-level directory
    #
    os.chdir(os.environ["PDAQ_HOME"])

    if args.deploy:
        deploy = Deploy(args.showCmd, args.showCmdOutput, args.dryRun,
                        args.clusterDesc)
        deploy.showHome()
        for cfg in Deploy.getUniqueClusterConfigs(RUN_LIST):
            deploy.deploy(cfg)
        deploy.showHome()
    if args.run:
        if args.cncrun:
            runmgr = CnCRun(showCmd=args.showCmd,
                            showCmdOutput=args.showCmdOutput,
                            dryRun=args.dryRun)
        else:
            runmgr = LiveRun(showCmd=args.showCmd,
                             showCmdOutput=args.showCmdOutput,
                             showCheck=args.showChk,
                             showCheckOutput=args.showChkOutput,
                             dryRun=args.dryRun)

        if sys.version_info > (2, 3):
            from DumpThreads import DumpThreadsOnSignal
            DumpThreadsOnSignal(fd=sys.stderr)

        # always kill running components in case they're from a
        # previous release
        #
        runmgr.killComponents(dryRun=args.dryRun)

        # stop existing runs gracefully on ^C
        #
        signal.signal(signal.SIGINT, runmgr.stopOnSIGINT)

        for data in RUN_LIST:
            data.run(runmgr, args.quick, clusterDesc=args.clusterDesc,
                     ignoreDB=args.ignoreDB, verbose=args.verbose)


if __name__ == "__main__":
    import argparse

    op = argparse.ArgumentParser()
    add_arguments(op)

    args = op.parse_args()

    run_tests(args)
