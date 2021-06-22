#!/usr/bin/env python

from __future__ import print_function

import os
import tempfile
import unittest

from ClusterDescription import ClusterDescription, \
    ClusterDescriptionFormatError, XMLFormatError
from DAQMocks import MockClusterConfigFile, MockCluCfgFileComp


class TestClusterDescription(unittest.TestCase):
    cfgdir = None
    DEBUG = False

    def __check_comp(self, comp, mock_comps):
        mock = None
        for mcmp in mock_comps:
            if comp.name == mcmp.name and comp.num == mcmp.num:
                mock = mcmp
                break

        self.assertFalse(mock is None, "Cannot find component \"%s\"" %
                         comp.name)
        self.assertEqual(mock.is_control_server, comp.is_control_server,
                         "Expected %s ctlSrvr to be %s, not %s for %s<%s>" %
                         (mock.name, mock.is_control_server,
                          comp.is_control_server, comp, type(comp)))
        self.assertEqual(mock.is_sim_hub, comp.is_sim_hub,
                         "Expected %s simHub to be %s, not %s for %s<%s>" %
                         (mock.name, mock.is_sim_hub, comp.is_sim_hub,
                          comp, type(comp)))
        self.assertEqual(mock.log_level, comp.log_level,
                         "Expected %s log level \"%s\", not \"%s\""
                         " for %s<%s>" %
                         (mock.name, mock.log_level, comp.log_level,
                          comp, type(comp)))
        self.assertEqual(mock.required, comp.required,
                         "Expected %s required to be %s, not %s for %s<%s>" %
                         (mock.name, mock.required, comp.required,
                          comp, type(comp)))
        if comp.is_control_server:
            self.assertFalse(comp.has_jvm_options,
                             "Expected no JVM options for %s<%s>" %
                             (comp, type(comp)))
        else:
            self.assertTrue(comp.has_jvm_options,
                            "Expected JVM options for %s<%s>" %
                            (comp, type(comp)))
            self.assertEqual(mock.jvm_extra_args, comp.jvm_extra_args,
                             "Expected %s JVM extra args \"%s\", not \"%s\""
                             " for %s<%s>" %
                             (mock.name, mock.jvm_extra_args,
                              comp.jvm_extra_args, comp, type(comp)))
            self.assertEqual(mock.jvm_heap_init, comp.jvm_heap_init,
                             "Expected %s JVM heapInit \"%s\", not \"%s\""
                             " for %s<%s>" %
                             (mock.name, mock.jvm_heap_init,
                              comp.jvm_heap_init, comp, type(comp)))
            self.assertEqual(mock.jvm_heap_max, comp.jvm_heap_max,
                             "Expected %s JVM heapMax \"%s\", not \"%s\""
                             " for %s<%s>" %
                             (mock.name, mock.jvm_heap_max, comp.jvm_heap_max,
                              comp, type(comp)))
            self.assertEqual(mock.jvm_path, comp.jvm_path, "Expected %s"
                             " JVM path \"%s\", not \"%s\" for %s<%s>" %
                             (mock.name, mock.jvm_path, comp.jvm_path,
                              comp, type(comp)))
            self.assertEqual(mock.jvm_server, comp.jvm_server,
                             "Expected %s JVM server \"%s\", not \"%s\""
                             " for %s<%s>" %
                             (mock.name, mock.jvm_server, comp.jvm_server,
                              comp, type(comp)))

    def setUp(self):
        if self.cfgdir is None or not os.path.isdir(self.cfgdir):
            self.cfgdir = tempfile.mkdtemp()

    def tearDown(self):
        pass

    def test_no_cluster_end(self):
        name = "no-cluster-end"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "%s: no element found: line 2, column 0" % path
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_no_host(self):
        name = "no-host"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\"/>" % name, file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "No hosts defined for cluster \"%s\"" % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_nameless_host(self):
        name = "nameless-host"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host/>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_multi_name(self):
        name = "multiname"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host><name>bar</name><name>bar2</name>", file=out)
            print("    <jvm/>", file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "Multiple <name> nodes found"
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_empty_name_node(self):
        name = "empty-name-node"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host><name/>", file=out)
            print("    <jvm/>", file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = '"%s" has <host> node without "name" attribute' % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_multi_text_node(self):
        name = "multitext"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host><name>a<x/>b</name>", file=out)
            print("    <jvm/>", file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = "Found multiple <name> text nodes"
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_no_name_text(self):
        name = "no-name-text"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host><name><x/></name>", file=out)
            print("    <jvm/>", file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" has <host> node without \"name\"" +
                      " attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_nameless_comp(self):
        name = "nameless-comp"
        hname = "hostx"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host name=\"%s\">" % hname, file=out)
            print("    <component/>", file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <component> node" +
                      " without \"name\" attribute") % (name, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_nameless_dflt_comp(self):
        name = "nameless-comp"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <default>", file=out)
            print("    <component/>", file=out)
            print("  </default>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" default section has <component> node" +
                      " without \"name\" attribute") % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_bad_comp_id(self):
        name = "bad-comp-id"
        hname = "hostx"
        cname = "foo"
        cid = "abc"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host name=\"%s\">" % hname, file=out)
            print("    <component name=\"%s\" id=\"%s\"/>" % (cname, cid),
                  file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" component \"%s\" has" +
                      " bad ID \"%s\"") % (name, hname, cname, cid)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_no_sim_prio(self):
        name = "no-sim-id"
        hname = "hostx"
        snum = 1

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host name=\"%s\">" % hname, file=out)
            print("    <simulatedHub number=\"%s\"/>" % snum, file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " without \"priority\" attribute") % (name, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_bad_sim_id(self):
        name = "bad-sim-id"
        hname = "hostx"
        snum = "abc"
        sprio = 1

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host name=\"%s\">" % hname, file=out)
            print("    <simulatedHub number=\"%s\" priority=\"%s\"/>" %
                  (snum, sprio), file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " with bad number \"%s\"") % (name, hname, snum)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_bad_sim_prio(self):
        name = "bad-sim-prio"
        hname = "hostx"
        snum = 1
        sprio = "abc"

        path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host name=\"%s\">" % hname, file=out)
            print("    <simulatedHub number=\"%s\" priority=\"%s\"/>" %
                  (snum, sprio), file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except XMLFormatError as fmterr:
            errmsg = ("Cluster \"%s\" host \"%s\" has <simulatedHub> node" +
                      " with bad priority \"%s\"") % (name, hname, sprio)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_empty(self):
        name = "empty"

        mock = MockClusterConfigFile(self.cfgdir, name)

        mock.create()

        try:
            _ = ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "No hosts defined for cluster \"%s\"" % name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_defaults(self):
        name = "dflts"

        data_dir = "/daq/data"
        log_dir = "/daq/log"
        spade_dir = "/daq/spade"

        mock = MockClusterConfigFile(self.cfgdir, name)
        mock.set_data_dir(data_dir)
        mock.set_log_dir(log_dir)
        mock.set_spade_dir(spade_dir)

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
        mock.set_default_log_level(log_level)

        acomp = MockCluCfgFileComp("foo", 1, hitspool_directory="hsDir",
                                   hitspool_interval=21.0,
                                   hitspool_max_files=10,
                                   jvm_path="abc", jvm_heap_init="1g",
                                   jvm_heap_max="3g", jvm_server=True,
                                   jvm_args="def", jvm_extra_args="ghi",
                                   log_level="xyz")
        mock.add_default_component(acomp)

        bcomp = MockCluCfgFileComp("bar")
        mock.add_default_component(bcomp)

        host = mock.add_host("host1")
        _ = host.add_component("foo", required=True)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                for line in out:
                    print(":: ", line, end=' ')

        cdesc = ClusterDescription(self.cfgdir, name)

        if self.DEBUG:
            cdesc.dump()

        self.assertEqual(name + "-cluster", cdesc.config_name,
                         "Expected cfgname \"%s-cluster\", not \"%s\"" %
                         (name, cdesc.config_name))

        self.assertEqual(mock.data_dir, cdesc.daq_data_dir,
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.data_dir, cdesc.daq_data_dir))
        self.assertEqual(mock.log_dir, cdesc.daq_log_dir,
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.log_dir, cdesc.daq_log_dir))
        self.assertEqual(mock.spade_dir, cdesc.log_dir_for_spade,
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spade_dir, cdesc.log_dir_for_spade))

        self.assertEqual(mock.default_jvm_args(), cdesc.default_jvm_args(),
                         "Expected default JVMArgs \"%s\", not \"%s\"" %
                         (mock.default_jvm_args(), cdesc.default_jvm_args()))
        self.assertEqual(mock.default_jvm_extra_args(),
                         cdesc.default_jvm_extra_args(),
                         "Expected default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (mock.default_jvm_extra_args(),
                          cdesc.default_jvm_extra_args()))
        self.assertEqual(mock.default_jvm_heap_init(),
                         cdesc.default_jvm_heap_init(),
                         "Expected default JVMHeapInit \"%s\", not \"%s\"" %
                         (mock.default_jvm_heap_init(),
                          cdesc.default_jvm_heap_init()))
        self.assertEqual(mock.default_jvm_heap_max(),
                         cdesc.default_jvm_heap_max(),
                         "Expected default JVMHeapMax \"%s\", not \"%s\"" %
                         (mock.default_jvm_heap_max(),
                          cdesc.default_jvm_heap_max()))
        self.assertEqual(mock.default_jvm_path(), cdesc.default_jvm_path(),
                         "Expected default JVMPath \"%s\", not \"%s\"" %
                         (mock.default_jvm_path(), cdesc.default_jvm_path()))
        self.assertEqual(mock.default_jvm_server(), cdesc.default_jvm_server(),
                         "Expected default JVMServer \"%s\", not \"%s\"" %
                         (mock.default_jvm_server(),
                          cdesc.default_jvm_server()))
        self.assertEqual(mock.default_log_level(), cdesc.default_log_level(),
                         "Expected default LogLevel \"%s\", not \"%s\"" %
                         (mock.default_log_level(), cdesc.default_log_level()))

        self.assertEqual(acomp.jvm_args, cdesc.default_jvm_args(acomp.name),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvm_args,
                          cdesc.default_jvm_args(acomp.name)))
        self.assertEqual(acomp.jvm_extra_args,
                         cdesc.default_jvm_extra_args(acomp.name),
                         "Expected %s default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvm_extra_args,
                          cdesc.default_jvm_extra_args(acomp.name)))
        self.assertEqual(acomp.jvm_heap_init,
                         cdesc.default_jvm_heap_init(acomp.name),
                         "Expected %s default JVMHeapInit \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvm_heap_init,
                          cdesc.default_jvm_heap_init(acomp.name)))
        self.assertEqual(acomp.jvm_heap_max,
                         cdesc.default_jvm_heap_max(acomp.name),
                         "Expected %s default JVMHeapMax \"%s\","
                         " not \"%s\"" %
                         (acomp.name, acomp.jvm_heap_max,
                          cdesc.default_jvm_heap_max(acomp.name)))
        self.assertEqual(acomp.jvm_path, cdesc.default_jvm_path(acomp.name),
                         "Expected %s default JVMPath \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvm_path,
                          cdesc.default_jvm_path(acomp.name)))
        self.assertEqual(acomp.jvm_server,
                         cdesc.default_jvm_server(acomp.name),
                         "Expected %s default JVMServer \"%s\", not \"%s\"" %
                         (acomp.name, acomp.jvm_server,
                          cdesc.default_jvm_server(acomp.name)))
        self.assertEqual(acomp.log_level, cdesc.default_log_level(acomp.name),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (acomp.name, acomp.log_level,
                          cdesc.default_log_level(acomp.name)))

        self.assertEqual(mock.default_jvm_args(),
                         cdesc.default_jvm_args(bcomp.name),
                         "Expected %s default JVMArgs \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_jvm_args(),
                          cdesc.default_jvm_args(bcomp.name)))
        self.assertEqual(mock.default_jvm_extra_args(),
                         cdesc.default_jvm_extra_args(bcomp.name),
                         "Expected %s default JVMExtraArgs \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.default_jvm_extra_args(),
                          cdesc.default_jvm_extra_args(bcomp.name)))
        self.assertEqual(mock.default_jvm_heap_init(),
                         cdesc.default_jvm_heap_init(bcomp.name),
                         "Expected %s default JVM HeapInit \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.default_jvm_heap_init(),
                          cdesc.default_jvm_heap_init(bcomp.name)))
        self.assertEqual(mock.default_jvm_heap_max(),
                         cdesc.default_jvm_heap_max(bcomp.name),
                         "Expected %s default JVM HeapMax \"%s\","
                         " not \"%s\"" %
                         (bcomp.name, mock.default_jvm_heap_max(),
                          cdesc.default_jvm_heap_max(bcomp.name)))
        self.assertEqual(mock.default_jvm_path(),
                         cdesc.default_jvm_path(bcomp.name),
                         "Expected %s default JVMPath \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_jvm_path(),
                          cdesc.default_jvm_path(bcomp.name)))
        self.assertEqual(mock.default_jvm_server(),
                         cdesc.default_jvm_server(bcomp.name),
                         "Expected %s default JVMServer \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_jvm_server(),
                          cdesc.default_jvm_server(bcomp.name)))
        self.assertEqual(mock.default_log_level(),
                         cdesc.default_log_level(bcomp.name),
                         "Expected %s default LogLevel \"%s\", not \"%s\"" %
                         (bcomp.name, mock.default_log_level(),
                          cdesc.default_log_level(bcomp.name)))

    def test_default_inheritance(self):
        name = "compdflts"

        data_dir = "/daq/data"
        log_dir = "/daq/log"
        spade_dir = "/daq/spade"

        dflt_hs_dir = "xxxHSDir"
        dflt_interval = 99.0
        dflt_max_files = 99

        dflt_path = "xxxjvm"
        dflt_heap_init = "2g"
        dflt_heap_max = "8g"
        dflt_server = False
        dflt_args = "jvmArgs"
        dflt_extra = "jvmExtra"

        dflt_loglvl = "logLvl"

        num_fields = 10

        (fld_path, fld_heap_init, fld_heap_max, fld_server, fld_jvmargs,
         fld_extraargs, fld_loglevel, fld_hs_dir, fld_hs_ival, fld_hs_max) = \
         list(range(num_fields))

        for idx in range(num_fields):
            if self.DEBUG:
                print("########## IDX %d" % idx)

            # create a cluster config file
            mock = MockClusterConfigFile(self.cfgdir, name)
            mock.set_data_dir(data_dir)
            mock.set_log_dir(log_dir)
            mock.set_spade_dir(spade_dir)

            # set hitspool defaults
            mock.set_default_hs_directory(dflt_hs_dir)
            mock.set_default_hs_interval(dflt_interval)
            mock.set_default_hs_max_files(dflt_max_files)

            # set JVM defaults
            mock.set_default_jvm_args(dflt_args)
            mock.set_default_jvm_extra_args(dflt_extra)
            mock.set_default_jvm_heap_init(dflt_heap_init)
            mock.set_default_jvm_heap_max(dflt_heap_max)
            mock.set_default_jvm_path(dflt_path)
            mock.set_default_jvm_server(dflt_server)

            # set log level defaults
            mock.set_default_log_level(dflt_loglvl)

            # add host
            hostname = "someHost"
            host = mock.add_host(hostname)

            # temporary values will be used to set up
            # component-specific default values
            (tmp_hs_dir, tmp_ival, tmp_max_f, tmp_path, tmp_heap_init,
             tmp_heap_max, tmp_server, tmp_args, tmp_extra, tmp_loglvl) = \
                (None, ) * num_fields

            # set component-level defaults
            plain_name = "foo"
            if idx == fld_path:
                plain_path = "plainPath"
                tmp_path = plain_path
            else:
                plain_path = dflt_path
            if idx == fld_heap_init:
                plain_heap_init = "1g"
                tmp_heap_init = plain_heap_init
            else:
                plain_heap_init = dflt_heap_init
            if idx == fld_heap_max:
                plain_heap_max = "3g"
                tmp_heap_max = plain_heap_max
            else:
                plain_heap_max = dflt_heap_max
            if idx == fld_server:
                plain_server = not dflt_server
                tmp_server = plain_server
            else:
                plain_server = dflt_server is True
            if idx == fld_jvmargs:
                plain_args = "plainArgs"
                tmp_args = plain_args
            else:
                plain_args = dflt_args
            if idx == fld_extraargs:
                plain_extra = "plainExtra"
                tmp_extra = plain_extra
            else:
                plain_extra = dflt_extra
            if idx == fld_loglevel:
                plain_loglvl = "plainLvl"
                tmp_loglvl = plain_loglvl
            else:
                plain_loglvl = dflt_loglvl
            if idx == fld_hs_dir:
                plain_hs_dir = "plainDir"
                tmp_hs_dir = plain_hs_dir
            else:
                plain_hs_dir = dflt_hs_dir
            if idx == fld_hs_ival:
                plain_ival = dflt_interval + 1.1
                tmp_ival = plain_ival
            else:
                plain_ival = dflt_interval
            if idx == fld_hs_max:
                plain_max_f = dflt_max_files + 1
                tmp_max_f = plain_max_f
            else:
                plain_max_f = dflt_max_files

            # add component-specific default (only one value will be active)
            acomp = MockCluCfgFileComp(plain_name, 0,
                                       hitspool_directory=tmp_hs_dir,
                                       hitspool_interval=tmp_ival,
                                       hitspool_max_files=tmp_max_f,
                                       jvm_path=tmp_path,
                                       jvm_heap_init=tmp_heap_init,
                                       jvm_heap_max=tmp_heap_max,
                                       jvm_server=tmp_server,
                                       jvm_args=tmp_args,
                                       jvm_extra_args=tmp_extra,
                                       log_level=tmp_loglvl)
            mock.add_default_component(acomp)

            # add unaltered component
            _ = host.add_component(plain_name, required=True)

            # add a component which will override a single value
            inst_name = "bar"
            mod_comp = host.add_component(inst_name, required=True)

            jdx = (idx + 1) % num_fields
            if self.DEBUG:
                print("########## JDX %d" % jdx)

            if jdx == fld_path:
                inst_path = "instPath"
                mod_comp.set_jvm_path(inst_path)
            else:
                inst_path = dflt_path
            if jdx == fld_heap_init:
                inst_heap_init = "instInit"
                mod_comp.set_jvm_heap_init(inst_heap_init)
            else:
                inst_heap_init = dflt_heap_init
            if jdx == fld_heap_max:
                inst_heap_max = "instMax"
                mod_comp.set_jvm_heap_max(inst_heap_max)
            else:
                inst_heap_max = dflt_heap_max
            if jdx == fld_server:
                inst_server = not dflt_server
                mod_comp.set_jvm_server(inst_server)
            else:
                inst_server = dflt_server is True
            if jdx == fld_jvmargs:
                inst_args = "instArgs"
                mod_comp.set_jvm_args(inst_args)
            else:
                inst_args = dflt_args
            if jdx == fld_extraargs:
                inst_extra = "instExtra"
                mod_comp.set_jvm_extra_args(inst_extra)
            else:
                inst_extra = dflt_extra
            if jdx == fld_loglevel:
                inst_loglvl = "instLvl"
                mod_comp.set_log_level(inst_loglvl)
            else:
                inst_loglvl = dflt_loglvl
            if jdx == fld_hs_dir:
                inst_hs_dir = "instHSDir"
                mod_comp.set_hitspool_directory(inst_hs_dir)
            else:
                inst_hs_dir = dflt_hs_dir
            if jdx == fld_hs_ival:
                inst_ival = dflt_interval + 2.2
                mod_comp.set_hitspool_interval(inst_ival)
            else:
                inst_ival = dflt_interval
            if jdx == fld_hs_max:
                inst_max_f = dflt_max_files + 2
                mod_comp.set_hitspool_max_files(inst_max_f)
            else:
                inst_max_f = dflt_max_files

            # create file
            mock.create()

            if self.DEBUG:
                with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                    print(":::::::::: %s-cluster.cfg" % name)
                    for line in out:
                        print(":: ", line, end=' ')

            cdesc = ClusterDescription(self.cfgdir, name)

            if self.DEBUG:
                cdesc.dump()

            self.assertEqual(name + "-cluster", cdesc.config_name,
                             "Expected cfgname \"%s-cluster\", not \"%s\"" %
                             (name, cdesc.config_name))

            self.assertEqual(data_dir, cdesc.daq_data_dir,
                             "Expected data dir \"%s\", not \"%s\"" %
                             (data_dir, cdesc.daq_data_dir))
            self.assertEqual(log_dir, cdesc.daq_log_dir,
                             "Expected log dir \"%s\", not \"%s\"" %
                             (log_dir, cdesc.daq_log_dir))
            self.assertEqual(spade_dir, cdesc.log_dir_for_spade,
                             "Expected SPADE dir \"%s\", not \"%s\"" %
                             (spade_dir, cdesc.log_dir_for_spade))

            self.assertEqual(dflt_hs_dir, cdesc.default_hs_directory(),
                             "Expected default HS directory \"%s\","
                             " not \"%s\"" %
                             (dflt_hs_dir, cdesc.default_hs_directory()))
            self.assertEqual(dflt_interval, cdesc.default_hs_interval(),
                             "Expected default HS interval \"%s\","
                             " not \"%s\"" %
                             (dflt_interval, cdesc.default_hs_interval()))
            self.assertEqual(dflt_max_files, cdesc.default_hs_max_files(),
                             "Expected default HS maximum files \"%s\","
                             " not \"%s\"" %
                             (dflt_max_files, cdesc.default_hs_max_files()))

            self.assertEqual(dflt_args, cdesc.default_jvm_args(),
                             "Expected default JVMArgs \"%s\", not \"%s\"" %
                             (dflt_args, cdesc.default_jvm_args()))
            self.assertEqual(dflt_extra, cdesc.default_jvm_extra_args(),
                             "Expected default JVMExtraArgs \"%s\","
                             " not \"%s\"" %
                             (dflt_extra, cdesc.default_jvm_extra_args()))
            self.assertEqual(dflt_heap_init, cdesc.default_jvm_heap_init(),
                             "Expected default JVMHeapInit \"%s\","
                             " not \"%s\"" %
                             (dflt_heap_init, cdesc.default_jvm_heap_init()))
            self.assertEqual(dflt_heap_max, cdesc.default_jvm_heap_max(),
                             "Expected default JVMHeapMax \"%s\", not \"%s\"" %
                             (dflt_heap_max, cdesc.default_jvm_heap_max()))
            self.assertEqual(dflt_path, cdesc.default_jvm_path(),
                             "Expected default JVMPath \"%s\", not \"%s\"" %
                             (dflt_path, cdesc.default_jvm_path()))
            self.assertEqual(dflt_server, cdesc.default_jvm_server(),
                             "Expected default JVMServer \"%s\", not \"%s\"" %
                             (dflt_server, cdesc.default_jvm_server()))

            self.assertEqual(dflt_loglvl, cdesc.default_log_level(),
                             "Expected default LogLevel \"%s\", not \"%s\"" %
                             (dflt_loglvl, cdesc.default_log_level()))

            for comp in cdesc.host(hostname).components:
                if comp.name == plain_name:
                    (hs_dir, hs_ival, hs_max_f, args, extra, heap_init,
                     heap_max, path, server, log_level) \
                     = (plain_hs_dir, plain_ival, plain_max_f, plain_args,
                        plain_extra, plain_heap_init, plain_heap_max,
                        plain_path, plain_server, plain_loglvl)
                else:
                    (hs_dir, hs_ival, hs_max_f, args, extra, heap_init,
                     heap_max, path, server, log_level) \
                     = (inst_hs_dir, inst_ival, inst_max_f, inst_args,
                        inst_extra, inst_heap_init, inst_heap_max, inst_path,
                        inst_server, inst_loglvl)

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
                    self.assertEqual(hs_ival, comp.hitspool_interval,
                                     "Expected %s<%s> HS interval \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hs_ival,
                                      comp.hitspool_interval))
                    self.assertEqual(hs_max_f, comp.hitspool_max_files,
                                     "Expected %s<%s> HS max files \"%s\","
                                     " not \"%s\"" %
                                     (comp.name, type(comp), hs_max_f,
                                      comp.hitspool_max_files))

    def test_components(self):
        name = "comps"

        data_dir = "/daq/data"
        log_dir = "/daq/log"
        spade_dir = "/daq/spade"

        mock_comps = []
        mock = MockClusterConfigFile(self.cfgdir, name)

        mock.set_data_dir(data_dir)
        mock.set_log_dir(log_dir)
        mock.set_spade_dir(spade_dir)

        host1 = mock.add_host("host1")
        mock_comps.append(host1.add_control_server())

        comp_foo = host1.add_component("foo", required=True)
        comp_foo.set_jvm_path("newJVM")
        comp_foo.set_jvm_args("newArgs")
        comp_foo.set_jvm_extra_args("newExtra")
        comp_foo.set_jvm_heap_init("newInit")
        comp_foo.set_jvm_heap_max("newMax")
        comp_foo.set_jvm_server(False)
        comp_foo.set_log_level("logLvl")
        mock_comps.append(comp_foo)

        comp_bar = host1.add_component("bar", 123)
        mock_comps.append(comp_bar)

        num_sim = 15
        prio_sim = 2

        sim = host1.add_sim_hubs(num_sim, prio_sim, if_unused=True)
        mock_comps.append(sim)

        host2 = mock.add_host("host2")
        sim = host2.add_sim_hubs(num_sim, prio_sim)
        mock_comps.append(sim)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                for line in out:
                    print(":: ", line, end=' ')

        cdesc = ClusterDescription(self.cfgdir, name)

        if self.DEBUG:
            cdesc.dump()

        self.assertEqual(mock.data_dir, cdesc.daq_data_dir,
                         "Expected data dir \"%s\", not \"%s\"" %
                         (mock.data_dir, cdesc.daq_data_dir))
        self.assertEqual(mock.log_dir, cdesc.daq_log_dir,
                         "Expected log dir \"%s\", not \"%s\"" %
                         (mock.log_dir, cdesc.daq_log_dir))
        self.assertEqual(mock.spade_dir, cdesc.log_dir_for_spade,
                         "Expected SPADE dir \"%s\", not \"%s\"" %
                         (mock.spade_dir, cdesc.log_dir_for_spade))

        for _, comp in cdesc.host_component_pairs:
            self.__check_comp(comp, mock_comps)
        for _, comp in cdesc.host_sim_hub_pairs:
            self.__check_comp(comp, mock_comps)
            self.assertEqual(num_sim, comp.number,
                             "Expected simHub number %s, not %s" %
                             (num_sim, comp.number))
            self.assertEqual(prio_sim, comp.priority,
                             "Expected simHub priority %s, not %s" %
                             (prio_sim, comp.priority))

    def test_dup_components(self):
        name = "dupcomps"

        mock = MockClusterConfigFile(self.cfgdir, name)

        host = mock.add_host("host1")
        comp = host.add_component("foo")
        host.add_component("foo")

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                for line in out:
                    print(":: ", line, end=' ')

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = ("Multiple entries for component \"%s\""
                      " in host \"%s\"") % (comp.name, host.name)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_multi_host_components(self):
        name = "multihost-comps"

        mock = MockClusterConfigFile(self.cfgdir, name)

        host1 = mock.add_host("host1")
        comp1 = host1.add_component("foo")

        host2 = mock.add_host("host2")
        _ = host2.add_component("foo")

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                for line in out:
                    print(":: ", line, end=' ')

        try:
            ClusterDescription(self.cfgdir, name)
            self.fail("Test %s should not succeed" % name)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "Multiple entries for component \"%s\"" % \
                     comp1.name
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_merged_host_entries(self):
        name = "merged-hosts"

        mock = MockClusterConfigFile(self.cfgdir, name)

        host1 = mock.add_host("host1")
        _ = host1.add_component("foo")

        host2 = mock.add_host("host2")
        _ = host2.add_component("bar")

        host3 = mock.add_host("host1")
        _ = host3.add_component("ney")

        mock.create(split_hosts=True)

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                for line in out:
                    print(":: ", line, end=' ')

        cdesc = ClusterDescription(self.cfgdir, name)

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

    def test_dup_sim_hubs(self):
        """duplicate simHub lines at different priorities are allowed"""
        name = "dupsim"

        mock = MockClusterConfigFile(self.cfgdir, name)

        host = mock.add_host("host1")
        _ = host.add_sim_hubs(15, 2, if_unused=True)
        host.add_sim_hubs(10, 1)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                for line in out:
                    print(":: ", line, end=' ')

        ClusterDescription(self.cfgdir, name)

    def test_add_dup_prio(self):
        """duplicate simHub lines at the same priority are not valid"""
        name = "dupprio"

        mock = MockClusterConfigFile(self.cfgdir, name)

        hname = "host1"
        host = mock.add_host(hname)

        prio = 2
        _ = host.add_sim_hubs(15, prio, if_unused=True)

        mock.create()

        if self.DEBUG:
            with open("%s/%s-cluster.cfg" % (self.cfgdir, name)) as out:
                for line in out:
                    print(":: ", line, end=' ')

        cdesc = ClusterDescription(self.cfgdir, name)
        host = cdesc.host(hname)
        try:
            host.add_simulated_hub(7, prio, False)
        except ClusterDescriptionFormatError as fmterr:
            errmsg = "Multiple <simulatedHub> nodes at prio %d for %s" % \
                     (prio, hname)
            if not str(fmterr).endswith(errmsg):
                self.fail("Expected exception \"%s\", not \"%s\"" %
                          (errmsg, fmterr))

    def test_multi_jvm(self):
        name = "multiJVM"

        hostname = "foo"
        comp_name = "fooComp"
        args = None
        extra = None
        heap_init = "2g"
        heap_max = "4g"
        path = None
        server = False

        clu_path = os.path.join(self.cfgdir, name + "-cluster.cfg")
        with open(clu_path, "w") as out:
            print("<cluster name=\"%s\">" % name, file=out)
            print("  <host name=\"%s\">" % hostname, file=out)
            print("    <component name=\"%s\">" % comp_name, file=out)
            print("      <jvm heapInit=\"xxx\"/>", file=out)
            print("      <jvm heapInit=\"%s\"/>" % heap_init, file=out)
            print("      <jvm heapMax=\"%s\"/>" % heap_max, file=out)
            print("    </component>", file=out)
            print("  </host>", file=out)
            print("</cluster>", file=out)

        cdesc = ClusterDescription(self.cfgdir, name)

        for comp in cdesc.host(hostname).components:
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
