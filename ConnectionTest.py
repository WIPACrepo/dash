#!/usr/bin/env python

import unittest
from CnCServer import Connector, DAQPool

from DAQMocks import MockAppender, MockDAQClient, MockLogger

LOUD = False

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
            connectors.append(Connector(k, False, self.getNextPort()))
        for k in self.inLinks.keys():
            connectors.append(Connector(k, True, self.getNextPort()))
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

    def buildRunset(self, nodeList):
        if LOUD:
            print '-- Nodes'
            for node in nodeList:
                print node.getDescription()

        nodeLog = {}

        pool = DAQPool()
        port = -1
        for node in nodeList:
            key = '%s#%d' % (node.name, node.num)
            nodeLog[key] = MockAppender('Log-%s' % key)
            pool.add(MockDAQClient(node.name, node.num, None, port, 0,
                                   node.getConnections(), nodeLog[key],
                                   node.outLinks))
            port -= 1

        if LOUD:
            print '-- Pool has ' + str(len(pool.pool)) + ' comps'
            for k in pool.pool.keys():
                print '  ' + str(k)
                for c in pool.pool[k]:
                    print '    ' + str(c)

        numComps = len(pool.pool)

        nameList = []
        for node in nodeList:
            nameList.append(node.name + '#' + str(node.num))

        logger = MockLogger('main')
        runset = pool.makeRunset(nameList, logger)

        chkId = ConnectionTest.EXP_ID
        ConnectionTest.EXP_ID += 1

        self.assertEquals(len(pool.pool), 0)
        self.assertEquals(len(pool.sets), 1)
        self.assertEquals(pool.sets[0], runset)

        self.assertEquals(runset.id, chkId)
        self.assertEquals(len(runset.set), len(nodeList))

        # copy node list
        #
        tmpList = []
        tmpList[0:] = nodeList[0:]

        # validate all components in runset
        #
        for comp in runset.set:
            node = None
            for t in tmpList:
                if comp.name == t.name and comp.num == t.num:
                    node = t
                    tmpList.remove(t)
                    break

            self.failIf(not node, 'Could not find component ' + str(comp))

            # copy connector list
            #
            compConn = []
            compConn[0:] = comp.connectors[0:]

            # remove all output connectors
            #
            for typ in node.outLinks:
                conn = None
                for c in compConn:
                    if not c.isInput and c.type == typ:
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
                    if c.isInput and c.type == typ:
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

        for key in nodeLog:
            nodeLog[key].addExpectedExact('End of log')
        pool.returnRunset(runset)
        self.assertEquals(len(pool.pool), numComps)
        self.assertEquals(len(pool.sets), 0)

        logger.checkStatus(10)

        for key in nodeLog:
            nodeLog[key].checkStatus(10)

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
