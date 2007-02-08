#!/usr/bin/env python

import unittest
from CnCServer import DAQPool, RunSet

class MockConnection:
    def __init__(self, type, isInput):
        self.type = type
        self.isInput = isInput
        self.port = -1

class MockComponent:
    def __init__(self, name, num, isSrc=False):
        self.name = name
        self.num = num
        self.isSrc = isSrc
        self.host = 'localhost'

        self.connectors = []

        self.configured = False
        self.connected = False
        self.runNum = None
        self.monitorState = '???'
        self.cmdOrder = None

    def addInput(self, type):
        self.connectors.append(MockConnection(type, True))

    def addOutput(self, type):
        self.connectors.append(MockConnection(type, False))

    def configure(self, name=None):
        self.configured = True

    def connect(self, conn=None):
        self.connected = True
        return 'OK'

    def getOrder(self):
        return self.cmdOrder

    def getState(self):
        if not self.connected:
            return 'idle'
        if not self.configured:
            return 'connected'
        if not self.runNum:
            return 'ready'

        return 'running'

    def isSource(self):
        return self.isSrc

    def monitor(self):
        return self.monitorState

    def reset(self):
        self.connected = False
        self.configured = False
        self.runNum = None

    def setOrder(self, num):
        self.cmdOrder = num

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

        set = mgr.findRunset(1)
        self.failIf(set is not None, 'Found set in empty manager')

        comp = mgr.remove(MockComponent('foo', 0))

    def testAddRemove(self):
        mgr = DAQPool()

        compList = [MockComponent('foo', 0), MockComponent('bar', 0)]

        self.assertEqual(len(mgr.pool), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildReturnSet(self):
        mgr = DAQPool()

        compList = [MockComponent('foo', 0, True), MockComponent('bar', 0)]

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), len(compList))

        set = mgr.makeRunset(nameList)

        self.assertEqual(len(mgr.pool), 0)

        found = mgr.findRunset(set.id)
        self.failIf(found is None, "Couldn't find runset #" + str(set.id))

        mgr.returnRunset(set)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildMissingOutput(self):
        mgr = DAQPool()

        fooComp = MockComponent('foo', 0, True)
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

        self.assertEqual(len(mgr.pool), len(compList))

        self.assertRaises(ValueError, mgr.makeRunset, nameList)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildMissingInput(self):
        mgr = DAQPool()

        fooComp = MockComponent('foo', 0, True)
        fooComp.addOutput('foo->bar')

        barComp = MockComponent('bar', 0)
        barComp.addInput('foo->bar')
        fooComp.addOutput('bar->foo')

        compList = [fooComp, barComp]

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), len(compList))

        self.assertRaises(ValueError, mgr.makeRunset, nameList)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testStartRun(self):
        mgr = DAQPool()

        a = MockComponent('a', 0, True)
        a.addOutput('ab');

        b = MockComponent('b', 0)
        b.addInput('ab');
        b.addOutput('bc');

        c = MockComponent('c', 0)
        c.addInput('bc');

        compList = [c, a, b]

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), len(compList))

        set = mgr.makeRunset(nameList)

        self.assertEqual(len(mgr.pool), 0)
        self.assertEqual(len(set.set), len(compList))

        set.configure('abc')

        ordered = True
        prevName = None
        for s in set.set:
            if not prevName:
                prevName = s.name
            elif prevName > s.name:
                ordered = False

        self.failIf(ordered, 'Runset sorted before startRun()')

        set.startRun(1)

        ordered = True
        prevName = None
        for s in set.set:
            if not prevName:
                prevName = s.name
            elif prevName < s.name:
                ordered = False

        self.failUnless(ordered, 'Runset was not sorted by startRun()')

        set.stopRun()

        ordered = True
        prevName = None
        for s in set.set:
            if not prevName:
                prevName = s.name
            elif prevName > s.name:
                ordered = False

        self.failUnless(ordered, 'Runset was not reversed by stopRun()')

        mgr.returnRunset(set)

        self.assertEqual(set.id, None)
        self.assertEqual(set.configured, False)
        self.assertEqual(set.runNumber, None)

        self.assertEqual(len(mgr.pool), len(compList))
        self.assertEqual(len(set.set), 0)

if __name__ == '__main__':
    unittest.main()
