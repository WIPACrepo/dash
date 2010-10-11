#!/usr/bin/env python
#
# Run standard pDAQ tests

import optparse, os, re, socket, stat, sys
from BaseRun import DatabaseType
from liverun import LiveRun

# times in seconds
#
FOUR_HR = 14400
EIGHT_HR = 28800

class PDAQRunException(Exception): pass

class PDAQRun(object):
    "Description of a pDAQ run"

    def __init__(self, runCfg, duration, numRuns=1, flashName=None,
                 flashTimes=None, flashPause=60):
        self.__runCfg = runCfg
        self.__duration = duration
        self.__numRuns = numRuns
        self.__flashName = flashName
        self.__flashTimes = flashTimes
        self.__flashPause = flashPause

    def clusterConfig(self): return self.__runCfg

    def run(self, liveRun, quick):
        if quick and self.__duration > 1200:
            duration = self.__duration / 120
        else:
            duration = self.__duration

        for r in range(self.__numRuns):
            liveRun.run(self.clusterConfig(), self.__runCfg,
                        duration, self.__flashName, self.__flashTimes,
                        self.__flashPause, False)

# configurations to run
#
RUN_LIST = (PDAQRun("spts64-dirtydozen-hlc-006", FOUR_HR),
            PDAQRun("spts64-dirtydozen-hlc-006", 0, 1,
                    "flash-21", (60, 45, 120)),
            ###PDAQRun("sim18str-noise25Hz-002", FOUR_HR),
            ###PDAQRun("sim18str-noise25Hz-002", EIGHT_HR),
            ###PDAQRun("sim22str-with-phys-trig-001", FOUR_HR),
            ###PDAQRun("sim22str-with-phys-trig-001", EIGHT_HR),
            #PDAQRun("sim40str-25Hz-reduced-trigger", FOUR_HR),
            #PDAQRun("sim40str-25Hz-reduced-trigger", EIGHT_HR),
            #PDAQRun("sim60str-mbt23", FOUR_HR),
            #PDAQRun("sim60str-mbt23", EIGHT_HR),
            PDAQRun("sim60str-mbt-vt-01", FOUR_HR),
            PDAQRun("sim60str-mbt-vt-01", EIGHT_HR),
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
    op.add_option("-d", "--deploy", dest="deploy",
                  action="store_true", default=False,
                  help="Deploy the standard tests")
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
        liveRun = LiveRun(opt.showCmd, opt.showCmdOutput, opt.showChk,
                          opt.showChkOutput)

        # always kill running components in case they're from a previous release
        #
        liveRun.killComponents()

        for data in RUN_LIST:
            data.run(liveRun, opt.quick)
