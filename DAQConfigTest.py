#!/usr/bin/env python

import unittest
import DAQConfig
from os import environ

if environ.has_key("PDAQ_HOME"):
    metaDir = environ["PDAQ_HOME"]
else:
    from locate_pdaq import find_pdaq_trunk
    metaDir = find_pdaq_trunk()
                    
class DAQConfigTest(unittest.TestCase):
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
        cfg = DAQConfig.DAQConfig("sim5str", metaDir + "/config")

        kinds = cfg.kinds()
        for exp in ('in-ice', 'icetop'):
            try:
                idx = kinds.index(exp)
            except:
                self.fail('Expected kind "%s" was not returned' % exp)

        for exp in ('amanda', ):
            try:
                idx = kinds.index(exp)
                self.fail('"kinds" should not contain %s' % exp)
            except:
                pass # expect this to fail

        comps = cfg.components()
        for exp in ('inIceTrigger#0', 'globalTrigger#0', 'eventBuilder#0',
                    'secondaryBuilders#0',  'stringHub#1001', 'stringHub#1002',
                    'stringHub#1003', 'stringHub#1004', 'stringHub#1005'):
            try:
                idx = comps.index(exp)
            except:
                self.fail('Expected component "%s" was not returned' % exp)
        for exp in ('iceTopTrigger#0', 'amandaTrigger#0'):
            try:
                idx = comps.index(exp)
                self.fail('"components" should not contain %s' % exp)
            except:
                pass # expect this to fail

    def testLookupSim5(self):
        cfg = DAQConfig.DAQConfig("sim5str", metaDir + "/config")

        dataList = (('53494d550101', 'Nicholson_Baker', 1001, 1),
                    ('53494d550564', 'SIM0320', 1005, 64))

        self.lookup(cfg, dataList)

    def testListsSpsIC40IT6(self):
        cfg = DAQConfig.DAQConfig("sps-IC40-IT6-AM-Revert-IceTop-V029",
                                  metaDir + "/config")

        kinds = cfg.kinds()
        for exp in ('amanda', 'in-ice', 'icetop'):
            try:
                idx = kinds.index(exp)
            except:
                self.fail('Expected kind "%s" was not returned' % exp)

        comps = cfg.components()
        for exp in ('inIceTrigger#0', 'iceTopTrigger#0', 'globalTrigger#0',
                    'amandaTrigger#0', 'eventBuilder#0', 'secondaryBuilders#0',
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
                    'stringHub#77', 'stringHub#78', 'stringHub#81',
                    'stringHub#82', 'stringHub#83', 'stringHub#84'):
            try:
                idx = comps.index(exp)
            except:
                self.fail('Expected component "%s" was not returned' % exp)

    def testLookupSpsIC40IT6(self):
        cfg = DAQConfig.DAQConfig("sps-IC40-IT6-AM-Revert-IceTop-V029",
                                  metaDir + "/config")

        dataList = (('737d355af587', 'Bat', 21, 1),
                    ('499ccc773077', 'Werewolf', 66, 6),
                    ('3681e9662126', 'Dead_Stop', 78, 64),
                    ('1e5b72775d19', 'AMANDA_SYNC_DOM', 0, 91),
                    ('1d165fc478ca', 'AMANDA_TRIG_DOM', 0, 92))

        self.lookup(cfg, dataList)

    def testReplay(self):
        cfg = DAQConfig.DAQConfig("replay-ic22-it4", metaDir + "/config")

        kinds = cfg.kinds()
        self.assertEquals(len(kinds), 0, "Expected empty 'kinds' list, not " +
                          str(kinds))

        comps = cfg.components()
        for exp in ('inIceTrigger#0', 'iceTopTrigger#0', 'globalTrigger#0',
                    'eventBuilder#0', 'replayHub#0', 'replayHub#21',
                    'replayHub#29', 'replayHub#84'):
            try:
                idx = comps.index(exp)
            except:
                self.fail('Expected component "%s" was not returned' % exp)

if __name__ == '__main__':
    unittest.main()
