#!/usr/bin/env python

import os, unittest
from DAQConfig import DAQConfig
from RunCluster import RunCluster

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
        return self.host == host and self.name.lower() == name.lower() and \
            self.id == id

class RunClusterTest(unittest.TestCase):
    CONFIG_DIR = os.path.abspath('src/test/resources/config')

    def __checkCluster(self, clusterName, cfgName, expNodes, spadeDir,
                       logCopyDir):
        cfg = DAQConfig.load(cfgName, RunClusterTest.CONFIG_DIR)

        cluster = RunCluster(cfg, clusterName, RunClusterTest.CONFIG_DIR)

        self.assertEquals(cluster.configName, cfgName,
                          'Expected config name %s, not %s' %
                          (cfgName, cluster.configName))

        for node in cluster.nodes():
            for comp in node.components():
                found = False
                for en in expNodes:
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

        hubList = cluster.getHubNodes()

        self.assertEqual(cluster.logDirForSpade(), spadeDir,
                         'SPADE log directory is "%s", not "%s"' %
                         (cluster.logDirForSpade(), spadeDir))
        self.assertEqual(cluster.logDirCopies(), logCopyDir,
                         'Log copy directory is "%s", not "%s"' %
                         (cluster.logDirCopies(), logCopyDir))

    def testClusterFile(self):
        cfg = DAQConfig.load("simpleConfig", RunClusterTest.CONFIG_DIR)

        cluster = RunCluster(cfg, "localhost", RunClusterTest.CONFIG_DIR)

        cluster.clearActiveConfig()

        cluster.writeCacheFile(False)
        cluster.writeCacheFile(True)

    def testDeployLocalhost(self):
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

        self.__checkCluster("localhost", "simpleConfig", expNodes, "spade",
                            None)

    def testDeploySPTS64(self):
        cfgName = 'simpleConfig'
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

        spadeDir = 'spade'
        logCopyDir = None

        self.__checkCluster("spts64", cfgName, expNodes,
                            "/mnt/data/spade/pdaq/runs", "/mnt/data/pdaqlocal")

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
                    DeployData('sps-ithub02', 'stringHub', 202),
                    DeployData('sps-ithub03', 'stringHub', 203),
                    DeployData('sps-ithub06', 'stringHub', 206),
                    ]

        spadeDir = 'spade'
        logCopyDir = None

        self.__checkCluster("sps", cfgName, expNodes,
                            "/mnt/data/spade/pdaq/runs", "/mnt/data/pdaqlocal")

if __name__ == '__main__':
    unittest.main()
