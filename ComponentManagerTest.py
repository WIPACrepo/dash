#!/usr/bin/env python

import os
import socket
import sys
import tempfile
import threading
import unittest

from CachedConfigName import CachedFile
from ClusterDescription import ClusterDescription
from ComponentManager import ComponentManager
from DAQConst import DAQPort
from DAQMocks import MockParallelShell, MockDeployComponent
from DAQRPC import RPCServer
from RunSetState import RunSetState


class MockNode(object):
    LIST = []

    def __init__(self, hostname):
        self.__hostname = hostname
        self.__comps = []

    def __str__(self):
        return "%s[%s]" % (str(self.__hostname), str(self.__comps))

    def addComp(self, compName, compId, logLevel, hsDir, hsInterval,
                hsMaxFiles, jvmPath, jvmServer, jvmHeapInit, jvmHeapMax,
                jvmArgs, jvmExtraArgs, alertEMail, ntpHost):
        comp = MockDeployComponent(compName, compId, logLevel, hsDir,
                                   hsInterval, hsMaxFiles, jvmPath, jvmServer,
                                   jvmHeapInit, jvmHeapMax, jvmArgs,
                                   jvmExtraArgs, alertEMail, ntpHost,
                                   host=self.__hostname)
        self.__comps.append(comp)
        return comp

    def components(self):
        return self.__comps

    @property
    def hostname(self):
        return self.__hostname


class MockClusterConfig(object):
    def __init__(self, name):
        self.__configName = name
        self.__nodes = []

    def addNode(self, node):
        self.__nodes.append(node)

    def clearActiveConfig(self):
        pass

    @property
    def configName(self):
        return self.__configName

    @property
    def description(self):
        return None

    def nodes(self):
        return self.__nodes[:]

    def writeCacheFile(self, writeActive):
        pass


class MockServer(RPCServer):
    STATE_KEY = "state"
    COMPS_KEY = "comps"

    def __init__(self):
        self.__runsets = {}
        self.__unused = []
        self.__nextID = 1

        self.__server = RPCServer(DAQPort.CNCSERVER)
        self.__server.register_function(self.__listCompDicts,
                                        'rpc_component_list_dicts')
        self.__server.register_function(self.__runsetCount,
                                        'rpc_runset_count')
        self.__server.register_function(self.__runsetListIDs,
                                        'rpc_runset_list_ids')
        self.__server.register_function(self.__runsetListComps,
                                        'rpc_runset_list')
        self.__server.register_function(self.__runsetState,
                                        'rpc_runset_state')

        t = threading.Thread(name="MockServer",
                             target=self.__server.serve_forever, args=())
        t.setDaemon(True)
        t.start()

    def __listCompDicts(self, idList=None, getAll=True):
        dictlist = []
        for c in self.__unused:
            newc = {}
            for k in c:
                newc[k] = c[k]
            dictlist.append(newc)
        return dictlist

    def __runsetCount(self):
        return len(self.__runsets)

    def __runsetListComps(self, rsid):
        dictlist = []

        if rsid in self.__runsets:
            for c in self.__runsets[rsid][self.COMPS_KEY]:
                newc = {}
                for k in c:
                    if k == self.STATE_KEY:
                        continue
                    newc[k] = c[k]
                dictlist.append(newc)

        return dictlist

    def __runsetListIDs(self):
        return self.__runsets.keys()

    def __runsetState(self, rsid):
        if not rsid in self.__runsets:
            return RunSetState.DESTROYED

        return self.__runsets[rsid][self.STATE_KEY]

    def addUnusedComponent(self, name, num, host):
        self.__unused.append({"compName" : name, "compNum" : num,
                              "host" : host})

    def addRunset(self, state, complist=None):
        fulldict = {}
        fulldict[self.STATE_KEY] = state
        if complist is not None:
            newlist = []
            for comp in complist:
                newdict = {}
                for k in comp:
                    newdict[k] = comp[k]
                newlist.append(newdict)
            fulldict[self.COMPS_KEY] = newlist

        rsid = self.__nextID
        self.__nextID += 1
        self.__runsets[rsid] = fulldict

    def close(self):
        self.__server.server_close()

class ComponentManagerTest(unittest.TestCase):
    CONFIG_DIR = os.path.abspath('src/test/resources/config')

    def setUp(self):
        self.__srvr = None

    def tearDown(self):
        if self.__srvr is not None:
            self.__srvr.close()
        CachedFile.clearActiveConfig()

    def testStartJava(self):
        dryRun = False
        configDir = '/foo/cfg'
        daqDataDir = '/foo/baz'
        logPort = 1234

        hsDir = "/mnt/data/testpath"
        hsInterval = 11.1
        hsMaxFiles = 12345

        jvmPath = "java"
        jvmServer = False
        jvmHeapInit = "1m"
        jvmHeapMax = "12m"
        jvmArgs = "-Xarg"
        jvmExtra = "-Xextra"

        alertEMail = "xxx@yyy.zzz"
        ntpHost = "NtPhOsT"

        verbose = False
        checkExists = False

        logLevel = 'DEBUG'

        for compName in ComponentManager.listComponents():
            if compName[-3:] == 'hub':
                compName = compName[:-3] + "Hub"
                compId = 17
            else:
                compId = 0
                if compName.endswith("builder"):
                    compName = compName[:-7] + "Builder"

            for host in MockNode.LIST:
                node = MockNode(host)
                comp = node.addComp(compName, compId, logLevel, hsDir,
                                    hsInterval, hsMaxFiles, jvmPath, jvmServer,
                                    jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra,
                                    alertEMail, ntpHost)

                for isLive in (True, False):
                    if isLive:
                        livePort = DAQPort.I3LIVE
                    else:
                        livePort = None

                    for eventCheck in (True, False):
                        parallel = MockParallelShell()

                        parallel.addExpectedJava(comp, configDir, daqDataDir,
                                                 logPort, livePort, verbose,
                                                 eventCheck, host)

                        ComponentManager.startComponents(node.components(),
                                                         dryRun, verbose,
                                                         configDir, daqDataDir,
                                                         logPort, livePort,
                                                         eventCheck=eventCheck,
                                                         checkExists=checkExists,
                                                         parallel=parallel)

                        parallel.check()

    def testKillJava(self):
        for compName in ComponentManager.listComponents():
            if compName[-3:] == 'hub':
                compId = 17
            else:
                compId = 0

            dryRun = False
            verbose = False

            hsDir = "/mnt/data/tstkill"
            hsInterval = 12.3
            hsMaxFiles = 12345

            jvmPath = "java"
            jvmServer = False
            jvmHeapInit = "1m"
            jvmHeapMax = "12m"
            jvmArgs = "-Xarg"
            jvmExtra = "-Xextra"

            alertEMail = "abc@def"
            ntpHost = "NTP1"

            logLevel = 'DEBUG'

            for host in MockNode.LIST:
                node = MockNode(host)
                node.addComp(compName, compId, logLevel, hsDir, hsInterval,
                             hsMaxFiles, jvmPath, jvmServer, jvmHeapInit,
                             jvmHeapMax, jvmArgs, jvmExtra, alertEMail,
                             ntpHost)

                for killWith9 in (True, False):
                    parallel = MockParallelShell()

                    parallel.addExpectedJavaKill(compName, compId, killWith9,
                                                 verbose, host)

                    ComponentManager.killComponents(node.components(),
                                                    dryRun=dryRun,
                                                    verbose=verbose,
                                                    killWith9=killWith9,
                                                    parallel=parallel)

                    parallel.check()

    def testLaunch(self):
        tmpdir = tempfile.mkdtemp()
        dryRun = False
        configDir = os.path.join(tmpdir, 'cfg')
        daqDataDir = os.path.join(tmpdir, 'data')
        dashDir = os.path.join(tmpdir, 'dash')
        logDir = os.path.join(tmpdir, 'log')
        spadeDir = os.path.join(tmpdir, 'spade')
        copyDir = os.path.join(tmpdir, 'copy')
        logPort = 1234
        verbose = False
        checkExists = False

        compName = 'eventBuilder'
        compId = 0

        hsDir = "/a/b/c"
        hsInterval = 1.0
        hsMaxFiles = 1

        jvmPath = "java"
        jvmServer = False
        jvmHeapInit = "1m"
        jvmHeapMax = "12m"
        jvmArgs = "-Xarg"
        jvmExtra = "-Xextra"

        alertEMail = "abc@def.ghi"
        ntpHost = "tempus"

        logLevel = 'DEBUG'

        # if there are N targets, range is 2^N
        for targets in range(2):
            doCnC = (targets & 1) == 1

            for host in MockNode.LIST:
                node = MockNode(host)
                comp = node.addComp(compName, compId, logLevel, hsDir,
                                    hsInterval, hsMaxFiles, jvmPath, jvmServer,
                                    jvmHeapInit, jvmHeapMax, jvmArgs, jvmExtra,
                                    alertEMail, ntpHost)

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

                        cluDesc = None

                        parallel.addExpectedPython(doCnC, dashDir, configDir,
                                                   logDir, daqDataDir,
                                                   spadeDir, cluDesc, cfgName,
                                                   copyDir, logPort, livePort)
                        parallel.addExpectedJava(comp, configDir, daqDataDir,
                                                 DAQPort.CATCHALL, livePort,
                                                 verbose, evtChk, host)

                        dryRun = False
                        logDirFallback = None

                        ComponentManager.launch(doCnC, dryRun, verbose,
                                                config, dashDir, configDir,
                                                daqDataDir, logDir,
                                                logDirFallback, spadeDir,
                                                copyDir, logPort, livePort,
                                                eventCheck=evtChk,
                                                checkExists=checkExists,
                                                startMissing=False,
                                                parallel=parallel)

                        parallel.check()

    def testDoKill(self):
        dryRun = False
        verbose = False

        compName = 'eventBuilder'
        compId = 0

        hsDir = "/x/y/z"
        hsInterval = 2.0
        hsMaxFiles = 100

        jvmPath = "java"
        jvmServer = False
        jvmHeapInit = "1m"
        jvmHeapMax = "12m"
        jvmArgs = "-Xarg"
        jvmExtra = "-Xextra"

        alertEMail = "alert@email"
        ntpHost = "ntpHost"

        logLevel = 'DEBUG'
        runLogger = None

        # if there are N targets, range is 2^N
        for targets in range(2):
            doCnC = (targets & 1) == 1

            for host in MockNode.LIST:
                node = MockNode(host)
                node.addComp(compName, compId, logLevel, hsDir, hsInterval,
                             hsMaxFiles, jvmPath, jvmServer, jvmHeapInit,
                             jvmHeapMax, jvmArgs, jvmExtra, alertEMail,
                             ntpHost)

                for killWith9 in (True, False):
                    parallel = MockParallelShell()

                    parallel.addExpectedPythonKill(doCnC, killWith9)
                    parallel.addExpectedJavaKill(compName, compId, killWith9,
                                                 verbose, host)

                    ComponentManager.kill(node.components(), verbose=verbose,
                                          dryRun=dryRun, killCnC=doCnC,
                                          killWith9=killWith9,
                                          logger=runLogger, parallel=parallel)

                    parallel.check()

    def testCountActiveNoServer(self):
        (rsDict, num) = ComponentManager.countActiveRunsets()
        self.assertEqual(num, 0, "Didn't expect any runsets, got %d" % num)

    def testCountActive(self):
        self.__srvr = MockServer()
        (rsDict, num) = ComponentManager.countActiveRunsets()
        self.assertEqual(num, 0, "Didn't expect any runsets, got %d" % num)

        self.__srvr.addRunset(RunSetState.RUNNING)
        self.__srvr.addRunset(RunSetState.READY)
        (rsDict, num) = ComponentManager.countActiveRunsets()
        self.assertEqual(num, 1, "Expected %d runsets, got %d" % (1, num))

    def testGetActiveNothing(self):
        comps = ComponentManager.getActiveComponents(None)
        self.failIf(comps is None,
                    "getActiveComponents should not return None")

    def testGetActiveConfig(self):
        configName = "simpleConfig"
        CachedFile.writeCacheFile(configName, True)

        clusterDesc = ClusterDescription.SPTS64

        comps = ComponentManager.getActiveComponents(clusterDesc,
                                                     configDir=self.CONFIG_DIR,
                                                     validate=False)
        self.failIf(comps is None,
                    "getActiveComponents should not return None")

        expComps = ("eventBuilder", "SecondaryBuilders", "globalTrigger",
                    "inIceTrigger", "stringHub#1001", "stringHub#1002",
                    "stringHub#1003", "stringHub#1004", "stringHub#1005")
        self.assertEqual(len(comps), len(expComps),
                         "Expected %d components, got %d (%s)" %
                         (len(expComps), len(comps), comps))

        names = []
        for c in comps:
            names.append(c.fullname)

        for c in expComps:
            self.failUnless(c in names,
                            "Expected component %s is not in (%s)" %
                            (c, names))

    def testGetActiveServer(self):
        self.__srvr = MockServer()

        expUnused = (("foo", 1, "www.icecube.wisc.edu"),
                     ("bar", 0, "localhost"))

        for uu in expUnused:
            self.__srvr.addUnusedComponent(uu[0], uu[1], uu[2])

        expRSComps = (("abc", 2, "127.0.0.1"),
                      ("cde", 0, "www.google.com"))

        compdict = []
        for rc in expRSComps:
            compdict.append({
                "compName" : rc[0],
                "compNum" : rc[1],
                "host" : rc[2],
            })
        self.__srvr.addRunset(RunSetState.RUNNING, compdict)

        clusterDesc = ClusterDescription.SPTS64

        comps = ComponentManager.getActiveComponents(clusterDesc,
                                                     configDir=self.CONFIG_DIR,
                                                     validate=False,
                                                     useCnC=True)
        self.failIf(comps is None,
                    "getActiveComponents should not return None")

        totComps = len(expUnused) + len(expRSComps)
        self.assertEqual(totComps, len(comps),
                         "Expected %d components, got %d (%s)" %
                         (totComps, len(comps), comps))

        names = []
        for c in comps:
            names.append(c.fullname)

        for expList in (expUnused, expRSComps):
            for c in expList:
                if c[1] == 0:
                    expName = c[0]
                else:
                    expName = "%s#%d" % (c[0], c[1])
                self.failUnless(expName in names,
                                "Expected component %s is not in (%s)" %
                                (expName, names))

if __name__ == '__main__':
    # make sure icecube.wisc.edu is valid
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    for rmtHost in ('localhost', 'icecube.wisc.edu'):
        try:
            s.connect((rmtHost, 56))
            MockNode.LIST.append(rmtHost)
        except:
            print >>sys.stderr, \
                "Warning: Remote host %s is not valid" % rmtHost

    unittest.main()
