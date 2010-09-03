#!/usr/bin/env python

import os, socket, sys, tempfile, unittest

from DAQMocks import MockParallelShell, MockDeployComponent
import DeployPDAQ

class MockNode(object):
    def __init__(self, hostName):
        self.__hostName = hostName

    def hostName(self):
        return self.__hostName

class MockClusterConfig(object):
    def __init__(self, hosts):
        self.__nodes = []
        for n in hosts:
            self.__nodes.append(MockNode(n))

    def nodes(self):
        return self.__nodes[:]

class DeployPDAQTest(unittest.TestCase):
    def __checkDeploy(self, hosts, subdirs, delete, dryRun, deepDryRun,
                      undeploy, niceAdj=DeployPDAQ.NICE_ADJ_DEFAULT,
                      express=DeployPDAQ.EXPRESS_DEFAULT):
        topDir = tempfile.mkdtemp()
        os.mkdir(os.path.join(topDir, "target"))

        homeDir = os.path.join(topDir, "home")
        os.mkdir(homeDir)

        config = MockClusterConfig(hosts)

        parallel = MockParallelShell()
        if undeploy:
            for h in hosts:
                parallel.addExpectedUndeploy(homeDir, topDir, h)
        else:
            for h in hosts:
                parallel.addExpectedRsync(topDir, subdirs, delete, deepDryRun,
                                          h, 0, niceAdj=niceAdj,
                                          express=express)

        traceLevel = -1

        DeployPDAQ.deploy(config, parallel, homeDir, topDir, subdirs, delete,
                          dryRun, deepDryRun, undeploy, traceLevel,
                          niceAdj=niceAdj, express=express)

        parallel.check()

    def testDeployMin(self):
        delete = False
        dryRun = False
        deepDryRun = False
        undeploy = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy)

    def testDeployDelete(self):
        delete = True
        dryRun = False
        deepDryRun = False
        undeploy = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy)

    def testDeployDeepDryRun(self):
        delete = False
        dryRun = False
        deepDryRun = True
        undeploy = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy)

    def testDeployDD(self):
        delete = True
        dryRun = False
        deepDryRun = True
        undeploy = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy)

    def testDeployDryRun(self):
        delete = False
        dryRun = True
        deepDryRun = False
        undeploy = False

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy)

    def testDeployUndeploy(self):
        delete = False
        dryRun = True
        deepDryRun = False
        undeploy = True

        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy)

    def testDeployNice(self):
        delete = False
        dryRun = False
        deepDryRun = False
        undeploy = False
        niceAdj = 5
        
        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy,
                           niceAdj)

    def testDeployExpress(self):
        delete = False
        dryRun = False
        deepDryRun = False
        undeploy = False
        niceAdj = 5
        express = True
        
        hosts = ("foo", "bar")

        subdirs = ("ABC", "DEF")

        self.__checkDeploy(hosts, subdirs, delete, dryRun, deepDryRun, undeploy,
                           niceAdj, express)

if __name__ == '__main__':
    unittest.main()
