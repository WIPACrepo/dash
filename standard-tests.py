#!/usr/bin/env python
#
# Run standard pDAQ tests

import optparse, os, re, socket, stat, sys
from liverun import DatabaseType, LiveRun

# times in seconds
#
FOUR_HR = 14400
EIGHT_HR = 28800

class RunDataException(Exception): pass

class RunData(object):
    "Description of a pDAQ run"

    # NOTE: this is a simple mapping of run configuration names to
    #       the corresponding cluster configuration names.  The test runs
    #       are described in RUN_LIST below
    #
    CFG2CLUSTER = {
        "spts64-dirtydozen-hlc-006" : "spts64-real-21-29",
        "sim4strAMANDA-25Hz" : "spts64-sim4strAMANDA",
        "sim18str-noise25Hz-002" : "spts64-sim18str",
        "sim22str-with-phys-trig-001" : "spts64-simIC22str",
        "sim22strAMANDA-doublespsfeb12rates" : "spts64-simIC22strAMANDA",
        "sim40str-25Hz-reduced-trigger" : "spts64-simIC40str",
        "sim60str-mbt23" : "spts64-simIC60str",
        "sim80str-25Hz" : "spts64-simIC80str",
        }

    def __init__(self, runCfg, duration, numRuns=1, flashName=None,
                 flashTimes=None, flashPause=60):
        self.__runCfg = runCfg
        self.__duration = duration
        self.__numRuns = numRuns
        self.__flashName = flashName
        self.__flashTimes = flashTimes
        self.__flashPause = flashPause

        if not RunData.CFG2CLUSTER.has_key(self.__runCfg):
            raise RunDataException("Unknown cluster config for '%s'" %
                                   self.__runCfg)

    def clusterConfig(self): return RunData.CFG2CLUSTER[self.__runCfg]

    def run(self, liveRun, quick):
        if quick and self.__duration > 1200:
            duration = self.__duration / 120
        else:
            duration = self.__duration

        liveRun.run(RunData.CFG2CLUSTER[self.__runCfg], self.__runCfg,
                    duration, self.__numRuns, self.__flashName,
                    self.__flashTimes, self.__flashPause, False)

# configurations to run
#
RUN_LIST = (RunData("spts64-dirtydozen-hlc-006", FOUR_HR),
            RunData("spts64-dirtydozen-hlc-006", 0, 1,
                    "flash-21", (60, 45, 120)),
            RunData("sim4strAMANDA-25Hz", 300),
            ###RunData("sim18str-noise25Hz-002", FOUR_HR),
            ###RunData("sim18str-noise25Hz-002", EIGHT_HR),
            ###RunData("sim22str-with-phys-trig-001", FOUR_HR),
            ###RunData("sim22str-with-phys-trig-001", EIGHT_HR),
            ###RunData("sim22strAMANDA-doublespsfeb12rates", FOUR_HR),
            #RunData("sim40str-25Hz-reduced-trigger", FOUR_HR),
            #RunData("sim40str-25Hz-reduced-trigger", EIGHT_HR),
            RunData("sim60str-mbt23", FOUR_HR),
            RunData("sim60str-mbt23", EIGHT_HR),
            ###RunData("sim80str-25Hz", FOUR_HR),
            ###RunData("sim80str-25Hz", EIGHT_HR),
            )

class Deploy(object):
    DEPLOY_CLEAN = False

    COMP_SUBPAT = r"(\S+):(\d+)\s*(\[(\S+)\])?"

    CFG_PAT = re.compile(r"^CONFIG:\s+(\S+)\s*$")
    NODE_PAT = re.compile(r"^\s\s+(\S+)\(\S+\)\s+" + COMP_SUBPAT + r"\s*$")
    COMP_PAT = re.compile(r"^\s\s+" + COMP_SUBPAT + r"\s*$")
    VERS_PAT = re.compile(r"^VERSION:\s+(\S+)\s*$")
    CMD_PAT = re.compile(r"^\s\s+.*rsync\s+.*$")

    def __init__(self, showCmd, showCmdOutput):
        self.__showCmd = showCmd
        self.__showCmdOutput = showCmdOutput

        homePath = os.environ["PDAQ_HOME"]
        self.__pdaqHome = self.__getCurrentLocation(homePath)

        # check for needed executables
        #
        self.__deploy = os.path.join(homePath, "dash", "DeployPDAQ.py")
        self.__checkExists("Deploy program", self.__deploy)

    def __checkExists(self, name, path):
        if not os.path.exists(path):
            raise SystemExit("%s '%s' does not exist" % (name, path))

    def __getCurrentLocation(self, homePath):
        statTuple = os.lstat(homePath)
        if not stat.S_ISLNK(statTuple[stat.ST_MODE]):
            raise SystemExit("PDAQ_HOME '%s' is not a symlink" %
                             homePath)

        return os.readlink(homePath)

    def __runDeploy(self, clusterCfg, arg):
        cmd = "%s -c %s %s" % (self.__deploy, clusterCfg, arg)
        if self.__showCmd: print cmd

        (fi, foe) = os.popen4(cmd)
        fi.close()

        inNodes = False
        inCmds = False

        for line in foe:
            line = line.rstrip()
            if self.__showCmdOutput: print '+ ' + line

            if line == "NODES:":
                inNodes = True
                continue

            if inNodes:
                if len(line) == 0: continue

                m = Deploy.NODE_PAT.match(line)
                if m:
                    #host = m.group(1)
                    #compName = m.group(2)
                    #compId = int(m.group(3))
                    #strType = m.group(5)
                    continue

                m = Deploy.COMP_PAT.match(line)
                if m:
                    #compName = m.group(1)
                    #compId = int(m.group(2))
                    #strType = m.group(4)
                    continue

                inNodes = False

            if line == "COMMANDS:":
                inCmds = True
                continue

            if inCmds:
                m = Deploy.CMD_PAT.match(line)
                if m:
                    continue
                inCmds = False

            m = Deploy.CFG_PAT.match(line)
            if m:
                if clusterCfg != m.group(1):
                    raise SystemExit("Expected to deploy %s, not %s" %
                                     (clusterCfg, m.group(1)))
                continue

            m = Deploy.VERS_PAT.match(line)
            if m:
                #version = m.group(1)
                continue

            if line.startswith("ERROR: "):
                raise SystemExit("Deploy error: " + line[7:])

            print >>sys.stderr, "Deploy: %s" % line
        foe.close()

    def deploy(self, clusterConfig):
        "Deploy to the specified cluster"
        if not self.__showCmd: print "Deploying %s" % clusterConfig
        if Deploy.DEPLOY_CLEAN:
            self.__runDeploy(clusterConfig, "--undeploy")

        self.__runDeploy(clusterConfig, "--delete")

    def getUniqueClusterConfigs(self, runList):
        "Return a list of the unique elements"
        ccDict = {}
        for data in runList:
            ccDict[data.clusterConfig()] = 1

        uniqList = ccDict.keys()
        uniqList.sort()

        return uniqList
    getUniqueClusterConfigs = classmethod(getUniqueClusterConfigs)

    def showHome(self):
        "Print the actual pDAQ home directory name"
        print "==============================================================="
        print "== PDAQ_HOME points to %s" % self.__pdaqHome
        print "==============================================================="

if __name__ == "__main__":
    op = optparse.OptionParser()
    op.add_option("-d", "--deploy", action="store_true", dest="deploy",
                  help="Deploy the standard tests")
    op.add_option("-q", "--quick", action="store_true", dest="quick",
                  help="Reduce 4/8 hour tests to 2/4 minute tests")
    op.add_option("-r", "--run", action="store_true", dest="run",
                  help="Run the standard tests")
    op.add_option("-s", "--showCommands", action="store_true", dest="showCmd",
                  help="Show the commands used to deploy and/or run")
    op.add_option("-x", "--showCommandOutput", action="store_true",
                  dest="showCmdOutput",
                  help="Show the output of the deploy and/or run commands")
    op.set_defaults(deploy = False,
                    quick = False,
                    run = False,
                    showCmd = False,
                    showCmdOutput = False)

    opt, args = op.parse_args()

    if not opt.deploy and not opt.run:
        #
        # Use hostname to guess what we're meant to do
        #
        hostName = socket.gethostname()
        if hostName.startswith("spts64-build64"):
            opt.deploy = True
        elif hostName.startswith("spts64-expcont"):
            opt.run = True
        else:
            raise SystemExit("Please specify --deploy or --run" +
                             " (unrecognized host %s)" % hostName)

    # Make sure expected environment variables are set
    #
    for nm in ("HOME", "PDAQ_HOME"):
        if not os.environ.has_key(nm):
            raise SystemExit("Environment variable '%s' has not been set" % nm)

    # run tests from pDAQ top-level directory
    #
    os.chdir(os.environ["PDAQ_HOME"])

    if opt.deploy:
        deploy = Deploy(opt.showCmd, opt.showCmdOutput)
        deploy.showHome()
        for cfg in Deploy.getUniqueClusterConfigs(RUN_LIST):
            deploy.deploy(cfg)
        deploy.showHome()
    if opt.run:
        liveRun = LiveRun(opt.showCmd, opt.showCmdOutput)

        # always kill running components in case they're from a previous release
        #
        liveRun.killComponents()

        for data in RUN_LIST:
            data.run(liveRun, opt.quick)
