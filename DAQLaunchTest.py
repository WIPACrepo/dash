#!/usr/bin/env python


import os
import tempfile
import unittest

from CachedConfigName import CachedConfigName
from DAQConst import DAQPort
from DAQLaunch import add_arguments_both, add_arguments_launch, \
     add_arguments_kill, launch, kill
from DAQMocks import MockClusterConfigFile, MockParallelShell, \
    MockRunConfigFile


class MockArguments(object):
    def __init__(self):
        pass

    def add_argument(self, *args, **kwargs):
        """
        Use 'dest' and 'default' keywords to create an argument attribute
        """
        if "dest" not in kwargs:
            raise Exception("No 'dest' for %s" % str(args))
        if "default" in kwargs:
            dflt = kwargs["default"]
        else:
            dflt = None
        setattr(self, kwargs["dest"], dflt)

    def set_argument(self, name, value):
        """
        Update the value on an existing argument attribute
        """
        if not hasattr(self, name):
            raise Exception("Unknown argument \"%s\"" % (name, ))
        setattr(self, name, value)


class TestDAQLaunch(unittest.TestCase):
    def __createClusterConfigFile(self, configDir, cluDesc, daqDataDir, logDir,
                                  spadeDir, compHostDict):
        cluDesc = "xxx"
        cluCfgFile = MockClusterConfigFile(configDir, cluDesc)

        cluCfgFile.setDataDir(daqDataDir)
        cluCfgFile.setLogDir(logDir)
        cluCfgFile.setSpadeDir(spadeDir)

        h1 = cluCfgFile.addHost("ctlhost")
        h1.addControlServer()

        cluHosts = {}
        for name, host in list(compHostDict.items()):
            if host not in cluHosts:
                cluHosts[host] = cluCfgFile.addHost(host)
            cluHosts[host].addComponent(name)

        sim = cluCfgFile.addHost("simhost")
        sim.addSimHubs(10, 1)

        cluCfgFile.create()

        return cluCfgFile

    def tearDown(self):
        # clear cached config directory
        CachedConfigName.clearActiveConfig()

    def testLaunchOnlyCnC(self):
        tmpdir = tempfile.mkdtemp()
        configDir = os.path.join(tmpdir, 'cfg')
        daqDataDir = os.path.join(tmpdir, 'data')
        dashDir = os.path.join(tmpdir, 'dash')
        logDir = os.path.join(tmpdir, 'log')
        spadeDir = os.path.join(tmpdir, 'spade')

        compHostDict = {
            "inIceTrigger": "trigger",
            "globalTrigger": "trigger",
            "eventBuilder": "builder",
            "secondaryBuilders": "builder",
            "ichub01": "ichub01",
        }

        cluCfgFile = self.__createClusterConfigFile(configDir, "xxx",
                                                    daqDataDir, logDir,
                                                    spadeDir, compHostDict)

        runCfgFile = MockRunConfigFile(configDir)
        cfgName = runCfgFile.create(list(compHostDict.keys()), {})

        copyDir = None
        logPort = None
        livePort = DAQPort.I3LIVE_ZMQ

        forceRestart = False
        logger = None
        checkExists = False

        shell = MockParallelShell()
        shell.addExpectedPython(True, dashDir, configDir, logDir, daqDataDir,
                                spadeDir, cluCfgFile.name, cfgName, copyDir,
                                logPort, livePort, forceRestart=forceRestart)

        args = MockArguments()
        add_arguments_both(args)
        add_arguments_launch(args)
        args.set_argument("clusterDesc", cluCfgFile.name)
        args.set_argument("configName", cfgName)
        args.set_argument("validation", False)
        args.set_argument("verbose", False)
        args.set_argument("dryRun", False)
        args.set_argument("eventCheck", False)
        args.set_argument("forceRestart", forceRestart)

        launch(configDir, dashDir, logger, args=args, parallel=shell,
               checkExists=checkExists)

    def testKillOnlyCnC(self):
        tmpdir = tempfile.mkdtemp()
        configDir = os.path.join(tmpdir, 'cfg')
        daqDataDir = os.path.join(tmpdir, 'data')
        logDir = os.path.join(tmpdir, 'log')
        spadeDir = os.path.join(tmpdir, 'spade')

        compHostDict = {
            "inIceTrigger": "trigger",
            "globalTrigger": "trigger",
            "eventBuilder": "builder",
            "secondaryBuilders": "builder",
            "ichub01": "ichub01",
        }

        cluCfgFile = self.__createClusterConfigFile(configDir, "xxx",
                                                    daqDataDir, logDir,
                                                    spadeDir, compHostDict)

        logger = None
        killWith9 = False

        shell = MockParallelShell()
        shell.addExpectedPythonKill(True, killWith9=killWith9)

        runCfgFile = MockRunConfigFile(configDir)
        cfgName = runCfgFile.create(list(compHostDict.keys()), {})

        # set the cached config name
        cc = CachedConfigName()
        cc.setConfigName(cfgName)
        cc.writeCacheFile(writeActiveConfig=True)

        args = MockArguments()
        add_arguments_both(args)
        add_arguments_kill(args)
        args.set_argument("clusterDesc", cluCfgFile.name)
        args.set_argument("validation", False)
        args.set_argument("serverKill", True)
        args.set_argument("verbose", False)
        args.set_argument("dryRun", False)
        args.set_argument("killWith9", killWith9)
        args.set_argument("force", True)

        kill(configDir, logger, args=args, parallel=shell)


if __name__ == '__main__':
    unittest.main()
