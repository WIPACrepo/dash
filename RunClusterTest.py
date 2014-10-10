#!/usr/bin/env python

import os
import unittest
from DAQConfig import DAQConfigParser
from RunCluster import RunCluster, RunClusterError


class DeployData(object):
    def __init__(self, host, name, id=0):
        self.host = host
        self.name = name
        self.id = id
        self.found = False

    def __str__(self):
        if self.id == 0 and not self.name.lower().endswith('hub'):
            return '%s/%s' % (self.host, self.name)
        return '%s/%s#%d' % (self.host, self.name, self.id)

    def isFound(self):
        return self.found

    def markFound(self):
        self.found = True

    def matches(self, host, name, id):
        return self.host == str(host) and \
            self.name.lower() == name.lower() and \
            self.id == id


class RunClusterTest(unittest.TestCase):
    CONFIG_DIR = os.path.abspath('src/test/resources/config')

    def __checkCluster(self, clusterName, cfgName, expNodes, spadeDir,
                       logCopyDir, daqLogDir, daqDataDir, verbose=False):
        cfg = DAQConfigParser.load(cfgName, RunClusterTest.CONFIG_DIR)

        cluster = RunCluster(cfg, clusterName, RunClusterTest.CONFIG_DIR)

        self.assertEqual(cluster.configName(), cfgName,
                          'Expected config name %s, not %s' %
                          (cfgName, cluster.configName()))

        sortedNodes = cluster.nodes()
        sortedNodes.sort()

        if verbose:
            print "=== RC -> %s" % cluster.configName()
            for n in sortedNodes:
                print "::  " + str(n)
                sortedComps = n.components()
                sortedComps.sort()
                for c in sortedComps:
                    print "        " + str(c)

            print "=== EXP"
            for en in sorted(expNodes, key=lambda x: str(x)):
                print "::  " + str(en)

        for node in sortedNodes:
            sortedComps = node.components()
            sortedComps.sort()
            for comp in sortedComps:
                found = False
                for en in expNodes:
                    #print "CMP %s/%s#%d <==> %s" % (node.hostName(), comp.name(), comp.id(), en)
                    if en.matches(node.hostName(), comp.name(), comp.id()):
                        found = True
                        en.markFound()
                        break
                if not found:
                    self.fail('Did not expect %s component %s' %
                              (node.hostName(), str(comp)))

        for en in expNodes:
            if not en.isFound():
                self.fail('Did not find expected component %s' % str(en))

        #hubList = cluster.getHubNodes()

        self.assertEqual(cluster.logDirForSpade(), spadeDir,
                         'SPADE log directory is "%s", not "%s"' %
                         (cluster.logDirForSpade(), spadeDir))
        self.assertEqual(cluster.logDirCopies(), logCopyDir,
                         'Log copy directory is "%s", not "%s"' %
                         (cluster.logDirCopies(), logCopyDir))
        self.assertEqual(cluster.daqLogDir(), daqLogDir,
                         'DAQ log directory is "%s", not "%s"' %
                         (cluster.daqLogDir(), daqLogDir))
        self.assertEqual(cluster.daqDataDir(), daqDataDir,
                         'DAQ data directory is "%s", not "%s"' %
                         (cluster.daqDataDir(), daqDataDir))

    def testClusterFile(self):
        cfg = DAQConfigParser.load("simpleConfig", RunClusterTest.CONFIG_DIR)

        cluster = RunCluster(cfg, "localhost", RunClusterTest.CONFIG_DIR)

        cluster.clearActiveConfig()

        cluster.writeCacheFile(False)
        cluster.writeCacheFile(True)

    def testDeployLocalhost(self):
        cfgName = 'simpleConfig'
        expNodes = [DeployData('localhost', 'inIceTrigger'),
                    DeployData('localhost', 'globalTrigger'),
                    DeployData('localhost', 'eventBuilder'),
                    DeployData('localhost', 'SecondaryBuilders'),
                    DeployData('localhost', 'stringHub', 1001),
                    DeployData('localhost', 'stringHub', 1002),
                    DeployData('localhost', 'stringHub', 1003),
                    DeployData('localhost', 'stringHub', 1004),
                    DeployData('localhost', 'stringHub', 1005),
                    ]

        daqLogDir = "logs"
        daqDataDir = "data"
        spadeDir = 'spade'
        logCopyDir = None

        self.__checkCluster("localhost", cfgName, expNodes, spadeDir,
                            logCopyDir, daqLogDir, daqDataDir)

    def testDeploySPTS64(self):
        cfgName = 'simpleConfig'
        expNodes = [DeployData('spts64-iitrigger', 'inIceTrigger'),
                    DeployData('spts64-gtrigger', 'globalTrigger'),
                    DeployData('spts64-evbuilder', 'eventBuilder'),
                    DeployData('spts64-expcont', 'SecondaryBuilders'),
                    DeployData('spts64-2ndbuild', 'stringHub', 1001),
                    DeployData('spts64-fpslave01', 'stringHub', 1002),
                    DeployData('spts64-fpslave02', 'stringHub', 1003),
                    DeployData('spts64-fpslave03', 'stringHub', 1004),
                    DeployData('spts64-fpslave04', 'stringHub', 1005),
                    ]

        daqLogDir = "/mnt/data/pdaq/log"
        daqDataDir = "/mnt/data/pdaqlocal"
        spadeDir = "/mnt/data/spade/pdaq/runs"
        logCopyDir = "/mnt/data/pdaqlocal"

        self.__checkCluster("spts64", cfgName, expNodes, spadeDir, logCopyDir,
                            daqLogDir, daqDataDir)

    def testDeployTooMany(self):
        cfgName = 'tooManyConfig'
        expNodes = [DeployData('spts64-iitrigger', 'inIceTrigger'),
                    DeployData('spts64-gtrigger', 'globalTrigger'),
                    DeployData('spts64-evbuilder', 'eventBuilder'),
                    DeployData('spts64-expcont', 'SecondaryBuilders'),
                    DeployData('spts64-stringproc01', 'stringHub', 1001),
                    DeployData('spts64-stringproc02', 'stringHub', 1002),
                    DeployData('spts64-stringproc03', 'stringHub', 1003),
                    DeployData('spts64-stringproc06', 'stringHub', 1004),
                    DeployData('spts64-stringproc07', 'stringHub', 1005),
                    ]

        daqLogDir = "logs"
        daqDataDir = "/mnt/data/pdaqlocal"
        spadeDir = 'spade'
        logCopyDir = None

        try:
            self.__checkCluster("localhost", cfgName, expNodes, spadeDir,
                                logCopyDir, daqLogDir, daqDataDir)
        except RunClusterError as rce:
            if not str(rce).endswith("Only have space for 11 of 10 hubs"):
                self.fail("Unexpected exception: " + str(rce))

    def testDeploySPS(self):
        cfgName = 'sps-IC40-IT6-Revert-IceTop-V029'
        expNodes = [DeployData('sps-trigger', 'inIceTrigger'),
                    DeployData('sps-trigger', 'iceTopTrigger'),
                    DeployData('sps-gtrigger', 'globalTrigger'),
                    DeployData('sps-evbuilder', 'eventBuilder'),
                    DeployData('sps-2ndbuild', 'SecondaryBuilders'),
                    DeployData('sps-ichub21', 'stringHub', 21),
                    DeployData('sps-ichub29', 'stringHub', 29),
                    DeployData('sps-ichub30', 'stringHub', 30),
                    DeployData('sps-ichub38', 'stringHub', 38),
                    DeployData('sps-ichub39', 'stringHub', 39),
                    DeployData('sps-ichub40', 'stringHub', 40),
                    DeployData('sps-ichub44', 'stringHub', 44),
                    DeployData('sps-ichub45', 'stringHub', 45),
                    DeployData('sps-ichub46', 'stringHub', 46),
                    DeployData('sps-ichub47', 'stringHub', 47),
                    DeployData('sps-ichub48', 'stringHub', 48),
                    DeployData('sps-ichub49', 'stringHub', 49),
                    DeployData('sps-ichub50', 'stringHub', 50),
                    DeployData('sps-ichub52', 'stringHub', 52),
                    DeployData('sps-ichub53', 'stringHub', 53),
                    DeployData('sps-ichub54', 'stringHub', 54),
                    DeployData('sps-ichub55', 'stringHub', 55),
                    DeployData('sps-ichub56', 'stringHub', 56),
                    DeployData('sps-ichub57', 'stringHub', 57),
                    DeployData('sps-ichub58', 'stringHub', 58),
                    DeployData('sps-ichub59', 'stringHub', 59),
                    DeployData('sps-ichub60', 'stringHub', 60),
                    DeployData('sps-ichub61', 'stringHub', 61),
                    DeployData('sps-ichub62', 'stringHub', 62),
                    DeployData('sps-ichub63', 'stringHub', 63),
                    DeployData('sps-ichub64', 'stringHub', 64),
                    DeployData('sps-ichub65', 'stringHub', 65),
                    DeployData('sps-ichub66', 'stringHub', 66),
                    DeployData('sps-ichub67', 'stringHub', 67),
                    DeployData('sps-ichub68', 'stringHub', 68),
                    DeployData('sps-ichub69', 'stringHub', 69),
                    DeployData('sps-ichub70', 'stringHub', 70),
                    DeployData('sps-ichub71', 'stringHub', 71),
                    DeployData('sps-ichub72', 'stringHub', 72),
                    DeployData('sps-ichub73', 'stringHub', 73),
                    DeployData('sps-ichub74', 'stringHub', 74),
                    DeployData('sps-ichub75', 'stringHub', 75),
                    DeployData('sps-ichub76', 'stringHub', 76),
                    DeployData('sps-ichub77', 'stringHub', 77),
                    DeployData('sps-ichub78', 'stringHub', 78),
                    DeployData('sps-ithub01', 'stringHub', 201),
                    #DeployData('sps-ithub02', 'stringHub', 202),
                    #DeployData('sps-ithub03', 'stringHub', 203),
                    DeployData('sps-ithub06', 'stringHub', 206),
                    ]

        daqLogDir = "/mnt/data/pdaq/log"
        daqDataDir = "/mnt/data/pdaqlocal"
        spadeDir = "/mnt/data/spade/pdaq/runs"
        logCopyDir = "/mnt/data/pdaqlocal"

        self.__checkCluster("sps", cfgName, expNodes, spadeDir, logCopyDir,
                            daqLogDir, daqDataDir)

    @classmethod
    def __addHubs(cls, nodes, hostname, numToAdd, hubnum):
        for i in xrange(numToAdd):
            nodes.append(DeployData(hostname, 'replayHub', hubnum))
            hubnum += 1
            if hubnum > 86:
                if hubnum > 211:
                    break
                if hubnum < 200:
                    hubnum = 201

        return hubnum

    def testDeployReplay(self):
        cfgName = 'replay-test'
        expNodes = [DeployData('trigger', 'iceTopTrigger'),
                    DeployData('trigger', 'iniceTrigger'),
                    DeployData('trigger', 'globalTrigger'),
                    DeployData('evbuilder', 'eventBuilder'),
                    DeployData('expcont', 'CnCServer'),
                    DeployData('2ndbuild', 'SecondaryBuilders'),
                    ]
        hubnum = 1
        hubnum = self.__addHubs(expNodes, 'daq01', 44, hubnum)
        hubnum = self.__addHubs(expNodes, 'pdaq2', 10, hubnum)
        for h in ('fpslave01', 'fpslave02'):
            hubnum = self.__addHubs(expNodes, h, 8, hubnum)
        for h in ('fpslave03', 'fpslave04'):
            hubnum = self.__addHubs(expNodes, h, 7, hubnum)
        hubnum = self.__addHubs(expNodes, 'ittest2', 7, hubnum)
        for h in ('fpslave05', 'ittest1'):
            hubnum = self.__addHubs(expNodes, h, 3, hubnum)

        daqLogDir = "/mnt/data/pdaq/log"
        daqDataDir = "/mnt/data/pdaqlocal"
        spadeDir = "/mnt/data/pdaq/spade/runs"
        logCopyDir = None

        self.__checkCluster("replay", cfgName, expNodes, spadeDir, logCopyDir,
                            daqLogDir, daqDataDir)

if __name__ == '__main__':
    unittest.main()
