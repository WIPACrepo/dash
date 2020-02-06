#!/usr/bin/env python

from __future__ import print_function

import shutil
import tempfile
import unittest
from CnCServer import Connector, DAQPool

from DAQMocks import MockDAQClient, MockLogger, MockRunConfigFile

LOUD = False


class MyDAQPool(DAQPool):
    def return_runset_components(self, rs, verbose=False, kill_with_9=True,
                                 event_check=False):
        rs.return_components(self, None, None, None, None, None,
                             verbose=verbose, kill_with_9=kill_with_9,
                             event_check=event_check)


class Node(object):
    IS_OUTPUT = True
    IS_INPUT = False

    CONN_PORT = -1

    def __init__(self, name, num=0):
        self.name = name
        self.num = num
        self.outLinks = {}
        self.inLinks = {}

    def __str__(self):
        return self.name + '#' + str(self.num)

    def connectOutputTo(self, comp, ioType):
        self.link(comp, ioType, Node.IS_OUTPUT)
        comp.link(self, ioType, Node.IS_INPUT)

    def getConnections(self):
        connectors = []
        for k in list(self.outLinks.keys()):
            connectors.append(Connector(k, Connector.OUTPUT,
                                        self.getNextPort()))
        for k in list(self.inLinks.keys()):
            connectors.append(Connector(k, Connector.INPUT,
                                        self.getNextPort()))
        return connectors

    def getNextPort(self):
        port = Node.CONN_PORT
        Node.CONN_PORT -= 1
        return port

    def link(self, comp, ioType, is_output):
        if is_output:
            links = self.outLinks
        else:
            links = self.inLinks

        if ioType not in links:
            links[ioType] = []

        links[ioType].append(comp)


class ConnectionTest(unittest.TestCase):
    EXP_ID = 1

    def __build_runset(self, nodeList, extra_loud=True):
        if LOUD:
            print('-- Nodes')
            for node in nodeList:
                print(node.getDescription())

        nodeLog = {}

        pool = MyDAQPool()
        port = -1
        for node in nodeList:
            key = '%s#%d' % (node.name, node.num)
            nodeLog[key] = MockLogger('Log-%s' % key)
            pool.add(MockDAQClient(node.name, node.num, None, port, 0,
                                   node.getConnections(), nodeLog[key],
                                   node.outLinks, extra_loud=extra_loud))
            port -= 1
        self.assertEqual(pool.num_components, len(nodeList))

        if LOUD:
            print('-- Pool has %s comps' % pool.num_components)
            for c in pool.components():
                print('    %s' % str(c))

        numComps = pool.num_components

        nameList = []
        for node in nodeList:
            nameList.append(node.name + '#' + str(node.num))

        rcFile = MockRunConfigFile(self.__run_config_dir)
        run_config = rcFile.create(nameList, {})

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                run_config)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % run_config)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        daq_data_dir = None

        runset = pool.make_runset(self.__run_config_dir, run_config, 0, 0,
                                  logger, daq_data_dir, force_restart=False,
                                  strict=False)

        chkId = ConnectionTest.EXP_ID
        ConnectionTest.EXP_ID += 1

        self.assertEqual(pool.num_unused, 0)
        self.assertEqual(pool.num_sets, 1)
        self.assertEqual(pool.runset(0), runset)

        self.assertEqual(runset.id, chkId)
        self.assertEqual(runset.size(), len(nodeList))

        # copy node list
        #
        tmpList = nodeList[:]

        # validate all components in runset
        #
        for comp in runset.components():
            node = None
            for t in tmpList:
                if comp.name == t.name and comp.num == t.num:
                    node = t
                    tmpList.remove(t)
                    break

            self.assertFalse(not node,
                             "Could not find component " + str(comp))

            # copy connector list
            #
            compConn = comp.connectors()

            # remove all output connectors
            #
            for typ in node.outLinks:
                conn = None
                for c in compConn:
                    if not c.is_input and c.name == typ:
                        conn = c
                        compConn.remove(c)
                        break

                self.assertFalse(not conn, "Could not find connector " + typ +
                                 " for component " + str(comp))

            # remove all input connectors
            #
            for typ in node.inLinks:
                conn = None
                for c in compConn:
                    if c.is_input and c.name == typ:
                        conn = c
                        compConn.remove(c)
                        break

                self.assertFalse(not conn, "Could not find connector " + typ +
                                 " for component " + str(comp))

            # whine if any connectors are left
            #
            self.assertEqual(len(compConn), 0, 'Found extra connectors in ' +
                             str(compConn))

        # whine if any components are left
        #
        self.assertEqual(len(tmpList), 0, 'Found extra components in ' +
                         str(tmpList))

        if LOUD:
            print('-- SET: ' + str(runset))

        if extra_loud:
            for key in nodeLog:
                nodeLog[key].addExpectedExact('End of log')
                nodeLog[key].addExpectedExact('Reset log to ?LOG?')
        pool.return_runset(runset, logger)
        self.assertEqual(pool.num_components, numComps)
        self.assertEqual(pool.num_sets, 0)

        logger.checkStatus(10)

        for key in nodeLog:
            nodeLog[key].checkStatus(10)

    def setUp(self):
        self.__run_config_dir = tempfile.mkdtemp()

    def tearDown(self):
        if self.__run_config_dir is not None:
            shutil.rmtree(self.__run_config_dir, ignore_errors=True)

    def testSimple(self):
        # build nodes
        #
        n1a = Node('oneA')
        n1b = Node('oneB')
        n2 = Node('two')
        n3 = Node('three')
        n4 = Node('four')

        # connect nodes
        #
        n1a.connectOutputTo(n2, 'out1')
        n1b.connectOutputTo(n2, 'out1')
        n2.connectOutputTo(n3, 'out2')
        n3.connectOutputTo(n4, 'out3')

        # build list of all nodes
        #
        allNodes = [n1a, n1b, n2, n3, n4]

        self.__build_runset(allNodes)

    def testStandard(self):
        # build nodes
        #
        shList = []
        ihList = []

        for i in range(0, 4):
            shList.append(Node('StringHub', i + 10))
            ihList.append(Node('IcetopHub', i + 20))

        gt = Node('GlobalTrigger')
        iit = Node('InIceTrigger')
        itt = Node('IceTopTrigger')
        eb = Node('EventBuilder')

        # connect nodes
        #
        for sh in shList:
            sh.connectOutputTo(iit, 'stringHit')
            eb.connectOutputTo(sh, 'rdoutReq')
            sh.connectOutputTo(eb, 'rdoutData')

        for ih in ihList:
            ih.connectOutputTo(itt, 'icetopHit')
            eb.connectOutputTo(ih, 'rdoutReq')
            ih.connectOutputTo(eb, 'rdoutData')

        iit.connectOutputTo(gt, 'inIceTrigger')
        itt.connectOutputTo(gt, 'iceTopTrigger')

        gt.connectOutputTo(eb, 'glblTrigger')

        # build list of all nodes
        #
        allNodes = [gt, iit, itt, eb]
        for i in shList:
            allNodes.append(i)
        for i in ihList:
            allNodes.append(i)

        self.__build_runset(allNodes)

    def testComplex(self):
        # build nodes
        #
        a1 = Node('A', 1)
        a2 = Node('A', 2)
        b1 = Node('B', 1)
        b2 = Node('B', 2)
        c = Node('C')
        d = Node('D')
        e = Node('E')
        f = Node('F')
        g = Node('G')
        h = Node('H')
        i = Node('I')

        # connect nodes
        #
        a1.connectOutputTo(c, 'DataA')
        a2.connectOutputTo(c, 'DataA')
        b1.connectOutputTo(d, 'DataB')
        b2.connectOutputTo(d, 'DataB')

        c.connectOutputTo(e, 'DataC')
        d.connectOutputTo(f, 'DataD')
        e.connectOutputTo(f, 'DataE')
        f.connectOutputTo(g, 'DataF')
        g.connectOutputTo(h, 'DataG')
        h.connectOutputTo(e, 'BackH')
        h.connectOutputTo(i, 'DataH')

        # build list of all nodes
        #
        allNodes = [a1, a2, b1, b2, c, d, e, f, g, h, i]

        self.__build_runset(allNodes)


if __name__ == '__main__':
    unittest.main()
