#!/usr/bin/env python

import unittest
from CnCServer import DAQPool, RunSet

class MockConnection(object):
    def __init__(self, type, isInput):
        self.type = type
        self.isInput = isInput
        self.port = -1

class MockComponent(object):
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

    def __str__(self):
        if self.num == 0:
            return self.name
        return '%s#%d' % (self.name, self.num)

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
            raise Exception(self.name + ' has not been configured')

        self.runNum = runNum

    def stopRun(self):
        if self.runNum is None:
            raise Exception(self.name + ' is not running')

        self.runNum = None

class TestDAQPool(unittest.TestCase):
    def testEmpty(self):
        mgr = DAQPool()

        runset = mgr.findRunset(1)
        self.failIf(runset is not None, 'Found set in empty manager')

        mgr.remove(MockComponent('foo', 0))

    def testAddRemove(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        compList.append(comp)

        self.assertEqual(len(mgr.pool), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildReturnSet(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa')
        compList.append(comp)

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), len(compList))

        runset = mgr.makeRunset(nameList)

        self.assertEqual(len(mgr.pool), 0)

        found = mgr.findRunset(runset.id)
        self.failIf(found is None, "Couldn't find runset #" + str(runset.id))

        mgr.returnRunset(runset)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildMissingOneOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addOutput('aaa')
        comp.addInput('xxx')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa')
        compList.append(comp)

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

    def testBuildMissingMultiOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addInput('xxx')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('xxx')
        compList.append(comp)

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

    def testBuildMatchPlusMissingMultiOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addInput('xxx')
        comp.addInput('yyy')
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa')
        compList.append(comp)

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

    def testBuildMissingOneInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa')
        comp.addOutput('xxx')
        compList.append(comp)

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

    def testBuildMatchPlusMissingMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addOutput('xxx')
        comp.addOutput('yyy')
        compList.append(comp)

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

    def testBuildMatchPlusMissingMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addOutput('aaa')
        comp.addOutput('xxx')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa')
        comp.addOutput('xxx')
        compList.append(comp)

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

    def testBuildMultiMissing(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addInput('xxx')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addOutput('xxx')
        compList.append(comp)

        comp = MockComponent('fee', 0, True)
        comp.addInput('xxx')
        compList.append(comp)

        comp = MockComponent('baz', 0)
        comp.addOutput('xxx')
        compList.append(comp)

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), len(compList))

        try:
            mgr.makeRunset(nameList)
            self.fail('Unexpected success')
        except ValueError:
            pass
        except:
            self.fail('Unexpected exception')

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

    def testBuildMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, True)
        comp.addOutput('conn')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('conn')
        compList.append(comp)

        comp = MockComponent('baz', 0)
        comp.addInput('conn')
        compList.append(comp)

        self.assertEqual(len(mgr.pool), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name)

        self.assertEqual(len(mgr.pool), len(compList))

        runset = mgr.makeRunset(nameList)

        self.assertEqual(len(mgr.pool), 0)

        found = mgr.findRunset(runset.id)
        self.failIf(found is None, "Couldn't find runset #" + str(runset.id))

        mgr.returnRunset(runset)

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

        runset = mgr.makeRunset(nameList)

        self.assertEqual(len(mgr.pool), 0)
        self.assertEqual(len(runset.set), len(compList))

        runset.configure('abc')

        ordered = True
        prevName = None
        for s in runset.set:
            if not prevName:
                prevName = s.name
            elif prevName > s.name:
                ordered = False

        self.failIf(ordered, 'Runset sorted before startRun()')

        runset.startRun(1)

        ordered = True
        prevName = None
        for s in runset.set:
            if not prevName:
                prevName = s.name
            elif prevName < s.name:
                ordered = False

        self.failUnless(ordered, 'Runset was not sorted by startRun()')

        runset.stopRun()

        ordered = True
        prevName = None
        for s in runset.set:
            if not prevName:
                prevName = s.name
            elif prevName > s.name:
                ordered = False

        self.failUnless(ordered, 'Runset was not reversed by stopRun()')

        mgr.returnRunset(runset)

        self.assertEqual(runset.id, None)
        self.assertEqual(runset.configured, False)
        self.assertEqual(runset.runNumber, None)

        self.assertEqual(len(mgr.pool), len(compList))
        self.assertEqual(len(runset.set), 0)

if __name__ == '__main__':
    unittest.main()
