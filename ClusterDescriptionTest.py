#!/usr/bin/env python

from __future__ import print_function

import os
import tempfile
import unittest

from ClusterDescription import ClusterDescription, \
    ClusterDescriptionFormatError, XMLFormatError
from DAQMocks import MockClusterConfigFile, MockCluCfgFileComp


class TestClusterDescription(unittest.TestCase):
    CFGDIR = None
    DEBUG = False

    def __checkComp(self, h, c, mockComps):
        mock = None
        for m in mockComps:
            if c.name == m.name and c.num == m.num:
                mock = m
                break

        self.assertFalse(mock is None, "Cannot find component \"%s\"" %
                         c.name)
        self.assertEqual(mock.is_control_server, c.is_control_server,
                         "Expected %s ctlSrvr to be %s, not %s for %s<%s>" %
                         (mock.name, mock.is_control_server,
                          c.is_control_server, c, type(c)))
        self.assertEqual(mock.is_sim_hub, c.is_sim_hub,
                         "Expected %s simHub to be %s, not %s for %s<%s>" %
                         (mock.name, mock.is_sim_hub, c.is_sim_hub,
                          c, type(c)))
        self.assertEqual(mock.log_level, c.log_level,
                         "Expected %s log level \"%s\", not \"%s\""
                         " for %s<%s>" %
                         (mock.name, mock.log_level, c.log_level, c, type(c)))
        self.assertEqual(mock.required, c.required,
                         "Expected %s required to be %s, not %s for %s<%s>" %
                         (mock.name, mock.required, c.required, c, type(c)))
        if c.is_control_server:
            self.assertFalse(c.has_jvm_options,
                             "Expected no JVM options for %s<%s>" %
                             (c, type(c)))
        else:
            self.assertTrue(c.has_jvm_options,
                            "Expected JVM options for %s<%s>" %
                            (c, type(c)))
            self.assertEqual(mock.jvm_extra_args, c.jvm_extra_args,
                             "Expected %s JVM extra args \"%s\", not \"%s\""
                             " for %s<%s>" %
                             (mock.name, mock.jvm_extra_args, c.jvm_extra_args,
                              c, type(c)))
            self.assertEqual(mock.jvm_heap_init, c.jvm_heap_init, "Expected %s"
                             " JVM heapInit \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvm_heap_init, c.jvm_heap_init,
                              c, type(c)))
            self.assertEqual(mock.jvm_heap_max, c.jvm_heap_max, "Expected %s"
                             " JVM heapMax \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvm_heap_max, c.jvm_heap_max,
                              c, type(c)))
            self.assertEqual(mock.jvm_path, c.jvm_path, "Expected %s"
                             " JVM path \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvm_path, c.jvm_path, c, type(c)))
            self.assertEqual(mock.jvm_server, c.jvm_server, "Expected %s JVM"
                             " server \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvm_server, c.jvm_server, c,
                              type(c)))

    def setUp(self):
        if self.CFGDIR is None or not os.path.isdir(self.CFGDIR):
            self.CFGDIR = tempfile.mkdtemp()

    def tearDown(self):
        pass

    def testNoClusterEnd(self):
        name = "no-cluster-end"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "%s: no element found: line 2, column 0" % path
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNoHost(self):
        name = "no-host"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\"/>" % name, file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "No hosts defined for cluster \"%s\"" % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNamelessHost(self):
        name = "nameless-host"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host/>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiName(self):
        name = "multiname"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host><name>bar</name><name>bar2</name>", file=fd)
            print("    <jvm/>", file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "Multiple <name> nodes found"
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testEmptyNameNode(self):
        name = "empty-name-node"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host><name/>", file=fd)
            print("    <jvm/>", file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = '"%s" has <host> node without "name" attribute' % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiTextNode(self):
        name = "multitext"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host><name>a<x/>b</name>", file=fd)
            print("    <jvm/>", file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "Found multiple <name> text nodes"
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNoNameText(self):
        name = "no-name-text"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host><name><x/></name>", file=fd)
            print("    <jvm/>", file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNamelessComp(self):
        name = "nameless-comp"
        hname = "hostx"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host name=\"%s\">" % hname, file=fd)
            print("    <component/>", file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <component> node" +
                      " without \"name\" attribute") % (name, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNamelessDfltComp(self):
        name = "nameless-comp"
        hname = "hostx"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <default>", file=fd)
            print("    <component/>", file=fd)
            print("  </default>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" default section has <component> node" +
                      " without \"name\" attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testBadCompId(self):
        name = "bad-comp-id"
        hname = "hostx"
        cname = "foo"
        cid = "abc"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host name=\"%s\">" % hname, file=fd)
            print("    <component name=\"%s\" id=\"%s\"/>" % (cname, cid), file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" component \"%s\" has" +
                      " bad ID \"%s\"") % (name, hname, cname, cid)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testNoSimPrio(self):
        name = "no-sim-id"
        hname = "hostx"
        snum = 1

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host name=\"%s\">" % hname, file=fd)
            print("    <simulatedHub number=\"%s\"/>" % snum, file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " without \"priority\" attribute") % (name, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testBadSimId(self):
        name = "bad-sim-id"
        hname = "hostx"
        snum = "abc"
        sprio = 1

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host name=\"%s\">" % hname, file=fd)
            print("    <simulatedHub number=\"%s\" priority=\"%s\"/>" % \
                (snum, sprio), file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " with bad number \"%s\"") % (name, hname, snum)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testBadSimPrio(self):
        name = "bad-sim-prio"
        hname = "hostx"
        snum = 1
        sprio = "abc"

        path = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(path, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host name=\"%s\">" % hname, file=fd)
            print("    <simulatedHub number=\"%s\" priority=\"%s\"/>" % \
                (snum, sprio), file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " with bad priority \"%s\"") % (name, hname, sprio)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testEmpty(self):
        name = "empty"

        mock = MockClusterConfigFile(self.CFGDIR, name)

        mock.create()

        try:
            cd = ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "No hosts defined for cluster \"%s\"" % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testDefaults(self):
        name = "dflts"

        data_dir = "/daq/data"
        log_dir = "/daq/log"
        spade_dir = "/daq/spade"

        mock = MockClusterConfigFile(self.CFGDIR, name)
        mock.setDataDir(data_dir)
        mock.setLogDir(log_dir)
        mock.setSpadeDir(spade_dir)

        hs_dir = "xxxDir"
        hs_interval = 12.0
        hs_max_files = 111

        jvm_path = "xxxjvm"
        jvm_args = "jvmArgs"
        jvm_heap_init = "2g"
        jvm_heap_max = "8g"
        jvm_server = False
        jvm_extra_args = "xxxArgs"

        log_level = "logLvl"

        mock.set_default_hs_directory(hs_dir)
        mock.set_default_hs_interval(hs_interval)
        mock.set_default_hs_max_files(hs_max_files)
        mock.set_default_jvm_args(jvm_args)
        mock.set_default_jvm_extra_args(jvm_extra_args)
        mock.set_default_jvm_heap_init(jvm_heap_init)
        mock.set_default_jvm_heap_max(jvm_heap_max)
        mock.set_default_jvm_path(jvm_path)
        mock.set_default_jvm_server(jvm_server)
        mock.setDefaultLogLevel(log_level)

        acomp = MockCluCfgFileComp("foo", 1, hitspool_directory="hsDir",
                                   hitspool_interval=21.0,
                                   hitspool_max_files=10,
                                   jvm_path="abc", jvm_heap_init="1g",
                                   jvm_heap_max="3g", jvm_server=True,
                                   jvm_args="def", jvm_extra_args="ghi",
                                   log_level="xyz")
        mock.addDefaultComponent(acomp)

        bcomp = MockCluCfgFileComp("bar")
        mock.addDefaultComponent(bcomp)

        h = mock.addHost("host1")
        foo = h.add_component("foo", required=True)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print(":: ", line, end=' ')

        cd = ClusterDescription(self.CFGDIR, name)

        if self.DEBUG:
            cd.dump()

        self.assertEqual(name + "-cluster", cd.config_name,
                         "Expected cfgname \"%s-cluster\", not \"%s\"" %
                         (name, cd.config_name))

        self.assertEqual(mock.data_dir, cd.daq_data_dir,
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.data_dir, cd.daq_data_dir))
        self.assertEqual(mock.log_dir, cd.daq_log_dir,
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.log_dir, cd.daq_log_dir))
        self.assertEqual(mock.spade_dir, cd.log_dir_for_spade,
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spade_dir, cd.log_dir_for_spade))

        self.assertEqual(mock.default_jvm_args(), cd.default_jvm_args(),
                         "Expected default JVMArgs \"%s\", not \"%s\"" %
                         (mock.default_jvm_args(), cd.default_jvm_args()))
        self.assertEqual(mock.default_jvm_extra_args(),
                         cd.default_jvm_extra_args(),
                         "Expected default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (mock.default_jvm_extra_args(),
                          cd.default_jvm_extra_args()))
        self.assertEqual(mock.default_jvm_heap_init(), cd.default_jvm_heap_init(),
                         "Expected default JVMHeapInit \"%s\", not \"%s\"" %
                         (mock.default_jvm_heap_init(),
                          cd.default_jvm_heap_init()))
        self.assertEqual(mock.default_jvm_heap_max(), cd.default_jvm_heap_max(),
                         "Expected default JVMHeapMax \"%s\", not \"%s\"" %
                         (mock.default_jvm_heap_max(), cd.default_jvm_heap_max()))
        self.assertEqual(mock.default_jvm_path(), cd.default_jvm_path(),
                         "Expected default JVMPath \"%s\", not \"%s\"" %
                         (mock.default_jvm_path(), cd.default_jvm_path()))
        self.assertEqual(mock.default_jvm_server(), cd.default_jvm_server(),
                         "Expected default JVMServer \"%s\", not \"%s\"" %
                         (mock.default_jvm_server(), cd.default_jvm_server()))
        self.assertEqual(mock.default_log_level, cd.default_log_level(),
                         "Expected default LogLevel \"%s\", not \"%s\"" %
                         (mock.default_log_level, cd.default_log_level()))

        self.assertEqual(acomp.jvm_args, cd.default_jvm_args(acomp.name),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvm_args,
                          cd.default_jvm_args(acomp.name)))
        self.assertEqual(acomp.jvm_extra_args,
                         cd.default_jvm_extra_args(acomp.name),
                         "Expected %s default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvm_extra_args,
                          cd.default_jvm_extra_args(acomp.name)))
        self.assertEqual(acomp.jvm_heap_init,
                         cd.default_jvm_heap_init(acomp.name),
                         "Expected %s default JVMHeapInit \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvm_heap_init,
                          cd.default_jvm_heap_init(acomp.name)))
        self.assertEqual(acomp.jvm_heap_max,
                         cd.default_jvm_heap_max(acomp.name),
                         "Expected %s default JVMHeapMax \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvm_heap_max,
                          cd.default_jvm_heap_max(acomp.name)))
        self.assertEqual(acomp.jvm_path, cd.default_jvm_path(acomp.name),
                         "Expected %s default JVMPath \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvm_path,
                          cd.default_jvm_path(acomp.name)))
        self.assertEqual(acomp.jvm_server,
                         cd.default_jvm_server(acomp.name),
                         "Expected %s default JVMServer \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvm_server,
                          cd.default_jvm_server(acomp.name)))
        self.assertEqual(acomp.log_level, cd.default_log_level(acomp.name),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (acomp.name, acomp.log_level,
                          cd.default_log_level(acomp.name)))

        self.assertEqual(mock.default_jvm_args(),
                         cd.default_jvm_args(bcomp.name),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_jvm_args(),
                          cd.default_jvm_args(bcomp.name)))
        self.assertEqual(mock.default_jvm_extra_args(),
                         cd.default_jvm_extra_args(bcomp.name),
                         "Expected %s default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.default_jvm_extra_args(),
                          cd.default_jvm_extra_args(bcomp.name)))
        self.assertEqual(mock.default_jvm_heap_init(),
                         cd.default_jvm_heap_init(bcomp.name),
                         "Expected %s default JVM HeapInit \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.default_jvm_heap_init(),
                          cd.default_jvm_heap_init(bcomp.name)))
        self.assertEqual(mock.default_jvm_heap_max(),
                         cd.default_jvm_heap_max(bcomp.name),
                         "Expected %s default JVM HeapMax \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.default_jvm_heap_max(),
                          cd.default_jvm_heap_max(bcomp.name)))
        self.assertEqual(mock.default_jvm_path(),
                         cd.default_jvm_path(bcomp.name),
                         "Expected %s default JVMPath \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_jvm_path(),
                          cd.default_jvm_path(bcomp.name)))
        self.assertEqual(mock.default_jvm_server(),
                         cd.default_jvm_server(bcomp.name),
                         "Expected %s default JVMServer \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_jvm_server(),
                          cd.default_jvm_server(bcomp.name)))
        self.assertEqual(mock.default_log_level,
                         cd.default_log_level(bcomp.name),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_log_level,
                          cd.default_log_level(bcomp.name)))

    def testDefaultInheritance(self):
        name = "compdflts"

        data_dir = "/daq/data"
        log_dir = "/daq/log"
        spade_dir = "/daq/spade"

        dfltHSDir = "xxxHSDir"
        dfltInterval = 99.0
        dfltMaxFiles = 99

        dfltPath = "xxxjvm"
        dfltHeapInit = "2g"
        dfltHeapMax = "8g"
        dfltServer = False
        dfltArgs = "jvmArgs"
        dfltExtra = "jvmExtra"

        dfltLogLvl = "logLvl"

        numFields = 10

        (FLD_PATH, FLD_HEAP_INIT, FLD_HEAP_MAX, FLD_SERVER, FLD_JVMARGS,
         FLD_EXTRAARGS, FLD_LOGLVL, FLD_HSDIR, FLD_HSIVAL, FLD_HSMAX) \
         = list(range(numFields))

        for i in range(numFields):
            if self.DEBUG:
                print("########## I %d" % i)

            # create a cluster config file
            mock = MockClusterConfigFile(self.CFGDIR, name)
            mock.setDataDir(data_dir)
            mock.setLogDir(log_dir)
            mock.setSpadeDir(spade_dir)

            # set hitspool defaults
            mock.set_default_hs_directory(dfltHSDir)
            mock.set_default_hs_interval(dfltInterval)
            mock.set_default_hs_max_files(dfltMaxFiles)

            # set JVM defaults
            mock.set_default_jvm_args(dfltArgs)
            mock.set_default_jvm_extra_args(dfltExtra)
            mock.set_default_jvm_heap_init(dfltHeapInit)
            mock.set_default_jvm_heap_max(dfltHeapMax)
            mock.set_default_jvm_path(dfltPath)
            mock.set_default_jvm_server(dfltServer)

            # set log level defaults
            mock.setDefaultLogLevel(dfltLogLvl)

            # add host
            hostname = "someHost"
            h = mock.addHost(hostname)

            # temporary values will be used to set up
            # component-specific default values
            (tmpHsDir, tmpIval, tmpMaxF, tmpPath, tmpHInit, tmpHMax,
             tmpServer, tmpArgs, tmpExtra, tmpLogLvl) = \
                (None, ) * numFields

            # set component-level defaults
            plainName = "foo"
            if i == FLD_PATH:
                plainPath = "plainPath"
                tmpPath = plainPath
            else:
                plainPath = dfltPath
            if i == FLD_HEAP_INIT:
                plainHeapInit = "1g"
                tmpHInit = plainHeapInit
            else:
                plainHeapInit = dfltHeapInit
            if i == FLD_HEAP_MAX:
                plainHeapMax = "3g"
                tmpHMax = plainHeapMax
            else:
                plainHeapMax = dfltHeapMax
            if i == FLD_SERVER:
                plainServer = not dfltServer
                tmpServer = plainServer
            else:
                plainServer = dfltServer is True
            if i == FLD_JVMARGS:
                plainArgs = "plainArgs"
                tmpArgs = plainArgs
            else:
                plainArgs = dfltArgs
            if i == FLD_EXTRAARGS:
                plainExtra = "plainExtra"
                tmpExtra = plainExtra
            else:
                plainExtra = dfltExtra
            if i == FLD_LOGLVL:
                plainLogLvl = "plainLvl"
                tmpLogLvl = plainLogLvl
            else:
                plainLogLvl = dfltLogLvl
            if i == FLD_HSDIR:
                plainHSDir = "plainDir"
                tmpHsDir = plainHSDir
            else:
                plainHSDir = dfltHSDir
            if i == FLD_HSIVAL:
                plainIval = dfltInterval + 1.1
                tmpIval = plainIval
            else:
                plainIval = dfltInterval
            if i == FLD_HSMAX:
                plainMaxF = dfltMaxFiles + 1
                tmpMaxF = plainMaxF
            else:
                plainMaxF = dfltMaxFiles

            # add component-specific default (only one value will be active)
            acomp = MockCluCfgFileComp(plainName, 0,
                                       hitspool_directory=tmpHsDir,
                                       hitspool_interval=tmpIval,
                                       hitspool_max_files=tmpMaxF,
                                       jvm_path=tmpPath,
                                       jvm_heap_init=tmpHInit,
                                       jvm_heap_max=tmpHMax,
                                       jvm_server=tmpServer,
                                       jvm_args=tmpArgs,
                                       jvm_extra_args=tmpExtra,
                                       log_level=tmpLogLvl)
            mock.addDefaultComponent(acomp)

            # add unaltered component
            foo = h.add_component(plainName, required=True)

            # add a component which will override a single value
            instName = "bar"
            bar = h.add_component(instName, required=True)

            j = (i + 1) % numFields
            if self.DEBUG:
                print("########## J %d" % j)

            if j == FLD_PATH:
                instPath = "instPath"
                bar.set_jvm_path(instPath)
            else:
                instPath = dfltPath
            if j == FLD_HEAP_INIT:
                instHeapInit = "instInit"
                bar.set_jvm_heap_init(instHeapInit)
            else:
                instHeapInit = dfltHeapInit
            if j == FLD_HEAP_MAX:
                instHeapMax = "instMax"
                bar.set_jvm_heap_max(instHeapMax)
            else:
                instHeapMax = dfltHeapMax
            if j == FLD_SERVER:
                instServer = not dfltServer
                bar.set_jvm_server(instServer)
            else:
                instServer = dfltServer is True
            if j == FLD_JVMARGS:
                instArgs = "instArgs"
                bar.set_jvm_args(instArgs)
            else:
                instArgs = dfltArgs
            if j == FLD_EXTRAARGS:
                instExtra = "instExtra"
                bar.set_jvm_extra_args(instExtra)
            else:
                instExtra = dfltExtra
            if j == FLD_LOGLVL:
                instLogLvl = "instLvl"
                bar.set_log_level(instLogLvl)
            else:
                instLogLvl = dfltLogLvl
            if j == FLD_HSDIR:
                instHSDir = "instHSDir"
                bar.setHitspoolDirectory(instHSDir)
            else:
                instHSDir = dfltHSDir
            if j == FLD_HSIVAL:
                instIval = dfltInterval + 2.2
                bar.setHitspoolInterval(instIval)
            else:
                instIval = dfltInterval
            if j == FLD_HSMAX:
                instMaxF = dfltMaxFiles + 2
                bar.setHitspoolMaxFiles(instMaxF)
            else:
                instMaxF = dfltMaxFiles

            # create file
            mock.create()

            if self.DEBUG:
                with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                    print(":::::::::: %s-cluster.cfg" % name)
                    for line in fd:
                        print(":: ", line, end=' ')

            cd = ClusterDescription(self.CFGDIR, name)

            if self.DEBUG:
                cd.dump()

            self.assertEqual(name + "-cluster", cd.config_name,
                             "Expected cfgname \"%s-cluster\", not \"%s\"" %
                             (name, cd.config_name))

            self.assertEqual(data_dir, cd.daq_data_dir,
                             "Expected data dir \"%s\", not \"%s\"" %
                             (data_dir, cd.daq_data_dir))
            self.assertEqual(log_dir, cd.daq_log_dir,
                             "Expected log dir \"%s\", not \"%s\"" %
                             (log_dir, cd.daq_log_dir))
            self.assertEqual(spade_dir, cd.log_dir_for_spade,
                             "Expected SPADE dir \"%s\", not \"%s\"" %
                             (spade_dir, cd.log_dir_for_spade))

            self.assertEqual(dfltHSDir, cd.default_hs_directory(),
                             "Expected default HS directory \"%s\","
                             " not \"%s\"" %
                             (dfltHSDir, cd.default_hs_directory()))
            self.assertEqual(dfltInterval, cd.default_hs_interval(),
                             "Expected default HS interval \"%s\","
                             " not \"%s\"" %
                             (dfltInterval, cd.default_hs_interval()))
            self.assertEqual(dfltMaxFiles, cd.default_hs_max_files(),
                             "Expected default HS maximum files \"%s\","
                             " not \"%s\"" %
                             (dfltMaxFiles, cd.default_hs_max_files()))

            self.assertEqual(dfltArgs, cd.default_jvm_args(),
                             "Expected default JVMArgs \"%s\", not \"%s\"" %
                             (dfltArgs, cd.default_jvm_args()))
            self.assertEqual(dfltExtra, cd.default_jvm_extra_args(),
                             "Expected default JVMExtraArgs \"%s\","
                             " not \"%s\"" %
                             (dfltExtra, cd.default_jvm_extra_args()))
            self.assertEqual(dfltHeapInit, cd.default_jvm_heap_init(),
                             "Expected default JVMHeapInit \"%s\","
                             " not \"%s\"" %
                             (dfltHeapInit, cd.default_jvm_heap_init()))
            self.assertEqual(dfltHeapMax, cd.default_jvm_heap_max(),
                             "Expected default JVMHeapMax \"%s\", not \"%s\"" %
                             (dfltHeapMax, cd.default_jvm_heap_max()))
            self.assertEqual(dfltPath, cd.default_jvm_path(),
                             "Expected default JVMPath \"%s\", not \"%s\"" %
                             (dfltPath, cd.default_jvm_path()))
            self.assertEqual(dfltServer, cd.default_jvm_server(),
                             "Expected default JVMServer \"%s\", not \"%s\"" %
                             (dfltServer, cd.default_jvm_server()))

            self.assertEqual(dfltLogLvl, cd.default_log_level(),
                             "Expected default LogLevel \"%s\", not \"%s\"" %
                             (dfltLogLvl, cd.default_log_level()))

            for comp in cd.host(hostname).components:
                if comp.name == plainName:
                    (hs_dir, hsIval, hs_max_f, args, extra, heap_init,
                     heap_max, path, server, log_level) \
                     = (plainHSDir, plainIval, plainMaxF, plainArgs,
                        plainExtra, plainHeapInit, plainHeapMax, plainPath,
                        plainServer, plainLogLvl)
                else:
                     (hs_dir, hsIval, hs_max_f, args, extra, heap_init,
                      heap_max, path, server, log_level) \
                     = (instHSDir, instIval, instMaxF, instArgs, instExtra,
                        instHeapInit, instHeapMax, instPath, instServer,
                        instLogLvl)

                has_jvm_options = args is not None and \
                                extra is not None and \
                                heap_init is not None and \
                                heap_max is not None and \
                                path is not None

                self.assertEqual(has_jvm_options, comp.has_jvm_options,
                                 "Expected %s<%s> hasJVMOptions %s, not %s" %
                                 (comp.name, type(comp), has_jvm_options,
                                  comp.has_jvm_options))
                if comp.has_jvm_options:
                    self.assertEqual(args, comp.jvm_args,
                                     "Expected %s<%s> JVMArgs \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), args,
                                      comp.jvm_args))
                    self.assertEqual(extra, comp.jvm_extra_args,
                                     "Expected %s<%s> JVMExtra \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), extra,
                                      comp.jvm_extra_args))
                    self.assertEqual(heap_init, comp.jvm_heap_init,
                                     "Expected %s<%s> JVMHeapInit \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), heap_init,
                                      comp.jvm_heap_init))
                    self.assertEqual(heap_max, comp.jvm_heap_max,
                                     "Expected %s<%s> JVMHeapMax \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), heap_max,
                                      comp.jvm_heap_max))
                    self.assertEqual(path, comp.jvm_path, "Expected %s<%s>"
                                     " JVMPath \"%s\", not \"%s\"" %
                                     (comp.name, type(comp), path,
                                      comp.jvm_path))
                    self.assertEqual(server, comp.jvm_server, "Expected %s<%s>"
                                     " JVMServer \"%s\", not \"%s\"" %
                                     (comp.name, type(comp), server,
                                      comp.jvm_server))
                    self.assertEqual(log_level, comp.log_level,
                                     "Expected %s<%s> LogLevel \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), log_level,
                                      comp.log_level))

                if comp.is_real_hub:
                    self.assertEqual(hs_dir, comp.hitspool_directory,
                                     "Expected %s<%s> HS directory \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hs_dir,
                                      comp.hitspool_directory))
                    self.assertEqual(hsIval, comp.hitspool_interval,
                                     "Expected %s<%s> HS interval \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hsIval,
                                      comp.hitspool_interval))
                    self.assertEqual(hs_max_f, comp.hitspool_max_files,
                                     "Expected %s<%s> HS max files \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hs_max_f,
                                      comp.hitspool_max_files))

    def testComponents(self):
        name = "comps"

        data_dir = "/daq/data"
        log_dir = "/daq/log"
        spade_dir = "/daq/spade"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        mock.setDataDir(data_dir)
        mock.setLogDir(log_dir)
        mock.setSpadeDir(spade_dir)

        h1 = mock.addHost("host1")
        mockComps.append(h1.addControlServer())

        foo = h1.add_component("foo", required=True)
        foo.set_jvm_path("newJVM")
        foo.set_jvm_args("newArgs")
        foo.set_jvm_extra_args("newExtra")
        foo.set_jvm_heap_init("newInit")
        foo.set_jvm_heap_max("newMax")
        foo.set_jvm_server(False)
        foo.set_log_level("logLvl")
        mockComps.append(foo)

        bar = h1.add_component("bar", 123)
        mockComps.append(bar)

        numSim = 15
        prioSim = 2

        sim = h1.addSimHubs(numSim, prioSim, if_unused=True)
        mockComps.append(sim)

        h2 = mock.addHost("host2")
        sim = h2.addSimHubs(numSim, prioSim)
        mockComps.append(sim)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print(":: ", line, end=' ')

        cd = ClusterDescription(self.CFGDIR, name)

        if self.DEBUG:
            cd.dump()

        self.assertEqual(mock.data_dir, cd.daq_data_dir,
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.data_dir, cd.daq_data_dir))
        self.assertEqual(mock.log_dir, cd.daq_log_dir,
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.log_dir, cd.daq_log_dir))
        self.assertEqual(mock.spade_dir, cd.log_dir_for_spade,
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spade_dir, cd.log_dir_for_spade))

        for h, c in cd.host_component_pairs:
            self.__checkComp(h, c, mockComps)
        for h, c in cd.host_sim_hub_pairs:
            self.__checkComp(h, c, mockComps)
            self.assertEqual(numSim, c.number,
                             "Expected simHub number %s, not %s" %
                             (numSim, c.number))
            self.assertEqual(prioSim, c.priority,
                             "Expected simHub priority %s, not %s" %
                             (prioSim, c.priority))

    def testDupComponents(self):
        name = "dupcomps"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        host = mock.addHost("host1")
        comp = host.add_component("foo")
        host.add_component("foo")

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print(":: ", line, end=' ')

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = ("Multiple entries for component \"%s\""
                      " in host \"%s\"") % (comp.name, host.name)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiHostComponents(self):
        name = "multihost-comps"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        h1 = mock.addHost("host1")
        c1 = h1.add_component("foo")

        h2 = mock.addHost("host2")
        c2 = h2.add_component("foo")

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print(":: ", line, end=' ')

        try:
            ClusterDescription(self.CFGDIR, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "Multiple entries for component \"%s\"" % \
                     c1.name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMergedHostEntries(self):
        name = "merged-hosts"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        h1 = mock.addHost("host1")
        c1 = h1.add_component("foo")

        h2 = mock.addHost("host2")
        c2 = h2.add_component("bar")

        h2 = mock.addHost("host1")
        c2 = h2.add_component("ney")

        mock.create(split_hosts=True)

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print(":: ", line, end=' ')

        cdesc = ClusterDescription(self.CFGDIR, name)

        mockdict = mock.hosts
        for name, comp in cdesc.host_component_pairs:
            if name not in mockdict:
                self.fail("Cannot find host \"%s\" in cluster description" %
                          (name, ))
            found = False
            for mcomp in mockdict[name].components:
                if comp.name == mcomp.name and comp.num == mcomp.num:
                    found = True
                    break
            if not found:
                self.fail("Cannot find host \"%s\" component \"%s\""
                          " in cluster description" % (name, comp))

    def testDupSimHubs(self):
        """duplicate simHub lines at different priorities are allowed"""
        name = "dupsim"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        host = mock.addHost("host1")
        sim = host.addSimHubs(15, 2, if_unused=True)
        host.addSimHubs(10, 1)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print(":: ", line, end=' ')

        ClusterDescription(self.CFGDIR, name)

    def testAddDupPrio(self):
        """duplicate simHub lines at the same priority are not valid"""
        name = "dupprio"

        mockComps = []
        mock = MockClusterConfigFile(self.CFGDIR, name)

        hname = "host1"
        host = mock.addHost(hname)

        prio = 2
        sim = host.addSimHubs(15, prio, if_unused=True)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.CFGDIR, name)) as fd:
                for line in fd:
                    print(":: ", line, end=' ')

        cd = ClusterDescription(self.CFGDIR, name)
        h = cd.host(hname)
        try:
            h.add_simulated_hub(7, prio, False)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "Multiple <simulatedHub> nodes at prio %d for %s" % \
                     (prio, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def testMultiJVM(self):
        name = "multiJVM"

        hostname = "foo"
        compName = "fooComp"
        args = None
        extra = None
        heap_init = "2g"
        heap_max = "4g"
        path = None
        server = False

        cluPath = os.path.join(self.CFGDIR, name + "-cluster.cfg")
        with open(cluPath, "w") as fd:
            print("<cluster name=\"%s\">" % name, file=fd)
            print("  <host name=\"%s\">" % hostname, file=fd)
            print("    <component name=\"%s\">" % compName, file=fd)
            print("      <jvm heapInit=\"xxx\"/>", file=fd)
            print("      <jvm heapInit=\"%s\"/>" % heap_init, file=fd)
            print("      <jvm heapMax=\"%s\"/>" % heap_max, file=fd)
            print("    </component>", file=fd)
            print("  </host>", file=fd)
            print("</cluster>", file=fd)

        cd = ClusterDescription(self.CFGDIR, name)

        for comp in cd.host(hostname).components:
            self.assertEqual(args, comp.jvm_args,
                             "Expected %s JVMArgs \"%s\", not \"%s\"" %
                             (comp.name, args, comp.jvm_args))
            self.assertEqual(extra, comp.jvm_extra_args,
                             "Expected %s JVMExtra \"%s\", not \"%s\"" %
                             (comp.name, extra, comp.jvm_extra_args))
            self.assertEqual(heap_init, comp.jvm_heap_init,
                             "Expected %s JVMHeapInit \"%s\", not \"%s\"" %
                             (comp.name, heap_init, comp.jvm_heap_init))
            self.assertEqual(heap_max, comp.jvm_heap_max,
                             "Expected %s JVMHeapMax \"%s\", not \"%s\"" %
                             (comp.name, heap_max, comp.jvm_heap_max))
            self.assertEqual(path, comp.jvm_path,
                             "Expected %s JVMPath \"%s\", not \"%s\"" %
                             (comp.name, path, comp.jvm_path))
            self.assertEqual(server, comp.jvm_server,
                             "Expected %s JVMServer \"%s\", not \"%s\"" %
                             (comp.name, server, comp.jvm_server))


if __name__ == '__main__':
    unittest.main()
