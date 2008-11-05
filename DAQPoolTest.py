#!/usr/bin/env python

import unittest
from CnCServer import DAQPool

from DAQMocks import MockComponent, MockLogger

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

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        runset = mgr.makeRunset(nameList, logger)

        self.assertEqual(len(mgr.pool), 0)

        found = mgr.findRunset(runset.id)
        self.failIf(found is None, "Couldn't find runset #" + str(runset.id))

        mgr.returnRunset(runset)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMissingOneOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMissingMultiOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMatchPlusMissingMultiOutput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMissingOneInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMatchPlusMissingMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMatchPlusMissingMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        self.assertRaises(ValueError, mgr.makeRunset, nameList, logger)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMultiMissing(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
        comp.addInput('xxx')
        compList.append(comp)

        comp = MockComponent('bar', 0)
        comp.addOutput('xxx')
        compList.append(comp)

        comp = MockComponent('fee', 0, isSrc=True)
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

        logger = MockLogger('main')
        try:
            mgr.makeRunset(nameList, logger)
            self.fail('Unexpected success')
        except ValueError:
            pass
        except:
            self.fail('Unexpected exception')

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testBuildMultiInput(self):
        mgr = DAQPool()

        compList = []

        comp = MockComponent('foo', 0, isSrc=True)
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

        logger = MockLogger('main')
        runset = mgr.makeRunset(nameList, logger)

        self.assertEqual(len(mgr.pool), 0)

        found = mgr.findRunset(runset.id)
        self.failIf(found is None, "Couldn't find runset #" + str(runset.id))

        mgr.returnRunset(runset)

        self.assertEqual(len(mgr.pool), len(compList))

        for c in compList:
            mgr.remove(c)

        self.assertEqual(len(mgr.pool), 0)

        logger.checkEmpty()

    def testStartRun(self):
        mgr = DAQPool()

        a = MockComponent('a', 0, isSrc=True)
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

        logger = MockLogger('main')
        runset = mgr.makeRunset(nameList, logger)

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

        logger.checkEmpty()

if __name__ == '__main__':
    unittest.main()
