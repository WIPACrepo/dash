#!/usr/bin/env python


import os
import tempfile
import unittest

from CachedConfigName import CachedConfigName
from DAQConfig import FindConfigDir
from DAQConst import DAQPort
from DAQLaunch import launch, kill
from DAQMocks import MockClusterConfigFile, MockParallelShell, MockRunConfigFile


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
        for name, host in compHostDict.items():
            if not cluHosts.has_key(host):
                cluHosts[host] = cluCfgFile.addHost(host)
            cluHosts[host].addComponent(name)

        sim = cluCfgFile.addHost("simhost")
        sim.addSimHubs(10, 1)

        cluCfgFile.create()

        return cluCfgFile

    def tearDown(self):
        # clear cached config directory
        FindConfigDir.CONFIG_DIR = None
        CachedConfigName.clearActiveConfig()

    def testLaunchOnlyCnC(self):
        tmpdir = tempfile.mkdtemp()
        configDir = os.path.join(tmpdir, 'cfg')
        daqDataDir = os.path.join(tmpdir, 'data')
        dashDir = os.path.join(tmpdir, 'dash')
        logDir = os.path.join(tmpdir, 'log')
        spadeDir = os.path.join(tmpdir, 'spade')

        compHostDict = {
            "inIceTrigger" : "trigger",
            "globalTrigger": "trigger",
            "eventBuilder": "builder",
            "secondaryBuilders": "builder",
            "ichub01": "ichub01",
        }

        cluCfgFile = self.__createClusterConfigFile(configDir, "xxx",
                                                    daqDataDir, logDir,
                                                    spadeDir, compHostDict)

        domList = []
        runCfgFile = MockRunConfigFile(configDir)
        cfgName = runCfgFile.create(compHostDict.keys(), domList)

        copyDir = None
        logPort = None
        livePort = DAQPort.I3LIVE_ZMQ

        validate = False
        verbose = False
        dryRun = False
        evtChk = False
        logger = None
        forceRestart = False
        checkExists = False

        shell = MockParallelShell()
        shell.addExpectedPython(True, dashDir, configDir, logDir, daqDataDir,
                                spadeDir, cluCfgFile.name(), cfgName, copyDir,
                                logPort, livePort, forceRestart=forceRestart)

        launch(configDir, dashDir, logger, clusterDesc=cluCfgFile.name(),
               configName=cfgName, validate=validate, verbose=verbose,
               dryRun=dryRun, eventCheck=evtChk, parallel=shell,
               forceRestart=forceRestart, checkExists=checkExists)

    def testKillOnlyCnC(self):
        tmpdir = tempfile.mkdtemp()
        configDir = os.path.join(tmpdir, 'cfg')
        daqDataDir = os.path.join(tmpdir, 'data')
        #dashDir = os.path.join(tmpdir, 'dash')
        logDir = os.path.join(tmpdir, 'log')
        spadeDir = os.path.join(tmpdir, 'spade')

        compHostDict = {
            "inIceTrigger" : "trigger",
            "globalTrigger": "trigger",
            "eventBuilder": "builder",
            "secondaryBuilders": "builder",
            "ichub01": "ichub01",
        }

        cluCfgFile = self.__createClusterConfigFile(configDir, "xxx",
                                                    daqDataDir, logDir,
                                                    spadeDir, compHostDict)

        domList = []
        runCfgFile = MockRunConfigFile(configDir)
        cfgName = runCfgFile.create(compHostDict.keys(), domList)

        #copyDir = None
        #logPort = None
        #livePort = DAQPort.I3LIVE_ZMQ

        validate = False
        serverKill = True
        verbose = False
        dryRun = False
        killWith9 = False
        logger = None
        forceKill = True

        shell = MockParallelShell()
        shell.addExpectedPythonKill(True, killWith9=killWith9)

        # set the cached config name
        cc = CachedConfigName()
        cc.setConfigName(cfgName)
        cc.writeCacheFile(writeActiveConfig=True)

        kill(configDir, logger, clusterDesc=cluCfgFile.name(),
             validate=validate, serverKill=serverKill, verbose=verbose,
             dryRun=dryRun, killWith9=killWith9, force=forceKill,
             parallel=shell)


if __name__ == '__main__':
    unittest.main()
