#!/usr/bin/env python

import os
import unittest

from DAQConfig import DAQConfigParser


class CommonCode(unittest.TestCase):
    TSTRSRC = None
    OLDFMT = None
    NEWFMT = None

    @classmethod
    def __checkSubdir(cls, topdir, subname):
        subdir = os.path.join(topdir, subname)
        if not os.path.exists(subdir):
            cls.fail('No "%s" subdirectory for "%s"' % (subdir, topdir))

        return subdir

    @classmethod
    def getConfigDir(cls, newFormat=None):
        if cls.TSTRSRC is None:
            curDir = os.getcwd()
            tstRsrc = os.path.join(curDir, 'src', 'test',
                                   'resources', 'config')
            if not os.path.exists(tstRsrc):
                cls.fail('Cannot find test resources')
            os.environ["PDAQ_HOME"] = tstRsrc
            cls.TSTRSRC = tstRsrc

        # if 'newFormat' is None, return the base config directory
        if newFormat is None:
            return cls.TSTRSRC

        # look for the appropriate subdirectory
        if newFormat:
            if cls.NEWFMT is None:
                cls.NEWFMT = cls.__checkSubdir(cls.TSTRSRC, 'new_format')
            subdir = cls.NEWFMT
        else:
            if cls.OLDFMT is None:
                cls.OLDFMT = cls.__checkSubdir(cls.TSTRSRC, 'old_format')
            subdir = cls.OLDFMT

        # return the subdirectory
        return subdir

    def lookup(self, cfg, dataList):
        for data in dataList:
            self.assertTrue(cfg.hasDOM(data[0]),
                            "Didn't find mbid " + data[0])

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

    def runNamesTest(self, newFormat):
        cfgDir = self.getConfigDir(newFormat=newFormat)

        simpledata = ("simpleConfig", 5, "IniceGlobalTest")
        sps40data = ("sps-IC40-IT6-AM-Revert-IceTop-V029", 41,
                     "sps-icecube-amanda-008")
        for data in (simpledata, sps40data):
            n = data[0]

            cfg = DAQConfigParser.load(n, cfgDir)
            self.assertEqual(n, cfg.basename(),
                             "Expected %s, not %s" % (n, cfg.basename()))
            fullname = os.path.join(cfgDir, n + ".xml")
            self.assertEqual(fullname, cfg.configFile(),
                             "Expected %s, not %s" %
                             (fullname, cfg.configFile()))

            domnames = cfg.getDomConfigs()
            self.assertEquals(data[1], len(domnames),
                              "Expected %s dom names in %s, not %s" %
                              (data[1], n, len(domnames)))

            trigcfg = cfg.getTriggerConfig()
            self.assertEquals(data[2], trigcfg.basename(),
                              "Expected trigger config %s in %s, not %s" %
                              (data[2], n, trigcfg.basename()))

    def runListsSim5Test(self, newFormat):
        cfgDir = self.getConfigDir(newFormat=newFormat)
        cfg = DAQConfigParser.load("simpleConfig", cfgDir)

        expected = ['eventBuilder', 'globalTrigger', 'inIceTrigger',
                    'secondaryBuilders', 'stringHub#1001', 'stringHub#1002',
                    'stringHub#1003', 'stringHub#1004', 'stringHub#1005']

        comps = cfg.components()

        self.assertEqual(len(expected), len(comps),
                         "Expected %d components (%s), not %d (%s)" %
                         (len(expected), str(expected), len(comps),
                          str(comps)))

        for c in comps:
            try:
                expected.index(c.fullName())
            except:
                self.fail('Unexpected component "%s"' % c)

    def runLookupSim5Test(self, newFormat):
        cfgDir = self.getConfigDir(newFormat=newFormat)
        cfg = DAQConfigParser.load("simpleConfig", cfgDir)

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

    def runListsSpsIC40IT6Test(self, newFormat):
        cfgDir = self.getConfigDir(newFormat=newFormat)
        cfg = DAQConfigParser.load("sps-IC40-IT6-AM-Revert-IceTop-V029",
                                   cfgDir)

        expected = ['amandaTrigger', 'eventBuilder', 'globalTrigger',
                    'iceTopTrigger', 'inIceTrigger', 'secondaryBuilders',
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
                    'stringHub#77', 'stringHub#78']

        comps = cfg.components()

        self.assertEqual(len(expected), len(comps),
                         "Expected %d components (%s), not %d (%s)" %
                         (len(expected), str(expected), len(comps),
                          str(comps)))

        for c in comps:
            try:
                expected.index(c.fullName())
            except:
                self.fail('Unexpected component "%s"' % c)

    def runLookupSpsIC40IT6Test(self, newFormat):
        cfgDir = self.getConfigDir(newFormat=newFormat)
        cfg = DAQConfigParser.load("sps-IC40-IT6-AM-Revert-IceTop-V029",
                                   cfgDir)

        dataList = (
            ('737d355af587', 'Bat', 21, 1),
            ('499ccc773077', 'Werewolf', 66, 6),
            ('efc9607742b9', 'Big_Two_Card', 78, 60),
            ('1e5b72775d19', 'AMANDA_SYNC_DOM', 0, 91),
            ('1d165fc478ca', 'AMANDA_TRIG_DOM', 0, 92),
        )

        self.lookup(cfg, dataList)

    def runDumpDOMsTest(self, newFormat):
        cfgDir = self.getConfigDir(newFormat=newFormat)
        cfg = DAQConfigParser.load("sps-IC40-IT6-AM-Revert-IceTop-V029",
                                   cfgDir)

        for d in cfg.getAllDOMs():
            mbid = str(d)
            if len(mbid) != 12 or mbid.startswith(" "):
                self.fail("DOM %s(%s) has bad MBID" % (mbid, d.name()))
            n = 0
            if str(d).startswith("0"):
                n += 1
                nmid = cfg.getIDbyName(d.name())
                if nmid != mbid:
                    self.fail("Bad IDbyName value \"%s\" for \"%s\"" %
                              (nmid, mbid))

                newid = cfg.getIDbyStringPos(d.string(), d.pos())
                if newid.startswith(" ") or len(newid) != 12:
                    self.fail("Bad IDbyStringPos value \"%s\" for \"%s\" %d" %
                              (newid, mbid, n))

    def runReplayTest(self, newFormat):
        cfgDir = self.getConfigDir(newFormat=newFormat)
        cfg = DAQConfigParser.load("replay-ic22-it4", cfgDir)

        expected = ['eventBuilder', 'globalTrigger', 'iceTopTrigger',
                    'inIceTrigger',
                    'replayHub#21', 'replayHub#29', 'replayHub#30',
                    'replayHub#38', 'replayHub#39', 'replayHub#40',
                    'replayHub#46', 'replayHub#47', 'replayHub#48',
                    'replayHub#49', 'replayHub#50', 'replayHub#56',
                    'replayHub#57', 'replayHub#58', 'replayHub#59',
                    'replayHub#65', 'replayHub#66', 'replayHub#67',
                    'replayHub#72', 'replayHub#73', 'replayHub#74',
                    'replayHub#78', 'replayHub#201', 'replayHub#202',
                    'replayHub#203', 'replayHub#204']

        comps = cfg.components()

        self.assertEqual(len(expected), len(comps),
                         "Expected %d components (%s), not %d (%s)" %
                         (len(expected), str(expected), len(comps),
                          str(comps)))

        for c in comps:
            try:
                expected.index(c.fullName())
            except:
                self.fail('Unexpected component "%s"' % c)

class DAQNewConfigTest(CommonCode):
    def testNames(self):
        self.runNamesTest(True)

    def testListsSim5(self):
        self.runListsSim5Test(True)

    def testLookupSim5(self):
        self.runLookupSim5Test(True)

    def testListsSpsIC40IT6(self):
        self.runListsSpsIC40IT6Test(True)

    def testLookupSpsIC40IT6(self):
        self.runLookupSpsIC40IT6Test(True)

    def testDumpDOMs(self):
        self.runDumpDOMsTest(True)

    def testReplay(self):
        self.runReplayTest(True)


class DAQOldConfigTest(CommonCode):
    def testNames(self):
        self.runNamesTest(False)

    def testListsSim5(self):
        self.runListsSim5Test(False)

    def testLookupSim5(self):
        self.runLookupSim5Test(False)

    def testListsSpsIC40IT6(self):
        self.runListsSpsIC40IT6Test(False)

    def testLookupSpsIC40IT6(self):
        self.runLookupSpsIC40IT6Test(False)

    def testDumpDOMs(self):
        self.runDumpDOMsTest(False)

    def testReplay(self):
        self.runReplayTest(False)

class DAQConfigTest(CommonCode):
    def testCheckPeriod(self):
        cfgDir = self.getConfigDir()

        cfg = DAQConfigParser.load("sps-IC40-hitspool", cfgDir)

        expVal = 10
        self.assertEqual(expVal, cfg.monitorPeriod(),
                         "Expected monitor period for %s to be %d, not %s" %
                         (cfg.basename(), expVal, cfg.monitorPeriod()))

        expVal = 25
        self.assertEqual(expVal, cfg.watchdogPeriod(),
                         "Expected watchdog period for %s to be %d, not %s" %
                         (cfg.basename(), expVal, cfg.watchdogPeriod()))



if __name__ == '__main__':
    unittest.main()
