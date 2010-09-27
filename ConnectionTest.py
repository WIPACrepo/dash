#!/usr/bin/env python

import shutil, sys, tempfile, unittest
from CnCServer import Connector, DAQPool

from DAQMocks import MockAppender, MockDAQClient, MockLogger, MockRunConfigFile

LOUD = False

class MyDAQPool(DAQPool):
    def returnRunsetComponents(self, rs, verbose=False, killWith9=True,
                               eventCheck=False):
        rs.returnComponents(self, None, None, None, None, None, None, None,
                            None)

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
        for k in self.outLinks.keys():
            connectors.append(Connector(k, Connector.OUTPUT,
                                        self.getNextPort()))
        for k in self.inLinks.keys():
            connectors.append(Connector(k, Connector.INPUT,
                                        self.getNextPort()))
        return connectors

    def getDescription(self):
        rtnStr = str(self)

        if len(self.outLinks) > 0:
            rtnStr += ' OUT['

            firstK = True
            for k in self.outLinks.keys():
                if firstK:
                    firstK = False
                else:
                    rtnStr += ','

                rtnStr += k + '='

                firstL = True
                for l in self.outLinks[k]:
                    if firstL:
                        firstL = False
                    else:
                        rtnStr += ','

                    rtnStr += str(l)

            rtnStr += ']'
                
        if len(self.inLinks) > 0:
            rtnStr += ' IN['

            firstK = True
            for k in self.inLinks.keys():
                if firstK:
                    firstK = False
                else:
                    rtnStr += ','

                rtnStr += k + '='

                firstL = True
                for l in self.inLinks[k]:
                    if firstL:
                        firstL = False
                    else:
                        rtnStr += ','

                    rtnStr += str(l)

            rtnStr += ']'

        return rtnStr

    def getNextPort(self):
        port = Node.CONN_PORT
        Node.CONN_PORT -= 1
        return port

    def link(self, comp, ioType, isOutput):
        if isOutput:
            links = self.outLinks
        else:
            links = self.inLinks

        if not links.has_key(ioType):
            links[ioType] = []

        links[ioType].append(comp)

class ConnectionTest(unittest.TestCase):
    EXP_ID = 1

    def buildRunset(self, nodeList, extraLoud=True):
        if LOUD:
            print '-- Nodes'
            for node in nodeList:
                print node.getDescription()

        nodeLog = {}

        pool = MyDAQPool()
        port = -1
        for node in nodeList:
            key = '%s#%d' % (node.name, node.num)
            nodeLog[key] = MockAppender('Log-%s' % key)
            pool.add(MockDAQClient(node.name, node.num, None, port, 0,
                                   node.getConnections(), nodeLog[key],
                                   node.outLinks, extraLoud=extraLoud))
            port -= 1
        self.assertEqual(pool.numComponents(), len(nodeList))

        if LOUD:
            print '-- Pool has %s comps' % pool.numComponents()
            for c in pool.components():
                print '    %s' % str(c)

        numComps = pool.numComponents()

        nameList = []
        for node in nodeList:
            nameList.append(node.name + '#' + str(node.num))

        rcFile = MockRunConfigFile(self.__runConfigDir)
        runConfig = rcFile.create(nameList, [])

        logger = MockLogger('main')
        logger.addExpectedExact("Loading run configuration \"%s\"" %
                                runConfig)
        logger.addExpectedExact("Loaded run configuration \"%s\"" % runConfig)
        logger.addExpectedRegexp(r"Built runset #\d+: .*")

        runset = pool.makeRunset(self.__runConfigDir, runConfig, 0, logger,
                                 forceRestart=False, strict=False)

        chkId = ConnectionTest.EXP_ID
        ConnectionTest.EXP_ID += 1

        self.assertEquals(pool.numUnused(), 0)
        self.assertEquals(pool.numSets(), 1)
        self.assertEquals(pool.runset(0), runset)

        self.assertEquals(runset.id(), chkId)
        self.assertEquals(runset.size(), len(nodeList))

        # copy node list
        #
        tmpList = nodeList[:]

        # validate all components in runset
        #
        for comp in runset.components():
            node = None
            for t in tmpList:
                if comp.name() == t.name and comp.num() == t.num:
                    node = t
                    tmpList.remove(t)
                    break

            self.failIf(not node, 'Could not find component ' + str(comp))

            # copy connector list
            #
            compConn = comp.connectors()

            # remove all output connectors
            #
            for typ in node.outLinks:
                conn = None
                for c in compConn:
                    if not c.isInput() and c.name() == typ:
                        conn = c
                        compConn.remove(c)
                        break

                self.failIf(not conn, 'Could not find connector ' + typ +
                            ' for component ' + str(comp))

            # remove all input connectors
            #
            for typ in node.inLinks:
                conn = None
                for c in compConn:
                    if c.isInput() and c.name() == typ:
                        conn = c
                        compConn.remove(c)
                        break

                self.failIf(not conn, 'Could not find connector ' + typ +
                            ' for component ' + str(comp))

            # whine if any connectors are left
            #
            self.assertEquals(len(compConn), 0, 'Found extra connectors in ' +
                              str(compConn))

        # whine if any components are left
        #
        self.assertEquals(len(tmpList), 0, 'Found extra components in ' +
                          str(tmpList))

        if LOUD:
            print '-- SET: ' + str(runset)

        if extraLoud:
            for key in nodeLog:
                nodeLog[key].addExpectedExact('End of log')
                nodeLog[key].addExpectedExact('Reset log to ?LOG?')
        pool.returnRunset(runset, logger)
        self.assertEquals(pool.numComponents(), numComps)
        self.assertEquals(pool.numSets(), 0)

        logger.checkStatus(10)

        for key in nodeLog:
            nodeLog[key].checkStatus(10)

    def setUp(self):
        self.__runConfigDir = tempfile.mkdtemp()

    def tearDown(self):
        if self.__runConfigDir is not None:
            shutil.rmtree(self.__runConfigDir, ignore_errors=True)

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

        self.buildRunset(allNodes)

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

        self.buildRunset(allNodes)

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

        self.buildRunset(allNodes)

if __name__ == '__main__':
    unittest.main()
