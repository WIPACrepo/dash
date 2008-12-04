#!/usr/bin/env python

import unittest

from DAQConst import DAQPort
from DAQLaunch import componentDB, cyclePDAQ, doKill, doLaunch, \
    killJavaProcesses, startJavaProcesses

from DAQMocks import MockParallelShell

class MockComponent(object):
    def __init__(self, name, id, level):
        self.compName = name
        self.compID = id
        self.logLevel = level

class MockNode(object):
    def __init__(self, hostName):
        self.hostName = hostName
        self.comps = []

    def addComp(self, compName, compId, logLevel):
        self.comps.append(MockComponent(compName, compId, logLevel))

class MockClusterConfig(object):
    def __init__(self, name):
        self.configName = name
        self.nodes = []

    def addNode(self, node):
        self.nodes.append(node)

    def clearActiveConfig(self):
        pass

    def writeCacheFile(self, writeActive):
        pass

class DAQLaunchTest(unittest.TestCase):
    def ZZZtestStartJava(self):
        dryRun = False
        configDir = '/foo/bar'
        logPort = 1234
        verbose = False
        checkExists = False

        logLevel = 'DEBUG'

        for compName in componentDB:
            if compName[-3:] == 'Hub':
                compId = 17
            else:
                compId = 0

            for remote in (False, True):
                if remote:
                    host = 'icecube.wisc.edu'
                else:
                    host = 'localhost'

                node = MockNode(host)
                node.addComp(compName, compId, logLevel)

                cfgName = 'mockCfg'

                config = MockClusterConfig(cfgName)
                config.addNode(node)

                for isLive in (True, False):
                    if isLive:
                        livePort = DAQPort.I3LIVE
                    else:
                        livePort = None

                    for eventCheck in (True, False):
                        parallel = MockParallelShell()

                        parallel.addExpectedJava(compName, compId, configDir,
                                                 logPort, livePort, logLevel,
                                                 verbose, eventCheck, host)

                        startJavaProcesses(dryRun, config, configDir, None,
                                           logPort, livePort, verbose,
                                           eventCheck=eventCheck,
                                           checkExists=checkExists,
                                           parallel=parallel)

                        parallel.check()

    def ZZZtestKillJava(self):
        for compName in componentDB:
            if compName[-3:] == 'Hub':
                compId = 17
            else:
                compId = 0

            dryRun = False
            verbose = False

            logLevel = 'DEBUG'

            for remote in (True, False):
                if remote:
                    host = 'icecube.wisc.edu'
                else:
                    host = 'localhost'

                node = MockNode(host)
                node.addComp(compName, compId, logLevel)

                cfgName = 'mockCfg'

                config = MockClusterConfig(cfgName)
                config.addNode(node)

                for killWith9 in (True, False):
                    parallel = MockParallelShell()

                    parallel.addExpectedJavaKill(compName, killWith9, verbose,
                                                 host)

                    killJavaProcesses(dryRun, config, verbose, killWith9,
                                      parallel)

                    parallel.check()

    def ZZZtestLaunch(self):
        dryRun = False
        configDir = '/foo/bar/cfg'
        dashDir = '/foo/bar/dash'
        logDir = '/foo/bar/log'
        spadeDir = '/foo/bar/spade'
        copyDir = '/foo/bar/copy'
        logPort = 1234
        verbose = False
        checkExists = False

        compName = 'eventBuilder'
        compId = 0
        logLevel = 'DEBUG'

        for remote in (False, True):
            if remote:
                host = 'icecube.wisc.edu'
            else:
                host = 'localhost'

            node = MockNode(host)
            node.addComp(compName, compId, logLevel)

            cfgName = 'mockCfg'

            config = MockClusterConfig(cfgName)
            config.addNode(node)

            for isLive in (True, False):
                if isLive:
                    livePort = DAQPort.I3LIVE
                else:
                    livePort = None

                for evtChk in (True, False):
                    parallel = MockParallelShell()

                    parallel.addExpectedPython(True, dashDir, configDir, logDir,
                                               spadeDir, cfgName, copyDir,
                                               logPort, livePort)
                    parallel.addExpectedJava(compName, compId, configDir,
                                             logPort, livePort, logLevel,
                                             verbose, evtChk, host)

                    doLaunch(True, False, False, config, dashDir, configDir,
                             logDir, spadeDir, copyDir, logPort, livePort,
                             eventCheck=evtChk, checkExists=checkExists,
                             parallel=parallel)

                    parallel.check()

    def ZZZtestDoKill(self):
        dryRun = False
        dashDir = '/foo/bar/dash'
        verbose = False

        compName = 'eventBuilder'
        compId = 0
        logLevel = 'DEBUG'

        for doDAQRun in (True, False):
            for remote in (False, True):
                if remote:
                    host = 'icecube.wisc.edu'
                else:
                    host = 'localhost'

                node = MockNode(host)
                node.addComp(compName, compId, logLevel)

                cfgName = 'mockCfg'

                config = MockClusterConfig(cfgName)
                config.addNode(node)

                for killWith9 in (True, False):
                    parallel = MockParallelShell()

                    parallel.addExpectedPythonKill(doDAQRun, dashDir, killWith9)
                    parallel.addExpectedJavaKill(compName, killWith9, verbose,
                                                 host)

                    doKill(doDAQRun, dryRun, dashDir, verbose, config,
                           killWith9, parallel)

                    parallel.check()

    def testCycle(self):
        configDir = '/foo/bar/cfg'
        dashDir = '/foo/bar/dash'
        logDir = '/foo/bar/log'
        spadeDir = '/foo/bar/spade'
        copyDir = '/foo/bar/copy'
        logPort = 1234
        checkExists = False

        compName = 'eventBuilder'
        compId = 0
        logLevel = 'DEBUG'

        doDAQRun = False
        dryRun = False
        verbose = False
        killWith9 = False

        for remote in (False, True):
            if remote:
                host = 'icecube.wisc.edu'
            else:
                host = 'localhost'

            node = MockNode(host)
            node.addComp(compName, compId, logLevel)

            cfgName = 'mockCfg'

            config = MockClusterConfig(cfgName)
            config.addNode(node)

            for isLive in (True, False):
                if isLive:
                    livePort = DAQPort.I3LIVE
                else:
                    livePort = None

                for eventCheck in (True, False):
                    parallel = MockParallelShell()

                    parallel.addExpectedPythonKill(doDAQRun, dashDir, killWith9)
                    parallel.addExpectedJavaKill(compName, killWith9, verbose,
                                                 host)

                    parallel.addExpectedPython(doDAQRun, dashDir, configDir,
                                               logDir, spadeDir, cfgName,
                                               copyDir, logPort, livePort)
                    parallel.addExpectedJava(compName, compId, configDir,
                                             logPort, livePort, logLevel,
                                             verbose, eventCheck, host)

                    cyclePDAQ(dashDir, config, configDir, logDir, spadeDir,
                              copyDir, logPort, livePort,
                              eventCheck=eventCheck, checkExists=checkExists,
                              parallel=parallel)

                    parallel.check()

if __name__ == '__main__':
    unittest.main()
