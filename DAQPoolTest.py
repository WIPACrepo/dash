#!/usr/bin/env python

import unittest
from DAQElement import DAQPool, RunSet

class MockConnection:
    def __init__(self, type, isInput):
        self.type = type
        self.isInput = isInput
        self.port = -1

class MockComponent:
    def __init__(self, name, num):
        self.name = name
        self.num = num
        self.host = 'localhost'

        self.connectors = []

        self.configured = False
        self.connected = False
        self.runNum = None
        self.monitorState = '???'

    def addInput(self, type):
        self.connectors.append(MockConnection(type, True))

    def addOutput(self, type):
        self.connectors.append(MockConnection(type, False))

    def configure(self):
        self.configured = True

    def connect(self, conn=None):
        self.connected = True

    def getState(self):
        if not self.configured:
            return 'Idle'

        if not self.connected:
            return "Configured"
        if not self.runNum:
            return 'Ready'

        return 'Running'

    def monitor(self):
        return self.monitorState

    def reset(self):
        self.configured = False

    def startRun(self, runNum):
        if not self.configured:
            raise Error, name + ' has not been configured'

        self.runNum = runNum

    def stopRun(self):
        if self.runNum is None:
            raise Error, name + ' is not running'

        self.runNum = None

class TestDAQPool(unittest.TestCase):
    def testEmpty(self):
        mgr = DAQPool()

        set = mgr.findSet(1)
        self.failIf(set is not None, 'Found set in empty manager')

        comp = mgr.remove(MockComponent('foo', 0))

    def testAddRemove(self):
        mgr = DAQPool()

        compList = [MockComponent('foo', 0), MockComponent('bar', 0)]

        self.assertEqual(len(mgr.pool), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(len(mgr.pool), 2)

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildReturnSet(self):
        mgr = DAQPool()

        compList = [MockComponent('foo', 0), MockComponent('bar', 0)]

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), 2)

        set = mgr.makeSet(nameList)

        self.assertEqual(len(mgr.pool), 0)

        found = mgr.findSet(set.id)
        self.failIf(found is None, "Couldn't find runset #" + str(set.id))

        mgr.returnSet(set)

        self.assertEqual(len(mgr.pool), 2)

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildFailed(self):
        mgr = DAQPool()

        fooComp = MockComponent('foo', 0)
        fooComp.addInput('bar->foo')
        fooComp.addOutput('foo->bar')

        barComp = MockComponent('bar', 0)
        barComp.addInput('foo->bar')

        compList = [fooComp, barComp]

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), 2)

        self.assertRaises(ValueError, mgr.makeSet, nameList)

        self.assertEqual(len(mgr.pool), 2)

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

if __name__ == '__main__':
    unittest.main()
