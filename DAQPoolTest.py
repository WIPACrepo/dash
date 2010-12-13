#!/usr/bin/env python

import unittest
from CnCServer import DAQPool

from DAQMocks import MockComponent, MockLogger

class TestDAQPool(unittest.TestCase):
    def __checkRunsetState(self, runset, expState):
        for c in runset.components():
            self.assertEquals(c.state(), expState,
                              "Comp %s state should be %s, not %s" %
                              (c.name(), expState, c.state()))

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

        self.assertEqual(mgr.numUnused(), 0)

        for c in compList:
            mgr.add(c)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

    def testBuildReturnSet(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 1234)
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        runset = mgr.makeRunset(nameList, logger)

        self.assertEqual(mgr.numUnused(), 0)

        found = mgr.findRunset(runset.id())
        self.failIf(found is None, "Couldn't find runset #%d" % runset.id())

        mgr.returnRunset(runset)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMissingOneOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp.addInput('xxx', 123)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 456)
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMissingMultiOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addInput('xxx', 123)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('xxx', 456)
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addInput('xxx', 123)
        comp.addInput('yyy', 456)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 789)
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMissingOneInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 123)
        comp.addOutput('xxx')
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addOutput('xxx')
        comp.addOutput('yyy')
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMatchPlusMissingMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('aaa')
        comp.addOutput('xxx')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('aaa', 123)
        comp.addOutput('xxx')
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMultiMissing(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addInput('xxx', 123)
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addOutput('xxx')
        compList.append(comp)

        comp = MockComponent('feeHub', 0)
        comp.addInput('xxx', 456)
        compList.append(comp)

        comp = MockComponent('baz', 0)
        comp.addOutput('xxx')
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        try:
            mgr.makeRunset(nameList, logger)
            self.fail('Unexpected success')
        except ValueError:
            pass
        except:
            self.fail('Unexpected exception')

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testBuildMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('fooHub', 0)
        comp.addOutput('conn')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addInput('conn', 123)
        compList.append(comp)

        comp = MockComponent('baz', 0)
        comp.addInput('conn', 456)
        compList.append(comp)

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        runset = mgr.makeRunset(nameList, logger)

        self.assertEqual(mgr.numUnused(), 0)

        found = mgr.findRunset(runset.id())
        self.failIf(found is None, "Couldn't find runset #%d" % runset.id())

        mgr.returnRunset(runset)

        self.assertEqual(mgr.numUnused(), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(mgr.numUnused(), 0)

        logger.checkStatus(10)

    def testStartRun(self):
        mgr = DAQPool()

        a = MockComponent('aHub', 0)
        a.addOutput('ab')

        b = MockComponent('b', 0)
        b.addInput('ab', 123)
        b.addOutput('bc')

        c = MockComponent('c', 0)
        c.addInput('bc', 456)

        compList = [c, a, b]

        self.assertEqual(mgr.numUnused(), 0)

        nameList = []
        for c in compList:
            mgr.add(c)
            nameList.append(c.name())

        self.assertEqual(mgr.numUnused(), len(compList))

        logger = MockLogger('main')
        runset = mgr.makeRunset(nameList, logger)

        self.assertEqual(mgr.numUnused(), 0)
        self.assertEqual(runset.size(), len(compList))

        self.__checkRunsetState(runset, 'connected')

        runset.configure('abc')

        self.__checkRunsetState(runset, 'ready')

        runset.startRun(1)

        self.__checkRunsetState(runset, 'running')

        runset.stopRun()

        self.__checkRunsetState(runset, 'ready')

        mgr.returnRunset(runset)

        self.assertEqual(runset.id(), None)
        self.assertEqual(runset.configured(), False)
        self.assertEqual(runset.runNumber(), None)

        self.assertEqual(mgr.numUnused(), len(compList))
        self.assertEqual(runset.size(), 0)

        logger.checkStatus(10)

if __name__ == '__main__':
    unittest.main()
