#!/usr/bin/env python
#
# Run standard pDAQ tests

import os
import re
import socket
import stat
import sys
import traceback

import DeployPDAQ

from BaseRun import FlasherShellScript, LaunchException
from ClusterDescription import ClusterDescription
from DAQConfig import DAQConfigException, DAQConfigParser
from cncrun import CnCRun
from liverun import LiveRun, LiveTimeoutException

from exc_string import exc_string, set_exc_string_encoding
set_exc_string_encoding("ascii")

# times in seconds
#
HALF_HR = 1800
FOUR_HR = 14400
EIGHT_HR = 28800


class PDAQRunException(Exception):
    pass


class PDAQRun(object):
    "Description of a pDAQ run"

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
                    path = FlasherShellScript.findDataFile(pair[0])
                self.__flashData.append((path, pair[1]))

    def clusterConfig(self):
        return self.__runCfgName

    def run(self, runmgr, quick, clusterDesc=None, ignoreDB=False,
            verbose=False):
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

        timeouts = 0
        for r in range(self.__numRuns):
            try:
                runmgr.run(self.__runCfgName, self.__runCfgName,
                           duration, flashData=self.__flashData,
                           clusterDesc=clusterDesc, ignoreDB=ignoreDB,
                           verbose=verbose)

                # reset the timeout counter after each successful run
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

# configurations to run
#
RUN_LIST = (PDAQRun("spts64-dirtydozen-hlc-006", FOUR_HR),
            PDAQRun("spts64-dirtydozen-hlc-006", 0, 1,
                     (("flash-21", 60), (None, 10), ("flash-21", 45),
                        (None, 20), ("flash-21", 120))),
            ###PDAQRun("sim18str-noise25Hz-002", FOUR_HR),
            ###PDAQRun("sim18str-noise25Hz-002", EIGHT_HR),
            ###PDAQRun("sim22str-with-phys-trig-001", FOUR_HR),
            ###PDAQRun("sim22str-with-phys-trig-001", EIGHT_HR),
            #PDAQRun("sim40str-25Hz-reduced-trigger", FOUR_HR),
            #PDAQRun("sim40str-25Hz-reduced-trigger", EIGHT_HR),
            #PDAQRun("sim60str-mbt23", FOUR_HR),
            #PDAQRun("sim60str-mbt23", EIGHT_HR),
            PDAQRun("sim60strIT-stdtest-01", HALF_HR),
            PDAQRun("sim60str-stdtest-01", HALF_HR),
            PDAQRun("sim60str-stdtest-01", EIGHT_HR),
            ###PDAQRun("sim80str-25Hz", FOUR_HR),
            ###PDAQRun("sim80str-25Hz", EIGHT_HR),
            )


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
            print "Deploying %s" % clusterCfg

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

        uniqList = ccDict.keys()
        uniqList.sort()

        return uniqList

    def showHome(self):
        "Print the actual pDAQ home directory name"
        print "==============================================================="
        print "== PDAQ_HOME points to %s" % self.__pdaqHome
        print "==============================================================="

if __name__ == "__main__":
    import optparse
    import signal

    op = optparse.OptionParser()
    op.add_option("-C", "--cluster-desc", type="string", dest="clusterDesc",
                  action="store", default=None,
                  help="Cluster description name")
    op.add_option("-c", "--cncrun", dest="cncrun",
                  action="store_true", default=False,
                  help="Control CnC directly instead of using I3Live")
    op.add_option("-d", "--deploy", dest="deploy",
                  action="store_true", default=False,
                  help="Deploy the standard tests")
    op.add_option("-i", "--ignore-db", dest="ignoreDB",
                  action="store_true", default=False,
                  help="Do not update I3OmDb with the run configuration")
    op.add_option("-n", "--dry-run", dest="dryRun",
                  action="store_true", default=False,
                  help="Don't run commands, just print as they would be run")
    op.add_option("-q", "--quick", dest="quick",
                  action="store_true", default=False,
                  help="Reduce 4/8 hour tests to 2/4 minute tests")
    op.add_option("-r", "--run", dest="run",
                  action="store_true", default=False,
                  help="Run the standard tests")
    op.add_option("-S", "--showCheck", dest="showChk",
                  action="store_true", default=False,
                  help="Show the 'livecmd check' commands")
    op.add_option("-s", "--showCommands", dest="showCmd",
                  action="store_true", default=False,
                  help="Show the commands used to deploy and/or run")
    op.add_option("-v", "--verbose", dest="verbose",
                  action="store_true", default=False,
                  help="Print more details of run transitions")
    op.add_option("-X", "--showCheckOutput", dest="showChkOutput",
                  action="store_true", default=False,
                  help="Show the output of the 'livecmd check' commands")
    op.add_option("-x", "--showCommandOutput", dest="showCmdOutput",
                  action="store_true", default=False,
                  help="Show the output of the deploy and/or run commands")

    opt, args = op.parse_args()

    if not opt.deploy and not opt.run:
        #
        # Use hostname to guess what we're meant to do
        #
        hostName = socket.gethostname()
        cluster = ClusterDescription.getClusterFromHostName(hostName)
        if cluster == ClusterDescription.SPS:
            raise SystemExit("Tests should not be run on SPS cluster")

        if hostName.find("access") >= 0 or hostName.find("build") >= 0:
            opt.deploy = True
        elif hostName.find("expcont") >= 0:
            opt.run = True
        else:
            raise SystemExit("Please specify --deploy or --run" +
                             " (unrecognized host %s)" % hostName)

    # Make sure expected environment variables are set
    #
    for nm in ("HOME", "PDAQ_HOME"):
        if not nm in os.environ:
            raise SystemExit("Environment variable '%s' has not been set" % nm)

    # run tests from pDAQ top-level directory
    #
    os.chdir(os.environ["PDAQ_HOME"])

    if opt.deploy:
        deploy = Deploy(opt.showCmd, opt.showCmdOutput, opt.dryRun,
                        opt.clusterDesc)
        deploy.showHome()
        for cfg in Deploy.getUniqueClusterConfigs(RUN_LIST):
            deploy.deploy(cfg)
        deploy.showHome()
    if opt.run:
        if opt.cncrun:
            runmgr = CnCRun(showCmd=opt.showCmd,
                            showCmdOutput=opt.showCmdOutput, dryRun=opt.dryRun)
        else:
            runmgr = LiveRun(showCmd=opt.showCmd,
                             showCmdOutput=opt.showCmdOutput,
                             showCheck=opt.showChk,
                             showCheckOutput=opt.showChkOutput,
                             dryRun=opt.dryRun)

        if sys.version_info > (2, 3):
            from DumpThreads import DumpThreadsOnSignal
            DumpThreadsOnSignal(fd=sys.stderr)

        # always kill running components in case they're from a
        # previous release
        #
        runmgr.killComponents(dryRun=opt.dryRun)

        # stop existing runs gracefully on ^C
        #
        signal.signal(signal.SIGINT, runmgr.stopOnSIGINT)

        for data in RUN_LIST:
            data.run(runmgr, opt.quick, clusterDesc=opt.clusterDesc,
                     ignoreDB=opt.ignoreDB, verbose=opt.verbose)
