#!/usr/bin/env python

import unittest
import DAQConfig
import os

class DAQConfigTest(unittest.TestCase):
    def initPDAQHome(self):
        curDir = os.getcwd()
        tstRsrc = os.path.join(curDir, 'src', 'test', 'resources')
        if not os.path.exists(tstRsrc):
            self.fail('Cannot find test resources')
        if not os.path.exists(os.path.join(tstRsrc, 'config')):
            self.fail('No "config" directory in resource directory ' +
                      tstRsrc)
        os.environ["PDAQ_HOME"] = tstRsrc
        return tstRsrc

    def lookup(self, cfg, dataList):
        for data in dataList:
            self.assert_(cfg.hasDOM(data[0]), "Didn't find mbid " + data[0])

        for data in dataList:
            try:
                dom = cfg.getIDbyName(data[1])
            except ValueError:
                self.fail("Didn't find name " + data[1])
            self.assertEqual(dom, data[0],
                             'For name %s, expected %s, not %s' %
                             (data[1], data[0], dom))

        for data in dataList:
            try:
                dom = cfg.getIDbyStringPos(data[2], data[3])
            except ValueError:
                self.fail("Didn't find string %d pos %d" % (data[2], data[3]))
            self.assertEqual(dom, data[0],
                             'For string %d pos %d, expected %s, not %s' %
                             (data[2], data[3], data[0], dom))

    def testListsSim5(self):
        metaDir = self.initPDAQHome()
        cfg = DAQConfig.DAQConfig("sim5str", metaDir + "/config")

        kinds = cfg.kinds()
        for exp in ('in-ice', 'icetop'):
            try:
                kinds.index(exp)
            except:
                self.fail('Expected kind "%s" was not returned' % exp)

        for exp in ('amanda', ):
            try:
                kinds.index(exp)
                self.fail('"kinds" should not contain %s' % exp)
            except:
                pass # expect this to fail

        comps = cfg.components()
        for exp in ('inIceTrigger', 'globalTrigger', 'eventBuilder',
                    'secondaryBuilders',  'stringHub#1001', 'stringHub#1002',
                    'stringHub#1003', 'stringHub#1004', 'stringHub#1005'):
            try:
                comps.index(exp)
            except:
                self.fail('Expected component "%s" was not returned' % exp)
        for exp in ('iceTopTrigger#0', 'amandaTrigger#0'):
            try:
                comps.index(exp)
                self.fail('"components" should not contain %s' % exp)
            except:
                pass # expect this to fail

    def testLookupSim5(self):
        metaDir = self.initPDAQHome()
        cfg = DAQConfig.DAQConfig("sim5str", metaDir + "/config")

        dataList = (('53494d550101', 'Nicholson_Baker', 1001, 1),
                    ('53494d550120', 'SIM0020', 1001, 20),
                    ('53494d550140', 'SIM0040', 1001, 40),
                    ('53494d550160', 'SIM0060', 1001, 60),
                    ('53494d550201', 'SIM0065', 1002, 1),
                    ('53494d550220', 'SIM0084', 1002, 20),
                    ('53494d550240', 'SIM0104', 1002, 40),
                    ('53494d550260', 'SIM0124', 1002, 60),
                    ('53494d550301', 'SIM0129', 1003, 1),
                    ('53494d550320', 'SIM0148', 1003, 20),
                    ('53494d550340', 'SIM0168', 1003, 40),
                    ('53494d550360', 'SIM0188', 1003, 60),
                    ('53494d550401', 'SIM0193', 1004, 1),
                    ('53494d550420', 'SIM0212', 1004, 20),
                    ('53494d550440', 'SIM0232', 1004, 40),
                    ('53494d550460', 'SIM0252', 1004, 60),
                    ('53494d550501', 'SIM0257', 1005, 1),
                    ('53494d550520', 'SIM0276', 1005, 20),
                    ('53494d550540', 'SIM0296', 1005, 40),
                    ('53494d550560', 'SIM0316', 1005, 60))

        self.lookup(cfg, dataList)

    def testListsSpsIC40IT6(self):
        metaDir = self.initPDAQHome()
        cfg = DAQConfig.DAQConfig("sps-IC40-IT6-AM-Revert-IceTop-V029",
                                  metaDir + "/config")

        kinds = cfg.kinds()
        for exp in ('amanda', 'in-ice', 'icetop'):
            try:
                kinds.index(exp)
            except:
                self.fail('Expected kind "%s" was not returned' % exp)

        comps = cfg.components()
        for exp in ('inIceTrigger', 'iceTopTrigger', 'globalTrigger',
                    'amandaTrigger', 'eventBuilder', 'secondaryBuilders',
                    'stringHub#0', 'stringHub#21', 'stringHub#29',
                    'stringHub#30', 'stringHub#38', 'stringHub#39',
                    'stringHub#40', 'stringHub#44', 'stringHub#45',
                    'stringHub#46', 'stringHub#47', 'stringHub#48',
                    'stringHub#49', 'stringHub#50', 'stringHub#52',
                    'stringHub#53', 'stringHub#54', 'stringHub#55',
                    'stringHub#56', 'stringHub#57', 'stringHub#58',
                    'stringHub#59', 'stringHub#60', 'stringHub#61',
                    'stringHub#62', 'stringHub#63', 'stringHub#64',
                    'stringHub#65', 'stringHub#66', 'stringHub#67',
                    'stringHub#68', 'stringHub#69', 'stringHub#70',
                    'stringHub#71', 'stringHub#72', 'stringHub#73',
                    'stringHub#74', 'stringHub#75', 'stringHub#76',
                    'stringHub#77', 'stringHub#78', 'stringHub#201',
                    'stringHub#202', 'stringHub#203'):
            try:
                comps.index(exp)
            except:
                self.fail('Expected component "%s" was not returned' % exp)

    def testLookupSpsIC40IT6(self):
        metaDir = self.initPDAQHome()
        cfg = DAQConfig.DAQConfig("sps-IC40-IT6-AM-Revert-IceTop-V029",
                                  metaDir + "/config")

        dataList = (('737d355af587', 'Bat', 21, 1),
                    ('499ccc773077', 'Werewolf', 66, 6),
                    ('efc9607742b9', 'Big_Two_Card', 78, 60),
                    ('1e5b72775d19', 'AMANDA_SYNC_DOM', 0, 91),
                    ('1d165fc478ca', 'AMANDA_TRIG_DOM', 0, 92),
                    )

        self.lookup(cfg, dataList)

    def testReplay(self):
        metaDir = self.initPDAQHome()
        cfg = DAQConfig.DAQConfig("replay-ic22-it4", metaDir + "/config")

        kinds = cfg.kinds()
        self.assertEquals(len(kinds), 0, "Expected empty 'kinds' list, not " +
                          str(kinds))

        comps = cfg.components()
        for exp in ('inIceTrigger', 'iceTopTrigger', 'globalTrigger',
                    'eventBuilder',
                    #'replayHub',
                    'replayHub#21', 'replayHub#29', 'replayHub#84'):
            try:
                comps.index(exp)
            except:
                self.fail('Expected component "%s" was not returned' % exp)

    def testRaise(self):
        try:
            raise DAQConfig.noDOMConfigFound("foo")
        except DAQConfig.noDOMConfigFound, e:
            self.assertEquals(str(e), "foo", "expected \"foo\" not \"%s\"" %
                              str(e))

if __name__ == '__main__':
    unittest.main()
